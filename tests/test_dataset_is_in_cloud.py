"""Tests for ``ndi.dataset.isInCloud``.

Port of MATLAB ``ndi.dataset/isInCloud`` (NDI-matlab ``41ef50f54``, PR #859,
``src/ndi/+ndi/dataset.m:260-296``).

Contract, per the MATLAB docstring:

- purely local -- inspects only the dataset's OWN database, no network;
- does not open the dataset's linked sessions, so it is cheap enough to call
  while listing datasets;
- returns ``(b, cloud_dataset_id)``: the id when ``b`` is true, ``""`` when
  false;
- with more than one ``dataset_remote`` document (a misconfiguration) it
  returns the first rather than raising -- this status check never throws.
"""

from __future__ import annotations

import pytest

from ndi.dataset._dataset import ndi_dataset_dir
from ndi.document import ndi_document


def _dataset(tmp_path, name="ds"):
    return ndi_dataset_dir("cloud_ref", tmp_path / name)


def _remote_doc(cloud_dataset_id):
    doc = ndi_document("dataset_remote")
    doc._set_nested_property("dataset_remote.dataset_id", cloud_dataset_id)
    return doc


class TestIsInCloud:
    def test_fresh_dataset_is_not_in_cloud(self, tmp_path):
        dataset = _dataset(tmp_path)

        assert dataset.isInCloud() == (False, "")

    def test_dataset_with_a_remote_document_is_in_cloud(self, tmp_path):
        dataset = _dataset(tmp_path)
        dataset.database_add(_remote_doc("67f723d574f5f79c6062389d"))

        in_cloud, cloud_id = dataset.isInCloud()

        assert in_cloud is True
        assert cloud_id == "67f723d574f5f79c6062389d"

    def test_returns_a_bool_and_a_str(self, tmp_path):
        """MATLAB promises a logical scalar and a char array."""
        dataset = _dataset(tmp_path)
        dataset.database_add(_remote_doc("abc"))

        in_cloud, cloud_id = dataset.isInCloud()

        assert isinstance(in_cloud, bool)
        assert isinstance(cloud_id, str)

    def test_multiple_remote_documents_return_the_first_without_raising(self, tmp_path):
        """A misconfiguration must degrade, not throw."""
        dataset = _dataset(tmp_path)
        first = _remote_doc("cloud-first")
        dataset.database_add(first)
        dataset.database_add(_remote_doc("cloud-second"))

        in_cloud, cloud_id = dataset.isInCloud()

        assert in_cloud is True
        assert cloud_id in {"cloud-first", "cloud-second"}

    def test_missing_dataset_id_yields_an_empty_id(self, tmp_path):
        """Present-but-blank document: still "in cloud", id unknown."""
        dataset = _dataset(tmp_path)
        dataset.database_add(ndi_document("dataset_remote"))

        in_cloud, cloud_id = dataset.isInCloud()

        assert in_cloud is True
        assert cloud_id == ""

    def test_non_string_id_is_coerced(self, tmp_path):
        """Mirrors MATLAB's ``char(string(...))``."""
        dataset = _dataset(tmp_path)
        dataset.database_add(_remote_doc(12345))

        assert dataset.isInCloud() == (True, "12345")


class TestIsInCloudIsLocalAndCheap:
    def test_does_not_use_the_linked_session_fan_out(self, tmp_path, monkeypatch):
        """Must query the dataset's own database, not ``database_search``.

        ``ndi_dataset.database_search`` also searches every linked session,
        which opens them. MATLAB explicitly reads
        ``ndi_dataset_obj.session.database.search`` instead, because the
        ``dataset_remote`` document lives in the dataset's own database.
        """
        dataset = _dataset(tmp_path)
        dataset.database_add(_remote_doc("cloud-local"))

        def explode(*args, **kwargs):
            raise AssertionError("isInCloud must not fan out to linked sessions")

        monkeypatch.setattr(type(dataset), "database_search", explode)
        monkeypatch.setattr(type(dataset), "_open_linked_sessions", explode)

        assert dataset.isInCloud() == (True, "cloud-local")

    def test_makes_no_network_call(self, tmp_path, monkeypatch):
        """A purely local check must not build a cloud client."""
        import ndi.cloud.client as cloud_client

        dataset = _dataset(tmp_path)
        dataset.database_add(_remote_doc("cloud-local"))

        def explode(*args, **kwargs):
            raise AssertionError("isInCloud must not touch the network")

        monkeypatch.setattr(cloud_client.CloudClient, "from_env", staticmethod(explode))

        assert dataset.isInCloud() == (True, "cloud-local")


class TestIsInCloudNeverThrows:
    def test_a_failing_database_search_returns_false(self, tmp_path, monkeypatch):
        dataset = _dataset(tmp_path)

        def boom(*args, **kwargs):
            raise RuntimeError("database is on fire")

        monkeypatch.setattr(dataset._session._database, "search", boom)

        assert dataset.isInCloud() == (False, "")

    def test_a_dataset_without_a_database_returns_false(self, tmp_path):
        dataset = _dataset(tmp_path)
        dataset._session._database = None

        assert dataset.isInCloud() == (False, "")

    def test_a_malformed_remote_document_returns_an_empty_id(self, tmp_path, monkeypatch):
        """A document whose properties are not the expected shape."""

        class Weird:
            document_properties = {"dataset_remote": "not-an-object"}

        dataset = _dataset(tmp_path)
        monkeypatch.setattr(dataset._session._database, "search", lambda *a, **k: [Weird()])

        assert dataset.isInCloud() == (True, "")


class TestIsInCloudSitsBesideIsIngested:
    def test_both_status_checks_are_available(self, tmp_path):
        """Guards against isInCloud landing on the wrong class."""
        dataset = _dataset(tmp_path)

        assert callable(dataset.isIngested)
        assert callable(dataset.isInCloud)

    def test_is_documented_as_the_matlab_port(self):
        from ndi.dataset._dataset import ndi_dataset

        doc = ndi_dataset.isInCloud.__doc__ or ""
        assert "dataset_remote" in doc


@pytest.mark.parametrize("cloud_id", ["a", "0" * 24, "with-dashes-123"])
def test_round_trips_any_cloud_id(tmp_path, cloud_id):
    dataset = ndi_dataset_dir("cloud_ref", tmp_path / cloud_id)
    dataset.database_add(_remote_doc(cloud_id))

    assert dataset.isInCloud() == (True, cloud_id)
