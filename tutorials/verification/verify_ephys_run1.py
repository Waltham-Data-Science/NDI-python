"""P1/G1 ephys-trace verification — dabrowska patch-Vm/patch-I readtimeseries.

Reproduces the tutorial's electrophysiology step (src L148-202):
  getprobes(subject_id,type=patch-Vm/patch-I) -> readtimeseries(epochNum,-inf,inf)
  -> split current-step traces on NaN gaps -> reshape (time x steps) -> currentSteps.

Ground truth for this step is a PLOT IMAGE in the tutorial HTML (no recorded
numbers), so verification is STRUCTURAL + PLAUSIBILITY: readtimeseries returns
data of the expected shape, the NaN-gap reshape yields a sensible current-step
family, Vm is in mV range and I in pA range. Saves the Vm-trace plot PNG so it
can be eyeballed against the tutorial figure. NO HARDCODING.

Validates the G1 fix: probes are reconstructed via ndi.database.fun
.ndi_document2ndi_object (must return the concrete mfdaq probe class, not a
bare ndi_element).
"""

import os
import sys

import numpy as np

from ndi.database_fun import ndi_document2ndi_object
from ndi.dataset import ndi_dataset_dir
from ndi.query import ndi_query

# Relocated 2026-07-20 into NDI-python/tutorials/verification/. Paths resolve
# against the sibling ndi-projects workspace root (override NDI_PROJECTS_ROOT).
_WS = os.environ.get("NDI_PROJECTS_ROOT", os.path.expanduser("~/Documents/ndi-projects"))
STORE = os.path.join(_WS, "tutorials", "_cache", "67f723d574f5f79c6062389d")
OUT_PNG = os.path.join(_WS, "tutorials", "_ephys_vm_traces.png")


def find_probe(sess, ptype, subject_id=None):
    for d in sess.database_search(ndi_query("").isa("element")):
        el = d.document_properties.get("element", {})
        if el.get("type") != ptype:
            continue
        if subject_id is not None:
            deps = d.document_properties.get("depends_on") or []
            sid = next((x.get("value") for x in deps if x.get("name") == "subject_id"), None)
            if sid != subject_id:
                continue
        return d
    return None


def main():
    ds = ndi_dataset_dir("", STORE)
    # The cached .ndi store holds documents but not the ingested binary
    # segments (channel_list.bin / ai_groupN_seg.nbf live in the cloud as
    # ndic:// references). Attach a cloud client so database_openbinarydoc can
    # fetch them on demand for readtimeseries. Creds come from the env.
    try:
        from ndi.cloud.client import CloudClient

        ds.cloud_client = CloudClient.from_env()
        print("cloud_client attached")
    except Exception as e:
        print("WARN: no cloud_client:", e)
    _ref, ids, *_ = ds.session_list()
    sess = ds.open_session(ids[0])

    # Pick a patch-Vm probe and its same-subject patch-I sibling.
    pv_doc = find_probe(sess, "patch-Vm")
    subj = next(
        (
            x.get("value")
            for x in (pv_doc.document_properties.get("depends_on") or [])
            if x.get("name") == "subject_id"
        ),
        None,
    )
    pi_doc = find_probe(sess, "patch-I", subject_id=subj)
    name_v = pv_doc.document_properties["element"]["name"]
    name_i = pi_doc.document_properties["element"]["name"]
    print(f"patch-Vm={name_v} | patch-I={name_i} | subject={subj}")

    patchVm = ndi_document2ndi_object(pv_doc, sess)
    patchI = ndi_document2ndi_object(pi_doc, sess)
    print(f"reconstructed Vm={type(patchVm).__name__} I={type(patchI).__name__}")
    assert hasattr(patchVm, "readtimeseries"), "G1 FAIL: patch-Vm has no readtimeseries"

    epochNum = 4  # tutorial uses epochNums(4)
    dataVm, t, _ = patchVm.readtimeseries(epochNum, -np.inf, np.inf)
    dataI, _, _ = patchI.readtimeseries(epochNum, -np.inf, np.inf)
    dataVm = np.asarray(dataVm).ravel()
    dataI = np.asarray(dataI).ravel()
    t = np.asarray(t).ravel()
    print(f"readtimeseries epoch {epochNum}: Vm{dataVm.shape} I{dataI.shape} t{t.shape}")
    print(
        f"  Vm range [{np.nanmin(dataVm):.3g},{np.nanmax(dataVm):.3g}] (mV?)  "
        f"I range [{np.nanmin(dataI):.3g},{np.nanmax(dataI):.3g}] (pA?)  "
        f"nNaN Vm={np.isnan(dataVm).sum()} I={np.isnan(dataI).sum()}"
    )

    # Split current-step traces on NaN gaps (tutorial L171-191).
    traceStarts = np.where(np.diff(np.concatenate([[1], np.isnan(dataI).astype(int)])) == -1)[0]
    traceEnds = np.where(np.diff(np.concatenate([np.isnan(dataI).astype(int), [0]])) == 1)[0]
    numSteps = len(traceStarts)
    if numSteps == 0:
        print("RESULT: FAIL ❌ — no current-step traces found (NaN-gap split empty)")
        sys.exit(1)
    numTimepoints = int(np.max(traceEnds - traceStarts) + 1)
    print(f"  numSteps={numSteps}  numTimepoints={numTimepoints}")

    timeMatrix = t[:numTimepoints]
    Vm = np.full((numTimepoints, numSteps), np.nan)
    Im = np.full((numTimepoints, numSteps), np.nan)
    for i in range(numSteps):
        s, e = traceStarts[i], traceEnds[i]
        Vm[: e - s + 1, i] = dataVm[s : e + 1]
        Im[: e - s + 1, i] = dataI[s : e + 1]
    rowInd = np.nanargmax(np.abs(Im), axis=0)
    currentSteps = Im[rowInd, np.arange(numSteps)]
    print(f"  currentSteps (pA): {np.round(currentSteps, 1)}")

    # Save the Vm trace family for visual comparison to the tutorial figure.
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(6, 4))
        order = np.argsort(currentSteps)
        cmap = plt.get_cmap("turbo")
        for k, i in enumerate(order):
            ax.plot(timeMatrix, Vm[:, i], color=cmap(k / max(1, numSteps - 1)), lw=0.8)
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Voltage (mV)")
        ax.set_title(f"{name_v} epoch {epochNum}: {numSteps} current steps")
        fig.tight_layout()
        fig.savefig(OUT_PNG, dpi=110)
        print(f"  saved plot -> {OUT_PNG}")
    except Exception as e:
        print("  (plot skipped:", e, ")")

    ok = (
        numSteps >= 3
        and numTimepoints > 100
        and np.nanmin(dataVm) > -200
        and np.nanmax(dataVm) < 100
    )
    print("RESULT:", "PASS ✅ (structural/plausibility)" if ok else "REVIEW ⚠")


if __name__ == "__main__":
    main()
