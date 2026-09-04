"""Shared ``element.ndi_element_class`` battery, defined identically in both languages.

MATLAB counterpart: tests/+ndi/+symmetry/+element/elementClassCases.m

WHAT CROSSES THE LANGUAGE BOUNDARY
An element document records the name of the class that wrote it, in
``element.ndi_element_class``. That string is the only thing telling a reader
what to rebuild: MATLAB calls ``feval`` on it
(``+ndi/+database/+fun/ndi_document2ndi_object.m``) and Python looks it up in
:mod:`ndi.class_registry`. So each language writes a session containing one
element of each kind, and the other language opens that session, asks it for
its elements, and checks that each one came back as the class that wrote it.

WHY IT IS A SESSION AND NOT A JSON TRANSCRIPT
The transcript is written too, but it is the weaker half. Comparing two
transcripts would only show that both languages spell the class names the same
way; it would not have caught issue #133, where Python spelled ``ndi.neuron``
correctly nowhere and could not rebuild a MATLAB-written neuron at all --
``getelements`` returned an empty list and said nothing. What pins that is one
language reading the OTHER language's database and getting objects back.

THE ASSERTION IS ON THE REBUILT OBJECT, NOT THE STORED STRING
Each side reports ``class(obj)`` / ``obj.ndi_element_class()`` of what
``getelements`` handed it. Reading the string straight out of the document
would pass even if the reader silently downgraded every element to the base
class -- which is exactly the failure this battery exists to catch.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: Written next to the session copy by each side's makeArtifacts test.
INDEX_FILE = "elementClasses.json"

#: The session reference both languages build under.
SESSION_REFERENCE = "elementclass1"

#: The subject both languages hang the elements off.
SUBJECT_NAME = "anteater27@nosuchlab.org"

#: One element per element class that can be written to an element document,
#: with the class name it must carry. The MATLAB name is the contract on both
#: sides: ``+ndi/element.m`` stores ``class(ndi_element_obj)``.
CASES: list[dict[str, Any]] = [
    {
        "name": "elec1",
        "reference": 1,
        "type": "n-trode",
        "ndi_element_class": "ndi.element",
        "note": "The base class. It is here as the control: if a reader "
        "downgrades everything to ndi.element, this case still passes and "
        "the other two fail, which distinguishes a broken reader from a "
        "broken writer.",
    },
    {
        "name": "ts1",
        "reference": 1,
        "type": "spikes",
        "ndi_element_class": "ndi.element.timeseries",
        "note": "Python wrote this as 'ndi.element' until issue #133, because "
        "ndi_element_timeseries did not override ndi_element_class(), so it "
        "round-tripped without readtimeseries -- the one method the class "
        "exists for.",
    },
    {
        "name": "neuron1",
        "reference": 1,
        "type": "neuron",
        "ndi_element_class": "ndi.neuron",
        "note": "The case that lost data in both directions (issue #133). "
        "Python wrote neurons labelled 'ndi.element'; and 'ndi.neuron', which "
        "is what MATLAB writes, was in no registry, so every MATLAB-written "
        "neuron was dropped from getelements without a word.",
    },
]


def case_names() -> list[str]:
    """The element names, in the order they are built."""
    return [c["name"] for c in CASES]


def expected() -> list[dict[str, Any]]:
    """The expected observation for each case: name, reference, type, class."""
    return [{k: c[k] for k in ("name", "reference", "type", "ndi_element_class")} for c in CASES]


def observe(elements: list[Any]) -> list[dict[str, Any]]:
    """Reduce ``getelements`` output to the transcript both languages write.

    ``ndi_element_class()`` is asked of the OBJECT, so what is recorded is the
    class the reader actually built -- not the string it read out of the
    document.
    """
    observations = [
        {
            "name": e.name,
            "reference": int(e.reference),
            "type": e.type,
            "ndi_element_class": e.ndi_element_class(),
        }
        for e in elements
    ]
    return sorted(observations, key=lambda o: o["name"])


def write_index(dest: Path, observations: list[dict[str, Any]]) -> Path:
    """Write this language's transcript beside its session copy."""
    path = Path(dest) / INDEX_FILE
    path.write_text(
        json.dumps(
            {
                "sessionReference": SESSION_REFERENCE,
                "elements": observations,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def load_index(path: Path) -> dict[str, Any]:
    """Read a transcript written by either language."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def compare(observations: list[dict[str, Any]]) -> list[str]:
    """Every difference between OBSERVATIONS and the shared case list."""
    return compare_lists(observations, expected())


def compare_lists(observations: list[dict[str, Any]], want: list[dict[str, Any]]) -> list[str]:
    """Every difference between two observation lists, by element name.

    Returns a list of human-readable problems; empty means agreement.
    """
    problems: list[str] = []
    expected_by_name = {c["name"]: c for c in want}
    seen = {o["name"] for o in observations}

    for name in sorted(set(expected_by_name) - seen):
        problems.append(
            f"{name}: no element of this name came back from getelements "
            f"(expected {expected_by_name[name]['ndi_element_class']}). An element that "
            "cannot be reconstructed is dropped, which is how issue #133 stayed invisible."
        )
    for name in sorted(seen - set(expected_by_name)):
        problems.append(f"{name}: unexpected extra element")

    for obs in sorted(observations, key=lambda o: o["name"]):
        exp = expected_by_name.get(obs["name"])
        if exp is None:
            continue
        for field in ("reference", "type", "ndi_element_class"):
            if obs[field] != exp[field]:
                problems.append(
                    f"{obs['name']}: {field} is {obs[field]!r}, expected {exp[field]!r}"
                )
    return problems
