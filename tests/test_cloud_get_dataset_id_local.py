"""``getCloudDatasetIdForLocalDataset`` must work on a real local dataset.

The function reached for ``dataset.database``, which ``ndi_dataset`` does not
define (the database hangs off ``dataset._session``). The resulting
``AttributeError`` was swallowed by a bare ``except Exception: pass``, so for
every real ``ndi_dataset_dir`` the function returned ``("", None)`` --
"this dataset has never been uploaded" -- no matter what its database said.

Three cloud call sites auto-detect the cloud dataset id through it:
``ndi.cloud.download`` (:503) and ``ndi.cloud.orchestration`` (:309, :408).
Every existing test of those paths monkeypatches this function, so the suite
stayed green while the live path returned nothing.

Discovered while porting ``ndi.dataset.isInCloud`` (NDI-matlab ``41ef50f54``),
whose MATLAB docstring names this function as its sibling.
"""

from __future__ import annotations

from ndi.cloud.internal import getCloudDatasetIdForLocalDataset
from ndi.dataset._dataset import ndi_dataset_dir
from ndi.document import ndi_document


def _remote_doc(cloud_dataset_id: str) -> ndi_document:
    doc = ndi_document("dataset_remote")
    doc._set_nested_property("dataset_remote.dataset_id", cloud_dataset_id)
    return doc


class TestGetCloudDatasetIdForLocalDataset:
    def test_finds_the_id_on_a_real_dataset_dir(self, tmp_path):
        dataset = ndi_dataset_dir("cloud_ref", tmp_path / "ds")
        dataset.database_add(_remote_doc("67f723d574f5f79c6062389d"))

        cloud_id, doc = getCloudDatasetIdForLocalDataset(dataset)

        assert cloud_id == "67f723d574f5f79c6062389d"
        assert doc is not None

    def test_returns_empty_for_a_dataset_that_was_never_uploaded(self, tmp_path):
        dataset = ndi_dataset_dir("cloud_ref", tmp_path / "ds")

        assert getCloudDatasetIdForLocalDataset(dataset) == ("", None)

    def test_agrees_with_is_in_cloud(self, tmp_path):
        """The two sibling status checks must not disagree."""
        linked = ndi_dataset_dir("cloud_ref", tmp_path / "linked")
        linked.database_add(_remote_doc("cloud-abc"))
        unlinked = ndi_dataset_dir("cloud_ref", tmp_path / "unlinked")

        for dataset in (linked, unlinked):
            in_cloud, id_from_dataset = dataset.isInCloud()
            id_from_helper, doc = getCloudDatasetIdForLocalDataset(dataset)
            assert id_from_helper == id_from_dataset
            assert (doc is not None) is in_cloud

    def test_accepts_an_object_exposing_database_directly(self, tmp_path):
        """A session-like object with a .database property still works."""
        dataset = ndi_dataset_dir("cloud_ref", tmp_path / "ds")
        dataset.database_add(_remote_doc("cloud-abc"))

        cloud_id, _doc = getCloudDatasetIdForLocalDataset(dataset._session)

        assert cloud_id == "cloud-abc"

    def test_a_dataset_without_a_database_returns_empty(self, tmp_path):
        dataset = ndi_dataset_dir("cloud_ref", tmp_path / "ds")
        dataset._session._database = None

        assert getCloudDatasetIdForLocalDataset(dataset) == ("", None)
