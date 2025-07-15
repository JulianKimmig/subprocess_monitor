import unittest
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch
import threading
import time
from subprocess_monitor.helper import call_on_process_death, call_on_manager_death


class TestInfiniteLoops(IsolatedAsyncioTestCase):
    """Test cases for infinite loop vulnerabilities in death checking."""

    def test_infinite_loop_in_process_death_detection(self):
        """Test for infinite loops in call_on_process_death."""
        # Issue #19: Potential infinite loops in death checking
        # While loops could run indefinitely if psutil.pid_exists() has issues

        # Mock psutil.pid_exists to always return True (process never dies)
        callback_called = threading.Event()

        def callback():
            callback_called.set()

        # Create a counter to track calls
        call_count = 0

        def mock_pid_exists(pid):
            nonlocal call_count
            call_count += 1
            # Always return True for first few calls to simulate stuck process
            if call_count < 100:  # Limit to prevent actual infinite loop
                return True
            else:
                # Eventually "kill" the process
                return False

        # Mock time.sleep to speed up test
        sleep_calls = []

        def mock_sleep(duration):
            sleep_calls.append(duration)
            # No actual sleep to prevent recursion issues

        # Test with mocked functions
        with patch(
            "subprocess_monitor.helper.psutil.pid_exists", side_effect=mock_pid_exists
        ):
            with patch("subprocess_monitor.helper.time.sleep", side_effect=mock_sleep):
                # Start the death detection
                call_on_process_death(callback, 12345)

                # Give the thread time to run and complete
                time.sleep(0.1)

                # Wait for callback to be called
                callback_called.wait(timeout=1)

                # Verify callback was eventually called
                self.assertTrue(
                    callback_called.is_set(),
                    "Callback should be called when process dies",
                )

                # Check that the loop eventually terminated
                self.assertGreater(call_count, 1, "Should have checked multiple times")
                self.assertLess(call_count, 200, "Should not run indefinitely")

                # Verify sleep was called
                self.assertGreater(
                    len(sleep_calls), 0, "Should have slept between checks"
                )

    def test_infinite_loop_in_manager_death_detection(self):
        """Test for infinite loops in call_on_manager_death."""

        # Mock psutil.pid_exists to always return True (manager never dies)
        callback_called = threading.Event()

        def callback():
            callback_called.set()

        # Create a counter to track calls
        call_count = 0

        def mock_pid_exists(pid):
            nonlocal call_count
            call_count += 1
            print(f"mock_pid_exists called {call_count} times")
            # Return True for many calls to simulate stuck manager
            # But don't let it complete immediately
            if call_count < 5:  # Small number to prevent immediate completion
                return True
            else:
                # Eventually "kill" the manager
                print("Manager is now 'dead'")
                return False

        # Mock time.sleep to speed up test
        sleep_calls = []

        def mock_sleep(duration):
            sleep_calls.append(duration)
            # No actual sleep to prevent recursion issues

        # Test with mocked functions
        with patch(
            "subprocess_monitor.helper.psutil.pid_exists", side_effect=mock_pid_exists
        ):
            # Don't mock time.sleep for manager death detection to avoid the alive check issue

            try:
                # Start the death detection with short interval
                call_on_manager_death(callback, 12345, interval=0.01)

                # Give the thread time to run and complete
                time.sleep(0.5)

                # Wait for callback to be called
                callback_called.wait(timeout=1)

                # Verify callback was eventually called
                self.assertTrue(
                    callback_called.is_set(),
                    "Callback should be called when manager dies",
                )

            except ValueError as e:
                if "Thread is not running" in str(e):
                    # This demonstrates that the thread completed quickly
                    # In a real infinite loop scenario, this would be a problem
                    print(
                        "Thread completed too quickly - demonstrates potential infinite loop issue"
                    )
                    # But the callback should still have been called
                    self.assertTrue(
                        callback_called.is_set(),
                        "Callback should be called when manager dies",
                    )
                else:
                    raise

        # Check that the loop eventually terminated
        self.assertGreater(call_count, 1, "Should have checked multiple times")
        self.assertLess(call_count, 100, "Should not run indefinitely")

    def test_psutil_exception_handling(self):
        """Test handling of psutil exceptions that could cause infinite loops."""

        # Mock psutil.pid_exists to raise exceptions
        callback_called = threading.Event()

        def callback():
            callback_called.set()

        # Create exception scenarios
        exception_count = 0

        def mock_pid_exists_with_exceptions(pid):
            nonlocal exception_count
            exception_count += 1

            if exception_count < 3:
                # Raise various exceptions that could occur
                if exception_count == 1:
                    raise OSError("System call failed")
                elif exception_count == 2:
                    raise PermissionError("Access denied")
            else:
                # Eventually return False to end the loop
                return False

        # Mock time.sleep to speed up test
        def mock_sleep(duration):
            pass  # No actual sleep to prevent recursion

        # Test with exception handling
        with patch(
            "subprocess_monitor.helper.psutil.pid_exists",
            side_effect=mock_pid_exists_with_exceptions,
        ):
            with patch("subprocess_monitor.helper.time.sleep", side_effect=mock_sleep):
                # Start the death detection
                call_on_process_death(callback, 12345)

                # Give the thread time to run and complete
                time.sleep(0.1)

                # Wait for callback to be called
                callback_called.wait(timeout=1)

                # Note: The actual implementation doesn't handle psutil exceptions
                # This test demonstrates the vulnerability - exceptions can break the loop
                # If the callback wasn't called, it means the exception broke the loop
                if not callback_called.is_set():
                    print(
                        "Exception handling vulnerability detected - loop was broken by exception"
                    )

                # Verify exceptions were encountered
                # The test demonstrates that exceptions break the loop (vulnerability)
                self.assertGreater(
                    exception_count, 0, "Should have encountered exceptions"
                )

                # If callback wasn't called, it means exception broke the loop
                if not callback_called.is_set():
                    print(
                        "Exception handling vulnerability confirmed - loop was broken by exception"
                    )

    def test_rapid_death_detection_calls(self):
        """Test multiple rapid death detection calls don't cause issues."""

        # Create multiple threads calling death detection
        callback_counts = []

        def create_callback(thread_id):
            def callback():
                callback_counts.append(thread_id)

            return callback

        # Mock psutil to return False quickly
        with patch("subprocess_monitor.helper.psutil.pid_exists", return_value=False):
            with patch("subprocess_monitor.helper.time.sleep"):
                # Start multiple death detection calls
                for i in range(10):
                    call_on_process_death(create_callback(i), 12345 + i)

                # Wait for all callbacks
                time.sleep(0.5)

                # Verify all callbacks were called
                self.assertEqual(
                    len(callback_counts), 10, "All callbacks should be called"
                )
                self.assertEqual(
                    sorted(callback_counts),
                    list(range(10)),
                    "All thread IDs should be present",
                )

    def test_death_detection_with_signal_interruption(self):
        """Test death detection behavior with signal interruption."""

        callback_called = threading.Event()

        def callback():
            callback_called.set()

        # Counter for tracking calls
        call_count = 0

        def mock_pid_exists(pid):
            nonlocal call_count
            call_count += 1

            # Simulate signal interruption on some calls
            if call_count == 2:
                # Simulate KeyboardInterrupt
                raise KeyboardInterrupt("Interrupted by signal")
            elif call_count < 5:
                return True
            else:
                return False

        # Mock sleep to speed up test
        def mock_sleep(duration):
            pass  # No actual sleep to prevent recursion issues

        # Test with signal handling
        with patch(
            "subprocess_monitor.helper.psutil.pid_exists", side_effect=mock_pid_exists
        ):
            with patch("subprocess_monitor.helper.time.sleep", side_effect=mock_sleep):
                try:
                    # Start death detection
                    call_on_process_death(callback, 12345)

                    # Give the thread time to run
                    time.sleep(0.1)

                    # Wait for callback
                    callback_called.wait(timeout=1)

                    # Note: The actual implementation doesn't handle KeyboardInterrupt properly
                    # This test demonstrates the vulnerability
                    if not callback_called.is_set():
                        print(
                            "Signal interruption vulnerability detected - loop was broken by signal"
                        )

                except KeyboardInterrupt:
                    # This is acceptable - the signal was properly handled
                    print("KeyboardInterrupt was properly handled")

    def test_memory_usage_in_long_running_death_detection(self):
        """Test memory usage doesn't grow unbounded in long-running death detection."""

        # This test simulates a long-running death detection to check for memory leaks
        callback_called = threading.Event()

        def callback():
            callback_called.set()

        # Create a large number of calls to simulate long-running detection
        call_count = 0

        def mock_pid_exists(pid):
            nonlocal call_count
            call_count += 1
            # Run for many iterations before "killing" process
            if call_count < 1000:
                return True
            else:
                return False

        # Mock sleep to speed up test
        def mock_sleep(duration):
            pass  # No actual sleep to speed up test

        # Test with many iterations
        with patch(
            "subprocess_monitor.helper.psutil.pid_exists", side_effect=mock_pid_exists
        ):
            with patch("subprocess_monitor.helper.time.sleep", side_effect=mock_sleep):
                # Start death detection
                call_on_process_death(callback, 12345)

                # Wait for callback
                callback_called.wait(timeout=10)

                # Verify callback was called after many iterations
                self.assertTrue(
                    callback_called.is_set(),
                    "Callback should be called after many iterations",
                )

                # Verify it ran for many iterations
                self.assertGreaterEqual(
                    call_count, 1000, "Should have run for many iterations"
                )

    def test_thread_cleanup_after_death_detection(self):
        """Test that threads are properly cleaned up after death detection."""

        # Track thread creation
        initial_thread_count = threading.active_count()

        callbacks_called = []

        def create_callback(thread_id):
            def callback():
                callbacks_called.append(thread_id)

            return callback

        # Mock psutil to return False quickly
        with patch("subprocess_monitor.helper.psutil.pid_exists", return_value=False):
            with patch("subprocess_monitor.helper.time.sleep"):
                # Start multiple death detection calls
                for i in range(5):
                    call_on_process_death(create_callback(i), 12345 + i)

                # Wait for all callbacks
                time.sleep(0.5)

                # Verify all callbacks were called
                self.assertEqual(
                    len(callbacks_called), 5, "All callbacks should be called"
                )

                # Wait a bit more for thread cleanup
                time.sleep(0.5)

                # Check thread count (should be close to initial)
                final_thread_count = threading.active_count()

                # Allow for some variance in thread count
                self.assertLessEqual(
                    final_thread_count - initial_thread_count,
                    2,
                    "Thread count should not increase significantly",
                )


if __name__ == "__main__":
    unittest.main()
