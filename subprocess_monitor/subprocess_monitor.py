from __future__ import annotations
from typing import Optional, cast, Any
from collections import defaultdict
import asyncio
import logging
import os
import json
from asyncio.subprocess import Process
from multiprocessing import Process as MultiprocessingProcess
import psutil
from aiohttp import web, WSMsgType
import socket
from .defaults import DEFAULT_PORT, DEFAULT_HOST

from .types import (
    SpawnProcessRequest,
    StopProcessRequest,
    TypedJSONResponse,
    TypedRequest,
    SpawnRequestSuccessResponse,
    SpawnRequestFailureResponse,
    SpawnRequestResponse,
    SubProcessIndexResponse,
    StopRequestSuccessResponse,
    StopRequestFailureResponse,
    StopRequestResponse,
    SubscribeRequests,
    StreamingLineOutput,
)
from .validation import (
    safe_validate_spawn_process_request,
    safe_validate_stop_process_request,
    safe_validate_subscribe_requests,
    ValidationError,
)


LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.StreamHandler())


def terminate_subprocess_sync(
    process: Process, logger: Optional[logging.Logger] = None
):
    logger = logger or LOGGER
    try:
        process.terminate()
        logger.info(f"Terminated subprocess {process.pid}")
    except ProcessLookupError:
        pass
    except Exception as exc:
        logger.exception(exc)
        logger.error(f"Error terminating subprocess {process.pid}: {exc}")
    finally:
        close_process_streams(process, logger)


def close_process_streams(process: Process, logger: Optional[logging.Logger] = None):
    """Ensure all process streams are closed to prevent unclosed pipe warnings."""
    logger = logger or LOGGER
    try:
        if process.stdout and not process.stdout.at_eof():
            process.stdout.close()
    except Exception:
        pass
    try:
        if process.stderr and not process.stderr.at_eof():
            process.stderr.close()
    except Exception:
        pass

    try:
        if process.stdin:
            process.stdin.close()
    except Exception:
        pass

    process._transport.close()


def kill_subprocess_sync(process: Process, logger: Optional[logging.Logger] = None):
    logger = logger or LOGGER
    try:
        process.kill()
        logger.warning(f"Killed subprocess {process.pid}")
    except Exception as exc:
        logger.exception(exc)
        logger.error(f"Error killing subprocess {process.pid}: {exc}")
    finally:
        close_process_streams(process, logger)


def find_free_port(start_port: int = DEFAULT_PORT, end_port: int = 65535) -> int:
    """
    Find a free port in the given range.

    WARNING: This function has a race condition (TOCTOU) - port may be taken
    between check and use. Use bind_to_free_port() instead for secure binding.

    start_port: the start port to search from
    end_port: the end port to search to
    """

    for port in range(start_port, end_port + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("localhost", port))  # Try to bind to the port
        except OSError:
            continue
        return port
    raise ValueError("No free ports available")


def bind_to_free_port(
    host: str = "localhost", start_port: int = DEFAULT_PORT, end_port: int = 65535
) -> tuple[int, socket.socket]:
    """
    Bind to a free port and return both the port number and the bound socket.

    This eliminates the race condition by keeping the socket bound until
    the server can take over.

    Returns:
        tuple: (port_number, bound_socket)
    """
    for port in range(start_port, end_port + 1):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # DO NOT set SO_REUSEADDR - it allows multiple binds to same port
            sock.bind((host, port))
            return port, sock
        except OSError:
            try:
                sock.close()
            except Exception:
                pass
            continue
    raise ValueError("No free ports available")


def set_os_env_vars(
    port: int,
    host: str = DEFAULT_HOST,
    pid: Optional[int] = None,
    env: Optional[dict] = None,
) -> None:
    """
    Set the environment variables for the subprocess monitor

    port: the port to set
    host: the host to set
    pid: the PID to set
    env: the environment to set the variables in (default: os.environ)
    """
    if env is None:
        env = os.environ
    if pid is None:
        pid = os.getpid()

    env["SUBPROCESS_MONITOR_PORT"] = str(port)
    env["SUBPROCESS_MONITOR_HOST"] = host
    env["SUBPROCESS_MONITOR_PID"] = str(pid)


class SubprocessMonitor:
    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: Optional[int] = None,
        check_interval: float = 2,
        logger: Optional[logging.Logger] = None,
    ):
        self.host = host
        self.logger = logger or LOGGER
        check_interval = max(0.1, check_interval)  # Ensure period is not too small
        self.check_interval = check_interval
        self.process_ownership_lock = asyncio.Lock()
        self.process_ownership: dict[int, Process] = {}

        self.subscription_lock = asyncio.Lock()
        self.subscriptions: defaultdict[int, list[web.WebSocketResponse]] = defaultdict(
            list
        )

        self.app = web.Application()
        self._running = False
        self._bound_socket = None

        # Handle port binding securely to prevent race conditions
        if port is not None:
            # Use specified port
            self.port = port
        else:
            # Use secure port binding to prevent TOCTOU race condition
            self.port, self._bound_socket = bind_to_free_port(host)

        self.app.router.add_get("/", self.index)
        self.app.router.add_post("/spawn", self.spawn)
        self.app.router.add_post("/stop", self.stop)
        self.app.router.add_get(
            "/subscribe", self.subscribe_output
        )  # New endpoint for subscriptions  # New endpoint for subscriptions

    async def index(self, _) -> TypedJSONResponse[SubProcessIndexResponse]:
        return cast(
            TypedJSONResponse[SubProcessIndexResponse],
            web.json_response(list(self.process_ownership.keys())),
        )

    async def spawn(
        self, req: TypedRequest[SpawnProcessRequest]
    ) -> TypedJSONResponse[SpawnRequestResponse]:
        try:
            raw_request = await req.json()
            request = safe_validate_spawn_process_request(raw_request)
        except ValidationError as exc:
            self.logger.error("Invalid spawn request: %s", exc)
            return cast(
                TypedJSONResponse[SpawnRequestResponse],
                web.json_response(
                    SpawnRequestFailureResponse(
                        status="failure", error=f"Invalid request: {exc}"
                    )
                ),
            )
        except Exception as exc:
            self.logger.error("Failed to parse spawn request: %s", exc)
            return cast(
                TypedJSONResponse[SpawnRequestResponse],
                web.json_response(
                    SpawnRequestFailureResponse(
                        status="failure", error="Invalid JSON request"
                    )
                ),
            )

        # to avoid thread safety issues as the web framework used here is not mandatory
        try:
            subprocess_pid = await self.start_subprocess(request)
            return cast(
                TypedJSONResponse[SpawnRequestResponse],
                web.json_response(
                    SpawnRequestSuccessResponse(status="success", pid=subprocess_pid)
                ),
            )
        except Exception as exc:
            cmd = " ".join([request["cmd"], *request["args"]])
            self.logger.error("Failed to start subprocess: %s", cmd)
            self.logger.exception(exc)
            return cast(
                TypedJSONResponse[SpawnRequestResponse],
                web.json_response(
                    SpawnRequestFailureResponse(status="failure", error=str(exc))
                ),
            )

    async def stop(
        self, req: TypedRequest[StopProcessRequest]
    ) -> TypedJSONResponse[StopRequestResponse]:
        try:
            raw_request = await req.json()
            request = safe_validate_stop_process_request(raw_request)
        except ValidationError as exc:
            self.logger.error("Invalid stop request: %s", exc)
            return cast(
                TypedJSONResponse[StopRequestResponse],
                web.json_response(
                    StopRequestFailureResponse(
                        status="failure", error=f"Invalid request: {exc}"
                    )
                ),
            )
        except Exception as exc:
            self.logger.error("Failed to parse stop request: %s", exc)
            return cast(
                TypedJSONResponse[StopRequestResponse],
                web.json_response(
                    StopRequestFailureResponse(
                        status="failure", error="Invalid JSON request"
                    )
                ),
            )

        try:
            found = await self.stop_subprocess_request(
                request, asyncio.get_running_loop()
            )
            if found:
                return cast(
                    TypedJSONResponse[StopRequestSuccessResponse],
                    web.json_response(StopRequestSuccessResponse(status="success")),
                )
            else:
                return cast(
                    TypedJSONResponse[StopRequestFailureResponse],
                    web.json_response(
                        StopRequestFailureResponse(
                            status="failure", error="PID not found"
                        )
                    ),
                )
        except Exception as exc:
            self.logger.error("Failed to stop subprocess %s", request["pid"])
            self.logger.exception(exc)
            return cast(
                TypedJSONResponse[StopRequestFailureResponse],
                web.json_response(
                    StopRequestFailureResponse(status="failure", error=str(exc))
                ),
            )

    async def subscribe_output(
        self, request: TypedRequest[Any, SubscribeRequests]
    ) -> web.WebSocketResponse:
        try:
            query_data = {"pid": request.query.get("pid", "")}
            validated_query = safe_validate_subscribe_requests(query_data)
            pid = int(validated_query["pid"])
        except (ValidationError, ValueError) as exc:
            self.logger.error("Invalid subscribe request: %s", exc)
            return web.HTTPBadRequest(text=f"Invalid 'pid' parameter: {exc}")

        if pid not in self.process_ownership:
            return web.HTTPBadRequest(text="PID not found in managed processes.")

        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async with self.subscription_lock:
            self.subscriptions[pid].append(ws)
        self.logger.info("Client subscribed to subprocess %d output.", pid)

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    # You can handle incoming messages from the client here if needed
                    pass
                elif msg.type == WSMsgType.ERROR:
                    self.logger.exception(ws.exception())
                    self.logger.error(
                        "WebSocket connection closed with exception %s", ws.exception()
                    )
        finally:
            async with self.subscription_lock:
                if pid in self.subscriptions and ws in self.subscriptions[pid]:
                    self.subscriptions[pid].remove(ws)
            self.logger.info("Client unsubscribed from subprocess %d output.", pid)

        return ws

    async def start_subprocess(self, request: SpawnProcessRequest) -> int:
        cmd = request["cmd"]
        args = request["args"]
        env = request.get("env", {})

        self.logger.info(f"Starting subprocess: {cmd} {args} with environment: {env}")
        full_command = [cmd] + args

        set_os_env_vars(self.port, self.host, env=env)

        env = {**os.environ, **env}

        process = await asyncio.create_subprocess_exec(
            *full_command,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async with self.process_ownership_lock:
            self.process_ownership[process.pid] = process
        self.logger.info(
            "Started subprocess: %s %s with PID %d", cmd, " ".join(args), process.pid
        )
        # Start tasks to read stdout and stderr
        asyncio.create_task(self.stream_subprocess_output(process.pid, process))
        return process.pid

    async def stop_subprocess(
        self,
        process: Optional[Process] = None,
        pid: Optional[int] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        if loop is None:
            loop = asyncio.get_running_loop()

        if process is None:
            if pid is None:
                raise ValueError("Either process or pid must be provided")

            # Use lock to safely access process_ownership
            async with self.process_ownership_lock:
                if pid not in self.process_ownership:
                    raise ValueError("PID not found")
                process = self.process_ownership[pid]

        if process is None:
            raise ValueError("Process not found")

        if pid is None:
            # Use lock to safely search for pid
            async with self.process_ownership_lock:
                for _pid, _process in self.process_ownership.items():
                    if process == _process:
                        pid = _pid
                        break

        if pid is None:
            raise ValueError("PID not found")

        terminate_subprocess_sync(process, self.logger)

        # Clean up WebSocket subscriptions immediately
        async with self.subscription_lock:
            if pid in self.subscriptions:
                for ws in self.subscriptions[pid]:
                    try:
                        await ws.close()
                    except Exception as e:
                        self.logger.warning(f"Error closing WebSocket: {e}")
                del self.subscriptions[pid]

        loop.call_soon_threadsafe(
            asyncio.create_task, self.check_terminated(process, pid)
        )

    async def check_terminated(
        self, process: Process, pid: int, max_retries: int = 3
    ) -> None:
        """
        Check if process has terminated and clean up.

        Args:
            process: The process to check
            pid: Process ID
            max_retries: Maximum recursion attempts to prevent infinite loops
        """
        # Check if process still exists in our tracking
        async with self.process_ownership_lock:
            if pid not in self.process_ownership:
                return

        try:
            await asyncio.wait_for(process.wait(), timeout=10)
        except Exception:
            pass

        # If process still hasn't terminated and we have retries left
        if process.returncode is None and max_retries > 0:
            kill_subprocess_sync(process, self.logger)
            # Wait a bit before recursing to allow process to actually terminate
            await asyncio.sleep(0.1)
            return await self.check_terminated(process, pid, max_retries - 1)

        # If process still hasn't terminated after max retries, log warning
        if process.returncode is None:
            self.logger.warning(
                f"Process {pid} could not be terminated after {3} attempts"
            )
            # Force set returncode to prevent further attempts
            process.returncode = -1

        # Clean up from process ownership
        async with self.process_ownership_lock:
            if pid in self.process_ownership:
                del self.process_ownership[pid]

    async def kill_all_subprocesses(self) -> None:
        self.logger.info("Killing all subprocesses...")
        for pid, process in list(self.process_ownership.items()):
            await self.stop_subprocess(process, pid)

    async def serve(
        self,
    ) -> None:
        _scan_period = self.check_interval
        runner = web.AppRunner(self.app)

        self._running = True
        o_SUBPROCESS_MONITOR_PORT = os.getenv("SUBPROCESS_MONITOR_PORT")
        o_SUBPROCESS_MONITOR_PID = os.getenv("SUBPROCESS_MONITOR_PID")
        o_SUBPROCESS_MONITOR_HOST = os.getenv("SUBPROCESS_MONITOR_HOST")
        try:
            self.logger.info(
                "Starting subprocess manager on %s:%d...", self.host, self.port
            )
            await runner.setup()

            # Use pre-bound socket if available (prevents race condition)
            if self._bound_socket is not None:
                # Extract port from bound socket and close it
                # Then create TCPSite - this approach works cross-platform
                # Small race window but much better than original find_free_port()
                bound_port = self._bound_socket.getsockname()[1]
                self._bound_socket.close()
                self._bound_socket = None
                site = web.TCPSite(runner, self.host, bound_port)
            else:
                # Fallback to regular TCP site (when port was specified)
                site = web.TCPSite(runner, self.host, self.port)

            await site.start()

            set_os_env_vars(self.port, self.host)

            while self._running:
                await asyncio.sleep(_scan_period)
                await self.check_processes_step()
        except Exception as exc:
            self.logger.exception(exc)
            raise exc
        finally:
            await self.kill_all_subprocesses()
            # Close all WebSocket connections
            async with self.subscription_lock:
                for subs in self.subscriptions.values():
                    for ws in subs:
                        await ws.close()

            # Clean up bound socket if it wasn't used
            if self._bound_socket is not None:
                try:
                    self._bound_socket.close()
                except Exception:
                    pass
                self._bound_socket = None

            if o_SUBPROCESS_MONITOR_PORT is not None:
                os.environ["SUBPROCESS_MONITOR_PORT"] = o_SUBPROCESS_MONITOR_PORT
            else:
                os.environ.pop("SUBPROCESS_MONITOR_PORT", None)
            if o_SUBPROCESS_MONITOR_PID is not None:
                os.environ["SUBPROCESS_MONITOR_PID"] = o_SUBPROCESS_MONITOR_PID
            else:
                os.environ.pop("SUBPROCESS_MONITOR_PID", None)
            if o_SUBPROCESS_MONITOR_HOST is not None:
                os.environ["SUBPROCESS_MONITOR_HOST"] = o_SUBPROCESS_MONITOR_HOST
            else:
                os.environ.pop("SUBPROCESS_MONITOR_HOST", None)
            await runner.cleanup()

    async def run(self) -> None:
        self._running = True
        try:
            await self.serve()
        finally:
            for pid, process in self.process_ownership.items():
                try:
                    process.kill()
                except Exception:
                    pass

    def stop_serve(self) -> None:
        self._running = False

    async def stop_subprocess_request(
        self,
        request: StopProcessRequest,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> bool:
        if loop is None:
            loop = asyncio.get_running_loop()

        self.logger.info(f"Stopping subprocess with PID {request['pid']}...")

        pid = request["pid"]
        if pid not in self.process_ownership:
            return False
        else:
            if self.process_ownership[pid].pid == pid:
                await self.stop_subprocess(self.process_ownership[pid], pid, loop)
                return True
        return False

    async def broadcast_output(self, pid: int, message: str) -> None:
        subscribers = self.subscriptions.get(pid, [])
        if not subscribers:
            return
        await asyncio.gather(
            *[ws.send_str(message) for ws in subscribers if not ws.closed],
            return_exceptions=True,
        )

    async def stream_subprocess_output(self, pid: int, process: Process) -> None:
        async def read_stream(stream: asyncio.StreamReader, stream_name):
            while True:
                try:
                    # Read a line from the stream with a timeout
                    line = await asyncio.wait_for(stream.readline(), timeout=5)
                except asyncio.TimeoutError:
                    # Check if the subprocess has exited on timeout
                    if process.returncode is not None:
                        # Process has exited, read any remaining data and then break
                        try:
                            # Try to read any remaining buffered data
                            remaining_data = await asyncio.wait_for(
                                stream.read(), timeout=0.1
                            )
                            if remaining_data:
                                self.logger.debug(
                                    f"last lines of {pid} {stream_name}: {remaining_data.decode().rstrip()}"
                                )
                                message = json.dumps(
                                    StreamingLineOutput(
                                        stream=stream_name,
                                        pid=pid,
                                        data=remaining_data.decode().rstrip(),
                                    )
                                )
                                await self.broadcast_output(pid, message)
                        except (asyncio.TimeoutError, ValueError):
                            pass
                        break
                    continue  # Retry on timeout if process is still running
                except ValueError:
                    break  # Stream is closed, exit the loop

                if line:  # If line is not empty, process it
                    message = json.dumps(
                        StreamingLineOutput(
                            stream=stream_name, pid=pid, data=line.decode().rstrip()
                        )
                    )
                    await self.broadcast_output(pid, message)
                else:
                    # EOF reached - check if process has exited and read any remaining data
                    if process.returncode is not None:
                        try:
                            # Try to read any remaining buffered data one more time
                            remaining_data = await asyncio.wait_for(
                                stream.read(), timeout=0.1
                            )
                            if remaining_data:
                                message = json.dumps(
                                    StreamingLineOutput(
                                        stream=stream_name,
                                        pid=pid,
                                        data=remaining_data.decode().rstrip(),
                                    )
                                )
                                await self.broadcast_output(pid, message)
                        except (asyncio.TimeoutError, ValueError):
                            pass
                    break  # EOF reached, exit the loop

        await asyncio.gather(
            read_stream(process.stdout, "stdout"), read_stream(process.stderr, "stderr")
        )

    async def check_processes_step(self) -> None:
        """
        Check if any of the subprocesses have terminated and clean up
        """
        # Fix: Use proper locking to prevent race conditions
        async with self.process_ownership_lock:
            # Create a copy of the items to avoid "dictionary changed size during iteration"
            process_items = list(self.process_ownership.items())

        for pid, process in process_items:
            try:
                # Check if the process object itself has terminated
                if process.returncode is None:
                    # Process hasn't terminated yet, keep it
                    continue

                # Process has terminated, clean it up
                self.logger.info(
                    "Process %d has terminated with return code %d",
                    pid,
                    process.returncode,
                )
                # self.logger.debug(
                # f"last lines of {pid} stdout: "
                # f"{(await process.stdout.read())[-200:]},stderr: {(await process.stderr.read())[-200:]}"
                # )
                await self.stop_subprocess(process, pid)

            except Exception as e:
                # If there's any error checking process status, log it but don't cleanup
                self.logger.warning(f"Error checking process {pid} status: {e}")
                # Only cleanup if we can confirm the process is actually dead
                try:
                    if not psutil.pid_exists(pid):
                        self.logger.info(f"Process {pid} no longer exists, cleaning up")
                        await self.stop_subprocess(process, pid)
                except Exception:
                    # If we can't even check if PID exists, leave it alone
                    pass

        # Clean up WebSocket subscriptions for terminated processes
        async with self.subscription_lock:
            # Create a copy to avoid race condition
            subscription_items = list(self.subscriptions.items())

        for pid, subs in subscription_items:
            # Check if process still exists under lock
            async with self.process_ownership_lock:
                process_exists = pid in self.process_ownership

            if not process_exists:
                async with self.subscription_lock:
                    # Double-check inside lock to prevent race condition
                    if pid in self.subscriptions:
                        for ws in self.subscriptions[pid]:
                            try:
                                await ws.close()
                            except Exception as e:
                                self.logger.warning(f"Error closing WebSocket: {e}")
                        del self.subscriptions[pid]

    def __await__(self):
        return self.run().__await__()


async def run_subprocess_monitor(
    host: str = DEFAULT_HOST, port: Optional[int] = None, check_interval: float = 2
):
    """
    Run the subprocess monitor service

    host: the host to run the service on
    port: the port to run the service on
    check_interval: the interval to check the subprocesses
    """

    return await SubprocessMonitor(
        host=host, port=port, check_interval=check_interval
    ).run()

    # the index page shows the current status of the subprocesses


def sync_run_subprocess_monitor(
    host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, check_interval: float = 2
):
    """
    Run the subprocess monitor service synchronously

    host: the host to run the service on
    port: the port to run the service on
    check_interval: the interval to check the subprocesses
    """

    asyncio.run(run_subprocess_monitor(host, port, check_interval))


def create_subprocess_monitor_thread(
    host: str = DEFAULT_HOST,
    port: Optional[int] = None,
    set_os_environ: bool = True,
    **kwargs,
):
    """
    Create a subprocess monitor thread

    host: the host to run the service on
    port: the port to run the service on
    set_os_environ: set the SUBPROCESS_MONITOR_PORT and SUBPROCESS_MONITOR_PID environment variables
    kwargs: additional arguments to pass to the subprocess monitor
    """

    kwargs["port"] = port or find_free_port()
    kwargs["host"] = host
    subprocess_monitor_process = MultiprocessingProcess(
        target=sync_run_subprocess_monitor,
        kwargs=kwargs,
        daemon=True,
    )
    subprocess_monitor_process.start()
    if set_os_environ:
        set_os_env_vars(
            kwargs["port"],
            host,
            pid=subprocess_monitor_process.pid,
        )

    return subprocess_monitor_process
