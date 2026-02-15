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

    Args:
        session: NDI session instance.

    Returns:
        DataFrame with probe properties.
    """
    _require_pandas()
    from ndi.query import Query

    docs = session.database_search(Query("").isa("probe"))
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


def epoch_table(
    session: Any,
) -> pd.DataFrame:
    """Create a summary table of epoch-related documents.

    MATLAB equivalent: ndi.fun.docTable.epoch

    Args:
        session: NDI session instance.

    Returns:
        DataFrame with epoch timing and stimulus information.
    """
    _require_pandas()
    from ndi.query import Query

    docs = session.database_search(Query("").isa("epochprobemap_daqsystem"))
    rows: list[dict[str, Any]] = []

    for doc in docs:
        props = doc.document_properties
        epm = props.get("epochprobemap_daqsystem", {})
        base = props.get("base", {})
        row = {
            "id": base.get("id", ""),
            "epoch_id": epm.get("epoch_id", ""),
        }
        rows.append(row)

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

    # 3. Get all treatment docs — index by subject_id
    treat_docs = session.database_search(Query("").isa("treatment"))
    treat_by_subject: dict[str, list[dict]] = {sid: [] for sid in subject_info}

    for doc in treat_docs:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        if not isinstance(props, dict):
            continue
        subj_id = _get_depends_on(props, "subject_id")
        if subj_id in treat_by_subject:
            treat = props.get("treatment", {})
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

        # Treatment: food restriction onset/offset
        treatments = treat_by_subject.get(sid, [])
        onset = ""
        offset = ""
        for t in treatments:
            name = t.get("name", "").lower()
            val = t.get("string_value", "")
            if not val:
                nv = t.get("numeric_value", "")
                val = str(nv) if nv else ""
            if "onset" in name:
                onset = val
            elif "offset" in name:
                offset = val
        row["Treatment_FoodRestrictionOnsetTime"] = onset
        row["Treatment_FoodRestrictionOffsetTime"] = offset

        rows.append(row)

    # Column order matching MATLAB output
    col_order = [
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
        "Treatment_FoodRestrictionOnsetTime",
        "Treatment_FoodRestrictionOffsetTime",
    ]
    df = pd.DataFrame(rows)
    # Reorder columns (only include those that exist)
    existing_cols = [c for c in col_order if c in df.columns]
    return df[existing_cols]
