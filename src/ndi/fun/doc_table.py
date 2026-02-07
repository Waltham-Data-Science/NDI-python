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
