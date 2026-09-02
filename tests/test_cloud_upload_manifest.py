"""scanForUpload and uploadToNDICloud see the dataset's documents.

Both searched with a bare ``ndi_query("")``. That query matches NO
documents -- it is not "match everything" -- so the upload manifest was
empty for every dataset, and scanForUpload additionally swallowed any real
failure into the same empty list.

Measured on main before the fix, on a dataset holding four documents:

    documents in the dataset          : 4
    scanForUpload doc_structs         : 0
    scanForUpload total_size_kb       : 0.0

This is the same defect fixed in ndi.cloud.orchestration, in a second file.
MATLAB's caller searches with ``ndi.query('','isa','base')`` and hands the
documents to scanForUpload (uploadToNDICloud.m:20).
"""

from __future__ import annotations

import pytest

from ndi.cloud.upload import scanForUpload
from ndi.dataset import ndi_dataset_dir
from ndi.document import ndi_document
from ndi.query import ndi_query


@pytest.fixture
def dataset(tmp_path):
    ds = ndi_dataset_dir("myds", str(tmp_path))
    for _ in range(3):
        ds.database_add(ndi_document("base"))
    return ds


def _doc_count(ds) -> int:
    return len(ds.database_search(ndi_query("").isa("base")))


class TestScanForUpload:
    def test_the_manifest_lists_every_document(self, dataset):
        """The regression. This produced an empty manifest on main."""
        expected = _doc_count(dataset)
        assert expected > 0, "fixture built no documents; the test proves nothing"

        # "" for the dataset id is MATLAB's "this is a new dataset", and keeps
        # the call off the network -- no remote id list is fetched.
        doc_structs, _file_structs, _kb = scanForUpload(dataset, "")
        assert len(doc_structs) == expected

    def test_every_document_starts_marked_not_uploaded(self, dataset):
        doc_structs, _, _ = scanForUpload(dataset, "")
        assert doc_structs
        assert all(d["is_uploaded"] is False for d in doc_structs)

    def test_the_manifest_carries_the_real_document_ids(self, dataset):
        expected = {
            d.document_properties["base"]["id"]
            for d in dataset.database_search(ndi_query("").isa("base"))
        }
        doc_structs, _, _ = scanForUpload(dataset, "")
        assert {d["docid"] for d in doc_structs} == expected

    def test_an_unreadable_database_raises_rather_than_scanning_nothing(self):
        """An empty manifest must mean an empty dataset and nothing else.

        Swallowed, the caller uploads no documents and is told the dataset
        held none.
        """

        class NotADataset:
            pass

        with pytest.raises(AttributeError):
            scanForUpload(NotADataset(), "")


class TestTheQueryIsTheReasonItWasEmpty:
    """Pinned separately from the manifest tests: a bare ndi_query("")
    matches nothing, and that fact is what made the manifest empty. If the
    query behaviour ever changes, this is where it should be noticed."""

    def test_a_bare_query_matches_no_documents(self, dataset):
        assert dataset.database_search(ndi_query("")) == []

    def test_the_isa_base_query_matches_them(self, dataset):
        assert len(dataset.database_search(ndi_query("").isa("base"))) == _doc_count(dataset)


if __name__ == "__main__":
    pytest.main([__file__])
