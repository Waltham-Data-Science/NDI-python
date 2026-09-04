"""Registered epochs come back alphabetized by epoch_id.

Issue: Waltham-Data-Science/NDI-python#162

epochtable() used to return registered epochs in the backend's natural row
order -- stable for a given database, but neither insertion order nor anything
a caller could predict. Five epochs added as epoch_1..epoch_5 came back as
epoch_4, epoch_5, epoch_1, epoch_3, epoch_2.

That order is what ndi.fun.probe.export.binary concatenates in and what
ndi.fun.probe.import_.kilosort maps sample indices back through, so a sort
crossing between the two languages could land spikes in the wrong epochs
without raising. MATLAB already sorts, via the intersect() in
ndi.element/buildepochtable; these tests pin the Python side to the same
answer.

PLAIN ALPHABETICAL, and only that: codepoint order on the raw id, so
epoch_10 precedes epoch_2 because the ids are not zero-padded. That is the
specified behaviour, not an artefact.
"""

from __future__ import annotations

import numpy as np
import pytest

from ndi.element_timeseries import ndi_element_timeseries
from ndi.session import ndi_session_dir
from ndi.subject import ndi_subject
from ndi.time.clocktype import ndi_time_clocktype

CLOCK = "dev_local_time"


@pytest.fixture
def element(tmp_path):
    """A non-direct element, whose epochs are registered ones."""
    directory = tmp_path / "sess"
    directory.mkdir(parents=True, exist_ok=True)
    session = ndi_session_dir("epoch_order", str(directory))
    subject = ndi_subject("mouse23@vhlab.org", "test mouse").newdocument()
    subject.set_session_id(session.id())
    session.database_add(subject)

    obj = ndi_element_timeseries(
        session=session,
        name="p",
        reference=1,
        type="n-trode",
        direct=False,
        subject_id=subject.id,
    )
    session.database_add(obj.newdocument())
    return obj


def _add(element, names):
    clock = [ndi_time_clocktype(CLOCK)]
    for index, name in enumerate(names):
        times = np.arange(5) / 10.0 + index
        element.addepoch(name, clock, [(float(index), float(index) + 1)], times, np.zeros((5, 1)))


def _ids(element):
    table, _ = element.epochtable()
    return [entry["epoch_id"] for entry in table]


class TestAlphabetical:
    def test_epochs_come_back_sorted_whatever_order_they_went_in(self, element):
        _add(element, ["epoch_3", "epoch_5", "epoch_1", "epoch_4", "epoch_2"])
        assert _ids(element) == ["epoch_1", "epoch_2", "epoch_3", "epoch_4", "epoch_5"]

    def test_it_is_plain_codepoint_order_so_ten_precedes_two(self, element):
        """The ids are not zero-padded; this is intended, and is what
        MATLAB's intersect produces."""
        _add(element, ["epoch_2", "epoch_10", "epoch_1"])
        assert _ids(element) == ["epoch_1", "epoch_10", "epoch_2"]

    def test_capitals_sort_by_codepoint_not_case_folded(self, element):
        """A case-insensitive sort is the plausible wrong choice here: it
        would put 'alpha' before 'Beta', where codepoint order does not."""
        _add(element, ["beta", "Beta", "alpha"])
        assert _ids(element) == ["Beta", "alpha", "beta"]

    def test_epoch_number_follows_the_sorted_position(self, element):
        _add(element, ["epoch_3", "epoch_1", "epoch_2"])
        table, _ = element.epochtable()
        assert [entry["epoch_number"] for entry in table] == [1, 2, 3]
        assert [entry["epoch_id"] for entry in table] == ["epoch_1", "epoch_2", "epoch_3"]

    def test_one_epoch_and_no_epochs_are_unremarkable(self, element):
        assert _ids(element) == []
        _add(element, ["only"])
        assert _ids(element) == ["only"]


class TestStability:
    def test_the_order_survives_a_rebuild_and_a_reopen(self, element, tmp_path):
        """It was already stable before this change; it must stay stable, or
        an export and a later import would disagree with each other."""
        _add(element, ["epoch_3", "epoch_1", "epoch_2"])
        first = _ids(element)

        rebuilt, _ = element.epochtable(force_rebuild=True)
        assert [entry["epoch_id"] for entry in rebuilt] == first

        from ndi.query import ndi_query

        reopened_session = ndi_session_dir("epoch_order", str(tmp_path / "sess"))
        docs = reopened_session.database_search(
            ndi_query("").isa("element") & ndi_query("element.name", "exact_string", "p", "")
        )
        reloaded = ndi_element_timeseries(session=reopened_session, document=docs[0])
        assert _ids(reloaded) == first


class TestDirectElementsAreNotReordered:
    def test_a_direct_element_keeps_its_underlying_element_s_order(self, element):
        """A direct element's epochs ARE the underlying element's, paired by
        position -- MATLAB's direct branch is ib = 1:numel(underlying_et).
        Sorting them here would break that pairing.
        """
        _add(element, ["epoch_3", "epoch_1", "epoch_2"])

        derived = ndi_element_timeseries(
            session=element.session,
            name="derived",
            reference=1,
            type="spikes",
            underlying_element=element,
            direct=True,
            subject_id=element.subject_id,
        )
        element.session.database_add(derived.newdocument())

        # the underlying element is itself sorted, so the derived element is
        # too -- but by inheritance, not by sorting a second time
        assert _ids(derived) == _ids(element)


class TestTheExportImportContract:
    def test_epoch_bounds_follow_the_sorted_order(self, element):
        """The importer's sample arithmetic counts epochs in table order, so
        the boundaries it builds must follow the sort rather than insertion.
        """
        from ndi.fun.probe.import_ import epoch_map

        _add(element, ["epoch_3", "epoch_1", "epoch_2"])

        class Probe:
            """The element, plus the converter API epoch_map needs."""

            def __init__(self, wrapped):
                self._wrapped = wrapped

            def __getattr__(self, name):
                return getattr(self._wrapped, name)

            def samplerate(self, epoch=None):
                return 10.0

            def times2samples(self, epoch, times):
                return np.round(np.asarray(times, dtype=float) * 10.0).astype(int)

            def samples2times(self, epoch, samples):
                return np.asarray(samples, dtype=float) / 10.0

        table, _ = epoch_map.epochtable(Probe(element))
        assert [entry["epoch_id"] for entry in table] == ["epoch_1", "epoch_2", "epoch_3"]

    def test_the_exported_binary_is_concatenated_in_the_sorted_order(self, tmp_path):
        """The contract in full: export.binary concatenates epochs in table
        order and the importer maps sample indices back through that same
        order. If the two ever disagreed, spikes would land in the wrong
        epochs without erroring, so this pins them together.
        """
        from ndi.fun.probe import export_binary
        from ndi.fun.probe.import_ import epoch_map

        rate, channels, samples = 100.0, 2, 50

        directory = tmp_path / "exp"
        directory.mkdir(parents=True, exist_ok=True)
        session = ndi_session_dir("exp", str(directory))
        subject = ndi_subject("mouse23@vhlab.org", "test mouse").newdocument()
        subject.set_session_id(session.id())
        session.database_add(subject)

        class Probe(ndi_element_timeseries):
            """An element carrying the probe API export and import require.

            It needs no readtimeseries override: export.binary calls that
            method positionally, so an element works in a probe's place. Until
            #166 it did not -- export passed ``epoch=``, the probe's spelling
            for a parameter MATLAB and the element class both call
            ``timeref_or_epoch`` -- and this stand-in had to redeclare the
            method to get past it.
            """

            def samplerate(self, epoch=None):
                return rate

            def times2samples(self, epoch, times):
                return np.round(np.asarray(times, dtype=float) * rate).astype(int)

            def samples2times(self, epoch, samples):
                return np.asarray(samples, dtype=float) / rate

        probe = Probe(
            session=session,
            name="ctx",
            reference=1,
            type="n-trode",
            direct=False,
            subject_id=subject.id,
        )
        session.database_add(probe.newdocument())

        # added out of order; each epoch's samples carry a marker value, so
        # the binary itself says which epoch was written where
        clock = [ndi_time_clocktype(CLOCK)]
        for marker, name in [(30, "epoch_3"), (10, "epoch_1"), (20, "epoch_2")]:
            times = np.arange(samples) / rate
            probe.addepoch(
                name,
                clock,
                [(0.0, samples / rate)],
                times,
                np.full((samples, channels), marker, dtype=float),
            )

        binary = tmp_path / "ctx.bin"
        export_binary(probe, str(binary), multiplier=1, verbose=False)

        written = np.fromfile(binary, dtype=np.int16).reshape(-1, channels)
        markers = [int(written[block * samples, 0]) for block in range(3)]
        assert markers == [10, 20, 30]  # epoch_1, epoch_2, epoch_3

        table, _ = epoch_map.epochtable(probe)
        assert [entry["epoch_id"] for entry in table] == ["epoch_1", "epoch_2", "epoch_3"]
