"""Generate symmetry artifacts for ``pathSafeName`` / ``elementDirectoryName`` (fun namespace).

Computation-style pair, following the ``time/test_time_convert.py`` precedent:
these are pure functions, not persisted document sets, so the artifact is a
self-describing JSON of inputs + computed outputs rather than a session-dir
copy.

Runs the shared ``tests/symmetry/_path_safe_name_cases`` vector through the real
``ndi.fun.file.pathSafeName`` and ``ndi.fun.file.elementDirectoryName`` and
writes:

    <tempdir>/NDI/symmetryTest/pythonArtifacts/fun/pathSafeName/
             testPathSafeNameArtifacts/pathSafeNameCases.json

MATLAB counterpart to author (FULL closure needs the MATLAB runtime):
    tests/+ndi/+symmetry/+makeArtifacts/+fun/pathSafeName.m -- build the same
    case ids, run them through ndi.fun.file.pathSafeName /
    ndi.fun.file.elementDirectoryName, and write
    matlabArtifacts/fun/.../pathSafeNameCases.json with the same schema.
    Rebuild each input from ``input_utf16`` (``char(uint16(units))``) rather
    than from a literal, so the astral-character cases are byte-identical.

The JSON is strict (``allow_nan=False``, ``ensure_ascii=True``) so MATLAB's
``jsondecode`` can read it without special-casing.
"""

import json
import shutil

from tests.symmetry._path_safe_name_cases import (
    ELEMENT_DIRECTORY_NAME_CASES,
    PATH_SAFE_NAME_CASES,
    run_element_directory_name_cases,
    run_path_safe_name_cases,
)
from tests.symmetry.conftest import PYTHON_ARTIFACTS

ARTIFACT_DIR = PYTHON_ARTIFACTS / "fun" / "pathSafeName" / "testPathSafeNameArtifacts"
ARTIFACT_FILE = ARTIFACT_DIR / "pathSafeNameCases.json"

SCHEMA_VERSION = 1


class TestPathSafeName:
    """Mirror of (to-be-authored) ndi.symmetry.makeArtifacts.fun.pathSafeName."""

    def test_path_safe_name_artifacts(self):
        if ARTIFACT_DIR.exists():
            shutil.rmtree(ARTIFACT_DIR)
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

        path_safe = run_path_safe_name_cases()
        element_dir = run_element_directory_name_cases()

        payload = {
            "description": (
                "ndi.fun.file.pathSafeName / elementDirectoryName symmetry cases. "
                "Each case carries the input three ways -- as a string, as Unicode "
                "code points, and as UTF-16 code units -- so the read side can "
                "prove both languages ran the same input before comparing outputs."
            ),
            "schemaVersion": SCHEMA_VERSION,
            "language": "python",
            "pathSafeName": path_safe,
            "elementDirectoryName": element_dir,
        }
        ARTIFACT_FILE.write_text(
            json.dumps(payload, indent=2, allow_nan=False, ensure_ascii=True),
            encoding="utf-8",
        )

        assert ARTIFACT_FILE.exists()
        assert len(path_safe) == len(PATH_SAFE_NAME_CASES)
        assert len(element_dir) == len(ELEMENT_DIRECTORY_NAME_CASES)

        # Case ids are the cross-language join key, so they must be unique.
        ids = [row["id"] for row in path_safe]
        assert len(set(ids)) == len(ids), f"duplicate pathSafeName case ids: {ids}"
        ids = [row["id"] for row in element_dir]
        assert len(set(ids)) == len(ids), f"duplicate elementDirectoryName case ids: {ids}"

        # The load-bearing values from the MATLAB contract, spelled out so a
        # regression here is obvious at the producing test rather than as an
        # opaque cross-language diff later.
        by_id = {row["id"]: row for row in path_safe}
        assert by_id["probeSpacedPipe"]["output"] == "probe_-_1"
        assert by_id["elementStringPipe"]["output"] == "ctx_-_1"
        assert by_id["windowsIllegalCharacters"]["output"] == "a" + "-" * 9 + "b"
        assert by_id["portableCharactersUnchanged"]["output"] == "AZaz09._-"
        assert by_id["trailingDotsStripped"]["output"] == "probe"
        assert by_id["reservedCon"]["output"] == "_CON"
        assert by_id["reservedNulWithExtension"]["output"] == "_nul.txt"
        assert by_id["reservedLpt9"]["output"] == "_LPT9"
        assert by_id["notReservedConsole"]["output"] == "CONSOLE"
        assert by_id["allDotsBecomesX"]["output"] == "x"
        assert by_id["emptyBecomesX"]["output"] == "x"
        # A character above U+FFFF is a surrogate PAIR in MATLAB, hence two '-'.
        assert by_id["astralUnicode"]["output"] == "a--b"
        assert by_id["astralUnicode"]["input_utf16"] == [0x61, 0xD83C, 0xDF89, 0x62]
        assert by_id["bmpUnicode"]["output"] == "a-b"

        by_id = {row["id"]: row for row in element_dir}
        assert by_id["elementSpacedPipe"]["dir_name"] == "ctx_-_1"
        assert by_id["elementSpacedPipe"]["legacy_dir_name"] == "ctx_|_1"
        assert by_id["elementAlreadySafe"]["dir_name"] == "mock_probe"
        assert by_id["elementAlreadySafe"]["legacy_dir_name"] == "mock_probe"
        assert by_id["elementEmpty"]["dir_name"] == "x"
        assert by_id["elementEmpty"]["legacy_dir_name"] == ""
