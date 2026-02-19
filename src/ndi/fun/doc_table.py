"""
ndi.fun.doc_table - Document-to-table conversion utilities.

MATLAB equivalents: +ndi/+fun/+docTable/*.m

Converts NDI documents into pandas DataFrames for analysis.
"""

from __future__ import annotations

from typing import Any

try:
    import pandas as pd
except ImportError:
    pd = None  # type: ignore[assignment]


def _require_pandas() -> None:
    if pd is None:
        raise ImportError(
            "pandas is required for ndi.fun.doc_table utilities. "
            "Install it with: pip install pandas"
        )


def ontology_table_row_doc_to_table(
    documents: list[Any],
    stack_all: bool = False,
) -> tuple[list[pd.DataFrame], list[list[str]]]:
    """Convert ontologyTableRow documents to grouped DataFrames.

    MATLAB equivalent: ndi.fun.doc.ontologyTableRowDoc2Table

    Groups documents by their ``variableNames`` field and extracts the
    ``data`` sub-dict from each document's ``ontologyTableRow`` section
    into DataFrame rows.

    Args:
        documents: List of NDI Document objects with ontologyTableRow data.
        stack_all: If True, stack all documents into a single table
            regardless of variable names.  Default groups by variable names.

    Returns:
        Tuple ``(data_tables, doc_ids)`` where *data_tables* is a list of
        DataFrames (one per group) and *doc_ids* is a list of string lists
        containing the document IDs for each group.
    """
    _require_pandas()
    from ndi.fun.table import vstack

    # Extract per-document data rows, variable names, and IDs
    table_rows: list[pd.DataFrame] = []
    variable_names: list[str] = []
    doc_id_list: list[str] = []

    for doc in documents:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        if not isinstance(props, dict):
            continue

        otr = props.get("ontologyTableRow", {})
        if not isinstance(otr, dict):
            continue

        data = otr.get("data", {})
        if not isinstance(data, dict) or not data:
            continue

        var_names = otr.get("variableNames", "")
        base = props.get("base", {})
        doc_id = base.get("id", "")

        table_rows.append(pd.DataFrame([data]))
        variable_names.append(var_names)
        doc_id_list.append(doc_id)

    if not table_rows:
        return [], []

    if stack_all:
        combined = vstack(table_rows)
        return [combined], [doc_id_list]

    # Group by variableNames (preserving first-occurrence order)
    groups: dict[str, list[int]] = {}
    seen_order: list[str] = []
    for i, vn in enumerate(variable_names):
        if vn not in groups:
            groups[vn] = []
            seen_order.append(vn)
        groups[vn].append(i)

    data_tables: list[pd.DataFrame] = []
    doc_ids: list[list[str]] = []
    for vn in seen_order:
        indices = groups[vn]
        group_rows = [table_rows[i] for i in indices]
        group_ids = [doc_id_list[i] for i in indices]
        data_tables.append(vstack(group_rows))
        doc_ids.append(group_ids)

    return data_tables, doc_ids


def doc_cell_array_to_table(
    documents: list[Any],
) -> pd.DataFrame:
    """Convert a list of NDI documents to a DataFrame.

    MATLAB equivalent: ndi.fun.docTable.docCellArray2Table

    Each document contributes one row.  The row is built from
    the document's properties dict, flattened one level deep.

    Args:
        documents: List of NDI Document objects.

    Returns:
        DataFrame with one row per document.
    """
    _require_pandas()

    rows: list[dict[str, Any]] = []
    for doc in documents:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        if not isinstance(props, dict):
            continue

        row: dict[str, Any] = {}
        # Flatten top-level sections
        for section, data in props.items():
            if isinstance(data, dict):
                for key, val in data.items():
                    row[f"{section}.{key}"] = val
            else:
                row[section] = data
        rows.append(row)

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def element_table(
    session: Any,
) -> pd.DataFrame:
    """Create a summary table of element documents.

    MATLAB equivalent: ndi.fun.docTable.element

    Args:
        session: NDI session instance.

    Returns:
        DataFrame with element properties.
    """
    _require_pandas()
    from ndi.query import Query

    docs = session.database_search(Query("").isa("element"))
    rows: list[dict[str, Any]] = []

    for doc in docs:
        props = doc.document_properties
        el = props.get("element", {})
        base = props.get("base", {})
        row = {
            "id": base.get("id", ""),
            "name": el.get("name", ""),
            "reference": el.get("reference", 0),
            "type": el.get("type", ""),
        }
        rows.append(row)

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def subject_table(
    session: Any,
) -> pd.DataFrame:
    """Create a summary table of subject documents.

    MATLAB equivalent: ndi.fun.docTable.subject

    Args:
        session: NDI session instance.

    Returns:
        DataFrame with subject properties.
    """
    _require_pandas()
    from ndi.query import Query

    docs = session.database_search(Query("").isa("subject"))
    rows: list[dict[str, Any]] = []

    for doc in docs:
        props = doc.document_properties
        subj = props.get("subject", {})
        base = props.get("base", {})
        row = {
            "id": base.get("id", ""),
            "local_identifier": subj.get("local_identifier", ""),
            "description": subj.get("description", ""),
        }
        rows.append(row)

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def probe_table(
    session: Any,
) -> pd.DataFrame:
    """Create a summary table of probe documents.

    MATLAB equivalent: ndi.fun.docTable.probe

    Returns a DataFrame with columns:
        SubjectDocumentIdentifier, ProbeDocumentIdentifier, ProbeName,
        ProbeType, ProbeReference, ProbeLocationName, ProbeLocationOntology,
        CellTypeName, CellTypeOntology

    Args:
        session: NDI session or dataset instance.

    Returns:
        DataFrame with probe properties.
    """
    _require_pandas()
    from ndi.query import Query

    # 1. Get all element docs that are probes
    docs = session.database_search(Query("").isa("probe"))
    if not docs:
        # Fallback: try all element docs
        docs = session.database_search(Query("").isa("element"))

    # 2. Build probe_location index: probe_id -> location info
    probe_loc_docs = session.database_search(Query("").isa("probe_location"))
    loc_by_probe: dict[str, dict] = {}
    for pld in probe_loc_docs:
        props = pld.document_properties if hasattr(pld, "document_properties") else pld
        probe_id = _get_depends_on(props, "probe_id")
        if probe_id:
            pl = props.get("probe_location", {})
            loc_by_probe[probe_id] = pl

    # 3. Build openminds_element index: element_id -> cell type info
    om_elem_docs = session.database_search(Query("").isa("openminds_element"))
    ct_by_element: dict[str, dict] = {}
    for omed in om_elem_docs:
        props = omed.document_properties if hasattr(omed, "document_properties") else omed
        element_id = _get_depends_on(props, "element_id")
        if element_id:
            fields = props.get("openminds", {}).get("fields", {})
            ct_by_element[element_id] = fields

    # 4. Build rows
    rows: list[dict[str, Any]] = []
    for doc in docs:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        el = props.get("element", {})
        base = props.get("base", {})
        probe_id = base.get("id", "")

        row: dict[str, Any] = {
            "SubjectDocumentIdentifier": _get_depends_on(props, "subject_id"),
            "ProbeDocumentIdentifier": probe_id,
            "ProbeName": el.get("name", ""),
            "ProbeType": el.get("type", ""),
            "ProbeReference": el.get("reference", 0),
        }

        # Probe location
        loc = loc_by_probe.get(probe_id, {})
        row["ProbeLocationName"] = loc.get("name", "")
        row["ProbeLocationOntology"] = loc.get("ontology_name", "")

        # Cell type
        ct = ct_by_element.get(probe_id, {})
        row["CellTypeName"] = ct.get("name", "")
        row["CellTypeOntology"] = ct.get("preferredOntologyIdentifier", "")

        rows.append(row)

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def epoch_table(
    session: Any,
) -> pd.DataFrame:
    """Create a summary table of epoch-related documents.

    MATLAB equivalent: ndi.fun.docTable.epoch

    Builds one row per (epoch, probe) combination by parsing the
    ``epochfiles_ingested`` documents and cross-referencing with
    ``stimulus_bath`` and ``openminds_stimulus`` documents.

    Returns a DataFrame with columns:
        EpochNumber, EpochDocumentIdentifier, ProbeDocumentIdentifier,
        SubjectDocumentIdentifier, MixtureName, MixtureOntology,
        ApproachName, ApproachOntology

    Args:
        session: NDI session or dataset instance.

    Returns:
        DataFrame with epoch timing and stimulus information.
    """
    _require_pandas()
    import csv
    import io

    from ndi.query import Query

    # 1. Build element name → (id, subject_id) map
    elem_docs = session.database_search(Query("").isa("element"))
    elem_by_key: dict[str, dict] = {}
    for doc in elem_docs:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        el = props.get("element", {})
        base = props.get("base", {})
        name = el.get("name", "")
        ref = el.get("reference", 0)
        etype = el.get("type", "")
        key = f"{name}|{ref}|{etype}"
        elem_by_key[key] = {
            "id": base.get("id", ""),
            "subject_id": _get_depends_on(props, "subject_id"),
        }

    # 2. Build epoch → stimulus_bath mapping
    sb_docs = session.database_search(Query("").isa("stimulus_bath"))
    sb_by_epoch: dict[str, list[dict]] = {}
    for doc in sb_docs:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        eid = props.get("epochid", {}).get("epochid", "")
        if eid:
            sb = props.get("stimulus_bath", {})
            sb_by_epoch.setdefault(eid, []).append(sb)

    # 3. Build epoch → openminds_stimulus (approach) mapping
    approach_docs = session.database_search(Query("").isa("openminds_stimulus"))
    approach_by_epoch: dict[str, list[dict]] = {}
    for doc in approach_docs:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        eid = props.get("epochid", {}).get("epochid", "")
        if eid:
            fields = props.get("openminds", {}).get("fields", {})
            approach_by_epoch.setdefault(eid, []).append(fields)

    # 4. Parse epochfiles_ingested docs to get epoch → probe mappings
    efi_docs = session.database_search(Query("").isa("epochfiles_ingested"))
    epoch_counter: dict[str, int] = {}  # probe_id -> running count
    rows: list[dict[str, Any]] = []

    for doc in efi_docs:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        ef = props.get("epochfiles_ingested", {})
        epoch_id = ef.get("epoch_id", "")
        epm_str = ef.get("epochprobemap", "")

        if not epm_str or not epoch_id:
            continue

        # Parse TSV epochprobemap
        try:
            reader = csv.DictReader(io.StringIO(epm_str), delimiter="\t")
            probes_in_epoch = list(reader)
        except Exception:
            continue

        # Mixture info for this epoch
        sbs = sb_by_epoch.get(epoch_id, [])
        mixture_name = ""
        mixture_ont = ""
        if sbs:
            loc = sbs[0].get("location", {})
            if isinstance(loc, dict):
                mixture_name = loc.get("name", "")
                mixture_ont = loc.get("ontologyNode", "")

        # Approach info for this epoch
        approaches = approach_by_epoch.get(epoch_id, [])
        approach_name = ""
        approach_ont = ""
        if approaches:
            approach_name = approaches[0].get("name", "")
            approach_ont = approaches[0].get("preferredOntologyIdentifier", "")

        for probe_entry in probes_in_epoch:
            pname = probe_entry.get("name", "")
            pref = probe_entry.get("reference", "0")
            ptype = probe_entry.get("type", "")

            # Convert reference to int for matching
            try:
                pref_int = int(pref)
            except (ValueError, TypeError):
                pref_int = 0

            key = f"{pname}|{pref_int}|{ptype}"
            elem_info = elem_by_key.get(key, {})
            probe_id = elem_info.get("id", "")
            subject_id = elem_info.get("subject_id", "")

            # Epoch counter per probe
            epoch_counter.setdefault(probe_id, 0)
            epoch_counter[probe_id] += 1

            rows.append(
                {
                    "EpochNumber": epoch_counter[probe_id],
                    "EpochDocumentIdentifier": epoch_id,
                    "ProbeDocumentIdentifier": probe_id,
                    "SubjectDocumentIdentifier": subject_id,
                    "MixtureName": mixture_name,
                    "MixtureOntology": mixture_ont,
                    "ApproachName": approach_name,
                    "ApproachOntology": approach_ont,
                }
            )

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def openminds_table(
    session: Any,
    doc_type: str = "openminds",
) -> pd.DataFrame:
    """Gather OpenMINDS document properties into a table.

    MATLAB equivalent: ndi.fun.docTable.openminds

    Args:
        session: NDI session instance.
        doc_type: OpenMINDS document type to query.

    Returns:
        DataFrame with OpenMINDS document properties.
    """
    _require_pandas()
    from ndi.query import Query

    docs = session.database_search(Query("").isa(doc_type))
    rows: list[dict[str, Any]] = []

    for doc in docs:
        props = doc.document_properties
        base = props.get("base", {})
        om = props.get(doc_type, {})
        row = {"id": base.get("id", "")}
        if isinstance(om, dict):
            row.update(om)
        rows.append(row)

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def treatment_table(
    session: Any,
) -> pd.DataFrame:
    """Gather treatment document properties into a table.

    MATLAB equivalent: ndi.fun.docTable.treatment

    Args:
        session: NDI session instance.

    Returns:
        DataFrame with treatment document properties.
    """
    _require_pandas()
    from ndi.query import Query

    docs = session.database_search(Query("").isa("treatment"))
    rows: list[dict[str, Any]] = []

    for doc in docs:
        props = doc.document_properties
        base = props.get("base", {})
        treat = props.get("treatment", {})
        row = {"id": base.get("id", "")}
        if isinstance(treat, dict):
            row.update(treat)
        rows.append(row)

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _get_depends_on(props: dict, name: str) -> str:
    """Extract a depends_on value by name from document properties."""
    deps = props.get("depends_on", [])
    if isinstance(deps, dict):
        deps = [deps]
    if not isinstance(deps, list):
        return ""
    for dep in deps:
        if isinstance(dep, dict) and dep.get("name") == name:
            val = dep.get("value", "")
            return val if isinstance(val, str) else ""
    return ""


def subject_summary(
    session: Any,
) -> pd.DataFrame:
    """Create a rich subject summary joining subject, openminds, and treatment data.

    MATLAB equivalent: ndi.fun.docTable.subject

    Builds a comprehensive table with one row per subject, including strain,
    species, genetic strain type, biological sex, and treatment information
    from linked ``openminds_subject`` and ``treatment`` documents.

    Args:
        session: NDI session or dataset instance.

    Returns:
        DataFrame with columns: SubjectDocumentIdentifier,
        SessionDocumentIdentifier, SubjectLocalIdentifier,
        StrainName, StrainOntology, GeneticStrainTypeName,
        SpeciesName, SpeciesOntology, BackgroundStrainName,
        BackgroundStrainOntology, BiologicalSexName, BiologicalSexOntology,
        Treatment_FoodRestrictionOnsetTime, Treatment_FoodRestrictionOffsetTime.
    """
    _require_pandas()
    from ndi.query import Query

    # 1. Get all subject docs — build subject_id → base info
    subject_docs = session.database_search(Query("").isa("subject"))
    subject_info: dict[str, dict[str, str]] = {}
    for doc in subject_docs:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        if not isinstance(props, dict):
            continue
        base = props.get("base", {})
        subj = props.get("subject", {})
        sid = base.get("id", "")
        if sid:
            subject_info[sid] = {
                "SubjectDocumentIdentifier": sid,
                "SessionDocumentIdentifier": base.get("session_id", ""),
                "SubjectLocalIdentifier": subj.get("local_identifier", ""),
            }

    if not subject_info:
        return pd.DataFrame()

    # 2. Get all openminds_subject docs — index by subject_id and type
    om_docs = session.database_search(Query("").isa("openminds_subject"))

    # Per-subject openminds data: {subject_id: {type: [doc_props, ...]}}
    om_by_subject: dict[str, dict[str, list[dict]]] = {sid: {} for sid in subject_info}

    for doc in om_docs:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        if not isinstance(props, dict):
            continue
        subj_id = _get_depends_on(props, "subject_id")
        if subj_id not in om_by_subject:
            continue
        om = props.get("openminds", {})
        if not isinstance(om, dict):
            continue
        om_type = om.get("openminds_type", "")
        short_type = om_type.rsplit("/", 1)[-1] if "/" in om_type else om_type
        om_by_subject[subj_id].setdefault(short_type, []).append(om)

    # 3. Get all treatment/measurement docs — index by subject_id
    # MATLAB queries: treatment | treatment_drug | virus_injection | measurement
    treat_docs = session.database_search(Query("").isa("treatment"))
    for extra_type in ("treatment_drug", "virus_injection", "measurement"):
        try:
            treat_docs.extend(session.database_search(Query("").isa(extra_type)))
        except Exception:
            pass
    treat_by_subject: dict[str, list[dict]] = {sid: [] for sid in subject_info}

    for doc in treat_docs:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        if not isinstance(props, dict):
            continue
        subj_id = _get_depends_on(props, "subject_id")
        if subj_id in treat_by_subject:
            # Try treatment, then measurement property
            treat = props.get("treatment", props.get("measurement", {}))
            if isinstance(treat, dict):
                treat_by_subject[subj_id].append(treat)

    # 4. Build rows
    rows: list[dict[str, Any]] = []
    for sid, info in subject_info.items():
        row = dict(info)  # copy base fields

        om_data = om_by_subject.get(sid, {})

        # Strain: find main strain (has non-empty backgroundStrain) vs background
        strains = om_data.get("Strain", [])
        main_strain: dict = {}
        bg_strain: dict = {}
        if len(strains) == 1:
            main_strain = strains[0]
        elif len(strains) >= 2:
            # Main strain has non-empty backgroundStrain field
            for s in strains:
                fields = s.get("fields", {})
                bg = fields.get("backgroundStrain", [])
                if bg:
                    main_strain = s
                else:
                    bg_strain = s
            if not main_strain:
                main_strain = strains[0]
                bg_strain = strains[1] if len(strains) > 1 else {}

        main_fields = main_strain.get("fields", {}) if main_strain else {}
        bg_fields = bg_strain.get("fields", {}) if bg_strain else {}
        row["StrainName"] = main_fields.get("name", "")
        row["StrainOntology"] = main_fields.get("ontologyIdentifier", "")
        row["BackgroundStrainName"] = bg_fields.get("name", "")
        row["BackgroundStrainOntology"] = bg_fields.get("ontologyIdentifier", "")

        # GeneticStrainType: pick the one matching the main strain
        gst_docs = om_data.get("GeneticStrainType", [])
        gst_name = ""
        if len(gst_docs) == 1:
            gst_name = gst_docs[0].get("fields", {}).get("name", "")
        elif len(gst_docs) >= 2:
            # Prefer 'transgenic'/'mutant' for the main strain type
            for g in gst_docs:
                n = g.get("fields", {}).get("name", "")
                if n and n != "wildtype":
                    gst_name = n
                    break
            if not gst_name:
                gst_name = gst_docs[0].get("fields", {}).get("name", "")
        row["GeneticStrainTypeName"] = gst_name

        # Species
        species_docs = om_data.get("Species", [])
        if species_docs:
            sp = species_docs[0].get("fields", {})
            row["SpeciesName"] = sp.get("name", "")
            row["SpeciesOntology"] = sp.get("preferredOntologyIdentifier", "")
        else:
            row["SpeciesName"] = ""
            row["SpeciesOntology"] = ""

        # BiologicalSex
        sex_docs = om_data.get("BiologicalSex", [])
        if sex_docs:
            sx = sex_docs[0].get("fields", {})
            row["BiologicalSexName"] = sx.get("name", "")
            row["BiologicalSexOntology"] = sx.get("preferredOntologyIdentifier", "")
        else:
            row["BiologicalSexName"] = ""
            row["BiologicalSexOntology"] = ""

        # Treatments: dynamic columns via ontology lookup
        # Matches MATLAB treatment.m logic: ontologyName -> short_name -> column
        treatments = treat_by_subject.get(sid, [])
        for t in treatments:
            ontology_name = t.get("ontologyName", "")
            treat_name = t.get("name", "")
            string_value = (t.get("string_value") or "").strip()
            numeric_value = t.get("numeric_value")
            # numeric_value of [] means absent
            if isinstance(numeric_value, list) and not numeric_value:
                numeric_value = None

            # Determine column prefix via ontology lookup
            col_prefix = ""
            if ontology_name:
                try:
                    from ndi.ontology import lookup as ontology_lookup

                    result = ontology_lookup(ontology_name)
                    if result and result.short_name:
                        col_prefix = result.short_name
                except Exception:
                    pass
            if not col_prefix:
                from ndi.fun.name_utils import name_to_variable_name

                col_prefix = name_to_variable_name(treat_name or ontology_name)
            if not col_prefix:
                continue

            # Determine column(s) based on value types
            # (matching MATLAB treatment.m lines 135-156)
            #
            # MATLAB priority: 1) datetime check, 2) ontology ":" check
            # Datetime strings (e.g. "03-Nov-2023 07:53:00") contain ":"
            # but should NOT be treated as ontology references.
            is_datetime = False
            if string_value:
                try:
                    from dateutil.parser import parse as _date_parse

                    _date_parse(string_value)
                    is_datetime = True
                except Exception:
                    pass

            ontology_resolved = False
            if string_value and not is_datetime and ":" in string_value:
                # Try ontology lookup — only create Name/Ontology if it resolves
                try:
                    from ndi.ontology import lookup as ontology_lookup

                    val_result = ontology_lookup(string_value)
                    if val_result and val_result.name:
                        row[f"{col_prefix}Name"] = val_result.name
                        row[f"{col_prefix}Ontology"] = val_result.id or string_value
                        ontology_resolved = True
                except Exception:
                    pass
                if not ontology_resolved:
                    # Lookup failed — store raw value in Name/Ontology
                    row[f"{col_prefix}Name"] = string_value
                    row[f"{col_prefix}Ontology"] = string_value
                    ontology_resolved = True

            if ontology_resolved:
                pass  # Already handled above
            elif string_value and numeric_value is not None:
                row[f"{col_prefix}Number"] = numeric_value
                row[f"{col_prefix}String"] = string_value
            elif string_value:
                row[col_prefix] = string_value
            elif numeric_value is not None:
                row[col_prefix] = numeric_value

        rows.append(row)

    # Column order: fixed metadata first, then dynamic treatment columns
    fixed_cols = [
        "SubjectDocumentIdentifier",
        "SessionDocumentIdentifier",
        "SubjectLocalIdentifier",
        "StrainName",
        "StrainOntology",
        "GeneticStrainTypeName",
        "SpeciesName",
        "SpeciesOntology",
        "BackgroundStrainName",
        "BackgroundStrainOntology",
        "BiologicalSexName",
        "BiologicalSexOntology",
    ]
    df = pd.DataFrame(rows)
    # Dynamic treatment columns sorted alphabetically
    all_cols = list(df.columns)
    treatment_cols = sorted(c for c in all_cols if c not in fixed_cols)
    col_order = [c for c in fixed_cols if c in all_cols] + treatment_cols
    return df[col_order]
