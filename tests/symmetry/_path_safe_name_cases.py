"""Shared case vector for the ``pathSafeName`` / ``elementDirectoryName`` symmetry pair (M2).

Both the make side (``make_artifacts/fun/test_path_safe_name.py``) and the read
side (``read_artifacts/fun/test_path_safe_name.py``) import this module, so the
two halves cannot drift apart, and the MATLAB counterpart
(``+makeArtifacts/+fun/pathSafeName.m``) builds the same vector from the same
case ids.

The vector is the full contract pinned by MATLAB
``ndi.unittest.fun.file.ElementDirectoryTest`` plus the Python-side additions
that the port's docstring promises: the ``'probe | 1'`` element string, every
character Windows forbids, the Windows reserved device names, trailing dots,
control characters, the empty string, and a character above U+FFFF.

Transport
---------
Case *inputs* travel three ways in the artifact JSON:

``input``
    The string itself.  Written with ``ensure_ascii=True`` so a non-BMP
    character crosses as an escaped surrogate pair, which MATLAB ``jsondecode``
    turns back into the same two UTF-16 code units MATLAB's ``char`` uses.
``input_codepoints``
    Unicode scalar values -- the authoritative form for Python.
``input_utf16``
    UTF-16 code units -- the authoritative form for MATLAB, which can rebuild
    the string with ``char(uint16(units))``.

Recording all three is what lets the read side prove the two languages actually
ran the *same* input before it compares outputs.  The U+FFFF boundary is the
whole reason this matters: ``pathSafeName`` emits one ``'-'`` per UTF-16 code
unit, so 'a🎉b' must yield ``'a--b'`` in both languages, and a case that
silently arrived as a different string would look like agreement.
"""

from __future__ import annotations

from typing import Any

import ndi.fun.file as ndi_fun_file

# Every character Windows forbids outright in a filename.
_WINDOWS_ILLEGAL = '<>:"/\\|?*'

# (case id, input string, what the case pins)
PATH_SAFE_NAME_CASES: tuple[tuple[str, str, str], ...] = (
    ("elementStringPipe", "ctx_|_1", "the '|' an element string embeds -> '-'"),
    ("elementStringSpacedPipe", "ctx | 1", "spaces -> '_', pipe -> '-'"),
    ("probeSpacedPipe", "probe | 1", "the MATLAB-contract probe element string"),
    (
        "windowsIllegalCharacters",
        "a" + _WINDOWS_ILLEGAL + "b",
        "every Windows-illegal character -> one '-' each",
    ),
    ("portableCharactersUnchanged", "AZaz09._-", "the portable set survives verbatim"),
    ("spaceBecomesUnderscore", "my probe", "whitespace -> '_'"),
    ("tabBecomesUnderscore", "a\tb", "control character U+0009 -> '_'"),
    ("newlineBecomesUnderscore", "a\nb", "control character U+000A -> '_'"),
    ("deleteBecomesUnderscore", "a\x7fb", "control character U+007F -> '_'"),
    ("trailingDotsStripped", "probe...", "Windows silently strips trailing dots"),
    ("reservedCon", "CON", "reserved device name -> '_' prefix"),
    ("reservedNulWithExtension", "nul.txt", "reserved even with an extension, case-insensitive"),
    ("reservedCom1", "COM1", "COM1 is reserved"),
    ("reservedCom3", "COM3", "COM3 is reserved"),
    ("reservedLpt9", "LPT9", "LPT9 is reserved"),
    ("notReservedConsole", "CONSOLE", "a longer name starting with CON is NOT reserved"),
    ("allDotsBecomesX", "...", "a name that sanitizes to nothing becomes 'x'"),
    ("emptyBecomesX", "", "the empty string becomes 'x'"),
    ("alreadySafe", "mock_probe", "an already-safe name is returned unchanged"),
    ("bmpUnicode", "aøb", "a BMP character above ASCII is one UTF-16 unit -> one '-'"),
    (
        "astralUnicode",
        "a\U0001f389b",
        "a character above U+FFFF is a surrogate PAIR -> two '-' (MATLAB parity)",
    ),
    (
        "astralUnicodeReservedPrefix",
        "CON\U0001f389",
        "the reserved-name check runs on the sanitized base name, not the input",
    ),
)

# elementDirectoryName takes an element string (or an object answering
# elementstring()); these are the element strings the MATLAB test uses plus the
# degenerate ones the Python port documents.
ELEMENT_DIRECTORY_NAME_CASES: tuple[tuple[str, str, str], ...] = (
    ("elementSpacedPipe", "ctx | 1", "the canonical element string -> ('ctx_-_1','ctx_|_1')"),
    ("elementProbeSpacedPipe", "probe | 1", "the MATLAB-contract probe element string"),
    ("elementAlreadySafe", "mock_probe", "no sanitizing needed; both names are identical"),
    ("elementEmpty", "", "legacy name is empty, new name is 'x'"),
    ("elementReserved", "CON", "reserved device name in an element string"),
    ("elementAstral", "ctx \U0001f389 1", "non-BMP character in an element string"),
)


def _utf16_units(value: str) -> list[int]:
    """UTF-16 code units of *value*, the unit MATLAB's ``char`` counts."""
    raw = value.encode("utf-16-be")
    return [(raw[i] << 8) | raw[i + 1] for i in range(0, len(raw), 2)]


def _string_forms(value: str) -> dict[str, Any]:
    """The three transport forms of one input string (see the module docstring)."""
    return {
        "input": value,
        "input_codepoints": [ord(ch) for ch in value],
        "input_utf16": _utf16_units(value),
    }


def run_path_safe_name_cases() -> list[dict[str, Any]]:
    """Run every ``pathSafeName`` case, recording inputs and outputs."""
    rows: list[dict[str, Any]] = []
    for case_id, value, note in PATH_SAFE_NAME_CASES:
        row: dict[str, Any] = {"id": case_id, "note": note}
        row.update(_string_forms(value))
        row["output"] = ndi_fun_file.pathSafeName(value)
        rows.append(row)
    return rows


def run_element_directory_name_cases() -> list[dict[str, Any]]:
    """Run every ``elementDirectoryName`` case, recording inputs and outputs."""
    rows: list[dict[str, Any]] = []
    for case_id, value, note in ELEMENT_DIRECTORY_NAME_CASES:
        dir_name, legacy_dir_name = ndi_fun_file.elementDirectoryName(value)
        row: dict[str, Any] = {"id": case_id, "note": note}
        row.update(_string_forms(value))
        row["dir_name"] = dir_name
        row["legacy_dir_name"] = legacy_dir_name
        rows.append(row)
    return rows
