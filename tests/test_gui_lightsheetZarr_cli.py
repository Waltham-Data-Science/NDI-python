"""Tests for the napariViewLightsheet CLI.

Only the orchestration is exercised here -- napari, dask and zarr never
have to be importable to run this file. Anything that would import them
lives behind ``deferred`` imports inside cli.py.

The one behaviour that most needs coverage is the DATASET-OR-SESSION
dispatch in ``_open_session``. A downloaded NDI dataset and a plain
session look identical on disk -- both keep their database at
``<path>/.ndi`` -- so opening one as the other succeeds and then finds
almost nothing. A dataset's documents may live in LINKED SESSIONS, and
only ``ndi_dataset.database_search`` follows those links.

The symptom, before this dispatch: a downloaded lightsheet dataset
reporting "No lightsheetZarrPyramid documents in this session" while
the same directory opened as an ``ndi.dataset.dir`` in MATLAB (or via
``ndi.cloud.download_helper``'s ``DL.open_session``) lists the pyramid
fine. The path is right, the data is there, and the reader is looking
one level too shallow.
"""

from __future__ import annotations

import pytest


class TestOpenSessionOrDataset:
    """The dispatcher tries the dataset reading first, then the session,
    and keeps whichever finds pyramids. Neither reading a real dataset
    nor a real session is done here: fakes stand in for both openers via
    monkeypatch, because the point being tested is which one wins, not
    how either is constructed.
    """

    def _install(self, monkeypatch, dataset, session):
        from ndi.gui.app.lightsheetZarr import cli

        monkeypatch.setattr(cli, "_pyramids", lambda obj: list(getattr(obj, "pyramids", [])))
        monkeypatch.setattr(cli, "_as_dataset", dataset)
        monkeypatch.setattr(cli, "_as_session", session)
        return cli

    def test_the_dataset_reading_wins_when_it_finds_the_pyramids(self, monkeypatch):
        class Dataset:
            pyramids = ["pyr"]

        class Session:
            pyramids: list = []

        cli = self._install(monkeypatch, lambda _p: Dataset(), lambda _p: Session())
        assert isinstance(cli._open_session("/some/download"), Dataset)

    def test_a_plain_session_still_opens_when_the_dataset_reading_is_empty(self, monkeypatch):
        class Dataset:
            pyramids: list = []

        class Session:
            pyramids = ["pyr"]

        cli = self._install(monkeypatch, lambda _p: Dataset(), lambda _p: Session())
        assert isinstance(cli._open_session("/some/session"), Session)

    def test_a_dataset_reading_that_raises_does_not_lose_the_session(self, monkeypatch):
        def boom(_p):
            raise RuntimeError("not a dataset")

        class Session:
            pyramids = ["pyr"]

        cli = self._install(monkeypatch, boom, lambda _p: Session())
        assert isinstance(cli._open_session("/some/session"), Session)

    def test_neither_reading_working_says_so(self, monkeypatch):
        def boom(_p):
            raise RuntimeError("nope")

        cli = self._install(monkeypatch, boom, boom)
        with pytest.raises(SystemExit, match="either an NDI"):
            cli._open_session("/nowhere")

    def test_an_empty_path_still_returns_something_to_report_on(self, monkeypatch):
        """Both open, neither has pyramids: the caller wants the object so
        it can print its own 'no pyramid here' message naming the path,
        not an exception from the opener."""

        class Empty:
            pyramids: list = []

        cli = self._install(monkeypatch, lambda _p: Empty(), lambda _p: Empty())
        assert isinstance(cli._open_session("/empty"), Empty)
