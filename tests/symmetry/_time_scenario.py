"""Shared, self-describing time/syncgraph symmetry scenario.

Both NDI language ports build referents from ``SCENARIO`` (a pure-JSON spec),
run ``CASES`` through their real ``time_convert`` implementation, and must agree
on the recorded outputs. Keeping the scenario as data (not a persisted session)
makes the artifact reproducible from the spec alone, which is what the MATLAB
``makeArtifacts``/``readArtifacts`` side needs in order to match it.

MATLAB counterpart to author: tests/+ndi/+symmetry/+makeArtifacts/+time/ +
+readArtifacts/+time/ — build the same SCENARIO referents, run CASES, and
compare the ``out_*`` fields to ``timeConvertCases.json``.
"""

from __future__ import annotations

from typing import Any

from ndi.time.clocktype import ndi_time_clocktype
from ndi.time.syncgraph import ndi_time_syncgraph
from ndi.time.timereference import ndi_time_timereference

# A referent ("probeA") with two epochs, each carrying a device-local clock and
# an experiment-global clock with known, distinct windows so every conversion is
# unambiguous and exactly reproducible.
SCENARIO: dict[str, Any] = {
    "referents": [
        {
            "name": "probeA",
            "id": "id_probeA",
            "epochs": [
                {
                    "epoch_id": "ep1",
                    "epoch_clock": ["dev_local_time", "exp_global_time"],
                    "t0_t1": [[0.0, 10.0], [100.0, 110.0]],
                },
                {
                    "epoch_id": "ep2",
                    "epoch_clock": ["dev_local_time", "exp_global_time"],
                    "t0_t1": [[0.0, 5.0], [200.0, 205.0]],
                },
            ],
        }
    ],
}

# Each case names an input (referent, clock, epoch, time) and an output
# (referent, clock); the generator fills in out_time / out_epoch / msg.
CASES: list[dict[str, Any]] = [
    # same-clock passthrough
    {
        "in_ref": "probeA",
        "in_clock": "dev_local_time",
        "in_epoch": "ep1",
        "in_time": 5.0,
        "out_ref": "probeA",
        "out_clock": "dev_local_time",
    },
    # cross-clock rescale (dev_local 5 in [0,10] -> exp_global 105 in [100,110])
    {
        "in_ref": "probeA",
        "in_clock": "dev_local_time",
        "in_epoch": "ep1",
        "in_time": 5.0,
        "out_ref": "probeA",
        "out_clock": "exp_global_time",
    },
    # endpoints
    {
        "in_ref": "probeA",
        "in_clock": "dev_local_time",
        "in_epoch": "ep1",
        "in_time": 0.0,
        "out_ref": "probeA",
        "out_clock": "exp_global_time",
    },
    {
        "in_ref": "probeA",
        "in_clock": "dev_local_time",
        "in_epoch": "ep1",
        "in_time": 10.0,
        "out_ref": "probeA",
        "out_clock": "exp_global_time",
    },
    # a second epoch with a different mapping (dev_local 2.5 in [0,5] -> 202.5 in [200,205])
    {
        "in_ref": "probeA",
        "in_clock": "dev_local_time",
        "in_epoch": "ep2",
        "in_time": 2.5,
        "out_ref": "probeA",
        "out_clock": "exp_global_time",
    },
    # empty-epoch resolution: a global time resolves to the owning epoch
    {
        "in_ref": "probeA",
        "in_clock": "exp_global_time",
        "in_epoch": None,
        "in_time": 105.0,
        "out_ref": "probeA",
        "out_clock": "exp_global_time",
    },
    {
        "in_ref": "probeA",
        "in_clock": "exp_global_time",
        "in_epoch": None,
        "in_time": 202.5,
        "out_ref": "probeA",
        "out_clock": "exp_global_time",
    },
]


class _Sess:
    def id(self) -> str:
        return "sess1"


class _SpecRef:
    """A real epochset-like referent built from a SCENARIO entry."""

    def __init__(self, spec: dict[str, Any]):
        self._spec = spec
        self.session = _Sess()

    def id(self) -> str:
        return self._spec["id"]

    def epochsetname(self) -> str:
        return self._spec["name"]

    def epochtable(self):
        et = [
            {
                "epoch_id": e["epoch_id"],
                "epoch_clock": [ndi_time_clocktype(c) for c in e["epoch_clock"]],
                "t0_t1": [tuple(x) for x in e["t0_t1"]],
            }
            for e in self._spec["epochs"]
        ]
        return et, "hash"


def build_referents() -> dict[str, _SpecRef]:
    return {r["name"]: _SpecRef(r) for r in SCENARIO["referents"]}


def run_cases() -> list[dict[str, Any]]:
    """Run every CASE through the real syncgraph and return cases + outputs."""
    refs = build_referents()
    sg = ndi_time_syncgraph(session=None)
    out: list[dict[str, Any]] = []
    for c in CASES:
        rin, rout = refs[c["in_ref"]], refs[c["out_ref"]]
        tin = ndi_time_timereference(rin, ndi_time_clocktype(c["in_clock"]), c["in_epoch"], 0)
        rec = dict(c)
        try:
            t, ref, msg = sg.time_convert(
                tin, c["in_time"], rout, ndi_time_clocktype(c["out_clock"])
            )
            rec["out_time"] = None if t is None else round(float(t), 9)
            rec["out_epoch"] = getattr(ref, "epoch", None) if ref is not None else None
            rec["msg"] = msg
        except Exception as exc:  # record errors as data so symmetry can compare them too
            rec["out_time"], rec["out_epoch"] = None, None
            rec["msg"] = f"ERROR:{type(exc).__name__}"
        out.append(rec)
    return out
