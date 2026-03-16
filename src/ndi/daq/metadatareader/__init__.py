"""
ndi.daq.metadatareader - Metadata reader for experiment metadata.

This module provides the ndi_daq_metadatareader class for reading stimulus
and experiment metadata from data files, plus format-specific
subclasses for different stimulus systems.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from ...ido import ndi_ido


class ndi_daq_metadatareader(ndi_ido):
    """
    Reader for experiment metadata such as stimulus parameters.

    ndi_daq_metadatareader reads metadata from files associated with epochs,
    typically containing stimulus parameters or experimental conditions.

    The base class supports tab-separated value (TSV) files with
    the format:
        STIMID<tab>PARAM1<tab>PARAM2...
        1<tab>value1<tab>value2...
        2<tab>value1<tab>value2...

    Attributes:
        tab_separated_file_parameter: Regex pattern to find TSV files

    Example:
        >>> reader = ndi_daq_metadatareader(r'.*stim.*\\.txt')
        >>> metadata = reader.readmetadata(['epoch1.txt', 'stim_params.txt'])
    """

    def __init__(
        self,
        tsv_pattern: str = "",
        identifier: str | None = None,
        session: Any | None = None,
        document: Any | None = None,
    ):
        """
        Create a new ndi_daq_metadatareader.

        Args:
            tsv_pattern: Regular expression to find TSV parameter files
            identifier: Optional unique identifier
            session: Optional session object
            document: Optional document to load from
        """
        super().__init__(identifier)
        self._session = session
        self._tab_separated_file_parameter = tsv_pattern

        # Load from document if provided
        if document is not None:
            doc_props = getattr(document, "document_properties", document)
            if hasattr(doc_props, "base") and hasattr(doc_props.base, "id"):
                self.identifier = doc_props.base.id
            if hasattr(doc_props, "daqmetadatareader"):
                self._tab_separated_file_parameter = getattr(
                    doc_props.daqmetadatareader, "tab_separated_file_parameter", ""
                )

    @property
    def tab_separated_file_parameter(self) -> str:
        """Get the TSV file pattern."""
        return self._tab_separated_file_parameter

    def readmetadata(
        self,
        epochfiles: list[str],
    ) -> list[dict[str, Any]]:
        """
        Read metadata parameters from epoch files.

        Args:
            epochfiles: List of file paths for the epoch

        Returns:
            List of parameter dictionaries, one per stimulus

        Raises:
            ValueError: If multiple files match or no files match

        Example:
            >>> reader = ndi_daq_metadatareader(r'stim.*\\.tsv')
            >>> params = reader.readmetadata(['data.bin', 'stim_params.tsv'])
            >>> print(params[0])  # First stimulus parameters
        """
        if not self._tab_separated_file_parameter:
            return []

        # Find matching files
        pattern = re.compile(self._tab_separated_file_parameter, re.IGNORECASE)
        matches = []
        for f in epochfiles:
            if pattern.search(f):
                matches.append(f)

        if len(matches) > 1:
            raise ValueError(
                f"Multiple files match pattern '{self._tab_separated_file_parameter}': "
                f"{matches}"
            )
        if len(matches) == 0:
            raise ValueError(
                f"No files match pattern '{self._tab_separated_file_parameter}' " f"in {epochfiles}"
            )

        filepath = matches[0]
        if not Path(filepath).is_file():
            raise FileNotFoundError(f"No such file: {filepath}")

        return self.readmetadatafromfile(filepath)

    def readmetadatafromfile(
        self,
        filepath: str,
    ) -> list[dict[str, Any]]:
        """
        Read metadata from a specific file.

        Args:
            filepath: Path to the metadata file

        Returns:
            List of parameter dictionaries
        """
        parameters = []

        with open(filepath, newline="") as f:
            # Try to detect delimiter (tab or comma)
            sample = f.read(1024)
            f.seek(0)

            if "\t" in sample:
                delimiter = "\t"
            elif "," in sample:
                delimiter = ","
            else:
                delimiter = "\t"

            reader = csv.DictReader(f, delimiter=delimiter)
            for row in reader:
                # Convert numeric strings to numbers
                params = {}
                for key, value in row.items():
                    if key is None:
                        continue
                    try:
                        # Try integer first
                        params[key] = int(value)
                    except ValueError:
                        try:
                            # Try float
                            params[key] = float(value)
                        except ValueError:
                            # Keep as string
                            params[key] = value
                parameters.append(params)

        return parameters

    def readmetadata_ingested(
        self,
        epochfiles: list[str],
        session: Any,
    ) -> list[dict[str, Any]]:
        """
        Read metadata from an ingested epoch.

        Args:
            epochfiles: List of file paths (starting with epochid://)
            session: ndi_session object with database access

        Returns:
            List of parameter dictionaries
        """
        doc = self.get_ingested_document(epochfiles, session)
        if doc is None:
            return []

        # Extract metadata from document
        # This would typically involve reading compressed data
        # For now, return empty list
        return []

    def get_ingested_document(
        self,
        epochfiles: list[str],
        session: Any,
    ) -> Any | None:
        """
        Get the ingested document for epochfiles.

        Args:
            epochfiles: List of file paths
            session: ndi_session object

        Returns:
            ndi_document object or None
        """
        from ...query import ndi_query

        # Check if ingested
        if not epochfiles or not epochfiles[0].startswith("epochid://"):
            return None

        epochid = epochfiles[0][len("epochid://") :]

        q = ndi_query("").depends_on("daqmetadatareader_id", self.id) & (
            ndi_query("epochid.epochid") == epochid
        )
        results = session.database_search(q)

        if len(results) == 1:
            return results[0]
        return None

    def ingest_epochfiles(
        self,
        epochfiles: list[str],
        epoch_id: str,
    ) -> Any:
        """
        Create a document for ingested epoch metadata.

        Args:
            epochfiles: List of file paths
            epoch_id: ndi_epoch_epoch identifier

        Returns:
            ndi_document object
        """
        from ...document import ndi_document

        epochid_struct = {"epochid": epoch_id}

        doc = ndi_document(
            "ingestion/daqmetadatareader_epochdata_ingested",
            epochid=epochid_struct,
        )
        doc.set_dependency_value("daqmetadatareader_id", self.id)

        # Read and store metadata
        try:
            self.readmetadata(epochfiles)
            # In a full implementation, we would compress and store
            # the parameters as binary data
        except (ValueError, FileNotFoundError):
            pass

        return doc

    def newdocument(self) -> Any:
        """
        Create a new document for this ndi_daq_metadatareader.

        Returns:
            ndi_document object
        """
        from ...document import ndi_document

        doc = ndi_document(
            "daq/daqmetadatareader",
            **{
                "daqmetadatareader.ndi_daqmetadatareader_class": self.__class__.__name__,
                "daqmetadatareader.tab_separated_file_parameter": self._tab_separated_file_parameter,
                "base.id": self.id,
            },
        )
        return doc

    def searchquery(self) -> Any:
        """
        Create a search query for this ndi_daq_metadatareader.

        Returns:
            ndi_query object
        """
        from ...query import ndi_query

        return ndi_query("base.id") == self.id

    def __eq__(self, other: Any) -> bool:
        """Test equality by class and properties."""
        if not isinstance(other, ndi_daq_metadatareader):
            return False
        return (
            self.__class__.__name__ == other.__class__.__name__
            and self._tab_separated_file_parameter == other._tab_separated_file_parameter
        )

    def __hash__(self) -> int:
        """Hash by ID."""
        return hash(self.id)


# Import subclass readers
from .newstim_stims import ndi_daq_metadatareader_NewStimStims
from .nielsenlab_stims import ndi_daq_metadatareader_NielsenLabStims

__all__ = ["ndi_daq_metadatareader", "ndi_daq_metadatareader_NewStimStims", "ndi_daq_metadatareader_NielsenLabStims"]
