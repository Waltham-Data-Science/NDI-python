"""Fixtures shared by the read-side symmetry tests.

Holds one thing, and it exists to close a hole rather than to save typing.

``object_type_marker_snapshot`` records the state of every artifact's
``.ndi/ndi_object_type.txt`` ONCE, before the first read-side test runs.  It has
to, because opening an NDI directory BACKFILLS the marker -- both languages do
this deliberately so legacy directories migrate on first open -- and several
read tests open sessions from ``matlabArtifacts``.  Whichever of those runs
first would write a Python marker into the MATLAB artifact, after which
``read_artifacts/*/test_object_type_marker.py`` would be reading Python's own
handiwork and calling it cross-language agreement.

A session-scoped autouse fixture in *this* directory is the right place for the
snapshot: it fires at the first ``read_artifacts`` test, which is after the
``make_artifacts`` tests have produced their artifacts (make sorts before read)
and before any read test has opened anything.
"""

import pytest

from tests.symmetry._object_type_marker import snapshot_markers


@pytest.fixture(scope="session", autouse=True)
def object_type_marker_snapshot():
    """Marker contents for every known artifact, captured before any read test.

    Maps the artifact directory (as a ``Path``) to the raw marker contents, or
    to ``None`` when the directory exists but carries no marker.  Directories
    that do not exist at all are absent from the mapping.
    """
    return snapshot_markers()
