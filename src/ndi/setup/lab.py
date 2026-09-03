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


def lab(session, lab_name: str, force_update: bool = False) -> None:
    """Add DAQ system documents to a session based on lab JSON configs.

    For each JSON config in ``ndi_common/daq_systems/<lab_name>/``, creates:

    - A ``daq/filenavigator`` document
    - A ``daq/daqreader`` document
    - Optionally a ``daq/daqmetadatareader`` document
    - A ``daq/daqsystem`` document linking them together

    Also installs the default ``ndi.time.syncrule.filematch`` rule (with
    ``number_fullpath_matches = 2``, mirroring MATLAB ``+setup/lab.m``) into
    the session's syncgraph, followed by any lab-specific sync rules defined
    under ``ndi_common/sync_rules/<lab_name>/``.

    Parameters
    ----------
    session : ndi.session.session_base
        The NDI session to add DAQ systems to.
    lab_name : str
        Name of the lab directory under ``ndi_common/daq_systems/``
        (e.g. ``"vhlab"``, ``"marderlab"``, ``"kjnielsenlab"``).
    force_update : bool
        Passed through to ``ndi.setup.sync.add_sync_rules``.
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
        custom_nav_class = config.get("FileNavigatorClass", "")
        if custom_nav_class:
            filenavigator_class = custom_nav_class
        elif has_epoch_dirs:
            filenavigator_class = "ndi.file.navigator.epochdir"
        else:
            filenavigator_class = "ndi.file.navigator"

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

        # Create daqreader document. NDR-family readers (the base
        # ndi.daq.reader.mfdaq.ndr and any subclass thereof, e.g.
        # ndi.setup.daq.reader.mfdaq.stimulus.rayolab_intanseries) need
        # the daqreader_ndr doc shape with ndr_reader_string so MATLAB
        # can reconstruct them; the matlab base ndr constructor reads
        # document_properties.daqreader_ndr.ndr_reader_string and errors
        # out on the generic daqreader shape.
        #
        # Signal: an NDR-family entry in the lab JSON sets
        # DaqReaderFileParameters (the ndr "reader string" -- typically
        # the format tag like "intan"). Use that as the trigger so we
        # catch subclasses without hard-coding their class names.
        reader_file_params = config.get("DaqReaderFileParameters", "")
        if isinstance(reader_file_params, list):
            reader_file_params = reader_file_params[0] if reader_file_params else ""

        is_ndr_family = reader_class == "ndi.daq.reader.mfdaq.ndr" or bool(reader_file_params)

        if is_ndr_family:
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

        # Create daqmetadatareader documents if configured. Mirrors MATLAB
        # +setup/@DaqSystemConfiguration/createMetadataReader: one reader per
        # MetadataReaderFileParameters entry (a single class is shared across
        # every entry; N classes must pair 1:1 with N file parameters), and
        # the file parameter is written into the document as
        # ``daqmetadatareader.tab_separated_file_parameter`` so the
        # downstream metadata reader can find its file(s) in the epoch.
        if metadata_reader_class and metadata_reader_class != []:
            mr_class_list = (
                [metadata_reader_class]
                if isinstance(metadata_reader_class, str)
                else list(metadata_reader_class)
            )

            mr_file_params_raw = config.get("MetadataReaderFileParameters", "")
            if isinstance(mr_file_params_raw, str):
                mr_file_params_list = [mr_file_params_raw] if mr_file_params_raw else []
            else:
                mr_file_params_list = list(mr_file_params_raw)

            if not mr_file_params_list:
                if len(mr_class_list) > 1:
                    raise ValueError(
                        f"{name}: {len(mr_class_list)} MetadataReaderClass entries "
                        "but no MetadataReaderFileParameters — cannot pair them."
                    )
                pairs = [(mr_class_list[0], "")]
            elif len(mr_class_list) == 1:
                pairs = [(mr_class_list[0], fp) for fp in mr_file_params_list]
            elif len(mr_class_list) == len(mr_file_params_list):
                pairs = list(zip(mr_class_list, mr_file_params_list))
            else:
                raise ValueError(
                    f"{name}: {len(mr_class_list)} MetadataReaderClass entries do not "
                    f"match {len(mr_file_params_list)} MetadataReaderFileParameters entries; "
                    "provide one class (shared across every file parameter) or one class "
                    "per file parameter."
                )

            for mr_class, mr_fp in pairs:
                mr_doc = session.newdocument(
                    "daq/daqmetadatareader",
                    **{
                        "base.name": name,
                        "daqmetadatareader.ndi_daqmetadatareader_class": mr_class,
                        "daqmetadatareader.tab_separated_file_parameter": mr_fp,
                    },
                )
                session.database_add(mr_doc)
                daq_doc = daq_doc.add_dependency_value_n("daqmetadatareader_id", mr_doc.id)

        session.database_add(daq_doc)

    # MATLAB +setup/lab.m installs a default filematch(2) syncrule and then
    # any lab-specific rules from ndi_common/sync_rules/<lab_name>. Do the
    # same here so Python labs come up with the same syncgraph as MATLAB.
    from ..time.syncrule import ndi_time_syncrule_filematch
    from .sync import add_sync_rules

    session.syncgraph_addrule(ndi_time_syncrule_filematch({"number_fullpath_matches": 2}))
    add_sync_rules(session, lab_name, force_update=force_update)
