import asyncio
import unittest
from unittest import IsolatedAsyncioTestCase
import sys
import logging
from subprocess_monitor.subprocess_monitor import SubprocessMonitor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TestRaceConditions(IsolatedAsyncioTestCase):
    """Test cases for race conditions in subprocess management."""

    async def asyncSetUp(self):
        """Set up test environment."""
        self.host = "localhost"
        self.monitor = SubprocessMonitor(check_interval=0.1, host=self.host)
        self.port = self.monitor.port
        # Don't start the full server for these tests

    async def asyncTearDown(self):
        """Clean up test environment."""
        await self.monitor.kill_all_subprocesses()

    async def test_process_ownership_race_condition(self):
        """Test for race condition in process_ownership dictionary access."""
        # Issue: process_ownership dictionary is accessed without lock during iteration
        # This can cause 'dictionary changed size during iteration' errors

        test_cmd = sys.executable
        test_args = ["-c", "import time; time.sleep(0.1)"]

        # Track race condition errors
        race_condition_errors = []

        async def spawn_and_track():
            """Spawn process and track potential race conditions."""
            try:
                request = {"cmd": test_cmd, "args": test_args, "env": {}}
                pid = await self.monitor.start_subprocess(request)
                return pid
            except Exception as e:
                if "dictionary changed size during iteration" in str(e):
                    race_condition_errors.append(e)
                return None

        async def check_and_track():
            """Check processes and track potential race conditions."""
            try:
                await self.monitor.check_processes_step()
            except RuntimeError as e:
                if "dictionary changed size during iteration" in str(e):
                    race_condition_errors.append(e)
                    return False
            return True

        async def stop_and_track():
            """Stop processes and track potential race conditions."""
            try:
                async with self.monitor.process_ownership_lock:
                    pids = list(self.monitor.process_ownership.keys())

                if pids:
                    pid = pids[0]
                    await self.monitor.stop_subprocess(pid=pid)
            except Exception as e:
                if "dictionary changed size during iteration" in str(e):
                    race_condition_errors.append(e)

        # Create high concurrency to trigger race condition
        tasks = []
        for i in range(50):  # Increased concurrency
            tasks.append(spawn_and_track())
            tasks.append(check_and_track())
            if i % 5 == 0:
                tasks.append(stop_and_track())

        # Execute all tasks concurrently
        await asyncio.gather(*tasks, return_exceptions=True)

        # Check for race conditions
        if race_condition_errors:
            self.fail(f"Race condition detected: {race_condition_errors[0]}")

        # Additional cleanup
        await asyncio.sleep(0.2)

    async def test_infinite_recursion_in_check_terminated(self):
        """Test for infinite recursion in check_terminated method."""
        # Issue: check_terminated can call itself recursively without limit
        # if kill_subprocess_sync fails to terminate the process

        test_cmd = sys.executable
        test_args = [
            "-c",
            (
                "import signal; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "signal.signal(signal.SIGINT, signal.SIG_IGN); "
                "import time; time.sleep(10)"
            ),
        ]

        request = {"cmd": test_cmd, "args": test_args, "env": {}}
        pid = await self.monitor.start_subprocess(request)

        # Get the process object
        process = self.monitor.process_ownership[pid]

        # Track recursion depth
        original_check_terminated = self.monitor.check_terminated
        recursion_depth = 0
        max_recursion = 0

        async def tracking_check_terminated(process, pid, max_retries=3):
            nonlocal recursion_depth, max_recursion
            recursion_depth += 1
            max_recursion = max(max_recursion, recursion_depth)

            try:
                result = await original_check_terminated(process, pid, max_retries)
                return result
            finally:
                recursion_depth -= 1

        # Mock the check_terminated method
        self.monitor.check_terminated = tracking_check_terminated

        # Call check_terminated directly to test recursion
        await self.monitor.check_terminated(process, pid)

        # Verify recursion occurred (should be 3 retries + 1 initial call)
        self.assertGreater(
            max_recursion, 1, "Expected recursive calls to check_terminated"
        )

        # Force cleanup - use cross-platform approach
        try:
            import os
            import signal

            # Use SIGTERM on Windows, SIGKILL on Unix
            if hasattr(signal, "SIGKILL"):
                os.kill(pid, signal.SIGKILL)
            else:
                # Windows fallback - terminate the process
                os.kill(pid, signal.SIGTERM)
        except (OSError, ProcessLookupError, AttributeError):
            pass

    async def test_websocket_subscription_cleanup_race(self):
        """Test race condition in WebSocket subscription cleanup."""
        # Issue: WebSocket subscriptions might not be cleaned up properly
        # causing memory leaks

        test_cmd = sys.executable
        test_args = ["-c", "import time; time.sleep(0.1); print('test')"]

        request = {"cmd": test_cmd, "args": test_args, "env": {}}
        pid = await self.monitor.start_subprocess(request)

        # Mock WebSocket to simulate subscription
        class MockWebSocket:
            def __init__(self):
                self.closed = False

            async def close(self):
                self.closed = True

            async def send_str(self, msg):
                pass

        # Add mock subscription
        mock_ws = MockWebSocket()
        async with self.monitor.subscription_lock:
            if pid not in self.monitor.subscriptions:
                self.monitor.subscriptions[pid] = []
            self.monitor.subscriptions[pid].append(mock_ws)

        # Stop the process
        await self.monitor.stop_subprocess(pid=pid)

        # Wait for cleanup
        await asyncio.sleep(0.2)

        # Check that subscription was cleaned up
        self.assertNotIn(
            pid,
            self.monitor.subscriptions,
            "Subscription should be cleaned up after process stops",
        )
        self.assertTrue(mock_ws.closed, "WebSocket should be closed")

    async def test_concurrent_process_ownership_access(self):
        """Test that concurrent access to process_ownership doesn't cause race conditions."""
        # Enhanced version of the original test
        test_cmd = sys.executable
        test_args = ["-c", "import time; time.sleep(0.1)"]

        # Track dictionary change errors
        dict_errors = []

        async def spawn_process():
            try:
                request = {"cmd": test_cmd, "args": test_args, "env": {}}
                return await self.monitor.start_subprocess(request)
            except Exception as e:
                if "dictionary changed size during iteration" in str(e):
                    dict_errors.append(e)
                return None

        async def check_processes():
            try:
                await self.monitor.check_processes_step()
            except RuntimeError as e:
                if "dictionary changed size during iteration" in str(e):
                    dict_errors.append(e)
                    return False
            return True

        async def stop_random_process():
            try:
                # Use lock to safely get PIDs
                async with self.monitor.process_ownership_lock:
                    pids = list(self.monitor.process_ownership.keys())

                if pids:
                    pid = pids[0]
                    await self.monitor.stop_subprocess(pid=pid)
            except Exception as e:
                if "dictionary changed size during iteration" in str(e):
                    dict_errors.append(e)

        # Create many concurrent tasks
        tasks = []
        for i in range(100):  # High concurrency
            tasks.append(spawn_process())
            tasks.append(check_processes())
            if i % 10 == 0:
                tasks.append(stop_random_process())

        # Execute all tasks
        await asyncio.gather(*tasks, return_exceptions=True)

        # Check for dictionary change errors
        if dict_errors:
            self.fail(f"Dictionary race condition detected: {dict_errors[0]}")

        # Cleanup
        await asyncio.sleep(0.5)

    async def test_concurrent_stop_and_check(self):
        """Test concurrent stopping and checking of processes."""
        test_cmd = sys.executable
        test_args = ["-c", "import time; time.sleep(2)"]
        request = {"cmd": test_cmd, "args": test_args, "env": {}}

        pid = await self.monitor.start_subprocess(request)
        self.assertIsNotNone(pid)

        # Track race condition errors
        race_errors = []

        async def stop_process():
            try:
                await self.monitor.stop_subprocess(pid=pid)
            except Exception as e:
                if "dictionary changed size during iteration" in str(e):
                    race_errors.append(e)

        async def check_processes():
            try:
                await self.monitor.check_processes_step()
            except RuntimeError as e:
                if "dictionary changed size during iteration" in str(e):
                    race_errors.append(e)

        # Run multiple concurrent operations
        tasks = [stop_process()]
        for _ in range(10):
            tasks.append(check_processes())

        await asyncio.gather(*tasks, return_exceptions=True)

        # Check for race conditions
        if race_errors:
            self.fail(f"Race condition in stop/check: {race_errors[0]}")


if __name__ == "__main__":
    unittest.main()
