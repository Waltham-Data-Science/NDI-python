"""
ndi.probe - Specialized element for measurement devices.

This module provides the ndi_probe class that represents measurement
or stimulation devices in neuroscience experiments.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from ..element import ndi_element
from ..epoch.epochprobemap import ndi_epoch_epochprobemap
from ..time import ndi_time_clocktype


class ndi_probe(ndi_element):
    """
    Specialized element for measurement/stimulation devices.

    ndi_probe represents a physical or virtual device that records or
    stimulates (e.g., electrodes, optical fibers, cameras). Probes
    build their epoch tables by matching epochprobemap entries from
    DAQ systems.

    Unlike generic Elements, Probes:
    - Build epochs from device epochprobemaps (not registered epochs)
    - Return False from issyncgraphroot() to continue graph traversal
    - Match by name, reference, and type against device probe maps

    Attributes:
        Inherits all from ndi_element

    Example:
        >>> probe = ndi_probe(
        ...     session=my_session,
        ...     name='electrode1',
        ...     reference=1,
        ...     type='n-trode',
        ...     subject_id='subj_001',
        ... )
        >>> et, hash_val = probe.epochtable()
    """

    def __init__(
        self,
        session: Any | None = None,
        name: str = "",
        reference: int = 0,
        type: str = "",
        subject_id: str = "",
        identifier: str | None = None,
        document: Any | None = None,
    ):
        """
        Create a new ndi_probe.

        Args:
            session: ndi_session object with database access
            name: ndi_probe name (no whitespace allowed)
            reference: Reference number (non-negative integer)
            type: ndi_probe type identifier (no whitespace)
            subject_id: ndi_subject document ID
            identifier: Optional unique identifier
            document: Optional document to load from
        """
        # MATLAB probe constructor sets direct=True (inputs{6}=1)
        # and has no underlying_element
        super().__init__(
            session=session,
            name=name,
            reference=reference,
            type=type,
            underlying_element=None,
            direct=True,
            subject_id=subject_id,
            dependencies=None,
            identifier=identifier,
            document=document,
        )

    # =========================================================================
    # ndi_epoch_epochset Overrides
    # =========================================================================

    def buildepochtable(self) -> list[dict[str, Any]]:
        """
        Build epoch table from DAQ system epochprobemaps.

        Scans all DAQ systems in the session and collects epochs
        where the epochprobemap matches this probe's name, reference,
        and type.

        Returns:
            List of epoch table entries
        """
        if self._session is None:
            return []

        # Get all DAQ systems from session
        daqsystems = self._get_daqsystems()

        et = []
        epoch_number = 0

        for daqsys in daqsystems:
            # Get device epoch table
            device_et = daqsys.epochtable()
            daqsys_name = getattr(daqsys, "name", getattr(daqsys, "_name", ""))

            for device_entry in device_et:
                # Check if any epochprobemap matches this probe
                epochprobemaps = device_entry.get("epochprobemap", [])
                matching_epm = self._find_matching_epochprobemap(epochprobemaps)

                if matching_epm is not None:
                    # Only include if the matching epochprobemap's device
                    # belongs to this DAQ system
                    epm_devicename = ""
                    if hasattr(matching_epm, "devicename"):
                        epm_devicename = matching_epm.devicename
                    elif hasattr(matching_epm, "devicestring"):
                        parts = matching_epm.devicestring.split(":")
                        epm_devicename = parts[0] if parts else ""

                    if epm_devicename.lower() != daqsys_name.lower():
                        continue

                    epoch_number += 1

                    # Get clock and timing info from device entry
                    epoch_clock = device_entry.get("epoch_clock", [])
                    t0_t1 = device_entry.get("t0_t1", [])

                    et.append(
                        {
                            "epoch_number": epoch_number,
                            "epoch_id": device_entry.get("epoch_id", ""),
                            "epoch_session_id": device_entry.get("epoch_session_id", ""),
                            "epochprobemap": [matching_epm],
                            "epoch_clock": epoch_clock,
                            "t0_t1": t0_t1,
                            "underlying_epochs": {
                                "underlying": daqsys,
                                "epoch_id": device_entry.get("epoch_id", ""),
                                "epoch_session_id": device_entry.get("epoch_session_id", ""),
                                "epochprobemap": epochprobemaps,
                                "epoch_clock": epoch_clock,
                                "t0_t1": t0_t1,
                            },
                        }
                    )

        return et

    def _get_daqsystems(self) -> list[Any]:
        """Get all DAQ systems from the session."""
        if self._session is None:
            return []

        # Check if session has a method to get DAQ systems
        if hasattr(self._session, "getdaqsystems"):
            return self._session.getdaqsystems()

        if hasattr(self._session, "daqsystems"):
            return self._session.daqsystems

        # Fall back to querying database
        from ..query import ndi_query

        q = ndi_query("").isa("daqsystem")
        docs = self._session.database_search(q)

        # Load ndi_daq_system objects from documents
        from ..daq.system import ndi_daq_system

        systems = []
        for doc in docs:
            try:
                sys = ndi_daq_system(session=self._session, document=doc)
                systems.append(sys)
            except Exception:
                pass

        return systems

    def _find_matching_epochprobemap(
        self,
        epochprobemaps: list[Any],
    ) -> ndi_epoch_epochprobemap | None:
        """
        Find an epochprobemap matching this probe.

        Args:
            epochprobemaps: List of probe maps to search

        Returns:
            Matching ndi_epoch_epochprobemap or None
        """
        for epm in epochprobemaps:
            # Handle both ndi_epoch_epochprobemap objects and dicts
            if isinstance(epm, ndi_epoch_epochprobemap):
                if epm.matches(self._name, self._reference, self._type):
                    return epm
            elif isinstance(epm, dict):
                if (
                    epm.get("name") == self._name
                    and epm.get("reference") == self._reference
                    and epm.get("type") == self._type
                ):
                    return ndi_epoch_epochprobemap.from_dict(epm)
            elif hasattr(epm, "name") and hasattr(epm, "reference") and hasattr(epm, "type"):
                if (
                    epm.name == self._name
                    and epm.reference == self._reference
                    and epm.type == self._type
                ):
                    return ndi_epoch_epochprobemap(
                        name=epm.name,
                        reference=epm.reference,
                        type=epm.type,
                        devicestring=getattr(epm, "devicestring", ""),
                        subjectstring=getattr(epm, "subjectstring", ""),
                    )

        return None

    def epochsetname(self) -> str:
        """Return the name of this epoch set."""
        return f"probe: {self._name} | {self._reference}"

    def issyncgraphroot(self) -> bool:
        """
        Check if this probe is a sync graph root.

        Probes return False to continue graph traversal to
        underlying DAQ systems.

        Returns:
            False (continue traversal)
        """
        return False

    # =========================================================================
    # ndi_probe-specific Methods
    # =========================================================================

    def probestring(self) -> str:
        """
        Format probe as human-readable string.

        MATLAB equivalent: ndi.probe.probestring

        Returns:
            String in format "name | reference | type"
        """
        return f"{self._name} | {self._reference} | {self._type}"

    def epochprobemapmatch(
        self,
        epochprobemap: Any,
    ) -> bool:
        """
        Check if an epochprobemap matches this probe.

        Args:
            epochprobemap: ndi_epoch_epochprobemap to check

        Returns:
            True if matches this probe's name, reference, type
        """
        if isinstance(epochprobemap, ndi_epoch_epochprobemap):
            return epochprobemap.matches(self._name, self._reference, self._type)
        elif isinstance(epochprobemap, dict):
            return (
                epochprobemap.get("name") == self._name
                and epochprobemap.get("reference") == self._reference
                and epochprobemap.get("type") == self._type
            )
        elif hasattr(epochprobemap, "name"):
            return (
                epochprobemap.name == self._name
                and epochprobemap.reference == self._reference
                and epochprobemap.type == self._type
            )
        return False

    def getchanneldevinfo(
        self,
        epoch_number: int,
    ) -> dict[str, Any]:
        """
        Get device and channel information for an epoch.

        Args:
            epoch_number: ndi_epoch_epoch number (1-indexed)

        Returns:
            Dict with:
            - daqsystem: The DAQ system object
            - device_epochnumber: ndi_epoch_epoch number in device
            - channels: Channel mappings
        """
        et, _ = self.epochtable()

        if epoch_number < 1 or epoch_number > len(et):
            raise IndexError(f"ndi_epoch_epoch {epoch_number} out of range (1..{len(et)})")

        entry = et[epoch_number - 1]
        underlying = entry.get("underlying_epochs", {})

        return {
            "daqsystem": underlying.get("underlying"),
            "device_epoch_id": underlying.get("epoch_id"),
            "epochprobemap": entry.get("epochprobemap", []),
        }

    # =========================================================================
    # ndi_element overrides
    # =========================================================================

    def ndi_element_class(self) -> str:
        """Return the NDI element class name for document storage.

        MATLAB equivalent: ``class(ndi_probe_obj)``

        Returns ``'ndi.probe'``.  Subclasses (e.g.
        ``ndi_probe_timeseries_mfdaq``) override this to return their own
        MATLAB class name.

        Returns:
            MATLAB class name string.
        """
        return "ndi.probe"

    # =========================================================================
    # Static Methods
    # =========================================================================

    @staticmethod
    def buildmultipleepochtables(
        probes: list[ndi_probe],
        session: Any,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Build epoch tables for multiple probes efficiently.

        Loads DAQ systems once and builds all probe epoch tables,
        avoiding redundant database queries.

        Args:
            probes: List of ndi_probe objects
            session: ndi_session object

        Returns:
            Dict mapping probe.id to epoch table
        """
        # Get DAQ systems once
        if hasattr(session, "getdaqsystems"):
            daqsystems = session.getdaqsystems()
        elif hasattr(session, "daqsystems"):
            daqsystems = session.daqsystems
        else:
            from ..query import ndi_query

            q = ndi_query("").isa("daqsystem")
            docs = session.database_search(q)
            from ..daq.system import ndi_daq_system

            daqsystems = []
            for doc in docs:
                try:
                    sys = ndi_daq_system(session=session, document=doc)
                    daqsystems.append(sys)
                except Exception:
                    pass

        # Build device epoch tables once
        device_tables = {}
        for daqsys in daqsystems:
            device_tables[id(daqsys)] = {
                "system": daqsys,
                "epochtable": daqsys.epochtable(),
            }

        # Build epoch tables for each probe
        result = {}
        for probe in probes:
            et = []
            epoch_number = 0

            for _daqsys_id, device_info in device_tables.items():
                daqsys = device_info["system"]
                device_et = device_info["epochtable"]
                daqsys_name = getattr(daqsys, "name", getattr(daqsys, "_name", ""))

                for device_entry in device_et:
                    epochprobemaps = device_entry.get("epochprobemap", [])
                    matching_epm = probe._find_matching_epochprobemap(epochprobemaps)

                    if matching_epm is not None:
                        # Only include if the matching epochprobemap's device
                        # belongs to this DAQ system
                        epm_devicename = ""
                        if hasattr(matching_epm, "devicename"):
                            epm_devicename = matching_epm.devicename
                        elif hasattr(matching_epm, "devicestring"):
                            parts = matching_epm.devicestring.split(":")
                            epm_devicename = parts[0] if parts else ""

                        if epm_devicename.lower() != daqsys_name.lower():
                            continue

                        epoch_number += 1
                        et.append(
                            {
                                "epoch_number": epoch_number,
                                "epoch_id": device_entry.get("epoch_id", ""),
                                "epoch_session_id": device_entry.get("epoch_session_id", ""),
                                "epochprobemap": [matching_epm],
                                "epoch_clock": device_entry.get("epoch_clock", []),
                                "t0_t1": device_entry.get("t0_t1", []),
                                "underlying_epochs": {
                                    "underlying": daqsys,
                                    "epoch_id": device_entry.get("epoch_id", ""),
                                    "epoch_session_id": device_entry.get("epoch_session_id", ""),
                                    "epochprobemap": epochprobemaps,
                                    "epoch_clock": device_entry.get("epoch_clock", []),
                                    "t0_t1": device_entry.get("t0_t1", []),
                                },
                            }
                        )

            result[probe.id] = et

        return result

    def __repr__(self) -> str:
        """String representation."""
        return f"ndi_probe({self._name}|{self._reference}|{self._type})"


# =========================================================================
# ndi_probe Type Map utilities
# =========================================================================

_PROBE_TYPE_MAP: dict[str, str] | None = None


def initProbeTypeMap() -> dict[str, str]:
    """Load the probe type→class mapping from ``probetype2object.json``.

    MATLAB equivalent: ndi.probe.fun.initProbeTypeMap

    Reads the JSON file that maps probe type strings (e.g. ``'n-trode'``)
    to class names (e.g. ``'ndi.probe.timeseries.mfdaq'``).

    Returns:
        Dict mapping type strings to class name strings.
    """
    import json

    try:
        from ..common import ndi_common_PathConstants

        json_path = ndi_common_PathConstants.COMMON_FOLDER / "probe" / "probetype2object.json"
    except Exception:
        return {}

    if not json_path.exists():
        return {}

    with open(json_path) as f:
        entries = json.load(f)

    result: dict[str, str] = {}
    for entry in entries:
        if isinstance(entry, dict) and "type" in entry and "classname" in entry:
            result[entry["type"]] = entry["classname"]

    return result


def getProbeTypeMap() -> dict[str, str]:
    """Return the cached probe type→class mapping.

    MATLAB equivalent: ndi.probe.fun.getProbeTypeMap

    Loads the mapping on first call, then returns the cached version.

    Returns:
        Dict mapping probe type strings to class name strings.
    """
    global _PROBE_TYPE_MAP
    if _PROBE_TYPE_MAP is None:
        _PROBE_TYPE_MAP = initProbeTypeMap()
    return _PROBE_TYPE_MAP
