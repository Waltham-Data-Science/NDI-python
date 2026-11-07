"""Tests for ndi.update.tools_folder (toolsFolder, moveToolsFolder).

MATLAB counterparts: ndi.update.toolsFolder, ndi.update.moveToolsFolder
(tests/+ndi/+unittest/+update/TestMoveToolsFolder.m).

Every move is of a small fake tools folder in tmp_path, with its own
ndi-deps.pth (the From and PthFile arguments), so the real environment is
never touched. The checks that matter most are the "nothing changed" ones: a
refused move must leave the tools, and the .pth file, exactly as they were.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from ndi.update import tools_folder as tf
from ndi.update.install import UpdateError

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def fake(tmp_path):
    """A tools folder holding one dependency clone, and a .pth pointing into it."""
    tools = tmp_path / "tools"
    dep = tools / "vhlab-toolbox-python"
    (dep / ".git").mkdir(parents=True)
    (dep / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (dep / "vlt").mkdir()
    (dep / "vlt" / "__init__.py").write_text("# vlt\n")
    pth = tmp_path / "site-packages" / tf.PTH_FILENAME
    pth.parent.mkdir()
    pth.write_text(f"{dep}\n")
    return tools, pth


def move(fake, to, **kwargs):
    tools, pth = fake
    kwargs.setdefault("Confirm", False)
    kwargs.setdefault("UpdatePath", False)
    return tf.moveToolsFolder(str(to), From=str(tools), PthFile=str(pth), **kwargs)


def assert_nothing_changed(fake):
    tools, pth = fake
    assert pth.read_text() == f"{tools / 'vhlab-toolbox-python'}\n"
    assert not Path(str(pth) + ".bak").exists()
    assert (tools / "vhlab-toolbox-python" / "vlt" / "__init__.py").is_file()


class TestToolsFolder:
    def test_from_pth_is_the_parent_of_the_clone(self, fake):
        tools, pth = fake
        assert tf.tools_folder_from_pth(pth) == str(tools)

    def test_from_pth_walks_up_from_a_subfolder(self, fake, tmp_path):
        tools, _ = fake
        pth = tmp_path / "other.pth"
        pth.write_text(f"# comment\n\n{tools / 'vhlab-toolbox-python' / 'vlt'}\n")
        assert tf.tools_folder_from_pth(pth) == str(tools)

    def test_from_missing_pth_is_empty(self, tmp_path):
        assert tf.tools_folder_from_pth(tmp_path / "nope.pth") == ""

    def test_ndi_home_names_the_folder(self, tmp_path):
        assert tf._tools_folder(str(tmp_path)) == tmp_path / "tools"

    def test_pth_is_used_when_there_is_one(self, fake, monkeypatch):
        tools, pth = fake
        monkeypatch.setattr(tf, "find_pth_file", lambda: pth)
        assert tf._tools_folder() == tools

    def test_default_without_pth(self, monkeypatch):
        monkeypatch.setattr(tf, "find_pth_file", lambda: None)
        assert tf._tools_folder() == Path.home() / ".ndi" / "tools"

    def test_not_git_is_empty(self, monkeypatch):
        import ndi.update.install_type as it

        monkeypatch.setattr(it, "installType", lambda: ("installer", {}))
        assert tf.toolsFolder() == ""

    def test_git_is_the_tools_folder(self, fake, monkeypatch):
        import ndi.update.install_type as it

        tools, pth = fake
        monkeypatch.setattr(it, "installType", lambda: ("git", {}))
        monkeypatch.setattr(tf, "find_pth_file", lambda: pth)
        assert tf.toolsFolder() == str(tools)


class TestTarget:
    def test_empty_folder_is_used_as_is(self, tmp_path):
        assert tf.tools_folder_target(tmp_path, "/x/tools") == str(tmp_path)

    def test_nonempty_folder_gets_a_subfolder(self, tmp_path):
        (tmp_path / "mine.txt").write_text("x")
        assert tf.tools_folder_target(tmp_path, "/x/tools") == str(tmp_path / "tools")


class TestMove:
    def test_moves_everything(self, fake, tmp_path):
        tools, pth = fake
        to = tmp_path / "new" / "ndi-tools"
        r = move(fake, to)
        assert r["Moved"] and r["OldDeleted"]
        assert not tools.exists()
        new_dep = Path(r["To"]) / "vhlab-toolbox-python"
        assert (new_dep / "vlt" / "__init__.py").is_file()
        assert (new_dep / ".git" / "HEAD").is_file(), "hidden folders move too"
        assert pth.read_text() == f"{new_dep}\n"
        assert Path(r["PthBackup"]).read_text() == f"{tools / 'vhlab-toolbox-python'}\n"

    def test_keeps_old_folder_when_asked(self, fake, tmp_path):
        tools, _ = fake
        r = move(fake, tmp_path / "ndi-tools", DeleteOld=False)
        assert r["Moved"] and not r["OldDeleted"]
        assert (tools / "vhlab-toolbox-python" / "vlt" / "__init__.py").is_file()

    def test_empty_existing_folder_is_used(self, fake, tmp_path):
        to = tmp_path / "empty"
        to.mkdir()
        r = move(fake, to)
        assert (Path(r["To"]) / "vhlab-toolbox-python").is_dir()

    def test_other_pth_lines_are_kept(self, fake):
        tools, pth = fake
        pth.write_text(
            f"# made by ndi_install.py\n/elsewhere/pkg\n{tools / 'vhlab-toolbox-python'}\n"
        )
        r = move(fake, tools.parent / "ndi-tools")
        lines = pth.read_text().splitlines()
        assert lines[:2] == ["# made by ndi_install.py", "/elsewhere/pkg"]
        assert lines[2] == str(Path(r["To"]) / "vhlab-toolbox-python")

    def test_updates_sys_path(self, fake, tmp_path, monkeypatch):
        tools, _ = fake
        monkeypatch.setattr(sys, "path", [*sys.path, str(tools / "vhlab-toolbox-python")])
        r = move(fake, tmp_path / "ndi-tools", UpdatePath=True)
        assert str(Path(r["To"]) / "vhlab-toolbox-python") in sys.path
        assert str(tools / "vhlab-toolbox-python") not in sys.path

    def test_tilde_is_expanded(self, fake, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        r = move(fake, "~/ndi-tools")
        assert r["To"] == str((tmp_path / "ndi-tools").resolve())

    def test_answering_no_changes_nothing(self, fake, tmp_path, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _prompt: "n")
        r = move(fake, tmp_path / "ndi-tools", Confirm=True)
        assert not r["Moved"]
        assert not (tmp_path / "ndi-tools").exists()
        assert_nothing_changed(fake)

    @pytest.mark.parametrize(
        "where, identifier",
        [
            (lambda tools: tools / "inside", "insideOld"),
            (lambda tools: tools, "sameFolder"),
            (lambda tools: Path("ndi-tools"), "relativePath"),
        ],
    )
    def test_refuses(self, fake, where, identifier):
        tools, _ = fake
        with pytest.raises(UpdateError) as err:
            move(fake, where(tools))
        assert err.value.identifier == f"ndi:update:moveToolsFolder:{identifier}"
        assert_nothing_changed(fake)

    def test_refuses_nonempty_folder(self, fake, tmp_path):
        to = tmp_path / "full"
        to.mkdir()
        (to / "mine.txt").write_text("keep me")
        with pytest.raises(UpdateError) as err:
            move(fake, to)
        assert err.value.identifier == "ndi:update:moveToolsFolder:notEmpty"
        assert (to / "mine.txt").read_text() == "keep me"
        assert_nothing_changed(fake)

    def test_refuses_pth_without_line(self, fake, tmp_path):
        tools, pth = fake
        pth.write_text("/elsewhere/pkg\n")
        with pytest.raises(UpdateError) as err:
            move(fake, tmp_path / "ndi-tools")
        assert err.value.identifier == "ndi:update:moveToolsFolder:noPthLine"
        assert not (tmp_path / "ndi-tools").exists(), "nothing is copied before the checks pass"
        assert (tools / "vhlab-toolbox-python").is_dir()

    def test_refuses_missing_pth(self, fake, tmp_path):
        tools, pth = fake
        pth.unlink()
        with pytest.raises(UpdateError) as err:
            move(fake, tmp_path / "ndi-tools")
        assert err.value.identifier == "ndi:update:moveToolsFolder:noPthFile"

    def test_failed_copy_is_removed(self, fake, tmp_path, monkeypatch):
        def broken_copytree(src, dst, **kwargs):
            Path(dst).mkdir(parents=True)
            (Path(dst) / "partial").write_text("x")
            raise OSError("disk full")

        monkeypatch.setattr(tf.shutil, "copytree", broken_copytree)
        with pytest.raises(UpdateError) as err:
            move(fake, tmp_path / "ndi-tools")
        assert err.value.identifier == "ndi:update:moveToolsFolder:copyFailed"
        assert not (tmp_path / "ndi-tools").exists()
        assert_nothing_changed(fake)


class TestInstallerScript:
    """ndi_install.py, with no --tools-dir, reuses the folder ndi-deps.pth names."""

    @staticmethod
    def load_script():
        spec = importlib.util.spec_from_file_location("ndi_install_script", REPO / "ndi_install.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_existing_tools_dir(self, fake):
        tools, pth = fake
        script = self.load_script()
        assert script.existing_tools_dir(pth.parent) == tools

    def test_no_pth_means_default(self, tmp_path):
        script = self.load_script()
        assert script.existing_tools_dir(tmp_path) is None
        assert script.existing_tools_dir(None) is None


class TestEditorButton:
    """The preferences editor's Tools folder... button, without a display."""

    @staticmethod
    def editor(tmp_path, answers, picked):
        from ndi.gui.preferences_editor import PreferencesEditor
        from ndi.preferences import ndi_preferences

        ed = PreferencesEditor(prefs=ndi_preferences(filename=tmp_path / "prefs.json"), build=False)
        replies = iter(answers)
        ed._confirm = lambda message, title, ok_text: next(replies)
        ed._pick_folder = lambda start: picked
        ed.alerts = []
        ed._alert = lambda message, title, success=True: ed.alerts.append((title, message))
        return ed

    def test_moves_after_two_yeses(self, fake, tmp_path, monkeypatch):
        tools, pth = fake
        monkeypatch.setattr(tf, "toolsFolder", lambda: str(tools))
        monkeypatch.setattr(tf, "find_pth_file", lambda: pth)
        new = tmp_path / "chosen"
        new.mkdir()
        ed = self.editor(tmp_path, [True, True], str(new))
        result = ed.on_tools_folder()
        assert result["Moved"]
        assert result["To"] == str(new.resolve())
        assert ed.alerts[-1][0] == "Tools folder moved"

    def test_cancel_changes_nothing(self, fake, tmp_path, monkeypatch):
        tools, _ = fake
        monkeypatch.setattr(tf, "toolsFolder", lambda: str(tools))
        called = []
        monkeypatch.setattr(tf, "moveToolsFolder", lambda *a, **k: called.append(a))
        ed = self.editor(tmp_path, [True, False], str(tmp_path / "chosen"))
        assert ed.on_tools_folder() is None
        assert called == []

    def test_not_git_says_so(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tf, "toolsFolder", lambda: "")
        ed = self.editor(tmp_path, [], "")
        assert ed.on_tools_folder() is None
        assert ed.alerts and "ndi_install.py" in ed.alerts[0][1]

    def test_error_is_shown(self, fake, tmp_path, monkeypatch):
        tools, _ = fake
        monkeypatch.setattr(tf, "toolsFolder", lambda: str(tools))
        ed = self.editor(tmp_path, [True, True], str(tools / "vhlab-toolbox-python"))
        assert ed.on_tools_folder() is None
        assert ed.alerts[-1][0] == "Could not move the tools folder"

    def test_button_exists(self, tmp_path):
        pytest.importorskip("PySide6")
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6 import QtWidgets

        from ndi.gui.preferences_editor import PreferencesEditor
        from ndi.preferences import ndi_preferences

        try:
            ed = PreferencesEditor(prefs=ndi_preferences(filename=tmp_path / "prefs.json"))
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"no usable Qt platform plugin: {exc}")
        button = ed.figure.findChild(QtWidgets.QPushButton, "ndiPrefToolsFolderButton")
        assert button is not None and button.text() == "Tools folder..."
