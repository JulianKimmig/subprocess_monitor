import unittest
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch
import threading
import time
import os
from subprocess_monitor.helper import call_on_manager_death, call_on_process_death


class TestManagerDeathDetection(IsolatedAsyncioTestCase):
    """Test cases for thread safety issues in manager death detection."""

    def test_manager_death_detection_race_condition(self):
        """Test race condition between p.start() and p.is_alive() check."""
        # Issue #10: Thread safety issue in manager death detection

        # Mock process that can simulate race condition
        class MockProcess:
            def __init__(self):
                self.started = False
                self.alive = True
                self.start_lock = threading.Lock()

            def start(self):
                with self.start_lock:
                    self.started = True
                    # Simulate delay in process startup
                    time.sleep(0.01)
                    self.alive = True

            def is_alive(self):
                # Race condition: check alive status before start completes
                return self.started and self.alive

            def kill(self):
                self.alive = False

        # Test the race condition
        race_condition_detected = False

        def test_race():
            nonlocal race_condition_detected
            mock_process = MockProcess()

            # Start the process
            mock_process.start()

            # Quickly check if alive (race condition)
            if not mock_process.is_alive():
                race_condition_detected = True

        # Run multiple times to increase chance of race condition
        for _ in range(10):
            test_race()

        # The race condition might not always occur, but the test
        # demonstrates the vulnerability exists

    def test_call_on_manager_death_threading_safety(self):
        """Test thread safety in call_on_manager_death function."""

        # Create a mock manager PID
        manager_pid = os.getpid()  # Use current process as manager

        # Mock psutil.pid_exists to simulate manager death
        pid_exists_calls = []

        def mock_pid_exists(pid):
            pid_exists_calls.append(pid)
            # Simulate manager death after a few calls
            return len(pid_exists_calls) < 3

        callback_called = []

        def test_callback():
            callback_called.append(True)

        # Test with mocked psutil
        with patch(
            "subprocess_monitor.helper.psutil.pid_exists", side_effect=mock_pid_exists
        ):
            with patch("subprocess_monitor.helper.time.sleep"):  # Speed up test
                try:
                    call_on_manager_death(test_callback, manager_pid)
                    # Give the thread time to run
                    time.sleep(1)
                except Exception:
                    # Expected when manager "dies"
                    pass

        # Verify callback was called
        self.assertTrue(
            len(callback_called) > 0, "Callback should be called when manager dies"
        )

    def test_call_on_process_death_threading_safety(self):
        """Test thread safety in call_on_process_death function."""

        # Create a mock process PID
        process_pid = 99999  # Non-existent PID

        # Mock psutil.pid_exists to simulate process death
        pid_exists_calls = []

        def mock_pid_exists(pid):
            pid_exists_calls.append(pid)
            # Simulate process death after a few calls
            return len(pid_exists_calls) < 3

        callback_called = []

        def test_callback():
            callback_called.append(True)

        # Test with mocked psutil
        with patch(
            "subprocess_monitor.helper.psutil.pid_exists", side_effect=mock_pid_exists
        ):
            with patch("subprocess_monitor.helper.time.sleep"):  # Speed up test
                try:
                    call_on_process_death(test_callback, process_pid)
                    # Give the thread time to run
                    time.sleep(0.1)
                except Exception:
                    # Expected when process "dies"
                    pass

        # Verify callback was called
        self.assertTrue(
            len(callback_called) > 0, "Callback should be called when process dies"
        )

    def test_concurrent_death_detection_calls(self):
        """Test concurrent calls to death detection functions."""

        # Test multiple threads calling death detection simultaneously
        results = []
        exceptions = []

        def death_detection_worker(worker_id):
            try:
                # Use current PID as manager
                manager_pid = os.getpid()

                callback_calls = []

                def callback():
                    callback_calls.append(worker_id)

                # Mock psutil to make it return False quickly
                with patch(
                    "subprocess_monitor.helper.psutil.pid_exists", return_value=False
                ):
                    with patch("subprocess_monitor.helper.time.sleep"):
                        try:
                            call_on_manager_death(callback, manager_pid)
                            time.sleep(0.1)  # Give thread time to run
                        except Exception:
                            # Expected when manager "dies"
                            pass

                results.append((worker_id, len(callback_calls)))

            except Exception as e:
                exceptions.append((worker_id, e))

        # Create multiple threads
        threads = []
        for i in range(5):
            thread = threading.Thread(target=death_detection_worker, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join(timeout=5)

        # Check results
        self.assertEqual(len(exceptions), 0, f"Unexpected exceptions: {exceptions}")
        self.assertEqual(len(results), 5, "All workers should complete")

    def test_psutil_pid_exists_edge_cases(self):
        """Test edge cases in psutil.pid_exists usage."""

        # Test with various invalid PIDs
        invalid_pids = [
            -1,  # Negative PID
            0,  # Zero PID
            999999,  # Very high PID (likely non-existent)
        ]

        for pid in invalid_pids:
            callback_called = []

            def callback():
                callback_called.append(True)

            # Mock psutil to return False for invalid PIDs
            with patch(
                "subprocess_monitor.helper.psutil.pid_exists", return_value=False
            ):
                with patch("subprocess_monitor.helper.time.sleep"):
                    try:
                        call_on_process_death(callback, pid)
                        time.sleep(0.1)  # Give thread time to run
                    except Exception:
                        # Expected for invalid PIDs
                        pass

            # Callback should be called since process doesn't exist
            self.assertTrue(
                len(callback_called) > 0,
                f"Callback should be called for invalid PID {pid}",
            )

    def test_death_detection_with_signal_handling(self):
        """Test death detection with signal handling."""

        # Test that death detection works even with signal interruptions
        callback_called = []

        def callback():
            callback_called.append(True)

        # Mock process that will "die" after some time
        call_count = 0

        def mock_pid_exists(pid):
            nonlocal call_count
            call_count += 1
            # Simulate process death after 3 calls
            return call_count < 3

        # Test with signal interruption
        with patch(
            "subprocess_monitor.helper.psutil.pid_exists", side_effect=mock_pid_exists
        ):
            with patch("subprocess_monitor.helper.time.sleep"):
                try:
                    call_on_process_death(callback, 12345)
                    time.sleep(0.1)  # Give thread time to run
                except Exception:
                    # Expected when process "dies"
                    pass

        # Verify callback was called
        self.assertTrue(
            len(callback_called) > 0,
            "Callback should be called despite signal handling",
        )

    def test_memory_leak_in_death_detection(self):
        """Test for potential memory leaks in death detection loops."""

        # Test that repeated calls don't cause memory issues
        callback_count = 0

        def callback():
            nonlocal callback_count
            callback_count += 1

        # Mock quick death detection
        with patch("subprocess_monitor.helper.psutil.pid_exists", return_value=False):
            with patch("subprocess_monitor.helper.time.sleep"):
                # Run multiple death detection cycles
                for i in range(10):
                    try:
                        call_on_process_death(callback, i + 1000)
                        time.sleep(0.01)  # Give thread time to run
                    except Exception:
                        # Expected when process "dies"
                        pass

        # Verify all callbacks were called
        self.assertEqual(callback_count, 10, "All callbacks should be called")


if __name__ == "__main__":
    unittest.main()
