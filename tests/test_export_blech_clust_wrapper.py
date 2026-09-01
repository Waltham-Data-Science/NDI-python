"""Tests for ndi.fun.export.blech_clust, the session-backed wrapper.

MATLAB counterpart: ndi.fun.export.blech_clust

The binning rules are pinned against blech_clust_write in
test_export_blech_clust.py; that function is pure and needs no session. What
is tested HERE is what only the wrapper does: refusing a sample rate
blech_clust cannot consume, finding the stimulus_presentation document,
mapping presentation_order to stimids, reading per-trial onsets back out of
the binary, and turning ensemble neurons into unit descriptors.
"""

from __future__ import annotations

import numpy as np
import pytest

from ndi.database_fun import write_presentation_time_structure
from ndi.fun import export as export_fun

pytest.importorskip("h5py")


class TestGuards:
    """These fire before anything touches a session."""

    def test_non_30khz_sample_rate_is_refused(self):
        with pytest.raises(ValueError, match="exactly 30000 Hz"):
            export_fun.blech_clust(None, None, "e", "/tmp/x.h5", sample_rate=20000)

    def test_negative_pre_stim_is_refused(self):
        with pytest.raises(ValueError, match="pre_stim"):
            export_fun.blech_clust(None, None, "e", "/tmp/x.h5", pre_stim=-1)

    def test_zero_post_stim_is_refused(self):
        with pytest.raises(ValueError, match="post_stim"):
            export_fun.blech_clust(None, None, "e", "/tmp/x.h5", post_stim=0)

    def test_guards_run_before_the_session_is_touched(self):
        """A None probe would raise AttributeError if the guards did not fire
        first, so this pins the ordering rather than just the message."""
        with pytest.raises(ValueError):
            export_fun.blech_clust(None, None, "e", "/tmp/x.h5", sample_rate=1)


class TestUnitDescriptors:
    """single_unit comes from the quality label; the other flags do not."""

    def test_single_unit_set_from_quality_label(self, monkeypatch):
        from ndi.fun import ensemble as ensemble_fun

        E = {
            "activity": np.array([[0.25, 0.75, 0.0], [0.5, 0.0, 0.0]]),
            "neuron_ids": ["a", "b"],
            "neuron_names": ["cell_a", "cell_b"],
            "info": {"clocktype": "dev_local_time"},
        }
        monkeypatch.setattr(
            ensemble_fun,
            "read",
            lambda *a, **k: E,
        )
        monkeypatch.setattr(
            ensemble_fun,
            "neuron_quality",
            lambda s, ids: (np.array([3.0, 1.0]), ["good", "noise"]),
        )
        trains, info, clock = export_fun._blech_get_ensemble(
            None, None, "e1", ensemble="something", single_unit_labels=("single", "good")
        )
        assert clock == "dev_local_time"
        assert [i["single_unit"] for i in info] == [1, 0]
        # Not inferred: NDI never claimed a cell type, so neither does the file.
        assert all(i["regular_spiking"] == 0 and i["fast_spiking"] == 0 for i in info)
        assert [i["name"] for i in info] == ["cell_a", "cell_b"]

    def test_zero_padding_is_stripped_from_each_train(self, monkeypatch):
        from ndi.fun import ensemble as ensemble_fun

        E = {
            "activity": np.array([[0.25, 0.75, 1.5], [0.5, 0.0, 0.0]]),
            "neuron_ids": ["a", "b"],
            "neuron_names": ["a", "b"],
            "info": {"clocktype": "dev_local_time"},
        }
        monkeypatch.setattr(ensemble_fun, "read", lambda *a, **k: E)
        monkeypatch.setattr(
            ensemble_fun,
            "neuron_quality",
            lambda s, ids: (np.array([np.nan, np.nan]), ["", ""]),
        )
        trains, _, _ = export_fun._blech_get_ensemble(
            None, None, "e1", ensemble="x", single_unit_labels=()
        )
        assert list(trains[0]) == [0.25, 0.75, 1.5]
        assert list(trains[1]) == [0.5]

    def test_label_match_is_case_insensitive(self, monkeypatch):
        from ndi.fun import ensemble as ensemble_fun

        E = {
            "activity": np.array([[0.25]]),
            "neuron_ids": ["a"],
            "neuron_names": ["a"],
            "info": {"clocktype": "c"},
        }
        monkeypatch.setattr(ensemble_fun, "read", lambda *a, **k: E)
        monkeypatch.setattr(
            ensemble_fun, "neuron_quality", lambda s, ids: (np.array([3.0]), ["GOOD"])
        )
        _, info, _ = export_fun._blech_get_ensemble(
            None, None, "e1", ensemble="x", single_unit_labels=("good",)
        )
        assert info[0]["single_unit"] == 1


class TestPresentationTimeRoundTrip:
    """load_presentation_time was a stub returning None; it reads real data now."""

    def test_reads_back_what_the_writer_wrote(self, tmp_path):
        from ndi.database_fun import read_presentation_time_structure

        entries = [
            {
                "clocktype": "dev_local_time",
                "stimopen": 0.9,
                "onset": 1.0,
                "offset": 2.0,
                "stimclose": 2.1,
                "stimevents": np.zeros((0, 2)),
            },
            {
                "clocktype": "dev_local_time",
                "stimopen": 3.9,
                "onset": 4.0,
                "offset": 5.0,
                "stimclose": 5.1,
                "stimevents": np.zeros((0, 2)),
            },
        ]
        path = tmp_path / "presentation_time.bin"
        write_presentation_time_structure(str(path), entries)
        _, got = read_presentation_time_structure(str(path))

        assert len(got) == 2
        assert [g["onset"] for g in got] == [1.0, 4.0]
        assert [g["offset"] for g in got] == [2.0, 5.0]
        assert got[0]["clocktype"] == "dev_local_time"

    def test_deprecated_in_document_form_still_loads(self, tmp_path):
        """An old document keeps the times inline; MATLAB warns and reads it."""
        from ndi.app.stimulus.decoder import ndi_app_stimulus_decoder
        from ndi.session import ndi_session_dir

        d = tmp_path / "s"
        d.mkdir()
        session = ndi_session_dir("dep", str(d))

        class FakeDoc:
            document_properties = {
                "stimulus_presentation": {"presentation_time": [{"onset": 1.0, "offset": 2.0}]}
            }

        decoder = ndi_app_stimulus_decoder(session)
        with pytest.warns(UserWarning, match="deprecated"):
            got = decoder.load_presentation_time(FakeDoc())
        assert got == [{"onset": 1.0, "offset": 2.0}]

    def test_no_session_returns_empty_not_none(self):
        """The stub returned None, which made every caller crash on iteration."""
        from ndi.app.stimulus.decoder import ndi_app_stimulus_decoder

        decoder = ndi_app_stimulus_decoder(None)
        assert decoder.load_presentation_time(None) == []


class TestStimulusIdentityMapping:
    """presentation_order is 1-based into `stimuli`; getting that wrong
    silently mislabels every trial's tastant."""

    def _fake(self, monkeypatch, presentation_order, stimuli):

        class FakeDoc:
            document_properties = {
                "stimulus_presentation": {
                    "presentation_order": presentation_order,
                    "stimuli": stimuli,
                },
                "epochid": {"epochid": "e1"},
            }

        class FakeSyncgraph:
            def time_convert(self, tr, t_in, referent, clock):
                return np.asarray(t_in, dtype=float), None, ""

        class FakeSession:
            syncgraph = FakeSyncgraph()

            def id(self):
                return "sess1"

            def database_search(self, q):
                return [FakeDoc()]

        fake_session = FakeSession()

        class FakeStim:
            id = "stim1"
            # A timereference resolves its referent's session id, so the fake
            # stimulator needs one.
            session_id = "sess1"

            @property
            def session(self):
                return fake_session

            def elementstring(self):
                return "stim"

        class FakeDecoder:
            def __init__(self, session):
                pass

            def load_presentation_time(self, doc):
                n = len(presentation_order)
                return [
                    {
                        "onset": float(i),
                        "offset": float(i) + 0.5,
                        "clocktype": "dev_local_time",
                    }
                    for i in range(n)
                ]

        import ndi.app.stimulus.decoder as dec

        monkeypatch.setattr(dec, "ndi_app_stimulus_decoder", FakeDecoder)
        return fake_session, FakeStim()

    def test_trial_stimids_follow_presentation_order(self, monkeypatch):
        stimuli = [
            {"parameters": {"stimid": 7, "tastant": "sucrose"}},
            {"parameters": {"stimid": 9, "tastant": "quinine"}},
        ]
        session, stim = self._fake(monkeypatch, [1, 2, 2, 1], stimuli)
        onset, trial_stimid, tastants = export_fun._blech_get_stimulus_presentation(
            session,
            stim,
            None,
            "e1",
            "dev_local_time",
            tastant_field="tastant",
            stimid_field="stimid",
        )
        assert list(trial_stimid) == [7.0, 9.0, 9.0, 7.0]
        assert tastants[7.0] == "sucrose"
        assert tastants[9.0] == "quinine"
        assert len(onset) == 4

    def test_missing_stimid_field_falls_back_to_index(self, monkeypatch):
        stimuli = [{"parameters": {"tastant": "a"}}, {"parameters": {"tastant": "b"}}]
        session, stim = self._fake(monkeypatch, [1, 2], stimuli)
        _, trial_stimid, _ = export_fun._blech_get_stimulus_presentation(
            session,
            stim,
            None,
            "e1",
            "dev_local_time",
            tastant_field="tastant",
            stimid_field="stimid",
        )
        assert list(trial_stimid) == [1.0, 2.0]

    def test_missing_presentation_document_names_the_remedy(self, monkeypatch):
        class EmptySession:
            def database_search(self, q):
                return []

        class FakeStim:
            id = "s"

            def elementstring(self):
                return "stim1"

        with pytest.raises(ValueError, match="Run the stimulus decoder"):
            export_fun._blech_get_stimulus_presentation(
                EmptySession(),
                FakeStim(),
                None,
                "e1",
                "dev_local_time",
                tastant_field="tastant",
                stimid_field="stimid",
            )
