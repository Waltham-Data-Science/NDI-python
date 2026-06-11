"""
Tests for the cloud binary-file upload path (audit C3).

Binaries are referenced under ``files.file_info[].locations[].uid`` (not a
top-level ``file_uid``); the previous implementation read the wrong field and
uploaded nothing without error. The bulk ``uploadSingleFile`` branch also
passed the ``{url, jobId}`` dict where a URL string was expected. The S3 byte
transfer itself is mocked here (no live cloud).
"""

from __future__ import annotations

import unittest.mock as mock

from ndi.cloud import upload


def _props_with_file(doc_id: str, name: str, uid: str, location_type: str = "file") -> dict:
    return {
        "base": {"id": doc_id},
        "files": {
            "file_info": [
                {
                    "name": name,
                    "locations": [
                        {"uid": uid, "location": f"/data/{name}", "location_type": location_type}
                    ],
                }
            ]
        },
    }


class FakeDataset:
    def __init__(self, binary_paths: dict):
        # (doc_id, filename) -> path
        self._binary_paths = binary_paths

    def database_existbinarydoc(self, doc_or_id, filename):
        key = (doc_or_id, filename)
        if key in self._binary_paths:
            return True, self._binary_paths[key]
        return False, None


class TestBinaryFileManifest:
    def test_reads_uid_from_file_info_locations(self):
        """C3: the manifest must come from files.file_info[].locations[].uid."""
        dataset = FakeDataset({("doc-1", "rec.dat"): "/store/rec.dat"})
        docs = [_props_with_file("doc-1", "rec.dat", "uid-abc")]

        manifest = upload._binary_file_manifest(dataset, docs)

        assert manifest == [{"uid": "uid-abc", "name": "rec.dat", "file_path": "/store/rec.dat"}]

    def test_ignores_top_level_file_uid(self):
        """A legacy top-level file_uid must NOT be treated as a binary."""
        dataset = FakeDataset({})
        docs = [{"base": {"id": "d"}, "file_uid": "legacy", "file_path": "/x"}]
        assert upload._binary_file_manifest(dataset, docs) == []

    def test_skips_ndicloud_locations(self):
        """Files already on the remote (ndicloud) are not re-uploaded."""
        dataset = FakeDataset({("doc-1", "rec.dat"): "/store/rec.dat"})
        docs = [_props_with_file("doc-1", "rec.dat", "uid-abc", location_type="ndicloud")]
        assert upload._binary_file_manifest(dataset, docs) == []

    def test_skips_unresolvable_binaries(self):
        dataset = FakeDataset({})  # no stored binary
        docs = [_props_with_file("doc-1", "rec.dat", "uid-abc")]
        assert upload._binary_file_manifest(dataset, docs) == []


class TestUploadFilesForDatasetDocuments:
    def test_uploads_each_resolved_file(self):
        dataset = FakeDataset({("doc-1", "rec.dat"): "/store/rec.dat"})
        docs = [_props_with_file("doc-1", "rec.dat", "uid-abc")]

        calls = []

        def fake_single(dataset_id, uid, file_path, *, use_bulk_upload=False, client=None):
            calls.append((dataset_id, uid, file_path, use_bulk_upload))
            return True, ""

        with mock.patch.object(upload, "uploadSingleFile", fake_single):
            with mock.patch(
                "ndi.cloud.internal.filesNotYetUploaded", side_effect=lambda m, d, client=None: m
            ):
                report = upload.uploadFilesForDatasetDocuments(dataset, "cloud-ds", docs)

        assert calls == [("cloud-ds", "uid-abc", "/store/rec.dat", True)]
        assert report["uploaded"] == 1
        assert report["failed"] == 0


class TestUploadSingleFileBulkBranch:
    def test_bulk_branch_passes_url_string_not_dict(self, tmp_path):
        """C3: the bulk branch must pass info['url'] (a string) into putFiles,
        not the whole {url, jobId} dict."""
        src = tmp_path / "f.dat"
        src.write_bytes(b"hello")

        client = mock.MagicMock()
        client.config.org_id = "org-1"

        put_calls = []

        fake_files = mock.MagicMock()
        fake_files.getFileCollectionUploadURL.return_value = {
            "url": "https://s3/put",
            "jobId": "job-9",
        }

        def fake_put(url, file_path, *, job_id="", **kwargs):
            put_calls.append((url, job_id))
            return True

        fake_files.putFiles.side_effect = fake_put

        with mock.patch.dict("sys.modules", {"ndi.cloud.api.files": fake_files}):
            with mock.patch("ndi.cloud.api.files", fake_files):
                ok, msg = upload.uploadSingleFile(
                    "cloud-ds", "uid-1", str(src), use_bulk_upload=True, client=client
                )

        assert ok, msg
        assert put_calls == [("https://s3/put", "job-9")]


class TestUploadToNDICloud:
    def test_uploads_documents_via_collection(self):
        """C3: uploadToNDICloud is rebuilt on uploadDocumentCollection and must
        not mis-unpack zipForUpload's (Path, list) return as (success, msg)."""
        from ndi.document import ndi_document

        doc = ndi_document({"base": {"id": "d1"}})

        dataset = mock.MagicMock()
        dataset.database_search.return_value = [doc]
        client = mock.MagicMock()

        with mock.patch.object(
            upload,
            "uploadDocumentCollection",
            return_value={"status": "ok", "manifest": ["d1"], "uploaded": 1, "skipped": 0},
        ) as up_coll:
            with mock.patch.object(
                upload, "uploadFilesForDatasetDocuments", return_value={"uploaded": 0, "failed": 0}
            ):
                ok, msg = upload.uploadToNDICloud(dataset, "cloud-ds", verbose=False, client=client)

        assert ok, msg
        up_coll.assert_called_once()
        # full document props were passed (not stubs)
        passed_docs = up_coll.call_args[0][1]
        assert passed_docs[0]["base"]["id"] == "d1"
