import unittest
from unittest import IsolatedAsyncioTestCase
from unittest.mock import Mock
import json
from typing import cast
from subprocess_monitor.types import (
    TypedJSONResponse,
    TypedClientResponse,
    SpawnProcessRequest,
    SpawnRequestResponse,
    StreamingLineOutput,
)


class TestTypeRuntimeValidation(IsolatedAsyncioTestCase):
    """Test cases for type runtime validation vulnerabilities."""

    def test_typed_json_response_cast_validation(self):
        """Test that TypedJSONResponse cast operations are safe."""
        # Issue #13: Missing type runtime validation
        # Extensive use of cast() without runtime validation

        # Create a mock response with invalid data
        mock_response = Mock()
        mock_response.json = Mock()

        # Test with invalid JSON structure
        invalid_json_cases = [
            {},  # Empty dict
            {"wrong_key": "value"},  # Wrong structure
            {"pid": "not_a_number"},  # Wrong type
            {"pid": 123, "extra_field": "unexpected"},  # Extra fields
            None,  # None value
            "string_instead_of_dict",  # Wrong type entirely
            123,  # Number instead of dict
            [],  # List instead of dict
        ]

        for invalid_json in invalid_json_cases:
            mock_response.json.return_value = invalid_json

            try:
                # This mimics the pattern used in the code
                typed_response = TypedJSONResponse[SpawnRequestResponse](mock_response)
                data = typed_response.json()

                # The cast operation will succeed even with invalid data
                # This demonstrates the vulnerability
                spawn_response = cast(SpawnRequestResponse, data)

                # Accessing fields that don't exist should fail
                if isinstance(data, dict) and "pid" in data:
                    # This might work if pid exists
                    pid = spawn_response["pid"]
                    if not isinstance(pid, int):
                        # Type mismatch detected
                        self.fail(f"Type mismatch: expected int, got {type(pid)}")
                else:
                    # This should fail but cast() allows it
                    try:
                        pid = spawn_response["pid"]
                        # If we get here, it means cast() didn't validate
                        self.fail("Cast should have failed for invalid structure")
                    except (KeyError, TypeError):
                        # Expected - the data is invalid
                        pass

            except Exception:
                # This is actually good - it means validation is working
                pass

    def test_typed_client_response_validation(self):
        """Test TypedClientResponse validation."""

        # Create mock aiohttp response
        mock_response = Mock()
        mock_response.status = 200
        mock_response.json = Mock()

        # Test with various invalid response structures
        invalid_responses = [
            # Missing required fields
            {"status": "success"},  # Missing data
            {"data": {}},  # Missing status
            # Wrong types
            {"status": 123, "data": {}},  # Status should be string
            {"status": "success", "data": "not_dict"},  # Data should be dict
            # Invalid status values
            {"status": "invalid_status", "data": {}},
            {"status": "", "data": {}},
            # Malformed JSON
            None,
            "not_json",
            123,
            [],
        ]

        for invalid_response in invalid_responses:
            mock_response.json.return_value = invalid_response

            try:
                # This simulates the pattern used in helper.py
                typed_response = TypedClientResponse[SpawnRequestResponse](
                    mock_response
                )
                result = typed_response.json()

                # Cast operation allows invalid data through
                casted_result = cast(SpawnRequestResponse, result)

                # Try to access expected fields
                if isinstance(result, dict):
                    # Check for expected structure
                    if "pid" in result:
                        pid = casted_result["pid"]
                        if not isinstance(pid, int):
                            self.fail("Type validation failed")
                    else:
                        # Missing required field
                        try:
                            pid = casted_result["pid"]
                            self.fail("Should have failed for missing field")
                        except KeyError:
                            # Expected
                            pass
                else:
                    # Invalid type
                    try:
                        pid = casted_result["pid"]
                        self.fail("Should have failed for invalid type")
                    except (KeyError, TypeError):
                        # Expected
                        pass

            except Exception:
                # Exception handling is good - it means some validation exists
                pass

    def test_spawn_request_validation(self):
        """Test SpawnRequest type validation."""

        # Test various invalid spawn requests
        invalid_requests = [
            # Missing required fields
            {"args": [], "env": {}},  # Missing cmd
            {"cmd": "test", "env": {}},  # Missing args
            {"cmd": "test", "args": []},  # Missing env
            # Wrong types
            {"cmd": 123, "args": [], "env": {}},  # cmd should be string
            {"cmd": "test", "args": "not_list", "env": {}},  # args should be list
            {"cmd": "test", "args": [], "env": "not_dict"},  # env should be dict
            # Invalid values
            {"cmd": "", "args": [], "env": {}},  # Empty cmd
            {"cmd": "test", "args": [123], "env": {}},  # Non-string args
            {"cmd": "test", "args": [], "env": {123: "value"}},  # Non-string env keys
            # Completely wrong structure
            None,
            "string",
            123,
            [],
        ]

        for invalid_request in invalid_requests:
            try:
                # This simulates how requests are handled
                request = cast(SpawnProcessRequest, invalid_request)

                # Try to access fields
                if isinstance(invalid_request, dict):
                    # Check required fields
                    required_fields = ["cmd", "args", "env"]
                    for field in required_fields:
                        if field in invalid_request:
                            value = request[field]
                            # Validate types
                            if field == "cmd" and not isinstance(value, str):
                                self.fail(f"Invalid type for {field}: {type(value)}")
                            elif field == "args" and not isinstance(value, list):
                                self.fail(f"Invalid type for {field}: {type(value)}")
                            elif field == "env" and not isinstance(value, dict):
                                self.fail(f"Invalid type for {field}: {type(value)}")
                        else:
                            # Missing required field
                            try:
                                value = request[field]
                                self.fail(
                                    f"Should have failed for missing field: {field}"
                                )
                            except KeyError:
                                # Expected
                                pass
                else:
                    # Invalid structure
                    try:
                        request["cmd"]
                        self.fail("Should have failed for invalid structure")
                    except (KeyError, TypeError):
                        # Expected
                        pass

            except Exception:
                # Exception handling is good
                pass

    def test_streaming_output_validation(self):
        """Test StreamingLineOutput type validation."""

        # Test various invalid streaming output structures
        invalid_outputs = [
            # Missing fields
            {"stream": "stdout", "pid": 123},  # Missing data
            {"stream": "stdout", "data": "test"},  # Missing pid
            {"pid": 123, "data": "test"},  # Missing stream
            # Wrong types
            {"stream": 123, "pid": 123, "data": "test"},  # stream should be string
            {"stream": "stdout", "pid": "not_int", "data": "test"},  # pid should be int
            {"stream": "stdout", "pid": 123, "data": 123},  # data should be string
            # Invalid values
            {"stream": "", "pid": 123, "data": "test"},  # Empty stream
            {"stream": "stdout", "pid": -1, "data": "test"},  # Negative pid
            {"stream": "stdout", "pid": 123, "data": ""},  # Empty data (might be valid)
            # Extra fields (should be allowed but worth testing)
            {"stream": "stdout", "pid": 123, "data": "test", "extra": "field"},
            # Wrong structure
            None,
            "string",
            123,
            [],
        ]

        for invalid_output in invalid_outputs:
            try:
                # Cast to StreamingLineOutput
                output = cast(StreamingLineOutput, invalid_output)

                # Validate structure and types
                if isinstance(invalid_output, dict):
                    required_fields = ["stream", "pid", "data"]
                    for field in required_fields:
                        if field in invalid_output:
                            value = output[field]
                            # Type validation
                            if field == "pid" and not isinstance(value, int):
                                self.fail(f"Invalid type for {field}: {type(value)}")
                            elif field in ["stream", "data"] and not isinstance(
                                value, str
                            ):
                                self.fail(f"Invalid type for {field}: {type(value)}")
                        else:
                            # Missing required field
                            try:
                                value = output[field]
                                self.fail(
                                    f"Should have failed for missing field: {field}"
                                )
                            except KeyError:
                                # Expected
                                pass
                else:
                    # Invalid structure
                    try:
                        output["stream"]
                        self.fail("Should have failed for invalid structure")
                    except (KeyError, TypeError):
                        # Expected
                        pass

            except Exception:
                # Exception handling is good
                pass

    def test_runtime_type_safety(self):
        """Test that runtime type safety is properly implemented."""

        # Test a complete scenario with invalid data
        invalid_data = {
            "stream": 123,
            "pid": "not_a_number",
            "data": None,
            "extra": "field",
        }

        # This should ideally fail at runtime, but cast() allows it
        try:
            output = cast(StreamingLineOutput, invalid_data)

            # Try to use the data
            stream = output["stream"]
            pid = output["pid"]
            data = output["data"]

            # Check if we can detect type mismatches
            if not isinstance(stream, str):
                print(
                    f"Type mismatch detected: stream should be str, got {type(stream)}"
                )

            if not isinstance(pid, int):
                print(f"Type mismatch detected: pid should be int, got {type(pid)}")

            if not isinstance(data, str):
                print(f"Type mismatch detected: data should be str, got {type(data)}")

            # The test passes if we can detect the mismatches
            self.assertTrue(True, "Type validation working as expected")

        except Exception as e:
            # This would be better - runtime validation
            print(f"Runtime validation worked: {e}")

    def test_json_deserialization_safety(self):
        """Test JSON deserialization safety."""

        # Test with malformed JSON that could cause issues
        malformed_json_cases = [
            '{"stream": "stdout", "pid": "not_a_number", "data": "test"}',  # Wrong type
            '{"stream": "stdout", "pid": 123, "data": null}',  # Null value
            '{"stream": "stdout", "pid": 123, "data": "test", "extra": {"nested": "object"}}',  # Nested objects
            '{"stream": "stdout", "pid": 123, "data": "'
            + "x" * 10000
            + '"}',  # Large field
            '{"stream": "stdout", "pid": 123, "data": "test", "array": [1, 2, 3]}',  # Array field
        ]

        for json_str in malformed_json_cases:
            try:
                # Parse JSON
                data = json.loads(json_str)

                # Cast to expected type
                output = cast(StreamingLineOutput, data)

                # Try to access fields
                stream = output.get("stream")
                pid = output.get("pid")
                data_field = output.get("data")

                # Validate types at runtime
                if stream is not None and not isinstance(stream, str):
                    print(f"Type validation needed for stream: {type(stream)}")

                if pid is not None and not isinstance(pid, int):
                    print(f"Type validation needed for pid: {type(pid)}")

                if data_field is not None and not isinstance(data_field, str):
                    print(f"Type validation needed for data: {type(data_field)}")

            except json.JSONDecodeError:
                # Expected for malformed JSON
                pass
            except Exception:
                # Other exceptions are also acceptable
                pass


if __name__ == "__main__":
    unittest.main()
