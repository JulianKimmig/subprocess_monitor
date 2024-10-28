from aiohttp import ClientSession, WSMsgType
import json
import logging

logger = logging.getLogger(__name__)


async def send_spawn_request(command, args, env, port):
    req = {
        "cmd": command,
        "args": args,
        "env": env,
        "pid": None,
    }
    async with ClientSession() as session:
        async with session.post(f"http://localhost:{port}/spawn", json=req) as resp:
            response = await resp.json()
            logger.info(f"Response from server: {json.dumps(response, indent=2)}")
            return response


async def send_stop_request(pid, port):
    req = {
        "pid": pid,
    }
    async with ClientSession() as session:
        async with session.post(f"http://localhost:{port}/stop", json=req) as resp:
            response = await resp.json()
            logger.info(f"Response from server: {json.dumps(response, indent=2)}")
            return response


async def get_status(port):
    async with ClientSession() as session:
        async with session.get(f"http://localhost:{port}/") as resp:
            response = await resp.json()
            logger.info(f"Current subprocess status: {json.dumps(response, indent=2)}")
            return response


async def subscribe(pid: int, port: int, callback=None):
    url = f"http://localhost:{port}/subscribe?pid={pid}"
    print(f"Subscribing to output for process with PID {pid}...")
    if callback is None:
        callback = lambda data: print(
            f"[{data['stream'].upper()}] PID {data['pid']}: {data['data']}"
        )

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
