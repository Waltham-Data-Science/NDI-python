"""Binary files go up in zip batches, the way NDI-matlab sends them.

MATLAB counterparts: ``+ndi/+cloud/+upload/zipForUpload.m`` and the
``FileUploadStrategy`` / ``FileBatchSizeLimit`` switch in
``+ndi/+cloud/+sync/+internal/uploadFilesForDatasetDocuments.m``
(NDI-matlab#1033).

Before this, every binary went up on its own signed URL and
``SyncOptions.file_upload_strategy`` was read by nothing. These tests pin the
packing rule (greedy, in order, an oversize file alone), what is inside each
zip, per-batch failure reporting -- a document whose binary did not arrive
must be named so the sync keeps it out of the index (NDI-matlab#805) -- and
that the size limit comes from ``Cloud.Upload.Max_File_Batch_Size`` unless a
caller overrides it.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

import ndi.cloud.internal
import ndi.cloud.sync.operations as ops
import ndi.cloud.upload as upload
import ndi.preferences
from ndi.cloud.api import files as files_api
from ndi.cloud.sync.mode import SyncOptions

CLOUD_ID = "65a1b2c3d4e5f60718293a4b"


class _Client:
    """A stand-in client; the dataset's organization is looked up, not configured."""


def _manifest(tmp_path: Path, sizes: dict[str, int]) -> list[dict]:
    """One file per document, named by the document; ``uid-<doc>`` as uid."""
    entries = []
    for doc_id, size in sizes.items():
        path = tmp_path / f"{doc_id}.bin"
        path.write_bytes(doc_id.encode() * size)
        entries.append(
            {
                "document_id": doc_id,
                "file_uid": f"uid-{doc_id}",
                "file_path": str(path),
                "bytes": path.stat().st_size,
            }
        )
    return entries


class _Server:
    """Records each zip sent and lets a test fail chosen steps."""

    def __init__(self, monkeypatch, *, job_states=None, url_fails=0, put_fails=0, job_id=True):
        self.zips: list[dict[str, bytes]] = []
        self.zip_paths: list[str] = []
        self.url_calls = 0
        self.put_calls = 0
        self._url_fails = url_fails
        self._put_fails = put_fails
        self._job_states = list(job_states or [])
        self._job_id = job_id
        self.waited: list[str] = []

        def _url(org_id, dataset_id, client=None):
            self.url_calls += 1
            assert org_id == "org-1"
            assert dataset_id == CLOUD_ID
            if self.url_calls <= self._url_fails:
                raise RuntimeError("no URL today")
            n = self.url_calls
            return {
                "url": f"https://bucket.example.com/zip{n}?sig=1",
                "jobId": f"job-{n}" if self._job_id else "",
            }

        def _put(url, path, **kwargs):
            self.put_calls += 1
            if self.put_calls <= self._put_fails:
                raise RuntimeError("connection reset")
            # The zip is deleted once sent, so read it while it exists.
            with zipfile.ZipFile(path) as zf:
                self.zips.append({name: zf.read(name) for name in zf.namelist()})
            self.zip_paths.append(path)
            return True

        def _wait(job_id, timeout=60.0, client=None, **kwargs):
            self.waited.append(job_id)
            state = self._job_states.pop(0) if self._job_states else "complete"
            return {"state": state}

        # The organization comes from the dataset record, as in MATLAB's
        # GetFileCollectionUploadURL -- not from the logged-in user.
        def _dataset_org(dataset_id, client=None):
            assert dataset_id == CLOUD_ID
            return "org-1"

        monkeypatch.setattr(ndi.cloud.internal, "_datasetOrganizationId", _dataset_org)
        monkeypatch.setattr(files_api, "getFileCollectionUploadURL", _url)
        monkeypatch.setattr(files_api, "putFiles", _put)
        monkeypatch.setattr(files_api, "waitForBulkUpload", _wait)


def _zip(manifest, **kwargs):
    kwargs.setdefault("retry_pause", 0)
    return upload.zipForUpload(manifest, CLOUD_ID, client=_Client(), **kwargs)


class TestPacking:
    def test_files_fill_a_batch_until_the_next_would_overflow(self, monkeypatch, tmp_path):
        server = _Server(monkeypatch)
        manifest = _manifest(tmp_path, {"a": 40, "b": 40, "c": 40})

        report = _zip(manifest, size_limit=100)

        assert [sorted(z) for z in server.zips] == [["uid-a", "uid-b"], ["uid-c"]]
        assert report["batches"] == 2
        assert report["uploaded"] == 3
        assert report["failed"] == 0

    def test_a_file_bigger_than_the_limit_goes_up_alone(self, monkeypatch, tmp_path):
        server = _Server(monkeypatch)
        manifest = _manifest(tmp_path, {"a": 10, "big": 500, "c": 10})

        report = _zip(manifest, size_limit=100)

        assert [sorted(z) for z in server.zips] == [["uid-a"], ["uid-big"], ["uid-c"]]
        assert report["uploaded"] == 3

    def test_everything_fits_in_one_batch(self, monkeypatch, tmp_path):
        server = _Server(monkeypatch)
        _zip(_manifest(tmp_path, {"a": 5, "b": 5, "c": 5}), size_limit=1e9)
        assert len(server.zips) == 1

    def test_entries_are_named_by_uid_and_hold_the_file(self, monkeypatch, tmp_path):
        server = _Server(monkeypatch)
        manifest = _manifest(tmp_path, {"a": 3})
        _zip(manifest, size_limit=1e9)
        assert server.zips == [{"uid-a": b"aaa"}]

    def test_the_temporary_zips_are_removed(self, monkeypatch, tmp_path):
        server = _Server(monkeypatch)
        _zip(_manifest(tmp_path, {"a": 40, "b": 40}), size_limit=50)
        assert len(server.zip_paths) == 2
        assert not any(Path(p).exists() for p in server.zip_paths)

    def test_a_non_positive_limit_is_refused(self, monkeypatch, tmp_path):
        _Server(monkeypatch)
        with pytest.raises(ValueError):
            _zip(_manifest(tmp_path, {"a": 1}), size_limit=0)


class TestTheLimitComesFromThePreference:
    def test_no_limit_reads_max_file_batch_size(self, monkeypatch, tmp_path):
        server = _Server(monkeypatch)
        asked = []
        real_get = ndi.preferences.get

        def _get(path):
            asked.append(path)
            return 50 if path == "Cloud.Upload.Max_File_Batch_Size" else real_get(path)

        monkeypatch.setattr(ndi.preferences, "get", _get)

        _zip(_manifest(tmp_path, {"a": 40, "b": 40}))

        assert "Cloud.Upload.Max_File_Batch_Size" in asked
        assert len(server.zips) == 2

    def test_the_default_preference_is_250_mb(self, tmp_path):
        prefs = ndi.preferences.ndi_preferences(tmp_path / "prefs.json")
        assert prefs.get("Cloud.Upload.Max_File_Batch_Size") == 250_000_000


class TestFailuresNameTheirDocuments:
    def test_an_extraction_job_that_fails_fails_its_batch_only(self, monkeypatch, tmp_path):
        _Server(monkeypatch, job_states=["complete", "failed"])
        manifest = _manifest(tmp_path, {"a": 40, "b": 40, "c": 40})

        report = _zip(manifest, size_limit=100)

        assert report["uploaded"] == 2
        assert report["failed"] == 1
        assert report["failed_document_ids"] == ["c"]
        assert "job-2" in report["errors"][0]

    def test_a_job_still_running_at_the_deadline_is_not_claimed(self, monkeypatch, tmp_path):
        _Server(monkeypatch, job_states=["timeout"])
        report = _zip(_manifest(tmp_path, {"a": 1, "b": 1}), size_limit=1e9)
        assert report["uploaded"] == 0
        assert sorted(report["failed_document_ids"]) == ["a", "b"]

    def test_no_url_after_every_retry_fails_the_batch(self, monkeypatch, tmp_path):
        server = _Server(monkeypatch, url_fails=99)
        report = _zip(_manifest(tmp_path, {"a": 1}), size_limit=1e9, number_retries=3)
        assert server.url_calls == 3
        assert server.put_calls == 0
        assert report["failed_document_ids"] == ["a"]

    def test_a_transient_url_failure_is_retried(self, monkeypatch, tmp_path):
        _Server(monkeypatch, url_fails=1)
        report = _zip(_manifest(tmp_path, {"a": 1}), size_limit=1e9, number_retries=3)
        assert report["uploaded"] == 1
        assert report["failed_document_ids"] == []

    def test_a_put_that_never_succeeds_fails_the_batch(self, monkeypatch, tmp_path):
        server = _Server(monkeypatch, put_fails=99)
        report = _zip(_manifest(tmp_path, {"a": 1}), size_limit=1e9, number_retries=2)
        assert server.put_calls == 2
        assert report["failed_document_ids"] == ["a"]
        assert server.waited == []

    def test_a_file_gone_before_zipping_fails_its_batch(self, monkeypatch, tmp_path):
        server = _Server(monkeypatch)
        manifest = _manifest(tmp_path, {"a": 1, "b": 1})
        Path(manifest[1]["file_path"]).unlink()
        report = _zip(manifest, size_limit=1e9)
        assert server.put_calls == 0
        assert sorted(report["failed_document_ids"]) == ["a", "b"]

    def test_a_server_without_job_ids_is_trusted_on_the_put(self, monkeypatch, tmp_path):
        server = _Server(monkeypatch, job_id=False)
        report = _zip(_manifest(tmp_path, {"a": 1}), size_limit=1e9)
        assert server.waited == []
        assert report["uploaded"] == 1

    def test_every_batch_is_sent_before_any_job_is_waited_on(self, monkeypatch, tmp_path):
        server = _Server(monkeypatch)
        order = []
        real_put, real_wait = files_api.putFiles, files_api.waitForBulkUpload
        monkeypatch.setattr(
            files_api, "putFiles", lambda *a, **k: (order.append("put"), real_put(*a, **k))[1]
        )
        monkeypatch.setattr(
            files_api,
            "waitForBulkUpload",
            lambda *a, **k: (order.append("wait"), real_wait(*a, **k))[1],
        )
        _zip(_manifest(tmp_path, {"a": 40, "b": 40}), size_limit=50)
        assert order == ["put", "put", "wait", "wait"]
        assert server.waited == ["job-1", "job-2"]


class TestTheStrategySwitch:
    def _docs(self, tmp_path):
        (tmp_path / "a").write_bytes(b"x")
        (tmp_path / "b").write_bytes(b"y")
        return [
            {"ndiId": "a", "file_uid": "uid-a", "file_path": str(tmp_path / "a")},
            {"ndiId": "b", "file_uid": "uid-b", "file_path": str(tmp_path / "b")},
        ]

    def test_batch_is_the_default_and_sends_zips(self, monkeypatch, tmp_path):
        server = _Server(monkeypatch)
        monkeypatch.setattr(
            files_api,
            "getFileUploadURL",
            lambda *a, **k: pytest.fail("batch mode must not ask for per-file URLs"),
        )
        report = upload.uploadFilesForDatasetDocuments(
            "org-1", CLOUD_ID, self._docs(tmp_path), client=_Client()
        )
        assert [sorted(z) for z in server.zips] == [["uid-a", "uid-b"]]
        assert report["uploaded"] == 2
        assert report["failed_document_ids"] == []
        assert "batches" not in report

    def test_the_batch_size_limit_reaches_the_batcher(self, monkeypatch, tmp_path):
        server = _Server(monkeypatch)
        upload.uploadFilesForDatasetDocuments(
            "org-1", CLOUD_ID, self._docs(tmp_path), file_batch_size_limit=1, client=_Client()
        )
        assert len(server.zips) == 2

    def test_serial_sends_each_file_on_its_own_url(self, monkeypatch, tmp_path):
        sent = []
        monkeypatch.setattr(
            files_api, "getFileUploadURL", lambda org, ds, uid, client=None: f"https://s3/{uid}"
        )
        monkeypatch.setattr(files_api, "putFiles", lambda url, path, **k: sent.append(url))
        monkeypatch.setattr(
            files_api,
            "getFileCollectionUploadURL",
            lambda *a, **k: pytest.fail("serial mode must not ask for a zip URL"),
        )
        report = upload.uploadFilesForDatasetDocuments(
            "org-1", CLOUD_ID, self._docs(tmp_path), file_upload_strategy="serial", client=_Client()
        )
        assert sent == ["https://s3/uid-a", "https://s3/uid-b"]
        assert report["uploaded"] == 2

    def test_an_unknown_strategy_is_refused(self, tmp_path):
        with pytest.raises(ValueError):
            upload.uploadFilesForDatasetDocuments(
                "org-1", CLOUD_ID, [], file_upload_strategy="parallel", client=_Client()
            )

    def test_no_files_means_no_requests(self, monkeypatch):
        server = _Server(monkeypatch)
        report = upload.uploadFilesForDatasetDocuments(
            "org-1", CLOUD_ID, [{"ndiId": "a"}], client=_Client()
        )
        assert server.url_calls == 0
        assert report == {"uploaded": 0, "failed": 0, "errors": [], "failed_document_ids": []}


class TestSyncOptionsReachTheUpload:
    def test_strategy_and_limit_are_passed_through(self, monkeypatch):
        seen = {}

        def _capture(org_id, dataset_id, documents, **kwargs):
            seen.update(kwargs)
            return {"failed_document_ids": []}

        monkeypatch.setattr(upload, "uploadFilesForDatasetDocuments", _capture)
        options = SyncOptions(
            sync_files=True, file_upload_strategy="serial", file_batch_size_limit=123.0
        )
        ops._upload_binaries(CLOUD_ID, [{"ndiId": "a"}], options, client=_Client())

        assert seen["file_upload_strategy"] == "serial"
        assert seen["file_batch_size_limit"] == 123.0

    def test_the_default_options_defer_to_the_preference(self):
        options = SyncOptions()
        assert options.file_upload_strategy == "batch"
        assert options.file_batch_size_limit is None


class TestDocumentCountsComeFromPreferences:
    def test_download_chunk_size_defaults_to_the_preference(self, monkeypatch):
        from ndi.cloud import download
        from ndi.cloud.api import documents as docs_api

        monkeypatch.setattr(
            ndi.preferences,
            "get",
            lambda path: 2 if path == "Cloud.Download.Max_Document_Batch_Count" else None,
        )
        chunks = []

        def _url(dataset_id, ids, client=None):
            chunks.append(list(ids))
            return ""

        monkeypatch.setattr(docs_api, "getBulkDownloadURL", _url)
        # No URL comes back, so the download is short and says so; only the
        # chunking is under test here.
        with pytest.raises(RuntimeError, match="incomplete"):
            download.downloadDocumentCollection(CLOUD_ID, ["d1", "d2", "d3"], client=_Client())
        assert chunks == [["d1", "d2"], ["d3"]]

    @pytest.mark.usefixtures("serial_document_upload")
    def test_upload_chunk_defaults_to_the_preference(self, monkeypatch):
        from ndi.cloud.api import documents as docs_api

        asked = []

        def _get(path):
            asked.append(path)
            return 2

        monkeypatch.setattr(ndi.preferences, "get", _get)
        monkeypatch.setattr(docs_api, "addDocument", lambda *a, **k: {"ok": True})
        report = upload.uploadDocumentCollection(
            CLOUD_ID, [{"ndiId": "a"}, {"ndiId": "b"}, {"ndiId": "c"}], only_missing=False
        )
        assert asked == ["Cloud.Upload.Max_Document_Batch_Count"]
        assert report["uploaded"] == 3
