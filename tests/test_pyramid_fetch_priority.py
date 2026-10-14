"""The chunk fetcher serves the view the user is looking at first.

napari slices on one thread, so a slice for a level the user zoomed
through held up the slice for where they stopped until every one of its
tiles had arrived, and the fetch queue was first-in-first-out on top of
that. Now: newest requests first, chunks in the current view ahead of
everything, and a blocking read for a chunk that has left the view is
released (StaleChunkRead) while its fetch carries on in the background.
"""

import threading
import time
import types

import pytest

from ndi.pyramid.multiscale import StaleChunkRead, _ChunkFetcher

DOC = types.SimpleNamespace(id="lvl0")
COARSE = types.SimpleNamespace(id="lvl3")


class _Session:
    """Reopenable fake session. Fetches block until released, and the
    order in which they start is recorded."""

    started: list = []
    gate = threading.Event()

    def __init__(self, path):
        self.path = path

    def database_openbinarydoc(self, doc, filename):
        _Session.started.append(filename)
        assert _Session.gate.wait(10)
        return types.SimpleNamespace(fullpathfilename=__file__)

    def database_closebinarydoc(self, fh):
        pass


@pytest.fixture
def fetcher():
    _Session.started = []
    _Session.gate = threading.Event()
    f = _ChunkFetcher(_Session("/x"), workers=1)
    f.warm()
    yield f
    _Session.gate.set()
    f.close()


def _occupy(f):
    """Tie up the single worker so later requests queue behind it."""
    f.prefetchAsync(DOC, "busy")
    for _ in range(100):
        if _Session.started:
            return
        time.sleep(0.01)


def _drain(f, n):
    _Session.gate.set()
    for _ in range(300):
        if len(_Session.started) >= n:
            return
        time.sleep(0.01)


def test_newest_request_goes_first(fetcher):
    _occupy(fetcher)
    for name in ("a", "b", "c"):
        fetcher.prefetchAsync(DOC, name)
    _drain(fetcher, 4)
    assert _Session.started == ["busy", "c", "b", "a"]


def test_the_current_view_jumps_the_queue_and_is_queued_unasked(fetcher):
    _occupy(fetcher)
    fetcher.prefetchAsync(DOC, "old")
    fetcher.setView({("lvl0", "v1"): DOC, ("lvl0", "v2"): DOC})
    fetcher.prefetchAsync(DOC, "newer-but-not-in-view")
    _drain(fetcher, 5)
    assert set(_Session.started[1:3]) == {"v1", "v2"}
    assert _Session.started[3:] == ["newer-but-not-in-view", "old"]


def test_a_chunk_that_leaves_the_view_drops_back(fetcher):
    _occupy(fetcher)
    fetcher.setView({("lvl0", "was-in-view"): DOC})
    fetcher.prefetchAsync(DOC, "other")
    fetcher.setView({("lvl0", "now-in-view"): DOC})
    _drain(fetcher, 4)
    assert _Session.started[1] == "now-in-view"


def test_a_waiting_read_is_released_when_its_chunk_leaves_the_view(fetcher):
    _occupy(fetcher)
    out = {}

    def read():
        try:
            out["path"] = fetcher.chunkPath(DOC, "zoomed-past")
        except StaleChunkRead as exc:
            out["stale"] = exc

    t = threading.Thread(target=read)
    t.start()
    time.sleep(0.15)
    fetcher.setView({("lvl0", "elsewhere"): DOC})
    t.join(2)
    assert not t.is_alive(), "the read must not wait for a tile nobody is looking at"
    assert "stale" in out
    assert fetcher.staleReleased() == 1

    # ...and the fetch still lands, slowly, for when they zoom back.
    _drain(fetcher, 3)
    for _ in range(200):
        if fetcher.chunkPathIfCached(DOC, "zoomed-past"):
            break
        time.sleep(0.01)
    assert fetcher.chunkPathIfCached(DOC, "zoomed-past") is not None


def test_a_read_in_view_is_never_released(fetcher):
    _occupy(fetcher)
    fetcher.setView({("lvl0", "wanted"): DOC})
    result = {}
    t = threading.Thread(target=lambda: result.update(p=fetcher.chunkPath(DOC, "wanted")))
    t.start()
    time.sleep(0.2)
    fetcher.setView({("lvl0", "wanted"): DOC, ("lvl0", "more"): DOC})
    _drain(fetcher, 2)
    t.join(2)
    assert result.get("p") == __file__


def test_a_read_that_started_after_the_view_was_set_is_not_judged_by_it(fetcher):
    """The poll lags napari: a read for the NEW view can start before
    the poll has seen the new view. It must not be released on the old
    one's say-so."""
    _occupy(fetcher)
    fetcher.setView({("lvl0", "old-view"): DOC})
    result = {}
    t = threading.Thread(target=lambda: result.update(p=fetcher.chunkPath(DOC, "new-view")))
    t.start()
    time.sleep(0.3)
    assert t.is_alive()
    _drain(fetcher, 2)
    t.join(2)
    assert result.get("p") == __file__


def test_the_coarsest_level_is_never_released(fetcher):
    _occupy(fetcher)
    fetcher.setView({}, never_stale_doc_ids=["lvl3"])
    result = {}
    t = threading.Thread(target=lambda: result.update(p=fetcher.chunkPath(COARSE, "c")))
    t.start()
    time.sleep(0.15)
    fetcher.setView({("lvl0", "x"): DOC})
    time.sleep(0.3)
    assert t.is_alive()
    _drain(fetcher, 3)
    t.join(2)
    assert result.get("p") == __file__


def test_an_unknown_view_releases_nothing(fetcher):
    _occupy(fetcher)
    fetcher.setView(None)
    t = threading.Thread(target=lambda: fetcher.chunkPath(DOC, "q"))
    t.start()
    time.sleep(0.3)
    assert t.is_alive()
    _drain(fetcher, 2)
    t.join(2)


def test_one_chunk_is_fetched_once_however_many_ask(fetcher):
    _occupy(fetcher)
    done = []
    threads = [
        threading.Thread(target=lambda: done.append(fetcher.chunkPath(DOC, "shared")))
        for _ in range(3)
    ]
    for t in threads:
        t.start()
    fetcher.prefetchAsync(DOC, "shared")
    _drain(fetcher, 2)
    for t in threads:
        t.join(2)
    assert _Session.started.count("shared") == 1
    assert done == [__file__] * 3
