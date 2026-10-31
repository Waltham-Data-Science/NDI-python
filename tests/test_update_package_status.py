"""The Update button's package table: ndi.update.packageStatus,
ndi.update.install(Packages=...), and ndi.gui.nav.update_dialog.

MATLAB counterparts: ndi.update.packageStatus, ndi.update.install's Packages
option and ndi.gui.nav.updateDialog (VH-Lab/NDI-matlab 19b8ab573, 749b1a266).

The git tests build throwaway clones exactly as test_update_check_git.py does
(bare repositories standing in for GitHub; no network). The dialog's
decisions are plain functions tested without Qt; the window itself is built
under QT_QPA_PLATFORM=offscreen.
"""

from __future__ import annotations

import os
import shutil

import pytest

from ndi.gui.nav.update_dialog import note_text, table_data, update_button_state
from ndi.update import UpdateError, check, install, packageStatus
from tests.test_update_check_git import Clones, commit_all, git

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="needs the git program")


@pytest.fixture
def clones(tmp_path):
    return Clones(tmp_path)


def run_check(clones):
    return check(RepoRoot=str(clones.ndi), NdiHome=str(clones.home), Verbose=False)


def run_install(clones, **kw):
    return install(RepoRoot=str(clones.ndi), NdiHome=str(clones.home), Confirm=False, **kw)


def by_name(rows):
    return {r["Name"]: r for r in rows}


# ---- packageStatus on git clones ---------------------------------------------


@needs_git
class TestPackageStatusGit:
    def test_up_to_date(self, clones):
        rows, summary = packageStatus(run_check(clones))
        assert [r["Name"] for r in rows] == ["NDI-python", "vhlab-toolbox-python"]
        assert [r["Kind"] for r in rows] == ["ndi", "dependency"]
        assert all(r["Status"] == "Up to date" for r in rows)
        assert not any(r["Selectable"] for r in rows)
        assert summary["AnyUpdate"] is False
        assert summary["Message"] == "Everything is up to date."
        assert rows[1]["Installed"] and rows[1]["Installed"] == rows[1]["Latest"]

    def test_packages_behind_start_ticked(self, clones):
        clones.push_upstream("NDI-python")
        clones.push_upstream("vhlab-toolbox-python")
        r = run_check(clones)
        dep = r["Dependencies"][0]
        assert dep["CurrentVersion"] != dep["LatestVersion"]
        rows, summary = packageStatus(r)
        for row in rows:
            assert row["Status"] == "1 new commit"
            assert row["WillUpdate"] and row["Selectable"] and row["Selected"]
            assert row["Installed"] != row["Latest"]
        assert summary["Message"] == "2 package(s) can be updated. Tick the ones to update."

    def test_your_changes_are_left_unticked(self, clones):
        clones.push_upstream("vhlab-toolbox-python")
        (clones.dep / "README.md").write_text("my edit")
        rows, summary = packageStatus(run_check(clones))
        dep = by_name(rows)["vhlab-toolbox-python"]
        assert dep["TouchesChanges"] is True
        assert dep["Selectable"] is True
        assert dep["Selected"] is False
        assert dep["NoteLevel"] == "warning"
        assert "1 changed file(s) will be stashed" in dep["Notes"][0]
        assert "changed:    README.md" in dep["Files"]
        assert "changed:    README.md" in dep["Details"]
        assert summary["HasUserChanges"] is True

    def test_changes_where_nothing_updates_are_not_touched(self, clones):
        clones.push_upstream("vhlab-toolbox-python")
        (clones.ndi / "README.md").write_text("my edit")
        ndi_row = by_name(packageStatus(run_check(clones))[0])["NDI-python"]
        assert ndi_row["WillUpdate"] is False
        assert ndi_row["TouchesChanges"] is False
        assert ndi_row["Notes"] == ["You have changed code here; it is not touched."]

    def test_untracked_file_in_the_way_blocks(self, clones):
        seed = clones.seeds / "NDI-python"
        (seed / "new.py").write_text("upstream\n")
        commit_all(seed, "adds a file")
        git(seed, "push", "-q", "origin", "main")
        (clones.ndi / "new.py").write_text("mine\n")
        rows, summary = packageStatus(run_check(clones))
        ndi_row = rows[0]
        assert ndi_row["Blocked"] and not ndi_row["Selectable"]
        assert ndi_row["NoteLevel"] == "error"
        assert "in the way: new.py" in ndi_row["Files"]
        assert summary["Message"].startswith("Updates are available, but none can be installed")

    def test_other_branch_blocks_ndi_python_only(self, clones):
        clones.push_upstream("NDI-python")
        clones.push_upstream("vhlab-toolbox-python")
        git(clones.ndi, "checkout", "-q", "-b", "myFeature")
        rows, summary = packageStatus(run_check(clones))
        assert rows[0]["Blocked"] is True
        assert "not main" in rows[0]["Notes"][0]
        assert rows[1]["Selectable"] is True
        assert summary["Message"].endswith("Packages marked with an error cannot be updated yet.")


# ---- packageStatus without git -------------------------------------------------


class TestPackageStatusOther:
    def test_installer_install(self):
        r = {
            "InstallType": "installer",
            "Status": "updateAvailable",
            "UpdateAvailable": True,
            "CanInstall": True,
            "CommitsBehind": 3,
            "CurrentVersion": "abc1234",
            "LatestVersion": "def5678",
            "Message": "An update.",
        }
        rows, summary = packageStatus(r)
        assert len(rows) == 1
        row = rows[0]
        assert (row["Name"], row["Kind"], row["Status"]) == (
            "NDI-python",
            "installer",
            "3 new commits",
        )
        assert row["Selected"] is True
        assert "Restart NDI after updating." in row["Notes"]
        assert summary["CanUpdate"] is True

    def test_pip_install_cannot_check(self):
        rows, summary = packageStatus({"InstallType": "pip", "Message": "pip says no.\nmore"})
        assert rows[0]["Status"] == "Could not check"
        assert rows[0]["Notes"] == ["pip says no."]
        assert summary["AnyUpdate"] is False


# ---- install(Packages=...) -------------------------------------------------------


@needs_git
class TestInstallPackages:
    def test_only_the_named_dependency_is_pulled(self, clones):
        clones.push_upstream("NDI-python", text="ndi update")
        clones.push_upstream("vhlab-toolbox-python", text="dep update")
        run_install(clones, Packages=["vhlab-toolbox-python"])
        assert "dep update" in (clones.dep / "README.md").read_text()
        assert "ndi update" not in (clones.ndi / "README.md").read_text()
        r = run_check(clones)
        assert r["Dependencies"][0]["Status"] == "upToDate"
        assert r["CommitsBehind"] == 1

    def test_dependency_update_ignores_the_ndi_branch_and_its_changes(self, clones):
        clones.push_upstream("NDI-python")
        clones.push_upstream("vhlab-toolbox-python", text="dep update")
        git(clones.ndi, "checkout", "-q", "-b", "myFeature")
        (clones.ndi / "README.md").write_text("my edit")
        run_install(clones, Packages=["vhlab-toolbox-python"])  # no consent needed
        assert "dep update" in (clones.dep / "README.md").read_text()
        assert (clones.ndi / "README.md").read_text() == "my edit"

    def test_named_changes_still_need_consent_and_survive(self, clones):
        seed = clones.seeds / "vhlab-toolbox-python"
        (seed / "notes.txt").write_text("original\n")
        commit_all(seed, "notes")
        git(seed, "push", "-q", "origin", "main")
        git(clones.dep, "pull", "-q")
        clones.push_upstream("vhlab-toolbox-python", text="dep update")
        (clones.dep / "notes.txt").write_text("mine\n")
        with pytest.raises(UpdateError) as err:
            run_install(clones, Packages=["vhlab-toolbox-python"])
        assert err.value.identifier == "ndi:update:install:localModifications"
        run_install(clones, Packages=["vhlab-toolbox-python"], AllowModified=True)
        assert (clones.dep / "notes.txt").read_text() == "mine\n"
        assert "dep update" in (clones.dep / "README.md").read_text()

    def test_naming_ndi_python_needs_main_and_the_installer(self, clones):
        clones.push_upstream("NDI-python")
        with pytest.raises(UpdateError) as err:
            run_install(clones, Packages=["NDI-python"])
        assert err.value.identifier == "ndi:update:install:noInstaller"
        git(clones.ndi, "checkout", "-q", "-b", "myFeature")
        with pytest.raises(UpdateError) as err:
            run_install(clones, Packages=["NDI-python"])
        assert err.value.identifier == "ndi:update:install:notOnMain"

    def test_ndi_python_alone_reinstalls_without_updating_dependencies(self, clones):
        marker = clones.root / "ran.txt"
        seed = clones.seeds / "NDI-python"
        (seed / "ndi_install.py").write_text(
            "import pathlib, sys\n"
            f"pathlib.Path({str(marker)!r}).write_text('ran ' + ' '.join(sys.argv[1:]))\n"
        )
        commit_all(seed, "add installer")
        git(seed, "push", "-q", "origin", "main")
        git(clones.ndi, "pull", "-q")
        clones.push_upstream("NDI-python", text="ndi update")
        clones.push_upstream("vhlab-toolbox-python", text="dep update")
        run_install(clones, Packages=["NDI-python"])
        assert "ndi update" in (clones.ndi / "README.md").read_text()
        assert marker.read_text() == "ran "  # no --update: the clones are left alone
        assert "dep update" not in (clones.dep / "README.md").read_text()

    def test_up_to_date_and_unknown_packages(self, clones):
        assert run_install(clones, Packages=["vhlab-toolbox-python"])["UpdateAvailable"] is False
        with pytest.raises(UpdateError) as err:
            run_install(clones, Packages=["NDI-matlab"])
        assert err.value.identifier == "ndi:update:install:unknownPackage"
        assert "NDI-python, vhlab-toolbox-python" in str(err.value)


# ---- the dialog's decisions ----------------------------------------------------


def _row(name="P", notes=(), levels=(), touches=False, selectable=True):
    return {
        "Name": name,
        "Installed": "a",
        "Latest": "b",
        "Status": "1 new commit",
        "Notes": list(notes),
        "NoteLevels": list(levels),
        "TouchesChanges": touches,
        "Selectable": selectable,
    }


class TestDialogDecisions:
    def test_note_text_shows_the_most_serious(self):
        assert note_text(_row()) == ""
        row = _row(notes=["fyi", "bad", "careful"], levels=["info", "error", "warning"])
        assert note_text(row) == "bad (+2 more)"

    def test_table_data(self):
        rows = [_row("A", ["fyi"], ["info"]), _row("B")]
        assert table_data(rows, [True, False]) == [
            [True, "A", "a", "b", "1 new commit", "fyi"],
            [False, "B", "a", "b", "1 new commit", ""],
        ]

    def test_update_button_state(self):
        rows = [_row("A"), _row("B", touches=True)]
        assert update_button_state(rows, [False, False]) == ("Update", False)
        assert update_button_state(rows, [True, False]) == ("Update (1)", True)
        assert update_button_state(rows, [True, True]) == ("Update anyway (2)", True)


# ---- the window --------------------------------------------------------------------


def _qt_or_skip():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from ndi.gui._qt_helpers import get_or_create_app

        return get_or_create_app()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no usable Qt platform plugin: {exc}")


@needs_git
class TestUpdateDialogWindow:
    def test_ticks_buttons_and_details(self, clones):
        _qt_or_skip()
        from ndi.gui.nav.update_dialog import UpdateDialog

        clones.push_upstream("vhlab-toolbox-python")
        (clones.dep / "README.md").write_text("my edit")
        d = UpdateDialog(run_check(clones))
        assert d.table.rowCount() == 2
        # NDI-python is up to date: it cannot be ticked, and stays unticked.
        d.set_selected(0, True)
        assert d.selected[0] is False
        # The dependency has your changes: unticked at first, so Update is off
        # and Cancel the default.
        assert d.selected[1] is False
        assert not d.update_button.isEnabled()
        assert d.cancel_button.isDefault()
        assert "my edit" not in d.details.toPlainText()  # files, not contents
        assert "README.md" in d.details.toPlainText()
        d.set_selected(1, True)
        assert d.update_button.text() == "Update anyway (1)"
        assert d.cancel_button.isDefault()
        assert d.selected_packages() == ["vhlab-toolbox-python"]
        d.choose("update")
        assert d.choice == "update"

    def test_nothing_to_do_says_close(self, clones):
        _qt_or_skip()
        from ndi.gui.nav.update_dialog import UpdateDialog

        d = UpdateDialog(run_check(clones))
        assert d.cancel_button.text() == "Close"
        assert d.update_button.text() == "Update"
        assert not d.update_button.isEnabled()


# ---- the navigator's Update button -----------------------------------------------


class _FakeNavigator:
    figure = object()

    def __init__(self):
        self.alerts = []

    def alert(self, message, title, *, success=True):
        self.alerts.append((message, success))


class TestNdiPaneUpdateButton:
    def test_installs_only_the_ticked_packages(self, monkeypatch):
        import ndi.update
        from ndi.gui.nav.ndi_pane import NdiPane

        result = {
            "InstallType": "git",
            "Status": "updateAvailable",
            "UpdateAvailable": True,
            "CommitsBehind": 0,
            "Branch": "main",
            "RepoRoot": "/x",
            "Dependencies": [
                {
                    "Name": "dep",
                    "Path": "/d",
                    "Status": "behind",
                    "CommitsBehind": 2,
                    "CurrentVersion": "a",
                    "LatestVersion": "b",
                    "Url": "",
                }
            ],
            "Modifications": [],
        }
        installed = []
        monkeypatch.setattr(ndi.update, "check", lambda **kw: result)
        monkeypatch.setattr(ndi.update, "install", lambda **kw: installed.append(kw))
        pane = NdiPane(_FakeNavigator())
        monkeypatch.setattr(pane, "_ask", lambda r: (True, ["dep"]))
        assert pane.check_for_updates() is result
        assert installed == [{"Confirm": False, "AllowModified": True, "Packages": ["dep"]}]
        message, success = pane.navigator.alerts[-1]
        assert success and message.startswith("Updated: dep.")

    def test_cancel_installs_nothing(self, monkeypatch):
        import ndi.update
        from ndi.gui.nav.ndi_pane import NdiPane

        installed = []
        monkeypatch.setattr(ndi.update, "check", lambda **kw: {"InstallType": "pip"})
        monkeypatch.setattr(ndi.update, "install", lambda **kw: installed.append(kw))
        pane = NdiPane(_FakeNavigator())
        monkeypatch.setattr(pane, "_ask", lambda r: (False, []))
        pane.check_for_updates()
        assert installed == []
        assert pane.navigator.alerts == []
