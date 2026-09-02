"""Write this language's ``element.ndi_element_class`` artifacts.

Python equivalent of:
    tests/+ndi/+symmetry/+makeArtifacts/+element/elementClass.m

Builds a session holding one element of each element class
(:mod:`tests.symmetry.element.element_class_cases`) and publishes it, together
with a transcript of what this language's ``getelements`` makes of it, under

    <tempdir>/NDI/symmetryTest/pythonArtifacts/element/elementClass/
             testElementClassArtifacts/

The MATLAB ``readArtifacts`` counterpart opens that session and rebuilds the
elements from it. Every element is read back HERE first, so a generator that
writes an unreadable session fails in this test rather than looking like a
cross-language divergence later.
"""

from __future__ import annotations

import shutil

import pytest

from ndi.element import ndi_element
from ndi.element_timeseries import ndi_element_timeseries
from ndi.neuron import ndi_neuron
from ndi.session.dir import ndi_session_dir
from ndi.subject import ndi_subject
from tests.symmetry.conftest import PYTHON_ARTIFACTS
from tests.symmetry.element import element_class_cases as cases

ARTIFACT_DIR = PYTHON_ARTIFACTS / "element" / "elementClass" / "testElementClassArtifacts"

#: The Python class that writes each case, keyed by the class name it records.
BUILDERS = {
    "ndi.element": ndi_element,
    "ndi.element.timeseries": ndi_element_timeseries,
    "ndi.neuron": ndi_neuron,
}


class TestElementClass:
    """Mirror of ndi.symmetry.makeArtifacts.element.elementClass."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        session_dir = tmp_path / cases.SESSION_REFERENCE
        session_dir.mkdir()
        session = ndi_session_dir(cases.SESSION_REFERENCE, session_dir)
        session.cache.clear()

        subject_doc = ndi_subject(cases.SUBJECT_NAME, "").newdocument()
        session.database_add(subject_doc)

        for case in cases.CASES:
            cls = BUILDERS[case["ndi_element_class"]]
            kwargs = {
                "session": session,
                "name": case["name"],
                "reference": case["reference"],
                "subject_id": subject_doc.id,
                # direct=False, with no underlying element, is what MATLAB's
                # maker builds (its ndi.element validates the pair); the flag
                # is not part of the transcript, but the two sessions should
                # differ in nothing that is avoidable.
                "direct": False,
            }
            # ndi_neuron fixes type='neuron' itself and takes no type argument,
            # exactly as MATLAB's ndi.neuron does.
            if cls is not ndi_neuron:
                kwargs["type"] = case["type"]
            session.database_add(cls(**kwargs).newdocument())

        self.session = session
        self.session_path = session_dir
        # No teardown -- the artifacts must persist for readArtifacts.

    def test_element_class_artifacts(self):
        """Publish the session and the transcript of reading it back."""
        # Re-open so nothing is served out of the writing session's cache: the
        # readers get a cold database, and so should the transcript.
        session = ndi_session_dir(cases.SESSION_REFERENCE, self.session_path)
        observations = cases.observe(session.getelements())

        problems = cases.compare(observations)
        assert not problems, (
            "Python could not read back the element classes it just wrote, so there is "
            "nothing worth publishing:\n  " + "\n  ".join(problems)
        )

        if ARTIFACT_DIR.exists():
            shutil.rmtree(ARTIFACT_DIR)
        shutil.copytree(str(self.session_path), str(ARTIFACT_DIR))
        index_path = cases.write_index(ARTIFACT_DIR, observations)

        assert index_path.is_file()
        assert (ARTIFACT_DIR / ".ndi").is_dir(), "the session database was not published"
