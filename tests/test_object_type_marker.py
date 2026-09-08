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


class TestDotNdiLayout:
    """The .ndi listing MATLAB expects.

    The symmetry tests compare this listing between languages, so the set has
    to match exactly -- a lazily-created directory reads as a missing entry
    just as a never-written file does (#73).
    """

    #: Confirmed against a real MATLAB-generated .ndi directory.
    MATLAB_ENTRIES = {
        "did-sqlite.sqlite",
        "files",
        "ndi_object_type.txt",
        "reference.txt",
        "unique_reference.txt",
    }

    def test_session_dot_ndi_matches_matlab(self, tmp_path):
        ndi_session_dir("sess", str(tmp_path))
        assert {p.name for p in (tmp_path / ".ndi").iterdir()} == self.MATLAB_ENTRIES

    def test_files_directory_exists_before_any_file_is_stored(self, tmp_path):
        """DID creates files/ lazily; MATLAB has it from the start."""
        ndi_session_dir("sess", str(tmp_path))
        assert (tmp_path / ".ndi" / "files").is_dir()

    def test_dataset_dot_ndi_matches_matlab(self, tmp_path):
        ndi_dataset_dir("myds", str(tmp_path))
        assert {p.name for p in (tmp_path / ".ndi").iterdir()} == self.MATLAB_ENTRIES

    def test_summary_agrees_with_disk(self, tmp_path):
        """filesInDotNDI is what the symmetry comparison actually reads."""
        from ndi.util.session_summary import sessionSummary

        s = ndi_session_dir("sess", str(tmp_path))
        assert set(sessionSummary(s)["filesInDotNDI"]) == self.MATLAB_ENTRIES


class TestSetObjectTypeMarker:
    def test_writes_the_value(self, tmp_path):
        s = ndi_session_dir("sess", str(tmp_path))
        s.setObjectTypeMarker("dataset")
        assert ndi_session_dir.directorytype(str(tmp_path)) == "dataset"

    def test_rejects_anything_else(self, tmp_path):
        s = ndi_session_dir("sess", str(tmp_path))
        with pytest.raises(ValueError, match="session.*dataset"):
            s.setObjectTypeMarker("elephant")


class TestASessionDirectoryIsNotADataset:
    """MATLAB counterpart: ``ndi.dataset.dir.mustNotBeSession``.

    Opening a plain session as a dataset used to succeed -- it falls back to
    the session's own document -- and the constructor then wrote 'dataset'
    into the marker, so the mistake was persisted and the next open
    inherited it. The guard reads the marker instead of opening anything.
    """

    def test_opening_a_session_as_a_dataset_is_refused(self, tmp_path):
        root = tmp_path / "plain_session"
        root.mkdir()
        ndi_session_dir("a_session", root)

        with pytest.raises(ValueError, match="holds an ndi.session"):
            ndi_dataset_dir(str(root))

    def test_the_two_argument_form_is_guarded_too(self, tmp_path):
        root = tmp_path / "plain_session_two_arg"
        root.mkdir()
        ndi_session_dir("a_session", root)

        with pytest.raises(ValueError, match="holds an ndi.session"):
            ndi_dataset_dir("some_reference", str(root))

    def test_the_refusal_does_not_relabel_the_directory(self, tmp_path):
        """The damage the guard exists to prevent: a persisted wrong type."""
        root = tmp_path / "still_a_session"
        root.mkdir()
        ndi_session_dir("a_session", root)

        with pytest.raises(ValueError):
            ndi_dataset_dir(str(root))

        assert _marker_path(root).read_text().strip() == "session"
        assert ndi_session_dir.directorytype(root) == "session"

    def test_an_empty_directory_is_still_allowed(self, tmp_path):
        """'none' means a dataset can be created here."""
        root = tmp_path / "brand_new"
        root.mkdir()
        dataset = ndi_dataset_dir("new_dataset", str(root))
        assert dataset is not None
        assert ndi_session_dir.directorytype(root) == "dataset"

    def test_an_existing_dataset_still_opens(self, tmp_path):
        root = tmp_path / "real_dataset"
        root.mkdir()
        ndi_dataset_dir("real_dataset", str(root))

        reopened = ndi_dataset_dir(str(root))
        assert reopened is not None


class TestDatasetExists:
    """MATLAB counterpart: ``ndi.dataset.dir.exists``."""

    def test_true_for_a_dataset(self, tmp_path):
        root = tmp_path / "exists_dataset"
        root.mkdir()
        ndi_dataset_dir("exists_dataset", str(root))
        assert ndi_dataset_dir.exists(root) is True

    def test_false_for_a_session(self, tmp_path):
        root = tmp_path / "exists_session"
        root.mkdir()
        ndi_session_dir("exists_session", root)
        assert ndi_dataset_dir.exists(root) is False

    def test_false_for_a_directory_that_is_neither(self, tmp_path):
        root = tmp_path / "exists_nothing"
        root.mkdir()
        assert ndi_dataset_dir.exists(root) is False


class TestADatasetIsRecognisedWhateverSessionYouOpen:
    """The marker must not depend on which session the open happened to adopt.

    ``updateObjectTypeMarker`` looks for the dataset bookkeeping documents
    (``session_in_a_dataset``, or the legacy ``dataset_session_info``). It
    used to look through ``session.database_search``, which filters on
    ``base.session_id == self.id()`` -- and a downloaded dataset holds
    several sessions, so opening its directory as a plain session adopts one
    that need not be the one the bookkeeping document belongs to. The
    document was then invisible and a real dataset was recorded as a
    session.

    That was harmless while nothing read the marker for a decision. It
    stopped being harmless when ``mustNotBeSession`` began refusing to open a
    directory marked 'session': the symmetry archive
    ``69a8705aa9ab25373cdc6563`` has 0 session-filtered and 1 unfiltered
    ``session_in_a_dataset`` document, so the dataset became un-openable.

    The looser search cannot mislabel a plain session in the other
    direction: a session holds no such document under any session id.
    """

    def test_the_document_is_found_under_another_session_id(self, tmp_path):
        from ndi.document import ndi_document
        from ndi.ido import ndi_ido
        from ndi.query import ndi_query

        root = tmp_path / "borrowed_bookkeeping"
        root.mkdir()
        session = ndi_session_dir("a_session", root)

        # A bookkeeping document owned by some OTHER session, which is the
        # shape a downloaded dataset arrives in.
        doc = ndi_document(
            "session_in_a_dataset",
            **{
                "session_in_a_dataset.session_id": ndi_ido().id,
                "session_in_a_dataset.is_linked": 0,
            },
        )
        doc = doc.set_session_id(ndi_ido().id)
        session._database.add(doc)

        assert session.database_search(ndi_query("").isa("session_in_a_dataset")) == []
        assert session._database.search(ndi_query("").isa("session_in_a_dataset"))

        session.updateObjectTypeMarker()

        assert _marker_path(root).read_text().strip() == "dataset"
        assert ndi_session_dir.directorytype(root) == "dataset"

    def test_a_plain_session_is_still_a_session(self, tmp_path):
        """The looser search must not start calling every session a dataset."""
        root = tmp_path / "genuinely_a_session"
        root.mkdir()
        session = ndi_session_dir("a_session", root)
        session.updateObjectTypeMarker()
        assert _marker_path(root).read_text().strip() == "session"
