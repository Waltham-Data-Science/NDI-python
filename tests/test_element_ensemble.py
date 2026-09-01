"""Round-trip tests for ndi.element.ensemble against a real session.

MATLAB counterpart: ndi.element.ensemble (src/ndi/+ndi/+element/ensemble.m)

The class exists to store a marked point process and recover, per epoch,
which neuron each mark refers to. So the tests go through a real
``ndi_session_dir`` and a real database rather than mocking: the failure this
class is most likely to have is that its two documents do not land together,
and no mock would show that.
"""

from __future__ import annotations

import numpy as np
import pytest

from ndi.element import ndi_element
from ndi.element.ensemble import ndi_element_ensemble
from ndi.session import ndi_session_dir
from ndi.subject import ndi_subject
from ndi.time.clocktype import ndi_time_clocktype

CLOCK = "dev_local_time"


@pytest.fixture
def ensemble(tmp_path):
    """An ensemble element in a real session, ready for add_ensemble_epoch.

    The neurons are REAL element documents in the database. They have to be:
    the ensemble map declares a ``neuron_id`` dependency per column, and DID
    rejects a dependency on a document that does not exist. Inventing ids
    would test a path no caller can reach.
    """
    d = tmp_path / "sess"
    d.mkdir(parents=True, exist_ok=True)
    session = ndi_session_dir("ensemble_test", str(d))

    subject_doc = ndi_subject("mouse23@vhlab.org", "test mouse").newdocument()
    subject_doc.set_session_id(session.id())
    session.database_add(subject_doc)

    neuron_ids = []
    for name in NEURON_NAMES:
        nrn = ndi_element(
            session=session,
            name=name,
            reference=1,
            type="neuron",
            direct=False,
            subject_id=subject_doc.id,
        )
        session.database_add(nrn.newdocument())
        neuron_ids.append(nrn.id)

    elem = ndi_element_ensemble(
        session=session,
        name="ens",
        reference=1,
        type="ensemble",
        direct=False,
        subject_id=subject_doc.id,
    )
    session.database_add(elem.newdocument())
    return session, elem, neuron_ids


def _clock():
    return [ndi_time_clocktype(CLOCK)]


# Three neurons with interleaved spikes. Every time is an exact binary
# fraction, so == is the right comparison (the same discipline as the VHSB
# battery).
NEURON_NAMES = ["cell_1", "cell_2", "cell_3"]
SPIKE_ROWS = [
    [0.25, 0.75, 1.5],
    [0.5, 1.25],
    [0.125, 2.0],
]
# Flattened and time-sorted by hand, as the stored form should be:
EXPECTED_TIMES = [0.125, 0.25, 0.5, 0.75, 1.25, 1.5, 2.0]
EXPECTED_MARKS = [3.0, 1.0, 2.0, 1.0, 2.0, 1.0, 3.0]


class TestFlatten:
    """The flattening is pure, so it is tested without a database."""

    def test_sorted_marked_point_process(self):
        times, marks = ndi_element_ensemble._flatten_spike_rows(SPIKE_ROWS)
        assert list(times) == EXPECTED_TIMES
        assert list(marks) == EXPECTED_MARKS

    def test_marks_are_one_based(self):
        """The stored mark is 1-based, matching what MATLAB writes."""
        _, marks = ndi_element_ensemble._flatten_spike_rows([[0.5], [0.25]])
        assert sorted(set(marks)) == [1.0, 2.0]
        assert 0.0 not in set(marks)

    def test_simultaneous_spikes_keep_column_order(self):
        """A stable sort, so a tie breaks by neuron column in both languages."""
        times, marks = ndi_element_ensemble._flatten_spike_rows([[1.0], [1.0], [1.0]])
        assert list(times) == [1.0, 1.0, 1.0]
        assert list(marks) == [1.0, 2.0, 3.0]

    def test_empty_ensemble_is_not_an_error(self):
        times, marks = ndi_element_ensemble._flatten_spike_rows([])
        assert times.size == 0 and marks.size == 0

    def test_neuron_with_no_spikes_contributes_nothing(self):
        times, marks = ndi_element_ensemble._flatten_spike_rows([[0.5], [], [0.25]])
        assert list(times) == [0.25, 0.5]
        assert list(marks) == [3.0, 1.0]


class TestAddEnsembleEpoch:
    def test_round_trip_times_and_marks(self, ensemble):
        session, elem, NEURON_IDS = ensemble
        elem.add_ensemble_epoch(
            "epoch_1", _clock(), [(0.0, 3.0)], NEURON_IDS, NEURON_NAMES, SPIKE_ROWS
        )
        data, times, _ = elem.readtimeseries("epoch_1", -np.inf, np.inf)
        assert list(np.asarray(times).ravel()) == EXPECTED_TIMES
        assert list(np.asarray(data).ravel()) == EXPECTED_MARKS

    def test_neuron_ids_and_names_in_column_order(self, ensemble):
        session, elem, NEURON_IDS = ensemble
        elem.add_ensemble_epoch(
            "epoch_1", _clock(), [(0.0, 3.0)], NEURON_IDS, NEURON_NAMES, SPIKE_ROWS
        )
        assert elem.neuron_ids("epoch_1") == NEURON_IDS
        assert elem.neuron_names("epoch_1") == NEURON_NAMES

    def test_mark_indexes_the_right_neuron(self, ensemble):
        """The point of the whole class: mark k means neuron_ids[k - 1]."""
        session, elem, NEURON_IDS = ensemble
        elem.add_ensemble_epoch(
            "epoch_1", _clock(), [(0.0, 3.0)], NEURON_IDS, NEURON_NAMES, SPIKE_ROWS
        )
        ids = elem.neuron_ids("epoch_1")
        data, times, _ = elem.readtimeseries("epoch_1", -np.inf, np.inf)
        marks = np.asarray(data).ravel().astype(int)
        times = np.asarray(times).ravel()

        for k, nid in enumerate(NEURON_IDS):
            got = sorted(times[marks == (k + 1)])
            assert got == sorted(SPIKE_ROWS[k]), f"neuron {nid} spikes disagree"
            assert ids[k] == nid

    def test_map_document_records_the_metadata(self, ensemble):
        session, elem, NEURON_IDS = ensemble
        elem.add_ensemble_epoch(
            "epoch_1",
            _clock(),
            [(0.0, 3.0)],
            NEURON_IDS,
            NEURON_NAMES,
            SPIKE_ROWS,
            value_description="spike times, seconds",
            ensemble_name="tetrode_A",
        )
        doc = elem.epoch_ensemble_doc("epoch_1")
        props = doc.document_properties["ensemble"]
        assert props["ensemble_name"] == "tetrode_A"
        assert props["value_type"] == "spiketimes"
        assert props["value_description"] == "spike times, seconds"
        assert props["num_neurons"] == 3
        assert props["clocktype"] == CLOCK

    def test_map_depends_on_the_epoch_document(self, ensemble):
        session, elem, NEURON_IDS = ensemble
        epoch_doc, map_doc = elem.add_ensemble_epoch(
            "epoch_1", _clock(), [(0.0, 3.0)], NEURON_IDS, NEURON_NAMES, SPIKE_ROWS
        )
        assert map_doc.dependency_value("element_epoch_id") == epoch_doc.id
        assert map_doc.dependency_value("element_id") == elem.id

    def test_size_mismatch_raises(self, ensemble):
        session, elem, NEURON_IDS = ensemble
        with pytest.raises(ValueError, match="same"):
            elem.add_ensemble_epoch(
                "epoch_1", _clock(), [(0.0, 3.0)], NEURON_IDS, ["only_one"], SPIKE_ROWS
            )

    def test_add_to_database_false_adds_nothing(self, ensemble):
        """Deferred means deferred: neither document may reach the database.

        This is the case the class is built around -- the map depends on the
        epoch document's id, so a partial add would leave either a resolvable
        epoch with no neuron map or a dangling dependency.
        """
        session, elem, NEURON_IDS = ensemble
        epoch_doc, map_doc = elem.add_ensemble_epoch(
            "epoch_1",
            _clock(),
            [(0.0, 3.0)],
            NEURON_IDS,
            NEURON_NAMES,
            SPIKE_ROWS,
            add_to_database=False,
        )
        from ndi.query import ndi_query

        found_epoch = session.database_search(
            ndi_query("base.id", "exact_string", epoch_doc.id, "")
        )
        found_map = session.database_search(
            ndi_query("base.id", "exact_string", map_doc.id, "")
        )
        assert found_epoch == [] and found_map == []
        # ...but they are fully built, so the caller can add them itself.
        assert map_doc.dependency_value("element_epoch_id") == epoch_doc.id

    def test_two_epochs_may_have_different_neurons(self, ensemble):
        """The map is per epoch, which is the reason it is a document at all."""
        session, elem, NEURON_IDS = ensemble
        elem.add_ensemble_epoch(
            "epoch_1", _clock(), [(0.0, 3.0)], NEURON_IDS, NEURON_NAMES, SPIKE_ROWS
        )
        elem.add_ensemble_epoch(
            "epoch_2",
            _clock(),
            [(0.0, 3.0)],
            [NEURON_IDS[0]],
            ["cell_9"],
            [[0.5, 1.0]],
        )
        assert elem.neuron_ids("epoch_1") == NEURON_IDS
        assert elem.neuron_ids("epoch_2") == [NEURON_IDS[0]]
        assert elem.neuron_names("epoch_2") == ["cell_9"]

    def test_missing_map_raises(self, ensemble):
        session, elem, NEURON_IDS = ensemble
        with pytest.raises(ValueError, match="No ensemble map document"):
            elem.epoch_ensemble_doc("no_such_epoch")


class TestNeuronNamesFile:
    def test_names_with_spaces_and_unicode_survive(self, ensemble):
        session, elem, NEURON_IDS = ensemble
        names = ["cell one", "cellulé_2", "cell-3"]
        elem.add_ensemble_epoch(
            "epoch_1", _clock(), [(0.0, 3.0)], NEURON_IDS, names, SPIKE_ROWS
        )
        assert elem.neuron_names("epoch_1") == names

    def test_trailing_newline_is_not_a_neuron(self, ensemble):
        """The file ends with a newline; that must not read back as a name."""
        session, elem, NEURON_IDS = ensemble
        elem.add_ensemble_epoch(
            "epoch_1", _clock(), [(0.0, 3.0)], NEURON_IDS, NEURON_NAMES, SPIKE_ROWS
        )
        assert len(elem.neuron_names("epoch_1")) == len(NEURON_NAMES)

    def test_read_names_handles_crlf(self, tmp_path):
        p = tmp_path / "n.txt"
        p.write_bytes(b"a\r\nb\r\nc\r\n")
        assert ndi_element_ensemble._read_names(str(p)) == ["a", "b", "c"]

    def test_read_names_empty_file(self, tmp_path):
        p = tmp_path / "n.txt"
        p.write_bytes(b"")
        assert ndi_element_ensemble._read_names(str(p)) == []


class TestSpikeMatrix:
    def test_rows_are_neurons_and_values_are_spike_times(self, ensemble):
        session, elem, NEURON_IDS = ensemble
        elem.add_ensemble_epoch(
            "epoch_1", _clock(), [(0.0, 3.0)], NEURON_IDS, NEURON_NAMES, SPIKE_ROWS
        )
        m, ids = elem.spike_matrix("epoch_1")
        assert ids == NEURON_IDS
        assert m.shape == (3, 3)  # widest row is neuron 1 with three spikes
        dense = m.toarray()
        assert list(dense[0, :3]) == [0.25, 0.75, 1.5]
        assert list(dense[1, :2]) == [0.5, 1.25]
        assert list(dense[2, :2]) == [0.125, 2.0]


class TestClassIdentity:
    def test_element_class_is_overridden(self):
        """Without this an ensemble is stored, and reloaded, as a bare element."""
        assert ndi_element_ensemble().ndi_element_class() == "ndi.element.ensemble"

    def test_registered_for_loading(self):
        from ndi.class_registry import get_class

        assert get_class("ndi.element.ensemble") is ndi_element_ensemble

    def test_bad_positional_arity_is_explicit(self):
        with pytest.raises(TypeError, match="positional"):
            ndi_element_ensemble("a", "b", "c")
