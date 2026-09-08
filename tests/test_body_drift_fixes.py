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
