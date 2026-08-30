"""Tests for the .ndi object-type marker (issue #73).

MATLAB records what a directory holds in ``.ndi/ndi_object_type.txt`` so the
type can be told cheaply -- by a file-open dialog, say -- without fully
instantiating the object. NDI-python never wrote it, so MATLAB reading a
Python-generated directory got 'unknown' where it expected 'dataset'.
"""

from __future__ import annotations

import pytest

from ndi.dataset import ndi_dataset_dir
from ndi.session.dir import ndi_session_dir

MARKER = "ndi_object_type.txt"


def _marker_path(root):
    return root / ".ndi" / MARKER


class TestMarkerFilename:
    def test_matches_matlab(self):
        """MATLAB's objecttypemarkerfilename() returns this exact name."""
        assert ndi_session_dir.objecttypemarkerfilename() == MARKER


class TestSessionMarker:
    def test_session_is_marked_on_construction(self, tmp_path):
        ndi_session_dir("sess", str(tmp_path))
        assert _marker_path(tmp_path).read_text().strip() == "session"

    def test_marker_lands_in_dot_ndi(self, tmp_path):
        ndi_session_dir("sess", str(tmp_path))
        assert MARKER in [p.name for p in (tmp_path / ".ndi").iterdir()]

    def test_directorytype_reports_session(self, tmp_path):
        ndi_session_dir("sess", str(tmp_path))
        assert ndi_session_dir.directorytype(str(tmp_path)) == "session"

    def test_reopening_keeps_session(self, tmp_path):
        ndi_session_dir("sess", str(tmp_path))
        ndi_session_dir(str(tmp_path))
        assert ndi_session_dir.directorytype(str(tmp_path)) == "session"


class TestDatasetMarker:
    def test_dataset_is_marked_dataset(self, tmp_path):
        ndi_dataset_dir("myds", str(tmp_path))
        assert _marker_path(tmp_path).read_text().strip() == "dataset"

    def test_directorytype_reports_dataset(self, tmp_path):
        ndi_dataset_dir("myds", str(tmp_path))
        assert ndi_session_dir.directorytype(str(tmp_path)) == "dataset"

    def test_reopening_dataset_keeps_dataset(self, tmp_path):
        ndi_dataset_dir("myds", str(tmp_path))
        ndi_dataset_dir(str(tmp_path))
        assert ndi_session_dir.directorytype(str(tmp_path)) == "dataset"

    def test_opening_a_dataset_as_a_session_does_not_downgrade_it(self, tmp_path):
        """The guard that matters.

        ndi_dataset_dir keeps an underlying session at the same path, and
        ingesting a session into a dataset builds a temporary session there.
        Either would relabel the directory 'session' without the never-
        downgrade rule in updateObjectTypeMarker.
        """
        ndi_dataset_dir("myds", str(tmp_path))
        ndi_session_dir(str(tmp_path))
        assert ndi_session_dir.directorytype(str(tmp_path)) == "dataset"


class TestDirectoryType:
    def test_none_for_a_directory_that_is_not_ndi(self, tmp_path):
        assert ndi_session_dir.directorytype(str(tmp_path)) == "none"

    def test_unknown_when_the_marker_predates_markers(self, tmp_path):
        """A directory created before markers existed reports 'unknown'."""
        ndi_session_dir("sess", str(tmp_path))
        _marker_path(tmp_path).unlink()
        assert ndi_session_dir.directorytype(str(tmp_path)) == "unknown"

    def test_unknown_for_an_unrecognized_marker_value(self, tmp_path):
        ndi_session_dir("sess", str(tmp_path))
        _marker_path(tmp_path).write_text("something else")
        assert ndi_session_dir.directorytype(str(tmp_path)) == "unknown"

    def test_marker_is_read_case_and_whitespace_insensitively(self, tmp_path):
        ndi_session_dir("sess", str(tmp_path))
        _marker_path(tmp_path).write_text("  DataSet \n")
        assert ndi_session_dir.directorytype(str(tmp_path)) == "dataset"


class TestSetObjectTypeMarker:
    def test_writes_the_value(self, tmp_path):
        s = ndi_session_dir("sess", str(tmp_path))
        s.setObjectTypeMarker("dataset")
        assert ndi_session_dir.directorytype(str(tmp_path)) == "dataset"

    def test_rejects_anything_else(self, tmp_path):
        s = ndi_session_dir("sess", str(tmp_path))
        with pytest.raises(ValueError, match="session.*dataset"):
            s.setObjectTypeMarker("elephant")
