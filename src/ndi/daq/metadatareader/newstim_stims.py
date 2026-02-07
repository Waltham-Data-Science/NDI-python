"""
ndi.daq.metadatareader.newstim_stims - NewStim stimulus metadata reader.

Reads stimulus parameters from NewStim visual stimulus computer outputs.
NewStim stores stimulus scripts as .mat files with a 'saveScript'
variable containing the stimulus script object.

MATLAB equivalent: src/ndi/+ndi/+daq/+metadatareader/NewStimStims.m
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..metadatareader import MetadataReader


class NewStimStimsReader(MetadataReader):
    """
    Metadata reader for NewStim stimulus systems.

    Reads stimulus parameters from NewStim .mat files containing
    stimulus script data (stimscripts with timing information).

    The reader looks for a file matching 'stims.mat' (or a custom
    pattern) in each epoch's file list, loads the stimulus script,
    and extracts parameters for each stimulus condition.

    Example:
        >>> reader = NewStimStimsReader()
        >>> params = reader.readmetadata(['data.rhd', 'stims.mat'])
    """

    STIM_FILE_PATTERN = r"stims\.mat$"

    def __init__(
        self,
        tsv_pattern: str = "",
        identifier: str | None = None,
        session: Any | None = None,
        document: Any | None = None,
    ):
        super().__init__(
            tsv_pattern=tsv_pattern,
            identifier=identifier,
            session=session,
            document=document,
        )

    def readmetadata(
        self,
        epochfiles: list[str],
    ) -> list[dict[str, Any]]:
        """
        Read stimulus metadata from NewStim files.

        Looks for a stims.mat file in the epoch file list and reads
        the stimulus script to extract parameters.

        Args:
            epochfiles: List of file paths for the epoch

        Returns:
            List of parameter dictionaries, one per stimulus

        Raises:
            ImportError: If scipy is not available for .mat reading
        """
        # First try TSV-based reading from base class
        if self._tab_separated_file_parameter:
            try:
                return super().readmetadata(epochfiles)
            except (ValueError, FileNotFoundError):
                pass

        # Look for stims.mat
        stim_file = self._find_stim_file(epochfiles)
        if stim_file is None:
            return []

        return self._read_newstim_mat(stim_file)

    def _find_stim_file(self, epochfiles: list[str]) -> str | None:
        """Find the NewStim .mat file in epoch files."""
        pattern = re.compile(self.STIM_FILE_PATTERN, re.IGNORECASE)
        for f in epochfiles:
            if pattern.search(f):
                return f
        return None

    def _read_newstim_mat(self, filepath: str) -> list[dict[str, Any]]:
        """
        Read stimulus parameters from a NewStim .mat file.

        Uses scipy.io.loadmat to read the MATLAB file and extract
        stimulus script parameters.

        Args:
            filepath: Path to stims.mat file

        Returns:
            List of parameter dicts

        Raises:
            ImportError: If scipy is not available
        """
        try:
            from scipy.io import loadmat
        except ImportError as exc:
            raise ImportError(
                "scipy is required to read NewStim .mat files. " "Install with: pip install scipy"
            ) from exc

        if not Path(filepath).is_file():
            return []

        mat_data = loadmat(filepath, squeeze_me=True, struct_as_record=True)

        # NewStim stores data in 'saveScript' variable
        if "saveScript" not in mat_data:
            return []

        return self._extract_script_parameters(mat_data["saveScript"])

    @staticmethod
    def _extract_script_parameters(script_data: Any) -> list[dict[str, Any]]:
        """
        Extract parameters from a NewStim script structure.

        Args:
            script_data: MATLAB struct array from saveScript

        Returns:
            List of parameter dicts
        """
        parameters = []

        try:
            import numpy as np

            # Handle various script_data formats
            if hasattr(script_data, "dtype") and script_data.dtype.names:
                # Structured array
                stims = script_data.get("stimscript", script_data)
                if hasattr(stims, "__len__"):
                    for i in range(len(stims)):
                        params = {}
                        stim = stims[i] if len(stims) > 1 else stims
                        if hasattr(stim, "dtype") and stim.dtype.names:
                            for name in stim.dtype.names:
                                val = stim[name]
                                if isinstance(val, np.ndarray) and val.size == 1:
                                    val = val.item()
                                params[name] = val
                        parameters.append(params)
                else:
                    parameters.append({})
            else:
                parameters.append({})
        except Exception:
            parameters.append({})

        return parameters

    def __repr__(self) -> str:
        return f"NewStimStimsReader(id='{self.id[:8]}...')"
