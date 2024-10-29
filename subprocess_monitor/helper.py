from typing import Dict, Optional, List
from aiohttp import ClientSession, WSMsgType
import json
import logging

from .defaults import DEFAULT_HOST, DEFAULT_PORT

logger = logging.getLogger(__name__)


async def send_spawn_request(
    command: str,
    args: Optional[List[str]] = None,
    env: Optional[Dict[str, str]] = None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
):
    if env is None:
        env = {}
    if args is None:
        args = []
    req = {
        "cmd": command,
        "args": args,
        "env": env,
        "pid": None,
    }
    async with ClientSession() as session:
        async with session.post(f"http://{host}:{port}/spawn", json=req) as resp:
            response = await resp.json()
            logger.info(f"Response from server: {json.dumps(response, indent=2)}")
            return response


async def send_stop_request(
    pid: int,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
):
    req = {
        "pid": pid,
    }
    async with ClientSession() as session:
        async with session.post(f"http://{host}:{port}/stop", json=req) as resp:
            response = await resp.json()
            logger.info(f"Response from server: {json.dumps(response, indent=2)}")
            return response


async def get_status(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
):
    async with ClientSession() as session:
        async with session.get(f"http://{host}:{port}/") as resp:
            response = await resp.json()
            logger.info(f"Current subprocess status: {json.dumps(response, indent=2)}")
            return response


def _default_callback(data):
    print(f"[{data['stream'].upper()}] PID {data['pid']}: {data['data']}")


async def subscribe(
    pid: int, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, callback=None
):
    url = f"http://{host}:{port}/subscribe?pid={pid}"
    print(f"Subscribing to output for process with PID {pid}...")
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
                    print(f"Error in WebSocket connection: {ws.exception()}")
                    break

            print(f"WebSocket connection for PID {pid} closed.")
