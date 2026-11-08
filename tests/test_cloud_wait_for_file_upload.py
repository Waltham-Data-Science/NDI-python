"""waitForFileUpload: wait until NDI Cloud records single-file uploads.

MATLAB counterpart: ndi.cloud.api.files.waitForFileUpload (NDI-matlab
eb5832895, VH-Lab/NDI-matlab#1027), exercised there through FilesTest. A PUT
returning 200 means S3 has the bytes; the cloud marks the file ``uploaded``
a little later, and this polls lookupFiles until it has.
"""

from __future__ import annotations

from unittest.mock import patch

from ndi.cloud.api import files as files_api

DS = "aaaaaaaaaaaaaaaaaaaaaaaa"


def run(rounds, **kw):
    """Call waitForFileUpload with lookupFiles answering from ROUNDS in turn."""
    calls = []

    def lookup(ds, uids, client=None):
        calls.append(list(uids))
        r = rounds[min(len(calls) - 1, len(rounds) - 1)]
        if isinstance(r, Exception):
            raise r
        return {"files": [{"uid": u, "uploaded": u in r} for u in uids], "missing": []}

    with (
        patch.object(files_api, "lookupFiles", lookup),
        patch.object(files_api.time, "sleep", lambda s: None),
    ):
        return files_api.waitForFileUpload(DS, ["a", "b", "a"], client=object(), **kw), calls


def test_returns_once_every_uid_is_recorded():
    answer, calls = run([{"a"}, {"a", "b"}])
    assert answer["state"] == "complete" and answer["pending"] == []
    assert calls == [["a", "b"], ["b"]], "asks only about the uids still pending, once each"
    assert sorted(r["uid"] for r in answer["files"]) == ["a", "b"]


def test_a_failed_poll_is_retried():
    answer, calls = run([RuntimeError("502"), {"a", "b"}])
    assert answer["state"] == "complete"
    assert len(calls) == 2


def test_times_out_naming_what_is_pending():
    times = iter([0.0, 0.0, 50.0, 200.0, 200.0])
    with patch.object(files_api.time, "monotonic", lambda: next(times)):
        answer, _ = run([{"a"}], timeout=120)
    assert answer["state"] == "timeout"
    assert answer["pending"] == ["b"]
    assert answer["elapsed"] >= 120
