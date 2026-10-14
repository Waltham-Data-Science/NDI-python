"""Unit tests for the async signed-URL-set-job family (NDI-python#206).

Covers the four new ``ndi.cloud.api.files`` entry points:

* :func:`createSignedURLSetJob` -- POST /.../signed-url-set-jobs.
* :func:`getSignedURLSetJob`    -- GET /signed-url-set-jobs/{jobId}.
* :func:`waitForSignedURLSetJob`-- exponential-backoff poll to a terminal
  state or timeout.
* :func:`getSignedURLSetResult` -- download and parse the gzipped result
  blob a ready job produced.

The live round trip against a real cloud dataset lives elsewhere; this
file is the offline half, driven by mocked clients and a scripted result
URL, so no credentials are required.
"""

from __future__ import annotations

import gzip
import json
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# createSignedURLSetJob
# ---------------------------------------------------------------------------


class TestCreateSignedURLSetJob:
    def test_posts_to_cloud_id_route_by_default(self):
        """id_namespace='cloud' (default) targets the by-_id route."""
        from ndi.cloud.api import files as files_api

        client = MagicMock()
        client.post.return_value = {"jobId": "j1", "datasetId": "ds1", "documentId": "doc1"}

        result = files_api.createSignedURLSetJob("ds1", "doc1", client=client)

        assert result == {"jobId": "j1", "datasetId": "ds1", "documentId": "doc1"}
        client.post.assert_called_once()
        args, kwargs = client.post.call_args
        assert args[0] == "/datasets/{datasetId}/documents/{documentId}/signed-url-set-jobs"
        assert kwargs.get("datasetId") == "ds1"
        assert kwargs.get("documentId") == "doc1"
        # An empty JSON body, matching MATLAB, so a gateway that rejects
        # zero-byte POSTs still accepts the call.
        assert kwargs.get("json") == {}

    def test_ndi_namespace_targets_ndi_documents_route(self):
        """id_namespace='ndi' is what NDI's own callers use."""
        from ndi.cloud.api import files as files_api

        client = MagicMock()
        client.post.return_value = {"jobId": "j2"}

        files_api.createSignedURLSetJob("ds1", "doc1", id_namespace="ndi", client=client)

        args, _ = client.post.call_args
        assert args[0] == "/datasets/{datasetId}/ndi-documents/{ndiDocumentId}/signed-url-set-jobs"
        # The path param name changes with the route (documentId ->
        # ndiDocumentId), mirroring MATLAB's endpointName switch.
        _, kwargs = client.post.call_args
        assert kwargs.get("ndiDocumentId") == "doc1"

    def test_file_series_folds_into_the_endpoint(self):
        """Optional fileSeries becomes a query parameter on the URL."""
        from ndi.cloud.api import files as files_api

        client = MagicMock()
        client.post.return_value = {"jobId": "j3"}

        files_api.createSignedURLSetJob(
            "ds1", "doc1", file_series="level_a", id_namespace="ndi", client=client
        )

        args, kwargs = client.post.call_args
        assert "fileSeries={fileSeries}" in args[0]
        assert kwargs.get("fileSeries") == "level_a"


# ---------------------------------------------------------------------------
# getSignedURLSetJob
# ---------------------------------------------------------------------------


class TestGetSignedURLSetJob:
    def test_calls_the_jobs_endpoint(self):
        from ndi.cloud.api import files as files_api

        client = MagicMock()
        client.get.return_value = {"jobId": "j1", "state": "running", "signedCount": 42}

        result = files_api.getSignedURLSetJob("j1", client=client)

        assert result["state"] == "running"
        args, kwargs = client.get.call_args
        assert args[0] == "/signed-url-set-jobs/{jobId}"
        assert kwargs.get("jobId") == "j1"


# ---------------------------------------------------------------------------
# waitForSignedURLSetJob
# ---------------------------------------------------------------------------


class TestWaitForSignedURLSetJob:
    def test_returns_ready_terminal_state(self):
        """A job that goes queued -> running -> ready terminates on ready."""
        from ndi.cloud.api import files as files_api

        states = [
            {"state": "queued"},
            {"state": "running", "signedCount": 500},
            {"state": "ready", "resultUrl": "https://example/result", "fileCount": 1000},
        ]

        with (
            patch("ndi.cloud.api.files.getSignedURLSetJob", side_effect=states),
            patch("ndi.cloud.api.files.time.sleep", lambda _s: None),
        ):
            result = files_api.waitForSignedURLSetJob(
                "j1",
                initial_interval=0.01,
                max_interval=0.01,
                timeout=10.0,
                client=MagicMock(),
            )

        assert result["state"] == "ready"
        assert result["resultUrl"] == "https://example/result"

    def test_returns_failed_terminal_state(self):
        """A job that goes to failed returns the failure payload verbatim."""
        from ndi.cloud.api import files as files_api

        with patch(
            "ndi.cloud.api.files.getSignedURLSetJob",
            return_value={"state": "failed", "error": "boom"},
        ):
            result = files_api.waitForSignedURLSetJob(
                "j1", initial_interval=0.01, timeout=1.0, client=MagicMock()
            )

        assert result["state"] == "failed"
        assert result["error"] == "boom"

    def test_timeout_returns_state_timeout(self):
        """When the deadline elapses, state='timeout' and elapsed is set."""
        from ndi.cloud.api import files as files_api

        with (
            patch(
                "ndi.cloud.api.files.getSignedURLSetJob",
                return_value={"state": "running", "signedCount": 10},
            ),
            patch("ndi.cloud.api.files.time.sleep", lambda _s: None),
        ):
            result = files_api.waitForSignedURLSetJob(
                "j1",
                initial_interval=1.0,
                max_interval=1.0,
                timeout=0.01,  # basically immediate
                client=MagicMock(),
            )

        assert result["state"] == "timeout"
        assert "elapsed" in result

    def test_transient_raise_is_not_terminal(self):
        """A gateway blip during a poll does not mark the job dead."""
        from ndi.cloud.api import files as files_api

        seq = [
            ConnectionError("blip"),
            {"state": "running"},
            {"state": "ready", "resultUrl": "https://example/r"},
        ]

        def poll(*args, **kwargs):
            v = seq.pop(0)
            if isinstance(v, Exception):
                raise v
            return v

        with (
            patch("ndi.cloud.api.files.getSignedURLSetJob", side_effect=poll),
            patch("ndi.cloud.api.files.time.sleep", lambda _s: None),
        ):
            result = files_api.waitForSignedURLSetJob(
                "j1",
                initial_interval=0.01,
                max_interval=0.01,
                timeout=10.0,
                client=MagicMock(),
            )

        assert result["state"] == "ready"


# ---------------------------------------------------------------------------
# getSignedURLSetResult
# ---------------------------------------------------------------------------


def _make_response(body: bytes, *, status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.content = body
    resp.text = body.decode("utf-8", errors="replace")
    return resp


class TestGetSignedURLSetResult:
    def test_parses_gzipped_blob(self):
        """A gzipped payload (typical S3 response) is inflated then parsed."""
        from ndi.cloud.api import files as files_api

        payload = {
            "jobId": "j1",
            "fileCount": 2,
            "generatedAt": "2026-09-27T00:00:00Z",
            "files": {"u1": "https://s3.example/u1", "u2": "https://s3.example/u2"},
        }
        body_gz = gzip.compress(json.dumps(payload).encode("utf-8"))

        session = MagicMock()
        session.get.return_value = _make_response(body_gz)
        with patch("ndi.cloud.api.files._download_session", return_value=session):
            result = files_api.getSignedURLSetResult("https://example/result.gz")

        assert result["files"] == payload["files"]
        assert result["fileCount"] == 2
        assert result["generatedAt"] == "2026-09-27T00:00:00Z"

    def test_parses_uncompressed_blob(self):
        """A body the transport already inflated is parsed as-is."""
        from ndi.cloud.api import files as files_api

        payload = {"files": {"u1": "https://s3/u1"}, "fileCount": 1}
        body = json.dumps(payload).encode("utf-8")

        session = MagicMock()
        session.get.return_value = _make_response(body)
        with patch("ndi.cloud.api.files._download_session", return_value=session):
            result = files_api.getSignedURLSetResult("https://example/result")

        assert result["files"] == payload["files"]

    def test_http_error_raises(self):
        from ndi.cloud.api import files as files_api

        session = MagicMock()
        session.get.return_value = _make_response(b"AccessDenied", status=403)
        with patch("ndi.cloud.api.files._download_session", return_value=session):
            with pytest.raises(RuntimeError, match="HTTP 403"):
                files_api.getSignedURLSetResult("https://example/result")

    def test_files_field_wrong_type_raises(self):
        """A payload whose 'files' isn't a dict is a caller-visible failure."""
        from ndi.cloud.api import files as files_api

        payload = {"files": "not-a-dict"}
        session = MagicMock()
        session.get.return_value = _make_response(json.dumps(payload).encode("utf-8"))
        with patch("ndi.cloud.api.files._download_session", return_value=session):
            with pytest.raises(RuntimeError, match="'files' arrived"):
                files_api.getSignedURLSetResult("https://example/result")


# ---------------------------------------------------------------------------
# batch_signed_url _default_signer -- end-to-end wiring through the new path
# ---------------------------------------------------------------------------


class TestDefaultSignerHappyPath:
    """A single happy pass through create -> wait -> read must produce the
    same (True, {files: ...}) shape the paged signer used to.
    """

    def test_returns_the_files_map_when_the_job_is_ready(self):
        from ndi.cloud.batch_signed_url import _default_signer

        files_map = {"u1": "https://s3/u1", "u2": "https://s3/u2"}

        with (
            patch(
                "ndi.cloud.api.files.createSignedURLSetJob",
                return_value={"jobId": "j1"},
            ) as m_create,
            patch(
                "ndi.cloud.api.files.waitForSignedURLSetJob",
                return_value={"state": "ready", "resultUrl": "https://example/r"},
            ) as m_wait,
            patch(
                "ndi.cloud.api.files.getSignedURLSetResult",
                return_value={"files": files_map, "fileCount": 2},
            ) as m_read,
        ):
            ok, answer = _default_signer(
                "ds1",
                "doc1",
                file_series="level_a",
                client=MagicMock(),
                retry_delays=(),
            )

        assert ok is True
        assert answer["files"] == files_map
        m_create.assert_called_once()
        m_wait.assert_called_once()
        m_read.assert_called_once_with("https://example/r")

        # The create call is what carries the NDI namespace and the series
        # scope; verify those explicitly so a future edit that drops the
        # id_namespace='ndi' argument fails here.
        _, create_kwargs = m_create.call_args
        assert create_kwargs.get("id_namespace") == "ndi"
        assert create_kwargs.get("file_series") == "level_a"

    def test_failed_state_reports_the_server_error(self):
        from ndi.cloud.batch_signed_url import BatchScopeUnreachable, _default_signer

        with (
            patch(
                "ndi.cloud.api.files.createSignedURLSetJob",
                return_value={"jobId": "j2"},
            ),
            patch(
                "ndi.cloud.api.files.waitForSignedURLSetJob",
                return_value={"state": "failed", "error": "signer crashed"},
            ),
        ):
            with pytest.raises(BatchScopeUnreachable, match="signer crashed"):
                _default_signer("ds1", "doc1", client=MagicMock(), retry_delays=())

    def test_wait_timeout_is_reported_as_failure(self):
        from ndi.cloud.batch_signed_url import BatchScopeUnreachable, _default_signer

        with (
            patch(
                "ndi.cloud.api.files.createSignedURLSetJob",
                return_value={"jobId": "j3"},
            ),
            patch(
                "ndi.cloud.api.files.waitForSignedURLSetJob",
                return_value={"state": "timeout", "elapsed": 900.0},
            ),
        ):
            with pytest.raises(BatchScopeUnreachable) as exc_info:
                _default_signer("ds1", "doc1", client=MagicMock(), retry_delays=())

        message = str(exc_info.value)
        assert (
            "did not finish" in message or "timeout" in message.lower()
        ), f"failure must name the timeout: {message!r}"

    def test_ready_without_result_url_is_reported_as_failure(self):
        """A ready job that carries no resultUrl is a server bug we must not
        follow into an assertion-free read. See NDI-matlab#1009 for the
        same guard on the MATLAB side.
        """
        from ndi.cloud.batch_signed_url import BatchScopeUnreachable, _default_signer

        with (
            patch(
                "ndi.cloud.api.files.createSignedURLSetJob",
                return_value={"jobId": "j4"},
            ),
            patch(
                "ndi.cloud.api.files.waitForSignedURLSetJob",
                return_value={"state": "ready"},  # no resultUrl
            ),
        ):
            with pytest.raises(BatchScopeUnreachable, match="resultUrl"):
                _default_signer("ds1", "doc1", client=MagicMock(), retry_delays=())
