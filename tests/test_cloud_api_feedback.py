"""Unit tests for ndi.cloud.api.feedback -- no network required.

Offline half of the port of NDI-matlab
``tests/+ndi/+unittest/+cloud/feedbackTest.m`` (75f937a76); the live half
is ``tests/test_cloud_feedback_live.py``.

The request body is a contract shared with NDI-matlab and the server
(ndi-cloud-node#158), so these tests pin the exact payload: which keys are
always sent, which are left out when not supplied, and that none is
renamed. The client is a real :class:`CloudClient` over a stub transport,
so the URL, method and error mapping under test are the ones a caller
actually gets.
"""

from __future__ import annotations

import json
import types

import pydantic
import pytest

from ndi.cloud.api import feedback
from ndi.cloud.api.feedback import deleteFeedback, submitFeedback
from ndi.cloud.client import CloudClient
from ndi.cloud.config import CloudConfig
from ndi.cloud.exceptions import CloudAPIError, CloudAuthError, CloudNotFoundError

API_URL = "https://api.example.test/v1"
APP = "NDI-python-unittest"
FEEDBACK_ID = "65f0c0ffee0000000000abcd"


def response(status=200, body=None, reason=""):
    """Something shaped like a ``requests.Response``."""
    text = json.dumps(body) if body is not None else ""

    def _json():
        if body is None:
            raise ValueError("no json")
        return body

    return types.SimpleNamespace(
        status_code=status,
        reason=reason,
        json=_json,
        text=text,
        content=text.encode(),
        headers={},
        elapsed=None,
    )


class Transport:
    """A stub ``requests.Session`` that records requests and replies RESP."""

    def __init__(self, resp):
        self.resp = resp
        self.calls: list[dict] = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.resp


def make_client(resp, token="test-token"):
    client = CloudClient.__new__(CloudClient)
    client.config = CloudConfig(api_url=API_URL, token=token)
    client._session = Transport(resp)
    return client


def created(feedback_id=FEEDBACK_ID):
    return make_client(response(201, {"id": feedback_id}, "Created"))


# ---------------------------------------------------------------------------
# submitFeedback
# ---------------------------------------------------------------------------


class TestSubmitFeedbackPayload:
    def test_minimal_report_sends_only_the_required_fields(self):
        client = created()
        submitFeedback(APP, "other", "minimal report", client=client)

        (call,) = client._session.calls
        assert call["json"] == {
            "schemaVersion": 1,
            "app": APP,
            "category": "other",
            "description": "minimal report",
        }

    def test_post_to_feedback_with_bearer_token(self):
        client = created()
        submitFeedback(APP, "bug", "x", client=client)

        (call,) = client._session.calls
        assert call["method"] == "POST"
        assert call["url"] == f"{API_URL}/feedback"
        assert call["headers"]["Authorization"] == "Bearer test-token"

    def test_full_report_sends_every_optional_field_under_its_matlab_name(self):
        environment = {"os": "linux", "python": "3.12", "launchedFrom": "pytest"}
        state = {"level": 3, "fetchStats": {"ok": 10, "failed": 2}}
        client = created()
        submitFeedback(
            APP,
            "bug",
            "full report",
            appVersion="NDI-python unittest",
            datasetId="000000000000000000000000",
            documentId="unittest-document",
            environment=environment,
            state=state,
            log="line 1\nline 2",
            traceback="no real traceback",
            client=client,
        )

        (call,) = client._session.calls
        assert call["json"] == {
            "schemaVersion": 1,
            "app": APP,
            "category": "bug",
            "description": "full report",
            "appVersion": "NDI-python unittest",
            "datasetId": "000000000000000000000000",
            "documentId": "unittest-document",
            "environment": environment,
            "state": state,
            "log": "line 1\nline 2",
            "traceback": "no real traceback",
        }

    @pytest.mark.parametrize(
        "field, value",
        [
            ("appVersion", "1.0"),
            ("datasetId", "abc"),
            ("documentId", "def"),
            ("log", "a log"),
            ("traceback", "a traceback"),
            ("environment", {"os": "linux"}),
            ("state", {"k": 1}),
        ],
    )
    def test_each_optional_field_is_sent_alone(self, field, value):
        client = created()
        submitFeedback(APP, "performance", "d", client=client, **{field: value})

        body = client._session.calls[0]["json"]
        assert body[field] == value
        assert set(body) == {"schemaVersion", "app", "category", "description", field}

    def test_empty_values_are_sent_not_dropped(self):
        # MATLAB omits only a missing string or struct.empty; "" and
        # struct() go out as they are. None is Python's "missing".
        client = created()
        submitFeedback(APP, "bug", "d", log="", environment={}, client=client)

        body = client._session.calls[0]["json"]
        assert body["log"] == ""
        assert body["environment"] == {}

    @pytest.mark.parametrize("category", ["bug", "performance", "other"])
    def test_every_category_is_accepted(self, category):
        client = created()
        submitFeedback(APP, category, "d", client=client)
        assert client._session.calls[0]["json"]["category"] == category


class TestSubmitFeedbackResult:
    def test_returns_the_stored_report_id(self):
        result = submitFeedback(APP, "bug", "d", client=created("abc123"))
        assert result.data == "abc123"
        assert result.success is True
        assert result.status_code == 201
        assert result.url == f"{API_URL}/feedback"

    def test_unpacks_like_matlab(self):
        b, feedbackID, status, url = submitFeedback(APP, "bug", "d", client=created("abc123"))
        assert (b, feedbackID, status, url) == (True, "abc123", 201, f"{API_URL}/feedback")


class TestSubmitFeedbackValidation:
    """Client-side argument validation: nothing reaches the network."""

    def test_unknown_category_is_rejected(self):
        client = created()
        with pytest.raises(pydantic.ValidationError):
            submitFeedback(APP, "feature", "never sent", client=client)
        assert client._session.calls == []

    def test_empty_description_is_rejected(self):
        client = created()
        with pytest.raises(pydantic.ValidationError):
            submitFeedback(APP, "bug", "", client=client)
        assert client._session.calls == []

    def test_empty_app_is_rejected(self):
        client = created()
        with pytest.raises(pydantic.ValidationError):
            submitFeedback("", "bug", "d", client=client)
        assert client._session.calls == []

    def test_environment_must_be_a_mapping(self):
        client = created()
        with pytest.raises(pydantic.ValidationError):
            submitFeedback(APP, "bug", "d", environment=["not", "a", "dict"], client=client)
        assert client._session.calls == []

    def test_optional_fields_are_keyword_only(self):
        client = created()
        with pytest.raises(pydantic.ValidationError):
            submitFeedback(APP, "bug", "d", "1.0", client=client)
        assert client._session.calls == []


class TestSubmitFeedbackErrors:
    @pytest.mark.parametrize(
        "status, error",
        [
            (400, "category must be one of bug, performance, other"),
            (413, "log exceeds 500000 characters"),
            (429, "Too many feedback reports; the limit is 10 per hour"),
            (500, "Failed to store feedback"),
        ],
    )
    def test_server_rejection_raises_with_status(self, status, error):
        client = make_client(response(status, {"error": error}))
        with pytest.raises(CloudAPIError) as excinfo:
            submitFeedback(APP, "bug", "d", client=client)
        assert excinfo.value.status_code == status
        assert excinfo.value.response_body == {"error": error}

    @pytest.mark.parametrize("status", [401, 403])
    def test_unauthenticated_raises_auth_error(self, status):
        client = make_client(response(status, {"error": "Unauthorized"}))
        with pytest.raises(CloudAuthError):
            submitFeedback(APP, "bug", "d", client=client)

    def test_post_is_not_retried(self):
        # A repeated POST could store the report twice.
        client = make_client(response(503, {"error": "unavailable"}))
        with pytest.raises(CloudAPIError):
            submitFeedback(APP, "bug", "d", client=client)
        assert len(client._session.calls) == 1


class TestSubmitRaw:
    """feedback._submit mirrors the SubmitFeedback implementation class."""

    def test_sends_the_body_as_is(self):
        body = {"schemaVersion": 99, "app": APP, "category": "feature"}
        client = created()
        feedback._submit(body, client=client)
        assert client._session.calls[0]["json"] == body


# ---------------------------------------------------------------------------
# deleteFeedback
# ---------------------------------------------------------------------------


class TestDeleteFeedback:
    def test_delete_url_and_method(self):
        client = make_client(response(204, None, "No Content"))
        deleteFeedback(FEEDBACK_ID, client=client)

        (call,) = client._session.calls
        assert call["method"] == "DELETE"
        assert call["url"] == f"{API_URL}/feedback/{FEEDBACK_ID}"
        assert call["headers"]["Authorization"] == "Bearer test-token"

    def test_success_unpacks_like_matlab(self):
        client = make_client(response(204, None, "No Content"))
        b, answer, status, url = deleteFeedback(FEEDBACK_ID, client=client)
        assert b is True
        assert answer == "Feedback deleted successfully."
        assert status == 204
        assert url == f"{API_URL}/feedback/{FEEDBACK_ID}"

    def test_id_is_url_encoded(self):
        client = make_client(response(204, None))
        deleteFeedback("a/b", client=client)
        assert client._session.calls[0]["url"] == f"{API_URL}/feedback/a%2Fb"

    def test_missing_report_raises_not_found(self):
        client = make_client(response(404, {"error": "Feedback not found"}))
        with pytest.raises(CloudNotFoundError):
            deleteFeedback("000000000000000000000000", client=client)

    def test_malformed_id_raises_400(self):
        client = make_client(response(400, {"error": "Invalid feedback id"}))
        with pytest.raises(CloudAPIError) as excinfo:
            deleteFeedback("not-a-valid-id", client=client)
        assert excinfo.value.status_code == 400

    def test_empty_id_is_rejected_without_a_request(self):
        client = make_client(response(204, None))
        with pytest.raises(pydantic.ValidationError):
            deleteFeedback("", client=client)
        assert client._session.calls == []


def test_registered_in_package():
    import ndi.cloud.api as api

    assert "feedback" in api.__all__
    assert api.feedback.submitFeedback is submitFeedback
