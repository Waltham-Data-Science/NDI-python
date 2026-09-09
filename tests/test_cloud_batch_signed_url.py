"""
Tests for ndi.cloud.batch_signed_url.

The point of the batch path is to turn one API call per uid into one call
per (dataset, document, series) scope. The test that earns its place -- as
NDI-python#262 puts it -- is "open N members of one series through a fake
API and assert the number of detail calls is 1, not N."

These tests exercise the cache itself and the fetch_cloud_file / handler
wiring that consults it, with a scripted signer standing in for the
signed-URL-set endpoint.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# BatchSignedUrlLookup
# ---------------------------------------------------------------------------


class _FakeSigner:
    """A signer that hands back a scripted uid -> URL map and counts calls.

    Passed by keyword to BatchSignedUrlLookup so the batch endpoint never
    needs a live server. The counters are what let the tests say
    "the batch was called ONCE for N members" rather than "the read
    returned data".
    """

    def __init__(self, files_by_scope: dict[tuple[str, str, str], dict[str, str]]):
        self.files_by_scope = files_by_scope
        self.calls: list[tuple[str, str, str]] = []
        self.raise_next = False

    def __call__(
        self,
        dataset_id: str,
        document_id: str,
        *,
        file_series: str = "",
        client=None,
    ):
        scope = (dataset_id, document_id, file_series)
        self.calls.append(scope)
        if self.raise_next:
            self.raise_next = False
            raise RuntimeError("scripted failure")
        files = self.files_by_scope.get(scope)
        if files is None:
            return False, {"message": "no such scope"}
        return True, {"files": dict(files)}


class TestBatchLookupBatches:
    """N members of one series must resolve with ONE batch call, not N."""

    def test_one_signer_call_serves_many_members(self):
        """The whole point of the exercise, in one assertion."""
        from ndi.cloud.batch_signed_url import BatchSignedUrlLookup

        member_uids = [f"member_{i:05d}" for i in range(50)]
        scope = ("ds1", "doc1", "stack")
        files = {uid: f"https://s3.example.com/{uid}" for uid in member_uids}
        signer = _FakeSigner({scope: files})
        lookup = BatchSignedUrlLookup(signer=signer)

        for uid in member_uids:
            url = lookup.lookup("ds1", "doc1", "stack", uid)
            assert url == f"https://s3.example.com/{uid}"

        assert len(signer.calls) == 1, (
            f"Batch endpoint was called {len(signer.calls)} times for 50 "
            "members; the whole point is one call per scope."
        )
        stats = lookup.stats()
        assert stats.uid_hits == 50
        assert stats.uid_misses == 0
        assert stats.signer_calls == 1

    def test_different_scopes_each_get_one_call(self):
        """Two series in the same document are two scopes, two calls."""
        from ndi.cloud.batch_signed_url import BatchSignedUrlLookup

        files_a = {"a_1": "https://s3/a1", "a_2": "https://s3/a2"}
        files_b = {"b_1": "https://s3/b1", "b_2": "https://s3/b2"}
        signer = _FakeSigner(
            {
                ("ds1", "doc1", "level_a"): files_a,
                ("ds1", "doc1", "level_b"): files_b,
            }
        )
        lookup = BatchSignedUrlLookup(signer=signer)

        assert lookup.lookup("ds1", "doc1", "level_a", "a_1") == "https://s3/a1"
        assert lookup.lookup("ds1", "doc1", "level_a", "a_2") == "https://s3/a2"
        assert lookup.lookup("ds1", "doc1", "level_b", "b_1") == "https://s3/b1"
        assert lookup.lookup("ds1", "doc1", "level_b", "b_2") == "https://s3/b2"
        assert len(signer.calls) == 2


class TestBatchLookupFallback:
    """Empty return means the caller falls back per uid; the read still works.

    A signer failure, a missing 'files' field, a uid the batch does not
    name -- all four look the same to the caller: an empty string, which
    the caller answers with a per-uid getFileDetails. What the CACHE has
    to do is stop hammering the endpoint after one attempted scope fetch
    and make WHICH cause visible in stats.
    """

    def test_missing_document_id_returns_empty(self):
        """Nothing to batch against; not a miss."""
        from ndi.cloud.batch_signed_url import BatchSignedUrlLookup

        signer = _FakeSigner({})
        lookup = BatchSignedUrlLookup(signer=signer)

        assert lookup.lookup("ds1", "", "series", "u1") == ""
        assert signer.calls == [], "no document id -> nothing was fetched"
        stats = lookup.stats()
        assert stats.uid_misses == 0
        assert stats.signer_calls == 0

    def test_a_raising_signer_becomes_an_empty_answer(self):
        """The batch is best-effort. A raise never propagates."""
        from ndi.cloud.batch_signed_url import BatchSignedUrlLookup

        signer = _FakeSigner({})
        signer.raise_next = True
        lookup = BatchSignedUrlLookup(signer=signer)

        assert lookup.lookup("ds1", "doc1", "", "u1") == ""
        assert "RuntimeError" in lookup.stats().last_failure_reason

    def test_a_scope_that_just_failed_is_not_re_hammered(self):
        """The next uid in the sweep must not fire another signer call.

        Without this a 28,000-member series makes 56,000 calls: one per
        uid to fetch the scope again, then one per uid for the fallback.
        """
        from ndi.cloud.batch_signed_url import BatchSignedUrlLookup

        signer = _FakeSigner({})  # every scope fails
        lookup = BatchSignedUrlLookup(signer=signer)

        for uid in [f"u_{i}" for i in range(10)]:
            lookup.lookup("ds1", "doc1", "series", uid)
        assert len(signer.calls) == 1, (
            f"Failure suppression is missing: signer was called " f"{len(signer.calls)} times."
        )
        stats = lookup.stats()
        assert stats.uid_hits == 0
        assert stats.uid_misses == 10

    def test_the_same_uid_retried_still_gets_a_fresh_attempt(self):
        """Suppression is scoped to a SWEEP, not to one uid.

        A caller re-asking for the same uid is retrying on purpose, and
        must get a real attempt: the whole point of the negative cache is
        to stop a sweep of unrelated uids from re-hammering a dead scope.
        """
        from ndi.cloud.batch_signed_url import BatchSignedUrlLookup

        signer = _FakeSigner({})
        lookup = BatchSignedUrlLookup(signer=signer)

        lookup.lookup("ds1", "doc1", "series", "u_same")
        lookup.lookup("ds1", "doc1", "series", "u_same")
        assert len(signer.calls) == 2

    def test_a_uid_absent_from_the_batch_map_falls_back(self):
        """Data drift: the scope was fetched, but this uid is not in it."""
        from ndi.cloud.batch_signed_url import BatchSignedUrlLookup

        files = {"known": "https://s3.example.com/known"}
        signer = _FakeSigner({("ds1", "doc1", ""): files})
        lookup = BatchSignedUrlLookup(signer=signer)

        assert lookup.lookup("ds1", "doc1", "", "known") == "https://s3.example.com/known"
        assert lookup.lookup("ds1", "doc1", "", "unknown") == ""
        stats = lookup.stats()
        assert stats.uid_hits == 1
        assert stats.uid_misses == 1

    def test_failure_reason_names_the_cause(self):
        """Reporting one silent miss leaves the endpoint owner with nothing.

        The four ways a batch can fail must be distinguishable from each
        other: the call raised, the signer reported failure, the payload
        had no 'files' field, the field was the wrong type.
        """
        from ndi.cloud.batch_signed_url import BatchSignedUrlLookup

        signer = MagicMock(return_value=(True, {"not_files": {}}))
        lookup = BatchSignedUrlLookup(signer=signer)
        lookup.lookup("ds1", "doc1", "", "u1")
        assert "no 'files'" in lookup.stats().last_failure_reason


class TestBatchLookupClear:
    def test_clear_drops_everything(self):
        from ndi.cloud.batch_signed_url import BatchSignedUrlLookup

        signer = _FakeSigner({("ds1", "doc1", ""): {"u1": "https://s3/u1"}})
        lookup = BatchSignedUrlLookup(signer=signer)

        lookup.lookup("ds1", "doc1", "", "u1")
        assert lookup.stats().signer_calls == 1
        lookup.clear()
        assert lookup.stats().signer_calls == 0
        lookup.lookup("ds1", "doc1", "", "u1")
        assert lookup.stats().signer_calls == 1  # refetched after clear


# ---------------------------------------------------------------------------
# fetch_cloud_file wiring: the batch cache is consulted, and its answer is
# what gets streamed. On a batch miss, the per-uid getFileDetails is called.
# ---------------------------------------------------------------------------


class TestFetchCloudFileUsesBatch:
    """fetch_cloud_file with a document id must go through the cache first."""

    def test_batch_answer_replaces_getFileDetails(self, tmp_path):
        """A hit means getFileDetails is NEVER called for this uid."""
        from ndi.cloud.batch_signed_url import BatchSignedUrlLookup
        from ndi.cloud.filehandler import fetch_cloud_file

        signer = _FakeSigner(
            {("ds1", "doc_ndi", "stack"): {"member_1": "https://s3.example.com/m1"}}
        )
        lookup = BatchSignedUrlLookup(signer=signer)
        target = tmp_path / "member.bin"

        with (
            patch("ndi.cloud.api.files.getFileDetails") as mock_details,
            patch("ndi.cloud.api.files.getFile") as mock_get_file,
        ):

            def fake_get_file(url, path, timeout=300):
                Path(path).write_bytes(b"member bytes")
                return True

            mock_get_file.side_effect = fake_get_file
            fetch_cloud_file(
                "ndic://ds1/member_1",
                target,
                client=MagicMock(),
                ndi_document_id="doc_ndi",
                series_name="stack",
                batch_lookup=lookup,
            )

        mock_details.assert_not_called()
        mock_get_file.assert_called_once()
        args, _ = mock_get_file.call_args
        assert args[0] == "https://s3.example.com/m1"
        assert target.read_bytes() == b"member bytes"

    def test_batch_miss_falls_back_to_getFileDetails(self, tmp_path):
        """No document id -> old path: one getFileDetails per uid."""
        from ndi.cloud.batch_signed_url import BatchSignedUrlLookup
        from ndi.cloud.filehandler import fetch_cloud_file

        lookup = BatchSignedUrlLookup(signer=_FakeSigner({}))
        target = tmp_path / "member.bin"

        with (
            patch("ndi.cloud.api.files.getFileDetails") as mock_details,
            patch("ndi.cloud.api.files.getFile") as mock_get_file,
        ):
            mock_details.return_value = {"downloadUrl": "https://s3.example.com/f"}
            mock_get_file.side_effect = lambda url, path, timeout=300: (
                Path(path).write_bytes(b"x") or True
            )
            fetch_cloud_file(
                "ndic://ds1/member_1",
                target,
                client=MagicMock(),
                ndi_document_id="",
                series_name="",
                batch_lookup=lookup,
            )

        mock_details.assert_called_once()

    def test_batch_miss_with_context_still_falls_back(self, tmp_path):
        """A batch that has the scope but not the uid falls back per uid.

        Data drift; the caller must still get its file, and it does via
        getFileDetails.
        """
        from ndi.cloud.batch_signed_url import BatchSignedUrlLookup
        from ndi.cloud.filehandler import fetch_cloud_file

        signer = _FakeSigner({("ds1", "doc_ndi", ""): {"other_uid": "https://s3/o"}})
        lookup = BatchSignedUrlLookup(signer=signer)
        target = tmp_path / "member.bin"
        client = MagicMock()

        with (
            patch("ndi.cloud.api.files.getFileDetails") as mock_details,
            patch("ndi.cloud.api.files.getFile") as mock_get_file,
        ):
            mock_details.return_value = {"downloadUrl": "https://s3.example.com/f"}
            mock_get_file.side_effect = lambda url, path, timeout=300: (
                Path(path).write_bytes(b"x") or True
            )
            fetch_cloud_file(
                "ndic://ds1/wanted_uid",
                target,
                client=client,
                ndi_document_id="doc_ndi",
                batch_lookup=lookup,
            )

        mock_details.assert_called_once_with("ds1", "wanted_uid", client=client)


# ---------------------------------------------------------------------------
# download_file_from_cloud passes DID's context through to the batch path.
# ---------------------------------------------------------------------------


class TestDownloadHandlerPassesContext:
    """The whole reason the handler takes DID's context.

    Without threading documentId and seriesName through to fetch_cloud_file,
    the batch cache has no scope to key on and every member costs a
    per-uid getFileDetails call.
    """

    MANIFEST_URI = "ndic://ds1/manifest_uid"
    MEMBER_UID = "member_uid_0000000000000000000000001"

    def test_series_member_uses_context_for_batch_scope(self, tmp_path):
        from ndi.cloud.filehandler import download_file_from_cloud

        dest = tmp_path / "member.bin"
        with patch("ndi.cloud.filehandler.fetch_cloud_file") as mock_fetch:
            download_file_from_cloud(
                dest,
                self.MANIFEST_URI,
                {
                    "documentId": "doc_ndi",
                    "seriesName": "stack",
                    "uid": self.MEMBER_UID,
                    "mode": "open",
                },
            )

        mock_fetch.assert_called_once()
        args, kwargs = mock_fetch.call_args
        # The MEMBER's URI (not the manifest's), plus the batch scope keys.
        assert args[0] == f"ndic://ds1/{self.MEMBER_UID}"
        assert kwargs["ndi_document_id"] == "doc_ndi"
        assert kwargs["series_name"] == "stack"

    def test_ordinary_file_still_carries_document_scope(self, tmp_path):
        """Two documents each with one file must not share a scope.

        An ordinary file (no seriesName) with a documentId still keys its
        batch scope on that documentId, so the endpoint returns just that
        document's map -- exactly one uid, but the cache is still primed
        for the next uid in the same document.
        """
        from ndi.cloud.filehandler import download_file_from_cloud

        dest = tmp_path / "f.bin"
        with patch("ndi.cloud.filehandler.fetch_cloud_file") as mock_fetch:
            download_file_from_cloud(
                dest,
                "ndic://ds1/some_uid",
                {"documentId": "doc_ndi", "uid": "some_uid"},
            )

        _, kwargs = mock_fetch.call_args
        assert kwargs["ndi_document_id"] == "doc_ndi"
        assert kwargs["series_name"] == ""

    def test_no_context_disables_batch(self, tmp_path):
        """Two-argument call: no documentId, no batch scope."""
        from ndi.cloud.filehandler import download_file_from_cloud

        dest = tmp_path / "f.bin"
        with patch("ndi.cloud.filehandler.fetch_cloud_file") as mock_fetch:
            download_file_from_cloud(dest, "ndic://ds1/some_uid")

        _, kwargs = mock_fetch.call_args
        assert kwargs["ndi_document_id"] == ""
        assert kwargs["series_name"] == ""


# ---------------------------------------------------------------------------
# The getSignedURLSetAll API function itself.
# ---------------------------------------------------------------------------


class TestGetSignedURLSetAll:
    def test_walks_every_page(self):
        """A three-page response merges into one dict, one call per page."""
        from ndi.cloud.api import files as files_api

        pages = [
            {"files": {"a": "urlA"}, "nextCursor": "c1"},
            {"files": {"b": "urlB"}, "nextCursor": "c2"},
            {"files": {"c": "urlC"}, "totalCount": 3},
        ]

        def fake_page(dataset_id, document_id, **kwargs):
            return pages.pop(0)

        with patch("ndi.cloud.api.files.getSignedURLSet", side_effect=fake_page):
            result = files_api.getSignedURLSetAll("ds1", "doc1", client=MagicMock())

        assert result["files"] == {"a": "urlA", "b": "urlB", "c": "urlC"}
        assert result["pages"] == 3
        assert result["totalCount"] == 3

    def test_cursor_that_does_not_advance_raises(self):
        from ndi.cloud.api import files as files_api

        with patch(
            "ndi.cloud.api.files.getSignedURLSet",
            return_value={"files": {"a": "urlA"}, "nextCursor": ""},
        ):
            result = files_api.getSignedURLSetAll("ds1", "doc1", client=MagicMock())
        assert result["pages"] == 1

        def loop_forever(*args, **kwargs):
            return {"files": {"a": "urlA"}, "nextCursor": "same"}

        with patch("ndi.cloud.api.files.getSignedURLSet", side_effect=loop_forever):
            # First call: cursor="" -> nextCursor="same" (advances).
            # Second call: cursor="same" -> nextCursor="same" (stalls, raise).
            with pytest.raises(files_api.SignedURLSetCursorDidNotAdvance):
                files_api.getSignedURLSetAll("ds1", "doc1", client=MagicMock())

    def test_max_pages_raises_with_partial_result(self):
        from ndi.cloud.api import files as files_api

        counter = {"n": 0}

        def unique_cursor(*args, **kwargs):
            counter["n"] += 1
            return {
                "files": {f"u{counter['n']}": f"url{counter['n']}"},
                "nextCursor": f"cursor_{counter['n']}",
            }

        with patch("ndi.cloud.api.files.getSignedURLSet", side_effect=unique_cursor):
            with pytest.raises(files_api.SignedURLSetMaxPagesReached) as exc:
                files_api.getSignedURLSetAll("ds1", "doc1", max_pages=3, client=MagicMock())
        assert exc.value.merged["pages"] == 3
