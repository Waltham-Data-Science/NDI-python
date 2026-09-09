"""``ndi.time.fun.syncRandomTriggers`` and the ``randomPulses`` sync rule.

NDI-python#249. The pre-existing Python helper was a cross-correlation argmax
with different guarantees from MATLAB: any input produced an answer, and the
failure mode was a ``ValueError`` on RMS rather than a ``(nan, nan)`` return
on no match. The port here mirrors ``+ndi/+time/+fun/syncRandomTriggers.m``:
hash the longer recording's interval fingerprints, probe the shorter one in
randomized order, verify each hit with a secondary pulse check, and return
``(nan, nan)`` when nothing validates.

The tests below pin the shape of that contract -- known shift/scale
recovered, partial overlap handled, unrelated trains refused rather than
answered wrong, periodic trains answered plausibly (they are, empirically,
the case where MATLAB and the port both make a choice they cannot uniquely
justify). Each call injects a seeded ``rng`` so the probe permutation is
reproducible.
"""

from __future__ import annotations

import numpy as np
import pytest

from ndi.time.syncrule.random_pulses import (
    _sync_random_triggers,
    ndi_time_syncrule_randomPulses,
)

#: Known ground truth for the synthetic trains: t1 = SHIFT + SCALE * t2.
#: Note that syncRandomTriggers takes the OPPOSITE convention from
#: syncTriggerTrains -- MATLAB's header documents it this way and the port
#: preserves it, so the test fixtures do too.
SHIFT = 12.5
SCALE = 1.0002


def make_train(n: int = 40, seed: int = 7, duration: float = 100.0) -> np.ndarray:
    """An irregular pulse train -- irregular so its intervals fingerprint."""
    rng = np.random.default_rng(seed)
    return np.sort(rng.uniform(0.0, duration, n))


def _rng() -> np.random.Generator:
    """A fresh seeded generator for reproducible probe permutations."""
    return np.random.default_rng(1)


class TestSyncRandomTriggers:
    """The ported ndi.time.fun.syncRandomTriggers."""

    def test_equal_length_recovers_known_shift_and_scale(self):
        t2 = make_train()
        t1 = SHIFT + SCALE * t2
        shift, scale = _sync_random_triggers(t1, t2, rng=_rng())
        assert shift == pytest.approx(SHIFT, abs=1e-9)
        assert scale == pytest.approx(SCALE, abs=1e-12)

    def test_partial_overlap_shorter_prober(self):
        """t1 covers only the second half of the recording, t2 covers all of it.

        MATLAB hashes the LONGER-duration recording and probes with the
        shorter, so this exercises the ``dur1 >= dur2`` else-branch of the
        outer function and its algebraic inversion. Either sign of the
        overlap should recover the same mapping.
        """
        t2_all = make_train(n=80, duration=200.0)
        t1_half = SHIFT + SCALE * t2_all[40:]  # only the tail of the run
        shift, scale = _sync_random_triggers(t1_half, t2_all, rng=_rng())
        assert shift == pytest.approx(SHIFT, abs=1e-9)
        assert scale == pytest.approx(SCALE, abs=1e-12)

    def test_partial_overlap_the_other_way_round(self):
        """Symmetric: now t2 is the shorter recording."""
        t1_all = SHIFT + SCALE * make_train(n=80, duration=200.0)
        t2_half = (t1_all[:40] - SHIFT) / SCALE
        shift, scale = _sync_random_triggers(t1_all, t2_half, rng=_rng())
        assert shift == pytest.approx(SHIFT, abs=1e-9)
        assert scale == pytest.approx(SCALE, abs=1e-12)

    def test_unrelated_trains_return_nan(self):
        """No fingerprint validates -- so nan, not a confident wrong answer.

        This is the whole reason for the failure-contract change: the old
        cross-correlation argmax always committed to a lag, and its RMS gate
        surfaced the mismatch as an exception. The port matches MATLAB and
        returns ``(nan, nan)``, so a caller can branch on it.
        """
        t1 = make_train(seed=1)
        t2 = make_train(n=37, seed=2)
        shift, scale = _sync_random_triggers(t1, t2, rng=_rng())
        assert np.isnan(shift) and np.isnan(scale)

    def test_too_few_pulses_to_fingerprint(self):
        """Fewer pulses than ``fingerprintSize + 1`` cannot form a key."""
        t2 = make_train(n=4)
        t1 = SHIFT + SCALE * t2
        shift, scale = _sync_random_triggers(t1, t2, rng=_rng())
        assert np.isnan(shift) and np.isnan(scale)

    def test_tolerates_jitter_well_inside_the_alignment_tolerance(self):
        """Sub-tolerance jitter still hashes into the same bucket.

        syncRandomTriggers quantizes intervals into buckets of width
        ``alignment_tolerance`` (unlike syncTriggerTrains, which uses
        ``2 * tol`` to widen the bucket). Two adjacent pulses each carry
        jitter, so the interval jitter is up to twice the per-pulse jitter
        -- pick a jitter well under half a bucket to stay reliably inside
        one bucket.
        """
        rng_jit = np.random.default_rng(11)
        t2 = make_train()
        t1 = SHIFT + SCALE * t2 + rng_jit.uniform(-2e-4, 2e-4, len(t2))
        shift, scale = _sync_random_triggers(t1, t2, rng=_rng())
        assert shift == pytest.approx(SHIFT, abs=5e-3)
        assert scale == pytest.approx(SCALE, abs=1e-4)

    def test_secondary_pulse_check_rejects_a_coincidental_fingerprint(self):
        """A same-shape interval sequence at the wrong offset is refused.

        This is the point of the ``continue`` after the verification test:
        two very short fingerprint windows can match by chance in dense
        data, and the port must NOT commit on the first key match. We
        construct a case where the shorter fingerprint window happens to
        appear twice in ``t2`` but only the second occurrence carries the
        right global shift, and check that the port converges on the
        second one rather than committing to the first.
        """
        # A random train with one extra insertion whose interval shape by
        # design coincides with the very first fingerprint. Small enough
        # fingerprintSize=2 to make the coincidence hit reliably.
        t2 = make_train()
        # Replay the first two intervals near a later position, so quantized
        # fingerprints collide but the linear model does not extend.
        d0 = t2[1] - t2[0]
        d1 = t2[2] - t2[1]
        anchor = 50.0
        t2 = np.sort(np.concatenate([t2, [anchor, anchor + d0, anchor + d0 + d1]]))
        t1 = SHIFT + SCALE * t2
        shift, scale = _sync_random_triggers(t1, t2, fingerprint_size=2, rng=_rng())
        assert shift == pytest.approx(SHIFT, abs=1e-9)
        assert scale == pytest.approx(SCALE, abs=1e-12)

    def test_periodic_trains_pick_a_candidate_matlab_does_not_disambiguate(self):
        """A uniform train gives many equally-plausible offsets.

        Unlike syncTriggerTrains, syncRandomTriggers does NOT detect
        ambiguity: it returns the first fingerprint that survives the
        secondary check. On perfectly periodic data every fingerprint
        matches every fingerprint AND the secondary check also passes at
        multiple offsets, so the answer is one of several equally-valid
        alignments -- possibly off by a whole pulse period.

        This test pins that behaviour deliberately. It is a known
        limitation of the algorithm shared by both sides; a caller who
        cares about ambiguity should use syncTriggerTrains, which raises
        SyncAmbiguityError in the corresponding case.
        """
        t2 = np.arange(25, dtype=float)
        t1 = SHIFT + SCALE * np.arange(20, dtype=float)
        shift, scale = _sync_random_triggers(t1, t2, rng=_rng())
        # Something was returned -- and the slope is right, because a unit-
        # period train constrains SCALE cleanly.
        assert not np.isnan(shift) and not np.isnan(scale)
        assert scale == pytest.approx(SCALE, abs=1e-6)

    def test_accepts_lists_and_column_shaped_input(self):
        t2 = make_train()
        t1 = SHIFT + SCALE * t2
        shift, scale = _sync_random_triggers(list(t1), t2.reshape(-1, 1), rng=_rng())
        assert shift == pytest.approx(SHIFT, abs=1e-9)
        assert scale == pytest.approx(SCALE, abs=1e-12)

    def test_default_rng_still_produces_a_valid_answer(self):
        """No rng argument -> uses np.random.default_rng() internally.

        Different runs may pick different fingerprints (verification means
        each is valid), but the resulting SHIFT and SCALE must always be
        the mapping that actually holds on the data.
        """
        t2 = make_train()
        t1 = SHIFT + SCALE * t2
        shift, scale = _sync_random_triggers(t1, t2)  # no rng
        assert shift == pytest.approx(SHIFT, abs=1e-6)
        assert scale == pytest.approx(SCALE, abs=1e-9)


# ---------------------------------------------------------------------------
# End-to-end: the port wired into apply()
# ---------------------------------------------------------------------------


class _FakeSession:
    def __init__(self):
        self.systems: dict[str, _FakeDaqSystem] = {}

    def daqsystem_load(self, field, value):
        return self.systems.get(value)

    def database_search(self, query):
        return []


class _FakeDaqSystem:
    """Minimum surface apply() touches: a name, session, and readevents()."""

    def __init__(self, name, session, triggers, epoch_id):
        self.name = name
        self.session = session
        self._triggers = np.asarray(triggers, dtype=float)
        self._epoch_id = epoch_id
        session.systems[name] = self

    def readevents(self, event_types, channels, epoch_id, t0, t1):
        return self._triggers, None


def _build(t1, t2):
    """A configured rule plus the two epoch nodes apply() expects."""
    session = _FakeSession()
    _FakeDaqSystem("dev1", session, t1, "epoch_1")
    _FakeDaqSystem("dev2", session, t2, "epoch_2")

    rule = ndi_time_syncrule_randomPulses(
        {
            "daqsystem1_name": "dev1",
            "daqsystem2_name": "dev2",
            "daqsystem_ch1": "dep1",
            "daqsystem_ch2": "dep1",
            "epochclocktype": "dev_local_time",
            "errorOnFailure": True,
        }
    )
    node_a = {
        "objectname": "dev1",
        "epoch_id": "epoch_1",
        "epoch_clock": {"type": "dev_local_time"},
    }
    node_b = {
        "objectname": "dev2",
        "epoch_id": "epoch_2",
        "epoch_clock": {"type": "dev_local_time"},
    }
    daq1 = session.systems["dev1"]
    return rule, node_a, node_b, daq1


class TestApplyNaNContract:
    """The NaN return path from the helper is now the live failure branch."""

    def test_matched_trains_produce_a_mapping(self):
        t2 = make_train()
        t1 = SHIFT + SCALE * t2
        rule, node_a, node_b, daq1 = _build(t1, t2)

        cost, mapping = rule.apply(node_a, node_b, daq1)

        assert cost == 1.0
        # apply() converts t1 = shift + scale * t2 into A(1) -> B(2) as
        # t2 = (1/scale) * t1 - shift/scale. Pin the exact conversion.
        assert mapping.mapping[0] == pytest.approx(1.0 / SCALE, abs=1e-9)
        assert mapping.mapping[1] == pytest.approx(-SHIFT / SCALE, abs=1e-6)

    def test_unrelated_trains_raise_when_error_on_failure_is_true(self):
        """The isnan branch used to be unreachable. Now it fires."""
        t1 = make_train(seed=1)
        t2 = make_train(n=37, seed=2)
        rule, node_a, node_b, daq1 = _build(t1, t2)

        with pytest.raises(ValueError, match="Could not find random pulse match"):
            rule.apply(node_a, node_b, daq1)

    def test_unrelated_trains_return_none_when_error_on_failure_is_false(self):
        t1 = make_train(seed=1)
        t2 = make_train(n=37, seed=2)
        rule, node_a, node_b, daq1 = _build(t1, t2)
        rule._parameters["errorOnFailure"] = False

        cost, mapping = rule.apply(node_a, node_b, daq1)

        assert cost is None and mapping is None

    def test_node_order_reversed_inverts_the_mapping(self):
        """apply(b, a) must map dev2 -> dev1, i.e. the inverse line."""
        t2 = make_train()
        t1 = SHIFT + SCALE * t2
        rule, node_a, node_b, daq1 = _build(t1, t2)
        daq2 = daq1.session.systems["dev2"]

        cost, mapping = rule.apply(node_b, node_a, daq2)

        assert cost == 1.0
        # Reversed: A is dev2, B is dev1, so mapping is t2 -> t1, which is
        # t1 = SHIFT + SCALE * t2 directly.
        assert mapping.mapping[0] == pytest.approx(SCALE, abs=1e-9)
        assert mapping.mapping[1] == pytest.approx(SHIFT, abs=1e-6)
