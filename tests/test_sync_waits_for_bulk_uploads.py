"""Every sync entry point waits for in-flight bulk uploads before inventorying.

MATLAB counterpart: NDI-matlab ``c425cd115`` wires
``ndi.cloud.api.files.waitForAllBulkUploads`` into all five sync entry
points, right after the dataset id is resolved and before the first
remote-state inventory.

THE RACE. A bulk upload arrives as a zip that a server-side worker then
extracts. Until it finishes, ``listFiles`` can report ``uploaded=true`` --
the zip is there -- while the per-file objects do not exist yet. A sync
that inventories in that window builds its whole plan on a picture that is
about to change, and what follows looks like intermittent cloud flakiness
rather than a race with a known cause.

``waitForAllBulkUploads`` was ported, and its docstring says callers
should do exactly this at sync boundaries. Nothing called it. That is the
shape of gap this burn-down keeps finding: the function is present, so a
reader checking whether the feature was ported would say yes.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ndi.cloud.sync.mode import SyncOptions

ENTRY_POINTS = ["uploadNew", "downloadNew", "mirrorToRemote", "mirrorFromRemote", "twoWaySync"]

DATASET_ID = "65a1b2c3d4e5f60718293a4b"


@pytest.fixture
def calls(tmp_path):
    """Run each entry point against stubs, recording the wait calls.

    The remote inventory and the document API are stubbed to empty, so
    each entry point does its bookkeeping and returns without touching
    the network.
    """
    from ndi.cloud.sync import operations

    def run(name, options):
        recorded: list[str] = []

        def fake_wait(dataset_id, **kwargs):
            recorded.append(dataset_id)
            return {"state": "complete", "jobs": [], "elapsed": 0.0}

        files_api = MagicMock()
        files_api.waitForAllBulkUploads = fake_wait

        with (
            patch.dict("sys.modules", {}),
            patch("ndi.cloud.api.files.waitForAllBulkUploads", fake_wait),
            patch("ndi.cloud.internal.listRemoteDocumentIds", lambda *a, **k: {}),
        ):
            getattr(operations, name)(str(tmp_path), DATASET_ID, options)
        return recorded

    return run


class TestTheWaitHappens:
    @pytest.mark.parametrize("entry_point", ENTRY_POINTS)
    def test_each_entry_point_waits_before_inventorying(self, entry_point, calls):
        assert calls(entry_point, SyncOptions()) == [DATASET_ID]


class TestADryRunDoesNotWait:
    """A dry run inventories to report and changes nothing, so it has no
    reason to block on someone else's upload. MATLAB skips it too."""

    @pytest.mark.parametrize("entry_point", ENTRY_POINTS)
    def test_each_entry_point_skips_the_wait(self, entry_point, calls):
        assert calls(entry_point, SyncOptions(dry_run=True)) == []


class TestAFailedWaitDoesNotStopTheSync:
    """The inventory that follows is then merely as stale as it was before
    this existed. Refusing to sync at all would be the worse answer."""

    def _run_with(self, tmp_path, wait):
        from ndi.cloud.sync import operations

        with (
            patch("ndi.cloud.api.files.waitForAllBulkUploads", wait),
            patch("ndi.cloud.internal.listRemoteDocumentIds", lambda *a, **k: {}),
        ):
            return operations.uploadNew(str(tmp_path), DATASET_ID, SyncOptions())

    def test_a_raising_wait_is_logged_and_survived(self, tmp_path, caplog):
        def boom(dataset_id, **kwargs):
            raise RuntimeError("cloud unreachable")

        with caplog.at_level("WARNING", logger="ndi.cloud.sync.operations"):
            report = self._run_with(tmp_path, boom)
        assert report["mode"] == "upload_new"
        assert "cloud unreachable" in caplog.text

    def test_a_timeout_is_logged_and_survived(self, tmp_path, caplog):
        def timed_out(dataset_id, **kwargs):
            return {"state": "timeout", "jobs": [{"id": "j1"}], "elapsed": 300.0}

        with caplog.at_level("WARNING", logger="ndi.cloud.sync.operations"):
            report = self._run_with(tmp_path, timed_out)
        assert report["mode"] == "upload_new"
        assert "did not settle" in caplog.text

    def test_a_complete_wait_logs_nothing(self, tmp_path, caplog):
        def complete(dataset_id, **kwargs):
            return {"state": "complete", "jobs": [], "elapsed": 1.0}

        with caplog.at_level("WARNING", logger="ndi.cloud.sync.operations"):
            self._run_with(tmp_path, complete)
        assert "did not settle" not in caplog.text


class TestTheWaitCannotSwallowTheClock:
    """The regression that made this whole boundary unaffordable.

    ``waitForAllBulkUploads`` polls until no bulk-upload job is active, and
    treats a failed poll as "still active, let the timeout govern". That is
    right for a blip partway through a real wait. It was applied to the very
    first poll too -- so a deployment where the listing never works at all
    (no bulk-upload service, an endpoint that 404s, credentials that do not
    reach it) sat out the entire 300s deadline, learned nothing, and did it
    again on the next call.

    Wiring the wait into all five sync entry points turned that into 300s
    per sync operation. It did not show up locally, where no cloud client
    can be built and the call raises immediately; it showed up in CI, where
    credentials exist and the poll loop is actually entered.
    """

    def test_a_first_poll_failure_returns_at_once(self):
        """Nothing has been observed, so the error is not evidence of
        activity -- it is evidence the wait cannot be performed."""
        import time as time_module

        from ndi.cloud.api import files as files_api

        def unavailable(*a, **k):
            raise RuntimeError("404 /files/bulk")

        slept: list[float] = []
        with (
            patch.object(files_api, "listActiveBulkUploads", unavailable),
            patch.object(time_module, "sleep", lambda s: slept.append(s)),
        ):
            result = files_api.waitForAllBulkUploads(DATASET_ID, client=object())

        assert result["state"] == "unavailable"
        assert "404" in result["error"]
        assert slept == [], "an unavailable endpoint must not be polled again"

    def test_a_blip_after_a_good_poll_is_still_ridden_out(self):
        """The forgiving behaviour is kept where it was earned: one failed
        poll mid-wait must not abandon a real extraction."""
        import time as time_module

        from ndi.cloud.api import files as files_api

        calls = {"n": 0}

        def flaky(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"jobs": [{"id": "j1", "state": "extracting"}]}
            if calls["n"] == 2:
                raise RuntimeError("transient 502")
            return {"jobs": [{"id": "j1", "state": "complete"}]}

        with (
            patch.object(files_api, "listActiveBulkUploads", flaky),
            patch.object(time_module, "sleep", lambda s: None),
        ):
            result = files_api.waitForAllBulkUploads(DATASET_ID, client=object())

        assert result["state"] == "complete"
        assert calls["n"] == 3

    def test_the_sync_boundary_caps_its_own_deadline(self):
        """300s is the right budget for "finish this extraction"; it is the
        wrong budget for a boundary every sync crosses on every call."""
        from ndi.cloud.sync import operations

        seen: dict = {}

        def record(dataset_id, **kwargs):
            seen.update(kwargs)
            return {"state": "complete", "jobs": [], "elapsed": 0.0}

        with patch("ndi.cloud.api.files.waitForAllBulkUploads", record):
            operations._settle_bulk_uploads(DATASET_ID, SyncOptions(), client=object())

        assert seen["timeout"] == operations._SETTLE_TIMEOUT
        assert operations._SETTLE_TIMEOUT <= 60

    def test_an_unavailable_service_does_not_warn_on_every_sync(self, tmp_path, caplog):
        """A deployment without the endpoint is not a sync problem, and a
        warning per call would train everyone to ignore the log."""
        from ndi.cloud.sync import operations

        def unavailable(dataset_id, **kwargs):
            return {"state": "unavailable", "jobs": [], "elapsed": 0.0, "error": "404"}

        with (
            patch("ndi.cloud.api.files.waitForAllBulkUploads", unavailable),
            patch("ndi.cloud.internal.listRemoteDocumentIds", lambda *a, **k: {}),
            caplog.at_level("WARNING", logger="ndi.cloud.sync.operations"),
        ):
            report = operations.uploadNew(str(tmp_path), DATASET_ID, SyncOptions())

        assert report["mode"] == "upload_new"
        assert caplog.text == ""


class TestAFileListedButNotUploadedIsRequeued:
    """``filesNotYetUploaded`` must read the ``uploaded`` flag, not just the uid.

    MATLAB counterpart: ``+cloud/+sync/+internal/filesNotYetUploaded.m``,
    hardened in NDI-matlab ``8c31a8f28`` (NDI-matlab#805).

    The cloud records a file when its upload is REGISTERED; ``uploaded`` is
    what says the transfer finished. Matching on the uid alone -- which is
    what this did -- treats a registered-but-unsent file as done, so the
    document is recorded as synced while its binary is not there.
    Downstream consumers 404, and nothing re-queues the file because the
    sync index says it is finished.
    """

    def _split(self, manifest, remote):
        from unittest.mock import MagicMock, patch

        from ndi.cloud import internal

        listing = MagicMock()
        listing.data = remote
        with patch("ndi.cloud.api.files.listFiles", lambda *a, **k: listing):
            return internal.filesNotYetUploaded(manifest, "65a1b2c3d4e5f60718293a4b")

    def test_an_unlisted_file_needs_uploading(self):
        got = self._split([{"uid": "a"}], [])
        assert [f["uid"] for f in got] == ["a"]

    def test_a_listed_and_uploaded_file_is_done(self):
        got = self._split([{"uid": "a"}], [{"uid": "a", "uploaded": True}])
        assert got == []

    def test_a_listed_but_unsent_file_is_requeued(self):
        """The bug: present in the listing, bytes never arrived."""
        got = self._split([{"uid": "a"}], [{"uid": "a", "uploaded": False}])
        assert [f["uid"] for f in got] == ["a"]

    def test_an_entry_with_no_uploaded_field_is_requeued(self, caplog):
        """Status unconfirmable. A needless re-upload costs bandwidth; a
        wrongly skipped one costs the binary."""
        with caplog.at_level("WARNING", logger="ndi.cloud.internal"):
            got = self._split([{"uid": "a"}], [{"uid": "a"}])
        assert [f["uid"] for f in got] == ["a"]
        assert "lacks an 'uploaded' field" in caplog.text

    def test_a_mixed_manifest_splits_correctly(self):
        manifest = [{"uid": "done"}, {"uid": "unsent"}, {"uid": "absent"}, {"uid": "unknown"}]
        remote = [
            {"uid": "done", "uploaded": True},
            {"uid": "unsent", "uploaded": False},
            {"uid": "unknown"},
        ]
        got = [f["uid"] for f in self._split(manifest, remote)]
        assert got == ["unsent", "absent", "unknown"]
