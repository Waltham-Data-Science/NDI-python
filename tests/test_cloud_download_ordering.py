"""Files are downloaded, and the documents rewritten, BEFORE the add.

MATLAB counterpart: ``+ndi/+cloud/+sync/+internal/downloadNdiDocuments.m``

MATLAB downloads the binaries into a staging folder
(``Constants.FileSyncLocation``), rewrites each document's file_info to name
the downloaded copies, and only then calls ``database_add`` -- so DID ingests
the files as part of adding the documents that refer to them.

``downloadDataset`` ran the other way round: add first, then download into
``target/.ndi/files``, which is DID's own FileDir. That skips ingestion
altogether. It LOOKS fine -- ``cached_path_for_uid`` finds bytes sitting in
FileDir under the right uid -- which is why it went unnoticed; what is
missing is the files-table row and the rewrite, so every document still
claims its files are on the cloud. ``updateFileInfoForLocalFiles``, whose
whole job is that rewrite, had no callers anywhere in the repository.

The order matters beyond tidiness. DID refuses a document whose file series
declares present members while recording no way to locate them, and the
record that answers it is rebuilt from the downloaded manifest -- which
cannot happen if the add has already gone through. See NDI-python#215.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ndi.cloud.internal import FILE_SYNC_LOCATION
from ndi.document import ndi_document

FILE_SLOT = "filename1.ext"
PAYLOAD = b"the bytes the cloud holds"
CLOUD_ID = "ds_cloud_1"


def _doc_json(tmp_path, number, uid):
    """A demoNDI document whose one file is recorded under ``uid``.

    Built through add_file and then rewritten to look like what comes back
    from the cloud: a location the local machine cannot read, which is the
    starting state the download path has to do something about.
    """
    placeholder = tmp_path / f"src_{number}.bin"
    placeholder.write_bytes(PAYLOAD)

    doc = ndi_document("demoNDI")
    props = doc.document_properties
    props["base"]["name"] = f"doc_{number}"
    props["demoNDI"]["value"] = number
    props = ndi_document(props).add_file(FILE_SLOT, str(placeholder)).document_properties

    location = props["files"]["file_info"][0]["locations"][0]
    location["uid"] = uid
    location["location"] = "https://cloud.invalid/not-reachable-from-here"
    location["location_type"] = "url"
    location["ingest"] = 0
    placeholder.unlink()
    return props


@pytest.fixture
def cloud(monkeypatch, tmp_path):
    """A cloud holding two one-file documents, and a record of what happened.

    ``events`` is the point of the fixture: it records file fetches and the
    moment documents are added, so a test can assert the ORDER rather than
    only the end state.
    """
    import requests

    import ndi.cloud.api
    from ndi.cloud.api import datasets as ds_api

    docs = [_doc_json(tmp_path, 1, "UID_ONE"), _doc_json(tmp_path, 2, "UID_TWO")]
    events: dict[str, list] = {"fetched": [], "added_when": [], "staged_into": []}
    unreachable: set[str] = set()

    class FakeFiles:
        @staticmethod
        def getFileDetails(dataset_id, uid, *, client=None):
            if uid in unreachable:
                raise RuntimeError("no such file")
            return {"downloadUrl": f"https://example.invalid/{uid}"}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def iter_content(chunk_size=8192):
            yield PAYLOAD

    def fake_get(url, **kwargs):
        events["fetched"].append(url.rsplit("/", 1)[-1])
        return FakeResponse()

    # Where the file pass was actually told to write. Asserted directly,
    # because a test that only checks "the folder I expected is gone
    # afterwards" passes just as happily when the code never used it.
    from ndi.cloud.download import downloadDatasetFiles as real_download_files

    def watched_download_files(dataset_id, documents, target_dir, **kwargs):
        events["staged_into"].append(Path(target_dir))
        return real_download_files(dataset_id, documents, target_dir, **kwargs)

    monkeypatch.setattr(
        "ndi.cloud.download.downloadDatasetFiles", watched_download_files, raising=False
    )

    monkeypatch.setattr(ndi.cloud.api, "files", FakeFiles, raising=False)
    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(ds_api, "getDataset", lambda *a, **k: {"name": "fake"}, raising=False)
    monkeypatch.setattr(
        "ndi.cloud.download.downloadDocumentCollection",
        lambda *a, **k: docs,
        raising=False,
    )

    # Mark the instant the documents reach the database, so "files first"
    # is asserted as an ordering rather than inferred from the end state.
    from ndi.dataset import ndi_dataset_dir as real_dir

    def watched_dir(*args, **kwargs):
        events["added_when"].append(len(events["fetched"]))
        return real_dir(*args, **kwargs)

    monkeypatch.setattr("ndi.dataset.ndi_dataset_dir", watched_dir, raising=False)

    return {"docs": docs, "events": events, "unreachable": unreachable}


def _download(tmp_path, sync_files=True):
    from ndi.cloud.orchestration import downloadDataset

    return downloadDataset(CLOUD_ID, str(tmp_path / "dl"), sync_files=sync_files, client=object())


class TestFilesArriveBeforeTheDocuments:
    def test_both_files_are_fetched_before_anything_is_added(self, tmp_path, cloud):
        _download(tmp_path)

        events = cloud["events"]
        assert events["fetched"] == ["UID_ONE", "UID_TWO"]
        assert events["added_when"], "the dataset was never built"
        assert events["added_when"][0] == 2, (
            "documents were added after "
            f'{events["added_when"][0]} of 2 files had been fetched; MATLAB '
            "downloads every file first so that the add can ingest them"
        )

    def test_the_files_are_ingested_not_merely_present(self, tmp_path, cloud):
        """The difference the ordering makes.

        Downloading into FileDir leaves bytes findable by uid but no ingest:
        the document still says its file is on the cloud. After the rewrite,
        the file_info names a location DID ingested from, and the bytes are
        DID's own copy.
        """
        dataset = _download(tmp_path)

        file_dir = Path(dataset._session._database.binary_path)
        assert (file_dir / "UID_ONE").read_bytes() == PAYLOAD
        assert (file_dir / "UID_TWO").read_bytes() == PAYLOAD

    def test_the_staging_folder_is_used_and_then_cleared(self, tmp_path, cloud):
        """Staged under Constants.FileSyncLocation, not into DID's store.

        Ingestion marks the staged copies delete_original, so the tree is
        empty afterwards and gets removed. If the staging folder WERE
        FileDir, this would delete the dataset's files.
        """
        dataset = _download(tmp_path)

        expected = Path(tmp_path / "dl" / CLOUD_ID) / FILE_SYNC_LOCATION
        file_dir = Path(dataset._session._database.binary_path)

        assert cloud["events"]["staged_into"] == [expected], (
            "the file pass did not write to Constants.FileSyncLocation; it "
            f'wrote to {cloud["events"]["staged_into"]}'
        )
        assert expected.resolve() != file_dir.resolve(), (
            "staging IS DID's file store: ingestion would then copy each "
            "file onto itself and delete the original"
        )
        assert not expected.exists(), "staging survived ingestion"
        assert file_dir.is_dir()

    def test_a_document_records_the_local_file_after_the_rewrite(self, tmp_path, cloud):
        """updateFileInfoForLocalFiles ran. Nothing called it before."""
        _download(tmp_path)

        locations = [
            loc
            for dj in cloud["docs"]
            for fi in [dj["files"]["file_info"]]
            for entry in (fi if isinstance(fi, list) else [fi])
            for loc in entry["locations"]
        ]
        assert any(
            loc["location_type"] == "file" and loc["ingest"] for loc in locations
        ), "no location was rewritten to a local ingestable path"
        assert not any(
            loc["location"].startswith("https://cloud.invalid") for loc in locations
        ), "a document still points at a location this machine cannot read"


class TestWithoutSyncFiles:
    def test_locations_become_ndic_references(self, tmp_path, cloud):
        _download(tmp_path, sync_files=False)

        assert cloud["events"]["fetched"] == [], "sync_files=False downloaded files"
        for dj in cloud["docs"]:
            for entry in dj["files"]["file_info"]:
                for loc in entry["locations"]:
                    assert loc["location"].startswith(f"ndic://{CLOUD_ID}/")


class TestAShortDownloadDegradesRatherThanLosing:
    def test_a_file_that_did_not_arrive_keeps_a_working_reference(self, tmp_path, cloud):
        """A DELIBERATE deviation from MATLAB, stated in orchestration.py.

        MATLAB does one rewrite or the other, and warns-and-drops a file that
        did not download -- the document loses it. Doing the remote rewrite
        first and letting the local one overwrite what actually arrived means
        a missing file keeps an ndic:// reference that still resolves on
        demand. A short download degrades to a slower read, not a lost file.
        """
        cloud["unreachable"].add("UID_TWO")

        _download(tmp_path)

        by_uid = {
            loc["uid"]: loc
            for dj in cloud["docs"]
            for entry in dj["files"]["file_info"]
            for loc in entry["locations"]
        }
        assert by_uid["UID_ONE"]["location_type"] == "file"
        assert by_uid["UID_TWO"]["location"] == f"ndic://{CLOUD_ID}/UID_TWO"
        assert by_uid["UID_TWO"]["location_type"] == "ndicloud"


class TestTheCloudDatasetIdReachesTheRewrite:
    """NDI-matlab cd3c11673 (#958) threaded cloudDatasetId into the rewrite.

    MATLAB does it inside downloadNdiDocuments, where the documentUpdateFcn
    is built; here the rewrite lives in orchestration.downloadDataset. Either
    way the id is what lets a downloaded series keep its manifest's ndic://
    reference and get its ingest_locations rebuilt -- without which DID
    refuses the document.

    updateFileInfoForLocalFiles takes cloud_dataset_id as an OPTIONAL third
    argument, and every existing test called it directly. So dropping the
    argument at the call site broke nothing any test could see, while a
    downloaded series lost the reference. This pins the call site.
    """

    def _spy(self, monkeypatch):
        seen = []
        from ndi.cloud import filehandler

        real = filehandler.updateFileInfoForLocalFiles

        def watched(props, directory, cloud_dataset_id=None, *args, **kwargs):
            seen.append(cloud_dataset_id)
            return real(props, directory, cloud_dataset_id, *args, **kwargs)

        monkeypatch.setattr(filehandler, "updateFileInfoForLocalFiles", watched)
        return seen

    def test_the_rewrite_is_given_the_cloud_dataset_id(self, tmp_path, cloud, monkeypatch):
        seen = self._spy(monkeypatch)
        _download(tmp_path)

        assert seen, "updateFileInfoForLocalFiles was never called"
        assert all(got == CLOUD_ID for got in seen), (
            f"the rewrite was called with {seen!r}; without the cloud dataset id "
            "a downloaded series cannot keep its manifest's ndic:// reference"
        )

    def test_it_is_not_called_at_all_without_sync_files(self, tmp_path, cloud, monkeypatch):
        """MATLAB picks one rewrite or the other on syncOptions.SyncFiles."""
        seen = self._spy(monkeypatch)
        _download(tmp_path, sync_files=False)
        assert seen == []
