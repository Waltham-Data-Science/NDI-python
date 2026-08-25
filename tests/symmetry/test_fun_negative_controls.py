"""Negative controls for the ``fun`` symmetry comparison.

A symmetry suite's real failure mode is not a red test -- it is a green one that
compared nothing, or compared two things that could not have differed.  These
tests hold the comparison itself against a MATLAB-SHAPED CLONE of Python's own
artifact and prove three things about it:

* **it agrees with itself** -- the clone, after being pushed through the shapes
  ``jsonencode`` actually produces, still joins 1:1 and compares equal.  Without
  this the other two controls could pass for the wrong reason.
* **it detects a perturbation** -- change one compared value in the clone and the
  comparison must say so.  A comparison that cannot fail is not evidence.
* **it does not accept silence** -- delete a case from the clone and the
  comparison must report it missing rather than skip past it.

Plus the allow-list controls, which are the same idea applied to the escape
hatch: an allow-listed case must be allowed to differ, and an allow-listed case
that has STOPPED differing must be reported as one to delete.

These tests are deliberately NOT under ``read_artifacts/``.  They build their own
clone in ``tmp_path`` and depend on no artifact directory, so they must not be
counted among the tests that ``NDI_SYMMETRY_REQUIRE_ARTIFACTS=1`` turns red on an
empty artifact root -- a test that passes there would be a hole in exactly the
guarantee that flag exists to give.

THE MATLAB-SHAPED CLONE
``jsonencode`` collapses a one-element ``double`` array to a bare number and an
empty one to ``[]``.  ``cases`` is a cell of structs on the MATLAB side precisely
so it cannot collapse, and every compared value is already a rendered string, so
the collapse only reaches two fields: ``inputCodepoints`` and
``elementLegacyDirNameCodepoints`` (the ``astralOnlyEmoji`` case has exactly one
of each).  :func:`_matlab_shaped` reproduces that collapse, so the clone
exercises the one piece of shape normalization the canonical grammar does not
remove.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from tests.symmetry._fun_cases import (
    audit_known_divergences,
    compare_maps,
    envelope,
    envelope_problems,
    index_by_name,
    known_divergences,
    load_cases,
    load_payload,
    path_safe_signature,
    run_path_safe_name_cases,
    run_what_varies_cases,
    what_varies_signature,
    write_cases,
)

_COLLAPSIBLE = ("inputCodepoints", "elementLegacyDirNameCodepoints")


def _matlab_shaped(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Push *cases* through the shapes MATLAB's ``jsonencode`` would produce."""
    out = copy.deepcopy(cases)
    for case in out:
        for field in _COLLAPSIBLE:
            value = case.get(field)
            if isinstance(value, list) and len(value) == 1:
                case[field] = value[0]
    return out


def _write_clone(tmp_path, cases, name: str):
    """Write a MATLAB-shaped clone artifact and read it back through the real
    loader, so the controls run against decoded JSON rather than live objects."""
    payload = envelope("cloned for a negative control", "negative-control clone", cases)
    payload["language"] = "matlab"
    artifact = write_cases(tmp_path / name, "cases.json", payload)
    return artifact


class TestClonedArtifactCrossCheck:
    """The comparison agrees with a MATLAB-shaped clone of Python's own output."""

    def test_path_safe_name_clone_agrees(self, tmp_path):
        fresh = run_path_safe_name_cases()
        artifact = _write_clone(tmp_path, _matlab_shaped(fresh), "psn")

        clone = index_by_name(load_cases(artifact))
        python = index_by_name(fresh)

        assert clone.keys() == python.keys()
        assert len(clone) == 22
        problems, _ = compare_maps(clone, python, "clone vs python", path_safe_signature)
        assert not problems, "\n".join(problems)

    def test_path_safe_name_clone_really_carried_a_collapsed_field(self, tmp_path):
        """The clone must actually exercise the collapse, or the control above is
        testing a shape that never occurs."""
        artifact = _write_clone(tmp_path, _matlab_shaped(run_path_safe_name_cases()), "psn-shape")
        raw = json.loads(artifact.read_text(encoding="utf-8"))
        astral = index_by_name(raw["cases"])["astralOnlyEmoji"]
        assert astral["inputCodepoints"] == 127881, "the 1x1 collapse was not reproduced"
        assert astral["elementLegacyDirNameCodepoints"] == 127881
        # ...and the comparison still reads it as the one-element list it is.
        assert "legacyCodepoints=[127881]" in path_safe_signature(astral)

    def test_what_varies_clone_agrees(self, tmp_path):
        fresh = run_what_varies_cases()
        artifact = _write_clone(tmp_path, _matlab_shaped(fresh), "wv")

        clone = index_by_name(load_cases(artifact))
        python = index_by_name(fresh)

        assert clone.keys() == python.keys()
        assert len(clone) == 18
        problems, reports = compare_maps(
            clone, python, "clone vs python", what_varies_signature, known_divergences()
        )
        assert not problems, "\n".join(problems)
        assert not reports, "a clone of Python's own artifact cannot diverge from it"

    def test_clone_envelope_is_well_formed(self, tmp_path):
        artifact = _write_clone(tmp_path, _matlab_shaped(run_what_varies_cases()), "env")
        assert not envelope_problems(load_payload(artifact), expected_language="matlab")


class TestPerturbationIsDetected:
    """Change one compared value and the comparison must say so."""

    def test_path_safe_name_perturbation(self, tmp_path):
        fresh = run_path_safe_name_cases()
        perturbed = _matlab_shaped(fresh)
        target = index_by_name(perturbed)["elementBarSeparator"]
        assert target["pathSafeName"] == "probe_-_1"
        target["pathSafeName"] = "probe_|_1"  # the very bug the sanitizer exists for

        artifact = _write_clone(tmp_path, perturbed, "psn-bad")
        problems, _ = compare_maps(
            index_by_name(load_cases(artifact)),
            index_by_name(fresh),
            "clone vs python",
            path_safe_signature,
        )
        assert len(problems) == 1, problems
        assert "elementBarSeparator" in problems[0]

    def test_path_safe_name_codepoint_perturbation(self, tmp_path):
        """A legacy name that differs only in a codepoint -- the case the
        signature carries codepoints for, rather than the decoded text, so that
        no JSON text-encoding difference can masquerade as a behaviour one."""
        fresh = run_path_safe_name_cases()
        perturbed = _matlab_shaped(fresh)
        target = index_by_name(perturbed)["astralUnicodeEmoji"]
        target["elementLegacyDirNameCodepoints"] = [97, 128512, 99]

        artifact = _write_clone(tmp_path, perturbed, "psn-cp")
        problems, _ = compare_maps(
            index_by_name(load_cases(artifact)),
            index_by_name(fresh),
            "clone vs python",
            path_safe_signature,
        )
        assert len(problems) == 1 and "astralUnicodeEmoji" in problems[0]

    def test_what_varies_value_perturbation(self, tmp_path):
        fresh = run_what_varies_cases()
        perturbed = _matlab_shaped(fresh)
        target = index_by_name(perturbed)["stimuliStructArray"]
        assert target["variesValues"] == ["[0, 90, 180]"]
        target["variesValues"] = ["[0, 90]"]

        artifact = _write_clone(tmp_path, perturbed, "wv-bad")
        problems, _ = compare_maps(
            index_by_name(load_cases(artifact)),
            index_by_name(fresh),
            "clone vs python",
            what_varies_signature,
            known_divergences(),
        )
        assert len(problems) == 1 and "stimuliStructArray" in problems[0]

    def test_what_varies_input_perturbation(self, tmp_path):
        """``inputRendered`` is compared on purpose: it is the only thing that
        catches the two hand-written batteries drifting apart. Without it the
        suite could go green while silently comparing two different inputs."""
        fresh = run_what_varies_cases()
        perturbed = _matlab_shaped(fresh)
        target = index_by_name(perturbed)["cellOfParameterStructs"]
        target["inputRendered"] = "[{angle: 0, contrast: 1}, {angle: 45, contrast: 1}]"

        artifact = _write_clone(tmp_path, perturbed, "wv-input")
        problems, _ = compare_maps(
            index_by_name(load_cases(artifact)),
            index_by_name(fresh),
            "clone vs python",
            what_varies_signature,
            known_divergences(),
        )
        assert len(problems) == 1 and "cellOfParameterStructs" in problems[0]

    def test_what_varies_status_perturbation(self, tmp_path):
        """Only the FACT of an error is symmetric -- but it IS symmetric."""
        fresh = run_what_varies_cases()
        perturbed = _matlab_shaped(fresh)
        target = index_by_name(perturbed)["badInputNumeric"]
        assert target["status"] == "error"
        target["status"] = "ok"

        artifact = _write_clone(tmp_path, perturbed, "wv-status")
        problems, _ = compare_maps(
            index_by_name(load_cases(artifact)),
            index_by_name(fresh),
            "clone vs python",
            what_varies_signature,
            known_divergences(),
        )
        assert len(problems) == 1 and "badInputNumeric" in problems[0]

    def test_error_identifier_and_message_are_not_compared(self, tmp_path):
        """The complement of the control above: rewriting the identifier and the
        message to MATLAB's spelling must NOT be a mismatch, or the symmetry test
        would be a translation table instead of a behaviour check."""
        fresh = run_what_varies_cases()
        rewritten = _matlab_shaped(fresh)
        target = index_by_name(rewritten)["badCellEntry"]
        target["identifier"] = "ndi:fun:stimulus:whatVaries_parameterList:badCellEntry"
        target["message"] = "Each cell entry must be an ndi.document or a parameter struct."
        # ...as are the humans-only fields.
        target["shape"] = "somethingElse"
        target["mirrors"] = "somethingElse"

        artifact = _write_clone(tmp_path, rewritten, "wv-ident")
        problems, _ = compare_maps(
            index_by_name(load_cases(artifact)),
            index_by_name(fresh),
            "clone vs python",
            what_varies_signature,
            known_divergences(),
        )
        assert not problems, "\n".join(problems)


class TestMissingCaseCannotBeSettledBySilence:
    """Delete a case and the comparison must report it, not skip past it."""

    def test_path_safe_name_missing_case_is_reported(self, tmp_path):
        fresh = run_path_safe_name_cases()
        clone_cases = [c for c in _matlab_shaped(fresh) if c["name"] != "astralThenTrailingDot"]
        artifact = _write_clone(tmp_path, clone_cases, "psn-missing")

        clone = index_by_name(load_cases(artifact))
        python = index_by_name(fresh)

        # Iterating the SHORTER side is the trap: the clone's 21 cases all agree.
        problems, _ = compare_maps(clone, python, "clone vs python", path_safe_signature)
        assert not problems, "the short side agrees with itself, as expected"

        # Iterating the full side is what catches it.
        problems, _ = compare_maps(python, clone, "python vs clone", path_safe_signature)
        assert len(problems) == 1
        assert "astralThenTrailingDot" in problems[0] and "missing" in problems[0]

        # ...and so does the key-set comparison the read side asserts first.
        assert python.keys() != clone.keys()
        assert python.keys() - clone.keys() == {"astralThenTrailingDot"}

    def test_what_varies_missing_case_is_reported(self, tmp_path):
        fresh = run_what_varies_cases()
        clone_cases = [
            c for c in _matlab_shaped(fresh) if c["name"] != "vectorValuedVaryingParameter"
        ]
        artifact = _write_clone(tmp_path, clone_cases, "wv-missing")

        clone = index_by_name(load_cases(artifact))
        python = index_by_name(fresh)

        problems, _ = compare_maps(
            python, clone, "python vs clone", what_varies_signature, known_divergences()
        )
        assert len(problems) == 1
        assert "vectorValuedVaryingParameter" in problems[0] and "missing" in problems[0]

    def test_an_allow_listed_case_may_not_be_settled_by_silence_either(self, tmp_path):
        """A missing allow-listed case is still a missing case.

        The allow-list says the two languages may DISAGREE about this case. It
        does not say one of them may decline to run it -- an omitted case
        produces no evidence either way, and the audit that is supposed to notice
        the divergence going away would have nothing to look at.
        """
        fresh = run_what_varies_cases()
        clone_cases = [c for c in _matlab_shaped(fresh) if c["name"] != "allNaNParameter"]
        artifact = _write_clone(tmp_path, clone_cases, "wv-missing-allowed")

        clone = index_by_name(load_cases(artifact))
        python = index_by_name(fresh)

        problems, _ = compare_maps(
            python, clone, "python vs clone", what_varies_signature, known_divergences()
        )
        # compare_maps checks presence BEFORE consulting the allow-list.
        assert len(problems) == 1 and "allNaNParameter" in problems[0]

        _, live = audit_known_divergences(clone, python)
        assert any("not present in both artifacts" in line for line in live)


class TestAllowListSemantics:
    """The escape hatch must open, and must announce when it is no longer needed."""

    def test_an_allow_listed_divergence_is_reported_not_failed(self, tmp_path):
        fresh = run_what_varies_cases()
        diverged = _matlab_shaped(fresh)
        # What MATLAB main is predicted to do: report the all-NaN parameter as
        # varying rather than constant.
        target = index_by_name(diverged)["allNaNParameter"]
        target["variesParameters"] = ["angle"]
        target["variesValues"] = ["[NaN]"]
        target["constantParameters"] = ["contrast"]
        target["constantValues"] = ["1"]
        target["whatIsConstantRendered"] = "[{parameter: 'contrast', value: 1}]"

        artifact = _write_clone(tmp_path, diverged, "wv-diverged")
        clone = index_by_name(load_cases(artifact))
        python = index_by_name(fresh)

        problems, reports = compare_maps(
            clone, python, "clone vs python", what_varies_signature, known_divergences()
        )
        assert not problems, "\n".join(problems)
        assert any("allNaNParameter" in line for line in reports)

        stale, live = audit_known_divergences(clone, python)
        assert any("allNaNParameter" in line for line in live)
        assert not any("allNaNParameter" in line for line in stale)

    def test_the_same_perturbation_off_the_allow_list_fails(self, tmp_path):
        """The allow-list must be doing the work, not the comparison being weak."""
        fresh = run_what_varies_cases()
        diverged = _matlab_shaped(fresh)
        target = index_by_name(diverged)["allNaNParameter"]
        target["variesParameters"] = ["angle"]
        target["variesValues"] = ["[NaN]"]

        artifact = _write_clone(tmp_path, diverged, "wv-diverged-strict")
        problems, _ = compare_maps(
            index_by_name(load_cases(artifact)),
            index_by_name(fresh),
            "clone vs python",
            what_varies_signature,
            allowed_divergences=(),
        )
        assert len(problems) == 1 and "allNaNParameter" in problems[0]

    def test_a_divergence_that_started_agreeing_is_reported_as_delete_the_entry(self, tmp_path):
        """A clone of Python's own artifact agrees on the allow-listed cases by
        construction, which is exactly the state the audit must flag: a listed
        case that no longer diverges means the upstream fix landed and the entry
        is now silencing nothing while looking like it silences something."""
        fresh = run_what_varies_cases()
        artifact = _write_clone(tmp_path, _matlab_shaped(fresh), "wv-agreeing")

        stale, live = audit_known_divergences(
            index_by_name(load_cases(artifact)), index_by_name(fresh)
        )

        assert not live
        assert len(stale) == len(known_divergences()) == 2
        for name in known_divergences():
            line = next(entry for entry in stale if name in entry)
            assert "now AGREES" in line
            assert "DELETE THE ALLOW-LIST ENTRY" in line
