#!/usr/bin/env python3
"""
NDI Dataset Tutorial: C. elegans Behavior & E. coli Fluorescence Imaging
=========================================================================

Python equivalent of the MATLAB tutorial:
  tutorial_682e7772cdf3f24938176fac.mlx

Paper: https://doi.org/10.7554/eLife.103191.3
Dataset DOI: https://doi.org/10.63884/ndic.2025.pb77mj2s

This script loads the Jess Haley dataset (682e7772cdf3f24938176fac),
runs the same analysis steps as the MATLAB tutorial, and writes
the results to an HTML file.

Prerequisites:
  - pip install pandas matplotlib opencv-python-headless
  - NDI Cloud account (free at https://www.ndi-cloud.com)
  - Set NDI_CLOUD_USERNAME/NDI_CLOUD_PASSWORD env vars (or edit this script)

Usage:
  python tutorials/tutorial_682e7772cdf3f24938176fac.py
"""

from __future__ import annotations

import base64
import io
import os
import sys
import time
from html import escape
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CLOUD_DATASET_ID = "682e7772cdf3f24938176fac"
DATA_PATH = Path(os.path.expanduser("~/Documents/MATLAB/Datasets"))
DATASET_PATH = DATA_PATH / CLOUD_DATASET_ID
OUTPUT_HTML = Path(__file__).parent / f"tutorial_{CLOUD_DATASET_ID}.html"

# ---------------------------------------------------------------------------
# NDI Cloud Credentials
# ---------------------------------------------------------------------------
# To download datasets and fetch binary files on demand, set your
# NDI Cloud credentials below OR as environment variables:
#
#   export NDI_CLOUD_USERNAME="your_email@example.com"
#   export NDI_CLOUD_PASSWORD="your_password"
#
# You can create a free account at https://www.ndi-cloud.com
NDI_CLOUD_USERNAME = os.environ.get("NDI_CLOUD_USERNAME", "")
NDI_CLOUD_PASSWORD = os.environ.get("NDI_CLOUD_PASSWORD", "")


# ---------------------------------------------------------------------------
# HTML Builder
# ---------------------------------------------------------------------------


class HTMLBuilder:
    """Builds an HTML document matching the MATLAB Live Script export style."""

    def __init__(self, title: str):
        self.title = title
        self.sections: list[str] = []

    def add_heading(self, text: str, level: int = 2) -> None:
        self.sections.append(f"<h{level}>{escape(text)}</h{level}>")

    def add_text(self, text: str) -> None:
        paragraphs = text.strip().split("\n\n")
        for p in paragraphs:
            self.sections.append(f"<p>{escape(p.strip())}</p>")

    def add_code(self, code: str) -> None:
        self.sections.append(
            f'<div class="code-block"><pre><code>{escape(code)}</code></pre></div>'
        )

    def add_output_text(self, text: str) -> None:
        self.sections.append(f'<div class="output-block"><pre>{escape(text)}</pre></div>')

    def add_table_html(self, table_html: str, caption: str = "") -> None:
        s = '<div class="table-block">'
        if caption:
            s += f'<div class="table-caption">{escape(caption)}</div>'
        s += table_html
        s += "</div>"
        self.sections.append(s)

    def add_image_base64(self, img_bytes: bytes, fmt: str = "png", caption: str = "") -> None:
        b64 = base64.b64encode(img_bytes).decode()
        s = '<div class="figure-block">'
        s += f'<img src="data:image/{fmt};base64,{b64}" />'
        if caption:
            s += f'<div class="figure-caption">{escape(caption)}</div>'
        s += "</div>"
        self.sections.append(s)

    def add_separator(self) -> None:
        self.sections.append("<hr/>")

    def render(self) -> str:
        body = "\n".join(self.sections)
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(self.title)}</title>
<style>
  body {{
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    max-width: 1100px;
    margin: 0 auto;
    padding: 20px 40px;
    background: #fafafa;
    color: #333;
    line-height: 1.6;
  }}
  h1 {{
    color: #1a5276;
    border-bottom: 3px solid #2980b9;
    padding-bottom: 10px;
  }}
  h2 {{
    color: #1a5276;
    margin-top: 40px;
    border-bottom: 1px solid #d5d8dc;
    padding-bottom: 6px;
  }}
  h3 {{
    color: #2c3e50;
    margin-top: 30px;
  }}
  p {{
    margin: 10px 0;
  }}
  .code-block {{
    background: #f4f6f7;
    border: 1px solid #d5d8dc;
    border-left: 4px solid #2980b9;
    border-radius: 4px;
    padding: 12px 16px;
    margin: 15px 0;
    overflow-x: auto;
  }}
  .code-block pre {{
    margin: 0;
    font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
    font-size: 13px;
    line-height: 1.5;
  }}
  .output-block {{
    background: #fff;
    border: 1px solid #e5e7e9;
    border-left: 4px solid #27ae60;
    border-radius: 4px;
    padding: 12px 16px;
    margin: 10px 0 20px 0;
    overflow-x: auto;
  }}
  .output-block pre {{
    margin: 0;
    font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
    font-size: 12px;
    line-height: 1.4;
    color: #2c3e50;
    white-space: pre-wrap;
  }}
  .table-block {{
    margin: 15px 0 25px 0;
    overflow-x: auto;
  }}
  .table-caption {{
    font-weight: 600;
    color: #2c3e50;
    margin-bottom: 8px;
    font-size: 14px;
  }}
  .table-block table {{
    border-collapse: collapse;
    font-size: 12px;
    font-family: 'Consolas', monospace;
    width: auto;
  }}
  .table-block th {{
    background: #2980b9;
    color: #fff;
    padding: 8px 12px;
    text-align: left;
    font-weight: 600;
    white-space: nowrap;
  }}
  .table-block td {{
    padding: 6px 12px;
    border-bottom: 1px solid #e5e7e9;
    white-space: nowrap;
    max-width: 300px;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .table-block tr:nth-child(even) {{
    background: #f8f9fa;
  }}
  .table-block tr:hover {{
    background: #eaf2f8;
  }}
  .figure-block {{
    text-align: center;
    margin: 20px 0;
  }}
  .figure-block img {{
    max-width: 100%;
    border: 1px solid #d5d8dc;
    border-radius: 4px;
  }}
  .figure-caption {{
    font-style: italic;
    color: #7f8c8d;
    margin-top: 8px;
    font-size: 13px;
  }}
  .timing {{
    color: #7f8c8d;
    font-size: 11px;
    font-style: italic;
  }}
  hr {{
    border: none;
    border-top: 1px solid #d5d8dc;
    margin: 30px 0;
  }}
</style>
</head>
<body>
<h1>{escape(self.title)}</h1>
{body}
<hr/>
<p class="timing">Generated by NDI-python tutorial script</p>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def df_to_html(df: Any, max_rows: int = 20, show_shape: bool = True) -> str:
    """Convert a DataFrame to a styled HTML table string."""

    n = len(df)
    if n > max_rows:
        top = df.head(max_rows // 2)
        bottom = df.tail(max_rows // 2)
        # Build HTML for top
        html = "<table>"
        html += "<tr>" + "".join(f"<th>{escape(str(c))}</th>" for c in df.columns) + "</tr>"
        for _, row in top.iterrows():
            html += "<tr>" + "".join(f"<td>{escape(str(v)[:200])}</td>" for v in row) + "</tr>"
        # Ellipsis row
        html += (
            "<tr>"
            + "".join("<td style='text-align:center;color:#999;'>...</td>" for _ in df.columns)
            + "</tr>"
        )
        for _, row in bottom.iterrows():
            html += "<tr>" + "".join(f"<td>{escape(str(v)[:200])}</td>" for v in row) + "</tr>"
        html += "</table>"
    else:
        html = "<table>"
        html += "<tr>" + "".join(f"<th>{escape(str(c))}</th>" for c in df.columns) + "</tr>"
        for _, row in df.iterrows():
            html += "<tr>" + "".join(f"<td>{escape(str(v)[:200])}</td>" for v in row) + "</tr>"
        html += "</table>"

    shape_str = f"<p class='timing'>{n} rows x {len(df.columns)} columns</p>" if show_shape else ""
    return html + shape_str


def fig_to_bytes() -> bytes:
    """Capture current matplotlib figure as PNG bytes."""
    import matplotlib.pyplot as plt

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    buf.seek(0)
    data = buf.read()
    plt.close()
    return data


def timed(func):
    """Decorator to time a function and print elapsed time."""

    def wrapper(*args, **kwargs):
        t0 = time.time()
        result = func(*args, **kwargs)
        elapsed = time.time() - t0
        print(f"  [{func.__name__}] {elapsed:.1f}s")
        return result

    return wrapper


# ---------------------------------------------------------------------------
# Tutorial Sections
# ---------------------------------------------------------------------------


def section_import(html: HTMLBuilder) -> None:
    """Section 1: Import the NDI dataset."""
    html.add_heading("Import the NDI dataset")
    html.add_text(
        "Define the dataset path and cloud ID. "
        "You will need an NDI Cloud account to download the dataset and "
        "fetch binary files on demand."
    )
    html.add_text("Paper: https://doi.org/10.7554/eLife.103191.3")
    html.add_text("Dataset DOI: https://doi.org/10.63884/ndic.2025.pb77mj2s")

    html.add_code("""\
import os
from pathlib import Path
from ndi.cloud import download_dataset
from ndi.cloud.auth import login
from ndi.cloud.client import CloudClient
import ndi.dataset

cloud_dataset_id = '682e7772cdf3f24938176fac'
data_path = Path(os.path.expanduser('~/Documents/MATLAB/Datasets'))
dataset_path = data_path / cloud_dataset_id

# NDI Cloud credentials (set via environment variables or edit here)
# Create a free account at https://www.ndi-cloud.com
ndi_cloud_username = os.environ.get('NDI_CLOUD_USERNAME', '')
ndi_cloud_password = os.environ.get('NDI_CLOUD_PASSWORD', '')""")

    html.add_output_text(
        f"cloud_dataset_id = '{CLOUD_DATASET_ID}'\n" f"dataset_path = '{DATASET_PATH}'"
    )


@timed
def section_load_dataset(html: HTMLBuilder) -> Any:
    """Section 2: Download or load the NDI dataset."""
    import ndi.dataset
    from ndi.cloud import download_dataset
    from ndi.cloud.auth import login
    from ndi.cloud.client import CloudClient

    html.add_heading("Download or load the NDI dataset")
    html.add_text(
        "The first time you try to access the data, it needs to be downloaded "
        "from NDI Cloud. This will take several minutes. Once you have the "
        "dataset downloaded, every other time you examine the data you can "
        "just load it."
    )

    html.add_code("""\
if dataset_path.exists():
    # Load from previously downloaded dataset
    dataset = ndi.dataset.Dataset(dataset_path)
else:
    # Download from NDI Cloud (first time only)
    config = login(ndi_cloud_username, ndi_cloud_password)
    client = CloudClient(config)
    dataset = download_dataset(client, cloud_dataset_id, str(dataset_path), verbose=True)""")

    t0 = time.time()
    if DATASET_PATH.exists():
        dataset = ndi.dataset.Dataset(DATASET_PATH)
        elapsed = time.time() - t0
        html.add_output_text(f"Dataset loaded in {elapsed:.1f}s from {DATASET_PATH}")
    else:
        if not NDI_CLOUD_USERNAME or not NDI_CLOUD_PASSWORD:
            print("ERROR: Dataset not found locally and no NDI Cloud credentials set.")
            print("Set NDI_CLOUD_USERNAME and NDI_CLOUD_PASSWORD environment variables,")
            print("or edit the credentials at the top of this script.")
            print(f"Expected dataset path: {DATASET_PATH}")
            sys.exit(1)
        config = login(NDI_CLOUD_USERNAME, NDI_CLOUD_PASSWORD)
        client = CloudClient(config)
        dataset = download_dataset(client, CLOUD_DATASET_ID, str(DATASET_PATH), verbose=True)
        elapsed = time.time() - t0
        html.add_output_text(f"Dataset downloaded in {elapsed:.1f}s to {DATASET_PATH}")

    return dataset


@timed
def section_sessions(html: HTMLBuilder, dataset: Any) -> dict:
    """Section 3: Retrieve the NDI sessions."""
    from ndi.query import Query

    html.add_heading("Retrieve the NDI session")
    html.add_text(
        "A dataset can have multiple sessions. This dataset has one session "
        "for C. elegans behavior and one session for E. coli fluorescence "
        "imaging data."
    )

    html.add_code("""\
from ndi.query import Query

session_docs = dataset.database_search(Query('').isa('session'))
for doc in session_docs:
    ref = doc.document_properties.get('session', {}).get('reference', '')
    print(f'  Session: {ref}')""")

    session_docs = dataset.database_search(Query("").isa("session"))
    output_lines = []
    sessions_by_ref: dict[str, Any] = {}
    for doc in session_docs:
        ref = doc.document_properties.get("session", {}).get("reference", "")
        if ref:
            output_lines.append(f"  Session: {ref}")
            sessions_by_ref[ref] = doc

    html.add_output_text("\n".join(output_lines) if output_lines else "(no session references)")

    return sessions_by_ref


@timed
def section_doc_types(html: HTMLBuilder, dataset: Any) -> tuple:
    """Section 4: View NDI file types."""
    import pandas as pd

    from ndi.fun.doc import get_doc_types

    html.add_heading("View NDI file types")
    html.add_text(
        "Each NDI dataset is composed of .json documents and associated binary "
        "files. Let's start by taking a look at the document types in this "
        "dataset. We'll subsequently explore each of these below."
    )

    html.add_code("""\
from ndi.fun.doc import get_doc_types

doc_types, doc_counts = get_doc_types(dataset)
documents_ndi = pd.DataFrame({'docTypes': doc_types, 'docCounts': doc_counts})
print(documents_ndi)""")

    doc_types, doc_counts = get_doc_types(dataset)
    df = pd.DataFrame({"docTypes": doc_types, "docCounts": doc_counts})
    html.add_table_html(df_to_html(df, max_rows=30), f"documentsNDI ({len(df)} x 2 table)")

    return doc_types, doc_counts


@timed
def section_ontology_terms(html: HTMLBuilder, dataset: Any) -> None:
    """Section 5: View ontology term definitions."""
    import pandas as pd

    from ndi.fun.doc import ontology_table_row_vars

    html.add_heading("View ontology term definitions")
    html.add_text(
        "Most of the metadata about these experiments are stored in "
        "ontologyTableRow documents. We can look at the variables stored in "
        "all ontologyTableRow documents and their well-defined meanings "
        "linked to an ontology."
    )

    html.add_code("""\
from ndi.fun.doc import ontology_table_row_vars
from ndi.ontology import lookup

full_names, variable_names, ontology_nodes = ontology_table_row_vars(dataset)

# Look up a specific ontology term by name
target_name = 'C. elegans behavioral assay: deceleration upon encounter'
idx = full_names.index(target_name)
term_id = ontology_nodes[idx]
result = lookup(term_id)
print(f'id:         {result.id}')
print(f'name:       {result.name}')
print(f'definition: {result.definition}')
print(f'shortName:  {result.short_name}')""")

    full_names, variable_names, ontology_nodes = ontology_table_row_vars(dataset)

    # Show the full variable list
    var_df = pd.DataFrame(
        {
            "name": full_names,
            "variableName": variable_names,
            "ontologyNode": ontology_nodes,
        }
    )
    html.add_table_html(
        df_to_html(var_df, max_rows=80), f"Ontology variables ({len(var_df)} unique variables)"
    )

    # Look up a specific term
    target_name = "C. elegans behavioral assay: deceleration upon encounter"
    try:
        idx = full_names.index(target_name)
        term_id = ontology_nodes[idx]

        from ndi.ontology import lookup

        result = lookup(term_id)

        info_df = pd.DataFrame(
            {"value": [result.id, result.name, result.definition[:200], result.short_name]},
            index=["id", "name", "definition", "shortName"],
        )

        html.add_table_html(
            df_to_html(info_df, max_rows=10, show_shape=False), f"variableInfo: lookup('{term_id}')"
        )
    except (ValueError, Exception) as e:
        html.add_output_text(f"Could not look up ontology term: {e}")


@timed
def section_retrieve_metadata(html: HTMLBuilder, dataset: Any) -> tuple:
    """Section 6-7: Retrieve experiment metadata (ontologyTableRow tables)."""
    from ndi.fun.doc_table import ontology_table_row_doc_to_table
    from ndi.query import Query

    html.add_heading("View C. elegans dataset")
    html.add_text(
        "In these next few sections we will look at the C. elegans session. "
        "Later, we will look at the E. coli session."
    )

    html.add_heading("Retrieve experiment metadata", level=3)
    html.add_text(
        "Most of the metadata about these experiments such as information "
        "about the agar plates used for cultivation and behavioral assay of "
        "the animals is stored in ontologyTableRow documents. Each document "
        "contains one row of data. We'll start by retrieving the information "
        "from these documents and placing them in their respective tables."
    )

    html.add_code("""\
from ndi.query import Query
from ndi.fun.doc_table import ontology_table_row_doc_to_table

query = Query('').isa('ontologyTableRow')
docs = dataset.database_search(query)
data_tables, doc_ids = ontology_table_row_doc_to_table(docs)

for i, (dt, ids) in enumerate(zip(data_tables, doc_ids)):
    print(f'Table {i+1}: {len(dt)} rows x {len(dt.columns)} cols — {list(dt.columns)[:3]}...')""")

    docs = dataset.database_search(Query("").isa("ontologyTableRow"))
    data_tables, doc_ids = ontology_table_row_doc_to_table(docs)

    output_lines = []
    for i, (dt, _ids) in enumerate(zip(data_tables, doc_ids)):
        cols_preview = list(dt.columns)[:4]
        output_lines.append(
            f"Table {i+1}: {len(dt)} rows x {len(dt.columns)} cols — {cols_preview}..."
        )
    html.add_output_text("\n".join(output_lines))

    # Add document identifier columns (matching MATLAB addvars)
    for i, (dt, ids) in enumerate(zip(data_tables, doc_ids)):
        cols = set(dt.columns)
        if "BacterialPatchCenter_XCoordinate" in cols:
            # C. elegans behavioral patch table
            data_tables[i] = dt.assign(BacterialPatchDocumentIdentifier=ids)
        elif "CElegansBehavioralAssayLabel" in cols and "BacterialPlateIdentifier" in cols:
            # C. elegans behavioral plate table
            data_tables[i] = dt.assign(BacterialPlateDocumentIdentifier=ids)
        elif (
            "MicroscopyImageIdentifier" in cols
            and "BacterialPlateIdentifier" in cols
            and len(dt) < 2000
        ):
            # E. coli microscopy image table (~1521 rows)
            data_tables[i] = dt.assign(ImageDocumentIdentifier=ids)
        elif "AgarPlatePouringTimestamp" in cols:
            # E. coli plate table
            data_tables[i] = dt.assign(BacterialPlateDocumentIdentifier=ids)

    return data_tables, doc_ids


@timed
def section_subject_summary(html: HTMLBuilder, dataset: Any, data_tables: list) -> Any:
    """Section 8: View subject summary table."""

    from ndi.fun.doc_table import subject_summary
    from ndi.fun.table import join

    html.add_heading("View subject summary table", level=3)
    html.add_text(
        "Each individual animal is referred to as a subject and has a unique "
        "alphanumeric SubjectDocumentID and SubjectLocalID. This dataset "
        "contains ontologyTableRow, subject, openminds_subject, and openminds "
        "documents which store metadata about each subject including their "
        "species, strain, genetic strain type, and biological sex which are "
        "linked to well-defined ontologies such as NCBI and WormBase. "
        "Additionally, metadata about any treatments that a subject received "
        "such as food deprivation are stored in treatment documents."
    )
    html.add_text("A summary table showing the metadata for each subject can be viewed below.")

    html.add_code("""\
from ndi.fun.doc_table import subject_summary
from ndi.fun.table import join

subject_summ = subject_summary(dataset)

# Find the subject identifier OTR table (has SubjectIdentifier column)
subject_otr = None
for dt in data_tables:
    if 'SubjectIdentifier' in dt.columns and 'SubjectLocalIdentifier' in dt.columns:
        subject_otr = dt
        break

# Join the OTR subject table with the rich subject summary
subject_table = join([subject_otr, subject_summ])
print(f'subjectTable: {subject_table.shape[0]} x {subject_table.shape[1]} table')
print(subject_table.head(10))""")

    subject_summ = subject_summary(dataset)

    # Find the OTR subject identifier table
    subject_otr = None
    for dt in data_tables:
        if "SubjectIdentifier" in dt.columns and "SubjectLocalIdentifier" in dt.columns:
            if len(dt.columns) <= 5:  # the small subject table
                subject_otr = dt
                break

    if subject_otr is not None:
        subject_table = join([subject_otr, subject_summ])
    else:
        # Fallback: use subject_summary directly
        subject_table = subject_summ

    html.add_table_html(
        df_to_html(subject_table, max_rows=20),
        f"subjectTable ({subject_table.shape[0]} x {subject_table.shape[1]} table)",
    )

    return subject_table


@timed
def section_filter_subjects(html: HTMLBuilder, subject_table: Any) -> Any:
    """Section 9: Filter subjects."""
    from ndi.fun.table import identify_matching_rows

    html.add_heading("Filter subjects", level=3)
    html.add_text(
        "We have created tools to filter a table by its values. "
        "Try finding subjects matching a given criterion."
    )

    html.add_code("""\
from ndi.fun.table import identify_matching_rows

column_name = 'StrainName'
data_value = 'PR811'
row_ind = identify_matching_rows(
    subject_table, column_name, data_value, string_match='contains'
)
filtered_subjects = subject_table[row_ind]
print(f'filteredSubjects: {len(filtered_subjects)} rows')""")

    col = "StrainName" if "StrainName" in subject_table.columns else "SubjectLocalIdentifier"
    value = "PR811"
    row_ind = identify_matching_rows(subject_table, col, value, string_match="contains")
    filtered = subject_table[row_ind]

    html.add_output_text(
        f"filteredSubjects: {len(filtered)} rows x {len(filtered.columns)} columns"
    )
    html.add_table_html(
        df_to_html(filtered, max_rows=20),
        f"filteredSubjects ({len(filtered)} x {len(filtered.columns)} table)",
    )

    return filtered


@timed
def section_behavior_plate(html: HTMLBuilder, data_tables: list) -> Any:
    """Section 10: View bacterial plate summary tables."""
    from ndi.fun.table import join

    html.add_heading("View bacterial plate summary tables", level=3)
    html.add_text("Let's combine all of the information about the behavior plates and patches.")

    html.add_code("""\
from ndi.fun.table import join

# Find the bacterial patch and plate tables, then join them
patch_table = None
plate_table = None
for dt in data_tables:
    if 'BacterialPatchRadius' in dt.columns:
        patch_table = dt
    elif 'BacterialPlateIdentifier' in dt.columns and 'BacterialOD600Label' in dt.columns:
        plate_table = dt

behavior_plate_table = join([patch_table, plate_table])
print(f'behaviorPlateTable: {behavior_plate_table.shape}')""")

    # Find the C. elegans behavioral patch table (6206 rows, has XY coordinates)
    # and the plate metadata table (597 rows, has CElegansBehavioralAssayLabel)
    patch_table = None
    plate_table = None
    for dt in data_tables:
        cols = set(dt.columns)
        if "BacterialPatchCenter_XCoordinate" in cols:
            patch_table = dt
        elif "CElegansBehavioralAssayLabel" in cols and "BacterialPlateIdentifier" in cols:
            plate_table = dt

    if patch_table is not None and plate_table is not None:
        behavior_plate_table = join([patch_table, plate_table])
        html.add_output_text(
            f"behaviorPlateTable: {behavior_plate_table.shape[0]} rows x "
            f"{behavior_plate_table.shape[1]} columns"
        )
        html.add_table_html(
            df_to_html(behavior_plate_table, max_rows=20),
            f"behaviorPlateTable ({behavior_plate_table.shape[0]} x "
            f"{behavior_plate_table.shape[1]} table)",
        )
        return behavior_plate_table
    else:
        html.add_output_text("Could not find matching patch/plate tables to join.")
        return None


def _identify_tables(data_tables: list) -> dict:
    """Identify OTR tables by their column signatures.

    Returns dict with keys: patch, plate_assay, subject_plate,
    subject, encounter, exclusion, ecoli_microscopy, ecoli_plate, ecoli_od600.
    """
    tables: dict[str, Any] = {}
    for dt in data_tables:
        cols = set(dt.columns)
        if "BacterialPatchCenter_XCoordinate" in cols:
            tables["patch"] = dt
        elif "CElegansBehavioralAssayLabel" in cols and "BacterialPlateIdentifier" in cols:
            tables["plate_assay"] = dt
        elif (
            "SubjectDocumentIdentifier" in cols
            and "BacterialPlateIdentifier" in cols
            and len(dt) > 2000
        ):
            tables["subject_plate"] = dt
        elif (
            "SubjectIdentifier" in cols
            and "SubjectLocalIdentifier" in cols
            and len(dt.columns) <= 5
        ):
            tables["subject"] = dt
        elif (
            "MicroscopyImageIdentifier" in cols
            and "BacterialPlateIdentifier" in cols
            and len(dt) < 2000
        ):
            tables["ecoli_microscopy"] = dt
        elif "BacterialPatchBorderPeakFluorescenceIntensity" in cols:
            tables["ecoli_patch_analysis"] = dt
        elif "AgarPlatePouringTimestamp" in cols and "BacterialPatchRadius" not in cols:
            tables["ecoli_plate"] = dt

    # Encounter table = largest remaining C. elegans table
    assigned = {id(v) for v in tables.values()}
    remaining = [dt for dt in data_tables if id(dt) not in assigned]
    celegans_remaining = [
        dt
        for dt in remaining
        if "MicroscopyImageIdentifier" not in dt.columns
        and "AgarPlatePouringTimestamp" not in dt.columns
    ]
    if celegans_remaining:
        tables["encounter"] = max(celegans_remaining, key=len)
    # Exclusion = next largest
    assigned2 = {id(v) for v in tables.values()}
    celegans_remaining2 = [
        dt
        for dt in data_tables
        if id(dt) not in assigned2 and "MicroscopyImageIdentifier" not in dt.columns
    ]
    if celegans_remaining2:
        tables["exclusion"] = max(celegans_remaining2, key=len)

    # E. coli OD600 table = small table with BacterialOD600TargetAtSeeding
    for dt in remaining:
        if id(dt) not in {id(v) for v in tables.values()}:
            if "BacterialOD600TargetAtSeeding" in dt.columns and len(dt) < 200:
                tables["ecoli_od600"] = dt

    return tables


def _get_doc_uid(doc_props: dict) -> str:
    """Extract binary file UID from document properties."""
    fi = doc_props.get("files", {}).get("file_info", {})
    if isinstance(fi, dict):
        locs = fi.get("locations", {})
        return locs.get("uid", "") if isinstance(locs, dict) else ""
    return ""


# ---------------------------------------------------------------------------
# Section 11: Retrieve C. elegans subject behavior
# ---------------------------------------------------------------------------

SUBJECT_LOCAL_ID = "N2_0360_SingleDensityMultiPatch_220318@chalasani-lab.salk.edu"


@timed
def section_subject_behavior(
    html: HTMLBuilder,
    dataset: Any,
    subject_table: Any,
    behavior_plate_table: Any,
    data_tables: list,
) -> dict:
    """Section 11: Retrieve C. elegans subject behavior — choose a subject."""

    html.add_heading("Retrieve C. elegans subject behavior", level=3)
    html.add_text(
        "Now let's choose a subject and look at all of the information "
        "we have available in the dataset."
    )

    html.add_code("""\
# Choose a subject to view its behavior data and metadata
subject_local_id = 'N2_0360_SingleDensityMultiPatch_220318@chalasani-lab.salk.edu'""")

    tables = _identify_tables(data_tables)
    subject_plate_table = tables.get("subject_plate")

    # --- Get subject and bacterial plate metadata ---
    html.add_heading("Get subject and bacterial plate metadata", level=3)

    html.add_code("""\
# Get subject document id from subject_table
ind_subject = subject_table['SubjectLocalIdentifier'] == subject_local_id
subject_id = subject_table.loc[ind_subject, 'SubjectDocumentIdentifier'].iloc[0]

# Get plate IDs for this subject from the subject-plate mapping table
subject_plate_table = data_tables['subject_plate']  # OTR table with SubjectDocumentIdentifier + BacterialPlateIdentifier
ind_sp = subject_plate_table['SubjectDocumentIdentifier'] == subject_id
plate_doc_ids = subject_plate_table.loc[ind_sp, 'BacterialPlateDocumentIdentifier'].tolist()

# Find behavior plate row for this subject
for pid in plate_doc_ids:
    ind_bp = behavior_plate_table['BacterialPlateDocumentIdentifier'] == pid
    if ind_bp.any():
        behavior_plate_id = pid
        break

current_subject = subject_table[ind_subject]

# Find the subject_group containing this subject (needed for imageStack queries)
sg_docs = dataset.database_search(Query('').isa('subject_group'))
for sg_doc in sg_docs:
    deps = sg_doc.document_properties.get('depends_on', [])
    for d in deps:
        if d.get('value') == subject_id:
            subject_group_id = sg_doc.document_properties['base']['id']
            break""")

    # Execute
    ind_subject = subject_table["SubjectLocalIdentifier"] == SUBJECT_LOCAL_ID
    if not ind_subject.any():
        html.add_output_text(f"Subject {SUBJECT_LOCAL_ID} not found in subjectTable.")
        return {}

    subject_id = subject_table.loc[ind_subject, "SubjectDocumentIdentifier"].iloc[0]

    # currentSubject table
    current_subject = subject_table[ind_subject]
    html.add_table_html(
        df_to_html(current_subject, max_rows=5),
        f"currentSubject ({current_subject.shape[0]} x {current_subject.shape[1]} table)",
    )

    # Get plate IDs for this subject
    behavior_plate_id = ""
    if (
        subject_plate_table is not None
        and "BacterialPlateDocumentIdentifier" in subject_plate_table.columns
    ):
        ind_sp = subject_plate_table["SubjectDocumentIdentifier"] == subject_id
        plate_doc_ids = subject_plate_table.loc[ind_sp, "BacterialPlateDocumentIdentifier"].tolist()

        # Find cultivation and behavior plate rows
        tables.get("exclusion")  # cultivation table — used in MATLAB for plate rows
        # Build currentPlates from behavior_plate_table
        if (
            behavior_plate_table is not None
            and "BacterialPlateDocumentIdentifier" in behavior_plate_table.columns
        ):
            for pid in plate_doc_ids:
                ind_bp = behavior_plate_table["BacterialPlateDocumentIdentifier"] == pid
                if ind_bp.any():
                    behavior_plate_id = pid
                    break

        # Show currentPlates from behaviorPlateTable
        if behavior_plate_id:
            bp_row = behavior_plate_table[
                behavior_plate_table["BacterialPlateDocumentIdentifier"] == behavior_plate_id
            ].head(1)
            html.add_table_html(
                df_to_html(bp_row, max_rows=5),
                f"currentPlates — behavior plate (1 x {bp_row.shape[1]} table)",
            )
    else:
        plate_doc_ids = []

    # Find the subject_group containing this subject
    subject_group_id = ""
    from ndi.query import Query as _Q

    sg_docs = dataset.database_search(_Q("").isa("subject_group"))
    for sg_doc in sg_docs:
        sg_props = sg_doc.document_properties
        sg_deps = sg_props.get("depends_on", [])
        if isinstance(sg_deps, dict):
            sg_deps = [sg_deps]
        for d in sg_deps:
            if isinstance(d, dict) and d.get("value") == subject_id:
                subject_group_id = sg_props.get("base", {}).get("id", "")
                break
        if subject_group_id:
            break

    if subject_group_id:
        html.add_output_text(f"Subject group ID: {subject_group_id}")

    return {
        "subject_id": subject_id,
        "subject_group_id": subject_group_id,
        "behavior_plate_id": behavior_plate_id,
        "plate_doc_ids": plate_doc_ids,
        "tables": tables,
    }


def _get_vhsb_filename(epoch_doc: Any) -> str:
    """Get the VHSB binary filename from the document's file_info.

    Different datasets may use different names (e.g. ``timeseries.vhsb``
    vs ``epoch_binary_data.vhsb``).  This reads the actual name from
    the document rather than hardcoding it.
    """
    props = (
        epoch_doc.document_properties if hasattr(epoch_doc, "document_properties") else epoch_doc
    )
    fi = props.get("files", {}).get("file_info")
    if isinstance(fi, dict):
        name = fi.get("name", "")
        if name.endswith(".vhsb"):
            return name
    elif isinstance(fi, list):
        for f in fi:
            name = f.get("name", "")
            if name.endswith(".vhsb"):
                return name
    return "timeseries.vhsb"  # fallback


def _read_vhsb_from_doc(dataset: Any, epoch_doc: Any, t0: float = 0, t1: float = 3600) -> tuple:
    """Read VHSB timeseries via the session binary API.

    Uses ``database_openbinarydoc`` which fetches on demand via ndic://
    when credentials are available.  Returns ``(y_data, x_time)``.
    """
    try:
        sys.path.insert(0, "/tmp/vhlab-toolbox-python")
        from vlt.file.custom_file_formats import vhsb_read

        vhsb_name = _get_vhsb_filename(epoch_doc)
        fid = dataset.database_openbinarydoc(epoch_doc, vhsb_name)
        try:
            return vhsb_read(fid, t0, t1)
        finally:
            if hasattr(fid, "close"):
                fid.close()
    except FileNotFoundError:
        return None, None
    except Exception:
        return None, None


def _safe_depends_on_search(dataset: Any, type_query: Any, dep_name: str, dep_value: str) -> list:
    """Search with depends_on, falling back to manual filter on DID-python bug.

    Some documents have string entries in their ``depends_on`` array instead
    of ``{name, value}`` dicts.  DID-python's ``field_search`` crashes with
    ``AttributeError: 'str' object has no attribute 'get'`` when it encounters
    these.  Also, DID-python doesn't handle single-dict ``depends_on``
    (returns empty instead of matching), so we fall back to manual filtering
    when the query returns no results.
    """
    from ndi.query import Query

    try:
        q = type_query & Query("").depends_on(dep_name, dep_value)
        results = dataset.database_search(q)
        if results:
            return results
        # Query returned empty — may be due to single-dict depends_on;
        # fall through to manual search below.
    except (AttributeError, TypeError):
        pass

    all_docs = dataset.database_search(type_query)
    results = []
    for doc in all_docs:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        if not isinstance(props, dict):
            continue
        deps = props.get("depends_on", [])
        if isinstance(deps, dict):
            deps = [deps]
        for dep in deps:
            if (
                isinstance(dep, dict)
                and dep.get("name") == dep_name
                and dep.get("value") == dep_value
            ):
                results.append(doc)
                break
    return results


def _find_element_epoch_doc(dataset: Any, element_id: str) -> Any:
    """Find the element_epoch document for reading binary data.

    Returns the first element_epoch document that has a binary file
    reference, or ``None``.
    """
    from ndi.query import Query

    epoch_docs = _safe_depends_on_search(
        dataset, Query("").isa("element_epoch"), "element_id", element_id
    )

    for doc in epoch_docs:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        if isinstance(props, dict):
            uid = _get_doc_uid(props)
            if uid:
                return doc
    return None


@timed
def section_position_element(html: HTMLBuilder, dataset: Any, ctx: dict) -> dict:
    """Section 12: Get position of subject over time."""
    import pandas as pd

    from ndi.query import Query

    subject_id = ctx.get("subject_id", "")
    position_data = {}

    html.add_heading("Get position of subject over time", level=3)
    html.add_text(
        "In the NDI framework, an element is a physical (e.g. an instrument "
        "that takes a measurement or produces a stimulus) or inferred object "
        "(e.g. simulated data). In these experiments, there are 2 element "
        "types per subject — a position element and a distance element."
    )
    html.add_text(
        "Each subject is linked to a unique set of elements. The position "
        "elements in this dataset are connected to the X,Y coordinate "
        "location of each subject over time in the behavioral video "
        "recording. The distance elements are connected to the distance "
        "between each subject and the nearest bacterial patch edge."
    )

    html.add_code("""\
from ndi.query import Query

# Get the position element document (one per subject)
query_doc_type = Query('element.type') == 'position'
query_dependency = Query('').depends_on('subject_id', subject_id)
position_docs = dataset.database_search(query_doc_type & query_dependency)
pos_id = position_docs[0].document_properties['base']['id']

# Find the element_epoch document for this element
q_epoch = Query('').isa('element_epoch') & Query('').depends_on('element_id', pos_id)
epoch_docs = dataset.database_search(q_epoch)

# Read position timeseries via database binary API (fetches on demand via ndic://)
from vlt.file.custom_file_formats import vhsb_read
vhsb_name = epoch_docs[0].document_properties['files']['file_info']['name']
fid = dataset.database_openbinarydoc(epoch_docs[0], vhsb_name)
position, time = vhsb_read(fid, t0=0, t1=3600)
fid.close()
# position shape: (N, 2) — columns are [X, Y] coordinates in pixels""")

    try:
        q_type = Query("element.type") == "position"
        position_docs = _safe_depends_on_search(dataset, q_type, "subject_id", subject_id)
        if position_docs:
            pos_id = position_docs[0].document_properties.get("base", {}).get("id", "")

            # Read position timeseries via session binary API
            epoch_doc = _find_element_epoch_doc(dataset, pos_id)
            if epoch_doc is not None:
                y, x = _read_vhsb_from_doc(dataset, epoch_doc)
                if y is not None:
                    position_data["position"] = y
                    position_data["time"] = x
                    html.add_output_text(
                        f"Position element ID: {pos_id}\n"
                        f"Position data: {y.shape[0]} samples x {y.shape[1]} columns\n"
                        f"Time range: [{x.min():.2f}, {x.max():.2f}] seconds"
                    )

            # Get position_metadata
            meta_docs = _safe_depends_on_search(
                dataset, Query("").isa("position_metadata"), "element_id", pos_id
            )
            if meta_docs:
                pos_meta = meta_docs[0].document_properties.get("position_metadata", {})
                from ndi.ontology import lookup

                rows = []
                for field, val in sorted(pos_meta.items()):
                    if not val or not isinstance(val, str):
                        continue
                    term_ids = [t.strip() for t in val.split(",") if t.strip()]
                    for tid in term_ids:
                        try:
                            info = lookup(tid)
                            rows.append(
                                {
                                    "field": field,
                                    "id": info.id,
                                    "name": info.name,
                                    "definition": info.definition[:80] if info.definition else "",
                                    "shortName": info.short_name,
                                }
                            )
                        except Exception:
                            rows.append(
                                {
                                    "field": field,
                                    "id": tid,
                                    "name": "",
                                    "definition": "",
                                    "shortName": "",
                                }
                            )

                if rows:
                    meta_df = pd.DataFrame(rows)
                    html.add_table_html(
                        df_to_html(meta_df, max_rows=20, show_shape=False),
                        f"positionMetadata ({len(meta_df)} x {len(meta_df.columns)} table)",
                    )
        else:
            html.add_output_text("No position element found for this subject.")
    except Exception as e:
        html.add_output_text(f"Position element query: {e}")

    return position_data


@timed
def section_image_metadata(html: HTMLBuilder, dataset: Any, ctx: dict) -> dict:
    """Section 13: Get associated video and image metadata."""
    import pandas as pd

    from ndi.query import Query

    subject_group_id = ctx.get("subject_group_id", "")

    html.add_heading("Get associated video and image metadata", level=3)
    html.add_text(
        "An additional document type known as imageStack contains an image "
        "or video and its relevant metadata associated with the behavioral "
        "video recordings. ontologyLabel documents are used to add relevant "
        "ontology-linked labels to each file."
    )

    html.add_code("""\
# Query imageStack documents linked to the subject's group
query_type = Query('').isa('imageStack')
query_dep = Query('').depends_on('subject_id', subject_group_id)
image_stack_docs = dataset.database_search(query_type & query_dep)

# Query ontologyLabel documents for each imageStack
for doc in image_stack_docs:
    doc_id = doc.document_properties['base']['id']
    label_query = Query('').isa('ontologyLabel') & Query('').depends_on('document_id', doc_id)
    label_docs = dataset.database_search(label_query)
    # ... look up ontology term for each label""")

    image_params_list = []
    image_doc_map = {}

    try:
        q_type = Query("").isa("imageStack")
        image_stack_docs = (
            _safe_depends_on_search(dataset, q_type, "subject_id", subject_group_id)
            if subject_group_id
            else []
        )

        for doc in image_stack_docs:
            props = doc.document_properties if hasattr(doc, "document_properties") else doc
            if not isinstance(props, dict):
                continue
            doc_id = props.get("base", {}).get("id", "")
            is_params = props.get("imageStack_parameters", {})
            is_info = props.get("imageStack", {})
            uid = _get_doc_uid(props)

            # Look up ontology label via depends_on query
            ontology_node = ""
            try:
                label_matches = _safe_depends_on_search(
                    dataset, Query("").isa("ontologyLabel"), "document_id", doc_id
                )
                if label_matches:
                    label_data = label_matches[0].document_properties.get("ontologyLabel", {})
                    ontology_node = label_data.get("ontologyNode", "")
            except Exception:
                pass

            # Use imageStack.label as the display name (descriptive text)
            label = is_info.get("label", "")

            # Determine format from formatOntology
            fmt_ontology = is_info.get("formatOntology", "")
            fmt = fmt_ontology  # Use raw ontology ID as fallback

            row = {
                "ontologyNode": ontology_node,
                "label": label[:80],
                "format": fmt,
                "data_type": is_params.get("data_type", ""),
                "dimension_size": str(is_params.get("dimension_size", [])),
                "dimension_order": is_params.get("dimension_order", ""),
            }
            image_params_list.append(row)
            # Use label text as key for image lookup
            image_doc_map[label] = {"doc": doc, "uid": uid, "doc_id": doc_id, "props": props}

        if image_params_list:
            params_df = pd.DataFrame(image_params_list)
            html.add_table_html(
                df_to_html(params_df, max_rows=20, show_shape=False),
                f"imageStackParameters ({len(params_df)} x {len(params_df.columns)} table)",
            )
            html.add_output_text(
                f"Found {len(image_stack_docs)} imageStack documents for this subject"
            )
        else:
            html.add_output_text("No imageStack documents found for this subject.")

    except Exception as e:
        html.add_output_text(f"Image metadata query: {e}")

    return image_doc_map


@timed
def section_plot_image_with_position(
    html: HTMLBuilder, dataset: Any, image_doc_map: dict, position_data: dict
) -> None:
    """Section 14: Plot an image/mask with subject position."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    html.add_heading("Plot an image/mask with subject position", level=3)

    html.add_code("""\
import numpy as np
from ndi.fun.data import read_image_stack

# Choose an image type: the patch identifier map
# (where each pixel's value = identifier of the closest bacterial patch)
image_name = 'identifier map'  # keyword to match in imageStack labels
doc_info = image_doc_map[image_name]

# Read image via the database binary API (auto-detects PNG/TIFF/raw binary)
# Binary files are fetched on demand from NDI Cloud via ndic:// protocol
img, info = read_image_stack(dataset, doc_info['doc'], 'auto')

# Normalize to [0, 1] for display (equivalent to MATLAB mat2gray)
img_float = img.astype(np.float64)
img_float = (img_float - img_float.min()) / (img_float.max() - img_float.min())

# Plot image with position track colored by time (jet colormap)
fig, ax = plt.subplots(figsize=(10, 10))
ax.imshow(np.flipud(img_float), cmap='gray', origin='lower',
          extent=[0, img.shape[1], 0, img.shape[0]])

n_bins = 60
bins = np.linspace(time.min(), time.max(), n_bins)
cmap = plt.cm.jet
for j in range(n_bins - 1):
    ind = (time >= bins[j]) & (time <= bins[j + 1])
    ax.plot(position[ind, 0], position[ind, 1],
            color=cmap(j / (n_bins - 1)), linewidth=1)""")

    # Find the identifier map image by label keyword
    target_name = "identifier map"
    img_info = None
    for name, info in image_doc_map.items():
        if "identifier" in name.lower() and "map" in name.lower():
            img_info = info
            target_name = name
            break

    if not img_info or not img_info.get("doc"):
        html.add_output_text(f"Image '{target_name}' not found or no binary file available.")
        return

    try:
        from ndi.fun.data import read_image_stack

        img, _info = read_image_stack(dataset, img_info["doc"], "auto")
    except FileNotFoundError:
        html.add_output_text(
            "Binary file not available. Set NDI_CLOUD_USERNAME/PASSWORD "
            "to fetch on demand from NDI Cloud."
        )
        return
    except Exception as e:
        html.add_output_text(f"Could not decode image data: {e}")
        return

    # Normalize to [0, 1]
    img_float = img.astype(np.float64)
    vmin, vmax = np.nanmin(img_float), np.nanmax(img_float)
    if vmax > vmin:
        img_float = (img_float - vmin) / (vmax - vmin)

    fig, ax = plt.subplots(figsize=(10, 10))
    ax.imshow(
        np.flipud(img_float), cmap="gray", origin="lower", extent=[0, img.shape[1], 0, img.shape[0]]
    )

    # Overlay position trajectory colored by time (matching MATLAB jet colormap)
    position = position_data.get("position")
    time_arr = position_data.get("time")
    if position is not None and time_arr is not None:
        valid = ~np.isnan(position[:, 0]) & ~np.isnan(position[:, 1])
        pos = position[valid]
        t = time_arr[valid]
        n_bins = 60
        bins = np.linspace(t.min(), t.max(), n_bins)
        cmap = plt.cm.jet
        for j in range(n_bins - 1):
            ind = (t >= bins[j]) & (t <= bins[j + 1])
            if ind.any():
                color = cmap(j / (n_bins - 1))
                ax.plot(pos[ind, 0], pos[ind, 1], color=color, linewidth=1)

    ax.set_xlim(0, img.shape[1])
    ax.set_ylim(0, img.shape[0])
    ax.set_xticks([])
    ax.set_yticks([])
    plt.tight_layout()
    html.add_image_base64(fig_to_bytes(), caption=f"Image: {target_name} with position track")


@timed
def section_play_video(html: HTMLBuilder, dataset: Any, image_doc_map: dict) -> None:
    """Section 15: Play video of the subject (show frame sequence)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    html.add_heading("Play video of the subject", level=3)

    html.add_code("""\
import cv2
from ndi.fun.data import read_image_stack

# Get the video recording from imageStack documents
image_name = 'video recording'  # keyword to match in imageStack labels
doc_info = image_doc_map[image_name]

# Read video via the database binary API (fetches on demand via ndic://)
video_data, info = read_image_stack(dataset, doc_info['doc'], 'mp4')

# Get time scale from imageStack_parameters.dimension_scale
is_params = doc_info['props']['imageStack_parameters']
time_per_frame = is_params['dimension_scale'][2]  # seconds per frame

total_frames = info['num_frames']
frame_indices = [int(i * total_frames / 8) for i in range(8)]

fig, axes = plt.subplots(2, 4, figsize=(16, 8))
for ax, fi in zip(axes.flat, frame_indices):
    frame = video_data[fi]
    ax.imshow(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cmap='gray')
    ax.set_title(f't = {fi * time_per_frame:.1f}s')
    ax.axis('off')""")

    try:
        import cv2
    except ImportError:
        html.add_output_text("OpenCV not available — skipping video display.")
        return

    # Find video by label keyword
    target_name = "video recording"
    vid_info = None
    for name, info in image_doc_map.items():
        if "video" in name.lower() and "recording" in name.lower():
            vid_info = info
            target_name = name
            break

    if not vid_info or not vid_info.get("doc"):
        html.add_output_text(f"Video '{target_name}' not found.")
        return

    # Get the video file path via database_openbinarydoc (triggers ndic:// fetch)
    try:
        fid = dataset.database_openbinarydoc(vid_info["doc"], "imageStack")
        filepath = fid.name
        fid.close()
    except FileNotFoundError:
        html.add_output_text(
            "Video file not available. Set NDI_CLOUD_USERNAME/PASSWORD "
            "to fetch on demand from NDI Cloud."
        )
        return

    props = vid_info.get("props", {})
    is_params = props.get("imageStack_parameters", {})
    dim_scale = is_params.get("dimension_scale", [1, 1, 1])
    time_per_frame = dim_scale[2] if len(dim_scale) > 2 else 1.0

    cap = cv2.VideoCapture(str(filepath))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if total_frames < 8:
        cap.release()
        html.add_output_text(f"Video too short: {total_frames} frames")
        return

    frame_indices = [int(i * total_frames / 8) for i in range(8)]

    fig, axes = plt.subplots(2, 4, figsize=(16, 8))
    for ax, fi in zip(axes.flat, frame_indices):
        cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
        ret, frame = cap.read()
        if ret:
            frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            ax.imshow(frame_gray, cmap="gray")
            time_sec = fi * time_per_frame
            ax.set_title(f"t = {time_sec:.1f}s", fontsize=9)
        ax.axis("off")

    cap.release()
    plt.suptitle(f"Video: {target_name}", fontsize=12)
    plt.tight_layout()
    html.add_image_base64(
        fig_to_bytes(), caption="8 evenly-spaced frames from C. elegans behavioral video"
    )


@timed
def section_distance_element(html: HTMLBuilder, dataset: Any, ctx: dict) -> None:
    """Section 16: Get distance to patch edge over time."""
    import pandas as pd

    from ndi.query import Query

    subject_id = ctx.get("subject_id", "")

    html.add_heading("Get distance to patch edge over time", level=3)
    html.add_text(
        "Now let's take a look at the distance element timeseries and its "
        "associated metadata. Each position element is associated with a "
        "distance_metadata which specifies what the distance timeseries is "
        "tracking along with the relevant ontology references and units."
    )

    html.add_code("""\
from ndi.query import Query

# Get the distance element document (one per subject)
query_type = Query('element.type') == 'distance'
query_dep = Query('').depends_on('subject_id', subject_id)
distance_docs = dataset.database_search(query_type & query_dep)
dist_id = distance_docs[0].document_properties['base']['id']

# Find the element_epoch document for this element
q_epoch = Query('').isa('element_epoch') & Query('').depends_on('element_id', dist_id)
epoch_docs = dataset.database_search(q_epoch)
epoch_doc = epoch_docs[0]

# Read distance timeseries via the session binary API
# Binary files are fetched on demand from NDI Cloud via ndic:// protocol
from vlt.file.custom_file_formats import vhsb_read
vhsb_name = epoch_doc.document_properties['files']['file_info']['name']
fid = dataset.database_openbinarydoc(epoch_doc, vhsb_name)
distance, time = vhsb_read(fid, t0=0, t1=3600)
fid.close()
# distance shape: (N, 3) — col 0: distance to patch edge (pixels),
#                           col 1: on-patch flag, col 2: closest patch number""")

    try:
        q_type = Query("element.type") == "distance"
        distance_docs = _safe_depends_on_search(dataset, q_type, "subject_id", subject_id)

        if distance_docs:
            dist_id = distance_docs[0].document_properties.get("base", {}).get("id", "")

            # Read distance timeseries via session binary API
            epoch_doc = _find_element_epoch_doc(dataset, dist_id)
            distance_y = None
            distance_t = None
            if epoch_doc is not None:
                distance_y, distance_t = _read_vhsb_from_doc(dataset, epoch_doc)
                if distance_y is not None:
                    html.add_output_text(
                        f"Distance element ID: {dist_id}\n"
                        f"Distance data: {distance_y.shape[0]} samples x {distance_y.shape[1]} columns\n"
                        f"Time range: [{distance_t.min():.2f}, {distance_t.max():.2f}] seconds"
                    )
                else:
                    html.add_output_text(
                        f"Distance element ID: {dist_id}\n"
                        "Could not read VHSB data (set NDI_CLOUD_USERNAME/PASSWORD "
                        "to fetch on demand)"
                    )
            else:
                html.add_output_text(
                    f"Distance element ID: {dist_id}\n" "No element_epoch binary file found"
                )

            # Get distance_metadata
            meta_docs = _safe_depends_on_search(
                dataset, Query("").isa("distance_metadata"), "element_id", dist_id
            )

            if meta_docs:
                dist_meta = meta_docs[0].document_properties.get("distance_metadata", {})
                from ndi.ontology import lookup

                rows = []
                for field, val in sorted(dist_meta.items()):
                    if not val or not isinstance(val, str):
                        continue
                    if "ontologyNode" not in field and "unit" not in field:
                        continue
                    term_ids = [t.strip() for t in val.split(",") if t.strip()]
                    for tid in term_ids:
                        try:
                            info = lookup(tid)
                            rows.append(
                                {
                                    "field": field,
                                    "id": info.id,
                                    "name": info.name,
                                    "definition": info.definition[:80] if info.definition else "",
                                    "shortName": info.short_name,
                                }
                            )
                        except Exception:
                            rows.append(
                                {
                                    "field": field,
                                    "id": tid,
                                    "name": "",
                                    "definition": "",
                                    "shortName": "",
                                }
                            )

                if rows:
                    meta_df = pd.DataFrame(rows)
                    html.add_table_html(
                        df_to_html(meta_df, max_rows=20, show_shape=False),
                        f"distanceMetadata ({len(meta_df)} x {len(meta_df.columns)} table)",
                    )

                # Show integer-to-label mapping
                for key in ["integerIDs_A", "integerIDs_B"]:
                    if key in dist_meta:
                        ids = dist_meta[key]
                        str_key = key.replace("integerIDs", "ontologyStringValues")
                        str_vals = dist_meta.get(str_key, "")
                        if str_vals:
                            labels = str_vals.split(",")
                            if isinstance(ids, list):
                                map_rows = [
                                    {"ObjectNum": idx, "label": lbl.strip()}
                                    for idx, lbl in zip(ids, labels)
                                ]
                                map_df = pd.DataFrame(map_rows)
                                suffix = key.split("_")[-1]
                                html.add_table_html(
                                    df_to_html(map_df, max_rows=20, show_shape=False),
                                    f"distanceMap_{suffix}",
                                )

            # --- Plot distance timeseries (matching MATLAB Image 3) ---
            if distance_y is not None and distance_t is not None:
                import matplotlib

                matplotlib.use("Agg")
                import matplotlib.pyplot as plt
                import numpy as np

                html.add_heading("Plot distance to nearest patch edge", level=3)

                fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

                # Subplot 1: distance colored by time (jet colormap)
                dist_vals = distance_y[:, 0]  # column 0 = distance to patch edge
                t = distance_t.flatten() if distance_t.ndim > 1 else distance_t
                n_bins = 60
                bins = np.linspace(t.min(), t.max(), n_bins)
                cmap = plt.cm.jet
                for j in range(n_bins - 1):
                    ind = (t >= bins[j]) & (t <= bins[j + 1])
                    if ind.any():
                        color = cmap(j / (n_bins - 1))
                        ax1.plot(t[ind], dist_vals[ind], color=color, linewidth=0.5)
                ax1.set_ylabel("Distance to nearest patch edge (pixels)")
                ax1.axhline(y=0, color="k", linewidth=0.5, linestyle="--")
                ax1.set_title("Distance to nearest bacterial patch edge")

                # Subplot 2: closest patch number over time
                if distance_y.shape[1] >= 3:
                    closest_patch = distance_y[:, 2]  # column 2 = closest patch #
                    ax2.plot(t, closest_patch, color="steelblue", linewidth=0.5)
                    ax2.set_ylabel("Closest patch number")
                    ax2.set_xlabel("Time (s)")
                    ax2.set_title("Closest bacterial patch over time")
                else:
                    ax2.set_xlabel("Time (s)")

                plt.tight_layout()
                html.add_image_base64(
                    fig_to_bytes(),
                    caption="Distance to nearest bacterial patch edge and closest patch number",
                )
        else:
            html.add_output_text("No distance element found for this subject.")
    except Exception as e:
        html.add_output_text(f"Distance element query: {e}")


@timed
def section_encounter_per_subject(html: HTMLBuilder, data_tables: list, ctx: dict) -> None:
    """Section 17: Get analysis of patch encounters for the chosen subject."""
    from ndi.fun.table import identify_matching_rows

    subject_id = ctx.get("subject_id", "")
    tables = ctx.get("tables", {})
    encounter_table = tables.get("encounter")

    html.add_heading("Get analysis of patch encounters", level=3)
    html.add_text(
        "Finally, let's view the analysis of patch encounters for this "
        "subject. This data is stored in ontologyTableRow documents."
    )

    html.add_code("""\
from ndi.fun.table import identify_matching_rows

# The encounter table is the largest ontologyTableRow group
# (contains C. elegans encounter behavior data with ~20K rows)
encounter_table = data_tables[0]  # largest group by row count

# Filter to encounters for this subject
ind = identify_matching_rows(
    encounter_table, 'SubjectDocumentIdentifier', subject_id)
current_encounters = encounter_table[ind]
print(f'currentEncounters: {current_encounters.shape}')""")

    if encounter_table is None:
        html.add_output_text("Encounter table not identified.")
        return

    if "SubjectDocumentIdentifier" not in encounter_table.columns:
        html.add_output_text(
            f"Encounter table ({encounter_table.shape}) does not have "
            "SubjectDocumentIdentifier column.\n"
            f"Columns: {list(encounter_table.columns)}"
        )
        return

    ind = identify_matching_rows(encounter_table, "SubjectDocumentIdentifier", subject_id)
    current_encounters = encounter_table[ind]

    html.add_output_text(
        f"currentEncounters: {current_encounters.shape[0]} rows x "
        f"{current_encounters.shape[1]} columns"
    )
    html.add_table_html(
        df_to_html(current_encounters, max_rows=20),
        f"currentEncounters ({current_encounters.shape[0]} x {current_encounters.shape[1]} table)",
    )


# ---------------------------------------------------------------------------
# E. coli sections
# ---------------------------------------------------------------------------


@timed
def section_ecoli_intro(html: HTMLBuilder) -> None:
    """Section 18: View E. coli dataset."""
    html.add_heading("View E. coli dataset")
    html.add_text("Now let's switch over to the E. coli dataset.")


@timed
def section_ecoli_strains(html: HTMLBuilder, dataset: Any) -> Any:
    """Section 19: View strains."""
    import pandas as pd

    from ndi.query import Query

    html.add_heading("View strains", level=3)
    html.add_text(
        "Let's look at the E. coli strain information. This is stored "
        "in openminds documents (Strain, Species, GeneticStrainType)."
    )

    html.add_code("""\
from ndi.query import Query

# Get openminds documents and find E. coli strains
om_docs = dataset.database_search(Query('').isa('openminds'))

# Filter to E. coli strains (OP50 and OP50-GFP)
ecoli_strains = []
for doc in om_docs:
    om = doc.document_properties.get('openminds', {})
    om_type = om.get('openminds_type', '').rsplit('/', 1)[-1]
    if om_type == 'Strain':
        name = om.get('fields', {}).get('name', '')
        if 'coli' in name.lower() or 'OP50' in name:
            ecoli_strains.append(doc)""")

    om_docs = dataset.database_search(Query("").isa("openminds"))

    # Index all openminds docs by ID for cross-referencing
    om_by_id: dict[str, dict] = {}
    for doc in om_docs:
        props = doc.document_properties
        doc_id = props.get("base", {}).get("id", "")
        # Handle ndi:// prefix in references
        om_by_id[doc_id] = props.get("openminds", {}).get("fields", {})
        om_by_id[f"ndi://{doc_id}"] = props.get("openminds", {}).get("fields", {})

    strain_rows = []
    for doc in om_docs:
        props = doc.document_properties
        om = props.get("openminds", {})
        om_type = om.get("openminds_type", "").rsplit("/", 1)[-1]
        if om_type != "Strain":
            continue
        fields = om.get("fields", {})
        name = fields.get("name", "")
        if "coli" not in name.lower() and "OP50" not in name:
            continue

        row = {
            "StrainName": name,
            "StrainOntology": fields.get("ontologyIdentifier", ""),
        }

        # Resolve background strain
        bg_refs = fields.get("backgroundStrain", [])
        bg_name = ""
        if bg_refs and isinstance(bg_refs, list):
            bg_fields = om_by_id.get(bg_refs[0], {})
            bg_name = bg_fields.get("name", "")
        row["BackgroundStrainName"] = bg_name

        # Resolve genetic strain type
        gst_refs = fields.get("geneticStrainType", [])
        gst_name = ""
        if gst_refs and isinstance(gst_refs, list):
            gst_fields = om_by_id.get(gst_refs[0], {})
            gst_name = gst_fields.get("name", "")
        row["GeneticStrainTypeName"] = gst_name

        # Resolve species
        species_refs = fields.get("species", [])
        species_name = ""
        species_ontology = ""
        if species_refs and isinstance(species_refs, list):
            sp_fields = om_by_id.get(species_refs[0], {})
            species_name = sp_fields.get("name", "")
            species_ontology = sp_fields.get("preferredOntologyIdentifier", "")
        row["SpeciesName"] = species_name
        row["SpeciesOntology"] = species_ontology

        doc_id = props.get("base", {}).get("id", "")
        row["BacterialStrainDocumentIdentifier"] = doc_id
        strain_rows.append(row)

    if strain_rows:
        # Deduplicate by StrainName
        seen = set()
        unique_rows = []
        for r in strain_rows:
            key = r["StrainName"]
            if key not in seen:
                seen.add(key)
                unique_rows.append(r)

        # Remove strains that appear only as background strains of other
        # strains (matches MATLAB "encompassing document" filtering logic).
        bg_names = {r["BackgroundStrainName"] for r in unique_rows if r.get("BackgroundStrainName")}
        unique_rows = [r for r in unique_rows if r["StrainName"] not in bg_names]

        strain_table = pd.DataFrame(unique_rows)
        html.add_table_html(
            df_to_html(strain_table, max_rows=10),
            f"strainTable ({strain_table.shape[0]} x {strain_table.shape[1]} table)",
        )
        return strain_table
    else:
        html.add_output_text("No E. coli strain information found.")
        return pd.DataFrame()


@timed
def section_ecoli_metadata(html: HTMLBuilder, data_tables: list, strain_table: Any) -> Any:
    """Section 20: Retrieve experiment metadata (E. coli)."""

    from ndi.fun.table import join

    tables = _identify_tables(data_tables)

    html.add_heading("Retrieve experiment metadata", level=3)
    html.add_text(
        "The E. coli dataset has 3 different data tables which store "
        "information related to the 1) bacterial plates, 2) microscopy "
        "images, 3) analysis of patches in each image. Let's combine "
        "all of the data into a big table with one row per patch per "
        "time point and add the relevant strain information."
    )

    html.add_code("""\
from ndi.fun.table import join

# Identify the E. coli ontologyTableRow tables by their column signatures:
#   ecoli_patch_analysis: has BacterialPatchBorderPeakFluorescenceIntensity
#   ecoli_microscopy: has MicroscopyImageIdentifier + BacterialPlateIdentifier (< 2000 rows)
#   ecoli_plate: has AgarPlatePouringTimestamp

# Join all E. coli tables on common columns (BacterialPlateIdentifier, etc.)
# Also join with strain_table to add strain metadata
bacteria_table = join([ecoli_patch_analysis, ecoli_microscopy, ecoli_plate, strain_table])
print(f'bacteriaTable: {bacteria_table.shape}')""")

    ecoli_microscopy = tables.get("ecoli_microscopy")
    ecoli_patch = tables.get("ecoli_patch_analysis")
    ecoli_plate = tables.get("ecoli_plate")

    # Join: patch analysis + microscopy (on MicroscopyImageIdentifier)
    #        + plate metadata (on BacterialPlateIdentifier)
    #        + strain info (on BacterialStrainDocumentIdentifier)
    join_tables = []
    if ecoli_patch is not None:
        join_tables.append(ecoli_patch)
    if ecoli_microscopy is not None:
        join_tables.append(ecoli_microscopy)
    if ecoli_plate is not None:
        join_tables.append(ecoli_plate)
    if strain_table is not None and len(strain_table) > 0:
        join_tables.append(strain_table)

    if len(join_tables) >= 2:
        bacteria_table = join(join_tables)
        html.add_output_text(
            f"bacteriaTable: {bacteria_table.shape[0]} rows x " f"{bacteria_table.shape[1]} columns"
        )
        html.add_table_html(
            df_to_html(bacteria_table, max_rows=20),
            f"bacteriaTable ({bacteria_table.shape[0]} x {bacteria_table.shape[1]} table)",
        )
        return bacteria_table
    else:
        html.add_output_text("Could not identify sufficient E. coli tables to join.")
        return None


@timed
def section_ecoli_image_metadata(html: HTMLBuilder, dataset: Any, bacteria_table: Any) -> dict:
    """Section 21: Get microscopy image metadata (E. coli)."""
    import pandas as pd

    from ndi.query import Query

    html.add_heading("Get microscopy image metadata", level=3)
    html.add_text(
        "We also have imageStack documents which contain images and their " "relevant metadata."
    )

    html.add_code("""\
from ndi.query import Query

# Choose a microscopy image to view
image_id = '0101'
ind_image = bacteria_table['MicroscopyImageIdentifier'].astype(str) == image_id
image_doc_id = bacteria_table.loc[ind_image, 'ImageDocumentIdentifier'].iloc[0]

# Query imageStack documents for this image
query_type = Query('').isa('imageStack')
query_dep = Query('').depends_on('document_id', image_doc_id)
image_stack_docs = dataset.database_search(query_type & query_dep)

# Get image parameters and ontology labels
for doc in image_stack_docs:
    props = doc.document_properties
    is_params = props.get('imageStack_parameters', {})
    label = props.get('imageStack', {}).get('label', '')
    print(f'{label}: {is_params.get("data_type")} {is_params.get("dimension_size")}')""")

    image_doc_map = {}
    if bacteria_table is None or len(bacteria_table) == 0:
        html.add_output_text("bacteriaTable not available for E. coli image lookup.")
        return image_doc_map

    # Find a specific microscopy image
    image_id = "0101"
    image_doc_id = ""
    if (
        "ImageDocumentIdentifier" in bacteria_table.columns
        and "MicroscopyImageIdentifier" in bacteria_table.columns
    ):
        ind = bacteria_table["MicroscopyImageIdentifier"].astype(str) == image_id
        if ind.any():
            image_doc_id = str(bacteria_table.loc[ind, "ImageDocumentIdentifier"].iloc[0])
            html.add_output_text(
                f"Selected MicroscopyImageIdentifier = {image_id}\n"
                f"ImageDocumentIdentifier = {image_doc_id}"
            )
    elif "MicroscopyImageIdentifier" not in bacteria_table.columns:
        html.add_output_text("MicroscopyImageIdentifier column not found in bacteriaTable.")
    else:
        html.add_output_text("ImageDocumentIdentifier column not found in bacteriaTable.")

    try:
        if image_doc_id:
            is_docs = _safe_depends_on_search(
                dataset, Query("").isa("imageStack"), "document_id", image_doc_id
            )
        else:
            is_docs = []

        rows = []
        for doc in is_docs:
            props = doc.document_properties if hasattr(doc, "document_properties") else doc
            if not isinstance(props, dict):
                continue
            doc_id = props.get("base", {}).get("id", "")
            is_params = props.get("imageStack_parameters", {})
            is_info = props.get("imageStack", {})
            uid = _get_doc_uid(props)
            label = is_info.get("label", "")

            rows.append(
                {
                    "label": label[:80],
                    "data_type": is_params.get("data_type", ""),
                    "dimension_size": str(is_params.get("dimension_size", [])),
                    "format": is_info.get("formatOntology", ""),
                }
            )
            image_doc_map[label] = {"doc": doc, "uid": uid, "doc_id": doc_id, "props": props}

        if rows:
            params_df = pd.DataFrame(rows)
            html.add_table_html(
                df_to_html(params_df, max_rows=20, show_shape=False),
                f"imageStackParameters ({len(params_df)} x {len(params_df.columns)} table)",
            )
            html.add_output_text(
                f"Found {len(is_docs)} imageStack documents for this microscopy image"
            )
        else:
            html.add_output_text("No E. coli imageStack documents found.")
    except Exception as e:
        html.add_output_text(f"E. coli image metadata query: {e}")

    return image_doc_map


@timed
def section_ecoli_plot_image(
    html: HTMLBuilder, dataset: Any, ecoli_image_map: dict, bacteria_table: Any
) -> None:
    """Section 22: Plot an image or mask (E. coli)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    html.add_heading("Plot an image or mask", level=3)

    html.add_code("""\
import numpy as np
from ndi.fun.data import read_image_stack

# Choose a fluorescence image (prefer normalized)
for name, info in ecoli_image_map.items():
    if 'fluorescence' in name.lower():
        image_name = name
        doc_info = info
        break

# Read image via the database binary API (auto-detects PNG/TIFF/raw binary)
# Binary files are fetched on demand from NDI Cloud via ndic:// protocol
img, info = read_image_stack(dataset, doc_info['doc'], 'auto')

# Plot with colorbar and metadata title
fig, ax = plt.subplots(figsize=(8, 8))
im = ax.imshow(img, cmap='gray')
plt.colorbar(im, ax=ax, fraction=0.046)

# Add metadata from bacteriaTable
od600 = bacteria_table['BacterialOD600TargetAtSeeding'].iloc[0]
growth = bacteria_table['BacteriaGrowthDurationAfterSeeding'].iloc[0]
ax.set_title(f'{image_name}\\ntarget OD600 at seeding = {od600}\\ngrowth time = {growth}h')""")

    # Find the fluorescence image by label keyword
    target_name = "fluorescence"
    img_info = None
    # Prefer normalized fluorescence
    for name, info in ecoli_image_map.items():
        if "fluorescence" in name.lower() and "normalized" in name.lower():
            img_info = info
            target_name = name
            break
    if not img_info:
        for name, info in ecoli_image_map.items():
            if "fluorescence" in name.lower():
                img_info = info
                target_name = name
                break
    if not img_info and ecoli_image_map:
        # Just use the first available image
        target_name = next(iter(ecoli_image_map))
        img_info = ecoli_image_map[target_name]

    if not img_info or not img_info.get("doc"):
        html.add_output_text(f"Image '{target_name}' not found or no binary file available.")
        return

    try:
        from ndi.fun.data import read_image_stack

        img, _info = read_image_stack(dataset, img_info["doc"], "auto")
    except FileNotFoundError:
        html.add_output_text(
            "Binary file not available. Set NDI_CLOUD_USERNAME/PASSWORD "
            "to fetch on demand from NDI Cloud."
        )
        return
    except Exception as e:
        html.add_output_text(f"Could not decode E. coli image data: {e}")
        return

    if img is not None:
        fig, ax = plt.subplots(figsize=(8, 8))
        im = ax.imshow(img, cmap="gray")
        plt.colorbar(im, ax=ax, fraction=0.046)

        # Add metadata title if available
        title_parts = [target_name]
        if bacteria_table is not None:
            try:
                if "BacterialOD600TargetAtSeeding" in bacteria_table.columns:
                    od600 = bacteria_table["BacterialOD600TargetAtSeeding"].iloc[0]
                    title_parts.append(f"target OD600 at seeding = {od600}")
                if "BacteriaGrowthDurationAfterSeeding" in bacteria_table.columns:
                    growth = bacteria_table["BacteriaGrowthDurationAfterSeeding"].iloc[0]
                    title_parts.append(f"growth time = {growth}h")
            except Exception:
                pass

        ax.set_title("\n".join(title_parts), fontsize=11)
        ax.set_xticks([])
        ax.set_yticks([])
        plt.tight_layout()
        html.add_image_base64(fig_to_bytes(), caption=f"E. coli fluorescence image: {target_name}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print("=" * 70)
    print("NDI Dataset Tutorial: C. elegans Behavior & E. coli Fluorescence")
    print(f"Dataset: {CLOUD_DATASET_ID}")
    print("=" * 70)

    html = HTMLBuilder("NDI Dataset Tutorial: C. elegans Behavior & E. coli Fluorescence Imaging")

    # Section 1: Import
    print("\n[1/18] Import dataset configuration...")
    section_import(html)

    # Section 2: Load dataset
    print("[2/18] Loading dataset...")
    dataset = section_load_dataset(html)

    # Section 3: Sessions
    print("[3/18] Retrieving sessions...")
    section_sessions(html, dataset)

    # Section 4: Document types
    print("[4/18] Viewing document types...")
    doc_types, doc_counts = section_doc_types(html, dataset)

    html.add_separator()

    # Section 5: Ontology terms
    print("[5/18] Viewing ontology term definitions...")
    section_ontology_terms(html, dataset)

    html.add_separator()

    # Section 6-7: Retrieve metadata (C. elegans)
    print("[6/18] Retrieving experiment metadata (ontologyTableRow tables)...")
    data_tables, doc_ids = section_retrieve_metadata(html, dataset)

    # Section 8: Subject summary
    print("[7/18] Building subject summary table...")
    subject_table = section_subject_summary(html, dataset, data_tables)

    # Section 9: Filter subjects
    print("[8/18] Filtering subjects...")
    section_filter_subjects(html, subject_table)

    # Section 10: Behavior plate
    print("[9/18] Building behavior plate table...")
    behavior_plate = section_behavior_plate(html, data_tables)

    html.add_separator()

    # Section 11: Retrieve C. elegans subject behavior
    print("[10/18] Retrieving C. elegans subject behavior...")
    ctx = section_subject_behavior(html, dataset, subject_table, behavior_plate, data_tables)

    # Section 12: Get position of subject over time
    print("[11/18] Getting position element metadata...")
    position_data = section_position_element(html, dataset, ctx)

    # Section 13: Get associated video and image metadata
    print("[12/18] Getting image/video metadata...")
    image_doc_map = section_image_metadata(html, dataset, ctx)

    # Section 14: Plot an image/mask with subject position
    print("[13/18] Plotting image with position overlay...")
    section_plot_image_with_position(html, dataset, image_doc_map, position_data)

    # Section 15: Play video of the subject
    print("[14/18] Showing video frame sequence...")
    section_play_video(html, dataset, image_doc_map)

    # Section 16: Get distance to patch edge over time
    print("[15/18] Getting distance element metadata...")
    section_distance_element(html, dataset, ctx)

    # Section 17: Get analysis of patch encounters
    print("[16/18] Getting encounter analysis for subject...")
    section_encounter_per_subject(html, data_tables, ctx)

    html.add_separator()

    # Section 18: View E. coli dataset
    print("[17/18] E. coli dataset...")
    section_ecoli_intro(html)

    # Section 19: View strains
    print("[17b/18] E. coli strain info...")
    strain_table = section_ecoli_strains(html, dataset)

    # Section 20: Retrieve experiment metadata (E. coli)
    print("[17c/18] E. coli experiment metadata...")
    bacteria_table = section_ecoli_metadata(html, data_tables, strain_table)

    # Section 21: Get microscopy image metadata
    print("[18/18] E. coli image metadata...")
    ecoli_image_map = section_ecoli_image_metadata(html, dataset, bacteria_table)

    # Section 22: Plot an image or mask
    print("[18b/18] E. coli fluorescence image...")
    section_ecoli_plot_image(html, dataset, ecoli_image_map, bacteria_table)

    # Write HTML
    output = html.render()
    OUTPUT_HTML.write_text(output, encoding="utf-8")
    print(f"\n{'=' * 70}")
    print(f"Tutorial HTML written to: {OUTPUT_HTML}")
    print(f"File size: {OUTPUT_HTML.stat().st_size / 1024:.1f} KB")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
