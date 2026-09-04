"""Read BOTH languages' statusIcon badges with this language's decoder.

MATLAB counterpart:
    tests/+ndi/+symmetry/+readArtifacts/+gui/statusIcon.m

This is the cross-language check for the one piece of the navigator GUI that
produces a comparable artifact. A pane layout diffs against nothing, so the
rest of the port is held to unit tests plus a human eye; ``statusIcon`` is
pure, deterministic, headless, and turns a status struct into a picture, so
it can be held to the same standard as VHSB.

Three things are checked, and they fail for different reasons:

* Each language's badges are compared against a reference this battery
  renders LOCALLY from the case list. Two ports that agreed with each other
  on the wrong glyph or the wrong palette entry still go red here.
* The two languages' badges are compared to each other, pixel for pixel.
  This is the direct statement of the contract, and it gives the clearest
  failure message when the pictures genuinely differ.
* The two indexes are compared, so the languages must agree on the case set
  AND on which cases drew no badge at all. Without that second half, a
  silently-missing file and a deliberately-absent badge look identical on
  disk -- and telling those apart is exactly what ``statusIcon`` returning
  ``""`` is for.

PIXELS, NOT BYTES. MATLAB writes with ``imwrite``; this port encodes the PNG
itself with the standard library. Both are valid 8-bit RGBA PNGs of the same
picture and both are free to differ in compression level, scanline filter
choice and chunk layout. See the case module.
"""

from __future__ import annotations

from tests.symmetry.conftest import SYMMETRY_BASE, missing_artifact
from tests.symmetry.gui import status_icon_cases as cases

REL_PATH = ("gui", "statusIcon", "testStatusIconArtifacts")


def _artifact_dir(source_type: str):
    return SYMMETRY_BASE.joinpath(source_type, *REL_PATH)


def _require(source_type: str):
    d = _artifact_dir(source_type)
    if not (d / cases.INDEX_FILE).is_file():
        missing_artifact(f"{source_type} statusIcon artifacts missing. Skipping.")
    return d


def _index(source_type: str) -> dict:
    return cases.load_index(_require(source_type) / cases.INDEX_FILE)


def _check_against_expectation(source_type: str):
    """Decode every badge SOURCE_TYPE wrote and check it against local values."""
    d = _require(source_type)
    badges = _index(source_type)["badges"]

    problems = []
    for name in cases.case_names():
        path = d / f"{name}.png"
        if not cases.draws_badge(name):
            # A no-badge case must have no file, in either language.
            if path.exists():
                problems.append(f"{name}: {source_type} wrote a badge where none is expected")
            continue
        if not badges.get(name):
            problems.append(f"{name}: {source_type}'s index says it drew no badge")
            continue
        if not path.is_file():
            problems.append(f"{name}: {source_type} wrote no {name}.png")
            continue
        for problem in cases.compare_to_expectation(name, path):
            problems.append(f"{name}: {problem}")

    assert not problems, (
        f"Decoding {source_type} badges and comparing against this language's "
        "reference rendering:\n  " + "\n  ".join(problems)
    )


class TestStatusIconReadArtifacts:
    def test_python_artifacts_match_expectation(self):
        """This language checks its own badges -- a cross-run regression guard."""
        _check_against_expectation("pythonArtifacts")

    def test_matlab_artifacts_match_expectation(self):
        """THE POINT: this language decodes MATLAB's PNGs.

        A failure here means the two ports draw different pictures for the
        same status -- a different glyph, a different palette entry, a
        different composite geometry -- rather than that they merely encoded
        the same picture differently.
        """
        _check_against_expectation("matlabArtifacts")

    def test_pixels_agree_across_languages(self):
        """Compare the two languages' badges directly, pixel for pixel.

        Redundant with the two checks above only while this battery's
        reference rendering is itself correct; as a direct statement of the
        contract it is the check that says what actually broke.
        """
        ml = _require("matlabArtifacts")
        py = _require("pythonArtifacts")

        problems = []
        for name in cases.case_names():
            if not cases.draws_badge(name):
                continue
            a, b = ml / f"{name}.png", py / f"{name}.png"
            if not (a.is_file() and b.is_file()):
                problems.append(
                    f"{name}: missing on one side (matlab={a.is_file()}, python={b.is_file()})"
                )
                continue
            for problem in cases.compare_files(a, b):
                problems.append(f"{name}: matlab vs python: {problem}")

        assert not problems, "The two ports drew different badges:\n  " + "\n  ".join(problems)

    def test_case_sets_agree(self):
        """Both sides must have written the same cases.

        Without this, each language could check its own files happily while
        silently covering a different battery.
        """
        ml, py = _index("matlabArtifacts"), _index("pythonArtifacts")
        assert sorted(ml["cases"]) == sorted(
            py["cases"]
        ), "MATLAB and Python wrote different statusIcon case sets."
        assert sorted(py["cases"]) == cases.case_names()

    def test_no_badge_cases_agree(self):
        """The two languages must agree on which cases drew nothing.

        A missing file and an absent badge are the same thing on disk, so
        without the index a port that silently stopped rendering a case would
        read as a port that correctly declined to.
        """
        ml, py = _index("matlabArtifacts"), _index("pythonArtifacts")
        ml_badges, py_badges = ml["badges"], py["badges"]

        expected = {name: cases.draws_badge(name) for name in cases.case_names()}
        for source, badges in (("matlab", ml_badges), ("python", py_badges)):
            got = {name: bool(badges.get(name, False)) for name in cases.case_names()}
            assert got == expected, (
                f"{source} disagrees with the battery about which cases draw a badge: "
                f"{sorted(k for k in expected if got.get(k) != expected[k])}"
            )

    def test_badge_versions_agree(self):
        """A one-sided BADGE_VERSION bump means one cache key, two pictures."""
        ml, py = _index("matlabArtifacts"), _index("pythonArtifacts")
        assert ml.get("badgeVersion") == py.get("badgeVersion") == cases.EXPECTED_BADGE_VERSION, (
            f"BADGE_VERSION diverged: matlab={ml.get('badgeVersion')!r}, "
            f"python={py.get('badgeVersion')!r}, battery expects "
            f"{cases.EXPECTED_BADGE_VERSION!r}."
        )
