"""ndi_element_timeseries stores epoch data as VHSB, the way MATLAB does.

MATLAB equivalent: ndi.element.timeseries/addepoch and /readtimeseries

Before this was wired up, storing an epoch was impossible in two independent
ways: the element_epoch document failed DID validation (epoch_clock is a
string in the schema, and a list was passed), and the binary write opened a
read-only handle under a file name the schema does not declare, inside a bare
``except Exception: pass``. So a caller could store an epoch, see no error,
and have nothing on disk -- and the read path then invented timestamps from a
sample rate, which is right for a sampled trace and wrong for spike times.

These tests exercise the whole path against a real session and database
rather than mocking the store, because both faults were in the seams.
"""

from __future__ import annotations

import numpy as np
import pytest

from ndi.element_timeseries import BINARY_FILE_NAME, ndi_element_timeseries
from ndi.session import ndi_session_dir
from ndi.subject import ndi_subject
from ndi.time.clocktype import ndi_time_clocktype

CLOCK = "dev_local_time"


@pytest.fixture
def element(tmp_path):
    """A non-direct element_timeseries in a real session, ready for addepoch."""
    d = tmp_path / "sess"
    d.mkdir(parents=True, exist_ok=True)
    session = ndi_session_dir("vhsb_test", str(d))

    subject_doc = ndi_subject("mouse23@vhlab.org", "test mouse").newdocument()
    subject_doc.set_session_id(session.id())
    session.database_add(subject_doc)

    elem = ndi_element_timeseries(
        session=session,
        name="el",
        reference=1,
        type="ensemble",
        direct=False,
        subject_id=subject_doc.id,
    )
    session.database_add(elem.newdocument())
    return session, elem


def _clock():
    return [ndi_time_clocktype(CLOCK)]


class TestMarkedPointProcess:
    """The case ndi.element.ensemble needs: the timestamps ARE the data.

    An ensemble epoch stores every spike of every neuron with the neuron
    column index as its mark, so the times are irregular. Reconstructing them
    from a sample rate returns plausible, evenly spaced, wrong answers.
    """

    def test_irregular_times_round_trip_exactly(self, element):
        session, elem = element
        times = np.array([0.013, 0.0517, 0.0518, 0.2, 0.9993])
        marks = np.array([1.0, 2.0, 1.0, 3.0, 2.0])
        elem, doc = elem.addepoch("epoch_1", _clock(), [(0.0, 1.0)], times, marks)

        data, read_times, _ = elem.readtimeseries("epoch_1", -np.inf, np.inf)
        assert np.array_equal(np.asarray(read_times).ravel(), times)
        assert np.array_equal(np.asarray(data).ravel(), marks)

    def test_two_sample_epoch(self, element):
        """Two spikes. This raised inside vhsb_write until VH-Lab/vhlab-toolbox-python#21."""
        session, elem = element
        elem, _ = elem.addepoch(
            "epoch_1", _clock(), [(0.0, 1.0)], np.array([0.25, 0.75]), np.array([7.0, 9.0])
        )
        data, times, _ = elem.readtimeseries("epoch_1", -np.inf, np.inf)
        assert np.array_equal(np.asarray(times).ravel(), [0.25, 0.75])
        assert np.array_equal(np.asarray(data).ravel(), [7.0, 9.0])


class TestRegularlySampledSeries:
    def test_infinite_bounds_return_the_whole_epoch(self, element):
        """Returned ONE sample until VH-Lab/vhlab-toolbox-python#21.

        A constant-interval file makes vhsb_read compute sample labels from
        +/-Inf, and the int cast turned those into garbage. Pinned here as
        well as in vlt, because this is the call NDI actually makes:
        ndi.element.ensemble/spikeMatrix reads with (-Inf, Inf).
        """
        session, elem = element
        times = np.arange(100) / 1000.0
        values = np.arange(100, dtype=float)
        elem, _ = elem.addepoch("epoch_1", _clock(), [(0.0, 0.099)], times, values)

        data, read_times, _ = elem.readtimeseries("epoch_1", -np.inf, np.inf)
        read_times = np.asarray(read_times).ravel()
        assert len(read_times) == 100, "all 100 samples, not 1"
        assert np.array_equal(read_times, times)
        assert np.array_equal(np.asarray(data).ravel(), values)

    def test_finite_window_selects_a_range(self, element):
        session, elem = element
        elem, _ = elem.addepoch(
            "epoch_1",
            _clock(),
            [(0.0, 0.099)],
            np.arange(100) / 1000.0,
            np.arange(100, dtype=float),
        )
        _, times, _ = elem.readtimeseries("epoch_1", 0.010, 0.019)
        times = np.asarray(times).ravel()
        assert len(times) == 10
        assert times[0] == pytest.approx(0.010)
        assert times[-1] == pytest.approx(0.019)

    def test_multi_channel_data(self, element):
        session, elem = element
        times = np.array([0.0, 0.25, 0.5, 0.75])
        values = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0], [7.0, 8.0]])
        elem, _ = elem.addepoch("epoch_1", _clock(), [(0.0, 1.0)], times, values)
        data, read_times, _ = elem.readtimeseries("epoch_1", -np.inf, np.inf)
        assert np.array_equal(np.asarray(read_times).ravel(), times)
        assert np.array_equal(np.asarray(data).reshape(values.shape), values)


class TestBinaryFileName:
    """The document file name is the cross-language contract.

    element_epoch.json declares exactly one file, "epoch_binary_data.vhsb", in
    BOTH repositories. The old code used "timeseries.vhsb", a name neither
    schema declares, so nothing MATLAB wrote could ever be found and nothing
    written here could ever be read by MATLAB.
    """

    def test_binary_is_stored_under_the_matlab_name(self, element):
        session, elem = element
        _, doc = elem.addepoch(
            "epoch_1", _clock(), [(0.0, 1.0)], np.array([0.1, 0.2]), np.array([1.0, 2.0])
        )
        exists, _ = session.database_existbinarydoc(doc, BINARY_FILE_NAME)
        assert exists
        assert BINARY_FILE_NAME == "epoch_binary_data.vhsb"

    def test_the_declared_file_list_is_the_same_name(self, element):
        session, elem = element
        _, doc = elem.addepoch(
            "epoch_1", _clock(), [(0.0, 1.0)], np.array([0.1, 0.2]), np.array([1.0, 2.0])
        )
        assert doc.document_properties["files"]["file_list"] == [BINARY_FILE_NAME]


class TestEpochDocumentShape:
    """MATLAB writes a string clock and a flat [t0 t1]; the schema demands it.

        epochclockstr = epochclock.ndi_clocktype2char();
        t0_t1_input   = vlt.data.colvec(t0_t1);

    Passing a list for epoch_clock made every addepoch fail DID validation
    with "Invalid non-char sub-field element_epoch.epoch_clock".
    """

    def test_epoch_clock_is_a_string(self, element):
        session, elem = element
        _, doc = elem.addepoch("epoch_1", _clock(), [(0.0, 1.0)])
        assert doc.document_properties["element_epoch"]["epoch_clock"] == CLOCK

    def test_t0_t1_is_a_flat_pair(self, element):
        session, elem = element
        _, doc = elem.addepoch("epoch_1", _clock(), [(0.25, 1.75)])
        assert list(doc.document_properties["element_epoch"]["t0_t1"]) == [0.25, 1.75]

    def test_a_bare_pair_is_accepted_too(self, element):
        session, elem = element
        _, doc = elem.addepoch("epoch_1", _clock(), (0.25, 1.75))
        assert list(doc.document_properties["element_epoch"]["t0_t1"]) == [0.25, 1.75]

    def test_more_than_one_clock_is_refused(self, element):
        """element_epoch holds ONE clock string, so two cannot be represented."""
        session, elem = element
        clocks = [ndi_time_clocktype(CLOCK), ndi_time_clocktype("dev_local_time")]
        with pytest.raises(ValueError, match="exactly one"):
            elem.addepoch("epoch_1", clocks, [(0.0, 1.0)])

    def test_more_than_one_time_range_is_refused(self, element):
        session, elem = element
        with pytest.raises(ValueError, match="one .t0 t1. pair"):
            elem.addepoch("epoch_1", _clock(), [(0.0, 1.0), (2.0, 3.0)])


class TestMultipleEpochs:
    def test_each_epoch_reads_back_its_own_data(self, element):
        """Found by epochid, not by position in a search result.

        The database promises no ordering, and MATLAB queries
        epochid.epochid. Indexing epoch_docs[n-1] returned whichever document
        the store happened to hand back first.
        """
        session, elem = element
        first_t, first_y = np.array([0.1, 0.2, 0.35]), np.array([1.0, 2.0, 3.0])
        second_t, second_y = np.array([5.0, 5.5, 6.25]), np.array([7.0, 8.0, 9.0])
        elem, _ = elem.addepoch("epoch_1", _clock(), [(0.0, 1.0)], first_t, first_y)
        elem, _ = elem.addepoch("epoch_2", _clock(), [(5.0, 7.0)], second_t, second_y)

        d1, t1, _ = elem.readtimeseries("epoch_1", -np.inf, np.inf)
        d2, t2, _ = elem.readtimeseries("epoch_2", -np.inf, np.inf)
        assert np.array_equal(np.asarray(t1).ravel(), first_t)
        assert np.array_equal(np.asarray(d1).ravel(), first_y)
        assert np.array_equal(np.asarray(t2).ravel(), second_t)
        assert np.array_equal(np.asarray(d2).ravel(), second_y)


class TestStorageErrorsAreNotSwallowed:
    """The old code hid every storage failure behind "best-effort"."""

    def test_mismatched_lengths_raise(self, element):
        session, elem = element
        with pytest.raises(ValueError, match="same number of samples"):
            elem.addepoch("epoch_1", _clock(), [(0.0, 1.0)], np.array([0.1, 0.2]), np.array([1.0]))


class TestEpochWithoutData:
    def test_addepoch_without_samples_stores_no_binary(self, element):
        session, elem = element
        _, doc = elem.addepoch("epoch_1", _clock(), [(0.0, 1.0)])
        exists, _ = session.database_existbinarydoc(doc, BINARY_FILE_NAME)
        assert not exists

    def test_reading_an_epoch_with_no_binary_is_not_an_error(self, element):
        """It falls through to the underlying element, which is empty here."""
        session, elem = element
        elem, _ = elem.addepoch("epoch_1", _clock(), [(0.0, 1.0)])
        data, times, _ = elem.readtimeseries("epoch_1", -np.inf, np.inf)
        assert len(np.asarray(data).ravel()) == 0
        assert len(np.asarray(times).ravel()) == 0
