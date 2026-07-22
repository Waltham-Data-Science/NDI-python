"""Regression tests for bulk-download completeness.

Guards the fix for the silent-chunk-drop bug: ``downloadDocumentCollection``
used to swallow every per-chunk failure and return the surviving chunks with no
error signal, so ``downloadDataset`` reported success on a dataset silently
missing whole 2,000-document chunks. It must now raise ``IncompleteDownloadError``
when fewer documents come back than were requested.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import ndi.cloud.download as download
from ndi.cloud.download import IncompleteDownloadError, downloadDocumentCollection


def _make_docs(chunk_ids):
    """A fake extracted-ZIP payload: one dict per requested id."""
    return [{"_id": cid, "base": {"id": cid}} for cid in chunk_ids]


def test_short_chunk_download_raises(monkeypatch):
    """Chunk 2 of 3 fails its presigned-URL request -> the collection is short
    -> IncompleteDownloadError, not a silently truncated list."""
    doc_ids = ["d0", "d1", "d2", "d3", "d4", "d5"]  # 3 chunks of 2 at chunk_size=2
    failing_chunk_marker = "d2"  # id that lands in the 2nd chunk

    def fake_get_url(dataset_id, chunk_ids, *, client=None):
        if failing_chunk_marker in chunk_ids:
            raise RuntimeError("503 Service Unavailable")
        return f"https://fake/{'-'.join(chunk_ids)}"

    def fake_zip(url, timeout, retry_interval):
        # Reconstruct this chunk's ids from the fake URL and return a full doc set.
        chunk_ids = url.rsplit("/", 1)[1].split("-")
        return _make_docs(chunk_ids)

    monkeypatch.setattr("ndi.cloud.api.documents.getBulkDownloadURL", fake_get_url)
    monkeypatch.setattr(download, "_download_chunk_zip", fake_zip)

    with pytest.raises(IncompleteDownloadError) as excinfo:
        downloadDocumentCollection(
            "dataset-1", doc_ids=doc_ids, chunk_size=2, max_workers=1, client=MagicMock()
        )

    err = excinfo.value
    # The two ids from the dropped chunk are reported; the four that downloaded
    # are preserved on the exception for a caller that wants the partial result.
    assert err.expected == 6
    assert err.received == 4
    assert set(err.failed_ids) == {"d2", "d3"}
    assert len(err.documents) == 4


def test_complete_download_returns_all(monkeypatch):
    """The happy path is unchanged: every chunk succeeds -> full list, no raise."""
    doc_ids = ["d0", "d1", "d2", "d3", "d4"]  # 3 chunks (2,2,1) at chunk_size=2

    def fake_get_url(dataset_id, chunk_ids, *, client=None):
        return f"https://fake/{'-'.join(chunk_ids)}"

    def fake_zip(url, timeout, retry_interval):
        chunk_ids = url.rsplit("/", 1)[1].split("-")
        return _make_docs(chunk_ids)

    monkeypatch.setattr("ndi.cloud.api.documents.getBulkDownloadURL", fake_get_url)
    monkeypatch.setattr(download, "_download_chunk_zip", fake_zip)

    docs = downloadDocumentCollection(
        "dataset-1", doc_ids=doc_ids, chunk_size=2, max_workers=1, client=MagicMock()
    )
    assert len(docs) == 5
    assert {d["_id"] for d in docs} == set(doc_ids)
