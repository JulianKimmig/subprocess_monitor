import argparse
import asyncio
import json
import logging
import os
from aiohttp import ClientSession, WSMsgType
from subprocess_monitor import run_subprocess_monitor

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


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


async def subscribe(pid: int, port: int):
    url = f"http://localhost:{port}/subscribe?pid={pid}"
    print(f"Subscribing to output for process with PID {pid}...")

    async with ClientSession() as session:
        async with session.ws_connect(url) as ws:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    # Print received message (process output)
                    data = json.loads(msg.data)
                    print(
                        f"[{data['stream'].upper()}] PID {data['pid']}: {data['data']}"
                    )
                elif msg.type == WSMsgType.ERROR:
                    print(f"Error in WebSocket connection: {ws.exception()}")
                    break

            print(f"WebSocket connection for PID {pid} closed.")


def main():
    parser = argparse.ArgumentParser(
        description="CLI for managing subprocesses using an async subprocess manager."
    )
    subparsers = parser.add_subparsers(dest="command")

    # Command to start the subprocess manager server
    parser_start = subparsers.add_parser(
        "start", help="Start the subprocess manager server."
    )
    parser_start.add_argument(
        "--port", type=int, default=5057, help="Port to run the subprocess manager on."
    )
    parser_start.add_argument(
        "--check_interval",
        type=float,
        default=2,
        help="Time period for checking subprocess status.",
    )

    # Command to spawn a new subprocess

    parser_spawn = subparsers.add_parser("spawn", help="Spawn a new subprocess.")
    parser_spawn.add_argument("cmd", help="The command to spawn.")
    parser_spawn.add_argument(
        "cmd_args", nargs=argparse.REMAINDER, help="Arguments for the command to spawn."
    )
    parser_spawn.add_argument(
        "--env",
        nargs="*",
        help="Environment variables for the command (key=value format).",
    )
    parser_spawn.add_argument(
        "--port", type=int, default=5057, help="Port to communicate with the server."
    )

    # Command to stop a subprocess
    parser_stop = subparsers.add_parser("stop", help="Stop a subprocess.")
    parser_stop.add_argument("pid", type=int, help="Process ID.")
    parser_stop.add_argument(
        "--port", type=int, default=5057, help="Port to communicate with the server."
    )

    # Command to check status of subprocesses
    parser_status = subparsers.add_parser("status", help="Check subprocess status.")
    parser_status.add_argument(
        "--port", type=int, default=5057, help="Port to communicate with the server."
    )

    # Command to subscribe to a topic
    parser_subscribe = subparsers.add_parser(
        "subscribe", help="Subscribe to a process."
    )
    parser_subscribe.add_argument("pid", type=int, help="Parent process ID.")
    parser_subscribe.add_argument(
        "--port", type=int, default=5057, help="Port to communicate with the server."
    )

    args = parser.parse_args()

    print(args)
    if args.command == "start":
        asyncio.run(
            run_subprocess_monitor(port=args.port, check_interval=args.check_interval)
        )

    elif args.command == "spawn":
        command = args.cmd
        spawn_args = args.cmd_args
        env = dict(var.split("=", 1) for var in args.env) if args.env else {}
        asyncio.run(send_spawn_request(command, spawn_args, env, args.port))

    elif args.command == "stop":
        asyncio.run(send_stop_request(args.pid, args.port))

    elif args.command == "status":
        asyncio.run(get_status(args.port))
    elif args.command == "subscribe":
        asyncio.run(subscribe(args.pid, args.port))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
