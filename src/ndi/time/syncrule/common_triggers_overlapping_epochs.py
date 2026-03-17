"""
ndi.time.syncrule.commonTriggersOverlappingEpochs - Sync rule for common triggers.

This module provides the ndi_time_syncrule_commonTriggersOverlappingEpochs sync rule that
synchronizes two DAQ systems by finding a linear time mapping from shared
trigger events recorded on overlapping (embedded) epochs.

MATLAB path: +ndi/+time/+syncrule/commonTriggersOverlappingEpochs.m
"""

from __future__ import annotations

import os
import re
from typing import Any

import numpy as np

from ..syncrule_base import ndi_time_syncrule
from ..timemapping import ndi_time_timemapping


def _parse_channel(ch_str: str) -> tuple[str, int]:
    """Parse a channel string like 'dep1' into ('dep', 1)."""
    match = re.search(r"\d", ch_str)
    if match is None:
        raise ValueError(f"Invalid channel string: {ch_str}")
    idx = match.start()
    return ch_str[:idx], int(ch_str[idx:])


def _get_parents(files: list[str]) -> list[str]:
    """Return unique parent directories of the given file paths."""
    return list({os.path.dirname(f) for f in files})


def _get_grandparents(files: list[str]) -> list[str]:
    """Return unique grandparent directories of the given file paths."""
    return list({os.path.dirname(os.path.dirname(f)) for f in files})


def _count_embedded_matches(files_deep: list[str], files_shallow: list[str]) -> int:
    """Count files in files_deep whose grandparent matches a parent of files_shallow."""
    parent_set = set(_get_parents(files_shallow))
    count = 0
    for f in files_deep:
        gp = os.path.dirname(os.path.dirname(f))
        if gp in parent_set:
            count += 1
    return count


def _sync_triggers(t1: np.ndarray, t2: np.ndarray) -> tuple[float, float]:
    """
    Find a linear mapping T2 = scale * T1 + shift via least-squares fit.

    Returns:
        Tuple of (shift, scale) where T2 ~ scale * T1 + shift.
    """
    if len(t1) == 0 or len(t2) == 0:
        raise ValueError("Empty trigger arrays cannot be synchronized.")
    if len(t1) != len(t2):
        raise ValueError(
            f"Trigger count mismatch: {len(t1)} vs {len(t2)}. " "Cannot compute linear mapping."
        )
    coeffs = np.polyfit(t1, t2, 1)
    scale = float(coeffs[0])
    shift = float(coeffs[1])
    return shift, scale


def _get_underlying_files(epochnode: dict[str, Any]) -> list[str]:
    """Extract underlying file paths from an epoch node."""
    underlying = epochnode.get("underlying_epochs")
    if not underlying:
        return []
    if isinstance(underlying, dict):
        files = underlying.get("underlying", [])
    elif hasattr(underlying, "underlying"):
        files = underlying.underlying
    else:
        return []
    if isinstance(files, list):
        return [str(f) for f in files]
    return []


class ndi_time_syncrule_commonTriggersOverlappingEpochs(ndi_time_syncrule):
    """
    Synchronization rule based on common triggers in overlapping embedded epochs.

    This sync rule assumes that the 'dev_local_time' of the DAQ systems reflects
    a shared absolute time reference (e.g., time of day) such that sorting
    disjoint trigger events chronologically aligns them correctly.

    Parameters:
        daqsystem1_name (str): Name of the first DAQ system.
        daqsystem2_name (str): Name of the second DAQ system.
        daqsystem_ch1 (str): Channel to read on DAQ system 1 (e.g., 'dep1').
        daqsystem_ch2 (str): Channel to read on DAQ system 2 (e.g., 'mk1').
        epochclocktype (str): The epoch clock type to consider.
        minEmbeddedFileOverlap (int): Minimum embedded file matches required.
        errorOnFailure (bool): If True, raise on failure.

    Example:
        >>> rule = ndi_time_syncrule_commonTriggersOverlappingEpochs({
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
                "minEmbeddedFileOverlap": 1,
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
            "minEmbeddedFileOverlap",
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
                    "daqsystem names, channels, and epochclocktype must be strings.",
                )

        if not isinstance(parameters["minEmbeddedFileOverlap"], (int, float)):
            return False, "minEmbeddedFileOverlap must be a number."

        if not isinstance(parameters["errorOnFailure"], (bool, int)):
            return False, "errorOnFailure must be logical or numeric (0/1)."

        return True, ""

    def eligible_epochsets(self) -> list[str]:
        """Return eligible epochset class names."""
        return ["ndi.daq.system"]

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

        # 3. Check initial embedded file overlap
        files_a = _get_underlying_files(epochnode_a)
        files_b = _get_underlying_files(epochnode_b)

        count1 = _count_embedded_matches(files_a, files_b)
        count2 = _count_embedded_matches(files_b, files_a)

        min_overlap = p.get("minEmbeddedFileOverlap", 1)
        if max(count1, count2) < min_overlap:
            return None, None

        # 4. Expand epoch group by finding all connected overlapping epochs
        epochs_a_all = daqsystem_a.epochtable() if daqsystem_a is not None else []
        if node_a_is_1:
            epochs_b_all = daqsystem2.epochtable()
        else:
            epochs_b_all = daqsystem1.epochtable()

        id_a_seed = epochnode_a.get("epoch_id", "")
        id_b_seed = epochnode_b.get("epoch_id", "")

        def _find_epoch_index(epoch_table: list, epoch_id: str) -> int | None:
            for i, ep in enumerate(epoch_table):
                eid = (
                    ep.get("epoch_id", "") if isinstance(ep, dict) else getattr(ep, "epoch_id", "")
                )
                if eid == epoch_id:
                    return i
            return None

        idx_a_seed = _find_epoch_index(epochs_a_all, id_a_seed)
        idx_b_seed = _find_epoch_index(epochs_b_all, id_b_seed)

        if idx_a_seed is None or idx_b_seed is None:
            return None, None

        group_a: set[int] = {idx_a_seed}
        group_b: set[int] = {idx_b_seed}

        def _get_epoch_files(epoch_table: list, idx: int) -> list[str]:
            ep = epoch_table[idx]
            if isinstance(ep, dict):
                ue = ep.get("underlying_epochs", {})
            elif hasattr(ep, "underlying_epochs"):
                ue = ep.underlying_epochs
            else:
                return []
            if isinstance(ue, dict):
                return [str(f) for f in ue.get("underlying", [])]
            elif hasattr(ue, "underlying"):
                return [str(f) for f in ue.underlying]
            return []

        # Iteratively expand groups
        added = True
        while added:
            added = False
            for i in range(len(epochs_a_all)):
                if i in group_a:
                    continue
                f_a = _get_epoch_files(epochs_a_all, i)
                for j in group_b:
                    f_b = _get_epoch_files(epochs_b_all, j)
                    c1 = _count_embedded_matches(f_a, f_b)
                    c2 = _count_embedded_matches(f_b, f_a)
                    if max(c1, c2) >= min_overlap:
                        group_a.add(i)
                        added = True
                        break

            for i in range(len(epochs_b_all)):
                if i in group_b:
                    continue
                f_b = _get_epoch_files(epochs_b_all, i)
                for j in group_a:
                    f_a = _get_epoch_files(epochs_a_all, j)
                    c1 = _count_embedded_matches(f_b, f_a)
                    c2 = _count_embedded_matches(f_a, f_b)
                    if max(c1, c2) >= min_overlap:
                        group_b.add(i)
                        added = True
                        break

        try:
            # 5. Read triggers from expanded groups
            type1, ch1 = _parse_channel(p["daqsystem_ch1"])
            type2, ch2 = _parse_channel(p["daqsystem_ch2"])

            if node_a_is_1:
                indices_1 = group_a
                indices_2 = group_b
                epochs_1 = epochs_a_all
                epochs_2 = epochs_b_all
            else:
                indices_1 = group_b
                indices_2 = group_a
                epochs_1 = epochs_b_all
                epochs_2 = epochs_a_all

            def _get_t0(epoch_table: list, idx: int) -> float:
                ep = epoch_table[idx]
                t0_t1 = ep.get("t0_t1") if isinstance(ep, dict) else getattr(ep, "t0_t1", None)
                if isinstance(t0_t1, list) and len(t0_t1) > 0:
                    val = t0_t1[0]
                    if isinstance(val, (list, tuple, np.ndarray)):
                        return float(val[0])
                    return float(val)
                return 0.0

            def _get_epoch_id(epoch_table: list, idx: int) -> str:
                ep = epoch_table[idx]
                if isinstance(ep, dict):
                    return ep.get("epoch_id", "")
                return getattr(ep, "epoch_id", "")

            sorted_1 = sorted(indices_1, key=lambda i: _get_t0(epochs_1, i))
            sorted_2 = sorted(indices_2, key=lambda i: _get_t0(epochs_2, i))

            # Read T1
            t1_total: list[float] = []
            for idx in sorted_1:
                eid = _get_epoch_id(epochs_1, idx)
                ts, _ = daqsystem1.readevents([type1], ch1, eid, float("-inf"), float("inf"))
                if isinstance(ts, list):
                    ts = ts[0] if ts else np.array([])
                if isinstance(ts, np.ndarray):
                    t1_total.extend(ts.flatten().tolist())
                elif ts is not None:
                    t1_total.extend(list(ts))

            # Read T2
            t2_total: list[float] = []
            for idx in sorted_2:
                eid = _get_epoch_id(epochs_2, idx)
                ts, _ = daqsystem2.readevents([type2], ch2, eid, float("-inf"), float("inf"))
                if isinstance(ts, list):
                    ts = ts[0] if ts else np.array([])
                if isinstance(ts, np.ndarray):
                    t2_total.extend(ts.flatten().tolist())
                elif ts is not None:
                    t2_total.extend(list(ts))

            # 6. Compute mapping
            t1_arr = np.sort(np.array(t1_total))
            t2_arr = np.sort(np.array(t2_total))
            shift, scale = _sync_triggers(t1_arr, t2_arr)

            if node_a_is_1:
                # T2 = scale * T1 + shift -> map A(1) to B(2)
                mapping = ndi_time_timemapping([scale, shift])
            else:
                # Want A(2)->B(1): T1 = (T2 - shift)/scale
                mapping = ndi_time_timemapping([1.0 / scale, -shift / scale])

            return 1.0, mapping

        except Exception:
            if p.get("errorOnFailure", True):
                raise
            return None, None
