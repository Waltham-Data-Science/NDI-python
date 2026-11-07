"""Abandoned and old bulk-upload jobs do not hold up waitForAllBulkUploads.

MATLAB counterpart: tests/+ndi/+unittest/+cloud/WaitForAllBulkUploadsStaleJobsTest.m
(NDI-matlab 7c6e9ed09, 7f7200034). A 'queued' job older than staleAfter is an
upload that never arrived; a failure older than that window is history.
"""

from __future__ import annotations

import datetime as dt
from unittest.mock import patch

from ndi.cloud.api import files as files_api
from ndi.cloud.api.files import _parse_timestamp, jobsCompletedSince, partitionStaleJobs

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 5, 12, 0, 0, tzinfo=UTC)


def iso(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S.123Z")


class TestParseTimestamp:
    def test_formats(self):
        expected = dt.datetime(2026, 11, 5, 12, 34, 56, tzinfo=UTC)
        for text in (
            "2026-11-05T12:34:56.789Z",
            "2026-11-05T12:34:56Z",
            "2026-11-05T12:34:56+00:00",
            "2026-11-05T12:34:56",
            "2026-11-05T12:34:56.123456789Z",
        ):
            t = _parse_timestamp(text)
            assert t is not None, text
            assert abs((t - expected).total_seconds()) < 1
        t = _parse_timestamp("2026-11-05T14:34:56+02:00")
        assert abs((t - expected).total_seconds()) < 1

    def test_bad_input_is_none(self):
        for bad in ("", "   ", "not a time", None, 5):
            assert _parse_timestamp(bad) is None


class TestPartition:
    def test_an_old_queued_job_is_stale(self):
        jobs = [
            {"jobId": "old", "state": "queued", "createdAt": iso(NOW - dt.timedelta(hours=2))},
            {"jobId": "new", "state": "queued", "createdAt": iso(NOW - dt.timedelta(minutes=5))},
        ]
        live, stale = partitionStaleJobs(jobs, 3600, NOW)
        assert [j["jobId"] for j in live] == ["new"]
        assert [j["jobId"] for j in stale] == ["old"]

    def test_an_extracting_job_is_never_stale(self):
        jobs = [{"state": "extracting", "createdAt": iso(NOW - dt.timedelta(days=1))}]
        live, stale = partitionStaleJobs(jobs, 3600, NOW)
        assert len(live) == 1 and stale == []

    def test_an_unreadable_time_is_kept_live(self):
        live, stale = partitionStaleJobs([{"state": "queued", "createdAt": "garbage"}], 3600, NOW)
        assert len(live) == 1 and stale == []

    def test_no_jobs(self):
        assert partitionStaleJobs([], 3600, NOW) == ([], [])
        assert jobsCompletedSince([], NOW) == []


class TestRecentFailures:
    def test_only_recent_failures_count(self):
        since = NOW - dt.timedelta(hours=1)
        jobs = [
            {"jobId": "old", "completedAt": iso(NOW - dt.timedelta(days=3))},
            {"jobId": "recent", "completedAt": iso(NOW - dt.timedelta(minutes=10))},
        ]
        assert [j["jobId"] for j in jobsCompletedSince(jobs, since)] == ["recent"]

    def test_without_completed_at_created_at_is_used(self):
        jobs = [{"createdAt": iso(NOW - dt.timedelta(days=3))}]
        assert jobsCompletedSince(jobs, NOW - dt.timedelta(hours=1)) == []

    def test_a_failure_with_no_usable_time_is_kept(self):
        jobs = [{"jobId": "x", "completedAt": "garbage"}]
        assert len(jobsCompletedSince(jobs, NOW)) == 1


class TestTheWait:
    def _wait(self, listing, **kwargs):
        seen = []

        def fake_list(dataset_id, **kw):
            seen.append(kw)
            return listing

        with (
            patch.object(files_api, "listActiveBulkUploads", fake_list),
            patch.object(files_api.time, "sleep", lambda s: None),
        ):
            result = files_api.waitForAllBulkUploads("d1", client=object(), timeout=5, **kwargs)
        return result, seen

    def test_an_abandoned_upload_does_not_hold_up_the_wait(self):
        now = dt.datetime.now(UTC)
        old = {"jobId": "a", "state": "queued", "createdAt": iso(now - dt.timedelta(hours=3))}
        result, seen = self._wait({"jobs": [old]})
        assert result["state"] == "complete"
        assert result["staleJobs"] == [old]
        assert "since" in seen[0], "recent failures are asked for with 'since'"

    def test_an_old_failure_is_history(self):
        now = dt.datetime.now(UTC)
        failed = {"state": "failed", "completedAt": iso(now - dt.timedelta(days=2))}
        result, _ = self._wait({"jobs": [failed]})
        assert result["state"] == "complete"

    def test_a_recent_failure_fails_the_wait(self):
        now = dt.datetime.now(UTC)
        failed = {"state": "failed", "completedAt": iso(now - dt.timedelta(minutes=2))}
        result, _ = self._wait({"jobs": [failed]})
        assert result["state"] == "failed"
        assert result["jobs"] == [failed]

    def test_since_is_sent_as_utc_milliseconds(self):
        sent = {}

        class Client:
            def get(self, path, params=None, **kw):
                sent.update(params)
                return {"jobs": []}

        t = dt.datetime(2026, 11, 5, 14, 0, 0, 250000, tzinfo=dt.timezone(dt.timedelta(hours=2)))
        files_api.listActiveBulkUploads("d1", state="failed", since=t, client=Client())
        assert sent == {"state": "failed", "since": "2026-11-05T12:00:00.250Z"}
