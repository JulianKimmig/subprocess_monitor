import argparse
import asyncio
import logging
import sys
from .defaults import DEFAULT_HOST, DEFAULT_PORT
from subprocess_monitor import (
    run_subprocess_monitor,
    send_spawn_request,
    send_stop_request,
    get_status,
    subscribe,
)


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


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
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="Port to run the subprocess manager on.",
    )

    parser_start.add_argument(
        "--host",
        type=str,
        default=DEFAULT_HOST,
        help="Host address of the subprocess manager",
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
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="Port to communicate with the server.",
    )

    parser_spawn.add_argument(
        "--host",
        type=str,
        default=DEFAULT_HOST,
        help="Host adress to communicate with the server.",
    )

    # Command to stop a subprocess
    parser_stop = subparsers.add_parser("stop", help="Stop a subprocess.")
    parser_stop.add_argument("pid", type=int, help="Process ID.")
    parser_stop.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="Port to communicate with the server.",
    )

    parser_stop.add_argument(
        "--host",
        type=str,
        default=DEFAULT_HOST,
        help="Host adress to communicate with the server.",
    )

    # Command to check status of subprocesses
    parser_status = subparsers.add_parser("status", help="Check subprocess status.")
    parser_status.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="Port to communicate with the server.",
    )

    parser_status.add_argument(
        "--host",
        type=str,
        default=DEFAULT_HOST,
        help="Host adress to communicate with the server.",
    )

    # Command to subscribe to a topic
    parser_subscribe = subparsers.add_parser(
        "subscribe", help="Subscribe to a process."
    )
    parser_subscribe.add_argument("pid", type=int, help="Parent process ID.")
    parser_subscribe.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="Port to communicate with the server.",
    )

    parser_subscribe.add_argument(
        "--host",
        type=str,
        default=DEFAULT_HOST,
        help="Host adress to communicate with the server.",
    )

    args = parser.parse_args()

    if args.command == "start":
        asyncio.run(
            run_subprocess_monitor(
                host=args.host, port=args.port, check_interval=args.check_interval
            )
        )

    elif args.command == "spawn":
        command = args.cmd
        spawn_args = args.cmd_args

        # Parse and validate environment variables
        env = {}
        if args.env:
            for var in args.env:
                if not var or "=" not in var:
                    logger.error(
                        f"Invalid environment variable format: '{var}'. Expected KEY=VALUE format."
                    )
                    sys.exit(1)

                key, value = var.split("=", 1)

                # Validate environment variable name (no spaces, valid identifier-like format)
                if (
                    not key
                    or " " in key
                    or not key.replace("_", "").replace("-", "").isalnum()
                ):
                    logger.error(
                        f"Invalid environment variable name: '{key}'."
                        " Names cannot contain spaces or special characters."
                    )
                    sys.exit(1)

                env[key] = value

        asyncio.run(send_spawn_request(command, spawn_args, env, args.host, args.port))

    elif args.command == "stop":
        asyncio.run(send_stop_request(args.pid, args.host, args.port))

    elif args.command == "status":
        asyncio.run(get_status(args.host, args.port))
    elif args.command == "subscribe":
        asyncio.run(subscribe(args.pid, args.host, args.port))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
