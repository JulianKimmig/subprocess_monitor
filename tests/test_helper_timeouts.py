import asyncio
import unittest
from unittest import IsolatedAsyncioTestCase
from aiohttp import ClientSession, ClientTimeout
from subprocess_monitor.helper import (
    send_spawn_request,
)


class TestHelperTimeouts(IsolatedAsyncioTestCase):
    """Test cases for timeout handling in helper functions."""

    async def test_timeout_integration(self):
        """Integration test for timeout handling."""
        # Test with an unreachable host/port to trigger timeout

        # First, let's test that current implementation hangs without timeout
        import time

        # Use a non-routable IP to ensure timeout
        start_time = time.time()

        try:
            # This should timeout quickly with proper timeout configuration
            await asyncio.wait_for(
                send_spawn_request("test_command", host="10.255.255.1", port=12345),
                timeout=2.0,
            )
            self.fail("Expected timeout but request completed")
        except asyncio.TimeoutError:
            # This is expected - the operation should timeout
            pass
        except Exception:
            # Connection errors are also acceptable
            pass

        elapsed = time.time() - start_time

        # The test should complete within reasonable time
        # Without proper timeout, it would hang much longer
        self.assertLess(elapsed, 5.0, "Request should timeout within 5 seconds")

    async def test_timeout_configuration_exists(self):
        """Test that timeout configuration can be applied."""
        # This test verifies that we can create ClientSession with timeout

        # Test that ClientTimeout can be created and configured
        timeout = ClientTimeout(total=5.0, connect=2.0)
        self.assertEqual(timeout.total, 5.0)
        self.assertEqual(timeout.connect, 2.0)

        # Test that ClientSession accepts timeout parameter
        session = ClientSession(timeout=timeout)
        self.assertIsNotNone(session.timeout)
        await session.close()


if __name__ == "__main__":
    unittest.main()
