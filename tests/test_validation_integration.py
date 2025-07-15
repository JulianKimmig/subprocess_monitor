import unittest
from unittest import IsolatedAsyncioTestCase
from subprocess_monitor.validation import (
    safe_validate_spawn_process_request,
    safe_validate_spawn_request_response,
    safe_validate_stop_process_request,
    safe_validate_stop_request_response,
    safe_validate_subprocess_index_response,
    safe_validate_streaming_line_output,
    safe_validate_subscribe_requests,
    ValidationError,
)


class TestValidationIntegration(IsolatedAsyncioTestCase):
    """Test integration of validation functions with actual data structures."""

    def test_spawn_process_request_validation_success(self):
        """Test successful validation of valid SpawnProcessRequest."""
        valid_request = {
            "cmd": "echo",
            "args": ["hello", "world"],
            "env": {"PATH": "/usr/bin", "HOME": "/home/user"},
        }

        # Should not raise an exception
        result = safe_validate_spawn_process_request(valid_request)
        self.assertEqual(result, valid_request)

    def test_spawn_process_request_validation_failure(self):
        """Test validation failure for invalid SpawnProcessRequest."""
        invalid_requests = [
            {},  # Missing all fields
            {"cmd": "echo"},  # Missing args and env
            {"cmd": "", "args": [], "env": {}},  # Empty cmd
            {"cmd": 123, "args": [], "env": {}},  # Wrong cmd type
            {"cmd": "echo", "args": "not_list", "env": {}},  # Wrong args type
            {"cmd": "echo", "args": [123], "env": {}},  # Wrong args element type
            {"cmd": "echo", "args": [], "env": "not_dict"},  # Wrong env type
            {"cmd": "echo", "args": [], "env": {123: "value"}},  # Wrong env key type
            {"cmd": "echo", "args": [], "env": {"key": 123}},  # Wrong env value type
        ]

        for invalid_request in invalid_requests:
            with self.assertRaises(ValidationError):
                safe_validate_spawn_process_request(invalid_request)

    def test_spawn_request_response_validation_success(self):
        """Test successful validation of valid SpawnRequestResponse."""
        valid_responses = [
            {"status": "success", "pid": 12345},
            {"status": "failure", "error": "Command not found"},
        ]

        for valid_response in valid_responses:
            result = safe_validate_spawn_request_response(valid_response)
            self.assertEqual(result, valid_response)

    def test_spawn_request_response_validation_failure(self):
        """Test validation failure for invalid SpawnRequestResponse."""
        invalid_responses = [
            {},  # Missing status
            {"status": "invalid"},  # Invalid status value
            {"status": "success"},  # Missing pid for success
            {"status": "success", "pid": "not_int"},  # Wrong pid type
            {"status": "success", "pid": -1},  # Invalid pid value
            {"status": "failure"},  # Missing error for failure
            {"status": "failure", "error": 123},  # Wrong error type
        ]

        for invalid_response in invalid_responses:
            with self.assertRaises(ValidationError):
                safe_validate_spawn_request_response(invalid_response)

    def test_stop_process_request_validation_success(self):
        """Test successful validation of valid StopProcessRequest."""
        valid_request = {"pid": 12345}

        result = safe_validate_stop_process_request(valid_request)
        self.assertEqual(result, valid_request)

    def test_stop_process_request_validation_failure(self):
        """Test validation failure for invalid StopProcessRequest."""
        invalid_requests = [
            {},  # Missing pid
            {"pid": "not_int"},  # Wrong pid type
            {"pid": -1},  # Invalid pid value
            {"pid": 0},  # Invalid pid value
        ]

        for invalid_request in invalid_requests:
            with self.assertRaises(ValidationError):
                safe_validate_stop_process_request(invalid_request)

    def test_stop_request_response_validation_success(self):
        """Test successful validation of valid StopRequestResponse."""
        valid_responses = [
            {"status": "success"},
            {"status": "failure", "error": "Process not found"},
        ]

        for valid_response in valid_responses:
            result = safe_validate_stop_request_response(valid_response)
            self.assertEqual(result, valid_response)

    def test_stop_request_response_validation_failure(self):
        """Test validation failure for invalid StopRequestResponse."""
        invalid_responses = [
            {},  # Missing status
            {"status": "invalid"},  # Invalid status value
            {"status": "failure"},  # Missing error for failure
            {"status": "failure", "error": 123},  # Wrong error type
        ]

        for invalid_response in invalid_responses:
            with self.assertRaises(ValidationError):
                safe_validate_stop_request_response(invalid_response)

    def test_subprocess_index_response_validation_success(self):
        """Test successful validation of valid SubProcessIndexResponse."""
        valid_responses = [
            [],  # Empty list
            [12345],  # Single PID
            [12345, 67890, 11111],  # Multiple PIDs
        ]

        for valid_response in valid_responses:
            result = safe_validate_subprocess_index_response(valid_response)
            self.assertEqual(result, valid_response)

    def test_subprocess_index_response_validation_failure(self):
        """Test validation failure for invalid SubProcessIndexResponse."""
        invalid_responses = [
            "not_list",  # Wrong type
            [12345, "not_int"],  # Wrong element type
            [12345, -1],  # Invalid pid value
            [12345, 0],  # Invalid pid value
        ]

        for invalid_response in invalid_responses:
            with self.assertRaises(ValidationError):
                safe_validate_subprocess_index_response(invalid_response)

    def test_streaming_line_output_validation_success(self):
        """Test successful validation of valid StreamingLineOutput."""
        valid_outputs = [
            {"stream": "stdout", "pid": 12345, "data": "Hello world"},
            {"stream": "stderr", "pid": 67890, "data": "Error message"},
            {"stream": "stdout", "pid": 11111, "data": ""},  # Empty data is valid
        ]

        for valid_output in valid_outputs:
            result = safe_validate_streaming_line_output(valid_output)
            self.assertEqual(result, valid_output)

    def test_streaming_line_output_validation_failure(self):
        """Test validation failure for invalid StreamingLineOutput."""
        invalid_outputs = [
            {},  # Missing all fields
            {"stream": "stdout", "pid": 12345},  # Missing data
            {"stream": "stdout", "data": "test"},  # Missing pid
            {"pid": 12345, "data": "test"},  # Missing stream
            {"stream": 123, "pid": 12345, "data": "test"},  # Wrong stream type
            {"stream": "invalid", "pid": 12345, "data": "test"},  # Invalid stream value
            {"stream": "stdout", "pid": "not_int", "data": "test"},  # Wrong pid type
            {"stream": "stdout", "pid": -1, "data": "test"},  # Invalid pid value
            {"stream": "stdout", "pid": 12345, "data": 123},  # Wrong data type
        ]

        for invalid_output in invalid_outputs:
            with self.assertRaises(ValidationError):
                safe_validate_streaming_line_output(invalid_output)

    def test_subscribe_requests_validation_success(self):
        """Test successful validation of valid SubscribeRequests."""
        valid_requests = [
            {"pid": "12345"},
            {"pid": "67890"},
        ]

        for valid_request in valid_requests:
            result = safe_validate_subscribe_requests(valid_request)
            self.assertEqual(result, valid_request)

    def test_subscribe_requests_validation_failure(self):
        """Test validation failure for invalid SubscribeRequests."""
        invalid_requests = [
            {},  # Missing pid
            {"pid": 123},  # Wrong pid type (should be string)
            {"pid": "not_a_number"},  # Invalid pid string
            {"pid": "-1"},  # Invalid pid value
            {"pid": "0"},  # Invalid pid value
        ]

        for invalid_request in invalid_requests:
            with self.assertRaises(ValidationError):
                safe_validate_subscribe_requests(invalid_request)

    def test_validation_error_messages(self):
        """Test that validation errors have descriptive messages."""
        with self.assertRaises(ValidationError) as cm:
            safe_validate_spawn_process_request({"cmd": 123, "args": [], "env": {}})
        self.assertIn("cmd must be str", str(cm.exception))

        with self.assertRaises(ValidationError) as cm:
            safe_validate_spawn_request_response({"status": "invalid"})
        self.assertIn("must be 'success' or 'failure'", str(cm.exception))

        with self.assertRaises(ValidationError) as cm:
            safe_validate_streaming_line_output(
                {"stream": "invalid", "pid": 123, "data": "test"}
            )
        self.assertIn("must be one of", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
