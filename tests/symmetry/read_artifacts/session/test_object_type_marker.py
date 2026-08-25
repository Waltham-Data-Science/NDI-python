"""Read + verify the ``.ndi/ndi_object_type.txt`` object-type marker on session
artifacts (M1).

Python equivalent of (to be authored):
    tests/+ndi/+symmetry/+readArtifacts/+session/objectTypeMarker.m

The point of the marker is that a caller -- a file-open dialog, say -- can tell
a session directory from a dataset directory WITHOUT instantiating either
object.  So this test never opens the sessions: it calls the static
``ndi.session.dir.directorytype`` (and ``ndi.dataset.dir.exists``) on each
artifact directory, which is exactly what MATLAB does.

That restraint is load-bearing, not stylistic.  Opening an NDI directory
backfills the marker in both languages -- deliberately, so legacy directories
migrate on first open.  A test that opened the session and then read the marker
would therefore pass against an artifact that had arrived without one, and the
cross-language claim ("MATLAB wrote a marker Python can read") would be
measuring Python's own backfill.  Nothing in this module may open a session.

Skips when the source's ``session`` artifact root is absent, per
read_artifacts/INSTRUCTIONS.md; ``NDI_SYMMETRY_REQUIRE_ARTIFACTS=1`` turns that
skip into a failure via tests/symmetry/conftest.py.
"""

import pytest

from ndi.dataset import Dataset
from ndi.session.dir import ndi_session_dir
from tests.symmetry._object_type_marker import (
    SESSION_ARTIFACTS,
    read_marker,
    replay_marker_directory,
)
from tests.symmetry.conftest import SOURCE_TYPES, SYMMETRY_BASE


@pytest.fixture(params=SOURCE_TYPES)
def source_type(request):
    """Parameterize over matlabArtifacts / pythonArtifacts."""
    return request.param


class TestObjectTypeMarker:
    """Mirror of ndi.symmetry.readArtifacts.session.objectTypeMarker."""

    def _present_session_dirs(self, source_type):
        """The listed session artifact directories that this source produced.

        Skips (a) when the source has no ``session`` namespace at all, and
        (b) when it has one but none of the listed directories are in it --
        the second guard is what stops this test from "passing" having
        classified nothing.
        """
        namespace_root = SYMMETRY_BASE / source_type / "session"
        if not namespace_root.is_dir():
            pytest.skip(
                f"Artifact namespace {namespace_root} from {source_type} does not "
                f"exist. Run the corresponding makeArtifacts suite first."
            )
        dirs = [
            (class_name, SYMMETRY_BASE / source_type / ns / class_name / test_name)
            for ns, class_name, test_name in SESSION_ARTIFACTS
        ]
        present = [(name, path) for name, path in dirs if path.is_dir()]
        if not present:
            pytest.skip(
                f"{namespace_root} exists but holds none of the expected session "
                f"artifact directories {[c for _, c, _ in SESSION_ARTIFACTS]}; "
                f"nothing to classify."
            )
        return present

    @staticmethod
    def _as_delivered(path, snapshot, tmp_path, index):
        """A replay of *path*'s marker exactly as the producing language wrote it."""
        assert (
            path in snapshot
        ), f"{path} was not in the pre-run marker snapshot; it appeared during the test run."
        return replay_marker_directory(snapshot[path], tmp_path / f"replay{index}")

    def test_directorytype_reports_session(
        self, source_type, object_type_marker_snapshot, tmp_path
    ):
        """Python's directorytype() classifies every session artifact as 'session'.

        Run against a replay of the marker as delivered, so an artifact that
        arrived without one cannot be rescued by the backfill an earlier test
        performed when it opened the session.
        """
        for index, (class_name, path) in enumerate(self._present_session_dirs(source_type)):
            replay = self._as_delivered(path, object_type_marker_snapshot, tmp_path, index)
            actual = ndi_session_dir.directorytype(replay)
            assert actual == "session", (
                f"{source_type} artifact {class_name} at {path}: as delivered, "
                f"directorytype() returns {actual!r}, expected 'session'. "
                f"Marker as delivered: {object_type_marker_snapshot[path]!r}; "
                f"on disk now: {read_marker(path)!r}."
            )

    def test_session_directories_are_not_datasets(
        self, source_type, object_type_marker_snapshot, tmp_path
    ):
        """The same directories must NOT answer ndi.dataset.dir.exists.

        directorytype() returning 'session' and Dataset.exists() returning
        False are the two halves of the same claim; asserting only the first
        would still pass a marker that both languages read as ambiguous.
        """
        for index, (class_name, path) in enumerate(self._present_session_dirs(source_type)):
            replay = self._as_delivered(path, object_type_marker_snapshot, tmp_path, index)
            assert not Dataset.exists(replay), (
                f"{source_type} artifact {class_name} at {path} is a session, "
                f"but ndi.dataset.dir.exists() accepted it as a dataset. "
                f"Marker as delivered: {object_type_marker_snapshot[path]!r}"
            )

    def test_marker_bytes_as_written_by_the_producing_language(
        self, source_type, object_type_marker_snapshot
    ):
        """The marker file is written verbatim, like the sibling reference.txt.

        MATLAB writes it with ``vlt.file.str2text``; Python's port pins the same
        bytes.  A language that appended a newline would still be readable
        (``directorytype`` strips), so only a byte-level check catches the
        divergence -- and it is the kind that silently spreads once one side
        starts stripping.

        Asserted against the pre-run snapshot, not the file on disk now: by the
        time this test runs, earlier read tests have opened these sessions, and
        opening backfills the marker.  Reading the file here would be reading
        Python's own backfill and calling it MATLAB's output.
        """
        for class_name, path in self._present_session_dirs(source_type):
            assert path in object_type_marker_snapshot, (
                f"{source_type} artifact {class_name} at {path} was not in the "
                f"pre-run marker snapshot; it appeared during the test run."
            )
            contents = object_type_marker_snapshot[path]
            assert contents == "session", (
                f"{source_type} artifact {class_name} at {path}: as written by the "
                f"producing language the marker file contents were {contents!r}, "
                f"expected exactly 'session' with no trailing newline or whitespace. "
                f"(On disk now: {read_marker(path)!r}.)"
            )
