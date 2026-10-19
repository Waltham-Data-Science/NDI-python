"""ndi.update: modificationSummary, checkOnStartup, installType, the CLI and
the navigator's Update-button decisions (update_dialog), all without Qt or
network.

MATLAB counterparts: TestModificationSummary.m, TestInstallType.m and
TestNavigatorLayout/testNdiPaneHasUpdateButton in NDI-matlab's
tests/+ndi/+unittest.
"""

from __future__ import annotations

import json
import sys

import pytest

import ndi
import ndi.preferences
import ndi.update
from ndi.gui.nav.ndi_pane import (
    BROOM_WIDTH,
    BUTTON_SPACING,
    PREFS_WIDTH,
    UPDATE_WIDTH,
    NdiPane,
    update_dialog,
)
from ndi.update import checkOnStartup, installType, modificationSummary

check_module = sys.modules["ndi.update.check"]


# ---- modificationSummary ---------------------------------------------------


def mod(name="NDI-python", changed=(), blocking=(), ahead=0):
    return {
        "Name": name,
        "Path": f"/x/{name}",
        "ChangedFiles": list(changed),
        "BlockingFiles": list(blocking),
        "CommitsAhead": ahead,
    }


def test_no_modifications_gives_empty():
    assert modificationSummary({"Modifications": []}) == ""


def test_summary_lists_files_and_commits():
    txt = modificationSummary(
        {"Modifications": [mod(changed=["src/a.py", "src/b.py"], blocking=["mine.py"], ahead=1)]}
    )
    assert "NDI-python (/x/NDI-python)" in txt
    assert "2 changed file(s)" in txt
    assert "1 untracked file(s) in the way of new files" in txt
    assert "1 local commit(s)" in txt
    assert "changed:    src/a.py" in txt
    assert "in the way: mine.py" in txt
    assert "stash" in txt
    assert "other untracked files are left alone" in txt


def test_max_files_counts_the_rest():
    files = [f"f{i}.py" for i in range(1, 6)]
    txt = modificationSummary({"Modifications": [mod(changed=files)]}, MaxFiles=2)
    assert "changed:    f2.py" in txt
    assert "f3.py" not in txt
    assert "... and 3 more" in txt


# ---- installType -------------------------------------------------------------


def test_install_type_fields():
    kind, info = installType()
    assert kind in {"installer", "git", "pip", "unknown"}
    assert set(info) == {"SourceDir", "RepoRoot", "NdiHome", "Receipt"}
    if kind == "git":
        assert info["RepoRoot"] and ndi.__file__.startswith(info["RepoRoot"])
    else:
        assert info["RepoRoot"] == ""


# ---- checkOnStartup ------------------------------------------------------------


@pytest.fixture
def prefs(monkeypatch):
    """An in-memory stand-in for ndi.preferences get/set."""
    store = {
        "Update.CheckOnStartup": True,
        "Update.CheckIntervalDays": 1.0,
        "Update.Python.LastCheckTime": "",
    }
    monkeypatch.setattr(ndi.preferences, "get", lambda key: store[key])
    monkeypatch.setattr(ndi.preferences, "set", lambda key, value: store.__setitem__(key, value))
    monkeypatch.delenv("CI", raising=False)
    return store


def fake_check(update=True, can_install=True):
    calls = []

    def run(**kw):
        calls.append(kw)
        return {
            "UpdateAvailable": update,
            "CanInstall": can_install,
            "Message": "An NDI-python update is available: 3 commits.\nRun ndi.update.install() ...",
        }

    run.calls = calls
    return run


def test_startup_check_reports_once_per_interval(prefs, monkeypatch, capsys):
    run = fake_check()
    monkeypatch.setattr(check_module, "check", run)
    line = checkOnStartup()
    assert line.startswith("An NDI-python update is available: 3 commits.")
    assert "ndi update" in line
    assert prefs["Update.Python.LastCheckTime"]
    assert checkOnStartup() == ""  # within the interval: no second check
    assert len(run.calls) == 1


def test_startup_check_leaves_matlabs_time_alone(prefs, monkeypatch):
    monkeypatch.setattr(check_module, "check", fake_check(update=False))
    checkOnStartup()
    assert "Update.MATLAB.LastCheckTime" not in prefs


def test_startup_check_can_be_turned_off(prefs, monkeypatch):
    run = fake_check()
    monkeypatch.setattr(check_module, "check", run)
    prefs["Update.CheckOnStartup"] = False
    assert checkOnStartup() == ""
    assert run.calls == []


def test_startup_check_is_skipped_in_ci(prefs, monkeypatch):
    run = fake_check()
    monkeypatch.setattr(check_module, "check", run)
    monkeypatch.setenv("CI", "true")
    assert checkOnStartup() == ""
    assert run.calls == []


def test_startup_check_never_raises(prefs, monkeypatch):
    def broken(**kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(check_module, "check", broken)
    assert checkOnStartup() == ""


def test_update_preferences_are_registered(tmp_path):
    from ndi.preferences import ndi_preferences

    p = ndi_preferences(filename=tmp_path / "NDI_Preferences.json")
    assert p.get("Update.CheckOnStartup") is True
    assert p.get("Update.CheckIntervalDays") == 1.0
    assert p.get("Update.Python.LastCheckTime") == ""


# ---- the CLI -----------------------------------------------------------------


def test_cli_check_json(monkeypatch, capsys):
    from ndi.__main__ import _update_main

    monkeypatch.setattr(
        ndi.update, "check", lambda **kw: {"Status": "upToDate", "UpdateAvailable": False}
    )
    assert _update_main(["--check", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["Status"] == "upToDate"


def test_cli_update_reports_refusal(monkeypatch, capsys):
    from ndi.__main__ import _update_main

    def refuse(**kw):
        raise ndi.update.UpdateError("ndi:update:install:notOnMain", "not on main")

    monkeypatch.setattr(ndi.update, "install", refuse)
    assert _update_main(["--yes"]) == 1
    assert "not on main" in capsys.readouterr().err


# ---- the navigator's Update button -------------------------------------------


def test_pane_is_wide_enough_for_three_buttons():
    pane = NdiPane()
    assert pane.right_width() == BROOM_WIDTH + UPDATE_WIDTH + PREFS_WIDTH + 2 * BUTTON_SPACING


def test_dialog_up_to_date_is_an_alert():
    plan = update_dialog({"UpdateAvailable": False, "Status": "upToDate", "Message": "fine"})
    assert plan == {"kind": "alert", "message": "fine", "success": True}


def test_dialog_unknown_is_a_warning():
    plan = update_dialog({"UpdateAvailable": False, "Status": "unknown", "Message": "offline"})
    assert plan["success"] is False


def test_dialog_other_branch_only_explains():
    plan = update_dialog(
        {"UpdateAvailable": True, "CanInstall": True, "InstallType": "git", "Branch": "dev"}
    )
    assert plan["kind"] == "alert"
    assert plan["success"] is False


def test_dialog_offers_update_and_drops_terminal_hints():
    plan = update_dialog(
        {
            "UpdateAvailable": True,
            "CanInstall": True,
            "InstallType": "git",
            "Branch": "main",
            "HasModifications": False,
            "Message": "An update is available.\nRun ndi.update.install() (or `ndi update`) to update.",
        }
    )
    assert plan["kind"] == "confirm"
    assert plan["accept"] == "Update"
    assert plan["default_cancel"] is False
    assert "ndi.update.install" not in plan["message"]
    assert plan["message"].endswith("Update now?")


def test_dialog_with_modified_code_defaults_to_cancel():
    plan = update_dialog(
        {
            "UpdateAvailable": True,
            "CanInstall": True,
            "InstallType": "git",
            "Branch": "main",
            "HasModifications": True,
            "Modifications": [mod(changed=["src/a.py"])],
            "Message": "An update is available.\nNote: you have changed code in NDI-python.",
        }
    )
    assert plan["accept"] == "Update anyway"
    assert plan["default_cancel"] is True
    assert "changed:    src/a.py" in plan["message"]
    assert "Note: you have changed code" not in plan["message"]


def test_dialog_with_untracked_files_in_the_way_only_explains():
    # git will not overwrite them, so the button says to move them instead of
    # offering an update that would stop part-way.
    plan = update_dialog(
        {
            "UpdateAvailable": True,
            "CanInstall": True,
            "InstallType": "git",
            "Branch": "main",
            "HasModifications": True,
            "Modifications": [mod(blocking=["new_module.py"])],
            "Message": "An update is available.",
        }
    )
    assert plan["kind"] == "alert"
    assert plan["success"] is False
    assert "in the way: new_module.py" in plan["message"]
    assert "Move or rename" in plan["message"]
