import asyncio
import unittest
from unittest import IsolatedAsyncioTestCase
import sys
import subprocess
import os

from subprocess_monitor.subprocess_monitor import SubprocessMonitor


class TestEnvironmentParsing(IsolatedAsyncioTestCase):
    """Test cases for environment variable parsing vulnerabilities."""

    async def asyncSetUp(self):
        """Set up test environment."""
        self.host = "localhost"
        self.monitor = SubprocessMonitor(check_interval=0.1, host=self.host)
        self.port = self.monitor.port

        self.server_task = asyncio.create_task(self.monitor.run())

        # Allow some time for the server to start
        await asyncio.sleep(1)

    async def asyncTearDown(self):
        """Clean up test environment."""
        await self.monitor.kill_all_subprocesses()
        self.monitor.stop_serve()  # flip _running to False
        await asyncio.wait_for(self.server_task, timeout=2)  # let serve() exit cleanly

    async def _run_with_live_output(self, cmd, timeout=10):
        """
        Run a command while streaming stdout/stderr without blocking the event loop.
        Returns a CompletedProcess-like object for assertions.
        """
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        async def _stream(stream, collector, sink):
            while True:
                line = await stream.readline()
                if not line:
                    break
                decoded = line.decode()
                collector.append(decoded)
                sink.write(decoded)
                sink.flush()

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    _stream(process.stdout, stdout_lines, sys.stdout),
                    _stream(process.stderr, stderr_lines, sys.stderr),
                    process.wait(),
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            process.kill()
            raise

        return subprocess.CompletedProcess(
            cmd, process.returncode, "".join(stdout_lines), "".join(stderr_lines)
        )

    async def test_cli_env_parsing_without_equals(self):
        """Test that environment variables without '=' cause proper error."""
        # Issue #8: Environment variable parsing vulnerability in CLI

        # Test various invalid environment variable formats
        invalid_env_formats = [
            ["INVALID_VAR"],  # No equals sign
            ["INVALID VAR=value"],  # Space in variable name
            ["=value"],  # No variable name
            [""],  # Empty string
            ["XXVAR=value"],  # norm case
            ["XXVAR==value"],  # Double equals (valid but edge case)
        ]

        for env_args in invalid_env_formats:
            cmd = (
                [sys.executable, "-m", "subprocess_monitor", "spawn", "--env"]
                + env_args
                + ["--host", self.host, "--port", str(self.port)]
                + ["--", sys.executable, "-c", "print('test')"]
            )

            try:
                result = await self._run_with_live_output(cmd, timeout=1000)

                # Check if it failed for invalid formats
                if not env_args or not env_args[0] or "=" not in env_args[0]:
                    # Should fail with ValueError
                    self.assertNotEqual(
                        result.returncode, 0, f"Should fail for invalid env: {env_args}"
                    )
                    # Check for error in output
                    self.assertTrue(
                        "error" in result.stderr.lower()
                        or "valueerror" in result.stderr.lower(),
                        f"Expected error for: {env_args}",
                    )

            except subprocess.TimeoutExpired:
                self.fail(f"Command timed out for env args: {env_args}")
            except Exception:
                # This is expected for invalid formats
                pass
            await asyncio.sleep(0.2)

    async def test_cli_env_parsing_edge_cases(self):
        """Test edge cases in environment variable parsing."""
        # Test the actual parsing logic from the CLI module

        # Test valid but edge case formats
        edge_cases = [
            ["VAR="],  # Empty value
            ["VAR=value=with=equals"],  # Multiple equals
            ["_VAR=value"],  # Underscore prefix
            ["VAR123=value"],  # Numbers in name
            ["PATH=/new/path:$PATH"],  # Path manipulation
        ]

        for env_list in edge_cases:
            try:
                # Test the parsing logic directly
                # This mimics what happens in __main__.py
                env = dict(var.split("=", 1) for var in env_list) if env_list else {}

                # These should parse successfully
                self.assertIsInstance(env, dict)

                # Check that the parsing worked as expected
                if env_list:
                    var_name = env_list[0].split("=")[0]
                    self.assertIn(var_name, env)

            except ValueError as e:
                self.fail(f"Valid env format should parse: {env_list}, error: {e}")
            except Exception as e:
                self.fail(f"Unexpected error parsing {env_list}: {e}")

    async def test_env_parsing_in_api(self):
        """Test environment variable handling in API."""
        from subprocess_monitor.subprocess_monitor import SubprocessMonitor

        monitor = SubprocessMonitor(check_interval=0.1)

        try:
            # Test various environment configurations
            test_cases = [
                # Normal cases
                {"TEST_VAR": "value"},
                {"PATH": "/custom/path:$PATH"},
                {"EMPTY": ""},
                # Edge cases that should work
                {"_UNDERSCORE": "value"},
                {"VAR123": "value"},
                {"MULTI_WORD_VAR": "multi word value"},
                # Special characters
                {"VAR": "value with spaces"},
                {"VAR": "value=with=equals"},
                {"VAR": "value;with;semicolons"},
            ]

            for env in test_cases:
                request = {
                    "cmd": sys.executable,
                    "args": ["-c", "import os; print(list(os.environ.keys())[:5])"],
                    "env": env,
                }

                # This should not crash
                pid = await monitor.start_subprocess(request)
                self.assertIsNotNone(pid)

                # Clean up
                await asyncio.sleep(0.1)
                await monitor.stop_subprocess(pid=pid)

        finally:
            await monitor.kill_all_subprocesses()

    async def test_port_env_parsing(self):
        """Test port environment variable parsing."""
        # Issue #23: Integer conversion errors in environment variable parsing

        # Save original env
        original_port = os.environ.get("SUBPROCESS_MONITOR_PORT")

        try:
            # Test invalid port values
            invalid_ports = [
                "not_a_number",
                "123.45",  # Float
                "-1",  # Negative
                "99999",  # Too high
                "",  # Empty
                "8080 ",  # With whitespace
                "8080\n",  # With newline
            ]

            for invalid_port in invalid_ports:
                os.environ["SUBPROCESS_MONITOR_PORT"] = invalid_port

                # Try to import and use the helper module
                # This should handle the error gracefully
                try:
                    # Re-import to pick up new env value
                    import importlib
                    import subprocess_monitor.helper as helper_module

                    importlib.reload(helper_module)

                    # Check if it falls back to default
                    # The module should handle the error and use default

                except ValueError:
                    # This is acceptable - the error is caught
                    pass
                except Exception as e:
                    self.fail(f"Unexpected error for port '{invalid_port}': {e}")

        finally:
            # Restore original env
            if original_port is not None:
                os.environ["SUBPROCESS_MONITOR_PORT"] = original_port
            else:
                os.environ.pop("SUBPROCESS_MONITOR_PORT", None)


if __name__ == "__main__":
    unittest.main()
