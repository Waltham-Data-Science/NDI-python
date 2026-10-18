"""ndi.update.check for a copy the NDI installer put in ~/.ndi.

MATLAB counterpart: tests/+ndi/+unittest/+update/TestCheckPython.m, which
checks this same install from NDI-matlab (ndi.update.checkPython).

A fake ~/.ndi (the NdiHome option) and a fake GitHub API (the GitHubApi
option): no network, and no real installer install is needed.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from ndi.update import check
from ndi.update.install_type import read_receipt

INSTALLED = "a" * 40
LATEST = "b" * 40
REPO = "repos/Waltham-Data-Science/NDI-python"


def fake_api(installed: str, ahead_by: int = 0, commits_since: int = 0):
    """Stand-in for GitHub: answers the requests check makes, and logs them."""
    calls: list[str] = []

    def api(path: str, timeout: float):
        calls.append(path)
        if path == f"{REPO}/commits/main":
            return {"sha": LATEST}
        if path == f"{REPO}/compare/{installed}...main":
            return {"ahead_by": ahead_by, "behind_by": 0}
        if path.startswith(f"{REPO}/commits?sha=main&per_page=100&since="):
            return [{"sha": "c"}] * commits_since
        raise AssertionError(f"unexpected GitHub request: {path}")

    api.calls = calls
    return api


def write_receipt(home: Path, **fields) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "install.json").write_text(json.dumps(fields), encoding="utf-8")


def run(home: Path, api) -> dict:
    return check(NdiHome=str(home), GitHubApi=api, Verbose=False)


def test_receipt_behind_main(tmp_path):
    write_receipt(tmp_path, commit=INSTALLED, installedAt="2026-10-01T00:00:00Z")
    r = run(tmp_path, fake_api(INSTALLED, ahead_by=3))
    assert r["InstallType"] == "installer"
    assert r["CanInstall"] is True
    assert r["Status"] == "updateAvailable"
    assert r["UpdateAvailable"] is True
    assert r["CommitsBehind"] == 3
    assert r["CurrentVersion"] == "aaaaaaa"
    assert r["LatestVersion"] == "bbbbbbb"
    assert "ndi.update.install()" in r["Message"]


def test_receipt_up_to_date(tmp_path):
    write_receipt(tmp_path, commit=LATEST)
    r = run(tmp_path, fake_api(LATEST, ahead_by=0))
    assert r["Status"] == "upToDate"
    assert r["UpdateAvailable"] is False


def test_receipt_without_commit_counts_commits_since_install(tmp_path):
    # The installer could not reach GitHub's API: only the time is known.
    write_receipt(tmp_path, commit=None, installedAt="2026-10-01T12:00:00Z")
    api = fake_api("", commits_since=2)
    r = run(tmp_path, api)
    assert r["Status"] == "updateAvailable"
    assert r["CommitsBehind"] == 2
    assert r["InstalledAt"] == "2026-10-01T12:00:00Z"
    assert r["CurrentVersion"] == "installed 2026-10-01"
    assert "since it was installed on 2026-10-01" in r["Message"]
    assert api.calls[-1].endswith("since=2026-10-01T12:00:00Z")


def test_install_older_than_receipts_uses_uv_time(tmp_path):
    uv_receipt = tmp_path / "venvs" / "ndi" / "uv-receipt.toml"
    uv_receipt.parent.mkdir(parents=True)
    uv_receipt.write_text("[tool]\n")
    stamp = time.mktime((2026, 9, 1, 0, 0, 0, 0, 0, -1))
    os.utime(uv_receipt, (stamp, stamp))
    r = run(tmp_path, fake_api("", commits_since=100))
    assert r["CommitsBehind"] == 100
    assert r["InstalledAt"].startswith("2026-0")
    assert "100 or more commit(s)" in r["Message"]


def test_no_version_information_is_unknown(tmp_path):
    r = run(tmp_path, fake_api(""))
    assert r["Status"] == "unknown"
    assert r["UpdateAvailable"] is False


def test_github_failure_is_unknown_not_an_error(tmp_path):
    write_receipt(tmp_path, commit=INSTALLED)

    def offline(path, timeout):
        raise OSError("no network")

    r = run(tmp_path, offline)
    assert r["Status"] == "unknown"
    assert r["UpdateAvailable"] is False
    assert "no network" in r["Message"]


@pytest.mark.parametrize("text", ["", "not json", "[1, 2]"])
def test_unreadable_receipt_is_no_receipt(tmp_path, text):
    (tmp_path / "install.json").write_text(text, encoding="utf-8")
    assert read_receipt(tmp_path) is None


def test_receipt_with_byte_order_mark_is_rejected_not_crashed(tmp_path):
    # The installer writes UTF-8 without a BOM; a BOM is unreadable, not fatal.
    (tmp_path / "install.json").write_bytes(b"\xef\xbb\xbf" + json.dumps({"commit": "x"}).encode())
    assert read_receipt(tmp_path) is None
