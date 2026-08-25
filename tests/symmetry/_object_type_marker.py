"""Shared inventory + helpers for the ``.ndi/ndi_object_type.txt`` marker (M1).

The object-type marker lets a caller tell a session directory from a dataset
directory *without instantiating either object* -- which is the whole point of
it, and also the reason a symmetry test for it cannot simply open the directory
and ask.  Opening an NDI directory BACKFILLS the marker (both languages do
this deliberately, so legacy directories migrate on first open), so a read-side
test that opens the session first and checks the marker afterwards would pass
against an artifact that never carried a marker at all.  Every helper here
therefore reads the file, or calls the static ``directorytype``, and nothing
else.

MATLAB counterparts:
    +ndi/+session/dir.m   objecttypemarkerfilename / directorytype
    +ndi/+dataset/dir.m   exists
"""

from __future__ import annotations

from pathlib import Path

# Mirrors ndi.session.dir.objecttypemarkerfilename() in both languages.
MARKER_FILENAME = "ndi_object_type.txt"

# (namespace, className, testName) of every makeArtifacts test whose artifact
# directory IS an NDI session directory.  camelCase, matching the artifact path
# contract in make_artifacts/INSTRUCTIONS.md.
SESSION_ARTIFACTS: tuple[tuple[str, str, str], ...] = (
    ("session", "buildSession", "testBuildSessionArtifacts"),
    ("session", "blankSessionKjnielsenlab", "testBlankSessionKjnielsenlab"),
    ("session", "blankSessionMarderlab", "testBlankSessionMarderlab"),
    ("session", "blankSessionRayolab", "testBlankSessionRayolab"),
    ("session", "blankSessionVhlab", "testBlankSessionVhlab"),
    ("session", "ingestionAxonNDR", "testIngestionAxonNDRArtifacts"),
    ("session", "ingestionIntan", "testIngestionIntanArtifacts"),
    ("session", "ingestionIntanNDR", "testIngestionIntanNDRArtifacts"),
)

# Same, for artifact directories that ARE an NDI dataset directory.
DATASET_ARTIFACTS: tuple[tuple[str, str, str], ...] = (
    ("dataset", "buildDataset", "testBuildDatasetArtifacts"),
)

# downloadIngested unpacks an archive, so the dataset directory is the single
# sub-directory of the artifact directory rather than the artifact directory
# itself.  Both languages lay it out this way (see the MATLAB
# +makeArtifacts/+dataset/downloadIngested.m untar + one-subdir check).
NESTED_DATASET_ARTIFACTS: tuple[tuple[str, str, str], ...] = (
    ("dataset", "downloadIngested", "testDownloadIngestedArtifacts"),
)


def marker_path(ndi_object_dir: str | Path) -> Path:
    """Path of the marker file inside *ndi_object_dir*'s ``.ndi`` folder."""
    return Path(ndi_object_dir) / ".ndi" / MARKER_FILENAME


def read_marker(ndi_object_dir: str | Path) -> str | None:
    """Raw marker contents, or ``None`` when the marker file is absent.

    Returned verbatim -- callers that want the semantic value should strip and
    lowercase, as ``directorytype`` does.  Kept raw here so a test can pin that
    the file has no trailing newline, which is part of the ported contract
    (MATLAB writes it with ``vlt.file.str2text``, like the sibling
    ``reference.txt``).
    """
    path = marker_path(ndi_object_dir)
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def assert_object_type_marker(ndi_object_dir: str | Path, expected: str) -> None:
    """Assert *ndi_object_dir* carries an object-type marker reading *expected*.

    Used by the make_artifacts side so that a Python-produced artifact that
    silently lost its marker fails at the producing test rather than surfacing
    later as an unexplained MATLAB read failure.
    """
    path = marker_path(ndi_object_dir)
    contents = read_marker(ndi_object_dir)
    assert contents is not None, (
        f"Object-type marker missing: {path} was not written. "
        f"Every NDI session/dataset directory must carry .ndi/{MARKER_FILENAME} "
        f"so the other language can identify it without opening it."
    )
    assert contents == expected, (
        f"Object-type marker {path} reads {contents!r}, expected {expected!r} "
        f"(exact bytes: the marker is written with no trailing newline)."
    )


def _all_known_object_dirs() -> list[Path]:
    """Every artifact directory that should be an NDI session or dataset directory.

    Across both source types, and resolving ``downloadIngested``'s nested layout.
    Only directories that currently exist are returned.
    """
    from tests.symmetry.conftest import SOURCE_TYPES, SYMMETRY_BASE

    found: list[Path] = []
    for source_type in SOURCE_TYPES:
        for ns, class_name, test_name in SESSION_ARTIFACTS + DATASET_ARTIFACTS:
            path = SYMMETRY_BASE / source_type / ns / class_name / test_name
            if path.is_dir():
                found.append(path)
        for ns, class_name, test_name in NESTED_DATASET_ARTIFACTS:
            artifact_dir = SYMMETRY_BASE / source_type / ns / class_name / test_name
            nested = resolve_dataset_dir(artifact_dir)
            if nested is not None:
                found.append(nested)
    return found


def snapshot_markers() -> dict[Path, str | None]:
    """Marker contents for every known artifact directory, right now.

    Taken before any read-side test opens a session -- see
    ``read_artifacts/conftest.py`` for why that timing is the whole point.
    """
    return {path: read_marker(path) for path in _all_known_object_dirs()}


def replay_marker_directory(snapshot_contents: str | None, dest: Path) -> Path:
    """Build a throwaway NDI-shaped directory carrying *snapshot_contents*.

    Lets ``directorytype`` be asked what an artifact looked like AS DELIVERED,
    using the real static method rather than a reimplementation of it, even
    after the artifact on disk has been backfilled by an earlier test that
    opened it.

    Only the marker is replayed.  ``reference.txt`` is stubbed because
    ``ndi_session_dir.exists`` -- ``directorytype``'s first gate -- requires it;
    the artifact having opened as a session already established that it has one.
    """
    ndi_dir = dest / ".ndi"
    ndi_dir.mkdir(parents=True, exist_ok=True)
    (ndi_dir / "reference.txt").write_text("replay", encoding="utf-8")
    if snapshot_contents is not None:
        (ndi_dir / MARKER_FILENAME).write_text(snapshot_contents, encoding="utf-8")
    return dest


def resolve_dataset_dir(artifact_dir: Path) -> Path | None:
    """The dataset directory inside an unpacked ``downloadIngested`` artifact.

    Returns ``None`` when the artifact directory does not hold exactly one
    sub-directory, which is the same one-directory invariant both languages'
    makeArtifacts tests assert after unpacking the archive.
    """
    if not artifact_dir.is_dir():
        return None
    subdirs = [p for p in sorted(artifact_dir.iterdir()) if p.is_dir()]
    if len(subdirs) != 1:
        return None
    return subdirs[0]
