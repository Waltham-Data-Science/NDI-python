"""
Tests for the previously-deferred cloud sync pieces:

  * ``validate()`` content comparison (MATLAB validate.m mismatch detection).
  * download-side file sync (``_download_files`` + its wiring into the download
    operations).
  * ``orchestration.syncDataset`` routing to the canonical ``operations.sync``
    engine while preserving the legacy return shape.

All cloud/network seams are mocked; no live access is required.
"""

from __future__ import annotations

import pytest

from ndi.cloud import internal as cloud_internal
from ndi.cloud.sync import operations as ops
from ndi.document import ndi_document

# ---------------------------------------------------------------------------
# _deep_equal_nan / _strip_for_compare units
# ---------------------------------------------------------------------------


def test_deep_equal_nan_basics():
    eq = cloud_internal._deep_equal_nan
    assert eq({"a": [1, 2], "b": {"c": 3}}, {"b": {"c": 3}, "a": [1, 2]})
    assert eq(1, 1.0)  # int/float equivalence (MATLAB isequaln)
    assert eq(float("nan"), float("nan"))  # NaN == NaN
    assert not eq({"a": 1}, {"a": 2})
    assert not eq({"a": 1}, {"a": 1, "b": 2})  # different key sets
    assert not eq([1, 2], [1, 2, 3])


def test_strip_for_compare_drops_files_and_remote_id():
    strip = cloud_internal._strip_for_compare
    local = {"base": {"id": "x"}, "files": {"file_info": []}, "k": 1}
    remote = {
        "base": {"id": "x"},
        "files": {"file_info": []},
        "id": "api",
        "_id": "api",
        "ndiId": "x",
        "k": 1,
    }
    assert strip(local, drop_id=False) == {"base": {"id": "x"}, "k": 1}
    assert strip(remote, drop_id=True) == {"base": {"id": "x"}, "k": 1}


# ---------------------------------------------------------------------------
# validateSync content comparison
# ---------------------------------------------------------------------------


def _wire_validate(monkeypatch, local_props_by_id, remote_props_by_id, *, missing_from_download=()):
    """Patch the three seams validateSync uses."""
    local_docs = [ndi_document(dict(p)) for p in local_props_by_id.values()]
    local_ids = list(local_props_by_id.keys())

    def fake_list_local(dataset):
        return local_docs, local_ids

    def fake_list_remote(cloud_id, *, client=None):
        return {ndi_id: f"api_{ndi_id}" for ndi_id in remote_props_by_id}

    def fake_download(cloud_id, doc_ids=None, *, client=None, **kwargs):
        out = []
        api_to_ndi = {f"api_{n}": n for n in remote_props_by_id}
        for api_id in doc_ids or []:
            ndi_id = api_to_ndi.get(api_id)
            if ndi_id is None or ndi_id in missing_from_download:
                continue
            doc = dict(remote_props_by_id[ndi_id])
            doc["_id"] = api_id
            doc["ndiId"] = ndi_id
            out.append(doc)
        return out

    monkeypatch.setattr("ndi.cloud.internal.listLocalDocuments", fake_list_local)
    monkeypatch.setattr("ndi.cloud.internal.listRemoteDocumentIds", fake_list_remote)
    monkeypatch.setattr("ndi.cloud.download.downloadDocumentCollection", fake_download)


def test_validate_detects_matching_and_mismatched_content(monkeypatch):
    local = {
        "a": {"base": {"id": "a"}, "payload": {"v": 1}},
        "b": {"base": {"id": "b"}, "payload": {"v": 2}},
    }
    remote = {
        "a": {"base": {"id": "a"}, "payload": {"v": 1}},  # identical
        "b": {"base": {"id": "b"}, "payload": {"v": 999}},  # differs
    }
    _wire_validate(monkeypatch, local, remote)

    report = cloud_internal.validateSync(object(), "cloud1")
    assert set(report["common_ids"]) == {"a", "b"}
    assert report["mismatched_ids"] == ["b"]
    assert report["mismatch_details"][0]["ndiId"] == "b"
    assert report["mismatch_details"][0]["apiId"] == "api_b"
    assert "do not match" in report["mismatch_details"][0]["reason"]


def test_validate_ignores_files_and_remote_id(monkeypatch):
    # Same content except the remote has the cloud-added id/_id/ndiId and a
    # differing 'files' block — both must be excluded, so NO mismatch.
    local = {"a": {"base": {"id": "a"}, "k": 1, "files": {"file_info": [{"name": "x"}]}}}
    remote = {"a": {"base": {"id": "a"}, "k": 1, "files": {"file_info": []}}}
    _wire_validate(monkeypatch, local, remote)
    report = cloud_internal.validateSync(object(), "cloud1")
    assert report["mismatched_ids"] == []


def test_validate_missing_from_bulk_download_is_mismatch(monkeypatch):
    local = {"a": {"base": {"id": "a"}, "k": 1}}
    remote = {"a": {"base": {"id": "a"}, "k": 1}}
    _wire_validate(monkeypatch, local, remote, missing_from_download=("a",))
    report = cloud_internal.validateSync(object(), "cloud1")
    assert report["mismatched_ids"] == ["a"]
    assert "could not be found" in report["mismatch_details"][0]["reason"]


def test_validate_compare_content_false_skips_download(monkeypatch):
    local = {"a": {"base": {"id": "a"}, "k": 1}}

    def boom(*a, **k):  # download must not be called
        raise AssertionError("download should not be called when compare_content=False")

    monkeypatch.setattr(
        "ndi.cloud.internal.listLocalDocuments",
        lambda ds: ([ndi_document(dict(local["a"]))], ["a"]),
    )
    monkeypatch.setattr(
        "ndi.cloud.internal.listRemoteDocumentIds", lambda c, *, client=None: {"a": "api_a"}
    )
    monkeypatch.setattr("ndi.cloud.download.downloadDocumentCollection", boom)
    report = cloud_internal.validateSync(object(), "cloud1", compare_content=False)
    assert report["common_ids"] == ["a"]
    assert report["mismatched_ids"] == []


# ---------------------------------------------------------------------------
# _download_files
# ---------------------------------------------------------------------------


class _BinDataset:
    """Fake dataset exposing only the binary API _download_files uses."""

    def __init__(self, existing=(), missing=(), errors=()):
        self.existing = set(existing)  # (doc_id, name) already local
        self.missing = set(missing)  # (doc_id, name) fetchable via ndic://
        self.errors = set(errors)  # (doc_id, name) that raise on open
        self.opened: list[tuple[str, str]] = []

    def database_existbinarydoc(self, doc_id, name):
        return ((doc_id, name) in self.existing), "/tmp/x"

    def database_openbinarydoc(self, doc_id, name):
        self.opened.append((doc_id, name))
        if (doc_id, name) in self.errors:
            raise RuntimeError("network down")
        if (doc_id, name) in self.missing:
            return object()  # a fake file object
        raise FileNotFoundError(name)  # no local or remote copy

    def database_closebinarydoc(self, fobj):
        pass


def _doc_with_files(doc_id, names):
    return {"base": {"id": doc_id}, "files": {"file_info": [{"name": n} for n in names]}}


def test_download_files_fetches_missing_skips_existing():
    ds = _BinDataset(existing=[("d1", "a.bin")], missing=[("d1", "b.bin")])
    docs = [_doc_with_files("d1", ["a.bin", "b.bin"])]
    rep = ops._download_files(ds, docs)
    assert rep["downloaded"] == 1  # b.bin fetched
    assert rep["skipped"] == 1  # a.bin already present
    assert rep["failed"] == 0
    assert ("d1", "b.bin") in ds.opened
    assert ("d1", "a.bin") not in ds.opened  # existing not re-opened


def test_download_files_counts_unfetchable_and_errors():
    ds = _BinDataset(missing=[("d1", "ok.bin")], errors=[("d1", "bad.bin")])
    docs = [_doc_with_files("d1", ["ok.bin", "bad.bin", "none.bin"])]
    rep = ops._download_files(ds, docs)
    assert rep["downloaded"] == 1  # ok.bin
    assert rep["failed"] == 1  # bad.bin raised
    assert rep["skipped"] == 1  # none.bin FileNotFoundError -> nothing to fetch


# ---------------------------------------------------------------------------
# downloadNdiDocuments failed-detection (matches by NDI id, not cloud api id)
# ---------------------------------------------------------------------------


def test_downloadNdiDocuments_matches_by_ndi_id(monkeypatch):
    # The live bulk download returns document bodies keyed by NDI id (base.id /
    # ndiId) WITHOUT the cloud api id. Matching by api id flagged every
    # successfully-downloaded doc as failed; failed must be empty here.
    ndi_to_api = {"n1": "api_1", "n2": "api_2"}

    def fake_download(cloud_id, doc_ids=None, *, client=None, **kwargs):
        # bodies carry only base.id + ndiId (no matching "_id" api id)
        return [
            {"base": {"id": "n1"}, "ndiId": "n1"},
            {"base": {"id": "n2"}},  # no ndiId either -> falls back to base.id
        ]

    monkeypatch.setattr("ndi.cloud.download.downloadDocumentCollection", fake_download)
    docs, failed = ops.downloadNdiDocuments("cloud1", ndi_to_api, {"n1", "n2"}, client=object())
    assert failed == []
    assert {d["ndiId"] for d in docs} == {"n1", "n2"}


def test_downloadNdiDocuments_reports_genuinely_missing(monkeypatch):
    ndi_to_api = {"n1": "api_1", "n2": "api_2"}

    def fake_download(cloud_id, doc_ids=None, *, client=None, **kwargs):
        return [{"base": {"id": "n1"}, "ndiId": "n1"}]  # n2 absent

    monkeypatch.setattr("ndi.cloud.download.downloadDocumentCollection", fake_download)
    _docs, failed = ops.downloadNdiDocuments("cloud1", ndi_to_api, ["n1", "n2"], client=object())
    assert failed == ["n2"]


# ---------------------------------------------------------------------------
# download-side sync_files wiring
# ---------------------------------------------------------------------------


def test_downloadNew_invokes_file_sync_only_when_requested(monkeypatch, tmp_path):
    from tests.test_cloud_sync_operations import FakeDataset, FakeRemote

    remote = FakeRemote()
    remote.docs["r1"] = _doc_with_files("r1", ["x.bin"])
    monkeypatch.setattr("ndi.cloud.internal.listRemoteDocumentIds", remote.list_ids)
    monkeypatch.setattr("ndi.cloud.download.downloadDocumentCollection", remote.download)

    calls = []
    monkeypatch.setattr(ops, "_download_files", lambda ds, docs: calls.append(len(docs)) or {})

    # Separate dataset paths so each run starts with a fresh (empty) sync index.
    a = FakeDataset(tmp_path / "a")
    (tmp_path / "a").mkdir()
    ops.downloadNew(a, "cloud1", ops.SyncOptions(sync_files=False), client=object())
    assert calls == []  # not called when sync_files is False

    b = FakeDataset(tmp_path / "b")
    (tmp_path / "b").mkdir()
    ops.downloadNew(b, "cloud1", ops.SyncOptions(sync_files=True), client=object())
    assert calls == [1]  # called once with the one downloaded doc


# ---------------------------------------------------------------------------
# syncDataset routing -> operations.sync (legacy shape preserved)
# ---------------------------------------------------------------------------


def test_syncDataset_routes_and_preserves_shape(monkeypatch):
    from ndi.cloud import orchestration

    captured = {}

    def fake_engine(dataset, cloud_id, mode, options, *, client=None):
        captured["mode"] = mode
        captured["options"] = options
        return {
            "downloaded_document_ids": ["d1", "d2"],
            "uploaded_document_ids": ["u1"],
            "deleted_local_document_ids": ["x1"],
            "deleted_remote_document_ids": [],
            "failed": [],
            "mode": "two_way_sync",
        }

    monkeypatch.setattr(
        "ndi.cloud.internal.getCloudDatasetIdForLocalDataset",
        lambda ds, *, client=None: ("cloud123", None),
    )
    monkeypatch.setattr("ndi.cloud.sync.operations.sync", fake_engine)

    report = orchestration.syncDataset(
        object(), sync_mode="two_way_sync", sync_files=True, client=object()
    )
    assert report["sync_mode"] == "two_way_sync"
    assert report["cloud_dataset_id"] == "cloud123"
    assert report["downloaded"] == 2
    assert report["uploaded"] == 1
    assert report["deleted"] == 1
    assert report["failed"] == []
    assert report["report"]["mode"] == "two_way_sync"
    # routed with the right enum + options
    assert captured["mode"].value == "two_way_sync"
    assert captured["options"].sync_files is True


def test_syncDataset_unknown_mode_and_no_cloud_id(monkeypatch):
    from ndi.cloud import orchestration

    monkeypatch.setattr(
        "ndi.cloud.internal.getCloudDatasetIdForLocalDataset",
        lambda ds, *, client=None: ("cloud123", None),
    )
    monkeypatch.setattr(
        "ndi.cloud.sync.operations.sync",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not route")),
    )
    assert "error" in orchestration.syncDataset(object(), sync_mode="bogus_mode", client=object())

    monkeypatch.setattr(
        "ndi.cloud.internal.getCloudDatasetIdForLocalDataset",
        lambda ds, *, client=None: ("", None),
    )
    assert "error" in orchestration.syncDataset(object(), sync_mode="download_new", client=object())


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
