# tests/test_helper.py

import asyncio
import sys
import unittest
from unittest import IsolatedAsyncioTestCase
import logging

import psutil
import subprocess
import time
import os

from subprocess_monitor.subprocess_monitor import (
    SubprocessMonitor,
    find_free_port,
)
from subprocess_monitor.helper import (
    send_spawn_request,
    send_stop_request,
    get_status,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TestHelperFunctions(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        """Set up the aiohttp server before each test."""

        # self.host = os.uname()[1]  # "localhost"
        # get ip of localhost
        self.host = "localhost"  # socket.gethostbyname(hostname)
        self.monitor = SubprocessMonitor(check_interval=0.1, host=self.host)
        self.port = self.monitor.port
        self.server_task = asyncio.create_task(self.monitor.run())

        # Allow some time for the server to start
        await asyncio.sleep(1)

    async def asyncTearDown(self):
        """Tear down the aiohttp server after each test."""
        self.server_task.cancel()
        try:
            await self.server_task
        except asyncio.CancelledError:
            pass

        # Ensure all subprocesses are terminated
        await self.kill_all_subprocesses()

    async def kill_all_subprocesses(self):
        """Helper function to kill all subprocesses."""
        tasks = []
        for pid, process in list(self.monitor.process_ownership.items()):
            tasks.append(self.stop_subprocess(process, pid))
        if tasks:
            await asyncio.gather(*tasks)

    async def stop_subprocess(self, process, pid):
        """Helper to stop a subprocess."""
        try:
            if process.returncode is None:
                process.terminate()
                await process.wait()
            self.monitor.process_ownership.pop(pid, None)
        except Exception as e:
            logger.exception(f"Error stopping subprocess {pid}: {e}")

    async def test_send_spawn_request(self):
        """Test the send_spawn_request helper function."""
        test_cmd = sys.executable
        test_args = ["-u", "-c", "import time; time.sleep(0.5); print('done')"]
        test_env = {}

        response = await send_spawn_request(
            test_cmd, test_args, test_env, port=self.port, host=self.host
        )
        self.assertEqual(response.get("status"), "success", response)
        pid = response.get("pid")
        self.assertIsInstance(pid, int)

        # Allow brief time for process to be added to ownership tracking
        await asyncio.sleep(0.1)
        self.assertIn(pid, self.monitor.process_ownership)

        # Wait for subprocess to finish
        await asyncio.sleep(0.8)
        self.assertFalse(psutil.pid_exists(pid))

    async def test_send_stop_request(self):
        """Test the send_stop_request helper function."""
        # Spawn a subprocess that sleeps for a while
        sleep_cmd = sys.executable
        sleep_args = ["-c", "import time; time.sleep(5)"]
        response = await send_spawn_request(
            sleep_cmd, sleep_args, port=self.port, host=self.host
        )
        self.assertEqual(response.get("status"), "success")
        pid = response.get("pid")
        self.assertIsInstance(pid, int)
        self.assertIn(pid, self.monitor.process_ownership)

        # Stop the subprocess
        stop_response = await send_stop_request(pid, port=self.port, host=self.host)
        self.assertEqual(stop_response.get("status"), "success")

        # Allow time for subprocess to terminate
        await asyncio.sleep(0.5)
        self.assertFalse(psutil.pid_exists(pid))

    async def test_get_status(self):
        """Test the get_status helper function."""
        # Initially, no subprocesses should be running
        status = await get_status(port=self.port, host=self.host)
        self.assertIsInstance(status, list)
        self.assertEqual(len(status), 0)

        # Spawn a subprocess
        test_cmd = sys.executable
        test_args = ["-u", "-c", "import time; time.sleep(0.5)"]
        response = await send_spawn_request(
            test_cmd, test_args, {}, port=self.port, host=self.host
        )
        self.assertEqual(response.get("status"), "success")
        pid = response.get("pid")
        self.assertIsInstance(pid, int)
        self.assertIn(pid, self.monitor.process_ownership)

        # Check status again
        status = await get_status(port=self.port, host=self.host)
        self.assertIn(pid, status)

        # Wait for subprocess to finish
        await asyncio.sleep(1)
        status = await get_status(port=self.port, host=self.host)
        self.assertNotIn(pid, status)

    def _spwan_new_manager(self):
        time.sleep(1)
        port = find_free_port()

        add_kwargs = {}

        # on POSIX (linux, mac), we need to set the start_new_session to True
        # to avoid the subprocess to become zombie when the parent is killed
        if os.name in ["posix"]:
            add_kwargs["start_new_session"] = True

        print("spwarning with:", add_kwargs)
        p1 = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "subprocess_monitor",
                "start",
                "--port",
                str(port),
                "--host",
                self.host,
            ],
            **add_kwargs,
        )
        time.sleep(1)
        return p1, port

    async def test_spawn_external_manager(self):
        p1, port = self._spwan_new_manager()
        p2, port2 = self._spwan_new_manager()

        try:
            self.assertIsNone(p1.returncode)
            self.assertIsNone(p2.returncode)

            status = await get_status(port=port, host=self.host)
            self.assertIsInstance(status, list)
            status = await get_status(port=port2, host=self.host)
            self.assertIsInstance(status, list)
        finally:
            p1.kill()
            p2.kill()


# TODO:The follwoing 2 tests fail on ubuntu since the exit status is None
#     async def test_call_spawn_external_process(self):
#         p1, port = self._spwan_new_manager()
#         time.sleep(1)

#         self.assertIsNone(p1.returncode)

#         status = await get_status(port=port, host=self.host)
#         self.assertIsInstance(status, list)

#         self.assertIsNone(p1.returncode)

#         resp = await send_spawn_request(
#             sys.executable,
#             ["-c", "import time; time.sleep(1)"],
#             port=port,
#             host=self.host,
#         )
#         self.assertIn("pid", resp, resp)

#         status = await get_status(port=port, host=self.host)
#         self.assertIsInstance(status, list)
#         self.assertEqual(len(status), 1)

#         p2 = psutil.Process(status[0])

#         self.assertTrue(p2.is_running())

#         p1.kill()

#         rc = p2.wait()
#         self.assertEqual(rc, 0)

#     async def test_call_on_manager_death(self):
#         p1, port = self._spwan_new_manager()

#         self.assertIsNone(p1.returncode)

#         status = await get_status(port=port, host=self.host)
#         self.assertIsInstance(status, list)
#         # assert p1  running
#         code = """
# import subprocess_monitor
# import time
# import os
# import sys

# KILL=False
# PID=os.environ.get("SUBPROCESS_MONITOR_PID")
# if PID is None:
#     sys.exit(2)

# def on_death():
#     global KILL
#     KILL=True
#     sys.exit(4)

# subprocess_monitor.call_on_manager_death(on_death, interval=0.5,)
# print("KILL")
# for i in range(10):
#     time.sleep(1)
#     if KILL:
#         sys.exit(3)
# """

#         self.assertIsNone(p1.returncode)

#         resp = await send_spawn_request(
#             sys.executable,
#             ["-c", code],
#             port=port,
#             host=self.host,
#         )
#         self.assertIn("pid", resp, resp)

#         status = await get_status(port=port, host=self.host)
#         self.assertIsInstance(status, list)
#         self.assertEqual(len(status), 1)

#         p2 = psutil.Process(status[0])

#         self.assertTrue(p2.is_running())

#         def on_death():
#             print("In code on_death")

#         os.environ["SUBPROCESS_MONITOR_PID"] = str(p1.pid)
#         call_on_manager_death(on_death, interval=0.1)
#         time.sleep(1)
#         self.assertTrue(p2.is_running())
#         p1.kill()

#         rc = p2.wait()
#         self.assertEqual(rc, 3)


# TODO: Uncomment this test, but its not working on ubuntu?
#     async def test_subscribe(self):
#         """Test the subscribe helper function."""
#         # Define a script that outputs multiple lines with delays
#         script = textwrap.dedent(
#             """
# import time
# time.sleep(0.5)
# for i in range(10):
#     print(f"Line {i}", flush=True)
#     time.sleep(0.1)
# time.sleep(0.5)
# """
#         ).strip()

#         # Spawn the subprocess
#         test_cmd = sys.executable
#         test_args = ["-u", "-c", script]
#         response = await send_spawn_request(test_cmd, test_args, {}, port=self.port)
#         self.assertEqual(response.get("status"), "success")
#         pid = response.get("pid")
#         self.assertIsInstance(pid, int)
#         self.assertIn(pid, self.monitor.process_ownership)

#         # Use the subscribe helper to capture output
#         messages = []

#         # Modify the `subscribe` function to accept a callback for testing purposes
#         # If you cannot modify the `subscribe` function, you can simulate similar behavior here
#         # For demonstration, we'll implement a similar subscription here

#         async with aiohttp.ClientSession() as session:
#             ws_url = f"http://localhost:{self.port}/subscribe?pid={pid}"
#             async with session.ws_connect(ws_url) as ws:
#                 async for msg in ws:
#                     if msg.type == aiohttp.WSMsgType.TEXT:
#                         data = json.loads(msg.data)
#                         messages.append(data)
#                     elif msg.type == aiohttp.WSMsgType.ERROR:
#                         raise Exception(
#                             f"WebSocket connection closed with error: {ws.exception()}"
#                         )
#                     else:
#                         raise Exception(f"Unexpected message type: {msg}")
#                     # Exit after receiving expected messages
#                     if len(messages) >= 3:
#                         break

#         # Verify received messages
#         self.assertGreaterEqual(len(messages), 3, messages)
#         for i, message in enumerate(messages[:3]):
#             self.assertEqual(message.get("pid"), pid)
#             self.assertEqual(message.get("stream"), "stdout")
#             self.assertEqual(message.get("data"), f"Line {i}")


if __name__ == "__main__":
    unittest.main()
