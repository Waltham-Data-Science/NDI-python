"""Tests for ndi.gui.app.vh_ndi_spike_sorter.

MATLAB counterpart: ndi.gui.app.vhNDISpikeSorter

This app is an availability check, a sentence and a button, so the tests are
about the check and the sentence.

The one that matters most is that the window NEVER CLAIMS THE SORTER IS
THERE WHEN IT IS NOT. A window saying "available" over a disabled button, or
over a sorter that will not launch, sends someone hunting a bug in the
sorter instead of installing it. The unavailable message is pinned for the
same reason: telling a Python user to "install vhlab-library-matlab" would
send them after a pip package that does not exist, since the library is
MATLAB.

The launcher is resolved by NAME rather than hardcoded absent, so both
states are reachable in a test -- and so a lab that ships a Python
``vhNDISpikeSorter.spikesorting`` gets a working button. The fixtures below
put such a module in and take it out again.

The Qt tests skip without PySide6, as elsewhere in this package.
"""

from __future__ import annotations

import os
import sys
import types

import pytest

from ndi.gui.app import SessionApp
from ndi.gui.app.vh_ndi_spike_sorter import (
    AVAILABLE_MESSAGE,
    DEFAULT_POSITION,
    LAUNCHER,
    LAUNCHER_FUNCTION,
    LAUNCHER_MODULE,
    NOT_FOUND_ALERT,
    UNAVAILABLE_MESSAGE,
    WINDOW_TAG,
    availability_message,
    resolve_launcher,
    vhNDISpikeSorter,
)


class FakeSession:
    def __init__(self, reference="2024-01-01"):
        self.reference = reference


def _absent(*names):
    """An import_module that fails for NAMES and behaves normally otherwise.

    Selective on purpose. A stub that raised for everything would also break
    the imports pytest and the Qt helper make while the patch is live, which
    turns "the sorter is missing" into "nothing works" -- a different test
    from the one intended, and one that passes for the wrong reason.
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
def no_launcher(monkeypatch):
    """The stock state: nothing named vhNDISpikeSorter is importable."""
    monkeypatch.delitem(sys.modules, LAUNCHER_MODULE, raising=False)
    monkeypatch.setattr(
        "ndi.gui.app.vh_ndi_spike_sorter.importlib.import_module",
        _absent(LAUNCHER_MODULE),
    )


@pytest.fixture
def with_launcher(monkeypatch):
    """A Python launcher of the expected name, as a lab's binding would be.

    Returns the dict the launcher records its keyword arguments into, so a
    test can check what the app handed it.
    """
    calls: dict = {}
    module = types.ModuleType(LAUNCHER_MODULE)

    def spikesorting(**kwargs):
        calls.update(kwargs)
        return "sorter-window"

    setattr(module, LAUNCHER_FUNCTION, spikesorting)
    monkeypatch.setitem(sys.modules, LAUNCHER_MODULE, module)
    return calls


# ----------------------------------------------------------------------
# resolving the launcher
# ----------------------------------------------------------------------
class TestResolveLauncher:
    def test_an_absent_module_resolves_to_nothing(self, no_launcher):
        assert resolve_launcher() is None

    def test_a_present_launcher_resolves_to_it(self, with_launcher):
        launcher = resolve_launcher()
        assert callable(launcher)
        assert launcher(ndiSession="s") == "sorter-window"

    def test_a_module_without_the_function_resolves_to_nothing(self, monkeypatch):
        """Half an installation is not an installation."""
        monkeypatch.setitem(sys.modules, LAUNCHER_MODULE, types.ModuleType(LAUNCHER_MODULE))
        assert resolve_launcher() is None

    def test_a_name_that_is_not_callable_resolves_to_nothing(self, monkeypatch):
        module = types.ModuleType(LAUNCHER_MODULE)
        setattr(module, LAUNCHER_FUNCTION, "not a function")
        monkeypatch.setitem(sys.modules, LAUNCHER_MODULE, module)
        assert resolve_launcher() is None

    def test_a_module_that_raises_on_import_resolves_to_nothing(self, monkeypatch):
        """Broken and absent mean the same thing here: cannot launch. An
        exception would take the window down with it, and a window that will
        not open cannot say why."""

        def boom(name):
            raise RuntimeError("the library is half-installed")

        monkeypatch.setattr("ndi.gui.app.vh_ndi_spike_sorter.importlib.import_module", boom)
        assert resolve_launcher() is None

    def test_the_name_is_matlabs(self):
        """The external contract, spelled as MATLAB spells it."""
        assert LAUNCHER == "vhNDISpikeSorter.spikesorting"
        assert (LAUNCHER_MODULE, LAUNCHER_FUNCTION) == ("vhNDISpikeSorter", "spikesorting")


# ----------------------------------------------------------------------
# what the window says
# ----------------------------------------------------------------------
class TestMessages:
    def test_available_says_what_to_do_next(self):
        assert availability_message(True) == AVAILABLE_MESSAGE
        assert "Click below" in AVAILABLE_MESSAGE

    def test_unavailable_says_the_library_is_matlab(self):
        """MATLAB's wording ("add vhlab-library-matlab to the MATLAB path")
        would send a Python user after a pip package that does not exist."""
        assert availability_message(False) == UNAVAILABLE_MESSAGE
        assert "MATLAB library" in UNAVAILABLE_MESSAGE

    def test_unavailable_names_both_ways_forward(self):
        """Run it from MATLAB, or supply a Python launcher -- those are the
        only two, and a user cannot guess the second."""
        assert "from MATLAB" in UNAVAILABLE_MESSAGE
        assert LAUNCHER in UNAVAILABLE_MESSAGE

    def test_the_two_messages_are_different(self):
        assert AVAILABLE_MESSAGE != UNAVAILABLE_MESSAGE


# ----------------------------------------------------------------------
# the model, without Qt
# ----------------------------------------------------------------------
def _app(session=None):
    return vhNDISpikeSorter(session or FakeSession(), build=False)


class TestAvailability:
    def test_no_launcher_is_not_available(self, no_launcher):
        assert _app().is_available() is False

    def test_a_launcher_is_available(self, with_launcher):
        assert _app().is_available() is True

    def test_the_status_text_follows_the_state(self, no_launcher):
        assert _app().status_text() == UNAVAILABLE_MESSAGE

    def test_availability_is_asked_fresh_each_time(self, monkeypatch):
        """A user can install the library while the window is open; MATLAB
        re-asks and so does this, so a cached "no" never sticks."""
        app = _app()
        monkeypatch.setattr(
            "ndi.gui.app.vh_ndi_spike_sorter.importlib.import_module", _absent(LAUNCHER_MODULE)
        )
        assert app.is_available() is False

        module = types.ModuleType(LAUNCHER_MODULE)
        setattr(module, LAUNCHER_FUNCTION, lambda **kw: None)
        monkeypatch.setattr(
            "ndi.gui.app.vh_ndi_spike_sorter.importlib.import_module", lambda name: module
        )
        assert app.is_available() is True


# ----------------------------------------------------------------------
# discovery
# ----------------------------------------------------------------------
class TestDiscovery:
    def test_the_app_is_found_by_scanning_ndi_gui_app(self):
        names = [app["Name"] for app in SessionApp.list(["ndi.gui.app"])]
        assert "VHLab Spike Sorter" in names

    def test_it_reports_the_class_launch_can_resolve(self):
        from ndi.gui.app.session_app import resolve_class

        entry = next(
            a for a in SessionApp.list(["ndi.gui.app"]) if a["Name"] == "VHLab Spike Sorter"
        )
        assert resolve_class(entry["Class"]) is vhNDISpikeSorter

    def test_the_menu_label_is_matlabs_verbatim(self):
        assert vhNDISpikeSorter.Name == "VHLab Spike Sorter"

    def test_it_groups_under_spike_sorters(self):
        """The submenu it shares with kiasort, when that lands."""
        assert vhNDISpikeSorter.Category == "Spike Sorters"

    def test_its_category_reaches_the_menu_record(self):
        entry = next(
            a for a in SessionApp.list(["ndi.gui.app"]) if a["Name"] == "VHLab Spike Sorter"
        )
        assert entry["Category"] == "Spike Sorters"


class TestNaming:
    def test_every_public_method_is_snake_case(self):
        """The house style for new code. The CLASS name stays MATLAB's,
        matching the .m file."""
        import re

        offenders = [
            name
            for name in vars(vhNDISpikeSorter)
            if not name.startswith("_")
            and name not in ("Name", "Category")
            and re.search(r"[a-z][A-Z]", name)
        ]
        assert offenders == []

    def test_a_pascal_case_alias_names_the_same_class(self):
        from ndi.gui.app.vh_ndi_spike_sorter import VHNDISpikeSorter

        assert VHNDISpikeSorter is vhNDISpikeSorter


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
    return vhNDISpikeSorter(session or FakeSession())


class TestWindow:
    def test_the_window_names_the_session_and_is_tagged(self, no_launcher):
        app = _window()
        assert app.figure.windowTitle() == "VHLab Spike Sorter: 2024-01-01"
        assert app.figure.objectName() == WINDOW_TAG
        app.close()

    def test_it_opens_where_matlab_opens_it(self, no_launcher):
        app = _window()
        assert app.position == DEFAULT_POSITION
        app.close()

    def test_it_opens_even_with_no_sorter_installed(self, no_launcher):
        """The whole point: the app has to be openable either way, or a user
        learns they need a library from a stack trace."""
        app = _window()
        assert app.figure is not None
        assert app.status_label.text() == UNAVAILABLE_MESSAGE
        app.close()

    def test_the_button_is_dead_when_the_sorter_is_absent(self, no_launcher):
        app = _window()
        assert app.open_button.isEnabled() is False
        app.close()

    def test_the_button_is_live_when_the_sorter_is_there(self, with_launcher):
        app = _window()
        assert app.open_button.isEnabled() is True
        assert app.status_label.text() == AVAILABLE_MESSAGE
        app.close()

    def test_the_message_wraps(self, no_launcher):
        """It is two sentences in a 460px window; unwrapped it is cut off
        mid-word, which is where the actionable half lives."""
        app = _window()
        assert app.status_label.wordWrap() is True
        app.close()

    def test_refreshing_picks_up_a_library_that_appeared(self, monkeypatch):
        app = _window()
        monkeypatch.setattr(
            "ndi.gui.app.vh_ndi_spike_sorter.importlib.import_module", _absent(LAUNCHER_MODULE)
        )
        app.refresh_availability()
        assert app.open_button.isEnabled() is False

        module = types.ModuleType(LAUNCHER_MODULE)
        setattr(module, LAUNCHER_FUNCTION, lambda **kw: None)
        monkeypatch.setattr(
            "ndi.gui.app.vh_ndi_spike_sorter.importlib.import_module", lambda name: module
        )

        assert app.refresh_availability() is True
        assert app.open_button.isEnabled() is True
        assert app.status_label.text() == AVAILABLE_MESSAGE
        app.close()


class TestOpening:
    def test_it_hands_the_session_to_the_sorter(self, with_launcher):
        """Under MATLAB's keyword, 'ndiSession': the sorter's contract, not
        NDI's, so it keeps MATLAB's spelling."""
        session = FakeSession()
        app = _window(session)

        result = app.open_sorter()

        assert result == "sorter-window"
        assert with_launcher["ndiSession"] is session
        app.close()

    def test_pressing_it_with_no_sorter_says_so_and_launches_nothing(self, no_launcher):
        app = _window()
        seen = {}
        app.alert = lambda message, title, **k: seen.update(message=message, title=title)

        assert app.open_sorter() is None
        assert seen["title"] == "Spike sorter not found"
        assert seen["message"] == NOT_FOUND_ALERT
        app.close()

    def test_a_sorter_that_vanished_is_caught_at_the_press(self, with_launcher, monkeypatch):
        """The window may have been open a while. MATLAB re-checks at the
        press and so does this, rather than calling into nothing."""
        app = _window()
        assert app.open_button.isEnabled() is True

        monkeypatch.setattr(
            "ndi.gui.app.vh_ndi_spike_sorter.importlib.import_module", _absent(LAUNCHER_MODULE)
        )
        seen = {}
        app.alert = lambda message, title, **k: seen.update(title=title)

        assert app.open_sorter() is None
        assert seen["title"] == "Spike sorter not found"
        assert app.open_button.isEnabled() is False  # the window caught up too
        app.close()

    def test_a_sorter_that_raises_is_reported_not_propagated(self, monkeypatch):
        """Its failure is its own; the app reports it and stays open."""
        module = types.ModuleType(LAUNCHER_MODULE)

        def broken(**kwargs):
            raise RuntimeError("no spike waveforms in this session")

        setattr(module, LAUNCHER_FUNCTION, broken)
        monkeypatch.setitem(sys.modules, LAUNCHER_MODULE, module)

        app = _window()
        seen = {}
        app.alert = lambda message, title, **k: seen.update(message=message, title=title)

        assert app.open_sorter() is None
        assert seen["title"] == "Could not open the VH Lab spike sorter"
        assert "no spike waveforms" in seen["message"]
        app.close()


class TestLaunching:
    def test_launch_constructs_it_with_the_session(self, no_launcher):
        _qt_or_skip()
        session = FakeSession()
        app = SessionApp.launch("ndi.gui.app.vh_ndi_spike_sorter.vhNDISpikeSorter", session)
        assert isinstance(app, vhNDISpikeSorter)
        assert app.session is session
        app.close()
