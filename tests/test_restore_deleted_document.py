"""A document deleted locally can be restored, for the cloud sync (NDI-matlab#1238).

DID retires the id of a document removed from every branch and refuses it
ever after. A cloud mirror that re-downloads a document deleted locally is
bringing back the SAME document, so the download path passes
``restore_deleted_id=True`` -- MATLAB's ``'RestoreDeletedId'`` -- which maps to
DID's ``OnDeletedId="restore"``.

MATLAB counterparts: ``tests/+ndi/+unittest/+database/TestRestoreDeletedDocument.m``
and ``MirrorFromRemoteTest/testMirrorRestoresLocallyDeletedDocument``.
"""

from __future__ import annotations

import pytest

from ndi.cloud.sync.operations import _ingest_downloaded_docs
from ndi.dataset import ndi_dataset_dir
from ndi.document import ndi_document
from ndi.query import ndi_query
from ndi.session.dir import ndi_session_dir


@pytest.fixture
def session(tmp_path):
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    return ndi_session_dir("restoreTest", session_dir)


def _found(container, doc_id):
    return container.database_search(ndi_query("base.id") == doc_id)


class TestSessionDatabaseAdd:
    def test_a_deleted_id_is_refused_by_default(self, session):
        doc = session.newdocument("base", **{"base.name": "restoreMe"})
        session.database_add(doc)
        session.database_rm(doc.id)

        with pytest.raises(ValueError, match="previously removed"):
            session.database_add(doc)

    def test_a_deleted_document_can_be_restored(self, session):
        doc = session.newdocument("base", **{"base.name": "restoreMe"})
        session.database_add(doc)
        session.database_rm(doc.id)

        session.database_add(doc, restore_deleted_id=True)

        found = _found(session, doc.id)
        assert len(found) == 1
        assert found[0].document_properties["base"]["name"] == "restoreMe"


class TestCloudDownloadRestores:
    def test_ingesting_a_download_restores_a_locally_deleted_document(self, tmp_path):
        """The ingestion step every cloud sync mode uses brings it back."""
        dataset_dir = tmp_path / "ds"
        dataset_dir.mkdir()
        dataset = ndi_dataset_dir("restoreDs", str(dataset_dir))
        doc = ndi_document("base", **{"base.name": "restoreMe"}).set_session_id(dataset.id())
        dataset.database_add(doc)
        dataset.database_rm(doc.id)
        assert _found(dataset, doc.id) == []

        _ingest_downloaded_docs(dataset, [doc.document_properties])

        assert len(_found(dataset, doc.id)) == 1
