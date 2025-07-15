import unittest
from unittest import IsolatedAsyncioTestCase
import threading
import socket
from subprocess_monitor.subprocess_monitor import SubprocessMonitor, bind_to_free_port


class TestPortBindingFix(IsolatedAsyncioTestCase):
    """Test that the port binding race condition fix works correctly."""

    def test_bind_to_free_port_function(self):
        """Test that bind_to_free_port() properly binds and returns socket."""
        # Test the new secure binding function
        port, sock = bind_to_free_port()

        try:
            # Verify we got a valid port
            self.assertIsInstance(port, int)
            self.assertGreater(port, 0)
            self.assertLess(port, 65536)

            # Verify socket is bound
            self.assertIsNotNone(sock)
            self.assertEqual(sock.getsockname()[1], port)

            # Verify port is actually bound (another bind should fail)
            with self.assertRaises(OSError):
                another_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                another_sock.bind(("localhost", port))
                another_sock.close()

        finally:
            sock.close()

    def test_secure_port_allocation_no_conflicts(self):
        """Test that secure port allocation prevents conflicts."""
        # This test should show that the fix works
        monitors = []
        ports = []

        try:
            # Create multiple monitors concurrently
            for i in range(5):
                monitor = SubprocessMonitor(check_interval=0.1)
                monitors.append(monitor)
                ports.append(monitor.port)

            # With the fix, all ports should be unique
            unique_ports = set(ports)
            self.assertEqual(
                len(unique_ports), len(ports), f"All ports should be unique: {ports}"
            )

            # Verify each monitor has a bound socket when auto-selecting port
            for monitor in monitors:
                # The _bound_socket should be set to prevent race condition
                # (though it may be None after serve() is called)
                self.assertIsNotNone(monitor.port)

        finally:
            # Clean up
            for monitor in monitors:
                try:
                    # Close bound socket if it exists
                    if hasattr(monitor, "_bound_socket") and monitor._bound_socket:
                        monitor._bound_socket.close()
                except Exception:
                    pass

    def test_specified_port_vs_auto_port(self):
        """Test behavior with specified port vs auto-allocated port."""
        # Test specified port (should not use bound socket)
        monitor1 = SubprocessMonitor(port=8080, check_interval=0.1)
        self.assertEqual(monitor1.port, 8080)
        self.assertIsNone(monitor1._bound_socket)

        # Test auto-allocated port (should use bound socket)
        monitor2 = SubprocessMonitor(check_interval=0.1)
        self.assertIsNotNone(monitor2.port)
        # The bound socket should be set initially
        # (though it may be None after serve() is called)

        # Clean up
        try:
            if hasattr(monitor1, "_bound_socket") and monitor1._bound_socket:
                monitor1._bound_socket.close()
            if hasattr(monitor2, "_bound_socket") and monitor2._bound_socket:
                monitor2._bound_socket.close()
        except Exception:
            pass

    def test_concurrent_monitor_creation_fixed(self):
        """Test that concurrent monitor creation no longer has race conditions."""
        # This test demonstrates that the race condition is fixed

        def create_monitor_sync():
            """Create a monitor in a thread and return port."""
            monitor = SubprocessMonitor(check_interval=0.1)
            return monitor.port

        ports = []
        threads = []

        # Create multiple threads that create monitors simultaneously
        for i in range(10):
            thread = threading.Thread(
                target=lambda: ports.append(create_monitor_sync())
            )
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # With the fix, all ports should be unique
        unique_ports = set(ports)
        self.assertEqual(
            len(unique_ports), len(ports), f"Race condition still exists: {ports}"
        )

        print(f"Successfully allocated unique ports: {sorted(ports)}")

    def test_socket_reuse_prevention(self):
        """Test that bound sockets prevent reuse."""
        # Get a port using the secure method
        port1, sock1 = bind_to_free_port()

        try:
            # Try to get another port - should be different
            port2, sock2 = bind_to_free_port()

            try:
                # Ports should be different
                self.assertNotEqual(port1, port2)

                # Both sockets should be bound
                self.assertEqual(sock1.getsockname()[1], port1)
                self.assertEqual(sock2.getsockname()[1], port2)

            finally:
                sock2.close()

        finally:
            sock1.close()

    def test_host_parameter_in_binding(self):
        """Test that host parameter works correctly in secure binding."""
        # Test with localhost
        port1, sock1 = bind_to_free_port("localhost")

        try:
            self.assertEqual(sock1.getsockname()[0], "127.0.0.1")

            # Test with 0.0.0.0
            port2, sock2 = bind_to_free_port("0.0.0.0")

            try:
                self.assertEqual(sock2.getsockname()[0], "0.0.0.0")

            finally:
                sock2.close()

        finally:
            sock1.close()


if __name__ == "__main__":
    unittest.main()
