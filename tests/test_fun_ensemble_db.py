"""Tests for the database-backed half of ndi.fun.ensemble.

MATLAB counterpart: src/ndi/+ndi/+fun/+ensemble/ (allElement, allNTrodes,
create, findExisting, load, neuronQuality, read; plot is smoke-tested).

Everything here goes through a real ndi_session_dir. These functions are
almost entirely queries and document writes, so a mocked session would test
the mock.
"""

from __future__ import annotations

import numpy as np
import pytest

import ndi.fun.ensemble as ens_fun
from ndi.element import ndi_element
from ndi.element.ensemble import ndi_element_ensemble
from ndi.element_timeseries import ndi_element_timeseries
from ndi.session import ndi_session_dir
from ndi.subject import ndi_subject
from ndi.time.clocktype import ndi_time_clocktype

CLOCK = "dev_local_time"

# Two neurons on one probe, with exact-binary-fraction spike times.
SPIKES = {
    "n1": [0.25, 0.75, 1.5],
    "n2": [0.5, 1.25],
}


def _clock():
    return [ndi_time_clocktype(CLOCK)]


def _session_with_subject(tmp_path, name):
    """A session plus a subject id.

    Every element document declares a subject_id dependency, and DID rejects
    an empty one, so there is no such thing as a subject-less element here.
    """
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    session = ndi_session_dir(name, str(d))
    subj = ndi_subject("mouse23@vhlab.org", "test mouse").newdocument()
    subj.set_session_id(session.id())
    session.database_add(subj)
    return session, subj.id


@pytest.fixture
def session_with_probe(tmp_path):
    """A session holding a probe-like element with one epoch, plus neurons.

    The neurons are element_timeseries of type 'spikes' whose underlying
    element is the probe, and each carries the SAME epoch id with its spike
    times stored -- which is what ndi.fun.ensemble.load goes looking for.
    """
    d = tmp_path / "sess"
    d.mkdir(parents=True, exist_ok=True)
    session = ndi_session_dir("ens_fun_test", str(d))

    subject_doc = ndi_subject("mouse23@vhlab.org", "test mouse").newdocument()
    subject_doc.set_session_id(session.id())
    session.database_add(subject_doc)

    probe = ndi_element_timeseries(
        session=session,
        name="ntrode1",
        reference=1,
        type="n-trode",
        direct=False,
        subject_id=subject_doc.id,
    )
    session.database_add(probe.newdocument())
    probe.addepoch("epoch_1", _clock(), [(0.0, 3.0)])

    neurons = {}
    for name, times in SPIKES.items():
        nrn = ndi_element_timeseries(
            session=session,
            name=name,
            reference=1,
            type="spikes",
            underlying_element=probe,
            direct=False,
            subject_id=subject_doc.id,
        )
        doc = nrn.newdocument()
        doc.set_dependency_value("underlying_element_id", probe.id)
        session.database_add(doc)
        t = np.asarray(times, dtype=float)
        nrn.addepoch("epoch_1", _clock(), [(0.0, 3.0)], t, np.ones_like(t))
        neurons[name] = nrn

    return session, probe, neurons


class TestFindExisting:
    def test_empty_before_anything_is_created(self, session_with_probe):
        session, probe, _ = session_with_probe
        subject_id = probe.subject_id
        ens = ndi_element_ensemble(
            session=session,
            name="e",
            reference=1,
            type="ensemble",
            direct=False,
            subject_id=subject_id,
        )
        session.database_add(ens.newdocument())
        assert ens_fun.find_existing(session, ens) == []

    def test_finds_the_map_and_filters_by_epoch(self, tmp_path):
        session, subject_id = _session_with_subject(tmp_path, "fe")

        nrn = ndi_element(
            session=session,
            name="n",
            reference=1,
            type="neuron",
            direct=False,
            subject_id=subject_id,
        )
        session.database_add(nrn.newdocument())

        ens = ndi_element_ensemble(
            session=session,
            name="e",
            reference=1,
            type="ensemble",
            direct=False,
            subject_id=subject_id,
        )
        session.database_add(ens.newdocument())
        ens.add_ensemble_epoch("epoch_1", _clock(), [(0.0, 1.0)], [nrn.id], ["n"], [[0.5]])

        assert len(ens_fun.find_existing(session, ens)) == 1
        assert len(ens_fun.find_existing(session, ens, epochid="epoch_1")) == 1
        assert ens_fun.find_existing(session, ens, epochid="nope") == []

    def test_accepts_an_id_string(self, tmp_path):
        session, subject_id = _session_with_subject(tmp_path, "fe2")
        ens = ndi_element_ensemble(
            session=session,
            name="e",
            reference=1,
            type="ensemble",
            direct=False,
            subject_id=subject_id,
        )
        session.database_add(ens.newdocument())
        assert ens_fun.find_existing(session, ens.id) == []

    def test_camelcase_alias_is_the_same_function(self):
        assert ens_fun.findExisting is ens_fun.find_existing


class TestLoad:
    def test_reads_every_neuron_on_the_element(self, session_with_probe):
        session, probe, _ = session_with_probe
        activity, ids, names, info, rows = ens_fun.load(session, probe, "epoch_1")

        assert len(ids) == 2
        assert info["num_neurons"] == 2
        assert info["clocktype"] == CLOCK
        assert info["value_type"] == "spiketimes"
        # Rows come back in whatever order the database returned the neurons,
        # so compare as a set of sorted trains rather than assuming an order.
        got = sorted(sorted(r.tolist()) for r in rows)
        assert got == sorted(sorted(v) for v in SPIKES.values())

    def test_activity_is_zero_padded_to_the_widest_row(self, session_with_probe):
        session, probe, _ = session_with_probe
        activity, ids, _, _, rows = ens_fun.load(session, probe, "epoch_1")
        assert activity.shape == (2, 3)  # widest train has three spikes
        dense = activity.toarray()
        for i, row in enumerate(rows):
            assert list(dense[i, : row.size]) == list(row)
            assert all(v == 0 for v in dense[i, row.size :])

    def test_unknown_epoch_raises(self, session_with_probe):
        session, probe, _ = session_with_probe
        with pytest.raises(ValueError, match="no epoch"):
            ens_fun.load(session, probe, "epoch_nope")

    def test_unknown_clocktype_raises(self, session_with_probe):
        session, probe, _ = session_with_probe
        with pytest.raises(ValueError, match="clock of type"):
            ens_fun.load(session, probe, "epoch_1", clocktype="no_such_clock")

    def test_default_value_description_names_the_clock(self, session_with_probe):
        session, probe, _ = session_with_probe
        *_, info, _ = ens_fun.load(session, probe, "epoch_1")
        assert CLOCK in info["value_description"]


class TestCreate:
    def test_stores_an_ensemble_epoch(self, session_with_probe):
        session, probe, _ = session_with_probe
        ens, existing = ens_fun.create(session, probe, "epoch_1")

        assert existing == []
        assert isinstance(ens, ndi_element_ensemble)
        assert ens.name == "ntrode1_ensemble"
        assert len(ens_fun.find_existing(session, ens, epochid="epoch_1")) == 1
        assert len(ens.neuron_ids("epoch_1")) == 2

    def test_second_call_raises_by_default(self, session_with_probe):
        session, probe, _ = session_with_probe
        ens_fun.create(session, probe, "epoch_1")
        with pytest.raises(ValueError, match="already exists"):
            ens_fun.create(session, probe, "epoch_1")

    def test_check_existing_false_allows_a_second(self, session_with_probe):
        session, probe, _ = session_with_probe
        ens_fun.create(session, probe, "epoch_1")
        ens, existing = ens_fun.create(session, probe, "epoch_1", check_existing=False)
        assert len(existing) == 1

    def test_reuses_one_ensemble_element(self, session_with_probe):
        """Calling create twice must not make a second ensemble element."""
        session, probe, _ = session_with_probe
        ens1, _ = ens_fun.create(session, probe, "epoch_1")
        ens2, _ = ens_fun.create(session, probe, "epoch_1", check_existing=False)
        assert ens1.id == ens2.id


class TestRead:
    @pytest.fixture
    def created(self, session_with_probe):
        session, probe, neurons = session_with_probe
        ens, _ = ens_fun.create(session, probe, "epoch_1")
        return session, ens

    def test_returns_the_ensemble_structure(self, created):
        session, ens = created
        E = ens_fun.read(session, ens, "epoch_1")
        assert set(E) >= {"activity", "neuron_ids", "neuron_names", "epoch", "info"}
        assert E["epoch"] == "epoch_1"
        assert len(E["neuron_ids"]) == 2
        assert E["info"]["num_neurons"] == 2

    def test_exclude_by_index_drops_a_neuron(self, created):
        session, ens = created
        E = ens_fun.read(session, ens, "epoch_1", exclude_index=[1])
        assert len(E["neuron_ids"]) == 1

    def test_include_ids_keeps_only_those(self, created):
        session, ens = created
        all_ids = ens_fun.read(session, ens, "epoch_1")["neuron_ids"]
        E = ens_fun.read(session, ens, "epoch_1", include_ids=[all_ids[0]])
        assert E["neuron_ids"] == [all_ids[0]]

    def test_no_options_returns_everything_unfiltered(self, created):
        session, ens = created
        E = ens_fun.read(session, ens, "epoch_1")
        assert len(E["neuron_ids"]) == 2

    def test_min_quality_drops_unrated_neurons(self, created):
        """No neuron here has a neuron_extracellular document, so all are
        unrated; an active quality filter must therefore drop them all."""
        session, ens = created
        E = ens_fun.read(session, ens, "epoch_1", min_quality=2)
        assert E["neuron_ids"] == []

    def test_keep_unrated_puts_them_back(self, created):
        session, ens = created
        E = ens_fun.read(session, ens, "epoch_1", min_quality=2, keep_unrated=True)
        assert len(E["neuron_ids"]) == 2

    def test_non_ensemble_element_raises(self, session_with_probe):
        session, probe, _ = session_with_probe
        with pytest.raises(TypeError, match="not an ndi_element_ensemble"):
            ens_fun.read(session, probe, "epoch_1")


class TestNeuronQuality:
    def test_all_nan_when_no_documents_exist(self, session_with_probe):
        session, probe, neurons = session_with_probe
        ids = [n.id for n in neurons.values()]
        qnum, qlabel = ens_fun.neuron_quality(session, ids)
        assert np.all(np.isnan(qnum))
        assert qlabel == ["", ""]

    def test_empty_id_list(self, session_with_probe):
        session, _, _ = session_with_probe
        qnum, qlabel = ens_fun.neuron_quality(session, [])
        assert qnum.size == 0 and qlabel == []


class TestAllElement:
    def test_builds_an_epoch_for_every_epoch(self, session_with_probe):
        session, probe, _ = session_with_probe
        ens = ens_fun.all_element(session, probe)
        assert len(ens_fun.find_existing(session, ens)) == 1  # the probe has one epoch

    def test_skip_is_idempotent(self, session_with_probe):
        session, probe, _ = session_with_probe
        ens_fun.all_element(session, probe)
        ens = ens_fun.all_element(session, probe)
        assert len(ens_fun.find_existing(session, ens)) == 1

    def test_if_exists_error_raises_on_the_second_run(self, session_with_probe):
        session, probe, _ = session_with_probe
        ens_fun.all_element(session, probe)
        with pytest.raises(ValueError, match="already exists"):
            ens_fun.all_element(session, probe, if_exists="error")

    def test_if_exists_replace_leaves_exactly_one(self, session_with_probe):
        session, probe, _ = session_with_probe
        ens_fun.all_element(session, probe)
        ens = ens_fun.all_element(session, probe, if_exists="replace")
        assert len(ens_fun.find_existing(session, ens)) == 1

    def test_bad_if_exists_is_rejected(self, session_with_probe):
        session, probe, _ = session_with_probe
        with pytest.raises(ValueError, match="if_exists"):
            ens_fun.all_element(session, probe, if_exists="clobber")


class TestAllNTrodes:
    def test_finds_the_ntrode_and_builds_its_ensemble(self, session_with_probe):
        session, probe, _ = session_with_probe
        out = ens_fun.all_ntrodes(session)
        assert len(out) == 1
        assert out[0].name == "ntrode1_ensemble"

    def test_no_ntrodes_returns_empty(self, tmp_path):
        session, _ = _session_with_subject(tmp_path, "none")
        assert ens_fun.all_ntrodes(session) == []


class TestPlot:
    def test_raster_has_one_line_per_neuron_with_spikes(self, session_with_probe):
        matplotlib = pytest.importorskip("matplotlib")
        matplotlib.use("Agg")
        session, probe, _ = session_with_probe
        ens, _ = ens_fun.create(session, probe, "epoch_1")
        E = ens_fun.read(session, ens, "epoch_1")
        ax = ens_fun.plot(E)
        assert len(ax.lines) == 2
        assert ax.get_ylabel() == "neuron"
