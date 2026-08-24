"""Tests for the ``.ndi`` object-type marker file (``ndi_object_type.txt``).

Mirrors the MATLAB unit test
``tests/+ndi/+unittest/+session/testDirectoryType.m`` and the MATLAB
implementation in ``+ndi/+session/dir.m``
(``objecttypemarkerfilename``/``updateObjectTypeMarker``/
``setObjectTypeMarker``/``directorytype``) and ``+ndi/+dataset/dir.m``.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from ndi.dataset import ndi_dataset_dir
from ndi.document import ndi_document
from ndi.session import ndi_session_dir


@pytest.fixture
def temp_dir():
    """Create a temporary directory that is removed after the test."""
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


def _markerfile(path: Path) -> Path:
    """Marker path as MATLAB's directorytype() computes it."""
    return Path(path) / ".ndi" / ndi_session_dir.objecttypemarkerfilename()


class TestObjectTypeMarkerFilename:
    """The marker file name is part of the on-disk contract with MATLAB."""

    def test_filename_matches_matlab(self):
        assert ndi_session_dir.objecttypemarkerfilename() == "ndi_object_type.txt"


class TestSetObjectTypeMarker:
    """setObjectTypeMarker writes TYPESTR unconditionally."""

    def test_writes_exact_bytes_no_trailing_newline(self, temp_dir):
        p = temp_dir / "a_session"
        p.mkdir()
        s = ndi_session_dir("my_ref", p)
        s.setObjectTypeMarker("dataset")
        # MATLAB vlt.file.str2text writes the string with no trailing newline;
        # the sibling reference.txt file is written the same way.
        assert _markerfile(p).read_bytes() == b"dataset"

    def test_rejects_other_types(self, temp_dir):
        p = temp_dir / "a_session"
        p.mkdir()
        s = ndi_session_dir("my_ref", p)
        with pytest.raises(ValueError):
            s.setObjectTypeMarker("something_else")


class TestDirectoryType:
    """ndi.session.dir.directorytype semantics."""

    def test_session_is_detected_as_session(self, temp_dir):
        p = temp_dir / "a_session"
        p.mkdir()
        ndi_session_dir("my_ref", p)

        assert ndi_session_dir.directorytype(p) == "session"
        assert _markerfile(p).read_bytes() == b"session"
        assert ndi_dataset_dir.exists(p) is False
        assert ndi_session_dir.exists(p) is True

    def test_empty_dataset_is_detected_as_dataset(self, temp_dir):
        p = temp_dir / "an_empty_dataset"
        p.mkdir()
        ndi_dataset_dir("my_ds_ref", str(p))

        assert ndi_session_dir.directorytype(p) == "dataset"
        assert ndi_dataset_dir.exists(p) is True
        assert ndi_session_dir.exists(p) is True

    def test_non_ndi_directory_is_none(self, temp_dir):
        p = temp_dir / "not_ndi"
        p.mkdir()
        # MATLAB commit 97444ee46: 'none', not '' (empty string).
        assert ndi_session_dir.directorytype(p) == "none"
        assert ndi_dataset_dir.exists(p) is False

    def test_missing_directory_is_none(self, temp_dir):
        assert ndi_session_dir.directorytype(temp_dir / "does_not_exist") == "none"

    def test_legacy_directory_is_unknown_then_migrated(self, temp_dir):
        p = temp_dir / "legacy_session"
        p.mkdir()
        ndi_session_dir("legacy_ref", p)

        # Simulate a directory created before markers existed.
        _markerfile(p).unlink()
        assert ndi_session_dir.directorytype(p) == "unknown"

        # Re-opening records the type (lazy migration / backfill).
        ndi_session_dir(p)
        assert ndi_session_dir.directorytype(p) == "session"

    def test_unrecognized_marker_contents_is_unknown(self, temp_dir):
        p = temp_dir / "garbled"
        p.mkdir()
        ndi_session_dir("ref", p)
        _markerfile(p).write_text("banana")
        assert ndi_session_dir.directorytype(p) == "unknown"

    def test_marker_read_is_case_and_whitespace_insensitive(self, temp_dir):
        p = temp_dir / "sloppy"
        p.mkdir()
        ndi_session_dir("ref", p)
        _markerfile(p).write_text("  DataSet \n")
        assert ndi_session_dir.directorytype(p) == "dataset"

    def test_accepts_string_path(self, temp_dir):
        p = temp_dir / "a_session"
        p.mkdir()
        ndi_session_dir("my_ref", p)
        assert ndi_session_dir.directorytype(str(p)) == "session"


class TestUpdateObjectTypeMarker:
    """updateObjectTypeMarker never downgrades and detects legacy datasets."""

    def test_reopening_dataset_as_session_does_not_downgrade(self, temp_dir):
        p = temp_dir / "dataset_reopened_as_session"
        p.mkdir()
        ndi_dataset_dir("ds_ref", str(p))
        assert ndi_session_dir.directorytype(p) == "dataset"

        # Opening the same directory as a session (as the dataset itself does
        # internally) must preserve the dataset marker.
        ndi_session_dir(p)
        assert ndi_session_dir.directorytype(p) == "dataset"
        assert ndi_dataset_dir.exists(p) is True

    def test_populated_dataset_stays_dataset_across_reopen(self, temp_dir):
        """A dataset with a linked session keeps its marker when re-opened."""
        dspath = temp_dir / "populated_dataset"
        dspath.mkdir()
        spath = temp_dir / "a_linked_session"
        spath.mkdir()

        ds = ndi_dataset_dir("ds_ref", str(dspath))
        ds.add_linked_session(ndi_session_dir("linked_ref", spath))
        assert ndi_session_dir.directorytype(dspath) == "dataset"

        # Re-opening as a dataset, then as a plain session, must both preserve
        # the marker (ndi_dataset_dir keeps an ndi_session_dir at the same path).
        ndi_dataset_dir(str(dspath))
        assert ndi_session_dir.directorytype(dspath) == "dataset"
        ndi_session_dir(dspath)
        assert ndi_session_dir.directorytype(dspath) == "dataset"

        # The linked session's own directory is still a plain session.
        assert ndi_session_dir.directorytype(spath) == "session"

    def test_populated_dataset_marker_is_rebuilt_by_session_open(self, temp_dir):
        """Deleting the marker of a real populated dataset: a session open restores it.

        This is MATLAB's updateObjectTypeMarker dataset-detection branch reached
        through the real dataset API rather than a hand-built document.
        """
        dspath = temp_dir / "unmarked_populated_dataset"
        dspath.mkdir()
        spath = temp_dir / "another_linked_session"
        spath.mkdir()

        ds = ndi_dataset_dir("ds_ref", str(dspath))
        ds.add_linked_session(ndi_session_dir("linked_ref", spath))

        _markerfile(dspath).unlink()
        assert ndi_session_dir.directorytype(dspath) == "unknown"

        ndi_session_dir(dspath)
        assert ndi_session_dir.directorytype(dspath) == "dataset"
        assert ndi_dataset_dir.exists(dspath) is True

    def test_legacy_dataset_backfills_dataset_marker(self, temp_dir):
        """A marker-less directory holding dataset bookkeeping docs is a dataset.

        MATLAB looks for 'session_in_a_dataset' (current) documents and marks
        the directory 'dataset' rather than 'session'.
        """
        p = temp_dir / "legacy_dataset"
        p.mkdir()
        s = ndi_session_dir("legacy_ds_ref", p)
        doc = ndi_document(
            "session_in_a_dataset",
            **{
                "session_in_a_dataset.session_id": s.id(),
                "session_in_a_dataset.session_reference": "legacy_ds_ref",
                "session_in_a_dataset.is_linked": False,
                "session_in_a_dataset.session_creator": "ndi_session_dir",
            },
        )
        doc = doc.set_session_id(s.id())
        s.database_add(doc)

        # Simulate the pre-marker era.
        _markerfile(p).unlink()
        assert ndi_session_dir.directorytype(p) == "unknown"

        ndi_session_dir(p)
        assert ndi_session_dir.directorytype(p) == "dataset"

    def test_legacy_dataset_session_info_backfills_dataset_marker(self, temp_dir):
        """The legacy 'dataset_session_info' document type also marks a dataset."""
        p = temp_dir / "very_legacy_dataset"
        p.mkdir()
        s = ndi_session_dir("very_legacy_ds_ref", p)
        doc = ndi_document(
            "dataset_session_info",
            **{
                "dataset_session_info.dataset_session_info": [
                    {
                        "session_id": s.id(),
                        "session_reference": "very_legacy_ds_ref",
                        "is_linked": 0,
                    }
                ]
            },
        )
        doc = doc.set_session_id(s.id())
        s.database_add(doc)

        _markerfile(p).unlink()
        ndi_session_dir(p)
        assert ndi_session_dir.directorytype(p) == "dataset"
