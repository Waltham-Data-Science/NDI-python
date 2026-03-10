"""
ndi.cloud.api.compute - Compute session management.

All functions accept an optional ``client`` keyword argument.  When omitted,
a client is created automatically from environment variables.

MATLAB equivalents: +ndi/+cloud/+api/+compute/*.m
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import SkipValidation, validate_call

from ..client import APIResponse, CloudClient, _auto_client
from ._validators import VALIDATE_CONFIG, NonEmptyStr

_Client = Annotated[CloudClient | None, SkipValidation()]


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def startSession(
    pipeline_id: NonEmptyStr,
    input_params: dict[str, Any] | None = None,
    *,
    client: _Client = None,
) -> dict[str, Any]:
    """POST /compute/start -- Start a new compute session."""
    body: dict[str, Any] = {"pipelineId": pipeline_id}
    if input_params:
        body["inputParameters"] = input_params
    return client.post("/compute/start", json=body)


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def getSessionStatus(session_id: NonEmptyStr, *, client: _Client = None) -> dict[str, Any]:
    """GET /compute/{sessionId} -- Get session status."""
    return client.get("/compute/{sessionId}", sessionId=session_id)


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def triggerStage(
    session_id: NonEmptyStr,
    stage_id: NonEmptyStr,
    *,
    client: _Client = None,
) -> dict[str, Any]:
    """POST /compute/{sessionId}/stage/{stageId}"""
    return client.post(
        "/compute/{sessionId}/stage/{stageId}",
        sessionId=session_id,
        stageId=stage_id,
    )


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def finalizeSession(session_id: NonEmptyStr, *, client: _Client = None) -> dict[str, Any]:
    """POST /compute/{sessionId}/finalize"""
    return client.post(
        "/compute/{sessionId}/finalize",
        sessionId=session_id,
    )


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def abortSession(session_id: NonEmptyStr, *, client: _Client = None) -> bool:
    """POST /compute/{sessionId}/abort"""
    client.post("/compute/{sessionId}/abort", sessionId=session_id)
    return True


@_auto_client
def listSessions(*, client: _Client = None) -> APIResponse:
    """GET /compute -- List all compute sessions."""
    result = client.get("/compute")
    # Handle both APIResponse (has .data) and raw dict/list from mocks
    raw = result.data if hasattr(result, "data") else result
    if isinstance(raw, list):
        sessions = raw
    else:
        sessions = raw.get("sessions", []) if isinstance(raw, dict) else []
    return APIResponse(sessions, success=True, status_code=200, url="")
