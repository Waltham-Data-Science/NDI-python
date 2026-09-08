"""Three defects found by reading what MATLAB changed under a stale hash.

Part of the NDI-python#211 drift burn-down: each of these was a bridge
entry whose ``matlab_last_sync_hash`` had gone stale, and reading the
MATLAB diff turned up something the Python side was actually missing.

* ``find_ingested_docs`` did not count image-series ingest documents, so
  an ingested imageseries session reported as not ingested.
* ``element.direct`` was parsed with ``int()``, which raises on the
  ``"true"`` / ``"false"`` spellings MATLAB now writes and accepts, with
  an error naming neither the field nor the document.
* ``makeCells`` had no way to record the file its cells were segmented
  from, although the document class has carried the dependency since it
  was written.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class TestIngestedImageSeriesCounts:
    """MATLAB counterpart: ``+ndi/+database/+fun/find_ingested_docs.m``.

    NDI-matlab 831a3fbef added ``daqreader_image_epochdata_ingested`` to
    the query when image-series acquisition landed (issue #823). Python
    kept the three older classes, so a session whose epochs were ingested
    as image series came back with nothing -- and "no ingested documents"
    reads as "nothing to do" rather than as an error, which is why this
    is worth a test rather than a glance.
    """

    def _searched_query_text(self):
        from ndi.database_fun import find_ingested_docs

        session = MagicMock()
        session.database_search.return_value = []
        find_ingested_docs(session)
        (query,), _ = session.database_search.call_args
        return str(query)

    @pytest.mark.parametrize(
        "isa_class",
        [
            "daqreader_mfdaq_epochdata_ingested",
            "daqmetadatareader_epochdata_ingested",
            "epochfiles_ingested",
            "daqreader_image_epochdata_ingested",
        ],
    )
    def test_every_ingest_document_class_is_searched_for(self, isa_class):
        assert isa_class in self._searched_query_text()


class TestElementDirectParsing:
    """MATLAB counterpart: the ``element.direct`` branch of ``+ndi/element.m``.

    NDI-matlab a030c830e replaced ``logical(eval(...))`` with an explicit
    parse, because the value comes out of a document and must never be run
    as code. Python never used ``eval``, so that half has no counterpart --
    but the same change also settled WHICH spellings are accepted, and
    Python's ``int(direct_val)`` raises on ``"true"``, with a message about
    base-10 literals that names neither the field nor the document.
    """

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (True, True),
            (False, False),
            (1, True),
            (0, False),
            ("1", True),
            ("0", False),
            ("true", True),
            ("false", False),
            ("TRUE", True),
            ("False", False),
            ("  1  ", True),
            ("", True),
            ("2", True),
        ],
    )
    def test_accepted_spellings(self, value, expected):
        from ndi.element import _parse_direct

        assert _parse_direct(value) is expected

    def test_an_empty_value_defaults_to_direct(self):
        """MATLAB's default for an element that does not say."""
        from ndi.element import _parse_direct

        assert _parse_direct("") is True

    def test_a_meaningless_string_says_what_is_wrong(self):
        from ndi.element import _parse_direct

        with pytest.raises(ValueError, match="element.direct"):
            _parse_direct("yes")


class TestMakeCellsRecordsItsSourceFile:
    """MATLAB counterpart: ``+ndi/+fun/+doc/+gene/makeCells.m``.

    NDI-matlab 6ae508708 added a ``sourceFileID`` option: the class has
    carried a ``source_file_id`` dependency since it was written and
    nothing populated it. Without it there is no way, from a cells
    document, to say which file the cells were segmented from.
    """

    @pytest.fixture
    def pyramid(self, tmp_path):
        from ndi.fun.doc_gene import makeGeneList, makePyramid
        from ndi.session.dir import ndi_session_dir

        root = tmp_path / "source_file_id"
        root.mkdir(parents=True, exist_ok=True)
        session = ndi_session_dir("cells", str(root))
        subject = session.newdocument("subject", **{"subject.local_identifier": "cells@vhlab"})
        session.database_add(subject)
        gene_list = makeGeneList(session, ["E1", "E2"], ["a", "b"])
        pyr, _ = makePyramid(
            session,
            [1000, 1005],
            [2000, 2003],
            [0, 1],
            [2, 3],
            gene_list,
            subjectID=subject.id,
            binSizes=[1],
            grid=1,
        )
        return session, pyr, subject

    def test_the_dependency_is_recorded_when_given(self, pyramid):
        from ndi.fun.doc_gene import makeCells

        session, pyr, subject = pyramid
        # Any document will do as the stand-in for a generic_file: what is
        # under test is that the id reaches the dependency, not what it names.
        doc = makeCells(session, ["a", "b"], [1, 2], [3, 4], pyr, sourceFileID=subject.id)
        assert doc.dependency_value("source_file_id") == subject.id

    def test_it_is_left_unset_when_not_given(self, pyramid):
        from ndi.fun.doc_gene import makeCells

        session, pyr, _ = pyramid
        doc = makeCells(session, ["a", "b"], [1, 2], [3, 4], pyr)
        assert not doc.dependency_value("source_file_id")


class TestTheBlanksStimulusIdIsRecovered:
    """MATLAB counterpart: ``+ndi/+app/+stimulus/tuning_response.m`` ae7916628.

    ``control_stimulus_ids`` holds, per trial, WHICH TRIAL is that trial's
    blank -- a presentation number. The ``control_stimid`` argument
    downstream wants the id of the blank STIMULUS. Passing the first as the
    second subtracts whichever stimulus happens to carry the blank's
    position as its id: right by coincidence for an unshuffled order, a
    different grating each epoch for a pseudorandom one.

    This port mirrored the bug on purpose while it stood upstream and
    reported it as VH-Lab/NDI-matlab#912; the module docstring said it
    would follow whatever landed there. This is that fix.
    """

    def _recover(self, trials, order):
        from ndi.app.stimulus.tuning_response import _control_stimulus_ids_from_trials

        return _control_stimulus_ids_from_trials(trials, order)

    def test_a_shuffled_order_no_longer_picks_the_wrong_stimulus(self):
        """The case that made this wrong rather than merely indirect.

        Trial 3 (1-based) is the blank and presents stimulus 7. The old
        code passed the trial number 3 through as a stimulus id, so
        stimulus 3 -- a real grating -- was subtracted as the baseline.
        """
        order = [4, 1, 7, 2, 3]
        assert self._recover([3, 3, 3, 3, 3], order) == [7.0]

    def test_an_unshuffled_order_is_unchanged(self):
        """Where trial number and stimulus id coincide, nothing moves --
        which is why the bug survived so long."""
        order = [1, 2, 3, 4, 5]
        assert self._recover([3, 3, 3, 3, 3], order) == [3.0]

    def test_several_repetitions_give_one_blank_id(self):
        """Each repetition has its own control TRIAL, all presenting the
        same blank STIMULUS -- so the answer is one id, not one per rep."""
        order = [9, 1, 2, 9, 2, 1]
        assert self._recover([1, 1, 1, 4, 4, 4], order) == [9.0]

    def test_trials_without_a_control_are_skipped(self):
        """NaN per trial is a legitimate run with no blank, not an error."""
        order = [4, 1, 7]
        assert self._recover([float("nan"), 3, float("nan")], order) == [7.0]

    def test_no_controls_at_all_gives_nothing(self):
        assert self._recover([float("nan"), float("nan")], [1, 2]) == []

    def test_an_out_of_range_trial_is_ignored_rather_than_raising(self):
        """A stored index past the end of the order is bad data, but losing
        the baseline is better than losing the whole computation."""
        assert self._recover([99], [1, 2, 3]) == []
