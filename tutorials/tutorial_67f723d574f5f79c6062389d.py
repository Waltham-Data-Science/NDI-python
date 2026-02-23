#!/usr/bin/env python3
"""
NDI Dataset Tutorial: Rat Electrophysiology & Optogenetic Stimulation
======================================================================

Python equivalent of the MATLAB tutorial:
  tutorial_67f723d574f5f79c6062389d.mlx

Paper: https://doi.org/10.1016/j.celrep.2025.115768
Dataset DOI: https://doi.org/10.63884/ndic.2025.jyxfer8m

This script loads the Dabrowska dataset (67f723d574f5f79c6062389d),
runs the same analysis steps as the MATLAB tutorial, and writes
the results to an HTML file.

Dataset summary:
  - 14646 documents, 215 subjects, 606 probes (202 each: patch-I, patch-Vm, stimulator)
  - Whole-cell patch-clamp recordings from identified neurons across
    stress-related brain regions with optogenetic stimulation
  - Species: Rattus norvegicus
  - Strains: CRF-Cre, OTR-IRES-Cre, AVP-Cre, SD wildtype

Prerequisites:
  - Run 'python ndi_install.py' to install NDI and all dependencies
  - NDI Cloud account (free at https://www.ndi-cloud.com)
  - Set NDI_CLOUD_USERNAME/NDI_CLOUD_PASSWORD env vars (or edit this script)
  - See tutorials/README.md for detailed setup instructions

Usage:
  python tutorials/tutorial_67f723d574f5f79c6062389d.py
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

CLOUD_DATASET_ID = "67f723d574f5f79c6062389d"
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


@timed
def section_1_import_and_load(html: HTMLBuilder) -> Any:
    """Section 1: Import and load NDI dataset."""
    import pandas as pd

    import ndi.dataset
    from ndi.cloud import download_dataset
    from ndi.cloud.auth import login
    from ndi.cloud.client import CloudClient
    from ndi.fun.doc import get_doc_types

    html.add_heading("Import and load NDI dataset")
    html.add_text(
        "Define the dataset path and cloud ID, then load the dataset. "
        "The first time you access a dataset it must be downloaded from "
        "NDI Cloud, which may take several minutes. Once downloaded, "
        "subsequent loads are instantaneous."
    )
    html.add_text(
        "You will need an NDI Cloud account to download the dataset and "
        "fetch binary files on demand. Create a free account at "
        "https://www.ndi-cloud.com and set your credentials via "
        "environment variables or at the top of this script."
    )
    html.add_text("Paper: https://doi.org/10.1016/j.celrep.2025.115768")
    html.add_text("Dataset DOI: https://doi.org/10.63884/ndic.2025.jyxfer8m")

    html.add_code("""\
import os
import ndi.dataset
from ndi.cloud import download_dataset
from ndi.cloud.auth import login
from ndi.cloud.client import CloudClient
from ndi.fun.doc import get_doc_types

cloud_dataset_id = '67f723d574f5f79c6062389d'
data_path = os.path.expanduser('~/Documents/MATLAB/Datasets')
dataset_path = os.path.join(data_path, cloud_dataset_id)

# NDI Cloud credentials (set via environment variables or edit here)
ndi_cloud_username = os.environ.get('NDI_CLOUD_USERNAME', '')
ndi_cloud_password = os.environ.get('NDI_CLOUD_PASSWORD', '')

if os.path.exists(dataset_path):
    dataset = ndi.dataset.Dataset(dataset_path)
else:
    config = login(ndi_cloud_username, ndi_cloud_password)
    client = CloudClient(config)
    dataset = download_dataset(client, cloud_dataset_id, dataset_path, verbose=True)""")

    t0 = time.time()
    if DATASET_PATH.exists():
        dataset = ndi.dataset.Dataset(DATASET_PATH)
        elapsed = time.time() - t0
        html.add_output_text(
            f"cloud_dataset_id = '{CLOUD_DATASET_ID}'\n"
            f"dataset_path = '{DATASET_PATH}'\n"
            f"Dataset loaded in {elapsed:.2f}s"
        )
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
        html.add_output_text(
            f"cloud_dataset_id = '{CLOUD_DATASET_ID}'\n"
            f"dataset_path = '{DATASET_PATH}'\n"
            f"Dataset downloaded in {elapsed:.2f}s"
        )

    # Show document type counts
    html.add_text(
        "Let's start by looking at the document types in this dataset and "
        "how many of each type are present."
    )

    html.add_code("""\
doc_types, doc_counts = get_doc_types(dataset)
for t, c in zip(doc_types, doc_counts):
    print(f'  {t}: {c}')""")

    doc_types, doc_counts = get_doc_types(dataset)
    output_lines = []
    total_docs = 0
    for t, c in zip(doc_types, doc_counts):
        output_lines.append(f"  {t}: {c}")
        total_docs += c
    output_lines.append(f"\nTotal: {total_docs} documents across {len(doc_types)} types")
    html.add_output_text("\n".join(output_lines))

    # Show as HTML table
    df = pd.DataFrame({"docType": doc_types, "count": doc_counts})
    html.add_table_html(df_to_html(df, max_rows=30), f"documentsNDI ({len(df)} x 2 table)")

    return dataset


@timed
def section_2_subject_summary(html: HTMLBuilder, dataset: Any) -> Any:
    """Section 2: View subject summary table."""

    from ndi.fun.doc_table import subject_summary

    html.add_heading("View subject summary table")
    html.add_text(
        "Each individual animal is referred to as a subject and has a unique "
        "alphanumeric SubjectDocumentIdentifier and SubjectLocalIdentifier. "
        "This dataset contains subject, openminds_subject, and treatment "
        "documents which store metadata about each subject including their "
        "species, strain, genetic strain type, biological sex, and "
        "optogenetic stimulation target location, all linked to well-defined "
        "ontologies such as NCBI, RRID, and UBERON."
    )
    html.add_text("A summary table showing the metadata for each subject can be " "viewed below.")

    html.add_code("""\
from ndi.fun.doc_table import subject_summary

subject_table = subject_summary(dataset)
print(f'subjectTable: {subject_table.shape[0]} x {subject_table.shape[1]} table')
print(f'Columns: {list(subject_table.columns)}')
print(subject_table.head(10))""")

    subject_table = subject_summary(dataset)

    html.add_output_text(
        f"subjectTable: {subject_table.shape[0]} x {subject_table.shape[1]} table\n"
        f"Columns: {list(subject_table.columns)}"
    )
    html.add_table_html(
        df_to_html(subject_table, max_rows=20),
        f"subjectTable ({subject_table.shape[0]} x {subject_table.shape[1]} table)",
    )

    return subject_table


@timed
def section_3_filter_subjects(html: HTMLBuilder, subject_table: Any) -> Any:
    """Section 3: Filter subjects by strain."""
    from ndi.fun.table import identify_matching_rows

    html.add_heading("Filter subjects by strain")
    html.add_text(
        "We have created tools to filter a table by its values. "
        "Let's find all subjects with strain name containing 'AVP-Cre'. "
        "This dataset includes several strains: CRF-Cre, OTR-IRES-Cre, "
        "AVP-Cre, and SD wildtype controls."
    )

    html.add_code("""\
from ndi.fun.table import identify_matching_rows

column_name = 'StrainName'
data_value = 'AVP-Cre'
row_ind = identify_matching_rows(
    subject_table, column_name, data_value, string_match='contains'
)
filtered_subjects = subject_table[row_ind]
print(f'filteredSubjects: {len(filtered_subjects)} rows x {len(filtered_subjects.columns)} columns')
print(filtered_subjects)""")

    row_ind = identify_matching_rows(
        subject_table, "StrainName", "AVP-Cre", string_match="contains"
    )
    filtered_subjects = subject_table[row_ind]

    html.add_output_text(
        f"filteredSubjects: {len(filtered_subjects)} rows x "
        f"{len(filtered_subjects.columns)} columns"
    )
    html.add_table_html(
        df_to_html(filtered_subjects, max_rows=20),
        f"filteredSubjects ({len(filtered_subjects)} x {len(filtered_subjects.columns)} table)",
    )

    return filtered_subjects


# ---------------------------------------------------------------------------
# Sections 4-6 (Pass 2): Probe summary, Epoch summary, Combined table
# ---------------------------------------------------------------------------


@timed
def section_4_probe_summary(html: HTMLBuilder, dataset: Any) -> Any:
    """Section 4: View probe summary table."""

    from ndi.fun.doc_table import probe_table

    html.add_heading("View probe summary table")
    html.add_text(
        "Each probe (recording electrode or stimulator) is described by a "
        "probe document. The probe summary table collects metadata for all "
        "probes in the dataset, including probe name, type, reference, "
        "location, and cell type annotations from the OpenMINDS ontology."
    )

    html.add_code("""\
from ndi.fun.doc_table import probe_table

probe_summary = probe_table(dataset)
print(f'probeTable: {probe_summary.shape[0]} x {probe_summary.shape[1]} table')
print(f'Columns: {list(probe_summary.columns)}')""")

    probe_summary = probe_table(dataset)

    html.add_output_text(
        f"probeTable: {probe_summary.shape[0]} x {probe_summary.shape[1]} table\n"
        f"Columns: {list(probe_summary.columns)}"
    )
    html.add_table_html(
        df_to_html(probe_summary, max_rows=20),
        f"probeTable ({probe_summary.shape[0]} x {probe_summary.shape[1]} table)",
    )

    # Probe type distribution
    html.add_text(
        "Let's look at the distribution of probe types. Each subject has "
        "three probes: a patch-clamp current probe (patch-I), a patch-clamp "
        "voltage probe (patch-Vm), and an optogenetic stimulator."
    )

    html.add_code("""\
print('Probe type distribution:')
print(probe_summary['ProbeType'].value_counts().to_string())""")

    probe_type_dist = probe_summary["ProbeType"].value_counts()
    dist_lines = ["Probe type distribution:"]
    for ptype, count in probe_type_dist.items():
        dist_lines.append(f"  {ptype}: {count}")
    html.add_output_text("\n".join(dist_lines))

    # Cell type distribution
    html.add_text(
        "The cell type annotations show the neuronal subtypes identified "
        "during patch-clamp recording."
    )

    html.add_code("""\
print('Cell type distribution:')
print(probe_summary['CellTypeName'].value_counts().to_string())""")

    cell_type_dist = probe_summary["CellTypeName"].value_counts()
    ct_lines = ["Cell type distribution:"]
    for ctype, count in cell_type_dist.items():
        label = ctype if ctype else "(empty / stimulator)"
        ct_lines.append(f"  {label}: {count}")
    html.add_output_text("\n".join(ct_lines))

    return probe_summary


@timed
def section_5_epoch_summary(html: HTMLBuilder, dataset: Any) -> Any:
    """Section 5: View epoch summary table."""

    from ndi.fun.doc_table import epoch_table

    html.add_heading("View epoch summary table")
    html.add_text(
        "An epoch is a segment of time during which data was recorded. "
        "The epoch summary table links each epoch to its probe, subject, "
        "and any stimulus or experimental approach metadata. Building this "
        "table requires cross-referencing several document types, so it "
        "takes a few seconds to compute."
    )

    html.add_code("""\
from ndi.fun.doc_table import epoch_table

epoch_summary = epoch_table(dataset)
print(f'epochTable: {epoch_summary.shape[0]} x {epoch_summary.shape[1]} table')
print(f'Columns: {list(epoch_summary.columns)}')""")

    epoch_summary = epoch_table(dataset)

    html.add_output_text(
        f"epochTable: {epoch_summary.shape[0]} x {epoch_summary.shape[1]} table\n"
        f"Columns: {list(epoch_summary.columns)}"
    )
    html.add_table_html(
        df_to_html(epoch_summary, max_rows=20),
        f"epochTable ({epoch_summary.shape[0]} x {epoch_summary.shape[1]} table)",
    )

    # Approach name distribution
    html.add_text("Let's examine the experimental approach distribution across epochs.")

    html.add_code("""\
print('Approach name distribution:')
print(epoch_summary['ApproachName'].value_counts().to_string())""")

    approach_dist = epoch_summary["ApproachName"].value_counts()
    approach_lines = ["Approach name distribution:"]
    for approach, count in approach_dist.items():
        label = approach if approach else "(none)"
        approach_lines.append(f"  {label}: {count}")
    html.add_output_text("\n".join(approach_lines))

    return epoch_summary


@timed
def section_6_combined_table(
    html: HTMLBuilder,
    subject_table: Any,
    probe_summary: Any,
    epoch_summary: Any,
) -> Any:
    """Section 6: Combined summary table and epoch filtering."""

    from ndi.fun.table import identify_matching_rows, join, move_columns_left

    html.add_heading("Combined summary table and epoch filtering")
    html.add_text(
        "We can join the subject, probe, and epoch summary tables on their "
        "common columns (SubjectDocumentIdentifier, ProbeDocumentIdentifier) "
        "to create a single combined table. Then we reorder columns so that "
        "SubjectLocalIdentifier and EpochNumber appear first."
    )

    html.add_code("""\
from ndi.fun.table import join, move_columns_left, identify_matching_rows

combined = join([subject_table, probe_summary, epoch_summary])
combined = move_columns_left(combined, ['SubjectLocalIdentifier', 'EpochNumber'])
print(f'combined: {combined.shape[0]} x {combined.shape[1]} table')
print(f'Columns: {list(combined.columns)}')""")

    combined = join([subject_table, probe_summary, epoch_summary])
    combined = move_columns_left(combined, ["SubjectLocalIdentifier", "EpochNumber"])

    html.add_output_text(
        f"combined: {combined.shape[0]} x {combined.shape[1]} table\n"
        f"Columns: {list(combined.columns)}"
    )
    html.add_table_html(
        df_to_html(combined, max_rows=20),
        f"combined ({combined.shape[0]} x {combined.shape[1]} table)",
    )

    # --- Filter by ApproachName containing 'optogenetic' ---
    html.add_heading("Filter epochs by approach name", level=3)
    html.add_text(
        "Let's filter the combined table to find all epochs where the "
        "ApproachName contains 'optogenetic'."
    )

    html.add_code("""\
row_ind = identify_matching_rows(
    combined, 'ApproachName', 'optogenetic', string_match='contains'
)
opto_epochs = combined[row_ind]
print(f'Epochs with optogenetic approach: {len(opto_epochs)} rows')""")

    row_ind = identify_matching_rows(
        combined, "ApproachName", "optogenetic", string_match="contains"
    )
    opto_epochs = combined[row_ind]

    html.add_output_text(f"Epochs with optogenetic approach: {len(opto_epochs)} rows")
    html.add_table_html(
        df_to_html(opto_epochs, max_rows=20),
        f"opto_epochs ({opto_epochs.shape[0]} x {opto_epochs.shape[1]} table)",
    )

    # --- Filter by MixtureName ---
    html.add_heading("Filter epochs by mixture name", level=3)
    html.add_text(
        "We can also filter by the bath solution (MixtureName) applied "
        "during recording. Let's find epochs where MixtureName contains "
        "'aCSF' (artificial cerebrospinal fluid)."
    )

    html.add_code("""\
row_ind = identify_matching_rows(
    combined, 'MixtureName', 'aCSF', string_match='contains'
)
acsf_epochs = combined[row_ind]
print(f'Epochs with aCSF mixture: {len(acsf_epochs)} rows')""")

    row_ind = identify_matching_rows(combined, "MixtureName", "aCSF", string_match="contains")
    acsf_epochs = combined[row_ind]

    html.add_output_text(f"Epochs with aCSF mixture: {len(acsf_epochs)} rows")
    html.add_table_html(
        df_to_html(acsf_epochs, max_rows=20),
        f"acsf_epochs ({acsf_epochs.shape[0]} x {acsf_epochs.shape[1]} table)",
    )

    # --- Filter by CellTypeName identical match ---
    html.add_heading("Filter epochs by cell type", level=3)
    html.add_text(
        "Finally, let's filter for a specific cell type using an exact "
        "(identical) match. We'll find all epochs recorded from 'type I "
        "BNST neuron' cells."
    )

    html.add_code("""\
row_ind = identify_matching_rows(
    combined, 'CellTypeName', 'type I BNST neuron', string_match='identical'
)
type1_epochs = combined[row_ind]
print(f'Epochs with type I BNST neuron: {len(type1_epochs)} rows')""")

    row_ind = identify_matching_rows(
        combined, "CellTypeName", "type I BNST neuron", string_match="identical"
    )
    type1_epochs = combined[row_ind]

    html.add_output_text(f"Epochs with type I BNST neuron: {len(type1_epochs)} rows")
    html.add_table_html(
        df_to_html(type1_epochs, max_rows=20),
        f"type1_epochs ({type1_epochs.shape[0]} x {type1_epochs.shape[1]} table)",
    )

    return combined


# ---------------------------------------------------------------------------
# Sections 7 (Pass 3): Plot electrophysiology data
# ---------------------------------------------------------------------------


@timed
def section_7_plot_electrophysiology(
    html: HTMLBuilder,
    dataset: Any,
    subject_table: Any,
    probe_summary: Any,
    combined_summary: Any,
) -> None:
    """Section 7: Plot electrophysiology data for a selected subject."""

    from ndi.fun.table import identify_matching_rows
    from ndi.query import Query

    html.add_heading("Plot electrophysiology data")
    html.add_text(
        "In MATLAB, we can use readtimeseries to read voltage and current "
        "traces from a probe for a given epoch. Here we select a subject "
        "by index, identify its recording probes and epochs, and prepare "
        "the data needed for plotting patch-clamp traces."
    )

    # --- Step 1: Select a subject by index (MATLAB: index 75, Python: 74) ---
    html.add_heading("Select a subject", level=3)
    html.add_text(
        "We pick the subject at index 74 (matching the MATLAB tutorial's "
        "index 75 since MATLAB is 1-indexed)."
    )

    html.add_code("""\
subject_id = subject_table['SubjectDocumentIdentifier'].iloc[74]
subject_name = subject_table['SubjectLocalIdentifier'].iloc[74]
print(f'Subject: {subject_name}')
print(f'ID:      {subject_id}')""")

    subject_id = subject_table["SubjectDocumentIdentifier"].iloc[74]
    subject_name = subject_table["SubjectLocalIdentifier"].iloc[74]

    html.add_output_text(f"Subject: {subject_name}\n" f"ID:      {subject_id}")

    # --- Step 2: Find probes for this subject ---
    html.add_heading("Identify probes for this subject", level=3)
    html.add_text(
        "Each subject has three probes: a patch-clamp voltage probe "
        "(patch-Vm), a patch-clamp current probe (patch-I), and an "
        "optogenetic stimulator. We filter the probe table by "
        "SubjectDocumentIdentifier to find them."
    )

    html.add_code("""\
probe_mask = probe_summary['SubjectDocumentIdentifier'] == subject_id
subject_probes = probe_summary[probe_mask]
print(subject_probes[['ProbeName', 'ProbeType', 'ProbeDocumentIdentifier']])

vm_probe_id = subject_probes[
    subject_probes['ProbeType'] == 'patch-Vm'
]['ProbeDocumentIdentifier'].iloc[0]
i_probe_id = subject_probes[
    subject_probes['ProbeType'] == 'patch-I'
]['ProbeDocumentIdentifier'].iloc[0]
print(f'\\nVm probe: {vm_probe_id}')
print(f'I  probe: {i_probe_id}')""")

    probe_mask = probe_summary["SubjectDocumentIdentifier"] == subject_id
    subject_probes = probe_summary[probe_mask]

    vm_row = subject_probes[subject_probes["ProbeType"] == "patch-Vm"]
    i_row = subject_probes[subject_probes["ProbeType"] == "patch-I"]
    vm_probe_id = vm_row["ProbeDocumentIdentifier"].iloc[0]
    i_probe_id = i_row["ProbeDocumentIdentifier"].iloc[0]

    probe_display = subject_probes[["ProbeName", "ProbeType", "ProbeDocumentIdentifier"]]
    html.add_output_text(
        probe_display.to_string(index=False)
        + f"\n\nVm probe: {vm_probe_id}"
        + f"\nI  probe: {i_probe_id}"
    )

    # --- Step 3: Find epoch conditions for this subject ---
    html.add_heading("Epoch conditions for this subject", level=3)
    html.add_text(
        "We filter the combined summary table to show the epoch "
        "conditions for the selected subject's voltage probe."
    )

    html.add_code("""\
epoch_mask = identify_matching_rows(
    combined, 'SubjectDocumentIdentifier', subject_id
)
epoch_conditions = combined[epoch_mask]

# Epochs for the Vm probe
vm_epochs = epoch_conditions[
    epoch_conditions['ProbeDocumentIdentifier'] == vm_probe_id
]
epoch_nums = sorted(vm_epochs['EpochNumber'].tolist())
print(f'Vm probe has {len(epoch_nums)} epochs: {epoch_nums}')""")

    epoch_mask = identify_matching_rows(combined_summary, "SubjectDocumentIdentifier", subject_id)
    epoch_conditions = combined_summary[epoch_mask]

    vm_epochs = epoch_conditions[epoch_conditions["ProbeDocumentIdentifier"] == vm_probe_id]
    epoch_nums = sorted(vm_epochs["EpochNumber"].tolist())

    html.add_output_text(f"Vm probe has {len(epoch_nums)} epochs: {epoch_nums}")

    # Show the Vm epoch conditions table
    display_cols = [
        "SubjectLocalIdentifier",
        "EpochNumber",
        "ProbeType",
        "MixtureName",
        "ApproachName",
        "CellTypeName",
    ]
    display_cols = [c for c in display_cols if c in vm_epochs.columns]
    html.add_table_html(
        df_to_html(vm_epochs[display_cols], max_rows=20),
        f"Vm epoch conditions ({len(vm_epochs)} x {len(display_cols)} table)",
    )

    # --- Step 4: Select epoch 4 ---
    html.add_heading("Select an epoch for plotting", level=3)
    html.add_text(
        "We select epoch 4 (the 4th recording sweep) for this subject, "
        "matching the MATLAB tutorial."
    )

    html.add_code("""\
epoch_num = epoch_nums[3]  # 4th epoch (0-indexed list)
epoch_row = vm_epochs[vm_epochs['EpochNumber'] == epoch_num].iloc[0]
print(f'Epoch number: {epoch_num}')
print(f'Approach:     {epoch_row["ApproachName"]}')
print(f'Mixture:      {epoch_row["MixtureName"]}')""")

    epoch_num = epoch_nums[3]
    epoch_row = vm_epochs[vm_epochs["EpochNumber"] == epoch_num].iloc[0]

    html.add_output_text(
        f"Epoch number: {epoch_num}\n"
        f"Approach:     {epoch_row['ApproachName']}\n"
        f"Mixture:      {epoch_row['MixtureName']}"
    )

    # --- Step 5: Reading timeseries (explanation + MATLAB equivalent) ---
    html.add_heading("Reading timeseries data", level=3)
    html.add_text(
        "In MATLAB, the readtimeseries function reads voltage and current "
        "traces directly from the probe object. The binary data is stored "
        "as ingested NBF segment files (ai_group*.nbf) referenced via the "
        "ndic:// protocol, which are fetched on demand from NDI Cloud."
    )
    html.add_text(
        "The MATLAB equivalent code for reading and plotting the "
        "electrophysiology data is shown below."
    )

    html.add_code("""\
% MATLAB equivalent:
%
% myVmP = dataset.getelements('element.name', probeTable.ProbeName{vmProbeIdx});
% myIP  = dataset.getelements('element.name', probeTable.ProbeName{iProbeIdx});
%
% [Vm_d, Vm_t] = myVmP{1}.readtimeseries(epochNum, 0, Inf);
% [I_d, I_t]   = myIP{1}.readtimeseries(epochNum, 0, Inf);
%
% figure;
% subplot(2,1,1); plot(Vm_t, Vm_d); ylabel('Vm (V)'); title(subjectName);
% subplot(2,1,2); plot(I_t, I_d);   ylabel('I (A)');  xlabel('Time (s)');""")

    html.add_text(
        "In Python, reading timeseries from cloud datasets requires the "
        "binary data files to be fetched via the ndic:// on-demand "
        "protocol. This requires NDI Cloud credentials "
        "(NDI_CLOUD_USERNAME and NDI_CLOUD_PASSWORD environment "
        "variables). When credentials are available, the data is "
        "fetched automatically on first access and cached locally."
    )

    # --- Step 6: Attempt to read binary data, or show what would be plotted ---
    html.add_code("""\
from ndi.query import Query

# Find the ingested DAQ document for this epoch
epoch_doc_id = vm_epochs[
    vm_epochs['EpochNumber'] == epoch_num
]['EpochDocumentIdentifier'].iloc[0]

q = (Query('').isa('daqreader_mfdaq_epochdata_ingested')
     & (Query('epochid.epochid') == epoch_doc_id))
daq_docs = dataset.database_search(q)
print(f'DAQ ingested docs for epoch {epoch_num}: {len(daq_docs)}')

# The binary files are stored as NBF segments:
#   ai_group1_seg.nbf_1  (analog input channel 1, segment 1)
#   ai_group1_seg.nbf_2  (analog input channel 1, segment 2)
# These contain the raw voltage and current waveforms.
#
# To read them, use:
#   fid = dataset.database_openbinarydoc(daq_doc, 'ai_group1_seg.nbf_1')
#   raw_bytes = fid.read()
#   fid.close()""")

    epoch_doc_id = vm_epochs[vm_epochs["EpochNumber"] == epoch_num]["EpochDocumentIdentifier"].iloc[
        0
    ]

    q = Query("").isa("daqreader_mfdaq_epochdata_ingested") & (
        Query("epochid.epochid") == epoch_doc_id
    )
    daq_docs = dataset.database_search(q)

    daq_output_lines = [
        f"DAQ ingested docs for epoch {epoch_num}: {len(daq_docs)}",
    ]
    if daq_docs:
        props = daq_docs[0].document_properties
        files = props.get("files", {})
        file_info = files.get("file_info", [])
        ai_files = [f for f in file_info if f.get("name", "").startswith("ai_")]
        daq_output_lines.append(f"Binary AI files available: {len(ai_files)}")
        if ai_files:
            daq_output_lines.append(
                f"Example: {ai_files[0].get('name', '')} -> "
                f"{ai_files[0].get('locations', {}).get('location', '')}"
            )
        # Show epoch timing
        daq_epoch = props.get("daqreader_epochdata_ingested", {})
        et_data = daq_epoch.get("epochtable", {})
        t0_t1 = et_data.get("t0_t1", [])
        if t0_t1:
            t0_dev, t1_dev = t0_t1[0]
            daq_output_lines.append(f"Epoch duration (device time): {t1_dev - t0_dev:.2f} s")

    html.add_output_text("\n".join(daq_output_lines))

    # --- Step 7: Read and plot the electrophysiology data ---
    html.add_heading("Plot Vm and I traces", level=3)
    html.add_text(
        "The ingested binary data is stored as compressed NBF (National "
        "Binary Format) tar.gz archives in the DAQ document, one per "
        "channel group. The channel_list.bin file describes the channel "
        "layout: ai1 (analog input = Vm), ao1 (analog output = I "
        "command), and t1 (time). We read each channel via the session "
        "binary API, which fetches the data on demand from NDI Cloud "
        "via the ndic:// protocol."
    )

    html.add_code("""\
import tarfile, numpy as np

daq_doc = daq_docs[0]  # the ingested DAQ document for this epoch

def read_nbf_channel(dataset, daq_doc, filename):
    \"\"\"Read raw float64 data from a compressed NBF tar.gz archive.\"\"\"
    fid = dataset.database_openbinarydoc(daq_doc, filename)
    filepath = fid.name
    fid.close()
    with tarfile.open(filepath, 'r:gz') as tar:
        for m in tar.getmembers():
            if not m.name.startswith('._') and m.name.endswith('.nbf'):
                return np.frombuffer(tar.extractfile(m).read(), dtype='<f8')
    return None

# Read membrane voltage (Vm) and injected current (I)
Vm_d = read_nbf_channel(dataset, daq_doc, 'ai_group1_seg.nbf_1')
I_d  = read_nbf_channel(dataset, daq_doc, 'ao_group1_seg.nbf_1')

# Segment into individual sweeps (separated by NaN gaps, as in MATLAB)
trace_starts = np.where(np.diff(np.concatenate([[1], np.isnan(I_d).astype(int)])) == -1)[0]
trace_ends   = np.where(np.diff(np.concatenate([np.isnan(I_d).astype(int), [0]])) == 1)[0]
num_steps     = len(trace_starts)
num_timepoints = max(trace_ends - trace_starts) + 1
sample_rate    = 10000.0

# Reformat into matrices (time x steps)
time_matrix = np.arange(num_timepoints) / sample_rate
Vm_matrix = np.full((num_timepoints, num_steps), np.nan)
I_matrix  = np.full((num_timepoints, num_steps), np.nan)
for i in range(num_steps):
    seg = slice(trace_starts[i], trace_ends[i] + 1)
    n = trace_ends[i] - trace_starts[i] + 1
    Vm_matrix[:n, i] = Vm_d[seg]
    I_matrix[:n, i]  = I_d[seg]

# Get current step value for each sweep
row_ind = np.nanargmax(np.abs(I_matrix), axis=0)
current_steps = np.array([I_matrix[row_ind[j], j] for j in range(num_steps)])

# Plot Vm and I traces in 2 subplots (matching MATLAB layout)
fig, (ax_vm, ax_i) = plt.subplots(2, 1, figsize=(8, 8), sharex=True)
cmap = plt.cm.turbo
norm = plt.Normalize(current_steps.min(), current_steps.max())
for i in range(num_steps):
    c = cmap(norm(current_steps[i]))
    ax_vm.plot(time_matrix, Vm_matrix[:, i], color=c, linewidth=0.8)
    ax_i.plot(time_matrix, I_matrix[:, i], color=c, linewidth=0.8)
ax_vm.set_ylabel('Vm (V)'); ax_vm.set_title(subject_name)
ax_i.set_ylabel('I (A)');   ax_i.set_xlabel('Time (s)')
sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
plt.colorbar(sm, ax=[ax_vm, ax_i], label='I (A)')""")

    import tarfile

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    def _read_nbf_channel(dataset_obj: Any, doc: Any, filename: str) -> np.ndarray | None:
        """Read raw float64 data from a compressed NBF tar.gz archive."""
        fid = dataset_obj.database_openbinarydoc(doc, filename)
        filepath = fid.name
        if hasattr(fid, "close"):
            fid.close()
        with tarfile.open(filepath, "r:gz") as tar:
            for m in tar.getmembers():
                if not m.name.startswith("._") and m.name.endswith(".nbf"):
                    f = tar.extractfile(m)
                    if f is not None:
                        return np.frombuffer(f.read(), dtype="<f8")
        return None

    try:
        # Read Vm from analog input, I from analog output
        vm_data = _read_nbf_channel(dataset, daq_docs[0], "ai_group1_seg.nbf_1")
        i_data = _read_nbf_channel(dataset, daq_docs[0], "ao_group1_seg.nbf_1")

        if vm_data is not None and i_data is not None:
            sample_rate = 10000.0

            # Segment sweeps by NaN gaps (matching MATLAB's readtimeseries)
            nan_i = np.isnan(i_data).astype(int)
            trace_starts = np.where(np.diff(np.concatenate([[1], nan_i])) == -1)[0]
            trace_ends = np.where(np.diff(np.concatenate([nan_i, [0]])) == 1)[0]
            num_steps = len(trace_starts)
            num_tp = max(trace_ends - trace_starts) + 1

            time_matrix = np.arange(num_tp) / sample_rate
            vm_matrix = np.full((num_tp, num_steps), np.nan)
            i_matrix = np.full((num_tp, num_steps), np.nan)
            for i in range(num_steps):
                n = trace_ends[i] - trace_starts[i] + 1
                vm_matrix[:n, i] = vm_data[trace_starts[i] : trace_ends[i] + 1]
                i_matrix[:n, i] = i_data[trace_starts[i] : trace_ends[i] + 1]

            # Current step value for each sweep
            row_ind = np.nanargmax(np.abs(i_matrix), axis=0)
            current_steps = np.array([i_matrix[row_ind[j], j] for j in range(num_steps)])

            # Plot Vm and I in 2 subplots (matching MATLAB layout)
            fig, (ax_vm, ax_i) = plt.subplots(2, 1, figsize=(8, 8), sharex=True)
            cmap = plt.cm.turbo
            norm = plt.Normalize(current_steps.min(), current_steps.max())
            for i in range(num_steps):
                c = cmap(norm(current_steps[i]))
                ax_vm.plot(time_matrix, vm_matrix[:, i], color=c, linewidth=0.8)
                ax_i.plot(time_matrix, i_matrix[:, i], color=c, linewidth=0.8)
            ax_vm.set_ylabel("Vm (V)")
            ax_vm.set_title(subject_name)
            ax_i.set_ylabel("I (A)")
            ax_i.set_xlabel("Time (s)")
            sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
            plt.colorbar(sm, ax=[ax_vm, ax_i], label="I (A)")
            plt.tight_layout()
            html.add_image_base64(
                fig_to_bytes(),
                caption=f"Electrophysiology trace: {subject_name} epoch {epoch_num}",
            )
        else:
            html.add_output_text("No AI/AO channel binary files found in the DAQ document.")
    except FileNotFoundError:
        html.add_output_text(
            "Binary data not available. Set NDI_CLOUD_USERNAME and "
            "NDI_CLOUD_PASSWORD environment variables to fetch on demand "
            "from NDI Cloud."
        )
    except Exception as e:
        html.add_output_text(f"Could not read electrophysiology data: {e}")


# ---------------------------------------------------------------------------
# Sections 8-9 (Pass 4): Elevated Plus Maze and Fear-Potentiated Startle
# ---------------------------------------------------------------------------


@timed
def section_8_plot_epm(html: HTMLBuilder, dataset: Any) -> Any:
    """Section 8: Plot Elevated Plus Maze data."""
    import pandas as pd

    from ndi.fun.doc_table import ontology_table_row_doc_to_table
    from ndi.fun.table import move_columns_left
    from ndi.query import Query

    html.add_heading("Plot Elevated Plus Maze data")
    html.add_text(
        "The dataset includes behavioral data from the Elevated Plus Maze "
        "(EPM), stored as ontologyTableRow documents. Each row represents "
        "one subject's EPM session, with columns for arm entries, time "
        "spent, latency, freezing, and locomotion metrics."
    )

    # --- Step 1: Query and convert EPM data ---
    html.add_code("""\
from ndi.query import Query
from ndi.fun.doc_table import ontology_table_row_doc_to_table
from ndi.fun.table import move_columns_left

query = Query('ontologyTableRow.variableNames').contains('ElevatedPlusMaze')
docs_epm = dataset.database_search(query)
tables_epm, ids_epm = ontology_table_row_doc_to_table(docs_epm)
table_epm = tables_epm[0]
print(f'tableEPM: {table_epm.shape[0]} x {table_epm.shape[1]} table')""")

    query = Query("ontologyTableRow.variableNames").contains("ElevatedPlusMaze")
    docs_epm = dataset.database_search(query)
    tables_epm, ids_epm = ontology_table_row_doc_to_table(docs_epm)
    table_epm = tables_epm[0]

    html.add_output_text(f"tableEPM: {table_epm.shape[0]} x {table_epm.shape[1]} table")

    # --- Step 2: Reorganize columns ---
    html.add_code("""\
table_epm = move_columns_left(table_epm, [
    'SubjectLocalIdentifier',
    'Treatment_CNOOrSalineAdministration',
    'ExperimentalGroupCode',
    'ElevatedPlusMaze_TestIdentifier',
    'DataExclusionFlag',
])
print(f'Columns: {list(table_epm.columns[:8])} ...')""")

    table_epm = move_columns_left(
        table_epm,
        [
            "SubjectLocalIdentifier",
            "Treatment_CNOOrSalineAdministration",
            "ExperimentalGroupCode",
            "ElevatedPlusMaze_TestIdentifier",
            "DataExclusionFlag",
        ],
    )

    html.add_output_text(f"Columns: {list(table_epm.columns[:8])} ...")
    html.add_table_html(
        df_to_html(table_epm, max_rows=20),
        f"tableEPM ({table_epm.shape[0]} x {table_epm.shape[1]} table)",
    )

    # --- Step 3: Select a variable and look up its definition ---
    html.add_heading("Select a variable to view its definition and plot", level=3)
    html.add_text(
        "We select a variable from the EPM table and look up its "
        "definition in the EMPTY ontology. The ontology provides "
        "human-readable names, definitions, and short variable names "
        "for each measured quantity."
    )

    plotting_variable = "ElevatedPlusMaze_OpenArmNorth_Entries"
    grouping_variable = "Treatment_CNOOrSalineAdministration"

    html.add_code(f"""\
from ndi.fun.doc import ontology_table_row_vars
from ndi.ontology import lookup as ontology_lookup

# Get ontology metadata for all OTR variables
full_names, short_names, ontology_nodes = ontology_table_row_vars(dataset)

# Look up the selected variable
plotting_variable = 'ElevatedPlusMaze_OpenArmNorth_Entries'
grouping_variable = '{grouping_variable}'

# Find the ontology term for this variable
try:
    term_idx = short_names.index(plotting_variable)
    term_id = ontology_nodes[term_idx]
    term_result = ontology_lookup(term_id)
    print(f'Variable:   {{plotting_variable}}')
    print(f'Full name:  {{full_names[term_idx]}}')
    print(f'Ontology:   {{term_id}}')
    if term_result:
        print(f'Definition: {{term_result.definition}}')
except ValueError:
    print(f'Variable {{plotting_variable}} not found in ontology metadata')""")

    from ndi.fun.doc import ontology_table_row_vars
    from ndi.ontology import lookup as ontology_lookup

    full_names, short_names, ontology_nodes = ontology_table_row_vars(dataset)

    term_info_lines = []
    term_full_name = plotting_variable
    try:
        term_idx = short_names.index(plotting_variable)
        term_id = ontology_nodes[term_idx]
        term_full_name = full_names[term_idx]
        term_result = ontology_lookup(term_id)
        term_info_lines.append(f"Variable:   {plotting_variable}")
        term_info_lines.append(f"Full name:  {full_names[term_idx]}")
        term_info_lines.append(f"Ontology:   {term_id}")
        if term_result:
            term_info_lines.append(f"Definition: {term_result.definition}")
    except ValueError:
        term_info_lines.append(f"Variable {plotting_variable} not found in ontology metadata")

    html.add_output_text("\n".join(term_info_lines))

    # --- Step 4: Filter valid rows and plot ---
    html.add_heading("Plot EPM data by treatment group", level=3)
    html.add_text(
        "We exclude subjects flagged for data exclusion (e.g., missing "
        "mCherry expression) and any rows with missing data. Then we "
        "create a violin plot comparing the selected variable across "
        "treatment groups (CNO vs Saline)."
    )

    html.add_code(f"""\
import matplotlib.pyplot as plt
import numpy as np

# Filter valid rows
valid_rows = ~table_epm['DataExclusionFlag']
y_col = table_epm['{plotting_variable}']

# Handle mixed types (some values may be stored in cells)
if y_col.dtype == object:
    valid_rows = valid_rows & y_col.apply(
        lambda x: isinstance(x, (int, float)) and not np.isnan(x)
    )
else:
    valid_rows = valid_rows & y_col.notna()

table_valid = table_epm[valid_rows]
x = table_valid['{grouping_variable}']
y = table_valid['{plotting_variable}']

fig, ax = plt.subplots(figsize=(6, 6))
groups = ['Saline', 'CNO']
colors_fill = ['#c4ddf0', '#f5cdb6']  # light blue, light peach
colors_dot  = ['#1f77b4', '#e67e22']  # blue, orange
data_by_group = [y[x == g].values for g in groups]

# Violin bodies
parts = ax.violinplot(data_by_group, positions=[0, 1], showextrema=False,
                      showmedians=False)
for i, body in enumerate(parts['bodies']):
    body.set_facecolor(colors_fill[i])
    body.set_edgecolor('black')
    body.set_linewidth(0.5)
    body.set_alpha(0.8)

# Inner box (IQR), whiskers, median for each group
for i, data in enumerate(data_by_group):
    q1, med, q3 = np.percentile(data, [25, 50, 75])
    iqr = q3 - q1
    wlo = max(data.min(), q1 - 1.5 * iqr)
    whi = min(data.max(), q3 + 1.5 * iqr)
    ax.add_patch(plt.Rectangle((i - 0.04, q1), 0.08, iqr,
                 facecolor='dimgray', zorder=3))
    ax.plot([i, i], [wlo, q1], color='gray', lw=1, zorder=2)
    ax.plot([i, i], [q3, whi], color='gray', lw=1, zorder=2)
    ax.scatter(i, med, color='white', s=20, zorder=4, edgecolor='none')

# Scatter individual data points (jittered)
rng = np.random.default_rng(42)
for i, data in enumerate(data_by_group):
    jitter = rng.uniform(-0.15, 0.15, len(data))
    ax.scatter(i + jitter, data, color=colors_dot[i], s=20,
               alpha=0.8, zorder=5, edgecolor='none')

ax.set_xticks([0, 1]); ax.set_xticklabels(groups)
ax.set_ylabel('{term_full_name}')
plt.tight_layout()""")

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    valid_rows = ~table_epm["DataExclusionFlag"]
    y_col = table_epm[plotting_variable]
    if y_col.dtype == object:
        valid_rows = valid_rows & y_col.apply(
            lambda x: isinstance(x, (int, float)) and not np.isnan(x)
        )
    else:
        valid_rows = valid_rows & y_col.notna()

    table_valid = table_epm[valid_rows]
    x = table_valid[grouping_variable]
    y = table_valid[plotting_variable]

    n_valid = len(table_valid)
    n_saline = (x == "Saline").sum()
    n_cno = (x == "CNO").sum()

    html.add_output_text(
        f"Valid rows: {n_valid} (excluded {len(table_epm) - n_valid})\n"
        f"Saline: {n_saline}, CNO: {n_cno}"
    )

    fig, ax = plt.subplots(figsize=(6, 6))
    groups = ["Saline", "CNO"]
    colors_fill = ["#c4ddf0", "#f5cdb6"]
    colors_dot = ["#1f77b4", "#e67e22"]
    data_by_group = [pd.to_numeric(y[x == g], errors="coerce").dropna().values for g in groups]

    parts = ax.violinplot(data_by_group, positions=[0, 1], showextrema=False, showmedians=False)
    for i, body in enumerate(parts["bodies"]):
        body.set_facecolor(colors_fill[i])
        body.set_edgecolor("black")
        body.set_linewidth(0.5)
        body.set_alpha(0.8)

    rng = np.random.default_rng(42)
    for i, data in enumerate(data_by_group):
        q1, med, q3 = np.percentile(data, [25, 50, 75])
        iqr = q3 - q1
        wlo = max(data.min(), q1 - 1.5 * iqr)
        whi = min(data.max(), q3 + 1.5 * iqr)
        ax.add_patch(plt.Rectangle((i - 0.04, q1), 0.08, iqr, facecolor="dimgray", zorder=3))
        ax.plot([i, i], [wlo, q1], color="gray", lw=1, zorder=2)
        ax.plot([i, i], [q3, whi], color="gray", lw=1, zorder=2)
        ax.scatter(i, med, color="white", s=20, zorder=4, edgecolor="none")
        jitter = rng.uniform(-0.15, 0.15, len(data))
        ax.scatter(
            i + jitter, data, color=colors_dot[i], s=20, alpha=0.8, zorder=5, edgecolor="none"
        )

    ax.set_xticks([0, 1])
    ax.set_xticklabels(groups)
    ax.set_ylabel(term_full_name)
    plt.tight_layout()

    html.add_image_base64(fig_to_bytes(), caption=f"EPM: {term_full_name} by Treatment")

    return table_epm


@timed
def section_9_plot_fps(html: HTMLBuilder, dataset: Any, table_epm: Any) -> None:
    """Section 9: Plot Fear-Potentiated Startle data."""
    import pandas as pd

    from ndi.fun.doc_table import ontology_table_row_doc_to_table
    from ndi.fun.table import move_columns_left
    from ndi.query import Query

    html.add_heading("Plot Fear-Potentiated Startle data")
    html.add_text(
        "The dataset also includes Fear-Potentiated Startle (FPS) data "
        "stored as ontologyTableRow documents. Each row represents one "
        "trial for one subject, with acoustic startle response metrics "
        "across different experimental phases and trial types."
    )

    # --- Step 1: Query and convert FPS data ---
    html.add_code("""\
query = Query('ontologyTableRow.variableNames').contains(
    'Fear_potentiatedStartle'
)
docs_fps = dataset.database_search(query)
tables_fps, ids_fps = ontology_table_row_doc_to_table(docs_fps)
table_fps = tables_fps[0]
print(f'tableFPS: {table_fps.shape[0]} x {table_fps.shape[1]} table')""")

    query = Query("ontologyTableRow.variableNames").contains("Fear_potentiatedStartle")
    docs_fps = dataset.database_search(query)
    tables_fps, ids_fps = ontology_table_row_doc_to_table(docs_fps)
    table_fps = tables_fps[0]

    html.add_output_text(f"tableFPS: {table_fps.shape[0]} x {table_fps.shape[1]} table")

    # --- Step 2: Reorganize columns ---
    html.add_code("""\
table_fps = move_columns_left(table_fps, [
    'Fear_potentiatedStartle_ExperimentalPhaseOrTestName',
    'SubjectLocalIdentifier',
])
print(f'Columns: {list(table_fps.columns)}')""")

    table_fps = move_columns_left(
        table_fps,
        [
            "Fear_potentiatedStartle_ExperimentalPhaseOrTestName",
            "SubjectLocalIdentifier",
        ],
    )

    html.add_output_text(f"Columns: {list(table_fps.columns)}")
    html.add_table_html(
        df_to_html(table_fps, max_rows=20),
        f"tableFPS ({table_fps.shape[0]} x {table_fps.shape[1]} table)",
    )

    # --- Step 3: Compute mean startle amplitude by group ---
    html.add_heading("Compute average startle amplitude by experimental phase", level=3)
    html.add_text(
        "We can reanalyze this data to derive values such as the "
        "percentage of cued and non-cued fear. First, we compute the "
        "mean startle amplitude for each combination of experimental "
        "phase, subject, and trial type using pandas groupby (equivalent "
        "to MATLAB's groupsummary)."
    )

    phase_col = "Fear_potentiatedStartle_ExperimentalPhaseOrTestName"
    subject_col = "SubjectLocalIdentifier"
    trial_col = "Fear_potentiatedStartle_TrialTypeIdentifier"
    amp_col = "AcousticStartleResponse_MaximumAmplitude"

    html.add_code(f"""\
# Compute mean startle amplitude per phase/subject/trial type
table_startle = table_fps.groupby(
    ['{phase_col}',
     '{subject_col}',
     '{trial_col}'],
    as_index=False
)['{amp_col}'].mean()

table_startle = table_startle.rename(
    columns={{'{amp_col}': 'mean_{amp_col}'}}
)
print(f'tableStartleAmplitude: {{table_startle.shape}}')

# Filter to Cue test phases only
experimental_phases = table_startle['{phase_col}'].unique()
cue_test_phases = sorted([p for p in experimental_phases if 'Cue test' in str(p)])
print(f'Cue test phases: {{cue_test_phases}}')""")

    # Ensure amplitude is numeric
    table_fps[amp_col] = pd.to_numeric(table_fps[amp_col], errors="coerce")

    table_startle = table_fps.groupby(
        [phase_col, subject_col, trial_col],
        as_index=False,
    )[amp_col].mean()

    mean_col = f"mean_{amp_col}"
    table_startle = table_startle.rename(columns={amp_col: mean_col})

    experimental_phases = table_startle[phase_col].unique()
    cue_test_phases = sorted([p for p in experimental_phases if "Cue test" in str(p)])

    html.add_output_text(
        f"tableStartleAmplitude: {table_startle.shape}\n" f"Cue test phases: {cue_test_phases}"
    )

    # --- Step 4: Pivot by trial type and calculate fear % ---
    html.add_heading("Calculate cued and non-cued fear percentages", level=3)
    html.add_text(
        "We separate the data by trial type: FPS (L+N) Testing Trial "
        "(light+noise cue), FPS (N) Testing Trial (noise only), and "
        "Startle 95 dB Trial (baseline startle). Then we join these "
        "tables and calculate fear percentages."
    )
    html.add_text(
        "Cued fear % = 100 * (LightNoise - NoiseOnly) / NoiseOnly\n\n"
        "Non-cued fear % = 100 * (NoiseOnly - Startle) / Startle"
    )

    html.add_code(f"""\
# Split by trial type
light_noise = table_startle[
    table_startle['{trial_col}'] == 'FPS (L+N) Testing Trial'
][['{phase_col}', '{subject_col}', '{mean_col}']].rename(
    columns={{'{mean_col}': 'startleAmplitudeLightNoise'}}
)

noise_only = table_startle[
    table_startle['{trial_col}'] == 'FPS (N) Testing Trial'
][['{phase_col}', '{subject_col}', '{mean_col}']].rename(
    columns={{'{mean_col}': 'startleAmplitudeNoiseOnly'}}
)

startle = table_startle[
    table_startle['{trial_col}'] == 'Startle 95 dB Trial'
][['{phase_col}', '{subject_col}', '{mean_col}']].rename(
    columns={{'{mean_col}': 'startleAmplitudeStartle'}}
)

# Join on phase + subject
join_keys = ['{phase_col}', '{subject_col}']
table_cue = light_noise.merge(noise_only, on=join_keys, how='inner')
table_cue = table_cue.merge(startle, on=join_keys, how='inner')

# Calculate fear percentages
table_cue['cuedFear'] = 100 * (
    table_cue['startleAmplitudeLightNoise']
    - table_cue['startleAmplitudeNoiseOnly']
) / table_cue['startleAmplitudeNoiseOnly']

table_cue['nonCuedFear'] = 100 * (
    table_cue['startleAmplitudeNoiseOnly']
    - table_cue['startleAmplitudeStartle']
) / table_cue['startleAmplitudeStartle']

print(f'tableCueTest: {{table_cue.shape}}')
print(table_cue.head(10))""")

    join_keys = [phase_col, subject_col]

    light_noise = table_startle[table_startle[trial_col] == "FPS (L+N) Testing Trial"][
        [phase_col, subject_col, mean_col]
    ].rename(columns={mean_col: "startleAmplitudeLightNoise"})

    noise_only = table_startle[table_startle[trial_col] == "FPS (N) Testing Trial"][
        [phase_col, subject_col, mean_col]
    ].rename(columns={mean_col: "startleAmplitudeNoiseOnly"})

    startle = table_startle[table_startle[trial_col] == "Startle 95 dB Trial"][
        [phase_col, subject_col, mean_col]
    ].rename(columns={mean_col: "startleAmplitudeStartle"})

    table_cue = light_noise.merge(noise_only, on=join_keys, how="inner")
    table_cue = table_cue.merge(startle, on=join_keys, how="inner")

    table_cue["cuedFear"] = (
        100
        * (table_cue["startleAmplitudeLightNoise"] - table_cue["startleAmplitudeNoiseOnly"])
        / table_cue["startleAmplitudeNoiseOnly"]
    )

    table_cue["nonCuedFear"] = (
        100
        * (table_cue["startleAmplitudeNoiseOnly"] - table_cue["startleAmplitudeStartle"])
        / table_cue["startleAmplitudeStartle"]
    )

    html.add_output_text(f"tableCueTest: {table_cue.shape}")
    html.add_table_html(
        df_to_html(table_cue, max_rows=20),
        f"tableCueTest ({table_cue.shape[0]} x {table_cue.shape[1]} table)",
    )

    # --- Step 5: Plot cued fear by treatment group ---
    html.add_heading("Plot cued fear by treatment group", level=3)
    html.add_text(
        "We select a Cue test phase, add the treatment group information "
        "from the EPM table, and create a violin plot of cued fear "
        "percentage by treatment (CNO vs Saline)."
    )

    # Pick the second Cue test phase (matching MATLAB: experimentalPhases(2))
    selected_phase = cue_test_phases[1] if len(cue_test_phases) > 1 else cue_test_phases[0]
    grouping_variable = "Treatment_CNOOrSalineAdministration"
    plotting_variable = "cuedFear"

    html.add_code(f"""\
# Select experimental phase
selected_phase = '{selected_phase}'

# Add treatment group from EPM table
grouping_variable = '{grouping_variable}'
table_cue_with_treatment = table_cue.merge(
    table_epm[['SubjectLocalIdentifier', grouping_variable]],
    on='SubjectLocalIdentifier',
    how='left',
)

# Filter to selected phase
phase_rows = table_cue_with_treatment['{phase_col}'] == selected_phase
table_phase = table_cue_with_treatment[phase_rows]

# Plot (matching MATLAB violinplot style)
fig, ax = plt.subplots(figsize=(6, 6))
groups = ['Saline', 'CNO']
colors_fill = ['#c4ddf0', '#f5cdb6']
colors_dot  = ['#1f77b4', '#e67e22']
data_by_group = [
    table_phase.loc[
        table_phase[grouping_variable] == g, '{plotting_variable}'
    ].dropna().values
    for g in groups
]
parts = ax.violinplot(data_by_group, positions=[0, 1],
                      showextrema=False, showmedians=False)
for i, body in enumerate(parts['bodies']):
    body.set_facecolor(colors_fill[i])
    body.set_edgecolor('black'); body.set_linewidth(0.5); body.set_alpha(0.8)
rng = np.random.default_rng(42)
for i, data in enumerate(data_by_group):
    q1, med, q3 = np.percentile(data, [25, 50, 75])
    iqr = q3 - q1
    wlo, whi = max(data.min(), q1-1.5*iqr), min(data.max(), q3+1.5*iqr)
    ax.add_patch(plt.Rectangle((i-0.04,q1), 0.08, iqr, fc='dimgray', zorder=3))
    ax.plot([i,i], [wlo,q1], color='gray', lw=1, zorder=2)
    ax.plot([i,i], [q3,whi], color='gray', lw=1, zorder=2)
    ax.scatter(i, med, color='white', s=20, zorder=4, edgecolor='none')
    jitter = rng.uniform(-0.15, 0.15, len(data))
    ax.scatter(i+jitter, data, color=colors_dot[i], s=20, alpha=0.8,
               zorder=5, edgecolor='none')
ax.set_xticks([0, 1]); ax.set_xticklabels(groups)
ax.set_ylabel('{plotting_variable}')
plt.tight_layout()""")

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Merge treatment info from EPM table
    treatment_cols = table_epm[["SubjectLocalIdentifier", grouping_variable]].drop_duplicates()
    table_cue_with_treatment = table_cue.merge(
        treatment_cols,
        on="SubjectLocalIdentifier",
        how="left",
    )

    # Filter to selected phase
    phase_rows = table_cue_with_treatment[phase_col] == selected_phase
    table_phase = table_cue_with_treatment[phase_rows]

    n_phase = len(table_phase)
    n_with_treatment = table_phase[grouping_variable].notna().sum()

    html.add_output_text(
        f"Selected phase: {selected_phase}\n"
        f"Subjects in phase: {n_phase}\n"
        f"With treatment info: {n_with_treatment}"
    )

    # Filter to rows that have treatment info
    table_phase = table_phase[table_phase[grouping_variable].notna()]

    import numpy as np

    fig, ax = plt.subplots(figsize=(6, 6))
    groups = ["Saline", "CNO"]
    colors_fill = ["#c4ddf0", "#f5cdb6"]
    colors_dot = ["#1f77b4", "#e67e22"]
    data_by_group = [
        table_phase.loc[table_phase[grouping_variable] == g, plotting_variable].dropna().values
        for g in groups
    ]

    non_empty = [d for d in data_by_group if len(d) > 0]
    if non_empty:
        positions = [i for i, d in enumerate(data_by_group) if len(d) > 0]
        labels = [groups[i] for i in positions]
        plot_data = [data_by_group[i] for i in positions]
        parts = ax.violinplot(plot_data, positions=positions, showextrema=False, showmedians=False)
        for idx, body in enumerate(parts["bodies"]):
            body.set_facecolor(colors_fill[positions[idx]])
            body.set_edgecolor("black")
            body.set_linewidth(0.5)
            body.set_alpha(0.8)

        rng = np.random.default_rng(42)
        for idx, pos in enumerate(positions):
            data = plot_data[idx]
            q1, med, q3 = np.percentile(data, [25, 50, 75])
            iqr = q3 - q1
            wlo = max(data.min(), q1 - 1.5 * iqr)
            whi = min(data.max(), q3 + 1.5 * iqr)
            ax.add_patch(plt.Rectangle((pos - 0.04, q1), 0.08, iqr, facecolor="dimgray", zorder=3))
            ax.plot([pos, pos], [wlo, q1], color="gray", lw=1, zorder=2)
            ax.plot([pos, pos], [q3, whi], color="gray", lw=1, zorder=2)
            ax.scatter(pos, med, color="white", s=20, zorder=4, edgecolor="none")
            jitter = rng.uniform(-0.15, 0.15, len(data))
            ax.scatter(
                pos + jitter,
                data,
                color=colors_dot[pos],
                s=20,
                alpha=0.8,
                zorder=5,
                edgecolor="none",
            )
        ax.set_xticks(positions)
        ax.set_xticklabels(labels)
    else:
        ax.text(0.5, 0.5, "No data available", transform=ax.transAxes, ha="center", va="center")

    ax.set_ylabel(plotting_variable)
    plt.tight_layout()

    html.add_image_base64(
        fig_to_bytes(),
        caption=f"FPS: Cued Fear % by Treatment ({selected_phase})",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print("=" * 70)
    print("NDI Dataset Tutorial: Rat Electrophysiology & Optogenetic Stimulation")
    print(f"Dataset: {CLOUD_DATASET_ID}")
    print("=" * 70)

    html = HTMLBuilder("NDI Dataset Tutorial: Rat Electrophysiology & Optogenetic Stimulation")

    # Section 1: Import and load
    print("\n[1] Import and load NDI dataset...")
    dataset = section_1_import_and_load(html)

    # Section 2: Subject summary
    print("[2] View subject summary table...")
    subject_table = section_2_subject_summary(html, dataset)

    # Section 3: Filter subjects
    print("[3] Filter subjects by strain...")
    section_3_filter_subjects(html, subject_table)

    html.add_separator()

    # Section 4: Probe summary
    print("[4] View probe summary table...")
    probe_summary = section_4_probe_summary(html, dataset)

    # Section 5: Epoch summary
    print("[5] View epoch summary table...")
    epoch_summary = section_5_epoch_summary(html, dataset)

    # Section 6: Combined table + epoch filtering
    print("[6] Combined summary table and epoch filtering...")
    combined = section_6_combined_table(
        html,
        subject_table,
        probe_summary,
        epoch_summary,
    )

    html.add_separator()

    # Section 7: Plot electrophysiology data
    print("[7] Plot electrophysiology data...")
    section_7_plot_electrophysiology(
        html,
        dataset,
        subject_table,
        probe_summary,
        combined,
    )

    html.add_separator()

    # Section 8: Elevated Plus Maze
    print("[8] Plot Elevated Plus Maze data...")
    table_epm = section_8_plot_epm(html, dataset)

    html.add_separator()

    # Section 9: Fear-Potentiated Startle
    print("[9] Plot Fear-Potentiated Startle data...")
    section_9_plot_fps(html, dataset, table_epm)

    # Write HTML
    output = html.render()
    OUTPUT_HTML.write_text(output, encoding="utf-8")
    print(f"\n{'=' * 70}")
    print(f"Tutorial HTML written to: {OUTPUT_HTML}")
    print(f"File size: {OUTPUT_HTML.stat().st_size / 1024:.1f} KB")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
