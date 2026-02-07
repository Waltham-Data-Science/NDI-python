"""
ndi.cloud.api.compute - Compute session management.

MATLAB equivalents: +ndi/+cloud/+api/+compute/*.m
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..client import CloudClient


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


def get_session_status(
    client: CloudClient,
    session_id: str,
) -> dict[str, Any]:
    """GET /compute/{sessionId} — Get session status."""
    return client.get("/compute/{sessionId}", sessionId=session_id)


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


def finalize_session(
    client: CloudClient,
    session_id: str,
) -> dict[str, Any]:
    """POST /compute/{sessionId}/finalize"""
    return client.post(
        "/compute/{sessionId}/finalize",
        sessionId=session_id,
    )


def abort_session(
    client: CloudClient,
    session_id: str,
) -> bool:
    """POST /compute/{sessionId}/abort"""
    client.post("/compute/{sessionId}/abort", sessionId=session_id)
    return True


def list_sessions(client: CloudClient) -> list[dict[str, Any]]:
    """GET /compute — List all compute sessions."""
    result = client.get("/compute")
    if isinstance(result, list):
        return result
    return result.get("sessions", []) if isinstance(result, dict) else []
