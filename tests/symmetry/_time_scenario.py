"""Shared, self-describing time/syncgraph symmetry scenario (Python side).

Python counterpart of NDI-matlab's ``tests/+ndi/+symmetry/+time/scenario.m``.
Both language ports build a referent from the same ``SCENARIO`` (a referent with
two multi-clock epochs), run the same ``CASES`` through their real
``ndi.time.syncgraph.time_convert``, and must agree on the recorded outputs
(``out_time`` / ``out_epoch`` / ``msg``) written to ``timeConvertCases.json``.

Every case is same-referent (``in_ref == out_ref == "probeA"``), so
``time_convert`` resolves it from the referent's epoch table alone (the
same-referent fast path) -- no syncgraph construction, no DAQ readers.

MATLAB is the symmetry reference: :func:`expected` lists the authoritative
outputs and the makeArtifacts test asserts each case matches before writing the
artifact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ndi.time.clocktype import ndi_time_clocktype
from ndi.time.syncgraph import ndi_time_syncgraph
from ndi.time.timereference import ndi_time_timereference

# The data the referent + the JSON "scenario" block are built from.
# Mirrors the MATLAB scenario.scenarioStruct().
SCENARIO: dict[str, Any] = {
    "referents": [
        {
            "name": "probeA",
            "id": "id_probeA",
            "epochs": [
                {
                    "epoch_id": "ep1",
                    "clocks": ["dev_local_time", "exp_global_time"],
                    "t0_t1": [[0, 10], [100, 110]],
                },
                {
                    "epoch_id": "ep2",
                    "clocks": ["dev_local_time", "exp_global_time"],
                    "t0_t1": [[0, 5], [200, 205]],
                },
            ],
        }
    ]
}

# Session id used by the throwaway referent/timereferences. The same-referent
# fast path never consults the syncgraph, so the value only needs to be stable.
_SESSION_ID = "symref_time_scenario"


@dataclass
class _SpecRef:
    """A minimal referent built straight from ``SCENARIO``.

    Provides exactly the contract the same-referent ``time_convert`` path needs:
    a name (``epochsetname``), a session id, an ``epochtable`` of multi-clock
    epochs, and ``==`` so ``timeref_in.referent == referent_out`` holds. This is
    the Python analogue of the real ``ndi.element`` the MATLAB scenario builds.
    """

    name: str
    id: str
    session_id: str = _SESSION_ID
    _epochs: list[dict[str, Any]] = field(default_factory=list)

    def epochsetname(self) -> str:
        return self.name

    def epochtable(self) -> list[dict[str, Any]]:
        # Each entry mirrors ndi.epoch.epochset epochtable rows: clocks become
        # ndi_time_clocktype objects, t0_t1 a parallel list of (t0, t1) tuples.
        table = []
        for e in self._epochs:
            table.append(
                {
                    "epoch_id": e["epoch_id"],
                    "epoch_clock": [ndi_time_clocktype.from_string(c) for c in e["clocks"]],
                    "t0_t1": [tuple(float(x) for x in r) for r in e["t0_t1"]],
                }
            )
        return table

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _SpecRef):
            return NotImplemented
        return self.name == other.name and self.id == other.id

    def __hash__(self) -> int:
        return hash((self.name, self.id))


def build_referent() -> _SpecRef:
    """Construct the scenario referent from ``SCENARIO`` (mirrors buildReferent)."""
    r = SCENARIO["referents"][0]
    return _SpecRef(name=r["name"], id=r["id"], _epochs=r["epochs"])


def case_defs() -> list[dict[str, Any]]:
    """The 7 input cases. ``out_*`` are placeholders filled by :func:`run_cases`.

    Mirrors the MATLAB scenario.caseDefs(); missing epochs are ``None`` (JSON
    null) and missing times are ``None`` (NaN on the MATLAB side).
    """

    def mk(in_ref, in_clock, in_epoch, in_time, out_ref, out_clock):
        return {
            "in_ref": in_ref,
            "in_clock": in_clock,
            "in_epoch": in_epoch,
            "in_time": in_time,
            "out_ref": out_ref,
            "out_clock": out_clock,
            "out_time": None,
            "out_epoch": None,
            "msg": "",
        }

    return [
        mk("probeA", "dev_local_time", "ep1", 5.0, "probeA", "dev_local_time"),
        mk("probeA", "dev_local_time", "ep1", 5.0, "probeA", "exp_global_time"),
        mk("probeA", "dev_local_time", "ep1", 0.0, "probeA", "exp_global_time"),
        mk("probeA", "dev_local_time", "ep1", 10.0, "probeA", "exp_global_time"),
        mk("probeA", "dev_local_time", "ep2", 2.5, "probeA", "exp_global_time"),
        mk("probeA", "exp_global_time", None, 105.0, "probeA", "exp_global_time"),
        mk("probeA", "exp_global_time", None, 202.5, "probeA", "exp_global_time"),
    ]


def run_cases() -> list[dict[str, Any]]:
    """Run every case through the real ``time_convert``; return filled cases.

    Errors are recorded as data (``msg = "ERROR:..."``) rather than raised,
    mirroring the MATLAB scenario.runCases().
    """
    defs = case_defs()
    referent = build_referent()
    sg = ndi_time_syncgraph(session=None)  # graph unused on the same-referent path
    results = []
    for c in defs:
        out = dict(c)
        ct_in = ndi_time_clocktype.from_string(c["in_clock"])
        ct_out = ndi_time_clocktype.from_string(c["out_clock"])
        try:
            tref_in = ndi_time_timereference(
                referent=referent,
                clocktype=ct_in,
                epoch=c["in_epoch"],
                time=0,
            )
            t_out, tref_out, msg = sg.time_convert(tref_in, c["in_time"], referent, ct_out)
            if msg and msg.startswith("ERROR:"):
                out["out_time"] = None
                out["out_epoch"] = None
                out["msg"] = msg
            else:
                out["out_time"] = None if t_out is None else round(float(t_out), 9)
                out["out_epoch"] = tref_out.epoch if tref_out is not None else None
                out["msg"] = msg or ""
        except Exception as exc:  # record errors as data, like MATLAB
            out["out_time"] = None
            out["out_epoch"] = None
            out["msg"] = f"ERROR:{type(exc).__name__}"
        results.append(out)
    return results


def expected() -> list[dict[str, Any]]:
    """MATLAB-authoritative correct outputs for :func:`case_defs`, in order.

    Within an epoch, time rescales linearly between the two clocks' ranges, and
    same-clock conversions are the identity.
    """
    return [
        {"exp_time": 5.0, "exp_epoch": "ep1"},  # dev_local identity
        {"exp_time": 105.0, "exp_epoch": "ep1"},  # [0 10]->[100 110]: 5->105
        {"exp_time": 100.0, "exp_epoch": "ep1"},  # 0->100
        {"exp_time": 110.0, "exp_epoch": "ep1"},  # 10->110
        {"exp_time": 202.5, "exp_epoch": "ep2"},  # ep2 [0 5]->[200 205]: 2.5->202.5
        {"exp_time": 105.0, "exp_epoch": "ep1"},  # exp_global identity (in ep1)
        {"exp_time": 202.5, "exp_epoch": "ep2"},  # exp_global identity (in ep2)
    ]


def verify_expected(results: list[dict[str, Any]]) -> None:
    """Assert computed RESULTS match the expected (reference) outputs."""
    exp = expected()
    assert len(results) == len(exp), f"Number of results ({len(results)}) != expected ({len(exp)})."
    for i, (r, e) in enumerate(zip(results, exp)):
        assert r["msg"] == "", f"Case {i} produced error: {r['msg']!r}"
        assert r["out_time"] is not None, f"Case {i} out_time is null."
        assert (
            abs(float(r["out_time"]) - e["exp_time"]) < 1e-9
        ), f"Case {i} out_time mismatch: {r['out_time']} != {e['exp_time']}"
        assert (
            r["out_epoch"] == e["exp_epoch"]
        ), f"Case {i} out_epoch mismatch: {r['out_epoch']} != {e['exp_epoch']}"
