"""Unit tests for ndi.cloud.api.files file-tier wrappers -- no network required.

MATLAB counterpart: tests/+ndi/+unittest/FileTierMockTest.m (poll logic) plus
setFileTier / getFileTier request-shape assertions.

The four wrappers under test (see files.py):

    setFileTier          POST /datasets/{d}/file-tier-jobs
    getFileTierJob       GET  /file-tier-jobs/{jobId}
    waitForFileTierJob   poll loop over getFileTierJob
    getFileTier          projects filesTier out of a GET /documents/{doc}

The interesting behaviours here are ones a working server will not produce on
demand: a job that never reaches a terminal state, a timeout, a transient
API error a naive loop would mistake for a dead job, and each of the three
terminal states resolving with the right verdict. A live-cloud test can show
the happy path works; only mocks can show what happens when it does not.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _make_client() -> MagicMock:
    """Return a mock CloudClient."""
    client = MagicMock()
    client.config.org_id = "org-123"
    client.config.api_url = "https://api.ndi-cloud.com/v1"
    return client


# ---------------------------------------------------------------------------
# setFileTier -- request shape
# ---------------------------------------------------------------------------


class TestSetFileTier:
    def test_posts_selector_list_to_file_tier_jobs(self):
        from ndi.cloud.api.files import setFileTier

        client = _make_client()
        client.post.return_value = {
            "jobId": "j-1",
            "fileCount": 2,
            "resolvedDocumentCount": 1,
            "collateralDocumentIds": [],
        }

        result = setFileTier("ds-1", ["doc-a"], "GLACIER", client=client)

        client.post.assert_called_once()
        call = client.post.call_args
        assert call.args[0] == "/datasets/{datasetId}/file-tier-jobs"
        assert call.kwargs["datasetId"] == "ds-1"
        assert call.kwargs["json"] == {
            "targetTier": "GLACIER",
            "documentSelectors": [{"id": "doc-a"}],
        }
        assert result["jobId"] == "j-1"

    def test_accepts_a_bare_string_document_id(self):
        from ndi.cloud.api.files import setFileTier

        client = _make_client()
        client.post.return_value = {"jobId": "j-2"}

        setFileTier("ds-1", "doc-a", "STANDARD", client=client)

        payload = client.post.call_args.kwargs["json"]
        assert payload["documentSelectors"] == [{"id": "doc-a"}]

    def test_id_namespace_cloud_forces_kind_on_every_selector(self):
        from ndi.cloud.api.files import setFileTier

        client = _make_client()
        client.post.return_value = {"jobId": "j-3"}

        setFileTier(
            "ds-1",
            ["doc-a", "doc-b"],
            "DEEP_ARCHIVE",
            id_namespace="cloud",
            client=client,
        )

        payload = client.post.call_args.kwargs["json"]
        assert payload["documentSelectors"] == [
            {"id": "doc-a", "kind": "cloud"},
            {"id": "doc-b", "kind": "cloud"},
        ]

    def test_id_namespace_ndi_forces_kind_on_every_selector(self):
        from ndi.cloud.api.files import setFileTier

        client = _make_client()
        client.post.return_value = {"jobId": "j-4"}

        setFileTier(
            "ds-1",
            ["ndi_abc"],
            "GLACIER_IR",
            id_namespace="ndi",
            client=client,
        )

        payload = client.post.call_args.kwargs["json"]
        assert payload["documentSelectors"] == [{"id": "ndi_abc", "kind": "ndi"}]

    def test_id_namespace_auto_never_writes_kind(self):
        # The "auto" default is what makes mixed cloud/NDI id lists work --
        # a stray kind='auto' on the wire would be rejected by the server.
        from ndi.cloud.api.files import setFileTier

        client = _make_client()
        client.post.return_value = {"jobId": "j-5"}

        setFileTier("ds-1", ["doc-a"], "STANDARD_IA", client=client)

        payload = client.post.call_args.kwargs["json"]
        assert "kind" not in payload["documentSelectors"][0]

    def test_empty_document_ids_raises(self):
        from ndi.cloud.api.files import setFileTier

        with pytest.raises(ValueError, match="non-empty"):
            setFileTier("ds-1", [], "STANDARD", client=_make_client())

    def test_bad_id_namespace_raises(self):
        # The Literal typing rejects anything but the three accepted values.
        from ndi.cloud.api.files import setFileTier

        with pytest.raises(Exception):
            setFileTier(
                "ds-1",
                ["doc-a"],
                "STANDARD",
                id_namespace="bogus",  # type: ignore[arg-type]
                client=_make_client(),
            )


# ---------------------------------------------------------------------------
# getFileTierJob -- URL shape
# ---------------------------------------------------------------------------


class TestGetFileTierJob:
    def test_gets_file_tier_jobs_endpoint(self):
        from ndi.cloud.api.files import getFileTierJob

        client = _make_client()
        client.get.return_value = {"jobId": "j-1", "state": "running"}

        result = getFileTierJob("j-1", client=client)

        client.get.assert_called_once()
        call = client.get.call_args
        assert call.args[0] == "/file-tier-jobs/{jobId}"
        assert call.kwargs["jobId"] == "j-1"
        assert result["state"] == "running"


# ---------------------------------------------------------------------------
# waitForFileTierJob -- poll logic
#
# Mirrors FileTierMockTest.m. Uses monkeypatched getFileTierJob and a
# time.sleep stub so backoff is exercised without actually sleeping.
# ---------------------------------------------------------------------------


class _ScriptedGetFileTierJob:
    """Return a sequence of scripted responses across successive calls.

    Each entry is either a dict (returned as the status payload) or an
    Exception (raised, to model a transient poll failure). The final entry
    repeats forever, so "always running" is one entry rather than a guess
    about how many polls the wait will make.
    """

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def __call__(self, job_id, *, client=None):
        self.calls += 1
        item = self.script[min(self.calls - 1, len(self.script) - 1)]
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture()
def no_sleep(monkeypatch):
    """Neutralise time.sleep inside ndi.cloud.api.files so tests run fast.

    monotonic still advances by wall clock, which is what the timeout
    branch reads -- a fake clock would need a much heavier harness.
    """
    monkeypatch.setattr("ndi.cloud.api.files.time.sleep", lambda _s: None)


class TestWaitForFileTierJob:
    def test_completed_is_success(self, no_sleep):
        from ndi.cloud.api import files as files_api

        scripted = _ScriptedGetFileTierJob(
            [
                {"state": "completed", "fileCount": 3, "filesDone": 3},
            ]
        )

        with patch.object(files_api, "getFileTierJob", scripted):
            result = files_api.waitForFileTierJob(
                "j1",
                timeout=5,
                initial_interval=0.01,
                max_interval=0.01,
                client=_make_client(),
            )

        assert result["state"] == "completed"
        assert scripted.calls == 1

    def test_failed_is_terminal_not_retried(self, no_sleep):
        from ndi.cloud.api import files as files_api

        scripted = _ScriptedGetFileTierJob([{"state": "failed"}])

        with patch.object(files_api, "getFileTierJob", scripted):
            result = files_api.waitForFileTierJob(
                "j1",
                timeout=5,
                initial_interval=0.01,
                max_interval=0.01,
                client=_make_client(),
            )

        assert result["state"] == "failed"
        assert scripted.calls == 1, "a failed job must not be polled again"

    def test_superseded_is_terminal_not_retried(self, no_sleep):
        # 'superseded' is unique to file-tier: a later job for the same
        # file has taken over. The caller has lost the race; polling on is
        # pointless.
        from ndi.cloud.api import files as files_api

        scripted = _ScriptedGetFileTierJob([{"state": "superseded"}])

        with patch.object(files_api, "getFileTierJob", scripted):
            result = files_api.waitForFileTierJob(
                "j1",
                timeout=5,
                initial_interval=0.01,
                max_interval=0.01,
                client=_make_client(),
            )

        assert result["state"] == "superseded"
        assert scripted.calls == 1, "a superseded job must not be polled again"

    def test_job_is_polled_until_it_completes(self, no_sleep):
        from ndi.cloud.api import files as files_api

        scripted = _ScriptedGetFileTierJob(
            [
                {"state": "queued"},
                {"state": "running"},
                {"state": "completed"},
            ]
        )

        with patch.object(files_api, "getFileTierJob", scripted):
            result = files_api.waitForFileTierJob(
                "j1",
                timeout=5,
                initial_interval=0.01,
                max_interval=0.01,
                client=_make_client(),
            )

        assert result["state"] == "completed"
        assert scripted.calls == 3

    def test_job_that_never_finishes_times_out(self, no_sleep):
        from ndi.cloud.api import files as files_api

        scripted = _ScriptedGetFileTierJob([{"state": "running"}])

        with patch.object(files_api, "getFileTierJob", scripted):
            result = files_api.waitForFileTierJob(
                "j1",
                timeout=0.05,
                initial_interval=0.01,
                max_interval=0.01,
                client=_make_client(),
            )

        assert result["state"] == "timeout"
        assert "elapsed" in result
        # We saw at least one running state before timing out; the last
        # non-timeout fields ride through into the timeout payload.
        assert result["elapsed"] > 0

    def test_an_api_error_is_not_mistaken_for_a_terminal_state(self, no_sleep):
        # A failed poll is not a failed job; keep polling until the deadline
        # rather than reporting the job dead. A naive loop that returns on
        # the first exception would break this.
        from ndi.cloud.api import files as files_api

        scripted = _ScriptedGetFileTierJob([RuntimeError("gateway 504")])

        with patch.object(files_api, "getFileTierJob", scripted):
            result = files_api.waitForFileTierJob(
                "j1",
                timeout=0.5,
                initial_interval=0.01,
                max_interval=0.01,
                client=_make_client(),
            )

        assert result["state"] == "timeout"
        assert (
            scripted.calls > 1
        ), "a transient API error should be retried, not treated as terminal"


# ---------------------------------------------------------------------------
# getFileTier -- projects filesTier off a document GET
# ---------------------------------------------------------------------------


class TestGetFileTier:
    def test_projects_files_tier_summary_out_of_document(self):
        from ndi.cloud.api import files as files_api

        client = _make_client()
        doc = {
            "id": "doc-1",
            "filesTier": {
                "counts": {"GLACIER": 3, "STANDARD": 1},
                "dominant": "GLACIER",
                "notes": ["sibling doc kept file warm"],
                "updatedAt": "2026-09-16T12:00:00Z",
            },
        }
        with patch("ndi.cloud.api.documents.getDocument", return_value=doc) as mock_get:
            result = files_api.getFileTier("ds-1", "doc-1", client=client)

        mock_get.assert_called_once_with("ds-1", "doc-1", client=client)
        assert result["counts"] == {"GLACIER": 3, "STANDARD": 1}
        assert result["dominant"] == "GLACIER"
        assert result["notes"] == ["sibling doc kept file warm"]
        assert result["updatedAt"] == "2026-09-16T12:00:00Z"
        # raw carries the full document for callers that want it.
        assert result["raw"] == doc

    def test_untiered_document_reads_clean_defaults(self):
        # A doc that has never had a tier op should return an empty
        # projection rather than raise -- callers can rely on the shape.
        from ndi.cloud.api import files as files_api

        client = _make_client()
        doc = {"id": "doc-1"}  # no filesTier field at all
        with patch("ndi.cloud.api.documents.getDocument", return_value=doc):
            result = files_api.getFileTier("ds-1", "doc-1", client=client)

        assert result["counts"] == {}
        assert result["dominant"] == ""
        assert result["notes"] == []
        assert result["updatedAt"] is None
        assert result["raw"] == doc

    def test_partial_files_tier_summary_projects_what_is_there(self):
        # The server may write only `counts` and `dominant` on the first
        # summary pass, before `notes` or `updatedAt` land. The projection
        # must not confuse "missing" with "empty".
        from ndi.cloud.api import files as files_api

        client = _make_client()
        doc = {
            "id": "doc-1",
            "filesTier": {
                "counts": {"STANDARD": 2},
                "dominant": "STANDARD",
            },
        }
        with patch("ndi.cloud.api.documents.getDocument", return_value=doc):
            result = files_api.getFileTier("ds-1", "doc-1", client=client)

        assert result["counts"] == {"STANDARD": 2}
        assert result["dominant"] == "STANDARD"
        assert result["notes"] == []
        assert result["updatedAt"] is None

    def test_files_tier_notes_scalar_string_is_wrapped_in_a_list(self):
        # The server encodes a single note as a string in some code paths.
        # The projection normalises to a list so callers can always iterate.
        from ndi.cloud.api import files as files_api

        client = _make_client()
        doc = {
            "id": "doc-1",
            "filesTier": {
                "counts": {"GLACIER": 1},
                "dominant": "GLACIER",
                "notes": "just one note",
            },
        }
        with patch("ndi.cloud.api.documents.getDocument", return_value=doc):
            result = files_api.getFileTier("ds-1", "doc-1", client=client)

        assert result["notes"] == ["just one note"]
