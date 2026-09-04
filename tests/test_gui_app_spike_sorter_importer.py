"""Tests for ndi.gui.app.spike_sorter_importer.

MATLAB counterpart: ndi.gui.app.spikeSorterImporter

This app is the route by which spiking neurons enter a Python NDI session at
all, so the tests run it against a real session holding a real synthetic Phy
sort: the import path writes documents, and a mock would only prove the mock
was called. What is checked with fakes is the presentation -- the three panes'
rows, the tag defaults, the confirmation text -- which is pure and has no
business touching a database.

DESTRUCTIVE ACTIONS ASK FIRST. Import and Delete both go through confirm(),
and a caller with no display sets auto_confirm rather than being asked; with
neither a window nor auto_confirm the answer is NO, which several tests pin,
because a destructive action nobody can be asked about must not proceed.

The Qt tests skip without PySide6, as elsewhere in this package.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from ndi.element_timeseries import ndi_element_timeseries
from ndi.fun.file import elementDirectoryName
from ndi.fun.probe import extracellularInfo
from ndi.fun.probe.import_ import kilosort
from ndi.gui.app.session_app import SessionApp
from ndi.gui.app.spike_sorter_importer import (
    DEFAULT_PIPELINE,
    DEFAULT_POSITION,
    NO_PROBE_SELECTED,
    NO_PROBES_ITEM,
    NO_TAGS_SELECTED,
    NOTHING_TO_DELETE,
    PIPELINES,
    WINDOW_TAG,
    binary_status_text,
    delete_confirm_message,
    import_confirm_message,
    pipeline_items,
    pipeline_key,
    quality_values_for,
    session_neuron_items,
    spikeSorterImporter,
    tag_defaults,
)
from ndi.query import ndi_query
from ndi.session import ndi_session_dir
from ndi.subject import ndi_subject
from ndi.time.clocktype import ndi_time_clocktype

SR = 30000.0
N_CH = 4
N_SAMP = 60000


class ProbeLike(ndi_element_timeseries):
    """An element carrying the probe converter API the importer requires."""

    def samplerate(self, epoch=None):
        return SR

    def times2samples(self, epoch, times):
        return np.round(np.asarray(times, dtype=float) * SR).astype(int)

    def samples2times(self, epoch, samples):
        return np.asarray(samples, dtype=float) / SR


class SessionWithProbe:
    """A session that reports the probe-like element as its n-trode probe.

    getprobes() only returns elements whose stored class names a probe, and a
    real probe takes its epochs from a daq system, so this is the smallest
    honest stand-in: everything else is the real session.
    """

    def __init__(self, session, probes):
        self._session = session
        self._probes = list(probes)

    def __getattr__(self, name):
        return getattr(self._session, name)

    def getprobes(self, **kwargs):
        return list(self._probes)


def _session_with_sort(tmp_path, *, labels=None, name="ssi"):
    directory = tmp_path / name
    directory.mkdir(parents=True, exist_ok=True)
    session = ndi_session_dir(name, str(directory))
    subject = ndi_subject("mouse23@vhlab.org", "test mouse").newdocument()
    subject.set_session_id(session.id())
    session.database_add(subject)

    probe = ProbeLike(
        session=session,
        name="ctx",
        reference=1,
        type="n-trode",
        direct=False,
        subject_id=subject.id,
    )
    session.database_add(probe.newdocument())
    times = np.arange(N_SAMP) / SR
    probe.addepoch(
        "epoch_1",
        [ndi_time_clocktype("dev_local_time")],
        [(0.0, N_SAMP / SR)],
        times,
        np.zeros((N_SAMP, N_CH)),
    )

    spikes = {
        1: np.arange(3000, N_SAMP - 3000, 5000),
        2: np.arange(4000, N_SAMP - 3000, 7000),
        3: np.arange(5000, N_SAMP - 3000, 11000),
    }
    labels = labels or {1: "good", 2: "mua", 3: "noise"}
    dirname, _ = elementDirectoryName(probe)
    kdir = os.path.join(str(session.getpath()), "kilosort", dirname, "kilosort_output")
    os.makedirs(kdir, exist_ok=True)

    samples = np.concatenate([np.asarray(v, dtype=np.int64) for v in spikes.values()])
    clusters = np.concatenate([np.full(len(v), int(k), dtype=np.int32) for k, v in spikes.items()])
    order = np.argsort(samples)
    np.save(os.path.join(kdir, "spike_times.npy"), samples[order])
    np.save(os.path.join(kdir, "spike_clusters.npy"), clusters[order])
    with open(os.path.join(kdir, "cluster_group.tsv"), "w", encoding="utf-8") as handle:
        handle.write("cluster_id\tgroup\n")
        for cid, label in labels.items():
            handle.write(f"{cid}\t{label}\n")

    templates = np.zeros((3, 61, N_CH))
    for index in range(3):
        templates[index, :, index % N_CH] = -np.exp(-((np.arange(61) - 20) ** 2) / 20.0)
    np.save(os.path.join(kdir, "templates.npy"), templates.astype(np.float32))
    np.save(os.path.join(kdir, "spike_templates.npy"), (clusters[order] - 1).astype(np.int32))
    np.save(os.path.join(kdir, "amplitudes.npy"), np.full(samples.size, 10.0, np.float32))

    return SessionWithProbe(session, [probe]), probe, spikes


def _app(session, *, confirm=True):
    """A built-less app, answering its own confirmations."""
    app = spikeSorterImporter(session, build=False)
    app.auto_confirm = confirm
    app.set_recalculate(False)  # no raw binary in these fixtures
    return app


# ----------------------------------------------------------------------
# what the panes show
# ----------------------------------------------------------------------
class TestPanes:
    def test_session_rows_are_name_quality_pipeline(self):
        rows = session_neuron_items(
            [{"element_name": "ctx_1_1", "quality_label": "good", "pipeline": "Kilosort2.5 to phy"}]
        )
        assert rows[0].startswith("ctx_1_1")
        assert "good" in rows[0] and "Kilosort2.5 to phy" in rows[0]

    def test_pipeline_rows_are_cluster_tag_spikes(self):
        rows = pipeline_items(
            {"cluster_ids": [1, 2], "cluster_labels": ["good", "mua"], "num_spikes": [10, 4]}
        )
        assert rows == ["    1 | good     |      10", "    2 | mua      |       4"]

    def test_no_info_is_no_rows(self):
        assert pipeline_items(None) == []

    def test_the_default_tags_are_the_importer_s_that_are_present(self):
        assert tag_defaults(["good", "mua", "noise"]) == ["good", "mua"]
        assert tag_defaults(["noise", "artifact"]) == []

    def test_tag_matching_is_case_insensitive_but_keeps_the_spelling(self):
        assert tag_defaults(["Good", "MUA"]) == ["Good", "MUA"]

    def test_quality_values_follow_the_importer_convention(self):
        assert quality_values_for(["good", "mua", "noise", "single"]) == [1, 4, 4, 1]

    def test_a_custom_tag_gets_the_more_modest_value(self):
        """The app cannot know where a lab's own label sits, so it claims less."""
        assert quality_values_for(["my_lab_tag"]) == [4]

    def test_the_pipeline_key_strips_whitespace(self):
        assert pipeline_key("Kilosort 2.5") == "Kilosort2.5"
        assert pipeline_key(DEFAULT_PIPELINE) in "Kilosort2.5 to phy to ndi.fun.probe.import"


class TestBinaryStatus:
    def test_nothing_to_report_is_empty(self):
        assert binary_status_text(None) == ("", "")
        assert binary_status_text({}) == ("", "")

    def test_a_found_binary_names_the_file_and_channels(self):
        text, tooltip = binary_status_text(
            {"binary_found": True, "binary_file": "/data/ctx.bin", "binary_num_channels": 385}
        )
        assert text == "Raw binary: found (ctx.bin, 385 ch)"
        assert tooltip == "/data/ctx.bin"

    def test_a_missing_binary_reports_the_dat_path_it_still_points_at(self):
        text, tooltip = binary_status_text(
            {"binary_found": False, "binary_dat_path": "temp_wh.dat"}
        )
        assert "NOT FOUND" in text and "temp_wh.dat" in text
        assert "temp_wh.dat" in tooltip

    def test_a_missing_binary_with_no_dat_path_says_so(self):
        text, _ = binary_status_text({"binary_found": False, "binary_dat_path": ""})
        assert "no .metadata" in text


class TestConfirmationText:
    def test_the_import_message_names_the_probe_and_tags(self):
        message = import_confirm_message("Kilosort 2.5", "ctx | 1", ["good", "mua"])
        assert "Kilosort 2.5" in message and "ctx | 1" in message and "good, mua" in message

    def test_recalculation_and_its_window_are_spelled_out(self):
        message = import_confirm_message(
            "Kilosort 2.5", "ctx | 1", ["good"], recalculate=True, window_ms=(-5.0, 5.0)
        )
        assert "recalculated from the raw binary" in message and "[-5, 5] ms" in message

    def test_overwrite_warns_that_neurons_are_removed(self):
        message = import_confirm_message("Kilosort 2.5", "ctx | 1", ["good"], overwrite=True)
        assert "removed and re-imported" in message

    def test_the_delete_message_names_every_neuron(self):
        message = delete_confirm_message([{"element_name": "ctx_1_1"}, {"element_name": "ctx_1_2"}])
        assert "Delete 2 neuron(s)" in message
        assert "cannot be undone" in message
        assert "ctx_1_1, ctx_1_2" in message


# ----------------------------------------------------------------------
# the model, over a real session
# ----------------------------------------------------------------------
class TestLoading:
    def test_the_probe_dropdown_lists_the_n_trode_probes(self, tmp_path):
        session, _, _ = _session_with_sort(tmp_path)
        app = _app(session)
        assert app.probe_items == ["ctx | ref 1"]
        assert app.probe_index == 0
        assert app.selected_probe() is not None

    def test_a_session_with_no_probes_says_so(self, tmp_path):
        session, _, _ = _session_with_sort(tmp_path)
        session._probes = []
        app = _app(session)
        assert app.probe_items == [NO_PROBES_ITEM]
        assert app.selected_probe() is None
        assert app.pipeline_items == []

    def test_the_pipeline_pane_lists_the_clusters_on_disk(self, tmp_path):
        session, _, spikes = _session_with_sort(tmp_path)
        app = _app(session)
        assert len(app.pipeline_items) == 3
        assert app.pipeline_items[0].strip().startswith("1 | good")
        assert str(len(spikes[1])) in app.pipeline_items[0]

    def test_the_tags_are_offered_with_the_defaults_selected(self, tmp_path):
        session, _, _ = _session_with_sort(tmp_path)
        app = _app(session)
        assert app.tags == ["good", "mua", "noise"]
        assert app.selected_tags == ["good", "mua"]

    def test_no_sort_on_disk_is_reported_in_the_pane_not_raised(self, tmp_path):
        directory = tmp_path / "bare"
        directory.mkdir()
        session = ndi_session_dir("bare", str(directory))
        subject = ndi_subject("mouse23@vhlab.org", "m").newdocument()
        subject.set_session_id(session.id())
        session.database_add(subject)
        probe = ProbeLike(
            session=session,
            name="ctx",
            reference=1,
            type="n-trode",
            direct=False,
            subject_id=subject.id,
        )
        session.database_add(probe.newdocument())

        app = _app(SessionWithProbe(session, [probe]))
        assert len(app.pipeline_items) == 1
        assert app.pipeline_items[0].startswith("(no Kilosort output")
        assert app.pipeline_error
        assert app.tags == []

    def test_the_binary_status_is_reported(self, tmp_path):
        session, _, _ = _session_with_sort(tmp_path)
        app = _app(session)
        assert "NOT FOUND" in app.binary_status[0]


class TestImporting:
    def test_import_writes_the_neurons_and_lists_them(self, tmp_path):
        session, probe, _ = _session_with_sort(tmp_path)
        app = _app(session)
        assert app.session_items == []

        assert app.on_import() == 2
        assert app.last_alert == ("Done", "Import complete.")
        assert len(app.session_items) == 2
        assert len(extracellularInfo(session, probe)[0]) == 2

    def test_only_the_selected_tags_are_imported(self, tmp_path):
        session, probe, _ = _session_with_sort(tmp_path)
        app = _app(session)
        app.set_tags(["good"])
        assert app.on_import() == 1
        assert [e["quality_label"] for e in extracellularInfo(session, probe)[0]] == ["good"]

    def test_a_tag_that_is_not_offered_cannot_be_selected(self, tmp_path):
        session, _, _ = _session_with_sort(tmp_path)
        app = _app(session)
        assert app.set_tags(["good", "invented"]) == ["good"]

    def test_no_tags_selected_refuses(self, tmp_path):
        session, _, _ = _session_with_sort(tmp_path)
        app = _app(session)
        app.set_tags([])
        assert app.on_import() == 0
        assert app.last_alert == ("No tags selected", NO_TAGS_SELECTED)

    def test_no_probe_refuses(self, tmp_path):
        session, _, _ = _session_with_sort(tmp_path)
        session._probes = []
        app = _app(session)
        assert app.on_import() == 0
        assert app.last_alert == ("No probe", NO_PROBE_SELECTED)

    def test_an_inverted_waveform_window_refuses(self, tmp_path):
        session, _, _ = _session_with_sort(tmp_path)
        app = _app(session)
        app.set_recalculate(True)
        app.set_window_ms(5.0, -5.0)
        assert app.on_import() == 0
        assert app.last_alert[0] == "Invalid window"

    def test_declining_the_confirmation_imports_nothing(self, tmp_path):
        session, probe, _ = _session_with_sort(tmp_path)
        app = _app(session, confirm=False)
        assert app.on_import() == 0
        assert extracellularInfo(session, probe)[0] == []

    def test_with_no_window_and_no_answer_nothing_happens(self, tmp_path):
        """A destructive action nobody can be asked about does not proceed."""
        session, probe, _ = _session_with_sort(tmp_path)
        app = spikeSorterImporter(session, build=False)
        assert app.auto_confirm is None
        assert app.on_import() == 0
        assert extracellularInfo(session, probe)[0] == []

    def test_a_second_import_reports_nothing_to_do(self, tmp_path):
        session, _, _ = _session_with_sort(tmp_path)
        app = _app(session)
        app.on_import()
        assert app.on_import() == 0
        assert len(app.session_items) == 2

    def test_overwrite_re_imports(self, tmp_path):
        session, _, _ = _session_with_sort(tmp_path)
        app = _app(session)
        app.on_import()
        app.set_overwrite(True)
        assert app.on_import() == 2
        assert len(app.session_items) == 2

    def test_the_import_failure_is_reported_rather_than_raised(self, tmp_path, monkeypatch):
        session, _, _ = _session_with_sort(tmp_path)
        app = _app(session)

        def boom(*args, **kwargs):
            raise RuntimeError("the sort is broken")

        monkeypatch.setattr(kilosort, "probe", boom)
        assert app.on_import() == 0
        assert app.last_alert == ("Import failed", "the sort is broken")

    def test_the_pipeline_selector_sets_the_recorded_version(self, tmp_path):
        session, probe, _ = _session_with_sort(tmp_path)
        app = _app(session)
        assert app.kilosort_version() == "2.5"
        app.on_import()
        entry = extracellularInfo(session, probe)[0][0]
        assert entry["pipeline"].startswith("Kilosort2.5 to phy to")


class TestDeleting:
    def test_delete_removes_the_selected_neurons(self, tmp_path):
        session, probe, _ = _session_with_sort(tmp_path)
        app = _app(session)
        app.on_import()
        app.set_session_selection([0])

        assert app.on_delete() == 1
        assert len(app.session_items) == 1
        assert len(extracellularInfo(session, probe)[0]) == 1

    def test_nothing_selected_refuses(self, tmp_path):
        session, _, _ = _session_with_sort(tmp_path)
        app = _app(session)
        app.on_import()
        assert app.on_delete() == 0
        assert app.last_alert == ("Nothing selected", NOTHING_TO_DELETE)

    def test_declining_the_confirmation_deletes_nothing(self, tmp_path):
        session, probe, _ = _session_with_sort(tmp_path)
        app = _app(session)
        app.on_import()
        app.set_session_selection([0, 1])
        app.auto_confirm = False
        assert app.on_delete() == 0
        assert len(extracellularInfo(session, probe)[0]) == 2

    def test_out_of_range_rows_are_dropped(self, tmp_path):
        session, _, _ = _session_with_sort(tmp_path)
        app = _app(session)
        app.on_import()
        assert app.set_session_selection([0, 99, -1]) == [0]

    def test_deleting_every_neuron_clears_the_provenance_marker(self, tmp_path):
        """Otherwise the importer would report 'nothing to do' forever."""
        session, probe, _ = _session_with_sort(tmp_path)
        app = _app(session)
        app.on_import()
        app.set_session_selection([0, 1])
        app.on_delete()

        assert session.database_search(ndi_query("").isa("kilosort_clusters")) == []
        # so a plain import works again, with no overwrite needed
        assert app.on_import() == 2

    def test_a_partial_delete_leaves_the_sort_marked_as_imported(self, tmp_path):
        """MATLAB's behaviour: the marker goes only when nothing depends on it."""
        session, probe, _ = _session_with_sort(tmp_path)
        app = _app(session)
        app.on_import()
        app.set_session_selection([0])
        app.on_delete()

        assert len(session.database_search(ndi_query("").isa("kilosort_clusters"))) == 1
        assert app.on_import() == 0  # still "already imported"
        app.set_overwrite(True)
        assert app.on_import() == 2


class TestFilterByPipeline:
    def test_the_filter_keeps_only_matching_provenance(self, tmp_path):
        session, _, _ = _session_with_sort(tmp_path)
        app = _app(session)
        app.on_import()
        assert len(app.session_items) == 2

        app.set_filter_by_pipeline(True)
        assert len(app.session_items) == 2  # this pipeline imported them

        app.pipeline = "Kilosort 9.9"  # a pipeline nothing was imported under
        app.reload_session_neurons()
        assert app.session_items == []


# ----------------------------------------------------------------------
# discovery
# ----------------------------------------------------------------------
class TestDiscovery:
    def test_it_adopts_the_session_app_interface(self):
        assert issubclass(spikeSorterImporter, SessionApp)
        assert SessionApp.is_session_app(spikeSorterImporter)
        assert not SessionApp.is_abstract(spikeSorterImporter)

    def test_the_menu_text_is_matlab_s_verbatim(self):
        assert spikeSorterImporter.Name == "spikeSorterImporter"
        assert spikeSorterImporter.Category == ""  # top level, as MATLAB has it

    def test_scanning_ndi_gui_app_finds_it(self):
        found = SessionApp.list(["ndi.gui.app"])
        assert {
            "Name": "spikeSorterImporter",
            "Class": "ndi.gui.app.spike_sorter_importer.spikeSorterImporter",
            "Category": "",
        } in found

    def test_the_navigator_offers_it_at_the_top_level(self):
        from ndi.gui.nav.datasets_pane import session_apps
        from ndi.gui.nav.datasets_text import order_app_menu

        entries = order_app_menu(session_apps())
        top_level = [e["label"] for e in entries if e["kind"] == "app"]
        assert "spikeSorterImporter" in top_level

    def test_methods_are_snake_case(self):
        import re

        camel = [
            name
            for name in vars(spikeSorterImporter)
            if not name.startswith("_") and re.search(r"[a-z][A-Z]", name)
        ]
        assert camel == []


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


class TestWindow:
    def test_the_window_carries_matlab_s_tag_and_geometry(self, tmp_path):
        _qt_or_skip()
        session, _, _ = _session_with_sort(tmp_path)
        app = spikeSorterImporter(session, build=True)
        assert app.figure.objectName() == WINDOW_TAG
        assert app.figure.windowTitle() == "NDI Spike Sorter Importer"
        # MATLAB documents this window as resizable and 600x600 INITIALLY, so
        # the geometry is a request rather than a contract: Qt widens it when
        # the three panes' minimum widths need more, which is the right
        # behaviour and not something to fight with a fixed size.
        geometry = app.figure.geometry()
        assert geometry.width() >= DEFAULT_POSITION[2]
        assert geometry.height() >= DEFAULT_POSITION[3]
        app.close()

    def test_the_three_panes_are_populated(self, tmp_path):
        _qt_or_skip()
        session, _, _ = _session_with_sort(tmp_path)
        app = spikeSorterImporter(session, build=True)
        assert app.probe_dropdown.count() == 1
        assert app.pipeline_list.count() == 3
        assert app.tag_list.count() == 3
        assert app.session_list.count() == 0
        assert [i.text() for i in app.tag_list.selectedItems()] == ["good", "mua"]
        assert app.pipeline_selector.count() == len(PIPELINES)
        app.close()

    def test_selecting_tags_in_the_widget_reaches_the_model(self, tmp_path):
        _qt_or_skip()
        session, _, _ = _session_with_sort(tmp_path)
        app = spikeSorterImporter(session, build=True)
        app.tag_list.clearSelection()
        app.tag_list.item(2).setSelected(True)  # 'noise'
        assert app.selected_tags == ["noise"]
        app.close()

    def test_the_window_fields_follow_the_recalc_checkbox(self, tmp_path):
        _qt_or_skip()
        session, _, _ = _session_with_sort(tmp_path)
        app = spikeSorterImporter(session, build=True)
        assert app.waveform_t0_field.isEnabled() is True
        app.recalc_checkbox.setChecked(False)
        assert app.recalculate is False
        assert app.waveform_t0_field.isEnabled() is False
        app.close()

    def test_an_import_through_the_built_window_fills_the_left_pane(self, tmp_path):
        _qt_or_skip()
        session, _, _ = _session_with_sort(tmp_path)
        app = spikeSorterImporter(session, build=True)
        app.auto_confirm = True
        app.set_recalculate(False)
        assert app.on_import() == 2
        assert app.session_list.count() == 2
        app.close()
