"""
ndi.time.syncrule.randomPulses - Sync rule for random pulse sequences.

This module provides the RandomPulses sync rule that synchronizes two DAQ
systems that recorded a shared random pulse sequence.

MATLAB path: +ndi/+time/+syncrule/randomPulses.m
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np

from ..syncrule_base import SyncRule
from ..timemapping import TimeMapping


def _parse_channel(ch_str: str) -> tuple[str, int]:
    """Parse a channel string like 'dep1' into ('dep', 1)."""
    match = re.search(r"\d", ch_str)
    if match is None:
        raise ValueError(f"Invalid channel string: {ch_str}")
    idx = match.start()
    return ch_str[:idx], int(ch_str[idx:])


def _sync_random_triggers(t1: np.ndarray, t2: np.ndarray) -> tuple[float, float]:
    """
    Find a linear mapping T1 = scale * T2 + shift by matching random pulses.

    Uses inter-pulse interval cross-correlation to find the best alignment,
    then performs a least-squares fit.

    Returns:
        Tuple of (shift, scale) where T1 ~ scale * T2 + shift.
    """
    if len(t1) < 2 or len(t2) < 2:
        raise ValueError("Need at least 2 triggers in each sequence to synchronize.")

    # Compute inter-pulse intervals
    ipi1 = np.diff(t1)
    ipi2 = np.diff(t2)

    # Normalize for cross-correlation
    ipi1_norm = (ipi1 - np.mean(ipi1)) / (np.std(ipi1) + 1e-15)
    ipi2_norm = (ipi2 - np.mean(ipi2)) / (np.std(ipi2) + 1e-15)

    # Cross-correlate to find best offset
    corr = np.correlate(ipi1_norm, ipi2_norm, mode="full")
    best_lag = int(np.argmax(corr)) - (len(ipi2_norm) - 1)

    # Determine overlapping region
    if best_lag >= 0:
        n_overlap = min(len(t1) - best_lag, len(t2))
        t1_matched = t1[best_lag : best_lag + n_overlap]
        t2_matched = t2[:n_overlap]
    else:
        n_overlap = min(len(t1), len(t2) + best_lag)
        t1_matched = t1[:n_overlap]
        t2_matched = t2[-best_lag : -best_lag + n_overlap]

    if n_overlap < 2:
        raise ValueError("Not enough overlapping triggers to compute mapping.")

    # Least-squares fit: T1 = scale * T2 + shift
    coeffs = np.polyfit(t2_matched, t1_matched, 1)
    scale = float(coeffs[0])
    shift = float(coeffs[1])

    # Validate fit quality
    residuals = t1_matched - (scale * t2_matched + shift)
    rms_error = float(np.sqrt(np.mean(residuals**2)))
    median_ipi = float(np.median(np.concatenate([ipi1, ipi2])))
    if median_ipi > 0 and rms_error > 0.1 * median_ipi:
        raise ValueError(
            f"Poor fit quality (RMS={rms_error:.4f}, "
            f"median IPI={median_ipi:.4f}). Sequences may not match."
        )

    return shift, scale


class RandomPulses(SyncRule):
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
        >>> rule = RandomPulses({
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
        return ["ndi.daq.system.mfdaq", "DAQSystem"]

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
    ) -> tuple[float | None, TimeMapping | None]:
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
            from ndi.query import Query

            q_existing = (
                Query("").isa("syncrule_mapping")
                & Query(
                    "syncrule_mapping.epochnode_a.epoch_id",
                    "exact_string",
                    epochnode_a.get("epoch_id", ""),
                )
                & Query(
                    "syncrule_mapping.epochnode_b.epoch_id",
                    "exact_string",
                    epochnode_b.get("epoch_id", ""),
                )
                & Query(
                    "syncrule_mapping.epochnode_a.objectname",
                    "exact_string",
                    name_a,
                )
                & Query(
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
                mapping = TimeMapping(sm.get("mapping", [1, 0]))
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
                mapping = TimeMapping([1.0 / scale, -shift / scale])
            else:
                # Want A->B, i.e. T2->T1
                # T1 = scale * T2 + shift
                mapping = TimeMapping([scale, shift])

            return 1.0, mapping

        except Exception:
            if p.get("errorOnFailure", True):
                raise
            return None, None
