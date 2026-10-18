"""Tests that create cloud datasets must name the organization.

MATLAB counterpart: tests/+ndi/+unittest/CloudTestsNameOrganizationTest.m

NDI Cloud users may belong to several organizations. When a call to
``createDataset``, ``uploadDataset`` or ``newDataset`` does not name one,
:func:`ndi.cloud.internal.chooseOrganization` asks on a terminal and raises
otherwise (a test cannot answer). A test that relies on that only works for
accounts with a single organization -- which is what CI runs with, so CI
cannot catch it. Every such call in tests/ must therefore pass
``organization_id`` / ``org_id`` (normally ``testOrganizationID(client)``) or
``organization_name``.

This scans the test sources statically; it needs no network or credentials.
"""

from __future__ import annotations

import re
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent

#: Files whose calls deliberately name no organization, with why.
EXEMPT = {
    "test_cloud_api_datasets.py": "tests chooseOrganization's own defaults, offline",
    "test_cloud_upload_orchestration.py": "offline; caches exactly one organization",
    "test_dataset_ingestion.py": "offline; caches exactly one organization",
    "test_cloud_tests_name_organization.py": "this guard",
}

_CALL = re.compile(r"\b(createDataset|uploadDataset|newDataset)\(")
_NAMED = re.compile(r"\b(organization_name|organization_id|org_id)\b|testOrganizationID")


def _dataset_creating_calls(source: str) -> list[str]:
    """Full text of each call in SOURCE, ignoring comment lines and definitions."""
    text = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    calls = []
    for match in _CALL.finditer(text):
        if text[max(0, match.start() - 4) : match.start()] == "def ":
            continue
        depth, i = 1, match.end()
        while depth and i < len(text):
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        calls.append(text[match.start() : i])
    return calls


def test_dataset_creating_calls_name_an_organization():
    offenders = []
    for path in sorted(TESTS_ROOT.rglob("*.py")):
        if path.name in EXEMPT:
            continue
        for call in _dataset_creating_calls(path.read_text(encoding="utf-8")):
            if not _NAMED.search(call):
                offenders.append(f"{path.relative_to(TESTS_ROOT)}: {' '.join(call.split())}")
    assert not offenders, (
        "These calls create a cloud dataset without naming an organization; pass "
        "organization_id=testOrganizationID(client):\n" + "\n".join(offenders)
    )


def test_the_scan_finds_a_call_that_names_none():
    """The guard would catch one: an unnamed call is found, a named one is not."""
    unnamed = 'ok = uploadDataset(\n    local,\n    remote_name="x",\n)'
    named = "uploadDataset(local, organization_id=testOrganizationID(client))"
    calls = _dataset_creating_calls(unnamed + "\n" + named)
    assert len(calls) == 2
    assert not _NAMED.search(calls[0])
    assert _NAMED.search(calls[1])
