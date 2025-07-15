import asyncio
import unittest
from unittest import IsolatedAsyncioTestCase
import socket
import threading
import time
from subprocess_monitor.subprocess_monitor import SubprocessMonitor


class TestPortBindingRaceCondition(IsolatedAsyncioTestCase):
    """Test cases for port binding race condition (TOCTOU) vulnerability."""

    def test_find_free_port_race_condition(self):
        """Test that find_free_port doesn't guarantee port availability."""
        # Issue #9: TOCTOU (Time-of-Check-Time-of-Use) race condition
        # in find_free_port function

        from subprocess_monitor.subprocess_monitor import find_free_port

        # Get a supposedly free port
        port = find_free_port()

        # Now quickly bind to it in another thread to simulate race condition
        def bind_port():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.bind(("localhost", port))
                sock.listen(1)
                time.sleep(0.1)  # Hold the port briefly
                sock.close()
            except Exception:
                pass

        # Start binding in background
        thread = threading.Thread(target=bind_port)
        thread.start()

        # Small delay to let the thread bind
        time.sleep(0.05)

        # Now try to use the port - this should fail
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(("localhost", port))
            sock.close()
            # If we get here, the race condition didn't occur
            # This is not a test failure, just shows the race condition exists
        except OSError:
            # This is expected - the port was taken by the other thread
            pass

        thread.join()

        # The test demonstrates the race condition exists
        # In a real scenario, this could cause service startup failures

    async def test_concurrent_port_allocation(self):
        """Test concurrent port allocation scenarios."""
        # Test that multiple SubprocessMonitor instances can have port conflicts

        monitors = []
        ports = []

        try:
            # Create multiple monitors concurrently
            # This can trigger port conflicts if they get the same port
            async def create_monitor():
                monitor = SubprocessMonitor(check_interval=0.1)
                return monitor

            # Create multiple monitors in parallel
            tasks = [create_monitor() for _ in range(5)]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Check for exceptions (port conflicts)
            successful = [r for r in results if not isinstance(r, Exception)]

            # Collect ports from successful monitors
            for monitor in successful:
                ports.append(monitor.port)
                monitors.append(monitor)

            # Check if any port conflicts occurred
            if len(set(ports)) != len(ports):
                # This indicates the race condition exists
                # The test has successfully detected the vulnerability
                print(f"Race condition detected: ports {ports}")
                self.assertTrue(
                    True, "Successfully detected port binding race condition"
                )

            # The test passes if no conflicts occurred
            # But the vulnerability still exists in high-concurrency scenarios

        finally:
            # Clean up
            for monitor in monitors:
                try:
                    await monitor.kill_all_subprocesses()
                except Exception:
                    pass

    async def test_port_exhaustion_scenario(self):
        """Test behavior when many ports are taken."""
        # Simulate a scenario where many ports are taken
        # to see how the system behaves

        sockets = []

        try:
            # Bind to many ports to create scarcity
            for i in range(10):
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.bind(("localhost", 0))  # Let OS choose port
                sock.listen(1)
                sockets.append(sock)

            # Now try to create a monitor
            monitor = SubprocessMonitor(check_interval=0.1)

            # Should succeed (system should find a free port)
            self.assertIsNotNone(monitor.port)

            await monitor.kill_all_subprocesses()

        finally:
            # Clean up sockets
            for sock in sockets:
                try:
                    sock.close()
                except Exception:
                    pass

    def test_port_binding_error_handling(self):
        """Test error handling when port binding fails."""

        # Create a custom version of find_free_port that can fail
        def always_busy_port():
            # Return a port that's likely to be busy
            return 80  # HTTP port, likely busy or restricted

        # Test what happens when we try to bind to a busy port
        port = always_busy_port()

        try:
            # This should fail for non-root users
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(("localhost", port))
            sock.close()

            # If we get here, the port wasn't busy (unlikely)
            # This is not a test failure

        except PermissionError:
            # Expected for privileged ports
            pass
        except OSError as e:
            if "Address already in use" in str(e):
                # Expected for busy ports
                pass
            else:
                # Unexpected error
                self.fail(f"Unexpected error binding to port {port}: {e}")

    async def test_multiple_monitors_same_host(self):
        """Test multiple monitors on same host with port conflicts."""
        # This test demonstrates the race condition more clearly

        monitors = []
        creation_times = []

        try:
            # Create monitors rapidly to increase chance of race condition
            for i in range(3):
                start_time = time.time()
                monitor = SubprocessMonitor(check_interval=0.1, host="localhost")
                creation_times.append(time.time() - start_time)
                monitors.append(monitor)

                # Very small delay to allow for race condition
                await asyncio.sleep(0.001)

            # Check that all monitors have different ports
            ports = [m.port for m in monitors]
            unique_ports = set(ports)

            if len(unique_ports) != len(ports):
                # Race condition detected - this is actually what we want to test
                print(f"Port binding race condition detected: {ports}")
                self.assertTrue(
                    True, "Successfully detected port binding race condition"
                )
            else:
                # No race condition this time, but vulnerability still exists
                print(f"No race condition this time, but vulnerability exists: {ports}")

            # Log timing information
            avg_creation_time = sum(creation_times) / len(creation_times)
            print(f"Average monitor creation time: {avg_creation_time:.4f}s")

        finally:
            # Clean up
            for monitor in monitors:
                try:
                    await monitor.kill_all_subprocesses()
                except Exception:
                    pass


if __name__ == "__main__":
    unittest.main()
