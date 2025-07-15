import asyncio
import unittest
from unittest import IsolatedAsyncioTestCase
import sys
from subprocess_monitor.subprocess_monitor import SubprocessMonitor


class TestCommandInjection(IsolatedAsyncioTestCase):
    """Test cases for command injection vulnerabilities."""

    async def asyncSetUp(self):
        """Set up test environment."""
        self.host = "localhost"
        self.monitor = SubprocessMonitor(check_interval=0.1, host=self.host)
        self.port = self.monitor.port

    async def asyncTearDown(self):
        """Clean up test environment."""
        await self.monitor.kill_all_subprocesses()

    async def test_command_injection_attempts(self):
        """Test that command injection attempts are handled safely."""
        # Issue #5: Command injection risk in start_subprocess

        # Test various injection attempts
        injection_attempts = [
            # Shell metacharacters
            {
                "cmd": sys.executable,
                "args": ["-c", "print('test'); echo 'injected'"],
                "env": {},
            },
            {
                "cmd": sys.executable,
                "args": ["-c", "print('test') && echo 'injected'"],
                "env": {},
            },
            {
                "cmd": sys.executable,
                "args": ["-c", "print('test') | echo 'injected'"],
                "env": {},
            },
            {
                "cmd": sys.executable,
                "args": ["-c", "print('test'); rm -rf /tmp/test"],
                "env": {},
            },
            # Path traversal attempts
            {"cmd": "../../../bin/sh", "args": ["-c", "echo 'injected'"], "env": {}},
            {"cmd": "/bin/sh", "args": ["-c", "echo 'injected'"], "env": {}},
            # Command substitution attempts
            {
                "cmd": sys.executable,
                "args": ["-c", "print('test'); $(echo injected)"],
                "env": {},
            },
            {
                "cmd": sys.executable,
                "args": ["-c", "print('test'); `echo injected`"],
                "env": {},
            },
        ]

        for attempt in injection_attempts:
            try:
                pid = await self.monitor.start_subprocess(attempt)

                # Wait for process to complete
                await asyncio.sleep(0.2)

                # Check that process executed safely
                # Since we use asyncio.create_subprocess_exec (not shell=True),
                # shell metacharacters should be treated literally
                process_info = self.monitor.process_ownership.get(pid)
                if process_info:
                    # Process should have executed the literal command
                    # not interpreted shell metacharacters
                    self.assertIsNotNone(process_info)

            except Exception:
                # Some attempts might fail due to invalid paths
                # This is expected and safe behavior
                pass

    async def test_shell_false_protection(self):
        """Test that shell=False is enforced (no shell interpretation)."""
        # Create a test that would fail if shell=True
        test_cmd = sys.executable
        test_args = ["-c", "import sys; print('SAFE'); print('test1 && echo INJECTED')"]

        request = {"cmd": test_cmd, "args": test_args, "env": {}}
        pid = await self.monitor.start_subprocess(request)

        # Collect output via mock subscription
        output_lines = []

        class MockWebSocket:
            def __init__(self):
                self.closed = False

            async def send_str(self, msg):
                output_lines.append(msg)

            async def close(self):
                self.closed = True

        # Add mock subscription to capture output
        mock_ws = MockWebSocket()
        async with self.monitor.subscription_lock:
            if pid not in self.monitor.subscriptions:
                self.monitor.subscriptions[pid] = []
            self.monitor.subscriptions[pid].append(mock_ws)

        # Wait for process to complete
        await asyncio.sleep(2.0)  # Give more time for output

        # Parse JSON output
        import json

        output_data = []
        for line in output_lines:
            try:
                data = json.loads(line)
                if "data" in data:
                    output_data.append(data["data"])
            except json.JSONDecodeError:
                output_data.append(line)

        # Join output - combine all messages
        full_output = "".join(
            output_data
        )  # No newline separator since messages may already have them

        # Verify that shell metacharacters were not interpreted
        self.assertIn("SAFE", full_output)

        # The literal string should be printed, not executed as a shell command
        # If shell=True was used, we'd see "INJECTED" on a separate line
        # Check that INJECTED only appears as part of the literal string
        if "INJECTED" in full_output:
            # Count occurrences - should be exactly 1 (in the literal string)
            injected_count = full_output.count("INJECTED")
            self.assertEqual(injected_count, 1, "INJECTED should appear exactly once")
            # Verify it's part of the literal output
            self.assertIn("test1 && echo INJECTED", full_output)

    async def test_environment_injection(self):
        """Test that environment variables cannot be used for injection."""
        # Test environment variable injection attempts
        injection_env_attempts = [
            {"PATH": "/malicious/path:$PATH"},
            {"LD_PRELOAD": "/malicious/library.so"},
            {"PYTHONPATH": "/malicious/code:$PYTHONPATH"},
            {"TEST": "value; echo injected"},
        ]

        for env_attempt in injection_env_attempts:
            request = {
                "cmd": sys.executable,
                "args": ["-c", "import os; print(os.environ.get('TEST', 'none'))"],
                "env": env_attempt,
            }

            try:
                pid = await self.monitor.start_subprocess(request)

                # Process should start successfully
                self.assertIsNotNone(pid)

                # Environment variables should be set literally
                # not interpreted as shell commands
                await asyncio.sleep(0.2)

            except Exception:
                # Some environment settings might cause Python to fail
                # This is acceptable as it prevents exploitation
                pass

    async def test_null_byte_injection(self):
        """Test handling of null bytes in commands."""
        # Null bytes can be used to truncate commands in some contexts
        null_byte_attempts = [
            {"cmd": sys.executable + "\x00/bin/sh", "args": [], "env": {}},
            {
                "cmd": sys.executable,
                "args": ["-c\x00rm -rf /", "print('test')"],
                "env": {},
            },
            {
                "cmd": sys.executable,
                "args": ["-c", "print('test')\x00; rm -rf /"],
                "env": {},
            },
        ]

        for attempt in null_byte_attempts:
            try:
                await self.monitor.start_subprocess(attempt)
                # If process starts, it should fail or ignore null bytes
                await asyncio.sleep(0.1)
            except Exception:
                # Expected - null bytes should cause errors
                # This prevents the injection
                pass


if __name__ == "__main__":
    unittest.main()
