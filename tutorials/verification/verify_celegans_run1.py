"""P1 Run-1 verification harness — C. elegans-memory (69bc5ca1).

Runs the native metadata + readtablechar-dependent steps and dumps them for
diffing against the recorded HTML tables. NO HARDCODING.
Ground truth = tutorials/tutorial_69bc5ca11d547b1f6d083761.html:
  t0 docTypes, t1 subjectTable (101x28), t4 odorTable (11x10, readtablechar),
  t5 imageStack, t7 treatment Gantt (10x9, readtablechar).
"""

import os
import traceback

import numpy as np

# Relocated 2026-07-20 into NDI-python/tutorials/verification/. Paths resolve
# against the sibling ndi-projects workspace root (override NDI_PROJECTS_ROOT).
_WS = os.environ.get("NDI_PROJECTS_ROOT", os.path.expanduser("~/Documents/ndi-projects"))
STORE = os.path.join(_WS, "tutorials", "_cache", "69bc5ca11d547b1f6d083761")


def show(name, fn):
    print(f"\n===== {name} =====", flush=True)
    try:
        r = fn()
        try:
            print("shape:", r.shape, "| cols:", list(r.columns), flush=True)
            print(r.head(6).to_string(), flush=True)
        except Exception:
            print(repr(r)[:1500], flush=True)
        return r
    except Exception as e:
        print("ERROR:", type(e).__name__, e, flush=True)
        traceback.print_exc()
        return None


def main():
    import ndi.fun.doc as fdoc
    import ndi.fun.doc_table as fdt
    from ndi.database_fun import readtablechar
    from ndi.dataset import ndi_dataset_dir
    from ndi.query import ndi_query

    ds = ndi_dataset_dir("", STORE)
    try:
        from ndi.cloud.client import CloudClient

        ds.cloud_client = CloudClient.from_env()
    except Exception as e:
        print("WARN no cloud_client:", e)
    refs, ids, *_ = ds.session_list()
    print("sessions:", refs, flush=True)
    sess = ds.open_session(ids[0]) if ids else ds

    show("getDocTypes", lambda: _dt(fdoc.getDocTypes(ds)))
    show("docTable.subject", lambda: fdt.subject(sess))

    # ontologyTableRowDoc2Table StackAll=True
    def _stackall():
        docs = ds.database_search(ndi_query("").isa("ontologyTableRow"))
        res = fdoc.ontologyTableRowDoc2Table(docs, StackAll=True)
        tables = res[0] if isinstance(res, tuple) else res
        print(
            f"  StackAll -> {len(tables)} table(s); shapes {[t.shape for t in tables]}", flush=True
        )
        return tables[0] if tables else None

    stacked = show("ontologyTableRowDoc2Table(StackAll=True)", _stackall)

    # odorTable: readtablechar on the mixture column (if present)
    if stacked is not None:
        mixcol = next((c for c in stacked.columns if "MixtureTable" in c), None)
        print(f"\n  mixture column: {mixcol!r}", flush=True)
        if mixcol is not None:
            parts = []
            for mt in stacked[mixcol].dropna().unique()[:30]:
                if isinstance(mt, str) and mt.strip():
                    try:
                        parts.append(readtablechar(mt, ".txt", "Delimiter", ","))
                    except Exception as e:
                        print("    readtablechar err:", e, flush=True)
            if parts:
                import pandas as pd

                odor = pd.concat(parts, ignore_index=True).drop_duplicates()
                print(f"  odorTable: {odor.shape} cols={list(odor.columns)}", flush=True)
                print(odor.head(6).to_string(), flush=True)

    # treatment_drug -> treatmentTable via readtablechar
    def _treatment():
        import pandas as pd

        tdocs = sess.database_search(ndi_query("").isa("treatment_drug"))
        print(f"  treatment_drug docs: {len(tdocs)}", flush=True)
        rows = []
        for d in tdocs[:60]:
            td = d.document_properties.get("treatment_drug", {})
            mt = td.get("mixture_table", "")
            base = {k: v for k, v in td.items() if k != "mixture_table"}
            if mt:
                try:
                    mtab = readtablechar(mt, ".txt", "Delimiter", ",")
                    for _, r in mtab.iterrows():
                        rows.append({**base, **r.to_dict()})
                except Exception as e:
                    print("    rtc err:", e, flush=True)
        return pd.DataFrame(rows) if rows else pd.DataFrame()

    show("treatmentTable (treatment_drug + readtablechar)", _treatment)

    # imageStack read
    def _img():
        import ndi.fun.data as fdata

        isd = sess.database_search(ndi_query("").isa("imageStack"))
        print(f"  imageStack docs: {len(isd)}", flush=True)
        if not isd:
            return None
        img, info = fdata.readImageStack(sess, isd[0], "auto")
        img = np.asarray(img)
        return f"readImageStack -> shape={img.shape} dtype={img.dtype}"

    show("imageStack readImageStack", _img)

    print("\n=== harness done ===", flush=True)


def _dt(res):
    import pandas as pd

    if isinstance(res, tuple):
        return pd.DataFrame({"docTypes": res[0], "docCounts": res[1]})
    return res


if __name__ == "__main__":
    main()
