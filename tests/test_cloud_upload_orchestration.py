"""uploadDataset and the sync helpers, against a real dataset.

These functions reached the local database through ``dataset.session``.
``ndi_dataset`` has no ``session`` attribute, so every one of those calls
raised AttributeError, and four of the five swallowed it into an empty list
or a no-op. A second, independent mistake sat on the same lines: the search
used a bare ``ndi_query("")``, which matches no documents at all.

Either mistake alone is enough to upload an empty dataset while reporting
success, which is why the tests here assert on COUNTS rather than on the
success flag. Measured on main before the fix, with a dataset holding four
documents:

    documents actually in the dataset : 4
    documents uploadDataset sent      : 0
    result                            : ok=True cloud_id='NEW-CLOUD-ID'
    dataset_remote link written back  : (False, '')

The missing link is the worst of the three. ``is_in_cloud()`` stays False, so
the NEXT upload does not find an existing remote dataset and creates a second
one -- the duplication #95 predicted, reached by a different route.

MATLAB reference: +ndi/+cloud/uploadDataset.m lines 91 and 96 --
``ndiDataset.database_add(remoteDatasetDoc)`` then
``ndiDataset.database_search(ndi.query('','isa','base'))``. Note the order:
the link document is written first and is therefore itself uploaded, so a
dataset holding N documents uploads N+1.

Only the HTTP layer is stubbed. The dataset is real, because mocking these
functions out is exactly what let three failures in one function ship.
"""

from __future__ import annotations

import types

import pytest

import ndi.cloud.api.datasets as ds_api
import ndi.cloud.internal as cloud_internal
import ndi.cloud.orchestration as orch
import ndi.cloud.upload as upload_mod
from ndi.dataset import ndi_dataset_dir
from ndi.document import ndi_document
from ndi.query import ndi_query


class FakeClient:
    config = types.SimpleNamespace(org_id="org")


@pytest.fixture
def dataset(tmp_path):
    """A real dataset holding a known number of documents."""
    ds = ndi_dataset_dir("myds", str(tmp_path))
    for _ in range(3):
        ds.database_add(ndi_document("base"))
    return ds


def _doc_count(ds) -> int:
    return len(ds.database_search(ndi_query("").isa("base")))


@pytest.fixture
def captured(monkeypatch):
    """Stub the cloud API and record what would have been sent."""
    box: dict = {"docs": None, "created": 0}

    def create_dataset(org, name, client=None):
        box["created"] += 1
        return {"id": f"CLOUD-{box['created']}"}

    def upload_docs(cloud_id, doc_jsons, client=None, **kw):
        box["docs"] = doc_jsons
        return {"uploaded": len(doc_jsons), "skipped": 0}

    monkeypatch.setattr(ds_api, "createDataset", create_dataset)
    # Patched on the DEFINING modules, not on ndi.cloud.orchestration: these
    # helpers are imported inside the function bodies, so a name bound on the
    # orchestration module is never consulted.
    monkeypatch.setattr(upload_mod, "uploadDocumentCollection", upload_docs)
    return box


class TestUploadDatasetSendsTheDocuments:
    def test_it_uploads_every_document_the_dataset_holds(self, dataset, captured):
        """The regression. This sent 0 documents on main."""
        expected = _doc_count(dataset)
        assert expected > 0, "fixture built no documents; the test proves nothing"

        orch.uploadDataset(dataset, sync_files=False, client=FakeClient())

        # +1: the dataset_remote link document is written before the search,
        # exactly as in uploadDataset.m, so it is uploaded too.
        assert len(captured["docs"]) == expected + 1

    def test_it_does_not_report_success_while_sending_nothing(self, dataset, captured):
        """Success with an empty payload is the shape of the original bug."""
        ok, _cloud_id, _msg = orch.uploadDataset(dataset, sync_files=False, client=FakeClient())
        assert ok is True
        assert captured["docs"], "reported success having uploaded no documents"

    def test_an_empty_dataset_still_uploads_its_link_document(self, tmp_path, captured):
        """Guards the test above: a count of zero must mean an empty dataset."""
        empty = ndi_dataset_dir("empty", str(tmp_path))
        before = _doc_count(empty)
        orch.uploadDataset(empty, sync_files=False, client=FakeClient())
        assert len(captured["docs"]) == before + 1


class TestUploadDatasetWritesTheCloudLink:
    def test_the_dataset_knows_it_is_in_the_cloud_afterwards(self, dataset, captured):
        assert dataset.is_in_cloud() == (False, "")
        _ok, cloud_id, _msg = orch.uploadDataset(dataset, sync_files=False, client=FakeClient())
        assert dataset.is_in_cloud() == (True, cloud_id)

    def test_a_second_upload_reuses_the_remote_rather_than_creating_another(
        self, dataset, captured
    ):
        """The duplication this bug caused, pinned directly.

        With the link unwritten, the second call cannot find the existing
        remote dataset and creates a new one.
        """
        _, first_id, _ = orch.uploadDataset(dataset, sync_files=False, client=FakeClient())
        _, second_id, _ = orch.uploadDataset(dataset, sync_files=False, client=FakeClient())
        assert second_id == first_id
        assert captured["created"] == 1, "a second remote dataset was created"

    def test_a_failed_link_write_is_reported_not_swallowed(self, dataset, captured, monkeypatch):
        """If the link cannot be written the caller must be told.

        Silence here means the caller believes the dataset is uploaded and
        linked when it is uploaded and orphaned.
        """

        def boom(_doc):
            raise RuntimeError("disk full")

        monkeypatch.setattr(dataset, "database_add", boom)
        ok, cloud_id, msg = orch.uploadDataset(dataset, sync_files=False, client=FakeClient())
        assert ok is False
        assert cloud_id
        assert "second remote dataset" in msg


class TestTheQueryMatchesDocuments:
    """A bare ndi_query("") matches nothing, which uploads an empty dataset
    just as effectively as the wrong attribute did. Pinned separately so a
    future edit cannot reintroduce one while fixing the other."""

    def test_a_bare_query_finds_nothing(self, dataset):
        assert dataset.database_search(ndi_query("")) == []

    def test_the_isa_base_query_finds_the_documents(self, dataset):
        assert len(dataset.database_search(ndi_query("").isa("base"))) > 0


class TestSyncHelpersSeeTheLocalSide:
    """_sync_upload_new and _sync_download_new read local ids the same way.
    Reported empty, every remote document looked new and every local one
    looked missing."""

    def test_upload_new_uploads_only_what_the_remote_lacks(self, dataset, monkeypatch):
        """Remote already has all but one document; exactly one should upload.

        Asserting a count of zero here would pass on the broken version too --
        an invisible local side also uploads nothing. Leaving one document out
        is what makes the assertion discriminate.
        """
        local_ids = [
            d.document_properties["base"]["id"]
            for d in dataset.database_search(ndi_query("").isa("base"))
        ]
        assert len(local_ids) > 1, "need at least two documents to hold one back"
        already_remote = dict.fromkeys(local_ids[:-1], "api")
        monkeypatch.setattr(
            cloud_internal, "listRemoteDocumentIds", lambda cid, client=None: already_remote
        )
        report = orch._sync_upload_new(dataset, "CLOUD-1", False, False, True, client=FakeClient())
        assert report["uploaded"] == 1

    def test_upload_new_uploads_a_document_the_remote_lacks(self, dataset, monkeypatch):
        monkeypatch.setattr(cloud_internal, "listRemoteDocumentIds", lambda cid, client=None: {})
        expected = _doc_count(dataset)
        report = orch._sync_upload_new(dataset, "CLOUD-1", False, False, True, client=FakeClient())
        assert report["uploaded"] == expected

    def test_download_new_does_not_redownload_what_is_already_local(self, dataset, monkeypatch):
        """The local side must be visible, or every remote doc looks new."""
        local = dataset.database_search(ndi_query("").isa("base"))
        # The remote API returns documents keyed by a TOP-LEVEL ndiId; the
        # local side reads base.id. _sync_download_new compares the two, so
        # the fixture has to use the real remote shape or the comparison is
        # meaningless.
        remote_payload = [
            {"ndiId": d.document_properties["base"]["id"], "base": d.document_properties["base"]}
            for d in local
        ]

        import ndi.cloud.api.documents as docs_api

        monkeypatch.setattr(
            docs_api,
            "listDatasetDocumentsAll",
            lambda cid, client=None: types.SimpleNamespace(data=remote_payload),
        )
        report = orch._sync_download_new(
            dataset, "CLOUD-1", False, False, True, client=FakeClient()
        )
        assert report["downloaded"] == 0


if __name__ == "__main__":
    pytest.main([__file__])
