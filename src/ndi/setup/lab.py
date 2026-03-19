"""Set up a session with DAQ systems from lab configuration files.

Reads DAQ system configuration JSON files from
``ndi_common/daq_systems/<lab_name>/`` and creates the corresponding
filenavigator, daqreader, (optionally daqmetadatareader), and daqsystem
documents in the given session.

This is the Python equivalent of MATLAB's ``ndi.setup.lab()``.

Example::

    import ndi
    session = ndi.ndi_session_dir("exp1", "/path/to/experiment")
    ndi.setup.lab(session, "vhlab")
"""

from __future__ import annotations

import json
from pathlib import Path


def _to_matlab_cell_str(items: list[str]) -> str:
    """Convert a list of strings to MATLAB cell-array syntax.

    Example: ``['#.rhd']`` becomes ``"{ '#.rhd' }"``.
    """
    if not items:
        return ""
    quoted = ", ".join(f"'{s}'" for s in items)
    return f"{{ {quoted} }}"


def _find_daq_configs(lab_name: str) -> list[dict]:
    """Read all DAQ system JSON configs for a given lab."""
    import ndi.ndi_common

    common_dir = Path(ndi.ndi_common.__path__[0])
    lab_dir = common_dir / "daq_systems" / lab_name

    if not lab_dir.exists():
        raise FileNotFoundError(f"No DAQ system configs found for lab: {lab_name}")

    configs = []
    for json_file in sorted(lab_dir.glob("*.json")):
        with open(json_file, encoding="utf-8") as f:
            configs.append(json.load(f))
    return configs


def lab(session, lab_name: str) -> None:
    """Add DAQ system documents to a session based on lab JSON configs.

    For each JSON config in ``ndi_common/daq_systems/<lab_name>/``, creates:

    - A ``daq/filenavigator`` document
    - A ``daq/daqreader`` document
    - Optionally a ``daq/daqmetadatareader`` document
    - A ``daq/daqsystem`` document linking them together

    Parameters
    ----------
    session : ndi.session.session_base
        The NDI session to add DAQ systems to.
    lab_name : str
        Name of the lab directory under ``ndi_common/daq_systems/``
        (e.g. ``"vhlab"``, ``"marderlab"``, ``"kjnielsenlab"``).
    """
    configs = _find_daq_configs(lab_name)

    for config in configs:
        name = config["Name"]
        file_params = config.get("FileParameters", [])
        epm_class = config.get("EpochProbeMapClass", "ndi.epoch.epochprobemap_daqsystem")
        epm_file_params = config.get("EpochProbeMapFileParameters", "")
        reader_class = config.get("DaqReaderClass", "ndi.daq.reader.mfdaq")
        system_class = config.get("DaqSystemClass", "ndi.daq.system.mfdaq")
        metadata_reader_class = config.get("MetadataReaderClass", [])
        has_epoch_dirs = config.get("HasEpochDirectories", False)

        # Choose the correct filenavigator class
        filenavigator_class = (
            "ndi.file.navigator.epochdir" if has_epoch_dirs else "ndi.file.navigator"
        )

        # Convert file parameters to MATLAB cell string format
        fp_str = _to_matlab_cell_str(file_params)

        # EpochProbeMapFileParameters may be a string or list
        if isinstance(epm_file_params, list):
            epm_fp_str = _to_matlab_cell_str(epm_file_params)
        else:
            epm_fp_str = f"{{ '{epm_file_params}' }}" if epm_file_params else ""

        # Create filenavigator document
        fn_doc = session.newdocument(
            "daq/filenavigator",
            **{
                "base.name": name,
                "filenavigator.ndi_filenavigator_class": filenavigator_class,
                "filenavigator.fileparameters": fp_str,
                "filenavigator.epochprobemap_class": epm_class,
                "filenavigator.epochprobemap_fileparameters": epm_fp_str,
            },
        )
        session.database_add(fn_doc)

        # Create daqreader document — use the specialised document type
        # for readers that require extra properties (e.g. ndr needs
        # daqreader_ndr.ndr_reader_string so MATLAB can reconstruct it).
        reader_file_params = config.get("DaqReaderFileParameters", "")
        if isinstance(reader_file_params, list):
            reader_file_params = reader_file_params[0] if reader_file_params else ""

        if reader_class == "ndi.daq.reader.mfdaq.ndr":
            dr_doc = session.newdocument(
                "daq/daqreader_ndr",
                **{
                    "base.name": name,
                    "daqreader.ndi_daqreader_class": reader_class,
                    "daqreader_ndr.ndr_reader_string": reader_file_params,
                    "daqreader_ndr.ndi_daqreader_ndr_class": reader_class,
                },
            )
        else:
            dr_doc = session.newdocument(
                "daq/daqreader",
                **{
                    "base.name": name,
                    "daqreader.ndi_daqreader_class": reader_class,
                },
            )
        session.database_add(dr_doc)

        # Create daqsystem document
        daq_doc = session.newdocument(
            "daq/daqsystem",
            **{
                "base.name": name,
                "daqsystem.ndi_daqsystem_class": system_class,
            },
        )
        daq_doc = daq_doc.set_dependency_value(
            "filenavigator_id", fn_doc.id, error_if_not_found=False
        )
        daq_doc = daq_doc.set_dependency_value("daqreader_id", dr_doc.id, error_if_not_found=False)

        # Create daqmetadatareader document if configured
        if metadata_reader_class and metadata_reader_class != []:
            mr_class = (
                metadata_reader_class
                if isinstance(metadata_reader_class, str)
                else metadata_reader_class[0]
            )
            mr_doc = session.newdocument(
                "daq/daqmetadatareader",
                **{
                    "base.name": name,
                    "daqmetadatareader.ndi_daqmetadatareader_class": mr_class,
                },
            )
            session.database_add(mr_doc)
            daq_doc = daq_doc.add_dependency_value_n("daqmetadatareader_id", mr_doc.id)

        session.database_add(daq_doc)
