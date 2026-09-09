"""
ndi.time.syncrule.randomPulses - Sync rule for random pulse sequences.

This module provides the ndi_time_syncrule_randomPulses sync rule that synchronizes two DAQ
systems that recorded a shared random pulse sequence.

MATLAB path: +ndi/+time/+syncrule/randomPulses.m
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np

from ..syncrule_base import ndi_time_syncrule
from ..timemapping import ndi_time_timemapping
from .common_triggers_overlapping_epochs import _matlab_round


def _parse_channel(ch_str: str) -> tuple[str, int]:
    """Parse a channel string like 'dep1' into ('dep', 1)."""
    match = re.search(r"\d", ch_str)
    if match is None:
        raise ValueError(f"Invalid channel string: {ch_str}")
    idx = match.start()
    return ch_str[:idx], int(ch_str[idx:])


def _run_hash_sync(
    target: np.ndarray,
    prober: np.ndarray,
    alignment_tolerance: float,
    fingerprint_size: int,
    rng: np.random.Generator,
) -> tuple[float, float]:
    """Hash target intervals, probe with prober intervals in random order.

    Returns ``(shift, scale)`` such that ``target = shift + scale * prober``,
    or ``(nan, nan)`` when no candidate passes the secondary pulse check.

    Mirrors ``runHashSync`` in ``+ndi/+time/+fun/syncRandomTriggers.m``.
    """
    tol = alignment_tolerance
    f_size = fingerprint_size

    # Quantize target intervals into buckets of width `tol`. `_matlab_round`
    # (half-away-from-zero) matches MATLAB's default `round`, so that halves
    # land in the same bucket on both sides.
    q_target = _matlab_round(np.diff(target) / tol).astype(np.int64)
    fingerprints: dict[tuple[int, ...], int] = {}
    for i in range(len(q_target) - f_size + 1):
        key = tuple(int(v) for v in q_target[i : i + f_size])
        # MATLAB's `if ~isKey`: keep the FIRST occurrence, ignore later ones.
        if key not in fingerprints:
            fingerprints[key] = i

    q_prober = _matlab_round(np.diff(prober) / tol).astype(np.int64)
    num_probes = len(q_prober) - f_size + 1
    if num_probes <= 0:
        return float("nan"), float("nan")

    # Randomized probe order so overlap is found in O(1) expected time no
    # matter where in the recording it sits. `rng.permutation` is MATLAB's
    # `randperm` for our purposes here.
    search_order = rng.permutation(num_probes)

    for i in search_order:
        i = int(i)
        key = tuple(int(v) for v in q_prober[i : i + f_size])
        idx_target = fingerprints.get(key)
        if idx_target is None:
            continue

        # A fingerprint of `f_size` intervals spans `f_size + 1` pulses.
        p_target = target[idx_target : idx_target + f_size + 1]
        p_prober = prober[i : i + f_size + 1]

        # polyfit(prober, target, 1) -> target = scale * prober + shift.
        seed_model = np.polyfit(p_prober, p_target, 1)
        scale = float(seed_model[0])
        shift = float(seed_model[1])

        # Verification: check one pulse beyond the fingerprint on each side.
        # A coincidental interval match still fails this if the clocks are
        # not actually aligned. `continue` lets the search try the next
        # candidate rather than committing to the coincidence.
        if (i + f_size + 1 < len(prober)) and (idx_target + f_size + 1 < len(target)):
            test_p_prob = float(prober[i + f_size + 1])
            test_p_target = float(target[idx_target + f_size + 1])
            predicted = scale * test_p_prob + shift
            if abs(test_p_target - predicted) > tol:
                continue

        return shift, scale

    return float("nan"), float("nan")


def _sync_random_triggers(
    t1: np.ndarray,
    t2: np.ndarray,
    alignment_tolerance: float = 0.002,
    fingerprint_size: int = 4,
    rng: np.random.Generator | None = None,
) -> tuple[float, float]:
    """Synchronize two clocks that recorded a common random pulse sequence.

    MATLAB counterpart: ``ndi.time.fun.syncRandomTriggers``. Returns
    ``(shift, scale)`` such that ``t1 = shift + scale * t2``. **Returns
    ``(nan, nan)`` when no candidate alignment validates** -- that is
    MATLAB's failure contract, and callers must check.

    The algorithm hashes interval fingerprints from the longer recording,
    probes them in randomized order with fingerprints from the shorter one,
    and validates each hit with a secondary pulse check before committing.
    A coincidental interval match is discarded and the search continues, so
    a wrong candidate does not commit -- unlike a single-shot argmax on the
    inter-pulse-interval cross-correlation.

    Args:
        t1: Pulse times (seconds) from device 1.
        t2: Pulse times (seconds) from device 2.
        alignment_tolerance: Maximum jitter (s) allowed between clocks to
            consider two pulses a match. Also the quantization bucket width.
            Default 2 ms, matching MATLAB.
        fingerprint_size: Number of intervals per hash key. Default 4.
        rng: Optional numpy Generator used for the probe permutation. Tests
            inject one for reproducibility; production callers leave it None.
    """
    t1 = np.asarray(t1, dtype=float).ravel()
    t2 = np.asarray(t2, dtype=float).ravel()

    f_size = fingerprint_size

    # Not enough pulses to form a single fingerprint on both sides.
    if len(t1) <= f_size or len(t2) <= f_size:
        return float("nan"), float("nan")

    if rng is None:
        rng = np.random.default_rng()

    # Hash the LONGER recording so the shorter one probes into a denser map.
    # `dur = max - min` rather than `len(t)` because partial-overlap
    # recordings have their pulse counts skewed by which run started earlier.
    dur1 = float(np.max(t1) - np.min(t1))
    dur2 = float(np.max(t2) - np.min(t2))

    if dur1 >= dur2:
        # target = t1, prober = t2 -> t1 = shift + scale * t2 (what we want).
        return _run_hash_sync(t1, t2, alignment_tolerance, f_size, rng)

    # target = t2, prober = t1 -> t2 = s_inv + m_inv * t1. Invert:
    # t1 = (-s_inv / m_inv) + (1 / m_inv) * t2.
    s_inv, m_inv = _run_hash_sync(t2, t1, alignment_tolerance, f_size, rng)
    if np.isnan(s_inv) or np.isnan(m_inv) or m_inv == 0:
        return float("nan"), float("nan")
    return -s_inv / m_inv, 1.0 / m_inv


class ndi_time_syncrule_randomPulses(ndi_time_syncrule):
    """
    Synchronization rule based on random pulse sequences on a shared channel.

    This sync rule synchronizes two DAQ systems that recorded a shared random
    pulse sequence. It uses inter-pulse interval cross-correlation to find the
    best alignment, then computes a linear time mapping via least-squares fit.

    Parameters:
        daqsystem1_name (str): Name of the first DAQ system.
        daqsystem2_name (str): Name of the second DAQ system.
        daqsystem_ch1 (str): Channel to read on DAQ system 1 (e.g., 'dep1').
        daqsystem_ch2 (str): Channel to read on DAQ system 2 (e.g., 'mk1').
        epochclocktype (str): The epoch clock type to consider.
        errorOnFailure (bool): If True, raise on failure.

    Example:
        >>> rule = ndi_time_syncrule_randomPulses({
        ...     'daqsystem1_name': 'daq1',
        ...     'daqsystem2_name': 'daq2',
        ...     'daqsystem_ch1': 'dep1',
        ...     'daqsystem_ch2': 'mk1',
        ... })
    """

    def __init__(
        self,
        parameters: dict[str, Any] | None = None,
        identifier: str | None = None,
    ):
        if parameters is None:
            parameters = {
                "daqsystem1_name": "",
                "daqsystem2_name": "",
                "daqsystem_ch1": "",
                "daqsystem_ch2": "",
                "epochclocktype": "dev_local_time",
                "errorOnFailure": True,
            }
        super().__init__(parameters, identifier)

    def is_valid_parameters(self, parameters: dict[str, Any]) -> tuple[bool, str]:
        if not isinstance(parameters, dict):
            return False, "Parameters must be a dictionary"

        required_fields = [
            "daqsystem1_name",
            "daqsystem2_name",
            "daqsystem_ch1",
            "daqsystem_ch2",
            "epochclocktype",
            "errorOnFailure",
        ]
        for field in required_fields:
            if field not in parameters:
                return False, f"Missing required field: {field}"

        for field in [
            "daqsystem1_name",
            "daqsystem2_name",
            "daqsystem_ch1",
            "daqsystem_ch2",
            "epochclocktype",
        ]:
            if not isinstance(parameters[field], str):
                return (
                    False,
                    "daqsystem names, channels, and epochclocktype " "must be strings.",
                )

        if not isinstance(parameters["errorOnFailure"], (bool, int)):
            return False, "errorOnFailure must be logical or numeric (0/1)."

        return True, ""

    def eligible_epochsets(self) -> list[str]:
        """Return eligible epochset class names."""
        return ["ndi.daq.system.mfdaq"]

    def ineligible_epochsets(self) -> list[str]:
        """Return ineligible epochset class names."""
        base_ineligible = super().ineligible_epochsets()
        return base_ineligible + [
            "ndi.epoch.epochset",
            "ndi.epoch.epochset.param",
            "ndi.file.navigator",
        ]

    def apply(
        self,
        epochnode_a: dict[str, Any],
        epochnode_b: dict[str, Any],
        daqsystem_a: Any = None,
    ) -> tuple[float | None, ndi_time_timemapping | None]:
        """
        Apply the sync rule to obtain a cost and mapping between two epoch nodes.

        Args:
            epochnode_a: First epoch node dict.
            epochnode_b: Second epoch node dict.
            daqsystem_a: The ndi.daq.system corresponding to epochnode_a.

        Returns:
            Tuple of (cost, mapping) or (None, None) if no sync possible.
        """
        p = self._parameters

        # 1. Verify epochnodes match the configured DAQ system pair
        name_a = epochnode_a.get("objectname", "")
        name_b = epochnode_b.get("objectname", "")

        node_a_is_1 = name_a == p["daqsystem1_name"]
        node_a_is_2 = name_a == p["daqsystem2_name"]
        node_b_is_1 = name_b == p["daqsystem1_name"]
        node_b_is_2 = name_b == p["daqsystem2_name"]

        if not ((node_a_is_1 and node_b_is_2) or (node_a_is_2 and node_b_is_1)):
            return None, None

        # Check epoch clock type
        clock_a = epochnode_a.get("epoch_clock", {})
        clock_b = epochnode_b.get("epoch_clock", {})
        clock_type_a = (
            clock_a.get("type", "") if isinstance(clock_a, dict) else getattr(clock_a, "type", "")
        )
        clock_type_b = (
            clock_b.get("type", "") if isinstance(clock_b, dict) else getattr(clock_b, "type", "")
        )

        if clock_type_a != p["epochclocktype"] or clock_type_b != p["epochclocktype"]:
            return None, None

        # Assign roles
        if node_a_is_1:
            daqsystem1 = daqsystem_a
            session = getattr(daqsystem1, "session", None)
            if session is None:
                return None, None
            daqsystem2 = session.daqsystem_load("name", p["daqsystem2_name"])
        else:
            daqsystem2 = daqsystem_a
            session = getattr(daqsystem2, "session", None)
            if session is None:
                return None, None
            daqsystem1 = session.daqsystem_load("name", p["daqsystem1_name"])

        if daqsystem1 is None or daqsystem2 is None:
            if p.get("errorOnFailure", True):
                raise RuntimeError("Could not load both DAQ systems.")
            return None, None

        if isinstance(daqsystem1, list):
            daqsystem1 = daqsystem1[0]
        if isinstance(daqsystem2, list):
            daqsystem2 = daqsystem2[0]

        # 2. Check for existing syncrule_mapping in database
        try:
            from ndi.query import ndi_query

            q_existing = (
                ndi_query("").isa("syncrule_mapping")
                & ndi_query(
                    "syncrule_mapping.epochnode_a.epoch_id",
                    "exact_string",
                    epochnode_a.get("epoch_id", ""),
                )
                & ndi_query(
                    "syncrule_mapping.epochnode_b.epoch_id",
                    "exact_string",
                    epochnode_b.get("epoch_id", ""),
                )
                & ndi_query(
                    "syncrule_mapping.epochnode_a.objectname",
                    "exact_string",
                    name_a,
                )
                & ndi_query(
                    "syncrule_mapping.epochnode_b.objectname",
                    "exact_string",
                    name_b,
                )
            )
            existing_docs = session.database_search(q_existing)
            if existing_docs:
                doc = existing_docs[0]
                props = doc.document_properties
                sm = props.get("syncrule_mapping", {})
                cost = sm.get("cost", 1.0)
                mapping = ndi_time_timemapping(sm.get("mapping", [1, 0]))
                return cost, mapping
        except Exception:
            pass  # No cached mapping, compute fresh

        try:
            # 3. Read triggers
            type1, ch1 = _parse_channel(p["daqsystem_ch1"])
            type2, ch2 = _parse_channel(p["daqsystem_ch2"])

            if node_a_is_1:
                epochnode_1 = epochnode_a
                epochnode_2 = epochnode_b
            else:
                epochnode_1 = epochnode_b
                epochnode_2 = epochnode_a

            # Read T1
            eid1 = epochnode_1.get("epoch_id", "")
            ts1, _ = daqsystem1.readevents([type1], ch1, eid1, float("-inf"), float("inf"))
            if isinstance(ts1, list):
                ts1 = ts1[0] if ts1 else np.array([])
            if not isinstance(ts1, np.ndarray):
                ts1 = np.array(ts1 if ts1 is not None else [])
            t1 = np.sort(ts1.flatten())

            # Read T2
            eid2 = epochnode_2.get("epoch_id", "")
            ts2, _ = daqsystem2.readevents([type2], ch2, eid2, float("-inf"), float("inf"))
            if isinstance(ts2, list):
                ts2 = ts2[0] if ts2 else np.array([])
            if not isinstance(ts2, np.ndarray):
                ts2 = np.array(ts2 if ts2 is not None else [])
            t2 = np.sort(ts2.flatten())

            # 4. Compute mapping: T1 = scale * T2 + shift
            shift, scale = _sync_random_triggers(t1, t2)

            if np.isnan(shift) or np.isnan(scale):
                if p.get("errorOnFailure", True):
                    raise ValueError("Could not find random pulse match.")
                return None, None

            # Build mapping from A to B
            if node_a_is_1:
                # Want A->B, i.e. T1->T2
                # T1 = scale * T2 + shift -> T2 = (T1 - shift) / scale
                mapping = ndi_time_timemapping([1.0 / scale, -shift / scale])
            else:
                # Want A->B, i.e. T2->T1
                # T1 = scale * T2 + shift
                mapping = ndi_time_timemapping([scale, shift])

            return 1.0, mapping

        except Exception:
            if p.get("errorOnFailure", True):
                raise
            return None, None
