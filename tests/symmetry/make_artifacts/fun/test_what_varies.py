"""Generate the whatVaries / whatIsConstant symmetry artifact (fun namespace).

Python counterpart of MATLAB
``tests/+ndi/+symmetry/+makeArtifacts/+fun/whatVaries.m``.  Runs the shared
``tests/symmetry/_fun_cases`` battery through the real
``ndi.fun.stimulus.whatVaries`` / ``whatIsConstant`` and writes::

    <tempdir>/NDI/symmetryTest/pythonArtifacts/fun/whatVaries/
             testWhatVariesArtifacts/whatVariesCases.json

The 18 cases mirror the 17 test methods of MATLAB
``tests/+ndi/+unittest/+fun/+stimulus/whatVariesTest.m`` -- 15 with a distinct
input, plus the two assertions of ``testBadInputErrors`` split into their own
rows -- plus one all-NaN probe added to pin a suspected cross-language
divergence.  ``testWhatIsConstantMatchesSecondOutput`` contributes no distinct
input: it is checked on EVERY case by the ``whatIsConstantRendered`` field.

WHY THIS GENERATOR RECORDS ERRORS INSTEAD OF FAILING ON THEM
Unlike its pathSafeName sibling, a case that raises is recorded as
``{"status": "error", ...}`` rather than failing the generator.  That is
deliberate: MATLAB main is expected to throw on the cell-valued-constant case
(``local_varyingFields`` compares with ``vlt.data.eqlen``, which bottoms out in a
bare ``==``, and ``==`` is undefined for two cell arrays), and a generator that
died there would write NO artifact at all -- costing the symmetry suite every
other case's coverage to report one already-known bug.  The error is not
swallowed: it is recorded in the artifact and asserted against the other language
in ``read_artifacts/fun/test_what_varies.py``, where the two can actually be held
against each other.

Python still asserts all 18 cases against its own reference expectations here.
MATLAB skips its two ``divergenceExpected`` cases in the equivalent check because
it has no measurement to check them against; this side does have one, so the
allow-list governs only the cross-language comparison, never Python's self-check.
"""

import json

from tests.symmetry._fun_cases import (
    WHAT_VARIES_DEFS,
    envelope,
    index_by_name,
    known_divergences,
    run_what_varies_cases,
    verify_what_varies_expected,
    write_cases,
)
from tests.symmetry.conftest import PYTHON_ARTIFACTS

ARTIFACT_DIR = PYTHON_ARTIFACTS / "fun" / "whatVaries" / "testWhatVariesArtifacts"
ARTIFACT_FILE = ARTIFACT_DIR / "whatVariesCases.json"

DESCRIPTION = "ndi.fun.stimulus.whatVaries / whatIsConstant symmetry cases"
GENERATOR = "tests.symmetry.make_artifacts.fun.test_what_varies"


def generate() -> list:
    """Run the battery, verify it, and write the artifact."""
    results = run_what_varies_cases()

    problems = verify_what_varies_expected(results)
    assert not problems, "whatVaries reference mismatches:\n" + "\n".join(problems)

    write_cases(ARTIFACT_DIR, ARTIFACT_FILE.name, envelope(DESCRIPTION, GENERATOR, results))
    return results


class TestWhatVaries:
    """Mirror of ndi.symmetry.makeArtifacts.fun.whatVaries."""

    def test_what_varies_artifacts(self, capsys):
        results = generate()

        assert ARTIFACT_FILE.exists()
        assert len(results) == 18, f"expected 18 recorded cases, got {len(results)}"

        names = [case["name"] for case in results]
        assert len(set(names)) == len(names), f"duplicate whatVaries case names: {names}"
        assert names == [d[0] for d in WHAT_VARIES_DEFS]

        # Make every recorded error visible even though none of them fails this
        # test -- the same reporting the MATLAB generator does.
        divergent = set(known_divergences())
        errored = [case for case in results if case["status"] == "error"]
        with capsys.disabled():
            for case in errored:
                note = (
                    "predicted divergence"
                    if case["name"] in divergent
                    else "expected by the battery"
                )
                print(
                    f"whatVaries case {case['name']!r} ERRORED ({note}): "
                    f"{case['identifier']} -- {case['message']}"
                )
            print(
                f"whatVaries battery: {len(errored)} of {len(results)} cases "
                "recorded status 'error'."
            )

        # The two bad-input rows are the only errors Python is expected to
        # record. The two allow-listed cases are where MATLAB is predicted to
        # throw and Python is predicted to succeed -- if Python starts throwing
        # on one of them, the divergence has changed shape and the allow-list no
        # longer describes it.
        assert [case["name"] for case in errored] == ["badInputNumeric", "badCellEntry"]

    def test_known_divergence_cases_are_declared_on_both_sides(self):
        """Every allow-listed name must exist in the case list, and vice versa.

        An allow-list entry naming a case that is not in the battery silences
        nothing and hides that it silences nothing; a ``divergence_expected``
        flag with no allow-list entry means the read side will hard-fail on a
        case the battery says is allowed to differ.  Either way the two lists
        have drifted, which is the failure mode the allow-list itself is meant to
        make visible.
        """
        names = {d[0] for d in WHAT_VARIES_DEFS}
        flagged = {d[0] for d in WHAT_VARIES_DEFS if d[8]}
        listed = set(known_divergences())
        assert listed <= names, f"allow-list names not in the battery: {sorted(listed - names)}"
        assert flagged == listed, (
            "divergence_expected flags and known_divergences() disagree: "
            f"flagged-only={sorted(flagged - listed)} listed-only={sorted(listed - flagged)}"
        )

    def test_artifact_reparses_as_strict_json(self):
        """The written file must be readable by MATLAB's ``jsondecode``.

        ``json.loads`` accepts the non-standard ``NaN`` / ``Infinity`` tokens by
        default, so only a ``parse_constant`` hook proves the file is portable
        JSON.  Under the canonical grammar an all-NaN case travels as the
        *string* ``'NaN'`` inside a rendered value, which is why the
        pre-contract ``"__NaN__"`` sentinel is gone: a hit here means some value
        reached the encoder without being rendered.
        """
        generate()
        raw = ARTIFACT_FILE.read_text(encoding="utf-8")

        def _reject(token):
            raise AssertionError(
                f"the artifact contains the non-standard JSON token {token!r}; "
                "MATLAB's jsondecode rejects it, and under the canonical grammar "
                "no non-finite number should ever reach the encoder."
            )

        payload = json.loads(raw, parse_constant=_reject)

        assert payload["schemaVersion"] == 1
        assert payload["language"] == "python"
        assert payload["description"] == DESCRIPTION
        assert payload["generator"] == GENERATOR
        assert isinstance(payload["cases"], list)

        required = (
            "name",
            "status",
            "identifier",
            "message",
            "shape",
            "mirrors",
            "excludeBlank",
            "inputRendered",
            "variesParameters",
            "variesValues",
            "constantParameters",
            "constantValues",
            "whatIsConstantRendered",
        )
        for case in payload["cases"]:
            missing = [field for field in required if field not in case]
            assert not missing, f"case {case.get('name')!r} is missing fields {missing}"
            # Parallel arrays, always. A varies/values pair of different lengths
            # would make the signature meaningless rather than merely wrong.
            assert len(case["variesParameters"]) == len(case["variesValues"])
            assert len(case["constantParameters"]) == len(case["constantValues"])

        by_name = index_by_name(payload["cases"])
        # NaN reached the artifact as a rendered token inside a string, in
        # MATLAB's spelling -- not as `null`, not as the bare `NaN` token.
        assert by_name["allNaNParameter"]["constantValues"] == ["NaN", "1"]
        assert "NaN" in by_name["allNaNParameter"]["inputRendered"]
        # A single distinct value still brackets: [5], never 5.
        assert by_name["fieldPresentInSomeStimuli"]["variesValues"] == ["[5]"]
