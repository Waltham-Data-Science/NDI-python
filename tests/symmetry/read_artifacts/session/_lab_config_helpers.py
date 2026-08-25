"""Lab-configuration symmetry helpers for the blankSession read tests (M4 / S1).

These back the additive half of the ``blankSession{Kjnielsenlab,Rayolab,Vhlab,
Marderlab}`` comparisons: per-DAQ-system ``daqmetadatareader``
``tab_separated_file_parameter`` values, and the syncrule documents a lab's
configuration installs.

Why this is the symmetry proof of the W3-A defect
-------------------------------------------------
Python's ``ndi.setup.lab()`` never read ``MetadataReaderFileParameters`` from
the lab JSON, so every ``daqmetadatareader`` document it wrote carried
``tab_separated_file_parameter = ""`` -- the regexp ``readmetadata()`` uses to
find an epoch's stimulus-parameter file -- and every Python-configured lab with
a metadata reader silently read NO stimulus metadata.  The same fix installed
the lab sync rules, which Python also never added: a session built by
``ndi.setup.lab(session, "vhlab")`` had an EMPTY syncgraph.

Neither field appears in ``sessionSummary``, so the existing
``compareSessionSummary`` comparisons passed throughout the defect and would
pass again if it regressed.  That is precisely the shape of hole these helpers
close: a control that guards one surface says nothing about the surface next to
it.

Non-circularity
---------------
The expectations are read straight from the vendored ``ndi_common`` JSON that
both languages ship (``daq_systems/<lab>/*.json`` and
``sync_rules/<lab>/*.json``), NOT by calling ``ndi.setup.lab``'s own helpers.
A test that asked the code under test what it expected would have passed before
the fix too.

The comparison is deliberately set-based rather than a re-implementation of
MATLAB ``createMetadataReader``'s four-branch pairing: what matters is that
every declared file parameter reached a document, and that no reader was
dropped.  The pre-fix defect failed both halves (empty parameters, and
dbkatzlab's three file parameters collapsing into one reader).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ndi.query import ndi_query

# The rule ndi.setup.lab() adds to every lab before the lab-specific ones.
# MATLAB lab.m:  nsf = ndi.time.syncrule.filematch(struct('number_fullpath_matches',2));
DEFAULT_SYNCRULE = ("ndi.time.syncrule.filematch", (("number_fullpath_matches", 2),))


# --------------------------------------------------------------------------
# What the shared ndi_common configuration declares
# --------------------------------------------------------------------------


def _ndi_common_dir() -> Path:
    import ndi.ndi_common

    return Path(ndi.ndi_common.__path__[0])


def _as_list(value: Any) -> list:
    """A JSON scalar / list / absent field as a list, dropping empty strings.

    MATLAB stores these fields as ``(1,:) string`` arrays, so a lone string and
    a one-element array are the same thing; ``jsondecode`` produces either
    depending on how the file was written.
    """
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [v for v in value if v != ""]
    return [value]


def declared_metadata_readers(lab_name: str) -> dict[str, dict[str, Any]]:
    """Per DAQ system, what the lab's vendored JSON declares.

    Returns ``{daq_system_name: {"classes": [...], "file_parameters": [...]}}``,
    including DAQ systems that declare no metadata reader at all (with two
    empty lists) so a caller can tell "declared nothing" from "not in the lab".
    """
    lab_dir = _ndi_common_dir() / "daq_systems" / str(lab_name)
    declared: dict[str, dict[str, Any]] = {}
    for config_file in sorted(lab_dir.glob("*.json")):
        config = json.loads(config_file.read_text(encoding="utf-8"))
        name = config.get("Name") or config_file.stem
        declared[name] = {
            "classes": _as_list(config.get("MetadataReaderClass")),
            "file_parameters": _as_list(config.get("MetadataReaderFileParameters")),
        }
    return declared


def declared_sync_rules(lab_name: str) -> list[tuple[str, tuple]]:
    """The syncrules a lab installs: the default filematch plus its own.

    Each rule is ``(class_name, sorted parameter items)`` so the result is
    hashable and order-independent.
    """
    rules = [DEFAULT_SYNCRULE]
    rules_dir = _ndi_common_dir() / "sync_rules" / str(lab_name)
    if rules_dir.is_dir():
        for config_file in sorted(rules_dir.glob("*.json")):
            config = json.loads(config_file.read_text(encoding="utf-8"))
            rules.append(_rule_key(config["syncrule_class"], config["parameters"]))
    return rules


# --------------------------------------------------------------------------
# What an artifact session actually holds
# --------------------------------------------------------------------------


def _all_documents(session) -> list:
    return session.database_search(ndi_query("base.id").match("(.*)"))


def _class_name(props: dict) -> str:
    return props.get("document_class", {}).get("class_name", "")


def _metadata_reader_dependency_ids(props: dict) -> list[str]:
    """The daqmetadatareader ids a daqsystem document depends on.

    Dependency names are ``daqmetadatareader_id`` and
    ``daqmetadatareader_id_<n>``; the unnumbered one is written as an empty
    placeholder when there are numbered entries, so empty values are dropped.
    """
    ids = []
    for dependency in props.get("depends_on", []) or []:
        name = dependency.get("name", "")
        if not name.startswith("daqmetadatareader_id"):
            continue
        suffix = name[len("daqmetadatareader_id") :]
        if suffix and not suffix.lstrip("_").isdigit():
            continue
        value = dependency.get("value", "")
        if value:
            ids.append(value)
    return ids


def session_metadata_readers(session) -> dict[str, list[dict[str, str]]]:
    """``{daq_system_name: [{"class":..., "file_parameter":...}, ...]}``.

    Resolved through the daqsystem document's ``depends_on`` rather than
    through the reader document's ``base.name``, because the dependency is the
    structure both languages are contractually required to write; a name on the
    reader document is a Python convenience.
    """
    documents = _all_documents(session)
    readers_by_id: dict[str, dict[str, str]] = {}
    daq_systems: list[tuple[str, dict]] = []

    for document in documents:
        props = document.document_properties
        class_name = _class_name(props)
        if class_name == "daqmetadatareader":
            payload = props.get("daqmetadatareader", {}) or {}
            readers_by_id[props["base"]["id"]] = {
                "class": payload.get("ndi_daqmetadatareader_class", ""),
                "file_parameter": payload.get("tab_separated_file_parameter", ""),
            }
        elif class_name == "daqsystem":
            daq_systems.append((props["base"]["name"], props))

    result: dict[str, list[dict[str, str]]] = {}
    for name, props in daq_systems:
        readers = []
        for reader_id in _metadata_reader_dependency_ids(props):
            reader = readers_by_id.get(reader_id)
            assert reader is not None, (
                f"DAQ system {name!r} depends on daqmetadatareader {reader_id!r}, "
                f"which is not in the session database."
            )
            readers.append(reader)
        result[name] = readers
    return result


def _rule_key(class_name: str, parameters: dict) -> tuple[str, tuple]:
    return (str(class_name), tuple(sorted((str(k), v) for k, v in (parameters or {}).items())))


def session_sync_rules(session) -> list[tuple[str, tuple]]:
    """The syncrule documents installed in a session, as comparable keys."""
    rules = []
    for document in _all_documents(session):
        props = document.document_properties
        if _class_name(props) != "syncrule":
            continue
        payload = props.get("syncrule", {}) or {}
        rules.append(
            _rule_key(
                payload.get("ndi_syncrule_class", ""),
                payload.get("parameters", {}),
            )
        )
    return rules


# --------------------------------------------------------------------------
# Assertions
# --------------------------------------------------------------------------


def assert_metadata_readers_match_lab_config(session, lab_name: str, source_type: str) -> None:
    """Every declared metadata-reader file parameter reached a document."""
    declared = declared_metadata_readers(lab_name)
    actual = session_metadata_readers(session)

    problems = []
    for daq_name, spec in declared.items():
        if daq_name not in actual:
            # The artifact may legitimately hold a subset of the lab's DAQ
            # systems; only systems that ARE present are checked.
            continue
        found = actual[daq_name]
        classes, file_parameters = spec["classes"], spec["file_parameters"]

        if not classes:
            if found:
                problems.append(
                    f"{daq_name}: lab config declares no MetadataReaderClass but the "
                    f"session holds {len(found)} daqmetadatareader document(s): {found}"
                )
            continue

        expected_count = max(len(file_parameters), len(classes))
        if len(found) != expected_count:
            problems.append(
                f"{daq_name}: expected {expected_count} daqmetadatareader document(s) "
                f"(config declares {len(classes)} class(es) and "
                f"{len(file_parameters)} file parameter(s)), found {len(found)}: {found}"
            )
            continue

        got_classes = sorted(reader["class"] for reader in found)
        if len(classes) == 1:
            expected_classes = sorted(classes * expected_count)
        else:
            expected_classes = sorted(classes)
        if got_classes != expected_classes:
            problems.append(
                f"{daq_name}: metadata reader classes {got_classes} != "
                f"declared {expected_classes}"
            )

        got_parameters = sorted(reader["file_parameter"] for reader in found)
        expected_parameters = sorted(file_parameters) if file_parameters else [""] * len(found)
        if got_parameters != expected_parameters:
            problems.append(
                f"{daq_name}: tab_separated_file_parameter values {got_parameters!r} "
                f"!= declared MetadataReaderFileParameters {expected_parameters!r}. "
                f"An empty value here is the W3-A defect: readmetadata() finds no "
                f"stimulus metadata file at all."
            )

    assert not problems, (
        f"{source_type} {lab_name} daqmetadatareader mismatch against the shared "
        f"ndi_common lab configuration:\n" + "\n".join(problems)
    )


def assert_sync_rules_match_lab_config(session, lab_name: str, source_type: str) -> None:
    """The lab's syncrules are installed, with their parameters intact."""
    expected = sorted(declared_sync_rules(lab_name))
    actual = sorted(session_sync_rules(session))
    assert actual == expected, (
        f"{source_type} {lab_name} syncrule documents do not match the shared "
        f"ndi_common lab configuration.\n"
        f"  expected: {expected}\n"
        f"  actual:   {actual}\n"
        f"An empty actual list is the W3-A defect: ndi.setup.lab() built a session "
        f"with an EMPTY syncgraph."
    )


def assert_metadata_readers_agree(session_a, session_b, lab_name: str) -> None:
    """MATLAB and Python wrote the same per-DAQ-system metadata readers."""
    a = {
        name: sorted(map(_reader_key, readers))
        for name, readers in session_metadata_readers(session_a).items()
    }
    b = {
        name: sorted(map(_reader_key, readers))
        for name, readers in session_metadata_readers(session_b).items()
    }
    shared = sorted(set(a) & set(b))
    assert shared, (
        f"{lab_name}: the MATLAB and Python artifacts share no DAQ system name, "
        f"so nothing was compared (matlab={sorted(b)}, python={sorted(a)})."
    )
    problems = [
        f"{name}: python={a[name]!r} matlab={b[name]!r}" for name in shared if a[name] != b[name]
    ]
    assert (
        not problems
    ), f"{lab_name}: daqmetadatareader disagreement between languages:\n" + "\n".join(problems)


def _reader_key(reader: dict[str, str]) -> tuple[str, str]:
    return (reader["class"], reader["file_parameter"])


def assert_sync_rules_agree(session_a, session_b, lab_name: str) -> None:
    """MATLAB and Python installed the same syncrules."""
    a, b = sorted(session_sync_rules(session_a)), sorted(session_sync_rules(session_b))
    assert a and b, (
        f"{lab_name}: one of the artifacts holds no syncrule documents at all "
        f"(python={a}, matlab={b}); there is nothing to compare."
    )
    assert a == b, (
        f"{lab_name}: syncrule disagreement between languages.\n"
        f"  python: {a}\n"
        f"  matlab: {b}"
    )
