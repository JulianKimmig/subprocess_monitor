from typing import Dict, Optional, List, Callable
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
    StopProcessRequest,
    StopRequestResponse,
    SubProcessIndexResponse,
    StreamingLineOutput,
)
from .validation import (
    safe_validate_spawn_process_request,
    safe_validate_spawn_request_response,
    safe_validate_stop_process_request,
    safe_validate_stop_request_response,
    safe_validate_subprocess_index_response,
    safe_validate_streaming_line_output,
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

    # Validate the request before sending
    safe_validate_spawn_process_request(req)

    logger.debug("Sending spawn request to %s:%s with request: %s", host, port, req)
    async with ClientSession() as session:
        async with session.post(f"http://{host}:{port}/spawn", json=req) as resp:
            raw_response = await resp.json()
            response = safe_validate_spawn_request_response(raw_response)
            logger.info("Response from server: %s", json.dumps(response, indent=2))
            return response


async def send_stop_request(
    pid: int,
    host: Optional[str] = None,
    port: Optional[int] = None,
) -> StopRequestResponse:
    req = StopProcessRequest(pid=pid)

    # Validate the request before sending
    safe_validate_stop_process_request(req)

    if host is None:
        host = os.environ.get("SUBPROCESS_MONITOR_HOST", DEFAULT_HOST)
    if port is None:
        port = int(os.environ.get("SUBPROCESS_MONITOR_PORT", DEFAULT_PORT))

    async with ClientSession() as session:
        async with session.post(f"http://{host}:{port}/stop", json=req) as resp:
            raw_response = await resp.json()
            response = safe_validate_stop_request_response(raw_response)
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
            raw_response = await resp.json()
            response = safe_validate_subprocess_index_response(raw_response)
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
                    raw_data = json.loads(msg.data)
                    data = safe_validate_streaming_line_output(raw_data)
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
    max_attempts: int = 1000,
):
    if host is None:
        host = os.environ.get("SUBPROCESS_MONITOR_HOST", DEFAULT_HOST)
    if port is None:
        port = int(os.environ.get("SUBPROCESS_MONITOR_PORT", DEFAULT_PORT))
    pid = int(pid)

    def call_on_death():
        attempts = 0
        consecutive_errors = 0
        max_consecutive_errors = 10

        while attempts < max_attempts:
            attempts += 1

            try:
                if not psutil.pid_exists(pid):
                    logger.info(f"Process {pid} has died, calling callback")
                    callback()
                    break

                # Reset error counter on successful check
                consecutive_errors = 0

            except (OSError, PermissionError) as e:
                consecutive_errors += 1
                logger.warning(
                    f"Error checking if process {pid} exists (attempt {attempts}/{max_attempts}, "
                    f"consecutive errors: {consecutive_errors}/{max_consecutive_errors}): {e}"
                )

                # If we've had too many consecutive errors, assume process is dead
                if consecutive_errors >= max_consecutive_errors:
                    logger.error(
                        f"Too many consecutive errors checking process {pid}, assuming it's dead"
                    )
                    callback()
                    break

            except KeyboardInterrupt:
                logger.info(f"Interrupted while monitoring process {pid}")
                break

            except Exception as e:
                consecutive_errors += 1
                logger.error(
                    f"Unexpected error checking process {pid} (attempt {attempts}/{max_attempts}): {e}"
                )

                # If we've had too many consecutive errors, assume process is dead
                if consecutive_errors >= max_consecutive_errors:
                    logger.error(
                        f"Too many consecutive errors checking process {pid}, assuming it's dead"
                    )
                    callback()
                    break

            try:
                time.sleep(interval)
            except KeyboardInterrupt:
                logger.info(
                    f"Interrupted while sleeping, stopping monitoring of process {pid}"
                )
                break

        if attempts >= max_attempts:
            logger.warning(
                f"Reached maximum attempts ({max_attempts}) monitoring process {pid}, stopping"
            )

    p = threading.Thread(target=call_on_death, daemon=True)
    p.start()


def call_on_manager_death(
    callback: Callable[[], None],
    manager_pid: Optional[int] = None,
    interval: float = 10,
    max_attempts: int = 1000,
):
    if manager_pid is None:
        manager_pid = os.environ.get("SUBPROCESS_MONITOR_PID")

    if manager_pid is None:
        raise ValueError(
            "manager_pid is not given and cannot be found as env:SUBPROCESS_MONITOR_PID"
        )

    manager_pid = int(manager_pid)

    def call_on_death():
        attempts = 0
        consecutive_errors = 0
        max_consecutive_errors = 10

        while attempts < max_attempts:
            attempts += 1

            try:
                if not psutil.pid_exists(manager_pid):
                    logger.info(f"Manager {manager_pid} has died, calling callback")
                    callback()
                    break

                # Reset error counter on successful check
                consecutive_errors = 0

            except (OSError, PermissionError) as e:
                consecutive_errors += 1
                logger.warning(
                    f"Error checking if manager {manager_pid} exists (attempt {attempts}/{max_attempts}, "
                    f"consecutive errors: {consecutive_errors}/{max_consecutive_errors}): {e}"
                )

                # If we've had too many consecutive errors, assume manager is dead
                if consecutive_errors >= max_consecutive_errors:
                    logger.error(
                        f"Too many consecutive errors checking manager {manager_pid}, assuming it's dead"
                    )
                    callback()
                    break

            except KeyboardInterrupt:
                logger.info(f"Interrupted while monitoring manager {manager_pid}")
                break

            except Exception as e:
                consecutive_errors += 1
                logger.error(
                    f"Unexpected error checking manager {manager_pid} (attempt {attempts}/{max_attempts}): {e}"
                )

                # If we've had too many consecutive errors, assume manager is dead
                if consecutive_errors >= max_consecutive_errors:
                    logger.error(
                        f"Too many consecutive errors checking manager {manager_pid}, assuming it's dead"
                    )
                    callback()
                    break

            try:
                time.sleep(interval)
            except KeyboardInterrupt:
                logger.info(
                    f"Interrupted while sleeping, stopping monitoring of manager {manager_pid}"
                )
                break

        if attempts >= max_attempts:
            logger.warning(
                f"Reached maximum attempts ({max_attempts}) monitoring manager {manager_pid}, stopping"
            )

    p = threading.Thread(target=call_on_death, daemon=True)
    p.start()
    time.sleep(0.1)

    # Check if thread is running, but don't fail if it completed quickly
    # (e.g., if the manager was already dead)
    if not p.is_alive():
        logger.warning(
            f"Thread monitoring manager {manager_pid} completed immediately - manager may already be dead"
        )


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

        # Validate the request before sending
        safe_validate_spawn_process_request(req)

        logger.info(f"Sending request to spawn subprocess: {json.dumps(req, indent=2)}")
        async with ClientSession() as session:
            async with session.post(
                f"http://{host}:{port}/spawn",
                json=req,
            ) as resp:
                raw_response = await resp.json()
                # Validate the response
                response = safe_validate_spawn_request_response(raw_response)
                logger.info(json.dumps(response, indent=2, ensure_ascii=True))
                return response

    return asyncio.run(send_request())
