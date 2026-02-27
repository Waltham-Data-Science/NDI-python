"""
ndi.cloud.api.compute - Compute session management.

All functions accept an optional :class:`~ndi.cloud.client.CloudClient` as
the first argument.  When omitted, a client is created automatically from
environment variables.

MATLAB equivalents: +ndi/+cloud/+api/+compute/*.m
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..client import _auto_client

if TYPE_CHECKING:
    from ..client import CloudClient


@_auto_client
def start_session(
    client: CloudClient,
    pipeline_id: str,
    input_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST /compute/start — Start a new compute session."""
    body: dict[str, Any] = {"pipelineId": pipeline_id}
    if input_params:
        body["inputParameters"] = input_params
    return client.post("/compute/start", json=body)


@_auto_client
def get_session_status(
    client: CloudClient,
    session_id: str,
) -> dict[str, Any]:
    """GET /compute/{sessionId} — Get session status."""
    return client.get("/compute/{sessionId}", sessionId=session_id)


@_auto_client
def trigger_stage(
    client: CloudClient,
    session_id: str,
    stage_id: str,
) -> dict[str, Any]:
    """POST /compute/{sessionId}/stage/{stageId}"""
    return client.post(
        "/compute/{sessionId}/stage/{stageId}",
        sessionId=session_id,
        stageId=stage_id,
    )


@_auto_client
def finalize_session(
    client: CloudClient,
    session_id: str,
) -> dict[str, Any]:
    """POST /compute/{sessionId}/finalize"""
    return client.post(
        "/compute/{sessionId}/finalize",
        sessionId=session_id,
    )


@_auto_client
def abort_session(
    client: CloudClient,
    session_id: str,
) -> bool:
    """POST /compute/{sessionId}/abort"""
    client.post("/compute/{sessionId}/abort", sessionId=session_id)
    return True


@_auto_client
def list_sessions(client: CloudClient) -> list[dict[str, Any]]:
    """GET /compute — List all compute sessions."""
    result = client.get("/compute")
    # Handle both APIResponse (has .data) and raw dict/list from mocks
    raw = result.data if hasattr(result, "data") else result
    if isinstance(raw, list):
        return raw
    return raw.get("sessions", []) if isinstance(raw, dict) else []
