"""``ndi.time.fun.syncTriggerTrains`` and the fallback that uses it.

NDI-python#223. ``commonTriggersOverlappingEpochs`` used to raise whenever the
two trigger counts differed; NDI-matlab 8736980ca made that recoverable by
falling back to ``ndi.time.fun.syncTriggerTrains``, which aligns trains of
unequal length. A dropped pulse is ordinary in a real recording, so the
refusal was firing on the normal case.

What these tests pin down is the pair of behaviours that make the fallback
safe to have at all: it must produce the RIGHT mapping when the trains really
do align, and it must produce NO mapping -- nan, not a plausible number --
when they do not. A wrong time mapping silently misaligns data, which is worse
than the exception it replaces.
"""

from __future__ import annotations

import logging

import numpy as np
import pytest

from ndi.time.syncrule.common_triggers_overlapping_epochs import (
    SyncAmbiguityError,
    _sync_trigger_trains,
    _sync_triggers,
    ndi_time_syncrule_commonTriggersOverlappingEpochs,
)

#: Known ground truth for the synthetic trains: T2 = SHIFT + SCALE * T1.
SHIFT = 12.5
SCALE = 1.0002


def make_train(n: int = 40, seed: int = 7, duration: float = 100.0) -> np.ndarray:
    """An irregular pulse train -- irregular so its intervals fingerprint."""
    rng = np.random.default_rng(seed)
    return np.sort(rng.uniform(0.0, duration, n))


class TestSyncTriggersUnchanged:
    """The equal-length least-squares path is untouched by the fallback."""

    def test_recovers_shift_and_scale(self):
        t1 = make_train()
        t2 = SHIFT + SCALE * t1
        shift, scale = _sync_triggers(t1, t2)
        assert shift == pytest.approx(SHIFT, abs=1e-6)
        assert scale == pytest.approx(SCALE, abs=1e-9)

    def test_still_rejects_a_count_mismatch(self):
        """_sync_triggers itself keeps its ValueError.

        The fallback lives in the CALLER, not in here: this function models
        vlt.time.syncTriggers, which has no notion of an unmatched pulse.
        """
        t1 = make_train()
        t2 = SHIFT + SCALE * np.delete(t1, 17)
        with pytest.raises(ValueError, match="Trigger count mismatch"):
            _sync_triggers(t1, t2)

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="Empty trigger arrays"):
            _sync_triggers(np.array([]), np.array([]))


class TestSyncTriggerTrains:
    """The ported ndi.time.fun.syncTriggerTrains."""

    def test_equal_length_recovers_known_shift_and_scale(self):
        t1 = make_train()
        t2 = SHIFT + SCALE * t1
        shift, scale = _sync_trigger_trains(t1, t2)
        assert shift == pytest.approx(SHIFT, abs=1e-6)
        assert scale == pytest.approx(SCALE, abs=1e-9)

    def test_dropped_pulse_still_recovers_known_shift_and_scale(self):
        """The whole point: a pulse missing from T2, and the answer survives.

        The drop is mid-train so that the intervals before it still form a
        fingerprint -- see test_a_drop_inside_the_lead_in_refuses for what
        happens when they do not.
        """
        t1 = make_train()
        t2 = np.delete(SHIFT + SCALE * t1, 17)
        shift, scale = _sync_trigger_trains(t1, t2)
        assert shift == pytest.approx(SHIFT, abs=1e-3)
        assert scale == pytest.approx(SCALE, abs=1e-5)

    def test_dropped_pulse_in_the_first_train(self):
        """Symmetric case: the drop is in T1, so T1 is the shorter train."""
        t1_full = make_train()
        t1 = np.delete(t1_full, 25)
        t2 = SHIFT + SCALE * t1_full
        shift, scale = _sync_trigger_trains(t1, t2)
        assert shift == pytest.approx(SHIFT, abs=1e-3)
        assert scale == pytest.approx(SCALE, abs=1e-5)

    def test_several_pulses_missing_from_the_longer_train_is_fine(self):
        """ "At most one missed pulse" counts the SHORTER train, not drops.

        Validation walks the shorter train and looks each pulse up in the
        longer one, so a pulse absent from the longer train is simply never
        looked for. Four drops still align.
        """
        t1 = make_train()
        t2 = np.delete(SHIFT + SCALE * t1, [17, 22, 31, 35])
        shift, scale = _sync_trigger_trains(t1, t2)
        assert shift == pytest.approx(SHIFT, abs=1e-3)
        assert scale == pytest.approx(SCALE, abs=1e-5)

    def test_two_unmatchable_pulses_refuse(self):
        """What the missed-pulse budget actually bounds.

        Two pulses in the shorter train land where the longer train has
        nothing -- a glitching line, say. That is two misses, one over budget,
        so no hypothesis validates and the answer is nan.
        """
        t1 = make_train()
        t2 = SHIFT + SCALE * t1
        t2[30] += 0.5
        t2[34] += 0.5
        t2 = np.sort(np.delete(t2, 17))
        shift, scale = _sync_trigger_trains(t1, t2)
        assert np.isnan(shift) and np.isnan(scale)

    def test_a_drop_inside_the_lead_in_refuses(self):
        """A limitation carried over from MATLAB, pinned so it stays visible.

        Candidate offsets come from runs of ``fingerprintSize`` consecutive
        intervals, and the rough shift for a nonzero offset is anchored at the
        FIRST pulse. Drop a pulse early enough that no unbroken fingerprint
        precedes it and the zero-offset hypothesis is never seeded, so the only
        surviving candidate anchors on the wrong pulse and fails validation.
        The result is nan -- a refusal, not a wrong mapping.
        """
        t1 = make_train()
        t2 = np.delete(SHIFT + SCALE * t1, 5)
        shift, scale = _sync_trigger_trains(t1, t2)
        assert np.isnan(shift) and np.isnan(scale)

    def test_too_few_pulses_to_fingerprint(self):
        t1 = make_train(n=4)
        t2 = SHIFT + SCALE * t1
        shift, scale = _sync_trigger_trains(t1, t2)
        assert np.isnan(shift) and np.isnan(scale)

    def test_unrelated_trains_refuse(self):
        """No alignment validates, so nan -- never a confident wrong answer."""
        t1 = make_train(seed=1)
        t2 = make_train(n=37, seed=2)
        shift, scale = _sync_trigger_trains(t1, t2)
        assert np.isnan(shift) and np.isnan(scale)

    def test_tolerates_jitter_within_the_alignment_tolerance(self):
        rng = np.random.default_rng(11)
        t1 = make_train()
        t2 = np.delete(SHIFT + SCALE * t1 + rng.uniform(-1e-3, 1e-3, len(t1)), 17)
        shift, scale = _sync_trigger_trains(t1, t2)
        assert shift == pytest.approx(SHIFT, abs=5e-3)
        assert scale == pytest.approx(SCALE, abs=1e-4)

    def test_perfectly_periodic_trains_are_ambiguous(self):
        """Uniform pulses align equally well at several offsets.

        MATLAB raises ndi:time:sync:ambiguous rather than picking one; so does
        this. Guessing here would misalign the data by whole pulse intervals.
        """
        t1 = np.arange(20, dtype=float)
        t2 = np.arange(25, dtype=float)
        with pytest.raises(SyncAmbiguityError):
            _sync_trigger_trains(t1, t2)
        assert SyncAmbiguityError.identifier == "ndi:time:sync:ambiguous"

    def test_accepts_lists_and_column_shaped_input(self):
        t1 = make_train()
        t2 = SHIFT + SCALE * t1
        shift, scale = _sync_trigger_trains(list(t1), t2.reshape(-1, 1))
        assert shift == pytest.approx(SHIFT, abs=1e-6)
        assert scale == pytest.approx(SCALE, abs=1e-9)


# ---------------------------------------------------------------------------
# End-to-end: the fallback wired into apply()
# ---------------------------------------------------------------------------


class _FakeSession:
    def __init__(self):
        self.systems: dict[str, _FakeDaqSystem] = {}

    def daqsystem_load(self, field, value):
        return self.systems.get(value)

    def database_search(self, query):
        return []


class _FakeDaqSystem:
    """Minimum surface apply() touches: an epoch table and readevents()."""

    def __init__(self, name, session, triggers, epoch_id, files):
        self.name = name
        self.session = session
        self._triggers = np.asarray(triggers, dtype=float)
        self._epoch_id = epoch_id
        self._files = files
        session.systems[name] = self

    def epochtable(self):
        return [
            {
                "epoch_id": self._epoch_id,
                "t0_t1": [0.0, 100.0],
                "underlying_epochs": {"underlying": self._files},
            }
        ]

    def readevents(self, event_types, channels, epoch_id, t0, t1):
        return self._triggers, None


def _build(t1, t2):
    """A configured rule plus the two epoch nodes apply() expects."""
    session = _FakeSession()
    # Embedded overlap: dev2's files sit one level under dev1's directory.
    files_1 = ["/data/session/dev1_a.bin"]
    files_2 = ["/data/session/sub/dev2_a.bin"]
    daq1 = _FakeDaqSystem("dev1", session, t1, "epoch_1", files_1)
    _FakeDaqSystem("dev2", session, t2, "epoch_2", files_2)

    rule = ndi_time_syncrule_commonTriggersOverlappingEpochs(
        {
            "daqsystem1_name": "dev1",
            "daqsystem2_name": "dev2",
            "daqsystem_ch1": "dep1",
            "daqsystem_ch2": "dep1",
            "epochclocktype": "dev_local_time",
            "minEmbeddedFileOverlap": 1,
            "errorOnFailure": True,
        }
    )
    node_a = {
        "objectname": "dev1",
        "epoch_id": "epoch_1",
        "epoch_clock": {"type": "dev_local_time"},
        "underlying_epochs": {"underlying": files_1},
    }
    node_b = {
        "objectname": "dev2",
        "epoch_id": "epoch_2",
        "epoch_clock": {"type": "dev_local_time"},
        "underlying_epochs": {"underlying": files_2},
    }
    return rule, node_a, node_b, daq1


class TestApplyFallback:
    def test_equal_counts_take_the_least_squares_path(self):
        t1 = make_train()
        t2 = SHIFT + SCALE * t1
        rule, node_a, node_b, daq1 = _build(t1, t2)

        cost, mapping = rule.apply(node_a, node_b, daq1)

        assert cost == 1.0
        assert mapping.mapping[0] == pytest.approx(SCALE, abs=1e-9)
        assert mapping.mapping[1] == pytest.approx(SHIFT, abs=1e-6)

    def test_mismatched_counts_now_produce_a_mapping(self, caplog):
        """The regression this whole change is about: used to raise."""
        t1 = make_train()
        t2 = np.delete(SHIFT + SCALE * t1, 17)
        rule, node_a, node_b, daq1 = _build(t1, t2)

        with caplog.at_level(logging.WARNING, logger="ndi"):
            cost, mapping = rule.apply(node_a, node_b, daq1)

        assert cost == 1.0
        assert mapping.mapping[0] == pytest.approx(SCALE, abs=1e-5)
        assert mapping.mapping[1] == pytest.approx(SHIFT, abs=1e-3)

    def test_the_fallback_says_so_out_loud(self, caplog):
        """A silent fallback would hide a real recording problem.

        The counts and both epoch ids have to be in the log line, because that
        is what tells someone reading it WHICH pair of epochs dropped a pulse.
        """
        t1 = make_train()
        t2 = np.delete(SHIFT + SCALE * t1, 17)
        rule, node_a, node_b, daq1 = _build(t1, t2)

        with caplog.at_level(logging.WARNING, logger="ndi"):
            rule.apply(node_a, node_b, daq1)

        messages = [r.getMessage() for r in caplog.records]
        assert any("trigger count mismatch" in m for m in messages)
        line = next(m for m in messages if "trigger count mismatch" in m)
        assert "T1=40" in line and "T2=39" in line
        assert "epoch_a=epoch_1" in line and "epoch_b=epoch_2" in line
        assert "syncTriggerTrains fallback" in line

    def test_equal_counts_stay_quiet(self, caplog):
        t1 = make_train()
        t2 = SHIFT + SCALE * t1
        rule, node_a, node_b, daq1 = _build(t1, t2)

        with caplog.at_level(logging.WARNING, logger="ndi"):
            rule.apply(node_a, node_b, daq1)

        assert not any("trigger count mismatch" in r.getMessage() for r in caplog.records)

    def test_node_order_reversed_inverts_the_mapping(self):
        """apply(b, a) must map dev2 -> dev1, i.e. the inverse line."""
        t1 = make_train()
        t2 = np.delete(SHIFT + SCALE * t1, 17)
        rule, node_a, node_b, daq1 = _build(t1, t2)
        daq2 = daq1.session.systems["dev2"]

        cost, mapping = rule.apply(node_b, node_a, daq2)

        assert cost == 1.0
        assert mapping.mapping[0] == pytest.approx(1.0 / SCALE, abs=1e-5)
        assert mapping.mapping[1] == pytest.approx(-SHIFT / SCALE, abs=1e-3)
