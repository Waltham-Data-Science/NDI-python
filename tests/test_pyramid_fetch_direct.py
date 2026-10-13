"""Session-free chunk resolution in ndi.pyramid.multiscale._ChunkFetcher.

A pyramid chunk is a file series member. Resolving one needs no database:
the document is in memory, its manifest names each member's uid, and DID's
cached_path_for_uid finds a member on disk with no SQL. So fetcher workers
are plain threads, and a worker opens a session of its own only when a chunk
must go the long way. These tests pin that down:

* a member on disk resolves from a worker thread without any session being
  reopened;
* a member not on disk is fetched through the cloud handler with DID's
  context (seriesName, member uid) and lands where cached_path_for_uid
  finds it;
* an absent (sparse) slot resolves to None, as open_doc's NoSuchMember;
* NDI_LIGHTSHEET_DIRECT=0 goes back through the session;
* configureDaskPool widens dask's pool to the worker count;
* fetch_cloud_file records per-stage timing for the debug log.
"""

from __future__ import annotations

import copy
import os
import threading

import pytest

from ndi.pyramid import multiscale
from ndi.pyramid.multiscale import _ChunkFetcher

SERIES = "chunkdata.bin"
COUNT = 4


def _content(i: int) -> bytes:
    return bytes([(i * 37 + k) % 256 for k in range(64)])


@pytest.fixture
def series_session(tmp_path):
    """A local dataset holding one demoNDISeries document with COUNT members."""
    from did.document import Document as DIDDocument

    from ndi.dataset import ndi_dataset_dir
    from ndi.document import ndi_document

    members = tmp_path / "members"
    members.mkdir()
    paths = []
    for i in range(COUNT):
        p = members / f"chunk_{i + 1}.bin"
        p.write_bytes(_content(i))
        paths.append(str(p))

    local = ndi_dataset_dir("direct_ds", str(tmp_path / "ds"))
    seed = ndi_document("demoNDISeries", **{"base.name": "direct_series", "demoNDISeries.value": 1})
    did_doc = DIDDocument(seed.document_properties)
    did_doc.add_file_series(SERIES, paths)
    doc = ndi_document(did_doc.document_properties)
    local.database_add(doc)
    stored = local.database_search(
        __import__("ndi.query", fromlist=["ndi_query"]).ndi_query("base.id") == doc.id
    )[0]
    return local, stored


def _no_reopen(fetcher):
    """Make any session reopen fail loudly: the direct path must not need one."""

    def boom():
        raise AssertionError("a worker reopened a session")

    fetcher._reopen = boom


def _resolve_on_worker(fetcher, doc, filename):
    out = {}

    def run():
        try:
            out["path"] = fetcher.chunkPath(doc, filename)
        except BaseException as exc:  # noqa: BLE001
            out["exc"] = exc

    t = threading.Thread(target=run)
    t.start()
    t.join(30)
    assert not t.is_alive(), "chunkPath did not return"
    if "exc" in out:
        raise out["exc"]
    return out["path"]


def test_member_on_disk_resolves_without_a_session(series_session):
    session, doc = series_session
    fetcher = _ChunkFetcher(session, workers=4)
    _no_reopen(fetcher)
    try:
        for i in range(COUNT):
            path = _resolve_on_worker(fetcher, doc, f"{SERIES}_{i + 1}")
            assert path is not None
            with open(path, "rb") as f:
                assert f.read() == _content(i), f"member {i + 1} resolved to the wrong file"
        assert fetcher._fallbacks == 0
    finally:
        fetcher.close()


def test_member_not_on_disk_is_fetched_through_the_cloud_handler(
    series_session, monkeypatch, tmp_path
):
    from did.file import cached_path_for_uid, read_series_manifest

    import ndi.cloud.filehandler as fh

    session, doc = series_session
    fetcher = _ChunkFetcher(session, workers=2)
    _no_reopen(fetcher)

    # The manifest's uid list, and the member we will make remote.
    props = copy.deepcopy(doc.document_properties)
    manifest_uid = None
    for info in props["files"]["file_info"]:
        if info["name"] == SERIES:
            locs = info["locations"]
            locs = locs if isinstance(locs, list) else [locs]
            manifest_uid = locs[0]["uid"]
            # Record a cloud copy of the manifest, as a downloaded dataset does.
            locs.append(
                {
                    "location": f"ndic://dsX/{manifest_uid}",
                    "location_type": "ndicloud",
                    "uid": manifest_uid,
                    "ingest": 0,
                    "delete_original": 0,
                }
            )
            info["locations"] = locs
    assert manifest_uid
    manifest_path = cached_path_for_uid(manifest_uid, additional_roots=[fetcher._file_dir])
    uids = read_series_manifest(manifest_path)["uids"]
    member_uid = uids[1]
    on_disk = cached_path_for_uid(member_uid, additional_roots=[fetcher._file_dir])
    os.remove(on_disk)

    calls = []

    def fake_download(dest, source, context=None):
        calls.append((source, dict(context or {})))
        with open(dest, "wb") as f:
            f.write(b"fetched-" + _content(1))

    monkeypatch.setattr(fh, "download_file_from_cloud", fake_download)

    # Keep the fetched file out of the user's global DID cache.
    import did.common

    def no_cache():
        raise OSError("no cache in tests")

    monkeypatch.setattr(did.common, "get_cache", no_cache)

    remote_doc = type(doc)(props)
    try:
        path = _resolve_on_worker(fetcher, remote_doc, f"{SERIES}_2")
        with open(path, "rb") as f:
            assert f.read() == b"fetched-" + _content(1)
        assert len(calls) == 1
        source, context = calls[0]
        assert source == f"ndic://dsX/{manifest_uid}"
        assert context["uid"] == member_uid
        assert context["seriesName"] == SERIES
        assert context["documentId"] == doc.id
        assert context["mode"] == "open"
        # Where DID will find it next time, with no database.
        assert cached_path_for_uid(member_uid, additional_roots=[fetcher._file_dir]) == path
        assert fetcher._fallbacks == 0
    finally:
        fetcher.close()


def test_sparse_slot_is_none(series_session):
    session, doc = series_session
    fetcher = _ChunkFetcher(session, workers=1)
    _no_reopen(fetcher)
    try:
        assert _resolve_on_worker(fetcher, doc, f"{SERIES}_{COUNT + 3}") is None
    finally:
        fetcher.close()


def test_direct_path_can_be_turned_off(series_session, monkeypatch):
    monkeypatch.setenv("NDI_LIGHTSHEET_DIRECT", "0")
    session, doc = series_session
    fetcher = _ChunkFetcher(session, workers=1)
    try:
        # Owner thread: goes through the session's database_openbinarydoc.
        path = fetcher.chunkPath(doc, f"{SERIES}_3")
        with open(path, "rb") as f:
            assert f.read() == _content(2)
        assert fetcher._direct is False
    finally:
        fetcher.close()


def test_default_workers_is_wide(monkeypatch):
    monkeypatch.delenv("NDI_LIGHTSHEET_WORKERS", raising=False)
    assert multiscale._default_workers() == 32
    monkeypatch.setenv("NDI_LIGHTSHEET_WORKERS", "5")
    assert multiscale._default_workers() == 5


def test_configure_dask_pool_matches_workers():
    import dask

    previous = dask.config.get("pool", None)
    try:
        n = multiscale.configureDaskPool(48)
        assert n >= 48
        assert dask.config.get("pool")._max_workers == n
    finally:
        dask.config.set(pool=previous)


def test_fetch_cloud_file_records_stage_timing(monkeypatch, tmp_path):
    import ndi.cloud.api.files as files_api
    import ndi.cloud.filehandler as fh

    monkeypatch.setattr(
        files_api, "getFileDetails", lambda ds, uid, client=None: {"downloadUrl": "https://x"}
    )

    def fake_get(url, dest, **kw):
        with open(dest, "wb") as f:
            f.write(b"x" * 1000)
        return True

    monkeypatch.setattr(files_api, "getFile", fake_get)
    assert fh.fetch_cloud_file("ndic://ds/uid1", tmp_path / "out", client=object())
    t = fh.lastFetchTiming()
    assert t is not None
    assert t["bytes"] == 1000
    assert t["ok"] is True
    assert t["batch"] is False
    assert t["sign_s"] >= 0 and t["transfer_s"] >= 0
