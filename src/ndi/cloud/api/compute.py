"""
ndi.cloud.api.compute - Compute session management.

All functions accept an optional ``client`` keyword argument.  When omitted,
a client is created automatically from environment variables.

MATLAB equivalents: +ndi/+cloud/+api/+compute/*.m
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..client import APIResponse, _auto_client

if TYPE_CHECKING:
    from ..client import CloudClient


@_auto_client
def start_session(
    pipeline_id: str,
    input_params: dict[str, Any] | None = None,
    *,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """POST /compute/start -- Start a new compute session."""
    body: dict[str, Any] = {"pipelineId": pipeline_id}
    if input_params:
        body["inputParameters"] = input_params
    return client.post("/compute/start", json=body)


@_auto_client
def get_session_status(session_id: str, *, client: CloudClient | None = None) -> dict[str, Any]:
    """GET /compute/{sessionId} -- Get session status."""
    return client.get("/compute/{sessionId}", sessionId=session_id)


@_auto_client
def trigger_stage(
    session_id: str,
    stage_id: str,
    *,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """POST /compute/{sessionId}/stage/{stageId}"""
    return client.post(
        "/compute/{sessionId}/stage/{stageId}",
        sessionId=session_id,
        stageId=stage_id,
    )


@_auto_client
def finalize_session(session_id: str, *, client: CloudClient | None = None) -> dict[str, Any]:
    """POST /compute/{sessionId}/finalize"""
    return client.post(
        "/compute/{sessionId}/finalize",
        sessionId=session_id,
    )


@_auto_client
def abort_session(session_id: str, *, client: CloudClient | None = None) -> bool:
    """POST /compute/{sessionId}/abort"""
    client.post("/compute/{sessionId}/abort", sessionId=session_id)
    return True


@_auto_client
def list_sessions(*, client: CloudClient | None = None) -> list[dict[str, Any]]:
    """GET /compute -- List all compute sessions."""
    result = client.get("/compute")
    # Handle both APIResponse (has .data) and raw dict/list from mocks
    raw = result.data if hasattr(result, "data") else result
    if isinstance(raw, list):
        sessions = raw
    else:
        sessions = raw.get("sessions", []) if isinstance(raw, dict) else []
    return APIResponse(sessions, success=True, status_code=200, url="")
