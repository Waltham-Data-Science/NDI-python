"""Set up a session with DAQ systems from lab configuration files.

Reads DAQ system configuration JSON files from
``ndi_common/daq_systems/<lab_name>/`` and creates the corresponding
filenavigator, daqreader, (optionally daqmetadatareader), and daqsystem
documents in the given session, then installs the lab's synchronization
rules from ``ndi_common/sync_rules/<lab_name>/``.

This is the Python equivalent of MATLAB's ``ndi.setup.lab()``
(``src/ndi/+ndi/+setup/lab.m``), whose body is::

    S = ndi.session.dir(ref, dirname);
    S = ndi.setup.daq.addDaqSystems(S, labName, options.forceUpdate);
    nsf = ndi.time.syncrule.filematch(struct('number_fullpath_matches',2));
    S.syncgraph_addrule(nsf);
    S = ndi.setup.sync.addSyncRules(S, labName);

Signature note: MATLAB's is ``lab(labName, ref, dirname, options)`` and
*creates* the session; Python's takes an already-constructed session,
``lab(session, lab_name)``.  That split predates this module and unifying
the two signatures is a separate design decision (see the catchup plan, M4).
Only the ``forceUpdate`` semantics are ported here, as ``force_update``.

Example::

    import ndi
    session = ndi.session.dir("exp1", "/path/to/experiment")
    ndi.setup.lab(session, "vhlab")
    ndi.setup.lab(session, "vhlab", force_update=True)  # re-install DAQ systems
"""

from __future__ import annotations

import json
from pathlib import Path

from ..query import ndi_query
from ..time.syncrule import ndi_time_syncrule_filematch
from .sync import add_sync_rules


def _to_matlab_cell_str(items: list[str]) -> str:
    """Convert a list of strings to MATLAB cell-array syntax.

    Example: ``['#.rhd']`` becomes ``"{ '#.rhd' }"``.
    """
    if not items:
        return ""
    quoted = ", ".join(f"'{s}'" for s in items)
    return f"{{ {quoted} }}"


def _as_list(value) -> list:
    """Normalize a JSON scalar/list/absent field to a list.

    MATLAB stores these fields as ``(1,:) string`` arrays, so a lone string and
    a one-element array are the same thing; ``jsondecode`` produces either
    depending on how the file was written.
    """
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [v for v in value if v != ""]
    return [value]


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


def _metadata_reader_pairs(config: dict) -> list[tuple[str, str]]:
    """Pair each ``MetadataReaderClass`` with its ``MetadataReaderFileParameters``.

    Mirrors MATLAB ``ndi.setup.DaqSystemConfiguration/createMetadataReader``:

    * no ``MetadataReaderClass`` -> no metadata readers;
    * one class, many file parameters -> that class instantiated once per
      file parameter;
    * N classes and N file parameters -> element-wise pairing;
    * a single class with a single (possibly empty) file parameter -> one
      reader constructed with that file parameter.

    Returns a list of ``(class_name, tab_separated_file_parameter)`` pairs.
    """
    classes = _as_list(config.get("MetadataReaderClass"))
    if not classes:
        return []

    file_params = _as_list(config.get("MetadataReaderFileParameters"))

    if len(file_params) > 1:
        if len(classes) == 1:
            return [(classes[0], fp) for fp in file_params]
        if len(classes) != len(file_params):
            raise ValueError(
                f"DAQ system '{config.get('Name')}': expected one MetadataReaderClass "
                f"per MetadataReaderFileParameters entry, got {len(classes)} classes "
                f"and {len(file_params)} file parameters."
            )
        return list(zip(classes, file_params))

    # Single (or absent) file parameter: MATLAB passes char('') through, which
    # yields a reader with an empty tab_separated_file_parameter.
    fp = file_params[0] if file_params else ""
    return [(classes[0], fp)]


def _existing_daqsystem_docs(session, name: str) -> list:
    """Return the daqsystem documents in ``session`` named ``name``."""
    q = ndi_query("").isa("daqsystem") & (ndi_query("base.name") == name)
    return session.database_search(q)


def _remove_daqsystem(session, name: str) -> None:
    """Remove a DAQ system and the documents it depends on.

    The Python ``lab()`` writes DAQ systems as documents rather than through
    ``ndi.daq.system`` objects (several of the lab reader classes have no
    Python implementation, so ``session.daqsystem_load`` cannot reconstruct
    them). Removal therefore also works at the document level, but performs
    the same teardown MATLAB's ``S.daqsystem_rm`` does: the daqsystem document
    plus its filenavigator / daqreader / daqmetadatareader dependencies.
    """
    for daq_doc in _existing_daqsystem_docs(session, name):
        _, deps = daq_doc.dependency()
        dep_ids = {dep["value"] for dep in deps if dep.get("value")}
        for dep_id in dep_ids:
            for dep_doc in session.database_search(ndi_query("base.id") == dep_id):
                session.database_rm(dep_doc)
        session.database_rm(daq_doc)


def _add_daq_system_from_config(session, config: dict) -> None:
    """Create the document set for one DAQ system config."""
    name = config["Name"]
    file_params = config.get("FileParameters", [])
    epm_class = config.get("EpochProbeMapClass", "ndi.epoch.epochprobemap_daqsystem")
    epm_file_params = config.get("EpochProbeMapFileParameters", "")
    reader_class = config.get("DaqReaderClass", "ndi.daq.reader.mfdaq")
    system_class = config.get("DaqSystemClass", "ndi.daq.system.mfdaq")
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
    daq_doc = daq_doc.set_dependency_value("filenavigator_id", fn_doc.id, error_if_not_found=False)
    daq_doc = daq_doc.set_dependency_value("daqreader_id", dr_doc.id, error_if_not_found=False)

    # Create a daqmetadatareader document per configured metadata reader.
    #
    # MATLAB constructs each reader as
    # feval(MetadataReaderClass(i), char(MetadataReaderFileParameters(i)))
    # and ndi.daq.metadatareader stores that argument as
    # daqmetadatareader.tab_separated_file_parameter -- the regexp used by
    # readmetadata() to locate the epoch's stimulus-parameter file. Omitting it
    # (as this function used to) leaves the field empty, and readmetadata()
    # then returns no parameters at all for every Python-configured lab.
    for mr_class, mr_file_param in _metadata_reader_pairs(config):
        mr_doc = session.newdocument(
            "daq/daqmetadatareader",
            **{
                "base.name": name,
                "daqmetadatareader.ndi_daqmetadatareader_class": mr_class,
                "daqmetadatareader.tab_separated_file_parameter": mr_file_param,
            },
        )
        session.database_add(mr_doc)
        daq_doc = daq_doc.add_dependency_value_n("daqmetadatareader_id", mr_doc.id)

    session.database_add(daq_doc)


def _add_daq_systems_from_configs(session, configs: list[dict], force_update: bool = False) -> None:
    """Add DAQ systems described by ``configs``, honouring ``force_update``.

    Python equivalent of MATLAB ``ndi.setup.daq.addDaqSystems(S, labName, force)``:
    a DAQ system that already exists in the session is left untouched unless
    ``force_update`` is true, in which case it is removed and re-created from
    the current definition.
    """
    for config in configs:
        name = config["Name"]
        exists = bool(_existing_daqsystem_docs(session, name))

        if force_update and exists:
            _remove_daqsystem(session, name)
            exists = False

        if not exists:
            _add_daq_system_from_config(session, config)


def lab(session, lab_name: str, force_update: bool = False):
    """Add a lab's DAQ systems and sync rules to a session.

    For each JSON config in ``ndi_common/daq_systems/<lab_name>/``, creates:

    - A ``daq/filenavigator`` document
    - A ``daq/daqreader`` (or ``daq/daqreader_ndr``) document
    - One ``daq/daqmetadatareader`` document per configured metadata reader,
      each carrying its ``MetadataReaderFileParameters`` regexp
    - A ``daq/daqsystem`` document linking them together

    Then adds the default ``filematch`` sync rule
    (``number_fullpath_matches = 2``) and any lab-specific rules found in
    ``ndi_common/sync_rules/<lab_name>/``.

    Parameters
    ----------
    session : ndi.session.session_base.ndi_session
        The NDI session to add DAQ systems to.
    lab_name : str
        Name of the lab directory under ``ndi_common/daq_systems/``
        (e.g. ``"vhlab"``, ``"marderlab"``, ``"kjnielsenlab"``).
    force_update : bool, optional
        If true, any DAQ system belonging to ``lab_name`` that already exists
        in the session is removed and re-installed from the current
        definition. Useful when the DAQ system definitions have been updated.
        If false (the default), existing DAQ systems are left untouched.
        MATLAB equivalent: ``ndi.setup.lab(..., 'forceUpdate', tf)``.

    Returns
    -------
    ndi.session.session_base.ndi_session
        The same session, for chaining (mirrors MATLAB's value semantics).
    """
    configs = _find_daq_configs(lab_name)

    _add_daq_systems_from_configs(session, configs, force_update=force_update)

    # By default, include a syncrule for matching file names.
    session.syncgraph_addrule(ndi_time_syncrule_filematch({"number_fullpath_matches": 2}))

    # Add any lab-specific synchronization rules. These are defined in
    # ndi_common/sync_rules/<lab_name> and are the syncgraph counterpart to the
    # DAQ systems added above. Labs without extra rules are left unchanged.
    add_sync_rules(session, lab_name)

    return session
