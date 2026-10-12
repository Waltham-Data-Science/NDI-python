"""
ndi.cloud.api.feedback - In-app problem reports.

All functions accept an optional ``client`` keyword argument.  When omitted,
a client is created automatically from environment variables.

The request body is a contract shared with NDI-matlab and the server
(ndi-cloud-node#158): field names, and which fields are left out when not
supplied, follow ``ndi.cloud.api.feedback.submitFeedback`` exactly. That is
why the optional arguments keep their camelCase payload names here rather
than the snake_case the sibling modules use for arguments.

MATLAB equivalents: +ndi/+cloud/+api/+feedback/*.m,
    +implementation/+feedback/*.m
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import SkipValidation, validate_call

from ..client import APIResponse, CloudClient, _auto_client
from ._validators import VALIDATE_CONFIG, CloudId, FeedbackCategory, NonEmptyStr

_Client = Annotated[CloudClient | None, SkipValidation()]

#: The report schema this client writes. The server refuses any other.
FEEDBACK_SCHEMA_VERSION = 1


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def submitFeedback(
    app: NonEmptyStr,
    category: FeedbackCategory,
    description: NonEmptyStr,
    *,
    appVersion: str | None = None,
    datasetId: str | None = None,
    documentId: str | None = None,
    environment: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
    log: str | None = None,
    traceback: str | None = None,
    client: _Client = None,
) -> APIResponse:
    """POST /feedback -- Submit an in-app problem report to NDI Cloud.

    The reporter is the logged-in user. The server redacts anything that
    looks like a bearer token or a signed S3 URL credential before storing
    the report, but callers should still scrub logs before sending.

    Args:
        app: Name of the client sending the report
            (e.g. ``"lightsheetZarr-viewer"``).
        category: One of ``"bug"``, ``"performance"`` or ``"other"``.
        description: The user's free-text description of the problem.
        appVersion: Version of the client (e.g. ``"NDI-python 2.0"``).
        datasetId: Cloud dataset id the report concerns.
        documentId: Document id the report concerns.
        environment: Dict describing the client environment (os, versions, ...).
        state: Dict with client state useful for diagnosis.
        log: Recent log lines.
        traceback: Error stack, if any.
        client: Authenticated cloud client.

    An optional field left at ``None`` is omitted from the request, as
    MATLAB omits a ``missing`` string or an empty struct. An empty string
    or an empty dict is sent, as MATLAB sends ``""`` and ``struct()``.

    Server limits: 1 MB per request; description 20,000 characters, log
    500,000, traceback 50,000; environment 20 kB and state 200 kB as JSON;
    10 reports per user per hour. Exceeding a size cap raises
    :class:`~ndi.cloud.exceptions.CloudAPIError` with ``status_code`` 413;
    the hourly limit, 429.

    Returns:
        :class:`~ndi.cloud.client.APIResponse` whose ``data`` is the id of
        the stored report (use it with :func:`deleteFeedback`), so that
        ``b, feedbackID, status, url = submitFeedback(...)`` mirrors
        MATLAB's ``[b, feedbackID, apiResponse, apiURL]``.
    """
    body: dict[str, Any] = {
        "schemaVersion": FEEDBACK_SCHEMA_VERSION,
        "app": app,
        "category": category,
        "description": description,
    }
    optional = {
        "appVersion": appVersion,
        "datasetId": datasetId,
        "documentId": documentId,
        "log": log,
        "traceback": traceback,
        "environment": environment,
        "state": state,
    }
    body.update({name: value for name, value in optional.items() if value is not None})
    return _submit(body, client=client)


def _submit(body: dict[str, Any], *, client: CloudClient) -> APIResponse:
    """POST BODY to /feedback as-is and return the stored report's id.

    MATLAB equivalent: ``ndi.cloud.api.implementation.feedback.SubmitFeedback``,
    which likewise sends whatever struct it is given, so tests can reach
    the server's own validation past the wrapper's.
    """
    result = client.post("/feedback", json=body)
    data = result.data if hasattr(result, "data") else result
    feedback_id = data.get("id", "") if isinstance(data, dict) else ""
    return APIResponse(
        feedback_id,
        success=True,
        status_code=getattr(result, "status_code", 201),
        url=getattr(result, "url", ""),
        headers=getattr(result, "headers", None),
        reason=getattr(result, "reason", ""),
        elapsed=getattr(result, "elapsed", None),
        http_response=getattr(result, "http_response", None),
    )


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def deleteFeedback(feedbackID: CloudId, *, client: _Client = None) -> APIResponse:
    """DELETE /feedback/{feedbackId} -- Withdraw one of your own reports.

    Only the user who submitted a report can delete it. A report that does
    not exist, or that belongs to another user, raises
    :class:`~ndi.cloud.exceptions.CloudNotFoundError` (HTTP 404); an id
    that is not a well-formed ObjectId raises
    :class:`~ndi.cloud.exceptions.CloudAPIError` with ``status_code`` 400.

    Args:
        feedbackID: The id returned by :func:`submitFeedback`.
        client: Authenticated cloud client.

    Returns:
        :class:`~ndi.cloud.client.APIResponse` (HTTP 204) whose ``data`` is
        MATLAB's confirmation message, ``"Feedback deleted successfully."``.
    """
    result = client.delete("/feedback/{feedbackId}", feedbackId=feedbackID)
    return APIResponse(
        "Feedback deleted successfully.",
        success=True,
        status_code=getattr(result, "status_code", 204),
        url=getattr(result, "url", ""),
        headers=getattr(result, "headers", None),
        reason=getattr(result, "reason", ""),
        elapsed=getattr(result, "elapsed", None),
        http_response=getattr(result, "http_response", None),
    )
