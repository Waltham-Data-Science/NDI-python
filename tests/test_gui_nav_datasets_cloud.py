"""Tests for ndi.gui.nav.datasets_cloud and ndi.cloud.sync.documentDifference.

MATLAB counterparts: the cloud action methods of ndi.gui.nav.datasetsPane,
and ndi.cloud.sync.documentDifference.

Every action returns what happened rather than showing it, so what the user
would be told is checkable here without a display. The cases that matter are
the failures: a dataset that is not linked to the cloud, a sync that raises,
an upload that reports failure. Each must come back as a clear message and
must NOT record a cloud state -- not knowing is not an answer.
"""

from __future__ import annotations

import pytest

from ndi.gui.nav import datasets_cloud as dc
from ndi.gui.nav.datasets_text import sync_result_message


class FakeDataset:
    def __init__(self, *, path="/data/ds", in_cloud=False, raises=False):
        self._path = path
        self._in_cloud = in_cloud
        self._raises = raises

    def getpath(self):
        return self._path

    def is_in_cloud(self):
        if self._raises:
            raise RuntimeError("no database")
        return self._in_cloud, "cloud-id" if self._in_cloud else ""


class TestCheckCloudStatus:
    def test_linked(self):
        r = dc.check_cloud_status(FakeDataset(in_cloud=True))
        assert r.ok and r.state == "incloud"
        assert "linked to NDI Cloud" in r.message

    def test_not_linked_points_at_the_next_step(self):
        r = dc.check_cloud_status(FakeDataset(in_cloud=False))
        assert r.ok and r.state == "notincloud"
        assert "Upload to Cloud" in r.message

    def test_a_failure_records_no_state(self):
        """Not knowing must not be recorded as a definite answer."""
        r = dc.check_cloud_status(FakeDataset(raises=True))
        assert not r.ok
        assert r.state is None
        assert r.icon == "error"

    def test_a_bare_boolean_is_accepted(self):
        class Bare(FakeDataset):
            def is_in_cloud(self):
                return True

        assert dc.check_cloud_status(Bare()).state == "incloud"


class TestUploadDataset:
    def test_success_links_the_dataset_without_another_query(self, monkeypatch):
        """A successful upload is what links it, so the state is known."""
        import ndi.cloud.orchestration as orch

        monkeypatch.setattr(orch, "uploadDataset", lambda ds, verbose=False: (True, "cid", ""))
        r = dc.upload_dataset(FakeDataset())
        assert r.ok and r.state == "incloud"

    def test_a_reported_failure_is_not_a_success(self, monkeypatch):
        import ndi.cloud.orchestration as orch

        monkeypatch.setattr(
            orch, "uploadDataset", lambda ds, verbose=False: (False, "", "quota exceeded")
        )
        r = dc.upload_dataset(FakeDataset())
        assert not r.ok
        assert r.state is None
        assert "quota exceeded" in r.message

    def test_a_raised_error_is_reported_not_propagated(self, monkeypatch):
        import ndi.cloud.orchestration as orch

        def boom(ds, verbose=False):
            raise RuntimeError("network down")

        monkeypatch.setattr(orch, "uploadDataset", boom)
        r = dc.upload_dataset(FakeDataset())
        assert not r.ok
        assert "network down" in r.message


class TestCheckForNew:
    def _patch_difference(self, monkeypatch, report):
        import ndi.cloud.sync as sync_module

        monkeypatch.setattr(sync_module, "documentDifference", lambda ds: report)

    def test_remote_side_reads_the_remote_only_count(self, monkeypatch):
        self._patch_difference(monkeypatch, {"num_remote_only": 3, "num_local_only": 7})
        r = dc.check_for_new(FakeDataset(), "remote")
        assert r.ok
        assert "3 documents on the cloud" in r.message

    def test_local_side_reads_the_local_only_count(self, monkeypatch):
        self._patch_difference(monkeypatch, {"num_remote_only": 3, "num_local_only": 7})
        r = dc.check_for_new(FakeDataset(), "local")
        assert "7 local documents" in r.message

    def test_zero_is_reported_as_nothing_new(self, monkeypatch):
        self._patch_difference(monkeypatch, {"num_remote_only": 0, "num_local_only": 0})
        assert "no new documents on the cloud" in dc.check_for_new(FakeDataset(), "remote").message

    def test_an_unlinked_dataset_is_an_error_not_a_count_of_zero(self, monkeypatch):
        """'Not linked' and 'nothing new' are different answers."""
        import ndi.cloud.sync as sync_module

        def unlinked(ds):
            raise RuntimeError("This dataset is not linked to a cloud dataset.")

        monkeypatch.setattr(sync_module, "documentDifference", unlinked)
        r = dc.check_for_new(FakeDataset(), "remote")
        assert not r.ok
        assert "not linked" in r.message

    def test_a_bad_side_is_rejected(self):
        with pytest.raises(ValueError, match="side must be"):
            dc.check_for_new(FakeDataset(), "sideways")


class TestSyncAndMirror:
    def _patch_op(self, monkeypatch, name, result):
        import ndi.cloud.sync as sync_module

        def op(path, cloud_id):
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(sync_module, name, op, raising=False)

    def _patch_resolve(self, monkeypatch, value=("/data/ds", "cid")):
        monkeypatch.setattr(dc, "resolve_cloud_target", lambda ds: value)

    def test_each_sync_mode_calls_its_function(self, monkeypatch):
        self._patch_resolve(monkeypatch)
        for mode, (fn, title) in dc.SYNC_MODES.items():
            self._patch_op(monkeypatch, fn, {"uploaded": ["a"]})
            r = dc.sync_dataset(FakeDataset(), mode)
            assert r.ok
            assert r.title == title
            assert "1 document uploaded" in r.message

    def test_a_python_shaped_report_is_summarised_correctly(self, monkeypatch):
        """The regression this slice exists to prevent: Python's sync
        reports key on 'uploaded', MATLAB's on 'uploaded_document_ids'.
        Reading only MATLAB's names calls a real sync 'no changes'."""
        self._patch_resolve(monkeypatch)
        self._patch_op(
            monkeypatch,
            "twoWaySync",
            {"mode": "two_way_sync", "uploaded": ["a", "b"], "downloaded": ["c"]},
        )
        r = dc.sync_dataset(FakeDataset(), "two_way_sync")
        assert "2 documents uploaded" in r.message
        assert "1 document downloaded" in r.message
        assert "No changes" not in r.message

    def test_a_matlab_shaped_report_is_summarised_the_same_way(self, monkeypatch):
        self._patch_resolve(monkeypatch)
        self._patch_op(monkeypatch, "twoWaySync", {"uploaded_document_ids": ["a", "b"]})
        assert "2 documents uploaded" in dc.sync_dataset(FakeDataset(), "two_way_sync").message

    def test_a_genuinely_empty_report_still_says_no_changes(self, monkeypatch):
        self._patch_resolve(monkeypatch)
        self._patch_op(monkeypatch, "uploadNew", {"uploaded": [], "downloaded": []})
        assert "No changes" in dc.sync_dataset(FakeDataset(), "upload_new").message

    def test_a_raising_sync_is_reported_with_the_verb(self, monkeypatch):
        self._patch_resolve(monkeypatch)
        self._patch_op(monkeypatch, "uploadNew", RuntimeError("connection reset"))
        r = dc.sync_dataset(FakeDataset(), "upload_new")
        assert not r.ok
        assert "Sync did not complete" in r.message
        assert "connection reset" in r.message

    def test_an_unlinked_dataset_never_reaches_the_sync_function(self, monkeypatch):
        """The resolution failure must stop the operation, not just colour
        the message: calling a sync function with an unresolved target is
        how a real dataset gets acted on by mistake."""
        import ndi.cloud.sync as sync_module

        calls = []

        def must_not_run(path, cloud_id):
            calls.append((path, cloud_id))
            return {}

        monkeypatch.setattr(sync_module, "uploadNew", must_not_run, raising=False)
        monkeypatch.setattr(
            dc,
            "resolve_cloud_target",
            lambda ds: (_ for _ in ()).throw(ValueError("This dataset is not linked")),
        )
        r = dc.sync_dataset(FakeDataset(), "upload_new")
        assert not r.ok
        assert "not linked" in r.message
        assert calls == []

    def test_sync_leaves_the_cloud_badge_alone(self, monkeypatch):
        """MATLAB's cloudSync and cloudMirror set no cloud state. A
        successful sync does imply the dataset is linked, but inventing a
        badge update here would diverge from MATLAB."""
        self._patch_resolve(monkeypatch)
        self._patch_op(monkeypatch, "uploadNew", {"uploaded": ["a"]})
        assert dc.sync_dataset(FakeDataset(), "upload_new").state is None

    def test_each_mirror_direction_calls_its_function(self, monkeypatch):
        self._patch_resolve(monkeypatch)
        for direction, (fn, title) in dc.MIRROR_MODES.items():
            self._patch_op(monkeypatch, fn, {"deleted_local": ["x"]})
            r = dc.mirror_dataset(FakeDataset(), direction)
            assert r.ok and r.title == title
            assert "1 local document deleted" in r.message

    def test_a_failing_mirror_says_mirror_not_sync(self, monkeypatch):
        self._patch_resolve(monkeypatch)
        self._patch_op(monkeypatch, "mirrorToRemote", RuntimeError("denied"))
        assert "Mirror did not complete" in dc.mirror_dataset(FakeDataset(), "to_remote").message

    def test_bad_mode_and_direction_are_rejected(self):
        with pytest.raises(ValueError, match="mode must be"):
            dc.sync_dataset(FakeDataset(), "sideways")
        with pytest.raises(ValueError, match="direction must be"):
            dc.mirror_dataset(FakeDataset(), "sideways")


class TestMirrorPrompt:
    def test_both_directions_name_the_side_that_loses_documents(self):
        """A mirror that deletes the wrong side is not recoverable, so the
        warning has to say which side is being overwritten."""
        _, from_remote = dc.mirror_prompt("from_remote")
        _, to_remote = dc.mirror_prompt("to_remote")
        assert "DELETED from the local dataset" in from_remote
        assert "DELETED from the cloud dataset" in to_remote

    def test_both_warn_that_it_cannot_be_undone(self):
        for direction in dc.MIRROR_MODES:
            assert "cannot be undone" in dc.mirror_prompt(direction)[1]

    def test_titles_match_the_mode_table(self):
        for direction, (_, title) in dc.MIRROR_MODES.items():
            assert dc.mirror_prompt(direction)[0] == title

    def test_a_bad_direction_is_rejected(self):
        with pytest.raises(ValueError, match="direction must be"):
            dc.mirror_prompt("sideways")


class TestResolveCloudTarget:
    def test_returns_path_and_id(self, monkeypatch):
        import ndi.cloud.internal as internal

        monkeypatch.setattr(internal, "getCloudDatasetIdForLocalDataset", lambda ds: ("cid", {}))
        assert dc.resolve_cloud_target(FakeDataset(path="/data/ds")) == ("/data/ds", "cid")

    def test_an_empty_id_is_an_actionable_message(self, monkeypatch):
        import ndi.cloud.internal as internal

        monkeypatch.setattr(internal, "getCloudDatasetIdForLocalDataset", lambda ds: ("", None))
        with pytest.raises(ValueError, match="not linked to a cloud dataset"):
            dc.resolve_cloud_target(FakeDataset())

    def test_a_raising_lookup_becomes_a_message(self, monkeypatch):
        import ndi.cloud.internal as internal

        def boom(ds):
            raise RuntimeError("db closed")

        monkeypatch.setattr(internal, "getCloudDatasetIdForLocalDataset", boom)
        with pytest.raises(ValueError, match="db closed"):
            dc.resolve_cloud_target(FakeDataset())


class TestSyncReportFieldNames:
    """ndi.cloud.sync reports must carry MATLAB's field names.

    These are what sync_result_message reads. Reading a report under the
    wrong name is SILENT -- a missing field and an empty one look the same --
    so a mismatch does not raise, it just tells the user nothing happened.
    """

    #: What each sync function must emit, from the MATLAB counterparts.
    EXPECTED = {
        "uploadNew": {"uploaded_document_ids"},
        "downloadNew": {"downloaded_document_ids"},
        "mirrorToRemote": {"uploaded_document_ids", "deleted_remote_document_ids"},
        "mirrorFromRemote": {"downloaded_document_ids", "deleted_local_document_ids"},
        "twoWaySync": {
            "uploaded_document_ids",
            "downloaded_document_ids",
            "deleted_local_document_ids",
            "deleted_remote_document_ids",
        },
    }

    def test_every_sync_function_initialises_matlabs_fields(self):
        import inspect

        import ndi.cloud.sync.operations as ops

        for name, expected in self.EXPECTED.items():
            source = inspect.getsource(getattr(ops, name))
            missing = {f for f in expected if f'"{f}"' not in source}
            assert not missing, f"{name} does not mention {sorted(missing)}"

    def test_no_function_still_uses_the_old_short_names(self):
        """The short names were the divergence. upload.py and
        orchestration.py legitimately use "uploaded" as an integer counter in
        FILE reports, which is why this checks only the sync module."""
        import inspect

        import ndi.cloud.sync.operations as ops

        for name in self.EXPECTED:
            source = inspect.getsource(getattr(ops, name))
            for old in (
                '"uploaded"',
                '"downloaded"',
                '"deleted_local"',
                '"deleted_remote"',
                '"deleted"',
            ):
                assert old not in source, f"{name} still uses {old}"

    def test_a_mirror_to_cloud_report_names_its_deletions(self):
        """The bug this rename fixes: mirrorToRemote recorded remote
        deletions under "deleted", which sync_result_message read under
        neither name -- so 50 permanent deletions were summarised as
        "Done. 3 documents uploaded"."""
        report = {
            "mode": "mirror_to_remote",
            "uploaded_document_ids": ["a", "b", "c"],
            "deleted_remote_document_ids": [f"x{i}" for i in range(50)],
        }
        message = sync_result_message(report)
        assert "3 documents uploaded" in message
        assert "50 remote documents deleted" in message


class TestDocumentDifference:
    """ndi.cloud.sync.documentDifference -- absent from Python before this."""

    def _patch(self, monkeypatch, local_ids, remote_ids, cloud_id="cid"):
        import ndi.cloud.internal as internal

        monkeypatch.setattr(
            internal, "getCloudDatasetIdForLocalDataset", lambda ds, client=None: (cloud_id, {})
        )
        monkeypatch.setattr(internal, "listLocalDocuments", lambda ds: ([], local_ids))
        monkeypatch.setattr(
            internal, "listRemoteDocumentIds", lambda cid, client=None: {r: r for r in remote_ids}
        )

    def test_set_differences_and_counts(self, monkeypatch):
        from ndi.cloud.sync import documentDifference

        self._patch(monkeypatch, ["a", "b", "c"], ["b", "c", "d"])
        report = documentDifference(FakeDataset())
        assert report["local_only_ids"] == ["a"]
        assert report["remote_only_ids"] == ["d"]
        assert report["common_ids"] == ["b", "c"]
        assert report["num_local_only"] == 1
        assert report["num_remote_only"] == 1
        assert report["num_common"] == 2

    def test_ids_are_sorted_so_two_runs_agree(self, monkeypatch):
        """MATLAB's setdiff returns sorted output; a Python set has no order
        at all, so without sorting the same comparison varies between runs."""
        from ndi.cloud.sync import documentDifference

        self._patch(monkeypatch, ["zeta", "alpha", "mid"], [])
        assert documentDifference(FakeDataset())["local_only_ids"] == ["alpha", "mid", "zeta"]

    def test_identical_sides_report_no_differences(self, monkeypatch):
        from ndi.cloud.sync import documentDifference

        self._patch(monkeypatch, ["a", "b"], ["a", "b"])
        report = documentDifference(FakeDataset())
        assert report["num_local_only"] == 0
        assert report["num_remote_only"] == 0
        assert report["num_common"] == 2

    def test_an_explicit_cloud_id_skips_the_lookup(self, monkeypatch):
        import ndi.cloud.internal as internal
        from ndi.cloud.sync import documentDifference

        def must_not_be_called(ds, client=None):
            raise AssertionError("the lookup should have been skipped")

        monkeypatch.setattr(internal, "getCloudDatasetIdForLocalDataset", must_not_be_called)
        monkeypatch.setattr(internal, "listLocalDocuments", lambda ds: ([], ["a"]))
        monkeypatch.setattr(internal, "listRemoteDocumentIds", lambda cid, client=None: {})
        assert documentDifference(FakeDataset(), "explicit-id")["num_local_only"] == 1

    def test_an_unlinked_dataset_raises_rather_than_reporting_zero(self, monkeypatch):
        """A count of zero would read as 'nothing new', which is a different
        and much more reassuring claim than 'we could not look'."""
        import ndi.cloud.internal as internal
        from ndi.cloud.exceptions import CloudSyncError
        from ndi.cloud.sync import documentDifference

        monkeypatch.setattr(
            internal, "getCloudDatasetIdForLocalDataset", lambda ds, client=None: ("", None)
        )
        with pytest.raises(CloudSyncError, match="not linked to a cloud dataset"):
            documentDifference(FakeDataset())

    def test_a_failing_lookup_is_wrapped_with_guidance(self, monkeypatch):
        import ndi.cloud.internal as internal
        from ndi.cloud.exceptions import CloudSyncError
        from ndi.cloud.sync import documentDifference

        def boom(ds, client=None):
            raise RuntimeError("db closed")

        monkeypatch.setattr(internal, "getCloudDatasetIdForLocalDataset", boom)
        with pytest.raises(CloudSyncError, match="db closed"):
            documentDifference(FakeDataset())


if __name__ == "__main__":
    pytest.main([__file__])
