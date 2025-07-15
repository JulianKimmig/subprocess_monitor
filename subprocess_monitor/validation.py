"""Runtime validation functions for TypedDict structures."""

from typing import Any, TypeGuard
import logging

from .types import (
    SpawnProcessRequest,
    SpawnRequestResponse,
    StopProcessRequest,
    StopRequestResponse,
    SubProcessIndexResponse,
    StreamingLineOutput,
    SubscribeRequests,
)

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when data validation fails."""

    pass


def validate_spawn_process_request(data: Any) -> TypeGuard[SpawnProcessRequest]:
    """Validate SpawnProcessRequest structure."""
    if not isinstance(data, dict):
        raise ValidationError(f"SpawnProcessRequest must be a dict, got {type(data)}")

    required_fields = ["cmd", "args", "env"]
    for field in required_fields:
        if field not in data:
            raise ValidationError(
                f"SpawnProcessRequest missing required field: {field}"
            )

    # Validate cmd
    if not isinstance(data["cmd"], str):
        raise ValidationError(
            f"SpawnProcessRequest.cmd must be str, got {type(data['cmd'])}"
        )

    if not data["cmd"].strip():
        raise ValidationError("SpawnProcessRequest.cmd cannot be empty")

    # Validate args
    if not isinstance(data["args"], list):
        raise ValidationError(
            f"SpawnProcessRequest.args must be list, got {type(data['args'])}"
        )

    for i, arg in enumerate(data["args"]):
        if not isinstance(arg, str):
            raise ValidationError(
                f"SpawnProcessRequest.args[{i}] must be str, got {type(arg)}"
            )

    # Validate env
    if not isinstance(data["env"], dict):
        raise ValidationError(
            f"SpawnProcessRequest.env must be dict, got {type(data['env'])}"
        )

    for key, value in data["env"].items():
        if not isinstance(key, str):
            raise ValidationError(
                f"SpawnProcessRequest.env key must be str, got {type(key)}"
            )
        if not isinstance(value, str):
            raise ValidationError(
                f"SpawnProcessRequest.env[{key}] must be str, got {type(value)}"
            )

    return True


def validate_spawn_request_response(data: Any) -> TypeGuard[SpawnRequestResponse]:
    """Validate SpawnRequestResponse structure."""
    if not isinstance(data, dict):
        raise ValidationError(f"SpawnRequestResponse must be a dict, got {type(data)}")

    if "status" not in data:
        raise ValidationError("SpawnRequestResponse missing required field: status")

    status = data["status"]
    if not isinstance(status, str):
        raise ValidationError(
            f"SpawnRequestResponse.status must be str, got {type(status)}"
        )

    if status == "success":
        if "pid" not in data:
            raise ValidationError(
                "SpawnRequestSuccessResponse missing required field: pid"
            )
        if not isinstance(data["pid"], int):
            raise ValidationError(
                f"SpawnRequestSuccessResponse.pid must be int, got {type(data['pid'])}"
            )
        if data["pid"] <= 0:
            raise ValidationError(
                f"SpawnRequestSuccessResponse.pid must be positive, got {data['pid']}"
            )
    elif status == "failure":
        if "error" not in data:
            raise ValidationError(
                "SpawnRequestFailureResponse missing required field: error"
            )
        if not isinstance(data["error"], str):
            raise ValidationError(
                f"SpawnRequestFailureResponse.error must be str, got {type(data['error'])}"
            )
    else:
        raise ValidationError(
            f"SpawnRequestResponse.status must be 'success' or 'failure', got {status}"
        )

    return True


def validate_stop_process_request(data: Any) -> TypeGuard[StopProcessRequest]:
    """Validate StopProcessRequest structure."""
    if not isinstance(data, dict):
        raise ValidationError(f"StopProcessRequest must be a dict, got {type(data)}")

    if "pid" not in data:
        raise ValidationError("StopProcessRequest missing required field: pid")

    if not isinstance(data["pid"], int):
        raise ValidationError(
            f"StopProcessRequest.pid must be int, got {type(data['pid'])}"
        )

    if data["pid"] <= 0:
        raise ValidationError(
            f"StopProcessRequest.pid must be positive, got {data['pid']}"
        )

    return True


def validate_stop_request_response(data: Any) -> TypeGuard[StopRequestResponse]:
    """Validate StopRequestResponse structure."""
    if not isinstance(data, dict):
        raise ValidationError(f"StopRequestResponse must be a dict, got {type(data)}")

    if "status" not in data:
        raise ValidationError("StopRequestResponse missing required field: status")

    status = data["status"]
    if not isinstance(status, str):
        raise ValidationError(
            f"StopRequestResponse.status must be str, got {type(status)}"
        )

    if status == "success":
        # No additional fields required for success
        pass
    elif status == "failure":
        if "error" not in data:
            raise ValidationError(
                "StopRequestFailureResponse missing required field: error"
            )
        if not isinstance(data["error"], str):
            raise ValidationError(
                f"StopRequestFailureResponse.error must be str, got {type(data['error'])}"
            )
    else:
        raise ValidationError(
            f"StopRequestResponse.status must be 'success' or 'failure', got {status}"
        )

    return True


def validate_subprocess_index_response(data: Any) -> TypeGuard[SubProcessIndexResponse]:
    """Validate SubProcessIndexResponse structure."""
    if not isinstance(data, list):
        raise ValidationError(
            f"SubProcessIndexResponse must be a list, got {type(data)}"
        )

    for i, pid in enumerate(data):
        if not isinstance(pid, int):
            raise ValidationError(
                f"SubProcessIndexResponse[{i}] must be int, got {type(pid)}"
            )
        if pid <= 0:
            raise ValidationError(
                f"SubProcessIndexResponse[{i}] must be positive, got {pid}"
            )

    return True


def validate_streaming_line_output(data: Any) -> TypeGuard[StreamingLineOutput]:
    """Validate StreamingLineOutput structure."""
    if not isinstance(data, dict):
        raise ValidationError(f"StreamingLineOutput must be a dict, got {type(data)}")

    required_fields = ["stream", "pid", "data"]
    for field in required_fields:
        if field not in data:
            raise ValidationError(
                f"StreamingLineOutput missing required field: {field}"
            )

    # Validate stream
    if not isinstance(data["stream"], str):
        raise ValidationError(
            f"StreamingLineOutput.stream must be str, got {type(data['stream'])}"
        )

    valid_streams = ["stdout", "stderr"]
    if data["stream"] not in valid_streams:
        raise ValidationError(
            f"StreamingLineOutput.stream must be one of {valid_streams}, got {data['stream']}"
        )

    # Validate pid
    if not isinstance(data["pid"], int):
        raise ValidationError(
            f"StreamingLineOutput.pid must be int, got {type(data['pid'])}"
        )

    if data["pid"] <= 0:
        raise ValidationError(
            f"StreamingLineOutput.pid must be positive, got {data['pid']}"
        )

    # Validate data
    if not isinstance(data["data"], str):
        raise ValidationError(
            f"StreamingLineOutput.data must be str, got {type(data['data'])}"
        )

    return True


def validate_subscribe_requests(data: Any) -> TypeGuard[SubscribeRequests]:
    """Validate SubscribeRequests structure."""
    if not isinstance(data, dict):
        raise ValidationError(f"SubscribeRequests must be a dict, got {type(data)}")

    if "pid" not in data:
        raise ValidationError("SubscribeRequests missing required field: pid")

    if not isinstance(data["pid"], str):
        raise ValidationError(
            f"SubscribeRequests.pid must be str, got {type(data['pid'])}"
        )

    # Validate that pid string can be converted to int
    try:
        pid_int = int(data["pid"])
        if pid_int <= 0:
            raise ValidationError(
                f"SubscribeRequests.pid must be positive, got {pid_int}"
            )
    except ValueError:
        raise ValidationError(
            f"SubscribeRequests.pid must be a valid integer string, got {data['pid']}"
        )

    return True


def safe_validate_spawn_process_request(data: Any) -> SpawnProcessRequest:
    """Safely validate and return SpawnProcessRequest."""
    try:
        validate_spawn_process_request(data)
        return data
    except ValidationError as e:
        logger.error(f"Validation failed for SpawnProcessRequest: {e}")
        raise


def safe_validate_spawn_request_response(data: Any) -> SpawnRequestResponse:
    """Safely validate and return SpawnRequestResponse."""
    try:
        validate_spawn_request_response(data)
        return data
    except ValidationError as e:
        logger.error(f"Validation failed for SpawnRequestResponse: {e}")
        raise


def safe_validate_stop_process_request(data: Any) -> StopProcessRequest:
    """Safely validate and return StopProcessRequest."""
    try:
        validate_stop_process_request(data)
        return data
    except ValidationError as e:
        logger.error(f"Validation failed for StopProcessRequest: {e}")
        raise


def safe_validate_stop_request_response(data: Any) -> StopRequestResponse:
    """Safely validate and return StopRequestResponse."""
    try:
        validate_stop_request_response(data)
        return data
    except ValidationError as e:
        logger.error(f"Validation failed for StopRequestResponse: {e}")
        raise


def safe_validate_subprocess_index_response(data: Any) -> SubProcessIndexResponse:
    """Safely validate and return SubProcessIndexResponse."""
    try:
        validate_subprocess_index_response(data)
        return data
    except ValidationError as e:
        logger.error(f"Validation failed for SubProcessIndexResponse: {e}")
        raise


def safe_validate_streaming_line_output(data: Any) -> StreamingLineOutput:
    """Safely validate and return StreamingLineOutput."""
    try:
        validate_streaming_line_output(data)
        return data
    except ValidationError as e:
        logger.error(f"Validation failed for StreamingLineOutput: {e}")
        raise


def safe_validate_subscribe_requests(data: Any) -> SubscribeRequests:
    """Safely validate and return SubscribeRequests."""
    try:
        validate_subscribe_requests(data)
        return data
    except ValidationError as e:
        logger.error(f"Validation failed for SubscribeRequests: {e}")
        raise
