"""Three loose ends from the ``+ndi/+cloud/`` body-drift cluster.

Each of these is a MATLAB commit whose substance had no counterpart here.
They share a shape: nothing raises, nothing is reported, and the user is
left with a result that looks complete and is not.
"""

from __future__ import annotations


class _Doc:
    def __init__(self, props):
        self.document_properties = props


def _generic_file_doc(doc_id, filename, location, uid="uid-1"):
    return _Doc(
        {
            "base": {"id": doc_id},
            "generic_file": {"filename": filename},
            "files": {
                "file_info": [
                    {
                        "name": filename,
                        "locations": [{"location": location, "uid": uid}],
                    }
                ]
            },
        }
    )


class _Dataset:
    def __init__(self, docs):
        self._docs = docs

    def database_search(self, query):
        return list(self._docs)


class TestAZippedFolderKeepsItsZipExtension:
    """MATLAB counterpart: ``downloadGenericFiles.m``, NDI-matlab ``0d32073fc``.

    A ``generic_file`` that was a directory is stored zipped, and a
    directory name has no extension -- so the download named the result
    after the folder with nothing to say it is an archive. Double-clicking
    it does nothing; ``file`` on it says Zip archive. The stored location
    is what knows, and it was not consulted.
    """

    @staticmethod
    def _download(monkeypatch, tmp_path, doc, naming_strategy="original"):
        """Run downloadGenericFiles far enough to see the chosen filename.

        The transfer itself is stubbed: the name is decided before any
        request is made, so a real fetch would only add a network to mock.
        """
        import requests

        import ndi.cloud.download as download
        import ndi.cloud.internal as internal
        from ndi.cloud.api import files as files_api

        monkeypatch.setattr(
            internal,
            "getCloudDatasetIdForLocalDataset",
            lambda ds, client=None: ("65a1b2c3d4e5f60718293a4b", ""),
        )
        monkeypatch.setattr(
            files_api,
            "getFileDetails",
            lambda *a, **k: {"downloadUrl": "https://host/x?sig=1"},
        )

        class _Resp:
            status_code = 200

            @staticmethod
            def iter_content(chunk_size=0):
                return [b"PK\x03\x04"]

        monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp())

        ok, err, report = download.downloadGenericFiles(
            _Dataset([doc]),
            ["doc-1"],
            tmp_path,
            verbose=False,
            naming_strategy=naming_strategy,
        )
        assert ok, err
        return report["downloaded_filenames"]

    def test_an_extensionless_name_stored_as_a_zip_gets_zip_back(self, monkeypatch, tmp_path):
        doc = _generic_file_doc("doc-1", "my_recording_folder", "/store/abc.zip")
        assert self._download(monkeypatch, tmp_path, doc) == ["my_recording_folder.zip"]

    def test_a_real_extension_is_left_alone(self, monkeypatch, tmp_path):
        """The location is a zip because the transfer is zipped; the file
        itself is a .tif, and renaming it would be the worse bug."""
        doc = _generic_file_doc("doc-1", "scan.tif", "/store/abc.zip")
        assert self._download(monkeypatch, tmp_path, doc) == ["scan.tif"]

    def test_a_plain_location_adds_nothing(self, monkeypatch, tmp_path):
        doc = _generic_file_doc("doc-1", "notes", "/store/abc.bin")
        assert self._download(monkeypatch, tmp_path, doc) == ["notes"]

    def test_it_applies_under_the_id_naming_strategies_too(self, monkeypatch, tmp_path):
        """The extension is computed once, before the strategy picks a stem,
        so every strategy has to carry it."""
        doc = _generic_file_doc("doc-1", "folder", "/store/abc.zip")
        assert self._download(monkeypatch, tmp_path, doc, "id") == ["doc-1.zip"]
        assert self._download(monkeypatch, tmp_path, doc, "id_original") == ["doc-1_folder.zip"]


class TestAShortDownloadIsAnnounced:
    """MATLAB counterpart: ``downloadNdiDocuments.m``, NDI-matlab ``7efa0a8a0``.

    Ask the cloud for 50 documents and get 47. Nothing raises -- the call
    succeeded, the list is simply shorter. This side already keeps the
    missing IDs out of the sync index so they are requested again
    (``test_cloud_sync_index_advancement.py``), which is the half that
    matters. What was missing is anybody ever being told: a user watching a
    download saw it finish and had no reason to look at ``report['failed']``.
    """

    @staticmethod
    def _run(monkeypatch, requested, returned):
        import ndi.cloud.download as download_module
        import ndi.cloud.sync.operations as ops

        monkeypatch.setattr(
            download_module,
            "downloadDocumentCollection",
            lambda cloud_id, doc_ids=None, client=None: [{"_id": i} for i in returned],
        )
        return ops.downloadNdiDocuments(
            "65a1b2c3d4e5f60718293a4b",
            {i: i for i in requested},
            set(requested),
        )

    def test_the_missing_ids_are_logged(self, monkeypatch, caplog):
        with caplog.at_level("WARNING", logger="ndi.cloud.sync.operations"):
            docs, failed = self._run(monkeypatch, ["a", "b", "c"], ["a", "c"])
        assert failed == ["b"]
        assert "Requested 3" in caplog.text
        assert "received 2" in caplog.text
        assert "b" in caplog.text

    def test_a_complete_download_says_nothing(self, monkeypatch, caplog):
        with caplog.at_level("WARNING", logger="ndi.cloud.sync.operations"):
            docs, failed = self._run(monkeypatch, ["a", "b"], ["a", "b"])
        assert failed == []
        assert caplog.text == ""

    def test_a_very_short_answer_does_not_dump_every_id(self, monkeypatch, caplog):
        """A dataset-sized failure must stay one readable line."""
        requested = [f"id{i:03d}" for i in range(200)]
        with caplog.at_level("WARNING", logger="ndi.cloud.sync.operations"):
            docs, failed = self._run(monkeypatch, requested, [])
        assert len(failed) == 200
        assert "..." in caplog.text
        assert len(caplog.text.splitlines()) == 1


class TestAFailedRemoteListingExplainsItself:
    """MATLAB counterpart: ``uploadDocumentCollection.m``, NDI-matlab ``e96801dee``.

    That commit's own bug does not port -- MATLAB called ``jsonencodenan``
    unqualified, which is a package-resolution mistake Python cannot make.
    What ports is what the commit message identifies as the reason the bug
    survived: a ``catch`` that recorded a failure and discarded the
    exception.

    The same shape was here. ``only_missing`` lists the remote documents to
    skip the ones already uploaded, inside ``except Exception: pass``. A
    listing call that has stopped working is then indistinguishable from an
    empty remote: every run re-uploads the whole dataset, and no log line
    anywhere says the filter did not run.
    """

    @staticmethod
    def _upload(monkeypatch, listing):
        import ndi.cloud.upload as upload
        from ndi.cloud.api import documents as docs_api

        monkeypatch.setattr(docs_api, "listDatasetDocumentsAll", listing)
        monkeypatch.setattr(docs_api, "addDocument", lambda *a, **k: {"ok": True})
        return upload.uploadDocumentCollection(
            "65a1b2c3d4e5f60718293a4b",
            [{"ndiId": "a"}, {"ndiId": "b"}],
            only_missing=True,
            client=object(),
        )

    def test_the_reason_reaches_the_log(self, monkeypatch, caplog):
        def _boom(*a, **k):
            raise RuntimeError("403 from /documents")

        with caplog.at_level("WARNING", logger="ndi.cloud.upload"):
            self._upload(monkeypatch, _boom)
        assert "403 from /documents" in caplog.text
        assert "only_missing" in caplog.text

    def test_and_the_upload_still_proceeds(self, monkeypatch):
        """Uploading everything is the right fallback -- a duplicate is
        rejected by the remote, a skipped document is lost."""

        def _boom(*a, **k):
            raise RuntimeError("nope")

        report = self._upload(monkeypatch, _boom)
        assert report["uploaded"] == 2
        assert report["skipped"] == 0

    def test_a_working_listing_logs_nothing(self, monkeypatch, caplog):
        class _Listing:
            data = [{"ndiId": "a"}]

        with caplog.at_level("WARNING", logger="ndi.cloud.upload"):
            report = self._upload(monkeypatch, lambda *a, **k: _Listing())
        assert report["skipped"] == 1
        assert report["uploaded"] == 1
        assert caplog.text == ""
