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
    organization_id: str,
    input_params: dict[str, Any] | None = None,
    *,
    client: _Client = None,
) -> dict[str, Any]:
    """POST /compute/start -- Start a new compute session.

    Args:
        pipeline_id: The pipeline to start.
        organization_id: The organization that owns -- and is billed for --
            the session. The backend requires it whenever the caller belongs
            to more than one organization, refusing the POST with HTTP 400
            "Organization ID is required (user has multiple)" otherwise, so
            it is positional here exactly as in MATLAB rather than an option
            a caller can forget. Pass ``""`` to leave it out of the request
            and let the backend decide, which is what a single-organization
            caller gets (VH-Lab/NDI-matlab#936).
        input_params: Pipeline input parameters.
        client: Authenticated cloud client.
    """
    body: dict[str, Any] = {"pipelineId": pipeline_id}
    # Empty means "not supplied": MATLAB's StartSession omits the field
    # rather than sending "", and an empty organizationId is not the same
    # request as an absent one.
    if organization_id:
        body["organizationId"] = organization_id
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
def advanceSession(session_id: NonEmptyStr, *, client: _Client = None) -> dict[str, Any]:
    """POST /compute/{sessionId}/advance -- Advance a session to the next stage.

    Advancing past the last stage finalizes the session; the cloud API exposes
    no separate ``/finalize`` endpoint.
    """
    return client.post(
        "/compute/{sessionId}/advance",
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
