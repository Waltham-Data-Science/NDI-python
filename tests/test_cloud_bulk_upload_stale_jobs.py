"""``waitForAllBulkUploads`` ignores abandoned uploads and old failures.

MATLAB counterpart: NDI-matlab ``cb0134b`` (VH-Lab/NDI-matlab#1189);
server side: Waltham-Data-Science/ndi-cloud-node#172.

THE BUG. The server creates a bulk-upload job in state ``'queued'`` as soon
as a client asks for an upload URL, and the job only moves on when the zip
arrives. An upload that failed or was interrupted left a ``'queued'`` job
behind that counted as active forever, so on a real dataset every sync spent
the wait's whole deadline at its bulk-upload boundary. Tests never saw it:
they use fresh datasets, which have no leftover jobs.

Separately, ``require_all_complete`` counted every failure in the listing's
history window, so one bad upload kept reporting ``'failed'`` for a day.

These tests build job dicts locally and stub the listing, so they need no
network.
"""

from __future__ import annotations

import time as time_module
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from ndi.cloud.api import files as files_api
from ndi.cloud.api.files import (
    _format_server_time,
    _jobs_completed_since,
    _parse_server_time,
    _partition_stale_jobs,
)

DATASET_ID = "65a1b2c3d4e5f60718293a4b"
NOW = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return _format_server_time(dt)


def _job(job_id: str, state: str, created: str, **extra) -> dict:
    return {"jobId": job_id, "state": state, "createdAt": created, **extra}


class TestParseServerTime:
    EXPECTED = datetime(2026, 11, 5, 12, 34, 56, tzinfo=timezone.utc)

    @pytest.mark.parametrize(
        "text",
        [
            "2026-11-05T12:34:56.789Z",
            "2026-11-05T12:34:56Z",
            "2026-11-05T12:34:56.123456Z",
            "2026-11-05T12:34:56+00:00",
            "2026-11-05T13:34:56+01:00",
            "2026-11-05T12:34:56",
        ],
    )
    def test_formats_parse_to_utc(self, text):
        assert _parse_server_time(text) == self.EXPECTED

    @pytest.mark.parametrize("bad", [None, "", "   ", "not a date", 42])
    def test_bad_input_is_none(self, bad):
        assert _parse_server_time(bad) is None

    def test_format_round_trips(self):
        dt = datetime(2026, 11, 5, 12, 0, 0, 123456, tzinfo=timezone.utc)
        assert _format_server_time(dt) == "2026-11-05T12:00:00.123Z"
        assert _parse_server_time(_format_server_time(dt)) == dt.replace(microsecond=0)

    def test_format_treats_naive_as_utc_and_converts_zoned(self):
        assert _format_server_time(datetime(2026, 11, 5, 12)) == "2026-11-05T12:00:00.000Z"
        plus_one = datetime(2026, 11, 5, 13, tzinfo=timezone(timedelta(hours=1)))
        assert _format_server_time(plus_one) == "2026-11-05T12:00:00.000Z"


class TestPartitionStaleJobs:
    def test_old_queued_job_is_stale(self):
        old = _job("old", "queued", "2026-11-04T12:00:00.000Z")
        new = _job("new", "queued", "2026-11-05T11:55:00.000Z")
        live, stale = _partition_stale_jobs([old, new], 3600, NOW)
        assert live == [new]
        assert stale == [old]

    def test_extracting_job_is_never_stale(self):
        """A big extraction can run for hours; only the server can tell
        slow from dead, so the client always waits for it."""
        job = _job("x", "extracting", "2026-11-04T09:00:00Z", startedAt="2026-11-04T09:01:00Z")
        live, stale = _partition_stale_jobs([job], 3600, NOW)
        assert live == [job]
        assert stale == []

    def test_unparseable_created_at_is_kept_live(self):
        job = _job("q", "queued", "garbage")
        live, stale = _partition_stale_jobs([job], 3600, NOW)
        assert live == [job]
        assert stale == []

    def test_empty(self):
        assert _partition_stale_jobs([], 3600, NOW) == ([], [])


class TestJobsCompletedSince:
    SINCE = datetime(2026, 11, 5, 11, 0, 0, tzinfo=timezone.utc)

    def test_only_recent_failures_count(self):
        old = _job("old", "failed", "2026-10-01T00:00:00Z", completedAt="2026-10-01T00:05:00Z")
        # Created before the cutoff but failed after it: counts.
        recent = _job(
            "recent", "failed", "2026-11-05T09:00:00Z", completedAt="2026-11-05T11:30:00Z"
        )
        assert _jobs_completed_since([old, recent], self.SINCE) == [recent]

    def test_missing_completed_at_falls_back_to_created_at(self):
        old = _job("old", "failed", "2026-10-01T00:00:00Z")
        assert _jobs_completed_since([old], self.SINCE) == []

    def test_no_usable_time_is_kept(self):
        """Err toward reporting a failure when the server response is odd."""
        odd = _job("odd", "failed", "garbage")
        assert _jobs_completed_since([odd], self.SINCE) == [odd]

    def test_empty(self):
        assert _jobs_completed_since([], self.SINCE) == []


class TestWaitForAllBulkUploads:
    """The wait loop, against a stubbed listing."""

    @staticmethod
    def _run(listings, **kwargs):
        """Call the wait with ``listActiveBulkUploads`` returning *listings*
        in turn (the last one repeats). Returns (result, calls, slept)."""
        calls: list[dict] = []
        slept: list[float] = []

        def fake_list(dataset_id, **kw):
            calls.append(kw)
            return listings[min(len(calls), len(listings)) - 1]

        with (
            patch.object(files_api, "listActiveBulkUploads", fake_list),
            patch.object(time_module, "sleep", lambda s: slept.append(s)),
        ):
            result = files_api.waitForAllBulkUploads(DATASET_ID, client=object(), **kwargs)
        return result, calls, slept

    def test_abandoned_queued_job_does_not_hold_the_wait(self):
        """The reported bug: an hour-old queued job made every call sit out
        its whole deadline."""
        abandoned = _job("a", "queued", _iso(datetime.now(timezone.utc) - timedelta(hours=2)))
        result, calls, slept = self._run([{"jobs": [abandoned]}])
        assert result["state"] == "complete"
        assert result["staleJobs"] == [abandoned]
        assert len(calls) == 1
        assert slept == []

    def test_recent_queued_job_is_waited_for(self):
        fresh = _job("f", "queued", _iso(datetime.now(timezone.utc) - timedelta(seconds=10)))
        result, calls, slept = self._run([{"jobs": [fresh]}], timeout=4.0, max_interval=2.0)
        assert result["state"] == "timeout"
        assert result["jobs"] == [fresh]
        assert result["staleJobs"] == []
        assert len(calls) > 1

    def test_long_running_extraction_is_waited_for(self):
        started = _iso(datetime.now(timezone.utc) - timedelta(hours=5))
        job = _job("x", "extracting", started, startedAt=started)
        done = dict(job, state="complete", completedAt=_iso(datetime.now(timezone.utc)))
        result, calls, _ = self._run([{"jobs": [job]}, {"jobs": [done]}])
        assert result["state"] == "complete"
        assert len(calls) == 2

    def test_old_failure_is_history(self):
        long_ago = _iso(datetime.now(timezone.utc) - timedelta(days=30))
        old = _job("old", "failed", long_ago, completedAt=long_ago)
        result, _, _ = self._run([{"jobs": [old]}])
        assert result["state"] == "complete"

    def test_recent_failure_is_reported(self):
        just_now = _iso(datetime.now(timezone.utc) - timedelta(minutes=1))
        failed = _job("f", "failed", just_now, completedAt=just_now)
        result, _, _ = self._run([{"jobs": [failed]}])
        assert result["state"] == "failed"
        assert result["jobs"] == [failed]

    def test_listing_asks_for_recent_terminal_jobs_only(self):
        _, calls, _ = self._run([{"jobs": []}], stale_after=600)
        assert calls[0]["state"] == "all"
        since = calls[0]["since"]
        expected = datetime.now(timezone.utc) - timedelta(seconds=600)
        assert abs((since - expected).total_seconds()) < 5

    def test_without_require_all_complete_lists_active_only(self):
        _, calls, _ = self._run([{"jobs": []}], require_all_complete=False)
        assert calls[0] == {"state": "active", "client": calls[0]["client"]}

    def test_stale_after_must_be_positive(self):
        with pytest.raises(Exception):
            files_api.waitForAllBulkUploads(DATASET_ID, client=object(), stale_after=0)


class TestListActiveBulkUploadsSince:
    @staticmethod
    def _params(**kwargs):
        seen: dict = {}

        class FakeClient:
            def get(self, endpoint, params=None, **path):
                seen["params"] = params
                return {"jobs": []}

        files_api.listActiveBulkUploads(DATASET_ID, client=FakeClient(), **kwargs)
        return seen["params"]

    def test_since_is_sent_as_iso_utc(self):
        params = self._params(state="failed", since=datetime(2026, 11, 5, 10, tzinfo=timezone.utc))
        assert params == {"state": "failed", "since": "2026-11-05T10:00:00.000Z"}

    def test_no_since_by_default(self):
        assert self._params() == {"state": "active"}
