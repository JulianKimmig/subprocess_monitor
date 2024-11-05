from typing import Optional, TypedDict
from aiohttp import web, WSMsgType, ClientSession
from collections import defaultdict
import asyncio
import logging
import os
import json
from asyncio.subprocess import Process
import psutil
from .defaults import DEFAULT_PORT, DEFAULT_HOST


logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())

PROCESS_OWNERSHIP: dict[int, Process] = {}
SUBSCRIPTIONS: defaultdict[int, list[web.WebSocketResponse]] = defaultdict(list)
PROCESS_OWNERSHIP_LOCK = asyncio.Lock()
SUBSCRIPTIONS_LOCK = asyncio.Lock()


class SpawnProcessRequest(TypedDict):
    cmd: str
    args: list[str]
    env: dict[str, str]


class StopProcessRequest(TypedDict):
    pid: int


async def check_processes_step():
    for pid, process in list(PROCESS_OWNERSHIP.items()):
        try:
            if (
                psutil.pid_exists(pid)
                and psutil.Process(pid).status() == psutil.STATUS_RUNNING
            ):
                continue
        except psutil.NoSuchProcess:
            pass

        logger.info(f"Process {pid} is not running ({process.returncode})")
        await stop_subprocess(process, pid)

    async with SUBSCRIPTIONS_LOCK:
        for pid, subs in list(SUBSCRIPTIONS.items()):
            if pid not in PROCESS_OWNERSHIP:
                for ws in subs:
                    await ws.close()
                del SUBSCRIPTIONS[pid]


async def run_subprocess_monitor(
    host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, check_interval: float = 2
):
    check_interval = max(0.1, check_interval)  # Ensure period is not too small
    app = web.Application()
    logger.info(f"Starting subprocess monitor on {host}:{port}...")

    # the index page shows the current status of the subprocesses
    async def index(req):
        return web.json_response(list(PROCESS_OWNERSHIP.keys()))

    async def spawn(req: web.Request):
        request: SpawnProcessRequest = await req.json()
        # to avoid thread safety issues as the web framework used here is not mandatory
        try:
            subprocess_pid = await start_subprocess(request, port)
            return web.json_response({"code": "success", "pid": subprocess_pid})
        except Exception as exc:
            cmd = " ".join([request["cmd"], *request["args"]])
            logger.error(f"Failed to start subprocess: {cmd}")
            logger.exception(exc)
            return web.json_response({"code": "failure", "error": str(exc)})

    async def stop(req: web.Request):
        request: StopProcessRequest = await req.json()
        try:
            found = await stop_subprocess_request(request, asyncio.get_running_loop())
            return web.json_response({"code": "success" if found else "failure"})
        except Exception as exc:
            logger.error(f"Failed to stop subprocess {request['pid']}")
            logger.exception(exc)
            return web.json_response({"code": "failure", "error": str(exc)})

    app.router.add_get("/", index)
    app.router.add_post("/spawn", spawn)
    app.router.add_post("/stop", stop)
    app.router.add_get("/subscribe", subscribe_output)  # New endpoint for subscriptions

    async def serve():
        _scan_period = check_interval
        runner = web.AppRunner(app)

        try:
            logger.info(f"Starting subprocess manager on {host}:{port}...")
            await runner.setup()
            site = web.TCPSite(runner, host, port)
            await site.start()

            while True:
                await asyncio.sleep(_scan_period)
                await check_processes_step()
        except Exception as exc:
            logger.exception(exc)
            raise exc
        finally:
            await runner.cleanup()
            await kill_all_subprocesses()

            # Close all WebSocket connections
            async with SUBSCRIPTIONS_LOCK:
                for subs in SUBSCRIPTIONS.values():
                    for ws in subs:
                        await ws.close()

    try:
        await serve()
    finally:
        for pid, process in PROCESS_OWNERSHIP.items():
            try:
                process.kill()
            except Exception:
                pass


async def subscribe_output(request: web.Request):
    pid = int(request.query.get("pid", -1))
    if pid == -1 or pid not in PROCESS_OWNERSHIP:
        return web.HTTPBadRequest(text="Invalid or missing 'pid' parameter.")

    ws = web.WebSocketResponse()
    await ws.prepare(request)
    async with SUBSCRIPTIONS_LOCK:
        SUBSCRIPTIONS[pid].append(ws)
    logger.info(f"Client subscribed to subprocess {pid} output.")

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                # You can handle incoming messages from the client here if needed
                pass
            elif msg.type == WSMsgType.ERROR:
                logger.exception(ws.exception())
                logger.error(
                    f"WebSocket connection closed with exception {ws.exception()}"
                )
    finally:
        async with SUBSCRIPTIONS_LOCK:
            if pid in SUBSCRIPTIONS and ws in SUBSCRIPTIONS[pid]:
                SUBSCRIPTIONS[pid].remove(ws)
        logger.info(f"Client unsubscribed from subprocess {pid} output.")

    return ws


def remote_spawn_subprocess(
    command: str,
    args: list[str],
    env: dict[str, str],
    host=DEFAULT_HOST,
    port: int = DEFAULT_PORT,
):
    """
    sends a spwan request to the service

    command: the command to spawn
    args: the arguments of the command
    env: the environment variables
    port: the port that the service is deployed on
    """

    async def send_request():
        req = SpawnProcessRequest(cmd=command, args=args, env=env)
        logger.info(f"Sending request to spawn subprocess: {json.dumps(req, indent=2)}")
        async with ClientSession() as session:
            async with session.post(
                f"http://{host}:{port}/spawn",
                json=req,
            ) as resp:
                ans = await resp.json()
                logger.info(json.dumps(ans, indent=2, ensure_ascii=True))
                return ans

    return asyncio.run(send_request())


async def kill_all_subprocesses():
    logger.info("Killing all subprocesses...")
    for pid, process in list(PROCESS_OWNERSHIP.items()):
        await stop_subprocess(process, pid)


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


async def stop_subprocess(
    process: Optional[Process] = None,
    pid: Optional[int] = None,
    loop: Optional[asyncio.AbstractEventLoop] = None,
):
    if loop is None:
        loop = asyncio.get_running_loop()
    if process is None:
        if pid is None:
            raise ValueError("Either process or pid must be provided")

        if pid not in PROCESS_OWNERSHIP:
            raise ValueError("PID not found")
        if PROCESS_OWNERSHIP[pid].pid == pid:
            process = PROCESS_OWNERSHIP[pid]

    if process is None:
        raise ValueError("Process not found")

    if pid is None:
        for _pid, process in PROCESS_OWNERSHIP.items():
            if process == process:
                pid = _pid
                break

    if pid is None:
        raise ValueError("PID not found")

    terminate_subprocess_sync(process)

    async def check_terminated(p: Process, pid):
        try:
            await p.wait()
        except Exception:
            pass
        if p.returncode is None:
            kill_subprocess_sync(p)

        async with PROCESS_OWNERSHIP_LOCK:
            del PROCESS_OWNERSHIP[pid]

    loop.call_soon_threadsafe(asyncio.create_task, check_terminated(process, pid))


async def stop_subprocess_request(
    request: StopProcessRequest, loop: Optional[asyncio.AbstractEventLoop] = None
):
    if loop is None:
        loop = asyncio.get_running_loop()

    logger.info(f"Stopping subprocess with PID {request['pid']}...")

    pid = request["pid"]
    if pid not in PROCESS_OWNERSHIP:
        return False
    else:
        if PROCESS_OWNERSHIP[pid].pid == pid:
            await stop_subprocess(PROCESS_OWNERSHIP[pid], pid, loop)
            return True
    return False


async def broadcast_output(pid: int, message: str):
    subscribers = SUBSCRIPTIONS.get(pid, [])
    await asyncio.gather(*[ws.send_str(message) for ws in subscribers if not ws.closed])


async def stream_subprocess_output(pid: int, process: Process):
    async def read_stream(stream, stream_name):
        while True:
            line = await stream.readline()
            if line:
                message = json.dumps(
                    {
                        "pid": process.pid,
                        "stream": stream_name,
                        "data": line.decode().rstrip(),
                    }
                )
                await broadcast_output(pid, message)
            else:
                break

    await asyncio.gather(
        read_stream(process.stdout, "stdout"), read_stream(process.stderr, "stderr")
    )


async def start_subprocess(request: SpawnProcessRequest, port: int):
    cmd = request["cmd"]
    args = request["args"]
    env = request.get("env", {})

    logger.info(f"Starting subprocess: {cmd} {args} with environment: {env}")
    full_command = [cmd] + args

    env["SUBPROCESS_MONITOR_PORT"] = str(port)
    env["SUBPROCESS_MONITOR_PID"] = str(os.getpid())

    env = {**os.environ, **env}

    process = await asyncio.create_subprocess_exec(
        *full_command,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async with PROCESS_OWNERSHIP_LOCK:
        PROCESS_OWNERSHIP[process.pid] = process
    logger.info(f"Started subprocess: {cmd} {' '.join(args)} with PID {process.pid}")
    # Start tasks to read stdout and stderr
    asyncio.create_task(stream_subprocess_output(process.pid, process))
    return process.pid
