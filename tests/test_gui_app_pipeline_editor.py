"""Tests for ndi.gui.app.pipeline_editor.

MATLAB counterpart: ndi.gui.app.pipelineEditor

The app is a launcher window over ndi.cpipeline.edit, which on MATLAB is a
native GUI and on Python is not ported yet. So the tests are about:

* the availability check -- resolving ndi.cpipeline.edit by name, with
  every failure collapsing to None (module absent, module raises on
  import, function missing, name not callable);
* the window opening either way, so a user does not learn 'it is not
  ported' from a stack trace;
* the unavailable message saying what is actually true and what actually
  works (run it from MATLAB), rather than telling a Python user to
  install a package that does not exist; and
* the launcher, when present, receiving MATLAB's keywords verbatim --
  ``command='new'`` and ``session=SESSION`` -- so the day
  ndi.cpipeline.edit lands as a Python module this app picks it up.

The Qt tests skip without PySide6, as elsewhere in this package.
"""

from __future__ import annotations

import os
import sys
import types

import pytest

from ndi.gui.app import SessionApp
from ndi.gui.app.pipeline_editor import (
    AVAILABLE_MESSAGE,
    DEFAULT_POSITION,
    EDITOR_FUNCTION,
    EDITOR_MODULE,
    EDITOR_TARGET,
    NOT_FOUND_ALERT,
    UNAVAILABLE_MESSAGE,
    WINDOW_TAG,
    availability_message,
    pipelineEditor,
    resolve_editor,
)


class FakeSession:
    def __init__(self, reference="2024-01-01"):
        self.reference = reference


def _absent(*names):
    """An import_module that fails for NAMES and behaves normally otherwise.

    Selective, so the imports pytest and the Qt helper make while the patch
    is live keep working; a stub that raised for everything would turn "the
    editor is missing" into "nothing works" and pass for the wrong reason.
    """
    import importlib

    real = importlib.import_module
    wanted = set(names)

    def fake(name, *args, **kwargs):
        if name in wanted:
            raise ModuleNotFoundError(f"No module named {name!r}")
        return real(name, *args, **kwargs)

    return fake


@pytest.fixture
def no_editor(monkeypatch):
    """The stock state: ndi.cpipeline is not importable."""
    monkeypatch.delitem(sys.modules, EDITOR_MODULE, raising=False)
    monkeypatch.setattr(
        "ndi.gui.app.pipeline_editor.importlib.import_module",
        _absent(EDITOR_MODULE),
    )


@pytest.fixture
def with_editor(monkeypatch):
    """A Python editor of the expected name, as a lab's port would be."""
    calls: dict = {}
    module = types.ModuleType(EDITOR_MODULE)

    def edit(**kwargs):
        calls.update(kwargs)
        return "editor-window"

    setattr(module, EDITOR_FUNCTION, edit)
    monkeypatch.setitem(sys.modules, EDITOR_MODULE, module)
    return calls


# ----------------------------------------------------------------------
# constants
# ----------------------------------------------------------------------
class TestConstants:
    def test_the_menu_label_is_matlabs_verbatim(self):
        assert pipelineEditor.Name == "Pipeline Editor"

    def test_matlab_has_no_category_so_neither_does_this(self):
        """MATLAB's pipelineEditor.m declares no Category, so the app sits
        at the top of the Apps menu rather than under a submenu."""
        assert pipelineEditor.Category == ""

    def test_the_window_tag_is_the_matlab_class_path(self):
        assert WINDOW_TAG == "ndi.gui.app.pipelineEditor"

    def test_the_editor_target_is_the_matlab_call(self):
        assert EDITOR_TARGET == "ndi.cpipeline.edit"
        assert (EDITOR_MODULE, EDITOR_FUNCTION) == ("ndi.cpipeline", "edit")

    def test_it_opens_with_the_same_footprint_as_vh_ndi_spike_sorter(self):
        """The two apps play the same role; keep the launcher size in step."""
        assert DEFAULT_POSITION == (100, 100, 460, 200)


# ----------------------------------------------------------------------
# resolving the editor
# ----------------------------------------------------------------------
class TestResolveEditor:
    def test_an_absent_module_resolves_to_nothing(self, no_editor):
        assert resolve_editor() is None

    def test_a_present_editor_resolves_to_it(self, with_editor):
        editor = resolve_editor()
        assert callable(editor)
        assert editor(command="new") == "editor-window"

    def test_a_module_without_the_function_resolves_to_nothing(self, monkeypatch):
        monkeypatch.setitem(sys.modules, EDITOR_MODULE, types.ModuleType(EDITOR_MODULE))
        assert resolve_editor() is None

    def test_a_name_that_is_not_callable_resolves_to_nothing(self, monkeypatch):
        module = types.ModuleType(EDITOR_MODULE)
        setattr(module, EDITOR_FUNCTION, "not a function")
        monkeypatch.setitem(sys.modules, EDITOR_MODULE, module)
        assert resolve_editor() is None

    def test_a_module_that_raises_on_import_resolves_to_nothing(self, monkeypatch):
        def boom(name):
            raise RuntimeError("half-installed")

        monkeypatch.setattr("ndi.gui.app.pipeline_editor.importlib.import_module", boom)
        assert resolve_editor() is None


# ----------------------------------------------------------------------
# messages
# ----------------------------------------------------------------------
class TestMessages:
    def test_available_says_what_to_do_next(self):
        assert availability_message(True) == AVAILABLE_MESSAGE
        assert "Click below" in AVAILABLE_MESSAGE

    def test_unavailable_says_the_editor_is_not_ported(self):
        """MATLAB's silence on the failure path (the editor is native
        there) does not translate: a Python user hearing 'not found' would
        pip-install something that does not exist."""
        assert availability_message(False) == UNAVAILABLE_MESSAGE
        assert "not been ported" in UNAVAILABLE_MESSAGE

    def test_unavailable_names_both_ways_forward(self):
        assert "from MATLAB" in UNAVAILABLE_MESSAGE
        assert EDITOR_TARGET in UNAVAILABLE_MESSAGE

    def test_the_two_messages_are_different(self):
        assert AVAILABLE_MESSAGE != UNAVAILABLE_MESSAGE


# ----------------------------------------------------------------------
# discovery
# ----------------------------------------------------------------------
class TestDiscovery:
    def test_the_app_is_found_by_scanning_ndi_gui_app(self):
        names = [app["Name"] for app in SessionApp.list(["ndi.gui.app"])]
        assert "Pipeline Editor" in names

    def test_it_reports_the_class_launch_can_resolve(self):
        from ndi.gui.app.session_app import resolve_class

        entry = next(a for a in SessionApp.list(["ndi.gui.app"]) if a["Name"] == "Pipeline Editor")
        assert resolve_class(entry["Class"]) is pipelineEditor


class TestNaming:
    def test_every_public_method_is_snake_case(self):
        import re

        offenders = [
            name
            for name in vars(pipelineEditor)
            if not name.startswith("_")
            and name not in ("Name", "Category")
            and re.search(r"[a-z][A-Z]", name)
        ]
        assert offenders == []

    def test_a_pascal_case_alias_names_the_same_class(self):
        from ndi.gui.app.pipeline_editor import PipelineEditor

        assert PipelineEditor is pipelineEditor


# ----------------------------------------------------------------------
# model, without Qt
# ----------------------------------------------------------------------
def _app(session=None):
    return pipelineEditor(session or FakeSession(), build=False)


class TestAvailability:
    def test_no_editor_is_not_available(self, no_editor):
        assert _app().is_available() is False

    def test_an_editor_is_available(self, with_editor):
        assert _app().is_available() is True

    def test_the_status_text_follows_the_state(self, no_editor):
        assert _app().status_text() == UNAVAILABLE_MESSAGE


# ----------------------------------------------------------------------
# Qt
# ----------------------------------------------------------------------
def _qt_or_skip():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from ndi.gui._qt_helpers import get_or_create_app

        return get_or_create_app()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no usable Qt platform plugin: {exc}")


def _window(session=None):
    _qt_or_skip()
    return pipelineEditor(session or FakeSession())


class TestWindow:
    def test_the_window_names_the_session_and_is_tagged(self, no_editor):
        app = _window()
        assert app.figure.windowTitle() == "Pipeline Editor: 2024-01-01"
        assert app.figure.objectName() == WINDOW_TAG
        app.close()

    def test_it_opens_even_with_no_editor(self, no_editor):
        """The whole point: the app has to be openable either way, or a
        user learns the editor is unported from a stack trace."""
        app = _window()
        assert app.figure is not None
        assert app.status_label.text() == UNAVAILABLE_MESSAGE
        assert app.open_button.isEnabled() is False
        app.close()

    def test_the_button_is_live_when_an_editor_appears(self, with_editor):
        app = _window()
        assert app.open_button.isEnabled() is True
        assert app.status_label.text() == AVAILABLE_MESSAGE
        app.close()

    def test_refreshing_picks_up_an_editor_that_appeared(self, monkeypatch):
        """A user can add a Python ndi.cpipeline while the window is open."""
        app = _window()
        monkeypatch.setattr(
            "ndi.gui.app.pipeline_editor.importlib.import_module", _absent(EDITOR_MODULE)
        )
        app.refresh_availability()
        assert app.open_button.isEnabled() is False

        module = types.ModuleType(EDITOR_MODULE)
        setattr(module, EDITOR_FUNCTION, lambda **kw: None)
        monkeypatch.setattr(
            "ndi.gui.app.pipeline_editor.importlib.import_module", lambda name: module
        )
        assert app.refresh_availability() is True
        assert app.open_button.isEnabled() is True
        app.close()


class TestOpening:
    def test_it_hands_the_session_to_the_editor(self, with_editor):
        """MATLAB's ('command','new','session',SESSION) round trips through
        the same keyword names, so the same call reaches a Python port."""
        session = FakeSession()
        app = _window(session)

        result = app.open_editor()

        assert result == "editor-window"
        assert with_editor["command"] == "new"
        assert with_editor["session"] is session
        app.close()

    def test_pressing_it_with_no_editor_says_so_and_launches_nothing(self, no_editor):
        app = _window()
        seen = {}
        app.alert = lambda message, title, **k: seen.update(message=message, title=title)
        assert app.open_editor() is None
        assert seen["title"] == "Pipeline editor not found"
        assert seen["message"] == NOT_FOUND_ALERT
        app.close()

    def test_an_editor_that_raises_is_reported_not_propagated(self, monkeypatch):
        module = types.ModuleType(EDITOR_MODULE)

        def broken(**_kwargs):
            raise RuntimeError("bad session state")

        setattr(module, EDITOR_FUNCTION, broken)
        monkeypatch.setitem(sys.modules, EDITOR_MODULE, module)

        app = _window()
        seen = {}
        app.alert = lambda message, title, **k: seen.update(message=message, title=title)
        assert app.open_editor() is None
        assert seen["title"] == "Could not open the NDI pipeline editor"
        assert "bad session state" in seen["message"]
        app.close()


class TestLaunching:
    def test_launch_constructs_it_with_the_session(self, no_editor):
        _qt_or_skip()
        session = FakeSession()
        app = SessionApp.launch("ndi.gui.app.pipeline_editor.pipelineEditor", session)
        assert isinstance(app, pipelineEditor)
        assert app.session is session
        app.close()
