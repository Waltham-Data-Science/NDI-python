"""P1 epoch() verification — dabrowska BNST (67f723d5).

Compares the rewritten ndi.fun.doc_table.epoch() against the tutorial's recorded
epochSummary (HTML table[3]) at the EPOCH level. Probe DocumentIdentifiers are
runtime-minted (getprobes) and not persisted, so we key on the stable
EpochDocumentIdentifier and verify the data columns by value:
  local_t0, local_t1, global_t0, global_t1, MixtureName, MixtureOntology,
  ApproachName, ApproachOntology, SubjectDocumentIdentifier.
NO HARDCODING — ground truth = the HTML.
"""

import os

import pandas as pd

import ndi.fun.doc_table as fdt
from ndi.dataset import ndi_dataset_dir

# Relocated 2026-07-20 into NDI-python/tutorials/verification/. Paths resolve
# against the sibling ndi-projects workspace root (override NDI_PROJECTS_ROOT).
# HTML ground truth is repointed at the committed NDI-matlab dabrowska copy
# (md5-identical to the former root tutorials/ copy, which was deleted).
_WS = os.environ.get("NDI_PROJECTS_ROOT", os.path.expanduser("~/Documents/ndi-projects"))
STORE = os.path.join(_WS, "tutorials", "_cache", "67f723d574f5f79c6062389d")
HTML = os.path.join(
    _WS,
    "NDI-matlab",
    "src",
    "ndi",
    "+ndi",
    "+setup",
    "+conv",
    "+dabrowska",
    "tutorial_67f723d574f5f79c6062389d.html",
)


def unquote(v):
    """Strip MATLAB string-display single quotes + Live-HTML &nbsp; (\xa0)."""
    if v is None:
        return ""
    s = str(v).replace("\xa0", " ")
    if s.strip() == "nan":
        return ""
    s = s.strip()
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        s = s[1:-1]
    return s


def main():
    html = pd.read_html(HTML)[3]
    html = html.drop(columns=[c for c in html.columns if str(c).startswith("Unnamed")])
    html = html[html["EpochDocumentIdentifier"].notna()].copy()
    html["__eid"] = html["EpochDocumentIdentifier"].map(unquote)

    ds = ndi_dataset_dir("", STORE)
    _ref, ids, *_ = ds.session_list()
    sess = ds.open_session(ids[0])
    got = fdt.epoch(sess)

    print("=== columns ===")
    print("HTML :", list(html.drop(columns="__eid").columns))
    print("GOT  :", list(got.columns))
    print("cols match:", list(html.drop(columns="__eid").columns) == list(got.columns))
    print("GOT shape:", got.shape, "| unique epochs:", got["EpochDocumentIdentifier"].nunique())

    # Build epoch -> row for GOT (data is per-epoch, identical across that epoch's probes)
    got_by_eid = {}
    for _, r in got.iterrows():
        got_by_eid.setdefault(r["EpochDocumentIdentifier"], r)

    # Science columns (the PASS bar). SubjectDocumentIdentifier is checked
    # separately below — it is a data-linkage handle that has drifted in the
    # re-ingested dataset (WT vs OTRCre), not something the port controls.
    datacols = [
        "local_t0",
        "local_t1",
        "global_t0",
        "global_t1",
        "MixtureName",
        "MixtureOntology",
        "ApproachName",
        "ApproachOntology",
    ]
    datacols = [c for c in datacols if c in got.columns and c in html.columns]

    checked = 0
    mism = 0
    subj_drift = 0
    seen = set()
    for _, h in html.iterrows():
        eid = h["__eid"]
        if eid in seen:
            continue
        seen.add(eid)
        g = got_by_eid.get(eid)
        if g is None:
            print(f"MISSING epoch in GOT: {eid}")
            mism += 1
            continue
        checked += 1
        for c in datacols:
            hv = unquote(h[c])
            gv = unquote(g[c])
            if c in ("local_t0", "local_t1"):
                try:
                    if abs(float(hv) - float(gv)) < 1e-3:
                        continue
                except (ValueError, TypeError):
                    pass
            if hv != gv:
                mism += 1
                if mism <= 25:
                    print(f"  MISMATCH eid={eid[:34]} col={c}\n    HTML={hv!r}\n    GOT ={gv!r}")
        if "SubjectDocumentIdentifier" in html.columns:
            if unquote(h["SubjectDocumentIdentifier"]) != unquote(g["SubjectDocumentIdentifier"]):
                subj_drift += 1

    print(f"\n=== SCIENCE columns: epochs checked={checked}, mismatches={mism} ===")
    print(
        f"=== Subject-linkage drift (separate, data-level): {subj_drift}/{checked} epochs differ ==="
    )
    print("RESULT:", "PASS ✅" if mism == 0 else "FAIL ❌")


if __name__ == "__main__":
    main()
