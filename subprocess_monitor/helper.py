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


async def send_spawn_request(
    command: str,
    args: Optional[List[str]] = None,
    env: Optional[Dict[str, str]] = None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> SpawnRequestResponse:
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
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> StopRequestResponse:
    req = StopProcessRequest(pid=pid)

    async with ClientSession() as session:
        async with session.post(f"http://{host}:{port}/stop", json=req) as resp:
            response = await cast(TypedClientResponse[StopRequestResponse], resp).json()
            logger.info("Response from server: %s", json.dumps(response, indent=2))
            return response


async def get_status(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> SubProcessIndexResponse:
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
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    callback: Optional[Callable[[StreamingLineOutput], None]] = None,
) -> None:
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


def call_on_manager_death(callback, manager_pid=None, interval=10):
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
