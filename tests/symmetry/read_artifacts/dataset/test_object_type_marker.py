"""Read + verify the ``.ndi/ndi_object_type.txt`` object-type marker on dataset
artifacts (M1).

Python equivalent of (to be authored):
    tests/+ndi/+symmetry/+readArtifacts/+dataset/objectTypeMarker.m

Dataset half of the marker symmetry check; see the module docstring of
``read_artifacts/session/test_object_type_marker.py`` for why nothing here may
open a dataset (opening backfills the marker, which would make the test measure
Python's own migration path rather than what the other language wrote).

``buildDataset``'s artifact directory IS the dataset directory.
``downloadIngested`` unpacks an archive, so its dataset directory is the single
sub-directory of the artifact directory -- both languages lay it out that way.
"""

import pytest

from ndi.dataset import Dataset
from ndi.session.dir import ndi_session_dir
from tests.symmetry._object_type_marker import (
    DATASET_ARTIFACTS,
    NESTED_DATASET_ARTIFACTS,
    read_marker,
    replay_marker_directory,
    resolve_dataset_dir,
)
from tests.symmetry.conftest import SOURCE_TYPES, SYMMETRY_BASE


@pytest.fixture(params=SOURCE_TYPES)
def source_type(request):
    """Parameterize over matlabArtifacts / pythonArtifacts."""
    return request.param


class TestObjectTypeMarker:
    """Mirror of ndi.symmetry.readArtifacts.dataset.objectTypeMarker."""

    def _present_dataset_dirs(self, source_type):
        """The listed dataset directories this source produced.

        A ``downloadIngested`` artifact whose archive did not unpack to exactly
        one sub-directory is reported as a hard failure rather than quietly
        dropped: that one-directory shape is an invariant both makeArtifacts
        suites already assert, so violating it means the artifact is broken,
        not absent.
        """
        namespace_root = SYMMETRY_BASE / source_type / "dataset"
        if not namespace_root.is_dir():
            pytest.skip(
                f"Artifact namespace {namespace_root} from {source_type} does not "
                f"exist. Run the corresponding makeArtifacts suite first."
            )

        present = []
        for ns, class_name, test_name in DATASET_ARTIFACTS:
            path = SYMMETRY_BASE / source_type / ns / class_name / test_name
            if path.is_dir():
                present.append((class_name, path))

        for ns, class_name, test_name in NESTED_DATASET_ARTIFACTS:
            artifact_dir = SYMMETRY_BASE / source_type / ns / class_name / test_name
            if not artifact_dir.is_dir():
                continue
            dataset_dir = resolve_dataset_dir(artifact_dir)
            assert dataset_dir is not None, (
                f"{source_type} artifact {class_name} at {artifact_dir} does not "
                f"hold exactly one sub-directory; the unpacked dataset directory "
                f"cannot be identified."
            )
            present.append((class_name, dataset_dir))

        if not present:
            pytest.skip(
                f"{namespace_root} exists but holds none of the expected dataset "
                f"artifact directories; nothing to classify."
            )
        return present

    @staticmethod
    def _as_delivered(path, snapshot, tmp_path, index):
        """A replay of *path*'s marker exactly as the producing language wrote it."""
        assert (
            path in snapshot
        ), f"{path} was not in the pre-run marker snapshot; it appeared during the test run."
        return replay_marker_directory(snapshot[path], tmp_path / f"replay{index}")

    def test_directorytype_reports_dataset(
        self, source_type, object_type_marker_snapshot, tmp_path
    ):
        """Python's directorytype() classifies every dataset artifact as 'dataset'.

        Run against a replay of the marker as delivered; see the session-side
        counterpart for why the artifact on disk is not the honest input.
        """
        for index, (class_name, path) in enumerate(self._present_dataset_dirs(source_type)):
            replay = self._as_delivered(path, object_type_marker_snapshot, tmp_path, index)
            actual = ndi_session_dir.directorytype(replay)
            assert actual == "dataset", (
                f"{source_type} artifact {class_name} at {path}: as delivered, "
                f"directorytype() returns {actual!r}, expected 'dataset'. "
                f"Marker as delivered: {object_type_marker_snapshot[path]!r}; "
                f"on disk now: {read_marker(path)!r}."
            )

    def test_dataset_dir_exists_accepts_them(
        self, source_type, object_type_marker_snapshot, tmp_path
    ):
        """``ndi.dataset.dir.exists`` -- the marker's production caller."""
        for index, (class_name, path) in enumerate(self._present_dataset_dirs(source_type)):
            replay = self._as_delivered(path, object_type_marker_snapshot, tmp_path, index)
            assert Dataset.exists(replay), (
                f"{source_type} artifact {class_name} at {path} is a dataset, "
                f"but ndi.dataset.dir.exists() rejected it. "
                f"Marker as delivered: {object_type_marker_snapshot[path]!r}"
            )

    def test_marker_bytes_as_written_by_the_producing_language(
        self, source_type, object_type_marker_snapshot
    ):
        """Byte-exact marker contents; see the session-side counterpart.

        Asserted against the pre-run snapshot because opening a dataset
        backfills the marker, and earlier read tests open these datasets.
        """
        for class_name, path in self._present_dataset_dirs(source_type):
            assert path in object_type_marker_snapshot, (
                f"{source_type} artifact {class_name} at {path} was not in the "
                f"pre-run marker snapshot; it appeared during the test run."
            )
            contents = object_type_marker_snapshot[path]
            assert contents == "dataset", (
                f"{source_type} artifact {class_name} at {path}: as written by the "
                f"producing language the marker file contents were {contents!r}, "
                f"expected exactly 'dataset' with no trailing newline or whitespace. "
                f"(On disk now: {read_marker(path)!r}.)"
            )
