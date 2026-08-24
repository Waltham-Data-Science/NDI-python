"""P1 Run-1 verification harness — dabrowska BNST (67f723d5, 14k).

Materializes the dataset locally (via the now-parallel downloadDataset) and runs
each NATIVE NDI metadata step from the tutorial, dumping the output table shape +
columns + head so it can be diffed against the tutorial's RECORDED HTML output.
Source of truth = tutorials/tutorial_67f723d574f5f79c6062389d.html. NO HARDCODING.
Credentials come from the env (CloudClient.from_env); values are never printed.
"""

import os
import time
import traceback

import ndi.fun.doc as fdoc
import ndi.fun.doc_table as fdt
from ndi.cloud.client import CloudClient
from ndi.cloud.orchestration import downloadDataset

DS = "67f723d574f5f79c6062389d"
# Relocated 2026-07-20 into NDI-python/tutorials/verification/. Paths resolve
# against the sibling ndi-projects workspace root (override NDI_PROJECTS_ROOT).
_WS = os.environ.get("NDI_PROJECTS_ROOT", os.path.expanduser("~/Documents/ndi-projects"))
CACHE = os.path.join(_WS, "tutorials", "_cache")
os.makedirs(CACHE, exist_ok=True)


def show(name, fn):
    print(f"\n===== {name} =====", flush=True)
    try:
        r = fn()
        try:
            print("shape:", r.shape, flush=True)
            print("columns:", list(r.columns), flush=True)
            print(r.head(15).to_string(), flush=True)
        except Exception:
            print(repr(r)[:3000], flush=True)
        return r
    except Exception as e:
        print("ERROR:", type(e).__name__, e, flush=True)
        traceback.print_exc()
        return None


def main():
    import os.path as osp

    store = osp.join(CACHE, DS)
    t0 = time.time()
    if osp.isdir(osp.join(store, ".ndi")):
        from ndi.dataset import ndi_dataset_dir

        dataset = ndi_dataset_dir("", store)
        print(f"warm-loaded cached store in {time.time() - t0:.0f}s", flush=True)
    else:
        client = CloudClient.from_env()
        dataset = downloadDataset(DS, CACHE, client=client)
        print(f"materialized (cold) in {time.time() - t0:.0f}s", flush=True)

    # MATLAB [ref, list] = session_list(); Python returns a 4-tuple.
    ref_list, id_list, *_ = dataset.session_list()
    print("session refs:", ref_list, "| ids:", id_list, flush=True)
    session = dataset.open_session(id_list[0]) if id_list else None

    # The native metadata steps the dabrowska tutorial runs (Run 1):
    show("getDocTypes(dataset)", lambda: fdoc.getDocTypes(dataset))
    show("docTable.subject(dataset)", lambda: fdt.subject(dataset))
    show("docTable.probe(dataset)", lambda: fdt.probe(dataset))
    show("docTable.epoch(session)", lambda: fdt.epoch(session))
    print("\n=== harness done ===", flush=True)


if __name__ == "__main__":
    main()
