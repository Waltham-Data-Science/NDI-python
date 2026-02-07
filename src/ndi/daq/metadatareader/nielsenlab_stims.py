"""
ndi.daq.metadatareader.nielsenlab_stims - Nielsen Lab stimulus metadata reader.

Reads stimulus parameters from Nielsen Lab .mat files containing
an 'Analyzer' structure with stimulus conditions and trial ordering.

MATLAB equivalent: src/ndi/+ndi/+daq/+metadatareader/NielsenLabStims.m
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..metadatareader import MetadataReader


class NielsenLabStimsReader(MetadataReader):
    """
    Metadata reader for Nielsen Lab stimulus systems.

    Reads stimulus parameters from .mat files containing an 'Analyzer'
    structure. The Analyzer has:
    - M: Global parameters
    - P.param: Cell array of parameter definitions
    - loops.conds: Condition-specific parameter values

    Example:
        >>> reader = NielsenLabStimsReader()
        >>> params = reader.readmetadata(['data.rhd', 'analyzer.mat'])
    """

    ANALYZER_FILE_PATTERN = r"analyzer\.mat$"

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
        Read stimulus metadata from Nielsen Lab files.

        Args:
            epochfiles: List of file paths for the epoch

        Returns:
            List of parameter dictionaries, one per condition
        """
        # First try TSV-based reading from base class
        if self._tab_separated_file_parameter:
            try:
                return super().readmetadata(epochfiles)
            except (ValueError, FileNotFoundError):
                pass

        # Look for analyzer.mat
        analyzer_file = self._find_analyzer_file(epochfiles)
        if analyzer_file is None:
            return []

        return self._read_analyzer_mat(analyzer_file)

    def _find_analyzer_file(self, epochfiles: list[str]) -> str | None:
        """Find the analyzer .mat file in epoch files."""
        pattern = re.compile(self.ANALYZER_FILE_PATTERN, re.IGNORECASE)
        for f in epochfiles:
            if pattern.search(f):
                return f
        return None

    def _read_analyzer_mat(self, filepath: str) -> list[dict[str, Any]]:
        """
        Read stimulus parameters from a Nielsen Lab analyzer .mat file.

        Args:
            filepath: Path to analyzer.mat file

        Returns:
            List of parameter dicts
        """
        try:
            from scipy.io import loadmat
        except ImportError as exc:
            raise ImportError(
                "scipy is required to read Nielsen Lab .mat files. "
                "Install with: pip install scipy"
            ) from exc

        if not Path(filepath).is_file():
            return []

        mat_data = loadmat(filepath, squeeze_me=True, struct_as_record=True)

        if "Analyzer" not in mat_data:
            return []

        return self.extract_stimulus_parameters(mat_data["Analyzer"])

    @staticmethod
    def extract_stimulus_parameters(
        analyzer: Any,
    ) -> list[dict[str, Any]]:
        """
        Extract stimulus parameters from an Analyzer structure.

        Consolidates parameters from global (M), parameter-list (P),
        and condition-specific (loops.conds) fields into per-condition
        parameter dicts.

        Args:
            analyzer: MATLAB Analyzer struct (numpy structured array)

        Returns:
            List of parameter dicts, one per condition
        """
        import numpy as np

        parameters = []

        try:
            # Extract global parameters from M field
            global_params = {}
            m_field = analyzer["M"] if "M" in analyzer.dtype.names else None
            if m_field is not None:
                if hasattr(m_field, "dtype") and m_field.dtype.names:
                    for name in m_field.dtype.names:
                        val = m_field[name]
                        if isinstance(val, np.ndarray) and val.size == 1:
                            val = val.item()
                        global_params[name] = val

            # Extract base parameters from P.param
            base_params = {}
            if "P" in analyzer.dtype.names:
                p_field = analyzer["P"]
                if hasattr(p_field, "dtype") and "param" in p_field.dtype.names:
                    param_array = p_field["param"]
                    if hasattr(param_array, "__len__"):
                        for item in param_array:
                            if hasattr(item, "__len__") and len(item) >= 3:
                                name = str(item[0])
                                value = item[2]
                                if isinstance(value, np.ndarray) and value.size == 1:
                                    value = value.item()
                                base_params[name] = value

            # Extract condition-specific parameters from loops.conds
            if "loops" in analyzer.dtype.names:
                loops = analyzer["loops"]
                if hasattr(loops, "dtype") and "conds" in loops.dtype.names:
                    conds = loops["conds"]
                    if hasattr(conds, "__len__"):
                        num_conds = len(conds)
                    else:
                        num_conds = 1
                        conds = [conds]

                    for i in range(num_conds):
                        cond = conds[i]
                        cond_params = dict(global_params)
                        cond_params.update(base_params)

                        # Add condition-specific values
                        if hasattr(cond, "dtype") and cond.dtype.names:
                            symbols = cond.get("symbol", []) if "symbol" in cond.dtype.names else []
                            vals = cond.get("val", []) if "val" in cond.dtype.names else []
                            if hasattr(symbols, "__len__") and hasattr(vals, "__len__"):
                                for s, v in zip(symbols, vals):
                                    name = str(s)
                                    if isinstance(v, np.ndarray) and v.size == 1:
                                        v = v.item()
                                    cond_params[name] = v

                        parameters.append(cond_params)
                else:
                    # No conditions - just use global + base params
                    merged = dict(global_params)
                    merged.update(base_params)
                    parameters.append(merged)
            else:
                # No loops - just use global + base params
                merged = dict(global_params)
                merged.update(base_params)
                parameters.append(merged)

        except Exception:
            # If extraction fails, return empty list
            pass

        return parameters

    @staticmethod
    def extract_display_order(analyzer: Any) -> list[int]:
        """
        Extract display order (trial-to-condition mapping) from Analyzer.

        Args:
            analyzer: MATLAB Analyzer struct

        Returns:
            List mapping trial number to condition index (0-based)
        """
        import numpy as np

        display_order = []
        try:
            if "loops" in analyzer.dtype.names:
                loops = analyzer["loops"]
                if hasattr(loops, "dtype") and "conds" in loops.dtype.names:
                    conds = loops["conds"]
                    if hasattr(conds, "__len__"):
                        for cond_idx, cond in enumerate(conds):
                            if hasattr(cond, "dtype") and "repeats" in cond.dtype.names:
                                repeats = cond["repeats"]
                                if hasattr(repeats, "__len__"):
                                    for rep in repeats:
                                        if hasattr(rep, "dtype") and "trialno" in rep.dtype.names:
                                            trialno = rep["trialno"]
                                            if isinstance(trialno, np.ndarray):
                                                trialno = trialno.item()
                                            display_order.append((int(trialno), cond_idx))

            # Sort by trial number and return condition indices
            display_order.sort(key=lambda x: x[0])
            return [cond_idx for _, cond_idx in display_order]
        except Exception:
            return []

    def __repr__(self) -> str:
        return f"NielsenLabStimsReader(id='{self.id[:8]}...')"
