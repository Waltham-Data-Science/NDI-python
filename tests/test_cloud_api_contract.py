"""
Tests for the cloud API contract fixes (audit 3.4-15/16/17, 7.4).

Covers the HTTP verb/path corrections that previously 404'd against the real
backend (compute abort/finalize, files bulk-upload URL), the scope validator
accepting dataset-id lists, the 5xx retry on idempotent requests, and the
formatApiError helper. No live cloud — the client's HTTP layer is mocked.
"""

from __future__ import annotations

import json
import unittest.mock as mock

import pytest
from pydantic import TypeAdapter, ValidationError

from ndi.cloud.api._validators import Scope
from ndi.cloud.internal import formatApiError


def _resp(status: int, body: dict | None = None, reason: str = "OK"):
    """Build a fake requests.Response. _handle_response reads .status_code,
    .content and json.loads(.text)."""
    r = mock.MagicMock()
    r.status_code = status
    r.reason = reason
    text = json.dumps(body if body is not None else {})
    r.text = text
    r.content = text.encode()
    r.headers = {}
    return r


def _client_recording(monkeypatch):
    """A CloudClient whose underlying requests.Session is a recording mock."""
    from ndi.cloud.client import CloudClient
    from ndi.cloud.config import CloudConfig

    cfg = CloudConfig(api_url="https://api.example.com", token="t")
    client = CloudClient(cfg)
    sess = mock.MagicMock()
    sess.request.return_value = _resp(200, {"url": "https://s3/presigned", "ok": True})
    client._session = sess
    return client, sess


class TestComputeRoutes:
    def test_abort_uses_delete(self, monkeypatch):
        import ndi.cloud.api.compute as compute

        client, sess = _client_recording(monkeypatch)
        compute.abortSession("sess-1", client=client)

        method, url = sess.request.call_args[0]
        assert method == "DELETE"
        assert url.endswith("/compute/sess-1")
        assert "/abort" not in url

    def test_finalize_uses_advance(self, monkeypatch):
        import ndi.cloud.api.compute as compute

        client, sess = _client_recording(monkeypatch)
        compute.finalizeSession("sess-1", client=client)

        method, url = sess.request.call_args[0]
        assert method == "POST"
        assert url.endswith("/compute/sess-1/advance")
        assert "/finalize" not in url


class TestFilesBulkUploadURL:
    def test_get_bulk_upload_url_uses_get(self, monkeypatch):
        import ndi.cloud.api.files as files

        client, sess = _client_recording(monkeypatch)
        url = files.getBulkUploadURL("org-1", "ds-1", client=client)

        method, request_url = sess.request.call_args[0]
        assert method == "GET"
        assert request_url.endswith("/datasets/org-1/ds-1/files/bulk")
        assert url == "https://s3/presigned"


class TestScopeValidator:
    def test_keywords(self):
        ta = TypeAdapter(Scope)
        assert ta.validate_python("public") == "public"
        assert ta.validate_python("private") == "private"
        assert ta.validate_python("all") == "all"

    def test_single_dataset_id(self):
        ta = TypeAdapter(Scope)
        oid = "a1b2c3d4e5f6a1b2c3d4e5f6"
        assert ta.validate_python(oid) == oid

    def test_csv_dataset_ids_normalized(self):
        ta = TypeAdapter(Scope)
        out = ta.validate_python("a1b2c3d4e5f6a1b2c3d4e5f6, 0a0b0c0d0e0f0a0b0c0d0e0f,")
        assert out == "a1b2c3d4e5f6a1b2c3d4e5f6,0a0b0c0d0e0f0a0b0c0d0e0f"

    def test_rejects_garbage(self):
        ta = TypeAdapter(Scope)
        with pytest.raises(ValidationError):
            ta.validate_python("not-a-scope")

    def test_rejects_short_hex(self):
        ta = TypeAdapter(Scope)
        with pytest.raises(ValidationError):
            ta.validate_python("abc123")


class TestRetry:
    def test_retries_504_on_get(self, monkeypatch):
        client, sess = _client_recording(monkeypatch)
        client.RETRY_BACKOFF = 0  # no real sleep

        bad = _resp(504, {}, reason="Gateway Timeout")
        good = _resp(200, {"ok": True})
        sess.request.side_effect = [bad, bad, good]

        result = client.get("/datasets/{datasetId}", datasetId="d1")
        assert sess.request.call_count == 3
        assert result["ok"] is True

    def test_does_not_retry_post(self, monkeypatch):
        from ndi.cloud.exceptions import CloudAPIError

        client, sess = _client_recording(monkeypatch)
        client.RETRY_BACKOFF = 0

        sess.request.return_value = _resp(503, {"error": "down"}, reason="Service Unavailable")
        sess.request.side_effect = None

        with pytest.raises(CloudAPIError):
            client.post("/datasets/{datasetId}/documents", json={}, datasetId="d1")
        # POST is not idempotent — exactly one attempt, no retry.
        assert sess.request.call_count == 1

    def test_stops_after_max_retries(self, monkeypatch):
        from ndi.cloud.exceptions import CloudAPIError

        client, sess = _client_recording(monkeypatch)
        client.RETRY_BACKOFF = 0

        sess.request.return_value = _resp(502, {"error": "no"}, reason="Bad Gateway")
        sess.request.side_effect = None

        with pytest.raises(CloudAPIError):
            client.get("/datasets/{datasetId}", datasetId="d1")
        assert sess.request.call_count == client.MAX_RETRIES


class TestFormatApiError:
    def test_none(self):
        assert formatApiError(None) == "no response from server"

    def test_status_and_message(self):
        class R:
            status_code = 504
            reason = "Gateway Timeout"
            data = {"message": "boom"}

        assert formatApiError(R()) == "HTTP 504 Gateway Timeout - boom"

    def test_error_field_fallback(self):
        class R:
            status_code = 400
            reason = "Bad Request"
            data = {"error": "bad input"}

        assert formatApiError(R()) == "HTTP 400 Bad Request - bad input"

    def test_plain_dict_body(self):
        assert formatApiError({"message": "just a message"}) == "just a message"

    def test_unknown(self):
        class R:
            status_code = None
            data = {}

        assert formatApiError(R()) == "unknown error"
