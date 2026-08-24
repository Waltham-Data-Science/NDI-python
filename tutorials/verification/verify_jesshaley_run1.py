"""P1 Run-1 verification harness — jess-haley C. elegans + E. coli (682e7772, 78k).

Loads the bulk JSON dataset ONCE into a persistent store (then warm-reopens) and
runs each NATIVE metadata step from the tutorial, dumping shape + columns + head
so it can be diffed against the tutorial's recorded HTML tables. NO HARDCODING.
Ground truth = NDI-matlab/src/ndi/+ndi/+setup/+conv/+haley/tutorial_682e7772cdf3f24938176fac.html
(the authoritative render; repointed 2026-07-20 from the former root copy, which
was archived — re-baseline the Run-1 parity numbers on the first post-repoint run).
"""

import os
import os.path as osp
import time
import traceback

# Relocated 2026-07-20 into NDI-python/tutorials/verification/. Paths resolve
# against the sibling ndi-projects workspace root (override NDI_PROJECTS_ROOT).
_WS = os.environ.get("NDI_PROJECTS_ROOT", os.path.expanduser("~/Documents/ndi-projects"))
DOCS = os.path.join(_WS, "datasets", "jess-haley", "documents")
LOADED = os.path.join(_WS, "datasets", "jess-haley", "_loaded")


def show(name, fn):
    print(f"\n===== {name} =====", flush=True)
    try:
        r = fn()
        try:
            print("shape:", r.shape, flush=True)
            print("columns:", list(r.columns), flush=True)
            print(r.head(8).to_string(), flush=True)
        except Exception:
            print(repr(r)[:2000], flush=True)
        return r
    except Exception as e:
        print("ERROR:", type(e).__name__, e, flush=True)
        traceback.print_exc()
        return None


def main():
    import ndi.fun.doc as fdoc
    import ndi.fun.doc_table as fdt
    from ndi.query import ndi_query

    t0 = time.time()
    if osp.isdir(osp.join(LOADED, ".ndi")):
        from ndi.dataset import ndi_dataset_dir

        dataset = ndi_dataset_dir("", LOADED)
        print(f"warm-opened loaded store in {time.time() - t0:.0f}s", flush=True)
    else:
        from ndi.cloud.orchestration import load_dataset_from_json_dir

        os.makedirs(LOADED, exist_ok=True)
        dataset = load_dataset_from_json_dir(DOCS, target_folder=LOADED, verbose=False)
        print(f"bulk-loaded JSON dir in {time.time() - t0:.0f}s", flush=True)

    refs, ids, *_ = dataset.session_list()
    print("session refs:", refs, "| ids:", ids, flush=True)

    # Tutorial uses the C. elegans session for docTable.subject.
    cele_idx = next((i for i, r in enumerate(refs) if "eleg" in str(r).lower()), 0)
    session = dataset.open_session(ids[cele_idx]) if ids else dataset

    # --- native metadata steps ---
    show("getDocTypes(dataset)", lambda: _doctypes_df(fdoc.getDocTypes(dataset)))

    def _otrvars():
        res = fdoc.ontologyTableRowVars(dataset)
        full, short, nodes = res[0], res[1], res[2]
        import pandas as pd

        return pd.DataFrame({"fullName": full, "shortName": short, "ontologyNode": nodes})

    show("ontologyTableRowVars(dataset)", _otrvars)

    def _otr2table():
        docs = dataset.database_search(ndi_query("").isa("ontologyTableRow"))
        print(f"  (ontologyTableRow docs: {len(docs)})", flush=True)
        res = fdoc.ontologyTableRowDoc2Table(docs)
        tables = res[0] if isinstance(res, tuple) else res
        print(
            f"  grouped into {len(tables)} tables; shapes: " f"{[t.shape for t in tables]}",
            flush=True,
        )
        for gi, t in enumerate(tables):
            print(f"  --- dataTable[{gi}] {t.shape} cols={list(t.columns)[:6]} ---", flush=True)
        return tables[0] if tables else None

    show("ontologyTableRowDoc2Table(docs) [grouped]", _otr2table)

    show("docTable.subject(C.elegans session)", lambda: fdt.subject(session))

    print("\n=== harness done ===", flush=True)


def _doctypes_df(res):
    import pandas as pd

    if isinstance(res, tuple):
        types, counts = res
        return pd.DataFrame({"docTypes": types, "docCounts": counts})
    return res


if __name__ == "__main__":
    main()
