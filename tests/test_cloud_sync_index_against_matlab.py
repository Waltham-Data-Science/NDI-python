"""``ndi.cloud.sync.index`` against ``+ndi/+cloud/+sync/+internal/+index/``.

WHAT WAS WRONG. ``.ndi/sync/index.json`` lives INSIDE the dataset, so it is
an interchange format between the two languages, not a private Python file.
MATLAB's ``createSyncIndexStruct`` writes ``localDocumentIdsLastSync`` /
``remoteDocumentIdsLastSync`` / ``lastSyncTimestamp``; Python wrote
``local_doc_ids_last_sync`` / ``remote_doc_ids_last_sync`` /
``last_sync_timestamp``. Neither language could read the other's index.

That is not a cosmetic mismatch, because neither side reports a bad read.
``SyncIndex.read`` fell back to ``[]`` for every key it did not recognise, so
a MATLAB-written index came back EMPTY and indistinguishable from one that
had never been synced -- the exact failure ``writeSyncIndex``'s own comment
warns about ("callers treat that as 'never synced'"). What each caller then
does with an empty index:

  uploadNew        new = local - remote          -> uploads NOTHING
  downloadNew      new = remote - local          -> downloads the whole remote
  mirrorToRemote   delete = remote - local       -> DELETES THE WHOLE REMOTE
  mirrorFromRemote download = remote - local     -> downloads the whole remote
  twoWaySync       last_local/last_remote empty  -> everything looks new

So opening a MATLAB-synced dataset in Python and running ``mirrorToRemote``
would have deleted the cloud copy, reporting success.
"""

from __future__ import annotations

import json
import re

import pytest

from ndi.cloud.sync.index import SyncIndex, index_filepath

MATLAB_KEYS = {
    "localDocumentIdsLastSync",
    "remoteDocumentIdsLastSync",
    "lastSyncTimestamp",
}


def _write_raw(path, payload):
    d = path / ".ndi" / "sync"
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.json").write_text(json.dumps(payload))


def _raw(path):
    return json.loads((path / ".ndi" / "sync" / "index.json").read_text())


class TestTheOnDiskKeysAreMatlabs:
    def test_written_keys_are_matlabs(self, tmp_path):
        idx = SyncIndex()
        idx.update(["a"], ["b"])
        idx.write(tmp_path)
        assert set(_raw(tmp_path)) == MATLAB_KEYS

    def test_a_matlab_written_index_reads_back(self, tmp_path):
        """The case that produced an empty index before."""
        _write_raw(
            tmp_path,
            {
                "localDocumentIdsLastSync": ["a", "b"],
                "remoteDocumentIdsLastSync": ["a", "c"],
                "lastSyncTimestamp": "2026-09-08T11:44:00-0400",
            },
        )
        idx = SyncIndex.read(tmp_path)
        assert idx.local_doc_ids_last_sync == ["a", "b"]
        assert idx.remote_doc_ids_last_sync == ["a", "c"]
        assert idx.last_sync_timestamp == "2026-09-08T11:44:00-0400"

    def test_a_matlab_index_is_not_mistaken_for_never_synced(self, tmp_path):
        _write_raw(
            tmp_path,
            {
                "localDocumentIdsLastSync": ["a"],
                "remoteDocumentIdsLastSync": ["a"],
                "lastSyncTimestamp": "2026-09-08T11:44:00-0400",
            },
        )
        assert SyncIndex.read(tmp_path) != SyncIndex()

    def test_a_legacy_python_index_still_reads(self, tmp_path):
        """An index already on disk from an older NDI-python must keep working."""
        _write_raw(
            tmp_path,
            {
                "local_doc_ids_last_sync": ["x"],
                "remote_doc_ids_last_sync": ["y"],
                "last_sync_timestamp": "then",
            },
        )
        idx = SyncIndex.read(tmp_path)
        assert idx.local_doc_ids_last_sync == ["x"]
        assert idx.remote_doc_ids_last_sync == ["y"]
        assert idx.last_sync_timestamp == "then"

    def test_matlab_keys_win_when_both_are_present(self, tmp_path):
        _write_raw(
            tmp_path,
            {
                "localDocumentIdsLastSync": ["new"],
                "local_doc_ids_last_sync": ["old"],
                "remoteDocumentIdsLastSync": ["new"],
                "remote_doc_ids_last_sync": ["old"],
                "lastSyncTimestamp": "new",
                "last_sync_timestamp": "old",
            },
        )
        idx = SyncIndex.read(tmp_path)
        assert idx.local_doc_ids_last_sync == ["new"]
        assert idx.remote_doc_ids_last_sync == ["new"]
        assert idx.last_sync_timestamp == "new"

    def test_a_legacy_index_is_rewritten_in_matlabs_keys(self, tmp_path):
        """Reading then writing migrates the file; the old keys do not linger."""
        _write_raw(
            tmp_path,
            {
                "local_doc_ids_last_sync": ["x"],
                "remote_doc_ids_last_sync": ["y"],
                "last_sync_timestamp": "then",
            },
        )
        idx = SyncIndex.read(tmp_path)
        idx.write(tmp_path)
        raw = _raw(tmp_path)
        assert set(raw) == MATLAB_KEYS
        assert raw["localDocumentIdsLastSync"] == ["x"]

    def test_a_python_written_index_round_trips(self, tmp_path):
        idx = SyncIndex()
        idx.update(["a", "b"], ["c"])
        idx.write(tmp_path)
        back = SyncIndex.read(tmp_path)
        assert back == idx


class TestTheTimestampFormat:
    """MATLAB: yyyy-MM-dd'T'HH:mm:ssZZZZ, local time, second resolution."""

    def test_it_matches_matlabs_pattern(self):
        idx = SyncIndex()
        idx.update([], [])
        assert re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{4}", idx.last_sync_timestamp
        ), idx.last_sync_timestamp

    def test_it_has_no_sub_second_part(self):
        idx = SyncIndex()
        idx.update([], [])
        assert "." not in idx.last_sync_timestamp

    def test_it_carries_an_explicit_offset(self):
        """Local time, as MATLAB writes it -- but never bare local time."""
        idx = SyncIndex()
        idx.update([], [])
        assert idx.last_sync_timestamp[-5] in "+-"


class TestIndexFilepath:
    """MATLAB equivalent: getIndexFilepath(path, mode)."""

    def test_the_path_is_matlabs(self, tmp_path):
        assert index_filepath(tmp_path) == tmp_path / ".ndi" / "sync" / "index.json"

    def test_read_mode_does_not_create_the_directory(self, tmp_path):
        index_filepath(tmp_path, "read")
        assert not (tmp_path / ".ndi").exists()

    def test_write_mode_creates_it(self, tmp_path):
        index_filepath(tmp_path, "write")
        assert (tmp_path / ".ndi" / "sync").is_dir()

    def test_write_mode_announces_it_when_verbose(self, tmp_path, capsys):
        index_filepath(tmp_path, "write", verbose=True)
        assert "Creating sync directory" in capsys.readouterr().out

    def test_it_does_not_announce_an_existing_directory(self, tmp_path, capsys):
        (tmp_path / ".ndi" / "sync").mkdir(parents=True)
        index_filepath(tmp_path, "write", verbose=True)
        assert capsys.readouterr().out == ""

    def test_an_unknown_mode_is_refused(self, tmp_path):
        """MATLAB's mustBeMember(mode, ["read","write"])."""
        with pytest.raises(ValueError, match="read.*write"):
            index_filepath(tmp_path, "append")

    def test_reading_a_never_synced_dataset_leaves_no_trace(self, tmp_path):
        SyncIndex.read(tmp_path)
        assert list(tmp_path.iterdir()) == []


class TestMissingIndex:
    def test_a_missing_file_reads_as_an_empty_index(self, tmp_path):
        assert SyncIndex.read(tmp_path) == SyncIndex()

    def test_an_index_missing_one_key_keeps_the_others(self, tmp_path):
        _write_raw(tmp_path, {"localDocumentIdsLastSync": ["a"]})
        idx = SyncIndex.read(tmp_path)
        assert idx.local_doc_ids_last_sync == ["a"]
        assert idx.remote_doc_ids_last_sync == []
        assert idx.last_sync_timestamp == ""
