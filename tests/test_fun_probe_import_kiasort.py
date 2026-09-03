"""Tests for ndi.fun.probe.import_.kiasort.

MATLAB counterpart: src/ndi/+ndi/+fun/+probe/+import/+kiasort/

The end-to-end tests carry the weight: a synthetic KIASORT output directory
on disk, imported, then read back as elements with spike trains. Two things
in that path fail silently and are pinned hardest.

The first is THE INDEX BASE. KIASORT writes 1-based sample indices;
everything downstream is 0-based. Getting it wrong moves every spike by one
sample -- invisible in a raster, and wrong at 30 kHz.

The second is WHICH EPOCH A SPIKE LANDS IN. Spikes are offsets into the
concatenation the exporter wrote, and turning one back into an epoch and a
time is arithmetic with exactly one right answer. Filing a spike under the
neighbouring epoch does not raise; it just puts the response in the wrong
trial.

The probe stand-in is the one the Kilosort tests use, for the same reason: a
real probe is 'direct' and cannot be handed epochs in a test.
"""

from __future__ import annotations

import os

import h5py
import numpy as np
import pytest
from scipy.io import savemat

from ndi.element_timeseries import ndi_element_timeseries
from ndi.fun.file import elementDirectoryName
from ndi.fun.probe.import_ import kiasort
from ndi.query import ndi_query
from ndi.session import ndi_session_dir
from ndi.subject import ndi_subject
from ndi.time.clocktype import ndi_time_clocktype

SR = 30000.0
N_CH = 4
N_SAMP = 60000  # 2 s per epoch
CLOCK = "dev_local_time"


class ProbeLike(ndi_element_timeseries):
    """An element with the probe converter API the importer requires."""

    def samplerate(self, epoch=None):
        return SR

    def times2samples(self, epoch, times):
        return np.round(np.asarray(times, dtype=float) * SR).astype(int)

    def samples2times(self, epoch, samples):
        return np.asarray(samples, dtype=float) / SR


def _session(tmp_path, name="kia", n_epochs=1):
    directory = tmp_path / name
    directory.mkdir(parents=True, exist_ok=True)
    session = ndi_session_dir(name, str(directory))
    subject = ndi_subject("mouse23@vhlab.org", "test mouse").newdocument()
    subject.set_session_id(session.id())
    session.database_add(subject)

    probe = ProbeLike(
        session=session,
        name="ctx",
        reference=1,
        type="n-trode",
        direct=False,
        subject_id=subject.id,
    )
    session.database_add(probe.newdocument())
    clock = [ndi_time_clocktype(CLOCK)]
    for index in range(n_epochs):
        t0 = index * 10.0
        times = np.arange(N_SAMP) / SR + t0
        probe.addepoch(
            f"epoch_{index + 1}",
            clock,
            [(t0, t0 + N_SAMP / SR)],
            times,
            np.zeros((N_SAMP, N_CH)),
        )
    return session, probe


def _write_h5(path, name, values):
    """One KIASORT output file: a single top-level dataset, as KIASORT writes."""
    with h5py.File(path, "w") as handle:
        handle.create_dataset(name, data=np.asarray(values))


def _write_sort(
    session,
    probe,
    spikes_by_unit,
    *,
    subdir="kiasort_output",
    suffix="",
    with_stats=True,
    n_waveform_samples=61,
):
    """A synthetic KIASORT output directory in the layout the exporter writes.

    SPIKES_BY_UNIT maps unit id -> 0-based sample offsets into the
    concatenated stream; they are written back out 1-based, as KIASORT does.
    """
    dirname, _ = elementDirectoryName(probe)
    kdir = os.path.join(str(session.getpath()), "kiasort", dirname, subdir)
    res_dir = os.path.join(kdir, "RES_Sorted")
    os.makedirs(res_dir, exist_ok=True)

    samples = np.concatenate([np.asarray(v, dtype=np.int64) for v in spikes_by_unit.values()])
    units = np.concatenate(
        [np.full(len(v), int(k), dtype=np.int64) for k, v in spikes_by_unit.items()]
    )
    order = np.argsort(samples)

    # KIASORT writes 1-based sample indices.
    _write_h5(
        os.path.join(res_dir, f"spike_idx{suffix}.h5"), f"spike_idx{suffix}", samples[order] + 1
    )
    _write_h5(
        os.path.join(res_dir, f"unifiedLabels{suffix}.h5"), f"unifiedLabels{suffix}", units[order]
    )
    _write_h5(
        os.path.join(res_dir, f"channelNum{suffix}.h5"),
        f"channelNum{suffix}",
        (units[order] % N_CH) + 1,
    )

    if with_stats:
        unit_ids = np.array(sorted(spikes_by_unit), dtype=float)
        waveforms = np.zeros((unit_ids.size, n_waveform_samples, N_CH))
        for row, _uid in enumerate(unit_ids):
            # a trough on this unit's own channel, at a per-unit sample, so a
            # waveform handed to the wrong unit is visible in the numbers
            waveforms[row, 20 + row, row % N_CH] = -(row + 1.0)
        stats = {
            "crossChannelStats": {
                "unified_labels": {
                    "label": unit_ids,
                    "channelID": (unit_ids % N_CH) + 1,
                    "meanWaveforms": waveforms,
                }
            }
        }
        os.makedirs(os.path.join(kdir, "Sorted_Samples"), exist_ok=True)
        savemat(os.path.join(kdir, "Sorted_Samples", "sorted_samples.mat"), stats)

    return kdir


@pytest.fixture
def sorted_session(tmp_path):
    """A session, a probe with one epoch, and a KIASORT sort on disk."""
    session, probe = _session(tmp_path)
    spikes = {
        1: np.arange(3000, N_SAMP - 3000, 5000),
        2: np.arange(4000, N_SAMP - 3000, 7000),
    }
    kdir = _write_sort(session, probe, spikes)
    return session, probe, kdir, spikes


# ----------------------------------------------------------------------
# reading what KIASORT wrote
# ----------------------------------------------------------------------
class TestResults:
    def test_spike_samples_come_back_zero_based(self, sorted_session):
        """KIASORT writes 1-based; everything downstream is 0-based. The
        conversion happens once, here."""
        _session_obj, _probe, kdir, spikes = sorted_session
        found = kiasort.results(kdir)
        assert found.spike_samples_global.min() == float(min(s.min() for s in spikes.values()))

    def test_every_spike_carries_its_unit(self, sorted_session):
        _session_obj, _probe, kdir, spikes = sorted_session
        found = kiasort.results(kdir)
        total = sum(s.size for s in spikes.values())
        assert found.spike_units.size == total
        assert set(np.unique(found.spike_units)) == {1.0, 2.0}

    def test_the_detection_channel_is_read_when_present(self, sorted_session):
        _session_obj, _probe, kdir, _spikes = sorted_session
        assert kiasort.results(kdir).spike_channels is not None

    def test_a_sort_with_no_channel_file_is_still_readable(self, tmp_path):
        """channelNum is optional; the import needs only samples and units."""
        session, probe = _session(tmp_path)
        kdir = _write_sort(session, probe, {1: np.arange(100, 200, 10)})
        os.remove(os.path.join(kdir, "RES_Sorted", "channelNum.h5"))
        assert kiasort.results(kdir).spike_channels is None

    def test_a_missing_res_sorted_says_so(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="RES_Sorted"):
            kiasort.results(str(tmp_path))

    def test_asking_for_curated_output_that_is_absent_warns_and_falls_back(self, sorted_session):
        """A hard error would make curated=True unusable as a batch default."""
        _session_obj, _probe, kdir, _spikes = sorted_session
        with pytest.warns(UserWarning, match="Curated KIASORT outputs missing"):
            found = kiasort.results(kdir, curated=True)
        assert found.suffix == ""

    def test_curated_output_is_preferred_when_it_exists(self, tmp_path):
        session, probe = _session(tmp_path)
        _write_sort(session, probe, {1: np.arange(100, 200, 10)})
        kdir = _write_sort(
            session, probe, {7: np.arange(300, 400, 10)}, suffix="_curated", with_stats=False
        )
        found = kiasort.results(kdir, curated=True, need_stats=False)
        assert found.suffix == "_curated"
        assert set(np.unique(found.spike_units)) == {7.0}


class TestUnitStats:
    def test_the_per_unit_statistics_are_read(self, sorted_session):
        _session_obj, _probe, kdir, _spikes = sorted_session
        stats = kiasort.unitstats(kdir)
        assert stats is not None
        assert stats.label.tolist() == [1.0, 2.0]
        assert stats.meanWaveforms.shape == (2, 61, N_CH)

    def test_a_v73_mat_is_read_with_matlabs_axis_order_restored(self, tmp_path):
        """MATLAB writes v7.3 (HDF5) for anything over 2 GB, and reverses the
        dimension order doing it. Read without reversing that back, a
        (units, samples, channels) array arrives as (channels, samples,
        units) and every unit gets another unit's waveform -- silently, with
        plausible numbers. scipy refuses v7.3 outright, so this branch is the
        only reader for a big sort.
        """
        from ndi.fun.probe.import_.kiasort.unit_stats import _load_mat_v73

        path = tmp_path / "v73.mat"
        waveforms = np.arange(2 * 3 * 4, dtype=float).reshape(2, 3, 4)
        with h5py.File(path, "w") as handle:
            group = handle.create_group("crossChannelStats").create_group("unified_labels")
            group.create_dataset("label", data=np.array([1.0, 2.0]))
            # as MATLAB writes it: dimensions reversed on the way out
            group.create_dataset("meanWaveforms", data=np.transpose(waveforms))

        contents = _load_mat_v73(path)
        unified = contents["crossChannelStats"]["unified_labels"]

        assert unified["label"].tolist() == [1.0, 2.0]
        assert unified["meanWaveforms"].shape == (2, 3, 4)
        assert np.array_equal(unified["meanWaveforms"], waveforms)

    def test_no_statistics_file_is_not_an_error(self, tmp_path):
        """The per-spike output alone imports spike trains; it just carries
        no waveforms."""
        session, probe = _session(tmp_path)
        kdir = _write_sort(session, probe, {1: np.arange(100, 200, 10)}, with_stats=False)
        assert kiasort.unitstats(kdir) is None


class TestLabels:
    def test_every_unit_of_a_plain_sort_is_good(self, sorted_session):
        """KIASORT tags nothing; labelling all units 'good' is what makes the
        default filter import them rather than none."""
        _session_obj, _probe, kdir, _spikes = sorted_session
        unit_ids, unit_labels = kiasort.labels(kdir)
        assert unit_ids.tolist() == [1.0, 2.0]
        assert unit_labels == ["good", "good"]

    def test_units_are_read_from_the_spikes_when_there_are_no_statistics(self, tmp_path):
        session, probe = _session(tmp_path)
        kdir = _write_sort(
            session,
            probe,
            {4: np.arange(100, 200, 10), 9: np.arange(300, 400, 10)},
            with_stats=False,
        )
        unit_ids, _labels = kiasort.labels(kdir)
        assert unit_ids.tolist() == [4.0, 9.0]


class TestMeanWaveform:
    def test_a_unit_gets_its_own_waveform(self, sorted_session):
        """Found by LABEL, not by row: labels are unit ids, and a curated
        sort renumbers them."""
        _session_obj, _probe, kdir, _spikes = sorted_session
        stats = kiasort.unitstats(kdir)

        first = kiasort.meanwaveform(1, stats)
        second = kiasort.meanwaveform(2, stats)

        assert first.shape == (61, N_CH)
        assert np.argmin(np.min(first, axis=0)) == 0  # unit 1 -> channel 1
        assert np.argmin(np.min(second, axis=0)) == 1  # unit 2 -> channel 2

    def test_a_unit_that_is_not_in_the_statistics_has_no_waveform(self, sorted_session):
        _session_obj, _probe, kdir, _spikes = sorted_session
        assert kiasort.meanwaveform(99, kiasort.unitstats(kdir)) is None

    def test_no_statistics_means_no_waveform(self):
        assert kiasort.meanwaveform(1, None) is None


class TestStatus:
    def test_an_unexported_probe_reports_nothing_done(self, tmp_path):
        session, probe = _session(tmp_path)
        st = kiasort.status(session, probe)
        assert (st.exported, st.run, st.curated) == (False, False, False)
        assert st.words() == []

    def test_an_exported_probe_reports_exported(self, tmp_path):
        session, probe = _session(tmp_path)
        dirname, _ = elementDirectoryName(probe)
        probedir = os.path.join(str(session.getpath()), "kiasort", dirname)
        os.makedirs(probedir, exist_ok=True)
        open(os.path.join(probedir, "kiasort.bin"), "wb").close()

        st = kiasort.status(session, probe)
        assert st.words() == ["exported"]

    def test_a_sorted_probe_reports_run(self, sorted_session):
        session, probe, _kdir, _spikes = sorted_session
        assert kiasort.status(session, probe).run is True

    def test_the_states_read_in_pipeline_order(self, sorted_session):
        """ "run, exported" would be nonsense in the GUI's label."""
        session, probe, kdir, _spikes = sorted_session
        open(os.path.join(os.path.dirname(kdir), "kiasort.bin"), "wb").close()
        open(os.path.join(kdir, "RES_Sorted", "spike_idx_curated.h5"), "wb").close()

        assert kiasort.status(session, probe).words() == ["exported", "run", "curated"]


class TestGetInfo:
    def test_it_counts_the_units_and_their_spikes(self, sorted_session):
        session, probe, _kdir, spikes = sorted_session
        info, _summary = kiasort.getInfo(session, probe)

        assert info.num_units == 2
        assert info.num_spikes_total == sum(s.size for s in spikes.values())
        assert info.num_spikes.tolist() == [float(spikes[1].size), float(spikes[2].size)]

    def test_everything_would_be_imported_under_the_default_filter(self, sorted_session):
        session, probe, _kdir, _spikes = sorted_session
        info, _summary = kiasort.getInfo(session, probe)
        assert info.num_would_import == info.num_units

    def test_a_filter_that_matches_nothing_would_import_nothing(self, sorted_session):
        session, probe, _kdir, _spikes = sorted_session
        info, _summary = kiasort.getInfo(session, probe, quality_labels=["mua"])
        assert info.num_would_import == 0

    def test_it_reports_the_waveform_shape(self, sorted_session):
        session, probe, _kdir, _spikes = sorted_session
        info, _summary = kiasort.getInfo(session, probe)
        assert info.samples_per_waveform == 61
        assert info.num_channels == N_CH

    def test_the_summary_names_the_probe_and_the_counts(self, sorted_session):
        session, probe, _kdir, _spikes = sorted_session
        _info, summary = kiasort.getInfo(session, probe)
        assert "ctx | 1" in summary
        assert "Units:            2" in summary
        assert "good: 2 unit(s)" in summary

    def test_a_sort_with_no_waveforms_says_so_rather_than_reporting_nan(self, tmp_path):
        session, probe = _session(tmp_path)
        _write_sort(session, probe, {1: np.arange(100, 200, 10)}, with_stats=False)
        _info, summary = kiasort.getInfo(session, probe)
        assert "sorted_samples.mat not present" in summary

    def test_a_missing_sort_says_where_it_looked(self, tmp_path):
        session, probe = _session(tmp_path)
        with pytest.raises(FileNotFoundError, match="RES_Sorted"):
            kiasort.getInfo(session, probe)


# ----------------------------------------------------------------------
# the import itself
# ----------------------------------------------------------------------
def _neurons(session):
    return session.database_search(ndi_query("element.type") == "spikes")


class TestImport:
    def test_every_unit_becomes_a_neuron(self, sorted_session):
        session, probe, _kdir, _spikes = sorted_session

        imported = kiasort.probe(session, probe, verbose=False)

        assert imported == 2
        assert len(_neurons(session)) == 2

    def test_the_neuron_name_carries_the_probe_reference(self, sorted_session):
        """Probes routinely share a name (ctx references 1..6); unit 3 of
        each would collide without it."""
        session, probe, _kdir, _spikes = sorted_session
        kiasort.probe(session, probe, verbose=False)

        names = {doc.document_properties["element"]["name"] for doc in _neurons(session)}
        assert names == {"ctx_1_1", "ctx_1_2"}

    def test_each_neuron_gets_a_neuron_extracellular_document(self, sorted_session):
        session, probe, _kdir, _spikes = sorted_session
        kiasort.probe(session, probe, verbose=False)

        docs = session.database_search(ndi_query("").isa("neuron_extracellular"))
        assert len(docs) == 2
        assert {d.document_properties["neuron_extracellular"]["cluster_index"] for d in docs} == {
            1,
            2,
        }

    def test_the_quality_label_and_number_are_stored(self, sorted_session):
        session, probe, _kdir, _spikes = sorted_session
        kiasort.probe(session, probe, verbose=False)

        doc = session.database_search(ndi_query("").isa("neuron_extracellular"))[0]
        extracellular = doc.document_properties["neuron_extracellular"]
        assert extracellular["quality_label"] == "good"
        assert extracellular["quality_number"] == 1.0

    def test_the_mean_waveform_is_stored_with_its_shape(self, sorted_session):
        session, probe, _kdir, _spikes = sorted_session
        kiasort.probe(session, probe, verbose=False)

        docs = session.database_search(ndi_query("").isa("neuron_extracellular"))
        extracellular = docs[0].document_properties["neuron_extracellular"]
        assert extracellular["number_of_samples_per_channel"] == 61
        assert extracellular["number_of_channels"] == N_CH

    def test_waveform_times_put_zero_at_the_trough(self, sorted_session):
        """The only landmark a mean waveform carries, and what makes two
        neurons' waveforms comparable."""
        session, probe, _kdir, _spikes = sorted_session
        kiasort.probe(session, probe, verbose=False)

        docs = session.database_search(ndi_query("").isa("neuron_extracellular"))
        for doc in docs:
            extracellular = doc.document_properties["neuron_extracellular"]
            times = np.asarray(extracellular["waveform_sample_times"], dtype=float).ravel()
            waveform = np.asarray(extracellular["mean_waveform"], dtype=float)
            trough_channel = int(np.argmin(np.min(waveform, axis=0)))
            trough_sample = int(np.argmin(waveform[:, trough_channel]))
            assert times[trough_sample] == pytest.approx(0.0)

    def test_waveform_source_none_imports_spike_trains_only(self, sorted_session):
        session, probe, _kdir, _spikes = sorted_session
        kiasort.probe(session, probe, waveform_source="none", verbose=False)

        doc = session.database_search(ndi_query("").isa("neuron_extracellular"))[0]
        extracellular = doc.document_properties["neuron_extracellular"]
        assert extracellular["number_of_samples_per_channel"] == 1
        assert extracellular["number_of_channels"] == 1

    def test_the_spike_times_come_back_where_they_were_put(self, sorted_session):
        """The whole point of the import: a 0-based offset into the exported
        concatenation, read back as a time in its epoch."""
        session, probe, _kdir, spikes = sorted_session
        kiasort.probe(session, probe, verbose=False)

        docs = _neurons(session)
        by_name = {d.document_properties["element"]["name"]: d for d in docs}
        neuron = ndi_element_timeseries(session=session, document=by_name["ctx_1_1"])
        data, times, _ref = neuron.readtimeseries("epoch_1", -np.inf, np.inf)

        # 0-based sample / rate: Python's samples2times is 0-based where
        # MATLAB's is 1-based, so neither language adds the other's offset.
        expected = spikes[1] / SR
        assert np.asarray(times).ravel().size == spikes[1].size
        assert np.allclose(np.sort(np.asarray(times).ravel()), np.sort(expected))
        assert np.all(np.asarray(data).ravel() == 1.0)

    def test_only_the_labels_asked_for_are_imported(self, sorted_session):
        session, probe, _kdir, _spikes = sorted_session
        imported = kiasort.probe(
            session, probe, quality_labels=["mua"], quality_values=[2], verbose=False
        )
        assert imported == 0
        assert _neurons(session) == []

    def test_mismatched_label_and_value_lists_are_refused(self, sorted_session):
        session, probe, _kdir, _spikes = sorted_session
        with pytest.raises(ValueError, match="same number of elements"):
            kiasort.probe(session, probe, quality_labels=["good", "mua"], quality_values=[1])

    def test_an_unknown_waveform_source_is_refused(self, sorted_session):
        session, probe, _kdir, _spikes = sorted_session
        with pytest.raises(ValueError, match="waveform_source"):
            kiasort.probe(session, probe, waveform_source="telepathy")

    def test_a_dry_run_changes_nothing(self, sorted_session):
        session, probe, _kdir, _spikes = sorted_session

        imported = kiasort.probe(session, probe, dryRun=True, verbose=False)

        assert imported == 2
        assert _neurons(session) == []
        assert session.database_search(ndi_query("").isa("kiasort_clusters")) == []


class TestIdempotency:
    def test_a_second_import_of_the_same_sort_does_nothing(self, sorted_session):
        session, probe, _kdir, _spikes = sorted_session
        kiasort.probe(session, probe, verbose=False)

        again = kiasort.probe(session, probe, verbose=False)

        assert again == 0
        assert len(_neurons(session)) == 2

    def test_force_reimports_an_unchanged_sort(self, sorted_session):
        session, probe, _kdir, _spikes = sorted_session
        kiasort.probe(session, probe, verbose=False)

        again = kiasort.probe(session, probe, force=True, verbose=False)

        assert again == 2
        assert len(_neurons(session)) == 2  # the old ones went first

    def test_a_changed_sort_replaces_the_old_neurons(self, sorted_session):
        """Two generations of neurons for one probe would be
        indistinguishable from each other."""
        session, probe, _kdir, _spikes = sorted_session
        kiasort.probe(session, probe, verbose=False)

        _write_sort(session, probe, {5: np.arange(1000, N_SAMP - 3000, 9000)})
        kiasort.probe(session, probe, verbose=False)

        names = {doc.document_properties["element"]["name"] for doc in _neurons(session)}
        assert names == {"ctx_1_5"}

    def test_the_cluster_document_records_the_checksum(self, sorted_session):
        session, probe, _kdir, _spikes = sorted_session
        kiasort.probe(session, probe, verbose=False)

        docs = session.database_search(ndi_query("").isa("kiasort_clusters"))
        assert len(docs) == 1
        assert docs[0].document_properties["kiasort_clusters"]["curated_output_MD5_checksum"]

    def test_the_neurons_depend_on_that_document(self, sorted_session):
        session, probe, _kdir, _spikes = sorted_session
        kiasort.probe(session, probe, verbose=False)

        cluster = session.database_search(ndi_query("").isa("kiasort_clusters"))[0]
        for doc in session.database_search(ndi_query("").isa("neuron_extracellular")):
            assert doc.dependency_value("spike_clusters_id") == cluster.id


class TestEpochMapping:
    def test_spikes_are_filed_under_the_epoch_they_fall_in(self, tmp_path):
        """The arithmetic with exactly one right answer: an offset past the
        first epoch's length belongs to the second.

        Counted per epoch and keyed by epoch id rather than compared as
        times: the fixture's samples2times is the plain 0-based converter and
        adds no per-epoch t0, so the two epochs' times overlap and only the
        counts say which epoch a spike was filed under.
        """
        session, probe = _session(tmp_path, n_epochs=2)
        probe_table, _hash = probe.epochtable()
        first_epoch = probe_table[0]["epoch_id"]
        first = np.array([1000, 2000, 3000])
        second = np.array([N_SAMP + 500])
        _write_sort(session, probe, {1: np.concatenate([first, second])})

        kiasort.probe(session, probe, verbose=False)

        neuron = ndi_element_timeseries(session=session, document=_neurons(session)[0])
        neuron_table, _hash = neuron.epochtable()
        counts = {}
        for entry in neuron_table:
            _data, times, _ref = neuron.readtimeseries(entry["epoch_id"], -np.inf, np.inf)
            counts[entry["epoch_id"]] = len(np.atleast_1d(times))

        assert sorted(counts.values()) == [second.size, first.size]
        # the first epoch of the PROBE's epochtable order -- the order the
        # export concatenated in -- holds the low sample offsets
        assert counts[first_epoch] == first.size

    def test_a_sort_of_another_recording_is_refused(self, tmp_path):
        """Out-of-range offsets mean the sort is not this probe's. Caught, it
        is one clear error; missed, the spikes are silently dropped."""
        session, probe = _session(tmp_path)
        _write_sort(session, probe, {1: np.array([10, N_SAMP + 10_000])})

        with pytest.raises(ValueError, match="outside the probe's epochs"):
            kiasort.probe(session, probe, verbose=False)

    def test_an_empty_epoch_still_gets_an_entry(self, tmp_path):
        """A neuron silent in one epoch is silent, not absent: the epoch has
        to exist for a later reader to say so."""
        session, probe = _session(tmp_path, n_epochs=2)
        _write_sort(session, probe, {1: np.array([1000, 2000])})

        kiasort.probe(session, probe, verbose=False)

        neuron = ndi_element_timeseries(session=session, document=_neurons(session)[0])
        table, _hash = neuron.epochtable()
        assert len(table) == 2


class TestSessionImport:
    def test_every_probe_with_a_sort_is_imported(self, sorted_session, monkeypatch):
        session, probe, _kdir, _spikes = sorted_session
        monkeypatch.setattr(type(session), "getprobes", lambda self, **kw: [probe], raising=False)
        assert kiasort.session(session, verbose=False) == 2

    def test_a_probe_with_no_sort_is_skipped_with_a_warning(self, tmp_path, monkeypatch):
        """Some probes sorted and some not is the normal state of a session;
        the sorted ones are still worth importing."""
        session, probe = _session(tmp_path)
        monkeypatch.setattr(type(session), "getprobes", lambda self, **kw: [probe], raising=False)
        with pytest.warns(UserWarning, match="no KIASORT output"):
            assert kiasort.session(session, verbose=False) == 0


class TestRemoveOld:
    def test_it_removes_the_neurons_and_the_marker(self, sorted_session):
        session, probe, _kdir, _spikes = sorted_session
        kiasort.probe(session, probe, verbose=False)
        cluster = session.database_search(ndi_query("").isa("kiasort_clusters"))[0]

        kiasort.removeold(session, cluster)

        assert _neurons(session) == []
        assert session.database_search(ndi_query("").isa("neuron_extracellular")) == []
        assert session.database_search(ndi_query("").isa("kiasort_clusters")) == []


# ----------------------------------------------------------------------
# what is deliberately not ported
# ----------------------------------------------------------------------
class TestUnportedEntryPoints:
    @pytest.mark.parametrize("name", ["run", "curate"])
    def test_they_raise_a_message_that_says_what_to_do(self, name):
        """Present so the failure is a sentence rather than an AttributeError
        for a caller who expected MATLAB's package shape."""
        with pytest.raises(NotImplementedError) as excinfo:
            getattr(kiasort, name)()
        message = str(excinfo.value)
        assert "MATLAB" in message
        assert "import.kiasort.probe" in message

    def test_the_import_half_is_all_present(self):
        for name in ("probe", "session", "getInfo", "status", "results", "labels"):
            assert callable(getattr(kiasort, name))
