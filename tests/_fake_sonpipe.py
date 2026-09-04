#!/usr/bin/env python3
"""A stand-in for the sonpipe CLI, for testing NDI's CED reader without CED's sonpy.

Mirrors NDR-python's tests/fake_sonpipe.py. Vendored here so this repo's
test matrix (Python 3.10-3.12, where sonpy has no wheel) can exercise the
CED wrapper end-to-end without a sibling checkout of NDR-python. The real
integration path lives in tests/test_cedspike2_integration.py, which runs
against actual sonpipe on Python 3.14 in the ced-integration CI job. Any
drift between the two copies -- CLI shape, JSON keys, sentinel line --
would be caught there.

sonpy cannot be installed on Linux or macOS for CPython 3.10-3.13 (see
ndr/format/ced/sonpipe/executable.py), so the real CLI cannot run in CI on the
Python versions NDR-python supports. This reproduces the parts of the CLI
contract NDR depends on -- the JSON shapes, the raw little-endian stdout, and
the completion sentinel on stderr -- so the invoke, parse, and dispatch layers
are exercised for real.

Fault injection, via the FAKE_SONPIPE_FAULT environment variable:
  nosentinel  write the data but no completion sentinel (a mid-stream abort)
  truncate    write fewer values than the sentinel claims
  fail        exit non-zero
  badjson     emit text that is not JSON
"""

import argparse
import json
import os
import sys

import numpy as np

SAMPLERATE = 1000.0
NUM_SAMPLES = 500
TIMEBASE = 1e-6

CHANNELS = [
    {
        "number": 1,
        "index": 0,
        "kind": 1,
        "kind_name": "Adc",
        "ndr_type": "analog_in",
        "title": "wave",
        "units": "V",
        "comment": "",
        "max_time_ticks": 500000,
        "max_time": 0.5,
        "sampleinterval": 1.0 / SAMPLERATE,
        "samplerate": SAMPLERATE,
        "divide": 1,
        "ideal_rate": SAMPLERATE,
        "scale": 1.0,
        "offset": 0.0,
        "num_samples": NUM_SAMPLES,
    },
    {
        "number": 2,
        "index": 1,
        "kind": 3,
        "kind_name": "EventRise",
        "ndr_type": "event",
        "title": "evt",
        "units": "",
        "comment": "",
        "max_time_ticks": 1000000,
        "max_time": 1.0,
        "sampleinterval": None,
        "samplerate": None,
        "divide": None,
        "ideal_rate": None,
        "scale": None,
        "offset": None,
        "num_samples": None,
    },
    {
        "number": 3,
        "index": 2,
        "kind": 5,
        "kind_name": "Marker",
        "ndr_type": "mark",
        "title": "mk",
        "units": "",
        "comment": "",
        "max_time_ticks": 1000000,
        "max_time": 1.0,
        "sampleinterval": None,
        "samplerate": None,
        "divide": None,
        "ideal_rate": None,
        "scale": None,
        "offset": None,
        "num_samples": None,
    },
]

EVENT_TIMES = np.array([0.1, 0.2, 0.35, 0.5, 0.75], dtype=np.float64)
MARKERS = [
    {"time": 0.15, "code": 11},
    {"time": 0.45, "code": 22},
    {"time": 0.85, "code": 33},
]


def waveform():
    """Sample i has value i, so a wrong --start or --count is visible."""
    return np.arange(NUM_SAMPLES, dtype=np.float64)


def channel(number):
    for c in CHANNELS:
        if c["number"] == number:
            return c
    raise SystemExit(f"fake_sonpipe: channel {number} not recorded")


def emit_binary(arr, label):
    fault = os.environ.get("FAKE_SONPIPE_FAULT", "")
    out = arr[:-2] if fault == "truncate" else arr
    sys.stdout.buffer.write(np.ascontiguousarray(out, dtype="<f8").tobytes())
    sys.stdout.buffer.flush()
    if fault != "nosentinel":
        sys.stderr.write(f"sonpipe: wrote {arr.size} {label} (double) for channel 1\n")
        sys.stderr.flush()


def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument("--version", action="store_true")
    sub = p.add_subparsers(dest="cmd")

    ph = sub.add_parser("header")
    ph.add_argument("file")

    ps = sub.add_parser("sampleinterval")
    ps.add_argument("file")
    ps.add_argument("-c", "--channel", type=int, required=True)

    pr = sub.add_parser("read")
    pr.add_argument("file")
    pr.add_argument("-c", "--channel", type=int, required=True)
    pr.add_argument("--start", type=int, default=None)
    pr.add_argument("--count", type=int, default=None)
    pr.add_argument("--t0", type=float, default=None)
    pr.add_argument("--t1", type=float, default=None)
    pr.add_argument("--json", action="store_true")

    args = p.parse_args(argv)

    if args.version or args.cmd is None:
        # Discovery probes --version, so it must succeed even under a fault;
        # otherwise executable() fails first and the fault is never exercised.
        print("fake-sonpipe 0.0.0")
        return 0

    if os.environ.get("FAKE_SONPIPE_FAULT") == "fail":
        sys.stderr.write("fake_sonpipe: simulated failure\n")
        return 3

    if os.environ.get("FAKE_SONPIPE_FAULT") == "badjson" and args.cmd != "read":
        print("this is not json")
        return 0

    if args.cmd == "header":
        json.dump(
            {
                "fileinfo": {
                    "path": args.file,
                    "timebase": TIMEBASE,
                    "max_channels": 32,
                    "max_time_ticks": 1000000,
                    "max_time": 1.0,
                    "version": 9,
                    "app_id": "S64",
                },
                "channelinfo": CHANNELS,
            },
            sys.stdout,
        )
        return 0

    if args.cmd == "sampleinterval":
        c = channel(args.channel)
        json.dump(
            {
                "channel": c["number"],
                "kind": c["kind"],
                "kind_name": c["kind_name"],
                "sampleinterval": c["sampleinterval"],
                "samplerate": c["samplerate"],
                "total_samples": c["num_samples"],
                "total_time": c["max_time"],
            },
            sys.stdout,
        )
        return 0

    c = channel(args.channel)
    if c["kind"] == 1:
        data = waveform()
        start = args.start or 0
        count = args.count if args.count is not None else data.size - start
        emit_binary(data[start : start + count], "samples")
        return 0

    if c["kind"] == 3:
        times = EVENT_TIMES
        if args.t0 is not None:
            times = times[times >= args.t0]
        if args.t1 is not None:
            times = times[times <= args.t1]
        emit_binary(times, "event times")
        return 0

    markers = MARKERS
    if args.t0 is not None:
        markers = [m for m in markers if m["time"] >= args.t0]
    if args.t1 is not None:
        markers = [m for m in markers if m["time"] <= args.t1]
    json.dump({"channel": c["number"], "kind": c["kind"], "markers": markers}, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
