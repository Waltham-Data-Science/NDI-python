"""confirmFilesRecorded: make sure NDI Cloud recorded every file an upload sent.

MATLAB counterpart: tests/+ndi/+unittest/+cloud/+upload/ConfirmFilesRecordedTest.m
(with the fake ndi.test.helper.FakeRecordingServer, mirrored here).

A batch (zip) upload's success only means S3 has the zip; the server records
the files in a later step that can fail without the client hearing of it (a
dataset lost 327 files this way, ndi-cloud-node#175). confirmFilesRecorded
waits for the records, uploads again what is never recorded, and reports
what is still missing. Needs no cloud access.
"""

from __future__ import annotations

import pytest

from ndi.cloud import upload
from ndi.cloud.api import files as files_api

UIDS = ["a", "b", "c"]
PATHS = ["/p/a", "/p/b", "/p/c"]


class FakeRecordingServer:
    """NDI Cloud's file-recording step, scripted.

    Each wait call first records the uids scheduled for it (schedule[n] for
    the n-th call), then reports which of the uids asked about are still
    unrecorded. resend records a uid at once unless it is in never_record (a
    server that keeps failing), refuses it if in refuse_resend, and raises if
    in throw_on_resend (as an upload of a missing local file does).
    """

    def __init__(self, schedule=(), never_record=(), refuse_resend=(), throw_on_resend=()):
        self.schedule = [list(s) for s in schedule]
        self.never_record = set(never_record)
        self.refuse_resend = set(refuse_resend)
        self.throw_on_resend = set(throw_on_resend)
        self.recorded: set[str] = set()
        self.wait_calls = 0
        self.wait_timeouts: list[float] = []
        self.resent: list[str] = []

    def wait(self, ids, timeout):
        self.wait_calls += 1
        self.wait_timeouts.append(timeout)
        if self.wait_calls <= len(self.schedule):
            self.recorded.update(self.schedule[self.wait_calls - 1])
        pending = [u for u in ids if u not in self.recorded]
        return {"state": "timeout" if pending else "complete", "pending": pending}

    def resend(self, uid, path):
        if uid in self.throw_on_resend:
            raise FileNotFoundError(f"No such file: {path}")
        if uid in self.refuse_resend:
            return False, "refused by the fake"
        self.resent.append(uid)
        if uid not in self.never_record:
            self.recorded.add(uid)
        return True, ""


def confirm(S, uids=UIDS, paths=PATHS, **kw):
    return upload.confirmFilesRecorded("d", uids, paths, wait_fcn=S.wait, resend_fcn=S.resend, **kw)


def test_everything_recorded_needs_one_look():
    S = FakeRecordingServer(schedule=[UIDS])
    r = confirm(S)
    assert r["ok"] and r["pending"] == [] and r["message"] == ""
    assert S.wait_calls == 1 and S.resent == []


def test_waiting_goes_on_while_records_arrive():
    # A slow server that keeps recording is waited for, not duplicated.
    S = FakeRecordingServer(schedule=[["a"], ["b"], ["c"]])
    assert confirm(S)["ok"]
    assert S.wait_calls == 3 and S.resent == []


def test_a_file_the_server_dropped_is_sent_again():
    S = FakeRecordingServer(schedule=[["a"], ["b"]])
    r = confirm(S, stall_timeout=7, resend_timeout=3)
    assert r["ok"]
    assert S.resent == ["c"] and r["resent"] == ["c"] and r["pending"] == []
    assert S.wait_timeouts == [
        7,
        7,
        7,
        3,
    ], "stall_timeout while the batch is being recorded, resend_timeout after resending"


def test_a_file_never_recorded_is_a_failure():
    S = FakeRecordingServer(schedule=[["a"]], never_record=["c"])
    r = confirm(S)
    assert not r["ok"]
    assert sorted(S.resent) == ["b", "c"]
    assert r["pending"] == ["c"]
    assert "1 of 3" in r["message"] and "only_missing" in r["message"]


def test_a_resend_that_fails_is_reported():
    S = FakeRecordingServer(schedule=[["a"]], refuse_resend=["b"])
    r = confirm(S)
    assert not r["ok"]
    assert r["pending"] == ["b"] and S.resent == ["c"]
    assert len(r["resend_errors"]) == 1
    assert "refused by the fake" in r["message"]


def test_a_resend_that_raises_is_reported_not_raised():
    S = FakeRecordingServer(schedule=[["a", "b"]], throw_on_resend=["c"])
    r = confirm(S)
    assert not r["ok"]
    assert r["pending"] == ["c"]
    assert "/p/c" in r["resend_errors"][0]


def test_duplicate_uids_are_checked_once():
    S = FakeRecordingServer(schedule=[["a"]])
    assert confirm(S, uids=["a", "b", "b"], paths=["/p/a", "/p/b", "/p/b"])["ok"]
    assert S.resent == ["b"]


def test_no_uids_is_nothing_to_do():
    S = FakeRecordingServer()
    assert confirm(S, uids=[], paths=[])["ok"]
    assert S.wait_calls == 0


def test_paths_must_match_uids():
    with pytest.raises(ValueError):
        upload.confirmFilesRecorded("d", ["a", "b"], ["/p/a"])


def test_the_default_resend_is_a_single_file_upload(monkeypatch):
    sent = []
    monkeypatch.setattr(
        files_api, "getFileUploadURL", lambda org, ds, uid, client=None: f"https://s3/{org}/{uid}"
    )
    monkeypatch.setattr(files_api, "putFiles", lambda url, path, **k: sent.append((url, path)))
    S = FakeRecordingServer(schedule=[["a", "b"], [], ["c"]])
    r = upload.confirmFilesRecorded("d", UIDS, PATHS, org_id="org-1", wait_fcn=S.wait)
    assert r["ok"]
    assert sent == [("https://s3/org-1/c", "/p/c")]
