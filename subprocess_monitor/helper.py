from typing import Dict, Optional, List, cast, Callable
import json
import logging
import os
import time
import threading
import psutil
from aiohttp import ClientSession, WSMsgType
import asyncio
from .defaults import DEFAULT_HOST, DEFAULT_PORT
from .types import (
    SpawnProcessRequest,
    SpawnRequestResponse,
    TypedClientResponse,
    StopProcessRequest,
    StopRequestResponse,
    SubProcessIndexResponse,
    StreamingLineOutput,
)

logger = logging.getLogger(__name__)


class SubprocessMonitorConnectionError(Exception):
    pass


async def send_spawn_request(
    command: str,
    args: Optional[List[str]] = None,
    env: Optional[Dict[str, str]] = None,
    host: Optional[str] = None,
    port: Optional[int] = None,
) -> SpawnRequestResponse:
    if host is None:
        host = os.environ.get("SUBPROCESS_MONITOR_HOST", DEFAULT_HOST)
    if port is None:
        port = int(os.environ.get("SUBPROCESS_MONITOR_PORT", DEFAULT_PORT))

    if env is None:
        env = {}
    if args is None:
        args = []
    req = SpawnProcessRequest(cmd=command, args=args, env=env)

    async with ClientSession() as session:
        async with session.post(f"http://{host}:{port}/spawn", json=req) as resp:
            response = await cast(
                TypedClientResponse[SpawnRequestResponse], resp
            ).json()
            logger.info("Response from server: %s", json.dumps(response, indent=2))
            return response


async def send_stop_request(
    pid: int,
    host: Optional[str] = None,
    port: Optional[int] = None,
) -> StopRequestResponse:
    req = StopProcessRequest(pid=pid)
    if host is None:
        host = os.environ.get("SUBPROCESS_MONITOR_HOST", DEFAULT_HOST)
    if port is None:
        port = int(os.environ.get("SUBPROCESS_MONITOR_PORT", DEFAULT_PORT))

    async with ClientSession() as session:
        async with session.post(f"http://{host}:{port}/stop", json=req) as resp:
            response = await cast(TypedClientResponse[StopRequestResponse], resp).json()
            logger.info("Response from server: %s", json.dumps(response, indent=2))
            return response


async def get_status(
    host: Optional[str] = None,
    port: Optional[int] = None,
) -> SubProcessIndexResponse:
    if host is None:
        host = os.environ.get("SUBPROCESS_MONITOR_HOST", DEFAULT_HOST)
    if port is None:
        port = int(os.environ.get("SUBPROCESS_MONITOR_PORT", DEFAULT_PORT))
    async with ClientSession() as session:
        async with session.get(f"http://{host}:{port}/") as resp:
            response = await cast(
                TypedClientResponse[SubProcessIndexResponse], resp
            ).json()
            logger.info("Current subprocess status: %s", json.dumps(response, indent=2))
            return response


def _default_callback(data: StreamingLineOutput):
    print(f"[{data['stream'].upper()}] PID {data['pid']}: {data['data']}")


async def subscribe(
    pid: int,
    host: Optional[str] = None,
    port: Optional[int] = None,
    callback: Optional[Callable[[StreamingLineOutput], None]] = None,
) -> None:
    if host is None:
        host = os.environ.get("SUBPROCESS_MONITOR_HOST", DEFAULT_HOST)
    if port is None:
        port = int(os.environ.get("SUBPROCESS_MONITOR_PORT", DEFAULT_PORT))
    url = f"http://{host}:{port}/subscribe?pid={pid}"
    logger.info("Subscribing to output for process with PID %d...", pid)
    if callback is None:
        callback = _default_callback

    async with ClientSession() as session:
        async with session.ws_connect(url) as ws:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    # Print received message (process output)
                    data = json.loads(msg.data)
                    callback(data)

                elif msg.type == WSMsgType.ERROR:
                    logger.error("Error in WebSocket connection: %s", ws.exception())
                    break

            logger.info(f"WebSocket connection for PID {pid} closed.")


def call_on_process_death(
    callback: Callable[[], None],
    pid: int,
    interval: float = 10,
    host: Optional[str] = None,
    port: Optional[int] = None,
):
    if host is None:
        host = os.environ.get("SUBPROCESS_MONITOR_HOST", DEFAULT_HOST)
    if port is None:
        port = int(os.environ.get("SUBPROCESS_MONITOR_PORT", DEFAULT_PORT))
    pid = int(pid)

    def call_on_death():
        while True:
            if not psutil.pid_exists(pid):
                callback()
                break
            time.sleep(interval)

    p = threading.Thread(target=call_on_death, daemon=True)
    p.start()


def call_on_manager_death(
    callback: Callable[[], None],
    manager_pid: Optional[int] = None,
    interval: float = 10,
):
    if manager_pid is None:
        manager_pid = os.environ.get("SUBPROCESS_MONITOR_PID")

    if manager_pid is None:
        raise ValueError(
            "manager_pid is not given and cannot be found as env:SUBPROCESS_MONITOR_PID"
        )

    manager_pid = int(manager_pid)

    def call_on_death():
        while True:
            if not psutil.pid_exists(manager_pid):
                callback()
                break
            time.sleep(interval)

    p = threading.Thread(target=call_on_death, daemon=True)
    p.start()
    time.sleep(0.1)
    # check if p is running
    if not p.is_alive():
        raise ValueError("Thread is not running")


def remote_spawn_subprocess(
    command: str,
    args: list[str],
    env: dict[str, str],
    host: Optional[str] = None,
    port: Optional[int] = None,
):
    """
    sends a spwan request to the service

    command: the command to spawn
    args: the arguments of the command
    env: the environment variables
    port: the port that the service is deployed on
    """

    if host is None:
        host = os.environ.get("SUBPROCESS_MONITOR_HOST", DEFAULT_HOST)
    if port is None:
        port = int(os.environ.get("SUBPROCESS_MONITOR_PORT", DEFAULT_PORT))

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
