"""Rebuild BOTH languages' elements with this language's reader.

Python equivalent of:
    tests/+ndi/+symmetry/+readArtifacts/+element/elementClass.m

The cross-language check that matters here is not that the two languages spell
the class names the same way -- it is that each one can rebuild what the other
wrote. Issue #133 is the proof: Python could not reconstruct a MATLAB-written
``ndi.neuron`` at all, and because ``getelements`` swallowed the failure, the
symptom was an empty list rather than an error.

So each test opens a session directory produced by one language's
``makeArtifacts`` suite, calls ``getelements``, and checks the class of every
object that comes back against the shared case list -- computed locally, not
read out of the artifact.
"""

from __future__ import annotations

import pytest

from ndi.session.dir import ndi_session_dir
from tests.symmetry.conftest import SOURCE_TYPES, SYMMETRY_BASE, missing_artifact
from tests.symmetry.element import element_class_cases as cases

REL_PATH = ("element", "elementClass", "testElementClassArtifacts")


@pytest.fixture(params=SOURCE_TYPES)
def source_type(request):
    """Parameterize over matlabArtifacts / pythonArtifacts."""
    return request.param


class TestElementClass:
    """Mirror of ndi.symmetry.readArtifacts.element.elementClass."""

    def _artifact_dir(self, source_type: str):
        return SYMMETRY_BASE.joinpath(source_type, *REL_PATH)

    def _open_session(self, source_type: str):
        d = self._artifact_dir(source_type)
        if not (d / cases.INDEX_FILE).is_file():
            missing_artifact(
                f"{source_type} element-class artifacts missing. "
                "Run the corresponding makeArtifacts suite first."
            )
        return d, ndi_session_dir(cases.SESSION_REFERENCE, d)

    def test_elements_rebuild_as_the_class_that_wrote_them(self, source_type):
        """THE POINT: every element comes back as its own class, not the base one."""
        _, session = self._open_session(source_type)

        observations = cases.observe(session.getelements())
        problems = cases.compare(observations)
        assert (
            not problems
        ), f"Rebuilding {source_type} elements with this language's reader:\n  " + "\n  ".join(
            problems
        )

    def test_transcript_agrees_with_this_language(self, source_type):
        """The writer's own reading of the session must match this reader's.

        A difference here means the two languages disagree about the same
        database, which is narrower information than the test above and worth
        separating from it.
        """
        artifact_dir, session = self._open_session(source_type)

        stored = cases.load_index(artifact_dir / cases.INDEX_FILE)
        assert stored["sessionReference"] == cases.SESSION_REFERENCE

        problems = cases.compare_lists(cases.observe(session.getelements()), stored["elements"])
        assert not problems, (
            f"this reader and the {source_type} writer disagree about the same session:\n  "
            + "\n  ".join(problems)
        )
