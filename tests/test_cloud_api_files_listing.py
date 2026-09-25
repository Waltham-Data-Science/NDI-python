"""Unit tests for the keyset (cursor) file-listing API — no network required.

Mirrors the MATLAB coverage that landed with the files-collection migration
(NDI-matlab#1004, ``tests/+ndi/+unittest/+cloud/FilesTest.testListFilesPagination``
and ``tests/+ndi/+test/+helper/largeFileListingScenario.m``):

* ``listFiles`` returns a single keyset page together with a
  cursor/hasMore/totalNumber envelope.
* The cursor fetches the next page, which does not overlap the previous one.
* ``listFilesAll`` follows the cursor across every page, de-duplicates by uid,
  and returns every file summary; its count equals both the envelope's
  ``totalNumber`` and the dataset's ``fileCount``.

The live round trip against a real cloud dataset lives in
``tests/test_cloud_live.py``; this file is the offline half, driven by a
scripted in-memory keyset endpoint, so no credentials are required.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from ndi.cloud.api.files import _MAX_FILE_PAGES, listFiles, listFilesAll

_FILES_ENDPOINT = "/datasets/{datasetId}/files"


def _file(uid: str) -> dict[str, Any]:
    """A file summary shaped like the server's, keyed by uid."""
    return {"uid": uid, "uploaded": True, "sourceDatasetId": "ds-1", "size": 100}


class _KeysetServer:
    """A fake, keyset-paginated ``GET /datasets/{datasetId}/files``.

    Serves an in-memory, insertion-ordered file set. The cursor is the uid of
    the last file on a page; ``after`` resumes strictly past that uid, so pages
    never overlap. Records every call so tests can assert the query it received.
    """

    def __init__(self, files: list[dict[str, Any]]):
        self.files = list(files)
        self.calls: list[dict[str, Any]] = []

    def get(self, endpoint: str, params: dict | None = None, **path_params: str) -> dict[str, Any]:
        params = params or {}
        limit = params.get("limit", 1000)
        after = params.get("after", "")
        self.calls.append({"endpoint": endpoint, "params": dict(params), "path": path_params})

        start = 0
        if after:
            uids = [f["uid"] for f in self.files]
            # A cursor the server never issued resumes past the end.
            start = uids.index(after) + 1 if after in uids else len(self.files)

        page = self.files[start : start + limit]
        return {
            "datasetId": path_params.get("datasetId", ""),
            "limit": limit,
            "count": len(page),
            "cursor": page[-1]["uid"] if page else "",
            "hasMore": (start + limit) < len(self.files),
            "totalNumber": len(self.files),
            "files": page,
        }


class TestListFilesSinglePage:
    """``listFiles`` sends the keyset query and returns the page envelope."""

    def test_first_page_sends_limit_and_no_cursor(self):
        client = MagicMock()
        client.get.return_value = {"files": [], "hasMore": False, "totalNumber": 0}

        listFiles("ds-1", limit=50, client=client)

        client.get.assert_called_once()
        call = client.get.call_args
        assert call.args[0] == _FILES_ENDPOINT
        assert call.kwargs["datasetId"] == "ds-1"
        assert call.kwargs["params"] == {"limit": 50}
        # The first page must not send an (empty) cursor.
        assert "after" not in call.kwargs["params"]

    def test_cursor_is_forwarded_as_after(self):
        client = MagicMock()
        client.get.return_value = {"files": [], "hasMore": False, "totalNumber": 0}

        listFiles("ds-1", limit=50, after="cursor-xyz", client=client)

        assert client.get.call_args.kwargs["params"] == {"limit": 50, "after": "cursor-xyz"}

    def test_returns_the_page_envelope(self):
        server = _KeysetServer([_file(u) for u in ("a", "b", "c", "d", "e")])

        page = listFiles("ds-1", limit=2, client=server)

        assert [f["uid"] for f in page["files"]] == ["a", "b"]
        assert page["totalNumber"] == 5
        assert page["hasMore"] is True
        assert page["cursor"] == "b"


class TestKeysetPagination:
    """The cursor advances to a non-overlapping next page (MATLAB steps 4-5)."""

    def test_cursor_fetches_a_non_overlapping_next_page(self):
        server = _KeysetServer([_file(u) for u in ("a", "b", "c", "d", "e")])

        page1 = listFiles("ds-1", limit=2, client=server)
        assert page1["hasMore"] is True
        assert page1["cursor"]

        page2 = listFiles("ds-1", limit=2, after=page1["cursor"], client=server)

        page1_uids = {f["uid"] for f in page1["files"]}
        page2_uids = {f["uid"] for f in page2["files"]}
        assert page1_uids.isdisjoint(page2_uids), "second page overlaps the first"
        assert page2_uids == {"c", "d"}


class TestListFilesAll:
    """``listFilesAll`` walks every page, de-duplicates, and matches counts."""

    def test_walks_all_pages_and_returns_every_file(self):
        uids = [f"file-{i:02d}" for i in range(7)]
        server = _KeysetServer([_file(u) for u in uids])

        result = listFilesAll("ds-1", limit=2, client=server)

        assert [f["uid"] for f in result.data] == uids
        # 7 files at limit 2 -> pages of 2,2,2,1 == 4 requests.
        assert len(server.calls) == 4
        # Every request after the first carried a cursor.
        assert "after" not in server.calls[0]["params"]
        assert all("after" in c["params"] for c in server.calls[1:])

    def test_count_parity_with_total_number_and_file_count(self):
        """list_files_all count == totalNumber == fileCount (the scenario's
        core assertion)."""
        uids = [f"file-{i:02d}" for i in range(5)]
        server = _KeysetServer([_file(u) for u in uids])

        # getDataset now reports fileCount instead of embedding the files.
        file_count = {"datasetId": "ds-1", "fileCount": 5}["fileCount"]

        result = listFilesAll("ds-1", limit=2, client=server)
        first_page = listFiles("ds-1", limit=2, client=server)

        assert len(result.data) == first_page["totalNumber"] == file_count == 5

    def test_a_single_full_page_needs_no_second_request(self):
        server = _KeysetServer([_file(u) for u in ("a", "b")])

        result = listFilesAll("ds-1", limit=2, client=server)

        # hasMore is false on the only page, so exactly one request is made.
        assert [f["uid"] for f in result.data] == ["a", "b"]
        assert len(server.calls) == 1

    def test_deduplicates_uids_that_straddle_a_page_boundary(self):
        """A concurrent write can make a uid reappear on the next page. The
        walk must return it once, not twice (MATLAB's setdiff dedup)."""
        client = MagicMock()
        client.get.side_effect = [
            {"files": [_file("a"), _file("b")], "cursor": "b", "hasMore": True, "totalNumber": 4},
            # 'b' repeats here -- must be dropped.
            {"files": [_file("b"), _file("c")], "cursor": "c", "hasMore": True, "totalNumber": 4},
            {"files": [_file("d")], "cursor": "d", "hasMore": False, "totalNumber": 4},
        ]

        result = listFilesAll("ds-1", limit=2, client=client)

        assert [f["uid"] for f in result.data] == ["a", "b", "c", "d"]

    def test_a_cursor_that_does_not_advance_terminates(self):
        """A server that echoes the same cursor with hasMore=true must not
        loop forever; the walk stops once the cursor fails to move."""
        client = MagicMock()
        client.get.return_value = {
            "files": [_file("a")],
            "cursor": "a",
            "hasMore": True,
            "totalNumber": 1,
        }

        result = listFilesAll("ds-1", limit=1, client=client)

        assert [f["uid"] for f in result.data] == ["a"]
        # Page 1 (after="") advances to "a"; page 2 (after="a") gets "a" back
        # and stops. Two calls, not _MAX_FILE_PAGES.
        assert client.get.call_count == 2
        assert client.get.call_count < _MAX_FILE_PAGES


class TestCheckForUpdates:
    """The optional re-poll picks up files appended while the scan ran."""

    def test_repolls_from_the_last_cursor_and_stops_when_quiet(self):
        client = MagicMock()
        client.get.side_effect = [
            # Initial scan: two files, no more pages.
            {"files": [_file("a"), _file("b")], "cursor": "b", "hasMore": False, "totalNumber": 2},
            # Update poll from cursor "b": one new file appeared.
            {"files": [_file("c")], "cursor": "c", "hasMore": False, "totalNumber": 3},
            # Update poll from cursor "c": nothing new -> stop.
            {"files": [], "cursor": "", "hasMore": False, "totalNumber": 3},
        ]

        result = listFilesAll(
            "ds-1",
            limit=10,
            check_for_updates=True,
            wait_for_updates=0,  # keep the test fast
            client=client,
        )

        assert [f["uid"] for f in result.data] == ["a", "b", "c"]
        assert client.get.call_count == 3
        # The update polls resume from the last-seen cursor, not the start.
        assert client.get.call_args_list[1].kwargs["params"].get("after") == "b"
        assert client.get.call_args_list[2].kwargs["params"].get("after") == "c"

    def test_disabled_by_default_makes_no_extra_polls(self):
        server = _KeysetServer([_file("a")])

        listFilesAll("ds-1", client=server)

        assert len(server.calls) == 1
