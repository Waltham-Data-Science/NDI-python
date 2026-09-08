"""A downloaded document must fetch EVERY file it records, not one.

MATLAB counterpart: ``+ndi/+cloud/+sync/+internal/getFileUidsFromDocuments.m``

A document records its files in ``files.file_info(j).locations(k).uid``.
``downloadFilesForDocument`` read a single top-level ``document["file_uid"]``
and returned empty when there was none -- which is the ordinary case. So an
ordinary document downloaded nothing at all, and a document with several
files could never have fetched more than one.

``getFileUidsFromDocuments`` had walked file_info correctly all along. It
simply had no callers, and carried two defects of its own that no caller had
exercised: it returned a set (so the order depended on Python's string
hashing) and it did not normalise MATLAB's one-element-struct-as-bare-object
encoding (so a single-file document's only file was skipped).

These are written as "what does the document say it has, and did we fetch
all of it", because a short download does not look broken -- it looks like a
dataset with fewer files.
"""

from __future__ import annotations

import pytest

import ndi.cloud.download as download
from ndi.cloud.internal import getFileUidsFromDocuments


def _doc(*file_entries):
    """A document whose files.file_info is ``file_entries``."""
    return {"base": {"id": "doc_1"}, "files": {"file_info": list(file_entries)}}


def _file(name, *uids):
    return {"name": name, "locations": [{"uid": u, "location": f"ndic://ds/{u}"} for u in uids]}


class TestGetFileUidsFromDocuments:
    def test_it_walks_file_info_locations(self):
        uids = getFileUidsFromDocuments([_doc(_file("a.bin", "UID_A"), _file("b.bin", "UID_B"))])
        assert uids == ["UID_A", "UID_B"]

    def test_a_file_with_several_locations_yields_each_uid(self):
        """A file can be recorded in more than one place -- a local path and
        a cloud reference, say -- and each location has its own uid."""
        uids = getFileUidsFromDocuments([_doc(_file("a.bin", "UID_LOCAL", "UID_CLOUD"))])
        assert uids == ["UID_LOCAL", "UID_CLOUD"]

    def test_a_single_file_document_is_not_invisible(self):
        """MATLAB's jsonencode writes a one-element struct array as a bare
        object, so file_info arrives as a dict. Iterating that yields its
        KEYS, which are then skipped as "not a dict" -- and the document's
        only file was silently missed. This is the shape every single-file
        document downloaded from a MATLAB-written dataset has."""
        doc = {"files": {"file_info": {"name": "only.bin", "locations": {"uid": "UID_ONLY"}}}}
        assert getFileUidsFromDocuments([doc]) == ["UID_ONLY"]

    def test_order_is_first_seen_and_repeatable(self):
        """MATLAB returns unique(...,'stable'). A set here made the download
        order differ between runs of the same input, for no reason."""
        docs = [_doc(_file("a", "U3", "U1")), _doc(_file("b", "U2", "U1", "U9"))]
        assert getFileUidsFromDocuments(docs) == ["U3", "U1", "U2", "U9"]

    def test_a_top_level_file_uid_is_still_honoured(self):
        doc = {"file_uid": "UID_TOP", "files": {"file_info": [_file("a", "UID_A")]}}
        assert getFileUidsFromDocuments([doc]) == ["UID_A", "UID_TOP"]

    def test_a_document_with_no_files_yields_nothing(self):
        assert getFileUidsFromDocuments([{"base": {"id": "d"}}]) == []
        assert getFileUidsFromDocuments([]) == []

    def test_junk_does_not_raise(self):
        """Downloaded JSON is the cloud's, not ours."""
        assert getFileUidsFromDocuments(["not a document", None, 7]) == []
        assert getFileUidsFromDocuments([{"files": "not a dict"}]) == []
        assert getFileUidsFromDocuments([{"files": {"file_info": ["junk", None]}}]) == []


@pytest.fixture
def stubbed_transfer(monkeypatch):
    """A cloud that hands back one small file for any uid asked for.

    Records the uids requested, in order, so a test can say which files were
    actually fetched rather than only how many.
    """
    import requests

    import ndi.cloud.api

    seen: dict[str, list[str]] = {"uids": []}

    class FakeFiles:
        @staticmethod
        def getFileDetails(dataset_id, uid, *, client=None):
            seen["uids"].append(uid)
            return {"downloadUrl": f"https://example.invalid/{uid}"}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def iter_content(chunk_size=8192):
            yield b"payload"

    monkeypatch.setattr(ndi.cloud.api, "files", FakeFiles, raising=False)
    monkeypatch.setattr(requests, "get", lambda url, **kw: FakeResponse())
    return seen


class TestDownloadFilesForDocument:
    def test_an_ordinary_document_downloads_its_files(self, tmp_path, stubbed_transfer):
        """The bug in one line: no top-level file_uid, so nothing was fetched."""
        written = download.downloadFilesForDocument(
            "ds", _doc(_file("a.bin", "UID_A")), tmp_path, client=object()
        )

        assert stubbed_transfer["uids"] == ["UID_A"]
        assert written == [tmp_path.resolve() / "UID_A"]

    def test_every_file_of_a_multi_file_document(self, tmp_path, stubbed_transfer):
        written = download.downloadFilesForDocument(
            "ds",
            _doc(_file("a.bin", "UID_A"), _file("b.bin", "UID_B"), _file("c.bin", "UID_C")),
            tmp_path,
            client=object(),
        )

        assert stubbed_transfer["uids"] == ["UID_A", "UID_B", "UID_C"]
        assert len(written) == 3
        for uid in ("UID_A", "UID_B", "UID_C"):
            assert (tmp_path / uid).read_bytes() == b"payload"

    def test_one_unreachable_file_does_not_end_the_document(
        self, tmp_path, stubbed_transfer, monkeypatch
    ):
        """Every early return used to abandon the whole document's download."""
        import ndi.cloud.api

        real = ndi.cloud.api.files.getFileDetails

        class PickyFiles:
            @staticmethod
            def getFileDetails(dataset_id, uid, *, client=None):
                if uid == "UID_B":
                    raise RuntimeError("gone")
                return real(dataset_id, uid, client=client)

        monkeypatch.setattr(ndi.cloud.api, "files", PickyFiles, raising=False)

        written = download.downloadFilesForDocument(
            "ds",
            _doc(_file("a.bin", "UID_A"), _file("b.bin", "UID_B"), _file("c.bin", "UID_C")),
            tmp_path,
            client=object(),
        )

        assert [p.name for p in written] == ["UID_A", "UID_C"]


class TestDownloadDatasetFilesReport:
    def test_the_report_counts_files_not_documents(self, tmp_path, stubbed_transfer):
        docs = [_doc(_file("a", "U1"), _file("b", "U2")), _doc(_file("c", "U3"))]
        report = download.downloadDatasetFiles("ds", docs, tmp_path, client=object())

        assert report["downloaded"] == 3
        assert report["failed"] == 0

    def test_a_partial_download_is_reported_as_failed(self, tmp_path, monkeypatch):
        """ "failed" counted documents whose download RAISED -- and a per-file
        failure warns rather than raising, so a document that fetched none of
        its files still reported zero failures. A caller reading this to
        decide whether the download was complete was told yes."""
        import requests

        import ndi.cloud.api

        class NoFiles:
            @staticmethod
            def getFileDetails(dataset_id, uid, *, client=None):
                return {"downloadUrl": ""}

        monkeypatch.setattr(ndi.cloud.api, "files", NoFiles, raising=False)
        monkeypatch.setattr(requests, "get", lambda url, **kw: None)

        report = download.downloadDatasetFiles(
            "ds", [_doc(_file("a", "U1"), _file("b", "U2"))], tmp_path, client=object()
        )

        assert report["downloaded"] == 0
        assert report["failed"] == 2
