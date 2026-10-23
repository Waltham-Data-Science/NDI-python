"""Bulk document upload and the ingestion wait -- no network required.

MATLAB counterparts: +ndi/+cloud/+upload/uploadDocumentCollection.m (batch
path), +ndi/+cloud/+upload/+internal/zip_documents_for_upload.m, and
tests/+ndi/+unittest/WaitForDocumentCountMockTest.m.

uploadDocumentCollection sends documents in bulk -- each chunk one zipped
JSON array PUT to a presigned URL -- rather than one request per document,
which for a dataset of 100,000 documents is the difference between minutes
and hours. A stored zip is not yet an ingested one, and a bulk document
upload has no job id to wait on, so afterwards it waits for the dataset's
document count to take the new documents in (VH-Lab/NDI-matlab#1047).
"""

from __future__ import annotations

import json
import math
import zipfile
from unittest.mock import MagicMock

import pytest

import ndi.cloud.upload as upload
from ndi.cloud.api import documents as docs_api
from ndi.cloud.api import files as files_api

CLOUD_ID = "65a1b2c3d4e5f60718293a4b"


def _make_client() -> MagicMock:
    client = MagicMock()
    client.config.api_url = "https://api.ndi-cloud.com/v1"
    return client


def _docs(*ids):
    return [{"base": {"id": i}, "value": n} for n, i in enumerate(ids)]


class _ScriptedCount:
    """countDocuments returning scripted values; an Exception entry is raised.

    The final entry repeats, so "never arrives" is one entry.
    """

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def __call__(self, dataset_id, *, client=None):
        self.calls += 1
        item = self.script[min(self.calls - 1, len(self.script) - 1)]
        if isinstance(item, Exception):
            raise item
        return item


class _BulkServer:
    """Stands in for getBulkUploadURL + putFiles and records each zip's documents."""

    def __init__(self, fail_batches=()):
        self.fail_batches = set(fail_batches)
        self.batches: list[list[dict]] = []
        self.zip_paths: list[str] = []

    def url(self, dataset_id, *, client=None):
        return f"https://s3.example/bulk/{len(self.zip_paths) + 1}"

    def put(self, url, file_path, *args, **kwargs):
        self.zip_paths.append(file_path)
        with zipfile.ZipFile(file_path) as zf:
            names = zf.namelist()
            assert len(names) == 1 and names[0].endswith(".json")
            self.batches.append(json.loads(zf.read(names[0])))
        if len(self.zip_paths) in self.fail_batches:
            raise RuntimeError("S3 said no")
        return True


@pytest.fixture()
def bulk(monkeypatch):
    monkeypatch.delenv("NDI_CLOUD_UPLOAD_NO_ZIP", raising=False)
    server = _BulkServer()
    monkeypatch.setattr(docs_api, "getBulkUploadURL", server.url)
    monkeypatch.setattr(files_api, "putFiles", server.put)

    def _no_single_adds(*a, **k):
        raise AssertionError("a bulk upload must not send documents one at a time")

    monkeypatch.setattr(docs_api, "addDocument", _no_single_adds)
    return server


# ---------------------------------------------------------------------------
# zip_documents_for_upload
# ---------------------------------------------------------------------------


class TestZipDocumentsForUpload:
    def test_one_json_array_of_the_documents(self, tmp_path):
        docs = _docs("a", "b")
        zip_path, ids = upload.zip_documents_for_upload(docs, CLOUD_ID, target_folder=tmp_path)
        with zipfile.ZipFile(zip_path) as zf:
            (name,) = zf.namelist()
            assert name.endswith(".json")
            assert json.loads(zf.read(name)) == docs
        assert ids == ["a", "b"]

    def test_named_for_the_dataset_and_unique(self, tmp_path):
        p1, _ = upload.zip_documents_for_upload(_docs("a"), CLOUD_ID, target_folder=tmp_path)
        p2, _ = upload.zip_documents_for_upload(_docs("a"), CLOUD_ID, target_folder=tmp_path)
        assert p1.name.startswith(CLOUD_ID + ".") and p1.suffix == ".zip"
        assert p1 != p2

    def test_nan_and_infinity_survive(self, tmp_path):
        docs = [{"base": {"id": "a"}, "x": float("nan"), "y": float("inf")}]
        zip_path, _ = upload.zip_documents_for_upload(docs, CLOUD_ID, target_folder=tmp_path)
        with zipfile.ZipFile(zip_path) as zf:
            back = json.loads(zf.read(zf.namelist()[0]))
        assert math.isnan(back[0]["x"]) and back[0]["y"] == math.inf


# ---------------------------------------------------------------------------
# uploadDocumentCollection -- the bulk path
# ---------------------------------------------------------------------------


class TestBulkUpload:
    def test_chunks_go_up_as_zips_not_one_by_one(self, bulk, monkeypatch):
        monkeypatch.setattr(docs_api, "countDocuments", _ScriptedCount([0, 5]))
        docs = _docs("a", "b", "c", "d", "e")
        report = upload.uploadDocumentCollection(
            CLOUD_ID, docs, only_missing=False, max_chunk=2, client=_make_client()
        )
        assert bulk.batches == [docs[0:2], docs[2:4], docs[4:5]]
        assert report["upload_type"] == "batch"
        assert report["status"] == "ok"
        assert report["uploaded"] == 5
        assert report["manifest"] == ["a", "b", "c", "d", "e"]

    def test_the_zips_are_deleted(self, bulk, monkeypatch):
        from pathlib import Path

        monkeypatch.setattr(docs_api, "countDocuments", _ScriptedCount([0, 2]))
        upload.uploadDocumentCollection(
            CLOUD_ID, _docs("a", "b"), only_missing=False, max_chunk=1, client=_make_client()
        )
        assert len(bulk.zip_paths) == 2
        assert not any(Path(p).exists() for p in bulk.zip_paths)

    def test_a_failed_batch_is_partial_and_the_rest_still_go(self, bulk, monkeypatch):
        bulk.fail_batches = {1}
        monkeypatch.setattr(docs_api, "countDocuments", _ScriptedCount([0, 1]))
        report = upload.uploadDocumentCollection(
            CLOUD_ID, _docs("a", "b"), only_missing=False, max_chunk=1, client=_make_client()
        )
        assert report["status"] == "partial"
        assert report["uploaded"] == 1
        assert report["manifest"] == ["b"]
        assert len(report["errors"]) == 1 and "S3 said no" in report["errors"][0]

    def test_the_wait_expects_the_count_before_plus_the_documents_stored(self, bulk, monkeypatch):
        monkeypatch.setattr(docs_api, "countDocuments", _ScriptedCount([7]))
        waits = []

        def _wait(dataset_id, expected, *, timeout, client=None):
            waits.append((expected, timeout))
            return {"state": "complete", "count": expected, "expectedCount": expected}

        monkeypatch.setattr(docs_api, "waitForDocumentCount", _wait)
        report = upload.uploadDocumentCollection(
            CLOUD_ID,
            _docs("a", "b", "c"),
            only_missing=False,
            ingestion_timeout=42,
            client=_make_client(),
        )
        assert waits == [(10, 42)]
        assert report["ingestion"]["state"] == "complete"

    def test_a_failed_batch_is_not_waited_for(self, bulk, monkeypatch):
        bulk.fail_batches = {2}
        monkeypatch.setattr(docs_api, "countDocuments", _ScriptedCount([4]))
        waits = []
        monkeypatch.setattr(
            docs_api,
            "waitForDocumentCount",
            lambda d, expected, **k: waits.append(expected) or {"state": "complete"},
        )
        upload.uploadDocumentCollection(
            CLOUD_ID, _docs("a", "b"), only_missing=False, max_chunk=1, client=_make_client()
        )
        assert waits == [5]

    def test_an_ingestion_timeout_warns_but_the_upload_stands(self, bulk, monkeypatch, caplog):
        monkeypatch.setattr(docs_api, "countDocuments", _ScriptedCount([0]))
        monkeypatch.setattr(
            docs_api,
            "waitForDocumentCount",
            lambda d, expected, **k: {"state": "timeout", "count": 1, "expectedCount": expected},
        )
        with caplog.at_level("WARNING", logger="ndi.cloud.upload"):
            report = upload.uploadDocumentCollection(
                CLOUD_ID, _docs("a", "b"), only_missing=False, client=_make_client()
            )
        assert report["status"] == "ok"
        assert report["ingestion"]["state"] == "timeout"
        assert "lists 1 of the 2 documents" in caplog.text

    def test_no_count_means_no_wait(self, bulk, monkeypatch, caplog):
        monkeypatch.setattr(docs_api, "countDocuments", _ScriptedCount([RuntimeError("503")]))
        monkeypatch.setattr(
            docs_api,
            "waitForDocumentCount",
            lambda *a, **k: pytest.fail("must not wait without a starting count"),
        )
        with caplog.at_level("WARNING", logger="ndi.cloud.upload"):
            report = upload.uploadDocumentCollection(
                CLOUD_ID, _docs("a"), only_missing=False, client=_make_client()
            )
        assert report["uploaded"] == 1
        assert "ingestion" not in report
        assert "503" in caplog.text

    def test_wait_for_ingestion_false_reads_no_count(self, bulk, monkeypatch):
        counts = _ScriptedCount([0])
        monkeypatch.setattr(docs_api, "countDocuments", counts)
        report = upload.uploadDocumentCollection(
            CLOUD_ID,
            _docs("a"),
            only_missing=False,
            wait_for_ingestion=False,
            client=_make_client(),
        )
        assert counts.calls == 0
        assert report["uploaded"] == 1 and "ingestion" not in report


class TestSerialSwitch:
    def test_no_zip_sends_documents_one_at_a_time(self, monkeypatch):
        monkeypatch.setenv("NDI_CLOUD_UPLOAD_NO_ZIP", "true")
        sent = []
        monkeypatch.setattr(
            docs_api, "addDocument", lambda d, doc, **k: sent.append(doc) or {"ok": True}
        )
        monkeypatch.setattr(
            docs_api,
            "getBulkUploadURL",
            lambda *a, **k: pytest.fail("a serial upload must not ask for a bulk URL"),
        )
        docs = _docs("a", "b")
        report = upload.uploadDocumentCollection(
            CLOUD_ID, docs, only_missing=False, client=_make_client()
        )
        assert sent == docs
        assert report["upload_type"] == "serial"
        assert report["uploaded"] == 2


# ---------------------------------------------------------------------------
# waitForDocumentCount -- poll logic (WaitForDocumentCountMockTest.m)
# ---------------------------------------------------------------------------


def _wait(monkeypatch, script, expected, timeout=5.0):
    counts = _ScriptedCount(script)
    monkeypatch.setattr(docs_api, "countDocuments", counts)
    answer = docs_api.waitForDocumentCount(
        CLOUD_ID,
        expected,
        timeout=timeout,
        initial_interval=0.01,
        max_interval=0.01,
        client=_make_client(),
    )
    return answer, counts


class TestWaitForDocumentCount:
    def test_count_already_reached_returns_at_once(self, monkeypatch):
        answer, counts = _wait(monkeypatch, [5], 5)
        assert answer["state"] == "complete"
        assert answer["count"] == 5 and answer["expectedCount"] == 5
        assert counts.calls == 1

    def test_count_above_target_is_success(self, monkeypatch):
        answer, _ = _wait(monkeypatch, [7], 5)
        assert answer["state"] == "complete" and answer["count"] == 7

    def test_lagging_count_is_polled_until_it_arrives(self, monkeypatch):
        answer, counts = _wait(monkeypatch, [0, 3, 5], 5)
        assert answer["state"] == "complete"
        assert counts.calls == 3

    def test_count_that_never_arrives_times_out(self, monkeypatch):
        answer, _ = _wait(monkeypatch, [4], 5, timeout=0.05)
        assert answer["state"] == "timeout"
        assert answer["count"] == 4, "the timeout should report the last count seen"
        assert answer["elapsed"] >= 0.05

    def test_an_api_error_is_retried_not_fatal(self, monkeypatch):
        answer, counts = _wait(monkeypatch, [RuntimeError("gateway"), 5], 5)
        assert answer["state"] == "complete"
        assert counts.calls == 2

    def test_only_api_errors_time_out_with_no_count(self, monkeypatch):
        answer, counts = _wait(monkeypatch, [RuntimeError("gateway")], 5, timeout=0.05)
        assert answer["state"] == "timeout"
        assert math.isnan(answer["count"])
        assert counts.calls > 1

    def test_zero_expected_is_immediately_met(self, monkeypatch):
        answer, counts = _wait(monkeypatch, [0], 0)
        assert answer["state"] == "complete"
        assert counts.calls == 1

    def test_a_negative_target_is_rejected(self, monkeypatch):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            docs_api.waitForDocumentCount(CLOUD_ID, -1, client=_make_client())
