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


logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())


def terminate_subprocess_sync(process: Process):
    try:
        process.terminate()
        logger.info(f"Terminated subprocess {process.pid}")
    except ProcessLookupError:
        pass
    except Exception as exc:
        logger.exception(exc)
        logger.error(f"Error terminating subprocess {process.pid}: {exc}")


def kill_subprocess_sync(process: Process):
    try:
        process.kill()
        logger.warning(f"Killed subprocess {process.pid}")
    except Exception as exc:
        logger.exception(exc)
        logger.error(f"Error killing subprocess {process.pid}: {exc}")


class SubprocessMonitor:
    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        check_interval: float = 2,
    ):
        self.host = host
        self.port = port

        check_interval = max(0.1, check_interval)  # Ensure period is not too small
        self.check_interval = check_interval
        self.process_ownership_lock = asyncio.Lock()
        self.process_ownership: dict[int, Process] = {}

        self.subscription_lock = asyncio.Lock()
        self.subscriptions: defaultdict[int, list[web.WebSocketResponse]] = defaultdict(
            list
        )

        self.app = web.Application()

        self.app.router.add_get("/", self.index)
        self.app.router.add_post("/spawn", self.spawn)
        self.app.router.add_post("/stop", self.stop)
        self.app.router.add_get(
            "/subscribe", self.subscribe_output
        )  # New endpoint for subscriptions

    async def index(self, _) -> TypedJSONResponse[SubProcessIndexResponse]:
        return cast(
            TypedJSONResponse[SubProcessIndexResponse],
            web.json_response(list(self.process_ownership.keys())),
        )

    async def spawn(
        self, req: TypedRequest[SpawnProcessRequest]
    ) -> TypedJSONResponse[SpawnRequestResponse]:
        request = await req.json()
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
            logger.error("Failed to start subprocess: %s", cmd)
            logger.exception(exc)
            return cast(
                TypedJSONResponse[SpawnRequestResponse],
                web.json_response(
                    SpawnRequestFailureResponse(status="failure", error=str(exc))
                ),
            )

    async def stop(
        self, req: TypedRequest[StopProcessRequest]
    ) -> TypedJSONResponse[StopRequestResponse]:
        request: StopProcessRequest = await req.json()
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
            logger.error("Failed to stop subprocess %s", request["pid"])
            logger.exception(exc)
            return cast(
                TypedJSONResponse[StopRequestFailureResponse],
                web.json_response(
                    StopRequestFailureResponse(status="failure", error=str(exc))
                ),
            )

    async def subscribe_output(
        self, request: TypedRequest[Any, SubscribeRequests]
    ) -> web.WebSocketResponse:
        pid = int(request.query.get("pid", -1))

        if pid == -1 or pid not in self.process_ownership:
            return web.HTTPBadRequest(text="Invalid or missing 'pid' parameter.")

        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async with self.subscription_lock:
            self.subscriptions[pid].append(ws)
        logger.info("Client subscribed to subprocess %d output.", pid)

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    # You can handle incoming messages from the client here if needed
                    pass
                elif msg.type == WSMsgType.ERROR:
                    logger.exception(ws.exception())
                    logger.error(
                        "WebSocket connection closed with exception %s", ws.exception()
                    )
        finally:
            async with self.subscription_lock:
                if pid in self.subscriptions and ws in self.subscriptions[pid]:
                    self.subscriptions[pid].remove(ws)
            logger.info("Client unsubscribed from subprocess %d output.", pid)

        return ws

    async def start_subprocess(self, request: SpawnProcessRequest) -> int:
        cmd = request["cmd"]
        args = request["args"]
        env = request.get("env", {})

        logger.info(f"Starting subprocess: {cmd} {args} with environment: {env}")
        full_command = [cmd] + args

        env["SUBPROCESS_MONITOR_PORT"] = str(self.port)
        env["SUBPROCESS_MONITOR_PID"] = str(os.getpid())

        env = {**os.environ, **env}

        process = await asyncio.create_subprocess_exec(
            *full_command,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async with self.process_ownership_lock:
            self.process_ownership[process.pid] = process
        logger.info(
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

            if pid not in self.process_ownership:
                raise ValueError("PID not found")
            if self.process_ownership[pid].pid == pid:
                process = self.process_ownership[pid]

        if process is None:
            raise ValueError("Process not found")

        if pid is None:
            for _pid, _process in self.process_ownership.items():
                if process == _process:
                    pid = _pid
                    break

        if pid is None:
            raise ValueError("PID not found")

        terminate_subprocess_sync(process)

        loop.call_soon_threadsafe(
            asyncio.create_task, self.check_terminated(process, pid)
        )

    async def check_terminated(self, process: Process, pid: int) -> None:
        try:
            await process.wait()
        except Exception:
            pass
        if process.returncode is None:
            kill_subprocess_sync(process)

        async with self.process_ownership_lock:
            del self.process_ownership[pid]

    async def kill_all_subprocesses(self) -> None:
        logger.info("Killing all subprocesses...")
        for pid, process in list(self.process_ownership.items()):
            await self.stop_subprocess(process, pid)

    async def serve(
        self,
    ) -> None:
        _scan_period = self.check_interval
        runner = web.AppRunner(self.app)

        try:
            logger.info("Starting subprocess manager on %s:%d...", self.host, self.port)
            await runner.setup()
            site = web.TCPSite(runner, self.host, self.port)
            await site.start()

            while True:
                await asyncio.sleep(_scan_period)
                await self.check_processes_step()
        except Exception as exc:
            logger.exception(exc)
            raise exc
        finally:
            await runner.cleanup()
            await self.kill_all_subprocesses()

            # Close all WebSocket connections
            async with self.subscription_lock:
                for subs in self.subscriptions.values():
                    for ws in subs:
                        await ws.close()

    async def run(self) -> None:
        try:
            await self.serve()
        finally:
            for pid, process in self.process_ownership.items():
                try:
                    process.kill()
                except Exception:
                    pass

    async def stop_subprocess_request(
        self,
        request: StopProcessRequest,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> bool:
        if loop is None:
            loop = asyncio.get_running_loop()

        logger.info(f"Stopping subprocess with PID {request['pid']}...")

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
        async def read_stream(stream, stream_name):
            while True:
                line = await stream.readline()
                if line:
                    message = json.dumps(
                        StreamingLineOutput(
                            stream=stream_name, pid=pid, data=line.decode().rstrip()
                        )
                    )
                    await self.broadcast_output(pid, message)
                else:
                    break

        await asyncio.gather(
            read_stream(process.stdout, "stdout"), read_stream(process.stderr, "stderr")
        )

    async def check_processes_step(self) -> None:
        """
        Check if any of the subprocesses have terminated and clean up
        """

        for pid, process in list(self.process_ownership.items()):
            try:
                if (
                    psutil.pid_exists(pid)
                    and psutil.Process(pid).status() == psutil.STATUS_RUNNING
                ):
                    continue
            except psutil.NoSuchProcess:
                pass

            logger.info("Process %d is not running (%d)", pid, process.returncode)
            await self.stop_subprocess(process, pid)

        async with self.subscription_lock:
            for pid, subs in list(self.subscriptions.items()):
                if pid not in self.process_ownership:
                    for ws in subs:
                        await ws.close()
                    del self.subscriptions[pid]

    def __await__(self):
        return self.run().__await__()


def run_subprocess_monitor(
    host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, check_interval: float = 2
):
    """
    Run the subprocess monitor service

    host: the host to run the service on
    port: the port to run the service on
    check_interval: the interval to check the subprocesses
    """
    return SubprocessMonitor(host, port, check_interval).run()

    # the index page shows the current status of the subprocesses


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

    if port is None:
        port = int(os.environ.get("SUBPROCESS_MONITOR_PORT", DEFAULT_PORT))

    kwargs["port"] = port
    kwargs["host"] = host
    subprocess_monitor_process = MultiprocessingProcess(
        target=run_subprocess_monitor,
        kwargs=kwargs,
        daemon=True,
    )
    subprocess_monitor_process.start()
    if set_os_environ:
        os.environ["SUBPROCESS_MONITOR_PORT"] = str(port)
        os.environ["SUBPROCESS_MONITOR_PID"] = str(subprocess_monitor_process.pid)

    return subprocess_monitor_process
