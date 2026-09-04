"""Tests for ndi.gui.app.kiasort.

MATLAB counterpart: ndi.gui.app.kiasort

The window is a probe list, a config block and two buttons. What matters:

* the STATE MACHINE reads the same as MATLAB -- Run enables on an exported
  probe, Curate on a probe that has been run -- so the disabled state is
  never a lie about the pipeline;
* Run and Curate quote the BACKEND'S MATLAB-only sentence when pressed,
  since ndi.fun.probe.import_.kiasort.run / .curate raise
  NotImplementedError on Python (KIASORT itself is MATLAB). A stack trace
  would send someone hunting an installation bug for something that is not
  an installation problem;
* the ``cfg_overrides`` handed to the backend has MATLAB's spelling
  verbatim -- ``useGPU``, ``sortingChunkDuration``, and so on. Those keys
  cross the API boundary into KIASORT and mean the same thing on both
  sides.

The Qt tests skip without PySide6, as elsewhere in this package.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from ndi.gui.app import SessionApp
from ndi.gui.app.kiasort import (
    CHECK_OPTIONS,
    CURATION_FAILED_TITLE,
    DEFAULT_BINARY_NAME,
    DEFAULT_KIASORT_DIR,
    DEFAULT_POSITION,
    DEFAULT_SUBDIR,
    NOT_EXPORTED_SUFFIX,
    NUM_OPTIONS,
    RUN_COMPLETE_TITLE,
    RUN_FAILED_TITLE,
    WINDOW_TAG,
    can_curate,
    can_run,
    config_overrides_from,
    kiasort,
    probe_label,
)


# ----------------------------------------------------------------------
# fake session and probes
# ----------------------------------------------------------------------
class FakeStatus:
    """The minimum of Status the app touches: exported/run/curated + words()."""

    def __init__(self, exported=False, run=False, curated=False):
        self.exported = exported
        self.run = run
        self.curated = curated

    def words(self):
        return [
            name
            for name, held in (
                ("exported", self.exported),
                ("run", self.run),
                ("curated", self.curated),
            )
            if held
        ]


class FakeProbe:
    def __init__(self, name):
        self._name = name

    def elementstring(self):
        return self._name


class FakeSession:
    def __init__(self, probes=(), reference="2024-01-01"):
        self._probes = list(probes)
        self.reference = reference

    def getprobes(self, type=None):  # noqa: A002 - MATLAB's spelling
        assert type == "n-trode", f"unexpected type={type!r}"
        return list(self._probes)


def _app(session=None, statuses=None, **kwargs):
    """Construct the app with build=False and inject controlled statuses.

    ``statuses`` matches the session's probes positionally; when a probe
    has no matching status, None is used (which every consumer treats as
    'nothing known yet'). A ``session`` that raises from ``getprobes``
    still produces an app -- load_probes catches that, per MATLAB.
    """
    session = session or FakeSession()
    probes = list(getattr(session, "_probes", []) or [])
    probe_to_status = dict(zip(probes, statuses or []))
    with mock.patch.object(kiasort, "probe_status", lambda self, p: probe_to_status.get(p)):
        return kiasort(session, build=False, **kwargs)


# ----------------------------------------------------------------------
# constants
# ----------------------------------------------------------------------
class TestConstants:
    def test_the_menu_label_is_matlabs_verbatim(self):
        assert kiasort.Name == "Kiasort"

    def test_it_groups_under_spike_sorters(self):
        """The submenu it shares with vhNDISpikeSorter."""
        assert kiasort.Category == "Spike Sorters"

    def test_the_window_tag_is_the_matlab_class_path(self):
        assert WINDOW_TAG == "ndi.gui.app.kiasort"

    def test_it_opens_where_matlab_opens_it(self):
        assert DEFAULT_POSITION == (100, 100, 560, 545)

    def test_the_filesystem_defaults_match_matlab(self):
        assert DEFAULT_KIASORT_DIR == "kiasort"
        assert DEFAULT_BINARY_NAME == "kiasort.bin"
        assert DEFAULT_SUBDIR == "kiasort_output"

    def test_check_options_are_matlabs_seven(self):
        fields = [row[0] for row in CHECK_OPTIONS]
        assert fields == [
            "useGPU",
            "parallelProcessing",
            "denoising",
            "extremeNoise",
            "sort_only",
            "extractWaveform",
            "parallelSort",
        ]

    def test_num_options_are_matlabs_two(self):
        fields = [row[0] for row in NUM_OPTIONS]
        assert fields == ["sortingChunkDuration", "batch_ch_size"]

    def test_the_only_integer_field_is_batch_ch_size(self):
        """The MATLAB numeric edit-field with RoundFractionalValues on."""
        integer_fields = [row[0] for row in NUM_OPTIONS if row[4]]
        assert integer_fields == ["batch_ch_size"]

    def test_useGPU_and_whitening_default_on(self):  # noqa: N802 - matches MATLAB
        """MATLAB's defaults: everything else is off out of the box."""
        by_field = {row[0]: row[2] for row in CHECK_OPTIONS}
        assert by_field["useGPU"] is True
        assert by_field["denoising"] is True
        for other in ("parallelProcessing", "extremeNoise", "sort_only"):
            assert by_field[other] is False


# ----------------------------------------------------------------------
# probe_label
# ----------------------------------------------------------------------
class TestProbeLabel:
    def test_a_probe_with_no_status_reads_as_not_exported(self):
        assert probe_label(FakeProbe("ctx_1"), None) == f"ctx_1 {NOT_EXPORTED_SUFFIX}"

    def test_a_probe_with_no_words_reads_as_not_exported(self):
        assert probe_label(FakeProbe("ctx_1"), FakeStatus()) == f"ctx_1 {NOT_EXPORTED_SUFFIX}"

    def test_a_probe_words_are_joined_in_pipeline_order(self):
        """Order fixed by Status.words(), so 'run, exported' never comes back."""
        status = FakeStatus(exported=True, run=True)
        assert probe_label(FakeProbe("ctx_1"), status) == "ctx_1 (exported, run)"

    def test_curated_shows_all_three_words(self):
        status = FakeStatus(exported=True, run=True, curated=True)
        assert probe_label(FakeProbe("ctx_1"), status) == "ctx_1 (exported, run, curated)"


# ----------------------------------------------------------------------
# config_overrides_from
# ----------------------------------------------------------------------
class TestConfigOverrides:
    def test_it_builds_a_dict_from_checks_and_nums(self):
        cfg = config_overrides_from({"useGPU": True}, {"batch_ch_size": 64})
        assert cfg == {"useGPU": True, "batch_ch_size": 64}

    def test_check_values_are_coerced_to_bool(self):
        """A Qt CheckState is not a bool; coerce so JSON round-trips are honest."""
        cfg = config_overrides_from({"useGPU": 1, "parallelProcessing": 0}, {})
        assert cfg == {"useGPU": True, "parallelProcessing": False}
        for value in cfg.values():
            assert isinstance(value, bool)

    def test_num_values_pass_through_unchanged(self):
        """MATLAB's edit-field rounds integer fields on entry; so does Qt."""
        cfg = config_overrides_from({}, {"sortingChunkDuration": 120.0, "batch_ch_size": 64})
        assert cfg["sortingChunkDuration"] == 120.0
        assert cfg["batch_ch_size"] == 64


# ----------------------------------------------------------------------
# can_run / can_curate
# ----------------------------------------------------------------------
class TestButtonPredicates:
    def test_no_status_disables_both(self):
        assert can_run(None) is False
        assert can_curate(None) is False

    def test_run_needs_exported(self):
        assert can_run(FakeStatus(exported=True)) is True
        assert can_run(FakeStatus(exported=False, run=True)) is False

    def test_curate_needs_run(self):
        assert can_curate(FakeStatus(exported=True, run=True)) is True
        assert can_curate(FakeStatus(exported=True, run=False)) is False


# ----------------------------------------------------------------------
# model
# ----------------------------------------------------------------------
class TestModel:
    def test_load_probes_returns_the_session_ntrodes(self):
        session = FakeSession([FakeProbe("a"), FakeProbe("b")])
        app = _app(session=session)
        assert app.probes == session._probes

    def test_load_probes_survives_a_broken_session(self):
        class Broken:
            reference = "x"

            def getprobes(self, **_kwargs):
                raise RuntimeError("no probes here")

        app = _app(session=Broken())
        assert app.probes == []

    def test_probe_labels_are_one_per_probe(self):
        a = FakeProbe("a")
        b = FakeProbe("b")
        session = FakeSession([a, b])
        statuses = [FakeStatus(exported=True), FakeStatus(exported=True, run=True)]
        app = _app(session=session, statuses=statuses)
        assert app.probe_labels() == ["a (exported)", "b (exported, run)"]

    def test_refresh_statuses_rereads_and_returns_the_list(self):
        p = FakeProbe("a")
        session = FakeSession([p])
        called = []

        def status(self, probe):
            called.append(probe)
            return FakeStatus(exported=True)

        with mock.patch.object(kiasort, "probe_status", status):
            app = kiasort(session, build=False)
        assert app.refresh_statuses() == app._statuses
        assert called[-1] is p


# ----------------------------------------------------------------------
# probe_status delegation
# ----------------------------------------------------------------------
class TestBackendDelegation:
    def test_probe_status_delegates_to_the_backend(self):
        """Patches the ``status`` name on the imported backend module so the
        call is intercepted whichever way the app imports it."""
        from ndi.fun.probe.import_ import kiasort as kiasort_backend

        session = FakeSession([FakeProbe("a")])
        seen = {}

        def fake_status(S, probe, **kwargs):  # noqa: N803 - MATLAB's parameter name
            seen["S"] = S
            seen["probe"] = probe
            seen.update(kwargs)
            return FakeStatus(exported=True)

        with mock.patch.object(kiasort_backend, "status", fake_status):
            app = kiasort(session, build=False)

        assert isinstance(app._statuses[0], FakeStatus)
        assert seen["S"] is session
        assert seen["probe"] is session._probes[0]
        # MATLAB's parameter spelling, since the port keeps it verbatim.
        assert seen["kiasort_dir"] == DEFAULT_KIASORT_DIR
        assert seen["binaryFileName"] == DEFAULT_BINARY_NAME
        assert seen["subdir"] == DEFAULT_SUBDIR

    def test_probe_status_is_none_on_any_failure(self):
        from ndi.fun.probe.import_ import kiasort as kiasort_backend

        session = FakeSession([FakeProbe("a")])

        def boom(*_args, **_kwargs):
            raise RuntimeError("bad export layout")

        with mock.patch.object(kiasort_backend, "status", boom):
            app = kiasort(session, build=False)

        assert app._statuses == [None]


# ----------------------------------------------------------------------
# discovery
# ----------------------------------------------------------------------
class TestDiscovery:
    def test_the_app_is_found_by_scanning_ndi_gui_app(self):
        names = [app["Name"] for app in SessionApp.list(["ndi.gui.app"])]
        assert "Kiasort" in names

    def test_it_reports_the_class_launch_can_resolve(self):
        from ndi.gui.app.session_app import resolve_class

        entry = next(a for a in SessionApp.list(["ndi.gui.app"]) if a["Name"] == "Kiasort")
        assert resolve_class(entry["Class"]) is kiasort

    def test_its_category_reaches_the_menu_record(self):
        entry = next(a for a in SessionApp.list(["ndi.gui.app"]) if a["Name"] == "Kiasort")
        assert entry["Category"] == "Spike Sorters"


class TestNaming:
    def test_every_public_method_is_snake_case(self):
        """The house style for new code. The CLASS name stays MATLAB's,
        matching the .m file."""
        import re

        offenders = [
            name
            for name in vars(kiasort)
            if not name.startswith("_")
            and name not in ("Name", "Category")
            and re.search(r"[a-z][A-Z]", name)
        ]
        assert offenders == []

    def test_a_pascal_case_alias_names_the_same_class(self):
        from ndi.gui.app.kiasort import Kiasort

        assert Kiasort is kiasort


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


def _window(session=None, statuses=None):
    _qt_or_skip()
    session = session or FakeSession()
    probe_to_status = dict(zip(session._probes, statuses or []))
    with mock.patch.object(kiasort, "probe_status", lambda self, p: probe_to_status.get(p)):
        return kiasort(session)


class TestWindow:
    def test_the_window_names_the_session_and_is_tagged(self):
        app = _window()
        assert app.figure.windowTitle() == "KIASORT: 2024-01-01"
        assert app.figure.objectName() == WINDOW_TAG
        app.close()

    def test_it_opens_where_matlab_opens_it(self):
        app = _window()
        assert app.position == DEFAULT_POSITION
        app.close()

    def test_it_opens_with_no_probes(self):
        """A session with nothing to sort still opens; the buttons are dead."""
        app = _window()
        assert app.figure is not None
        assert app.probe_list.count() == 0
        assert app.run_button.isEnabled() is False
        assert app.curate_button.isEnabled() is False
        app.close()

    def test_the_listbox_renders_one_row_per_probe(self):
        session = FakeSession([FakeProbe("a"), FakeProbe("b")])
        statuses = [FakeStatus(exported=True), None]
        app = _window(session=session, statuses=statuses)
        rows = [app.probe_list.item(i).text() for i in range(app.probe_list.count())]
        assert rows == ["a (exported)", f"b {NOT_EXPORTED_SUFFIX}"]
        app.close()

    def test_the_config_defaults_reach_their_widgets(self):
        app = _window()
        assert app._check_widgets["useGPU"].isChecked() is True
        assert app._check_widgets["denoising"].isChecked() is True
        assert app._check_widgets["parallelProcessing"].isChecked() is False
        assert app._num_widgets["sortingChunkDuration"].value() == pytest.approx(120.0)
        assert app._num_widgets["batch_ch_size"].value() == 64
        app.close()

    def test_selecting_a_run_probe_enables_both_buttons(self):
        session = FakeSession([FakeProbe("a")])
        app = _window(session=session, statuses=[FakeStatus(exported=True, run=True)])
        app.probe_list.setCurrentRow(0)
        run_ok, curate_ok = app.update_button_state()
        assert run_ok is True
        assert curate_ok is True
        assert app.run_button.isEnabled() is True
        assert app.curate_button.isEnabled() is True
        app.close()

    def test_selecting_an_exported_probe_enables_only_run(self):
        session = FakeSession([FakeProbe("a")])
        app = _window(session=session, statuses=[FakeStatus(exported=True)])
        app.probe_list.setCurrentRow(0)
        run_ok, curate_ok = app.update_button_state()
        assert (run_ok, curate_ok) == (True, False)
        assert app.run_button.isEnabled() is True
        assert app.curate_button.isEnabled() is False
        app.close()

    def test_config_overrides_reflects_the_widget_state(self):
        app = _window()
        app._check_widgets["useGPU"].setChecked(False)
        app._check_widgets["parallelSort"].setChecked(True)
        app._num_widgets["batch_ch_size"].setValue(128)
        cfg = app.config_overrides()
        assert cfg["useGPU"] is False
        assert cfg["parallelSort"] is True
        assert cfg["batch_ch_size"] == 128
        # every check field appears, even the ones the user did not touch
        for field, _, _, _ in CHECK_OPTIONS:
            assert field in cfg
        app.close()


# ----------------------------------------------------------------------
# actions -- the MATLAB-only backend calls
# ----------------------------------------------------------------------
def _patch_backend(**overrides):
    """Replace one or more names on ndi.fun.probe.import_.kiasort in place.

    Patches on the imported module rather than sys.modules, because the
    app does ``from ...fun.probe.import_ import kiasort as kiasort_backend``
    -- once ndi.fun.probe.import_ has cached ``kiasort`` as an attribute,
    swapping sys.modules is invisible to that lookup.
    """
    from ndi.fun.probe.import_ import kiasort as kiasort_backend

    return mock.patch.multiple(kiasort_backend, **overrides)


class TestRunSelected:
    def test_pressing_run_with_no_selection_launches_nothing(self):
        app = _window()
        called = []
        with _patch_backend(
            run=lambda *a, **k: called.append(("run", a, k)),
            probe=lambda *a, **k: None,
        ):
            assert app.run_selected() is None
        assert called == []
        app.close()

    def test_pressing_run_quotes_the_backend_message(self):
        """ndi.fun.probe.import_.kiasort.run raises NotImplementedError on
        Python, and its message names the way forward (sort in MATLAB, then
        import). The alert shows the message verbatim."""
        session = FakeSession([FakeProbe("a")])
        app = _window(session=session, statuses=[FakeStatus(exported=True)])
        app.probe_list.setCurrentRow(0)

        seen = {}
        app.alert = lambda message, title, **k: seen.update(message=message, title=title)

        def _run(*_args, **_kwargs):
            raise NotImplementedError(
                "ndi.fun.probe.import.kiasort.run drives the KIASORT toolbox, "
                "which is MATLAB. It cannot run from Python and is not ported."
            )

        with _patch_backend(run=_run, probe=lambda *a, **k: None):
            app.run_selected()

        assert seen["title"] == RUN_FAILED_TITLE
        assert "KIASORT toolbox" in seen["message"]
        app.close()

    def test_a_successful_run_reports_a_run_complete_alert(self):
        """A lab that grows a Python KIASORT backend gets the success path."""
        session = FakeSession([FakeProbe("a")])
        app = _window(session=session, statuses=[FakeStatus(exported=True)])
        app.probe_list.setCurrentRow(0)

        seen = {}
        app.alert = lambda message, title, **k: seen.update(
            message=message, title=title, success=k.get("success", False)
        )

        with _patch_backend(
            run=lambda *_a, **_k: None,
            probe=lambda *_a, **_k: None,
        ):
            app.run_selected()

        assert seen["title"] == RUN_COMPLETE_TITLE
        assert seen["success"] is True
        assert "a" in seen["message"]  # the element string appears
        app.close()

    def test_run_hands_cfg_overrides_and_the_session_to_the_backend(self):
        """The keys cross the API boundary into the KIASORT backend as-is."""
        session = FakeSession([FakeProbe("a")])
        app = _window(session=session, statuses=[FakeStatus(exported=True)])
        app.probe_list.setCurrentRow(0)
        app._check_widgets["parallelSort"].setChecked(True)
        app._num_widgets["batch_ch_size"].setValue(96)

        run_seen = {}
        probe_seen = {}

        def _run(S, probe, **kwargs):
            run_seen["S"] = S
            run_seen["probe"] = probe
            run_seen.update(kwargs)

        def _probe(S, probe, **kwargs):
            probe_seen["S"] = S
            probe_seen["probe"] = probe
            probe_seen.update(kwargs)

        with _patch_backend(run=_run, probe=_probe):
            app.alert = lambda *a, **k: None
            app.run_selected()

        assert run_seen["S"] is session
        assert run_seen["probe"] is session._probes[0]
        assert run_seen["verbose"] == 0
        cfg = run_seen["cfg_overrides"]
        assert cfg["parallelSort"] is True
        assert cfg["batch_ch_size"] == 96
        assert probe_seen["S"] is session
        assert probe_seen["probe"] is session._probes[0]
        app.close()


class TestCurateSelected:
    def test_pressing_curate_with_no_selection_launches_nothing(self):
        app = _window()
        called = []
        with _patch_backend(curate=lambda *a, **k: called.append((a, k))):
            assert app.curate_selected() is None
        assert called == []
        app.close()

    def test_pressing_curate_quotes_the_backend_message(self):
        session = FakeSession([FakeProbe("a")])
        app = _window(session=session, statuses=[FakeStatus(exported=True, run=True)])
        app.probe_list.setCurrentRow(0)

        seen = {}
        app.alert = lambda message, title, **k: seen.update(message=message, title=title)

        def _curate(*_args, **_kwargs):
            raise NotImplementedError("KIASORT's curation UI is a MATLAB app.")

        with _patch_backend(curate=_curate):
            app.curate_selected()

        assert seen["title"] == CURATION_FAILED_TITLE
        assert "MATLAB" in seen["message"]
        app.close()


class TestLaunching:
    def test_launch_constructs_it_with_the_session(self):
        _qt_or_skip()
        session = FakeSession()
        with mock.patch.object(kiasort, "probe_status", lambda self, p: None):
            app = SessionApp.launch("ndi.gui.app.kiasort.kiasort", session)
        assert isinstance(app, kiasort)
        assert app.session is session
        app.close()
