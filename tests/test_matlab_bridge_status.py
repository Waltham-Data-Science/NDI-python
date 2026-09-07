"""``status:`` uses the five documented values, and the docs say the same five.

MATLAB counterpart: none -- this checks a convention of the bridge files
themselves, so it needs no NDI-matlab checkout and runs in every job.

`status` is how a bridge entry answers *can I do this from Python, and if
not, will I ever be able to?*. It was never documented, so it grew by
precedent into six values plus an implicit default, and two of them had
stopped meaning one thing each:

* ``not_applicable`` covered three incompatible claims. ~15 of its 48
  entries said some version of "Python uses X instead" -- the capability
  EXISTS -- while others meant "MATLAB-only, never port" and three meant
  "removed upstream". A reader asking whether Python can do the thing got
  the wrong answer for the first group.
* ``not_yet_ported`` mixed deliberate deferral, blocked-on-an-external-
  toolbox, and genuinely undecided. At least one entry under it
  (``getUploadedDocumentIds``) actually meant ``ported_elsewhere``.

``implemented`` was a synonym for the ported default and ``does_not_exist``
a one-off for ``retired``. The vocabulary is now five values, defined in
section 6 of ``docs/developer_notes/ndi_matlab_python_bridge.yaml``.

WHY THE DOCS ARE CHECKED TOO, and not just the data. The previous rule in
this file family -- ``matlab_last_sync_hash`` -- was written in three
documents, drifted, and ended up with prose contradicting the command
printed beside it; 35 entries recorded the wrong KIND of hash as a result.
Documentation that no test reads is documentation that can quietly stop
being true. So the normative list is parsed out of the spec and compared
with :data:`ALLOWED`: adding a value to one without the other fails here.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The permitted ``status:`` values. Section 6 of the spec defines each.
#:
#: ``ported`` is the odd one: an entry with a ``python_path`` and NO status
#: is already ported, which is how ~460 entries spell it. Writing it out is
#: allowed where an entry benefits from saying so, so the value is legal
#: without being required.
ALLOWED = frozenset({"ported", "ported_elsewhere", "matlab_only", "porting_deferred", "retired"})

#: Values that were in use before the vocabulary was settled. Named rather
#: than merely absent so the failure can say what to use instead.
RETIRED_SPELLINGS = {
    "not_yet_ported": "porting_deferred, or ported_elsewhere if Python already does it another way",
    "not_applicable": "matlab_only, ported_elsewhere or retired -- it meant all three",
    "implemented": "nothing: drop the status, a python_path already means ported",
    "does_not_exist": "retired",
}

SPEC = REPO_ROOT / "docs" / "developer_notes" / "ndi_matlab_python_bridge.yaml"
AGENTS = REPO_ROOT / "AGENTS.md"


def bridge_files() -> list[Path]:
    """Every bridge YAML, including the three that sit under no package."""
    found = set(REPO_ROOT.glob("src/**/ndi_matlab_python_bridge.yaml"))
    found |= set(REPO_ROOT.glob("src/ndi/ndi_matlab_python_bridge_*.yaml"))
    return sorted(found)


def entries_with_status(node: Any) -> list[dict[str, Any]]:
    """Every mapping carrying a ``status:``, at any depth."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if isinstance(node.get("status"), str):
            found.append(node)
        for value in node.values():
            found.extend(entries_with_status(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(entries_with_status(item))
    return found


def documented_values() -> set[str]:
    """The vocabulary as the spec states it, from its ``# VALUES:`` line."""
    for line in SPEC.read_text(encoding="utf-8").split("\n"):
        match = re.match(r"^#\s*VALUES:\s*(.+)$", line)
        if match:
            return {value.strip() for value in match.group(1).split(",") if value.strip()}
    raise AssertionError(
        f"{SPEC.relative_to(REPO_ROOT)} has no '# VALUES:' line. That line is the "
        "machine-readable form of the normative vocabulary; without it this check "
        "cannot tell whether the documentation still matches the code."
    )


class TestTheDataUsesTheVocabulary:
    def test_every_status_is_one_of_the_five(self):
        offenders = []
        for source in bridge_files():
            data = yaml.safe_load(source.read_text(encoding="utf-8"))
            for entry in entries_with_status(data):
                status = entry["status"]
                if status in ALLOWED:
                    continue
                name = entry.get("name", "<unnamed>")
                where = source.relative_to(REPO_ROOT)
                hint = RETIRED_SPELLINGS.get(status)
                hint = f" -- use {hint}" if hint else ""
                offenders.append(f"{where}: {name} has status {status!r}{hint}")
        assert not offenders, (
            "bridge entries using a status outside the documented vocabulary:\n  "
            + "\n  ".join(offenders)
            + "\n\nThe five permitted values and how to choose between them are in "
            "section 6 of docs/developer_notes/ndi_matlab_python_bridge.yaml."
        )


class TestTheDocsAndTheCheckAgree:
    """The guard against the failure that produced 35 blob hashes: a rule
    written in prose that nothing reads, drifting from the mechanism.
    """

    def test_the_spec_documents_exactly_the_enforced_values(self):
        documented = documented_values()
        assert documented == set(ALLOWED), (
            "the spec's '# VALUES:' line and this test's ALLOWED set disagree.\n"
            f"  documented but not enforced: {sorted(documented - set(ALLOWED))}\n"
            f"  enforced but not documented: {sorted(set(ALLOWED) - documented)}\n"
            "Change both together, or the docs stop being true."
        )

    def test_the_spec_explains_each_value(self):
        """A value in the list with no prose is a name, not a definition."""
        body = SPEC.read_text(encoding="utf-8")
        section = body[body.index("# VALUES:") :]
        missing = [value for value in sorted(ALLOWED) if value not in section]
        assert not missing, f"section 6 lists but never explains: {missing}"

    def test_agents_md_carries_the_same_vocabulary(self):
        """AGENTS.md is what an agent reads first; a value it omits is a
        value the next author will not know exists."""
        body = AGENTS.read_text(encoding="utf-8")
        missing = [value for value in sorted(ALLOWED) if f"`{value}`" not in body]
        assert not missing, (
            f"AGENTS.md Rule 4 does not mention: {missing}. It carries the summary "
            "table; the definitions stay in the spec."
        )

    def test_the_retired_spellings_are_really_gone(self):
        """They are only worth naming in a failure message while nothing uses
        them; if one comes back, this file is out of date rather than right."""
        for source in bridge_files():
            data = yaml.safe_load(source.read_text(encoding="utf-8"))
            for entry in entries_with_status(data):
                assert entry["status"] not in RETIRED_SPELLINGS, (
                    f"{source.relative_to(REPO_ROOT)}: {entry.get('name')} still uses "
                    f"the retired spelling {entry['status']!r}"
                )


class TestTheGuardWouldActuallyCatchOne:
    """Passing on a clean tree is also what a check that reads nothing does."""

    @staticmethod
    def _entries(text: str):
        return entries_with_status(yaml.safe_load(text))

    def test_a_status_outside_the_vocabulary_is_visible(self):
        entries = self._entries("functions:\n  - name: someFunction\n    status: not_applicable\n")
        assert len(entries) == 1
        assert entries[0]["status"] not in ALLOWED

    def test_a_nested_entry_is_found(self):
        """Entries live at several depths; a top-level-only walk missed the
        SyncIndex methods when the completeness guard was first written."""
        entries = self._entries(
            "classes:\n"
            "  - name: SyncIndex\n"
            "    methods:\n"
            "      - name: read\n"
            "        status: porting_deferred\n"
        )
        assert [entry["name"] for entry in entries] == ["read"]

    def test_every_allowed_value_is_accepted(self):
        for value in ALLOWED:
            entries = self._entries(f"functions:\n  - name: f\n    status: {value}\n")
            assert entries[0]["status"] in ALLOWED
