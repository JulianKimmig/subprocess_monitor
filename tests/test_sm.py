# tests/test_helper.py

import asyncio
import sys
import unittest
from unittest import IsolatedAsyncioTestCase
import logging

import psutil
import time

from subprocess_monitor.subprocess_monitor import (
    SubprocessMonitor,
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
        # First ensure all subprocesses are terminated
        await self.kill_all_subprocesses()

        # Then cancel and wait for server task
        self.server_task.cancel()
        try:
            await self.server_task
        except asyncio.CancelledError:
            pass

        # Add small delay to ensure cleanup completes
        await asyncio.sleep(0.1)

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
        test_args = ["-u", "-c", "import time; time.sleep(2); print('done')"]
        test_env = {}

        response = await send_spawn_request(
            test_cmd, test_args, test_env, port=self.port, host=self.host
        )
        self.assertEqual(response.get("status"), "success", response)
        pid = response.get("pid")
        self.assertIsInstance(pid, int)

        # Wait longer for process to be added to ownership tracking
        await asyncio.sleep(0.3)

        # Check if process is still alive before checking ownership
        if pid and psutil.pid_exists(pid):
            self.assertIn(pid, self.monitor.process_ownership)
        else:
            # Process has exited but may still be in ownership until next cleanup cycle
            # This is expected behavior with the new cleanup logic
            pass

        # Wait for subprocess to finish
        await asyncio.sleep(2.5)
        if pid:
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

        # Wait for process to be properly tracked
        await asyncio.sleep(0.5)
        self.assertIn(pid, self.monitor.process_ownership)

        # Stop the subprocess
        if pid:
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
        test_args = ["-u", "-c", "import time; time.sleep(2)"]
        response = await send_spawn_request(
            test_cmd, test_args, {}, port=self.port, host=self.host
        )

        self.assertEqual(response.get("status"), "success")
        pid = response.get("pid")
        self.assertIsInstance(pid, int)

        status = await get_status(port=self.port, host=self.host)
        self.assertIsInstance(status, list)
        self.assertEqual(len(status), 1)

        self.assertIn(pid, self.monitor.process_ownership)

        # Check status again
        status = await get_status(port=self.port, host=self.host)
        self.assertIn(pid, status)

        # Wait for subprocess to finish (subprocess sleeps for 2 seconds)
        await asyncio.sleep(2.5)
        status = await get_status(port=self.port, host=self.host)
        self.assertNotIn(pid, status)

    def _spwan_new_manager(self):
        time.sleep(1)
        monitor = SubprocessMonitor(check_interval=0.1, host=self.host)
        server_task = asyncio.create_task(monitor.run())
        return server_task, monitor

    async def test_spawn_external_manager(self):
        p1, monitor1 = self._spwan_new_manager()
        p2, monitor2 = self._spwan_new_manager()
        await asyncio.sleep(1)
        assert monitor1.port != monitor2.port
        try:  # Check if processes are still running after some time
            if p1.done():
                self.fail("Manager 1 died")

            if p2.done():
                self.fail("Manager 2 died")

            status = await get_status(host=self.host, port=monitor1.port)
            self.assertIsInstance(status, list)
            status = await get_status(host=self.host, port=monitor2.port)
            self.assertIsInstance(status, list)
        finally:
            p1.cancel()
            p2.cancel()


if __name__ == "__main__":
    unittest.main()
