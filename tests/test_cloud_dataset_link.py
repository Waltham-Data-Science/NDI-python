"""The two local lookups that link a dataset to its cloud counterpart.

Both functions in this file answer a question about a dataset by searching
its own database, and both were broken on main in the same way: they reached
for an attribute ``ndi_dataset`` does not have, inside a bare
``except Exception``, so the resulting AttributeError was reported as a
perfectly ordinary answer.

    getCloudDatasetIdForLocalDataset   reached for  dataset.database
    listLocalDocuments                 reached for  dataset.session

The failures were silent and wrong in the worst direction:

    getCloudDatasetIdForLocalDataset returned ("", None) -- "never uploaded"
    -- for every dataset that HAD been uploaded. Callers respond to "" by
    creating a new remote dataset, so the auto-detect path in
    ndi.cloud.orchestration would duplicate a dataset in the cloud rather
    than update it.

    listLocalDocuments returned no documents for every dataset, so
    validateSync and documentDifference reported every local document as
    missing and every remote document as remote-only.

Neither was caught because every existing test mocked these functions out.
So the tests here use a REAL ndi_dataset on a real path. That is the whole
point: a mock reproduces the bug's absence, not its presence.

MATLAB reference: +ndi/+cloud/+internal/getCloudDatasetIdForLocalDataset.m
and +ndi/+cloud/+sync/+internal/listLocalDocuments.m -- both search through
``ndiDataset.database_search``, which is what these now do.
"""

from __future__ import annotations

import socket

import pytest

from ndi.cloud import internal
from ndi.cloud.exceptions import CloudSyncError
from ndi.dataset import ndi_dataset_dir
from ndi.document import ndi_document
from ndi.query import ndi_query


def _remote_doc(cloud_id: str):
    doc = ndi_document("dataset_remote")
    doc._set_nested_property("dataset_remote.dataset_id", cloud_id)
    return doc


@pytest.fixture
def unlinked(tmp_path):
    """A real dataset that has never been uploaded."""
    return ndi_dataset_dir("myds", str(tmp_path))


@pytest.fixture
def linked(tmp_path):
    """A real dataset carrying the dataset_remote document an upload writes."""
    ds = ndi_dataset_dir("myds", str(tmp_path))
    ds.database_add(_remote_doc("CLOUD-ABC-123"))
    return ds


class TestGetCloudDatasetIdForLocalDataset:
    def test_an_uploaded_dataset_reports_its_cloud_id(self, linked):
        """The regression. This returned ("", None) on main."""
        cloud_id, doc = internal.getCloudDatasetIdForLocalDataset(linked)
        assert cloud_id == "CLOUD-ABC-123"
        assert doc is not None

    def test_a_never_uploaded_dataset_reports_no_id(self, unlinked):
        assert internal.getCloudDatasetIdForLocalDataset(unlinked) == ("", None)

    def test_the_returned_document_is_the_dataset_remote_document(self, linked):
        _, doc = internal.getCloudDatasetIdForLocalDataset(linked)
        assert doc.document_properties["dataset_remote"]["dataset_id"] == "CLOUD-ABC-123"

    def test_two_remote_documents_raise_rather_than_picking_one(self, linked):
        """MATLAB raises NDICloud:Sync:MultipleCloudDatasetId here.

        The caller is about to choose which remote dataset to write to.
        Picking arbitrarily between two would send data to the wrong one.
        """
        linked.database_add(_remote_doc("CLOUD-SECOND"))
        with pytest.raises(CloudSyncError, match="more than one"):
            internal.getCloudDatasetIdForLocalDataset(linked)

    def test_an_unreadable_database_raises_instead_of_saying_not_uploaded(self):
        """The bug's exact shape, pinned so it cannot return.

        An object with no searchable database must NOT come back as ("",
        None). That answer means "this dataset has never been uploaded", and
        acting on it creates a duplicate remote dataset.
        """

        class NotADataset:
            pass

        with pytest.raises(AttributeError):
            internal.getCloudDatasetIdForLocalDataset(NotADataset())


class TestListLocalDocuments:
    def test_a_dataset_with_documents_lists_them(self, linked):
        """The regression. This returned ([], []) on main."""
        docs, ids = internal.listLocalDocuments(linked)
        assert docs, "a dataset holding documents listed none"
        assert len(ids) == len(docs)

    def test_the_ids_are_the_documents_own_ids(self, linked):
        docs, ids = internal.listLocalDocuments(linked)
        expected = [d.document_properties["base"]["id"] for d in docs]
        assert ids == expected

    def test_it_agrees_with_a_direct_database_search(self, linked):
        direct = linked.database_search(ndi_query("").isa("base"))
        docs, _ = internal.listLocalDocuments(linked)
        assert len(docs) == len(direct)

    def test_an_unreadable_database_raises_instead_of_reporting_empty(self):
        """An empty list must mean an empty dataset and nothing else.

        Reported as empty, validateSync and documentDifference conclude that
        every remote document is missing locally.
        """

        class NotADataset:
            pass

        with pytest.raises(AttributeError):
            internal.listLocalDocuments(NotADataset())


class TestTheTwoLookupsAgree:
    """is_in_cloud and getCloudDatasetIdForLocalDataset answer the same
    question by different routes, so a disagreement means one is broken.

    On main they disagreed on every real dataset: (True, 'CLOUD-ABC-123')
    against ('', None).
    """

    def test_both_find_the_link_on_an_uploaded_dataset(self, linked):
        in_cloud, status_id = linked.is_in_cloud()
        resolved_id, _ = internal.getCloudDatasetIdForLocalDataset(linked)
        assert in_cloud is True
        assert status_id == resolved_id == "CLOUD-ABC-123"

    def test_both_report_absence_on_a_never_uploaded_dataset(self, unlinked):
        assert unlinked.is_in_cloud() == (False, "")
        assert internal.getCloudDatasetIdForLocalDataset(unlinked) == ("", None)

    def test_they_diverge_only_where_matlab_does(self, linked):
        """Two remote documents: the status check picks, the resolver raises.

        MATLAB draws the line in exactly this place -- isInCloud documents
        that it "never throws" so it stays cheap to call while listing a
        tree, while getCloudDatasetIdForLocalDataset errors. Asserted here so
        the asymmetry reads as intended rather than as an inconsistency.
        """
        linked.database_add(_remote_doc("CLOUD-SECOND"))
        in_cloud, cloud_id = linked.is_in_cloud()
        assert in_cloud is True
        assert cloud_id in {"CLOUD-ABC-123", "CLOUD-SECOND"}
        with pytest.raises(CloudSyncError):
            internal.getCloudDatasetIdForLocalDataset(linked)


class TestNeitherLookupTouchesTheNetwork:
    """Both are local checks. Measured, not asserted in prose.

    PR #61 commit 0e1738b exists solely because the first version of this
    claim was written as a comment and never checked.
    """

    @pytest.fixture
    def no_network(self, monkeypatch):
        def forbidden(*args, **kwargs):
            raise AssertionError("a local check opened a network connection")

        monkeypatch.setattr(socket, "socket", forbidden)
        monkeypatch.setattr(socket, "create_connection", forbidden)

    def test_is_in_cloud_makes_no_connection(self, linked, no_network):
        assert linked.is_in_cloud() == (True, "CLOUD-ABC-123")

    def test_the_id_lookup_makes_no_connection(self, linked, no_network):
        cloud_id, _ = internal.getCloudDatasetIdForLocalDataset(linked)
        assert cloud_id == "CLOUD-ABC-123"

    def test_listing_local_documents_makes_no_connection(self, linked, no_network):
        docs, _ = internal.listLocalDocuments(linked)
        assert docs

    def test_the_guard_itself_works(self, no_network):
        """Without this, all three tests above would pass if the guard were
        silently ineffective."""
        with pytest.raises(AssertionError, match="network connection"):
            socket.socket()


class TestDownstreamReportsAreCorrectNow:
    """validateSync consumes listLocalDocuments, so it inherited the bug:
    every local document was reported missing from the local side."""

    def test_a_document_present_both_sides_is_common_not_remote_only(self, linked, monkeypatch):
        docs, ids = internal.listLocalDocuments(linked)
        # Without this the test passes vacuously on the broken version: an
        # empty local list makes every assertion below trivially true.
        assert ids, "no local documents to compare; the test proves nothing"
        monkeypatch.setattr(
            internal, "listRemoteDocumentIds", lambda cid, client=None: dict.fromkeys(ids, "api")
        )
        report = internal.validateSync(linked, "CLOUD-ABC-123")
        assert report["local_count"] == len(ids)
        assert sorted(report["common_ids"]) == sorted(ids)
        assert report["remote_only_ids"] == []

    def test_a_remote_only_document_is_still_reported(self, linked, monkeypatch):
        _, ids = internal.listLocalDocuments(linked)
        assert ids, "no local documents to compare; the test proves nothing"
        monkeypatch.setattr(
            internal,
            "listRemoteDocumentIds",
            lambda cid, client=None: {**dict.fromkeys(ids, "api"), "only-remote": "api"},
        )
        report = internal.validateSync(linked, "CLOUD-ABC-123")
        assert report["remote_only_ids"] == ["only-remote"]


if __name__ == "__main__":
    pytest.main([__file__])
