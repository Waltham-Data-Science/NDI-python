"""ndi.file.navigator against MATLAB's +ndi/+file/navigator.m.

Two findings, both in selectfilegroups:

* MATLAB's ``unique()`` sorts, and it iterates the sorted result, so epoch
  NUMBERS are alphabetical by epoch_id. ``dict.fromkeys`` preserved
  first-appearance order instead, putting every ingested epoch before every
  disk one -- so the two languages numbered the same session's epochs
  differently whenever it held both.
* MATLAB remembers, per navigator, whether the session has ever had an
  ingested epoch, and skips the database query once the answer has been no.
  The three cache methods had no Python counterpart at all.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from ndi.cache import ndi_cache
from ndi.file.navigator import ndi_file_navigator


class Navigator(ndi_file_navigator):
    """A navigator with the disk scan and the ingested lookup stubbed."""

    def __init__(self, session, disk=None, ingested=None):
        super().__init__(session=session, fileparameters=[".*\\.dat\\>"])
        self._disk = disk or []
        self._ingested = ingested or []
        self.ingested_lookups = 0

    def selectfilegroups_disk(self):
        return list(self._disk)

    def find_ingested_documents(self):
        self.ingested_lookups += 1
        return list(self._ingested)

    def epochid(self, epoch_number, epochfiles=None):
        # One epoch per directory; the id is the directory name, as
        # epochdir's override gives it in MATLAB.
        from pathlib import Path

        return Path(epochfiles[0]).parent.name


@pytest.fixture
def session():
    s = MagicMock()
    s.cache = ndi_cache()
    s.id.return_value = "sess_1"
    return s


def ingested(epoch_id: str, files: list[str]) -> dict[str, Any]:
    return {"epoch_id": epoch_id, "files": files, "epochprobemap": None}


class TestEpochOrder:
    """MATLAB iterates the SORTED unique epoch ids."""

    def test_ingested_and_disk_epochs_come_back_sorted(self, session):
        nav = Navigator(
            session,
            disk=[["/s/a00002/x.dat"], ["/s/a00004/x.dat"]],
            ingested=[ingested("a00003", ["f3"]), ingested("a00001", ["f1"])],
        )
        files, _ = nav.selectfilegroups()
        # first-appearance order would be a00003, a00001, a00002, a00004
        # sorted ids: a00001 a00002 a00003 a00004
        assert [f[0] for f in files] == ["f1", "/s/a00002/x.dat", "f3", "/s/a00004/x.dat"]

    def test_an_epoch_on_both_sides_appears_once_and_ingested_wins(self, session):
        nav = Navigator(
            session,
            disk=[["/s/t1/x.dat"]],
            ingested=[ingested("t1", ["ingested_t1"])],
        )
        files, _ = nav.selectfilegroups()
        assert files == [["ingested_t1"]]

    def test_disk_only_is_returned_untouched(self, session):
        # MATLAB returns before the unique() when nothing is ingested, so
        # the disk order stands.
        disk = [["/s/b/x.dat"], ["/s/a/x.dat"]]
        nav = Navigator(session, disk=disk)
        files, probemaps = nav.selectfilegroups()
        assert files == disk
        assert probemaps == [None, None]

    def test_ingested_only_is_sorted(self, session):
        nav = Navigator(
            session,
            ingested=[ingested("z", ["fz"]), ingested("a", ["fa"])],
        )
        files, _ = nav.selectfilegroups()
        assert [f[0] for f in files] == ["fa", "fz"]


class TestIngestedCache:
    """MATLAB's getcache / get_cached_value / add_cached_value."""

    def test_the_three_methods_exist(self):
        for name in ("getcache", "get_cached_value", "add_cached_value"):
            assert callable(getattr(ndi_file_navigator, name, None)), name

    def test_the_key_names_the_navigator(self, session):
        nav = Navigator(session)
        cache, key = nav.getcache()
        assert cache is session.cache
        assert key == f"filenavigator_{nav.id}"

    def test_no_session_means_no_cache(self):
        nav = Navigator(None)
        assert nav.getcache() == (None, None)
        assert nav.get_cached_value("anything", "logical") is None
        nav.add_cached_value("anything", "logical", True)  # must not raise

    def test_a_value_round_trips(self, session):
        nav = Navigator(session)
        nav.add_cached_value("has_ingested_epoch", "logical", True)
        assert nav.get_cached_value("has_ingested_epoch", "logical") is True

    def test_a_missing_value_is_none(self, session):
        assert Navigator(session).get_cached_value("never_set", "logical") is None

    def test_two_navigators_do_not_share_a_value(self, session):
        first, second = Navigator(session), Navigator(session)
        first.add_cached_value("has_ingested_epoch", "logical", True)
        assert second.get_cached_value("has_ingested_epoch", "logical") is None

    def test_a_session_with_no_ingested_epochs_is_only_asked_once(self, session):
        nav = Navigator(session, disk=[["/s/t1/x.dat"]])
        nav.selectfilegroups()
        nav.selectfilegroups()
        nav.selectfilegroups()
        # Without the memo the database was queried on every epoch lookup.
        assert nav.ingested_lookups == 1

    def test_a_session_with_ingested_epochs_is_still_asked(self, session):
        nav = Navigator(session, ingested=[ingested("t1", ["f1"])])
        nav.selectfilegroups()
        nav.selectfilegroups()
        assert nav.ingested_lookups == 2

    def test_a_negative_memo_stands_until_the_cache_is_cleared(self, session):
        # The cache APPENDS and lookup() returns the FIRST match, on both
        # sides, so a second value for the same key can never be read. Once
        # "no ingested epochs" is recorded, ingesting one does not change the
        # answer until the cache is cleared -- which is why ndi.mock's
        # stimulus_response calls S.cache.clear() before it builds anything.
        nav = Navigator(session, disk=[["/s/t1/x.dat"]])
        nav.selectfilegroups()

        nav._ingested = [ingested("t1", ["f1"])]
        assert nav.selectfilegroups()[0] == [["/s/t1/x.dat"]]

        session.cache.clear()
        assert nav.selectfilegroups()[0] == [["f1"]]

    def test_the_memo_is_written_once(self, session):
        # MATLAB writes one on every call, which appends an entry that can
        # never be looked up.
        nav = Navigator(session, ingested=[ingested("t1", ["f1"])])
        nav.selectfilegroups()
        nav.selectfilegroups()
        cache, key = nav.getcache()
        matching = [e for e in cache._table if e.key == f"{key}_has_ingested_epoch"]
        assert len(matching) == 1
