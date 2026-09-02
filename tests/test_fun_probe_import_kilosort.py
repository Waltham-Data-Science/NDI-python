"""Tests for ndi.fun.probe.import_.kilosort and ndi.fun.probe.extracellularInfo.

MATLAB counterparts: src/ndi/+ndi/+fun/+probe/+import/+kilosort/ and
ndi.fun.probe.extracellularInfo

This is the subsystem that MAKES NEURONS: until it landed, nothing in the
Python port could create the 'spikes' elements that ndi.fun.ensemble reads,
because ndi.app.spikesorter.clusters2neurons raises NotImplementedError. So
the tests that matter most are the end-to-end ones -- a synthetic Phy output
directory on disk, imported, then read back as elements with spike trains --
and the numeric ones over a synthetic raw binary, where a silent off-by-one
would produce plausible-looking wrong waveforms rather than an error.

The probe stand-in is an element_timeseries carrying the three converter
methods a real ndi.probe.timeseries has (samplerate, times2samples,
samples2times). A real probe is 'direct' -- its epochs come from a daq system
-- so it cannot be handed epochs in a test; the converters are spelled out
exactly as ndi.probe.timeseries defines them, 0-based.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from ndi.element_timeseries import ndi_element_timeseries
from ndi.fun.file import elementDirectory, elementDirectoryName
from ndi.fun.probe import extracellularInfo
from ndi.fun.probe.import_ import kilosort
from ndi.fun.probe.import_.kilosort.binary_info import read_params_py
from ndi.fun.probe.import_.kilosort.recalculate_mean_waveforms import (
    select_spikes,
    window_offsets,
)
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


def _session(tmp_path, name="ks", n_epochs=1):
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


def _write_sort(session, probe, spikes_by_cluster, labels, *, subdir="kilosort_output"):
    """A synthetic Phy output directory in the layout the exporter writes."""
    dirname, _ = elementDirectoryName(probe)
    kdir = os.path.join(str(session.getpath()), "kilosort", dirname, subdir)
    os.makedirs(kdir, exist_ok=True)

    samples = np.concatenate([np.asarray(v, dtype=np.int64) for v in spikes_by_cluster.values()])
    clusters = np.concatenate(
        [np.full(len(v), int(k), dtype=np.int32) for k, v in spikes_by_cluster.items()]
    )
    order = np.argsort(samples)
    np.save(os.path.join(kdir, "spike_times.npy"), samples[order])
    np.save(os.path.join(kdir, "spike_clusters.npy"), clusters[order])

    with open(os.path.join(kdir, "cluster_group.tsv"), "w", encoding="utf-8") as handle:
        handle.write("cluster_id\tgroup\n")
        for cid, label in labels.items():
            handle.write(f"{cid}\t{label}\n")

    n_clusters = len(spikes_by_cluster)
    templates = np.zeros((n_clusters, 61, N_CH))
    for index in range(n_clusters):
        templates[index, :, index % N_CH] = -np.exp(-((np.arange(61) - 20) ** 2) / 20.0)
    np.save(os.path.join(kdir, "templates.npy"), templates.astype(np.float32))
    np.save(
        os.path.join(kdir, "spike_templates.npy"),
        (clusters[order] - min(spikes_by_cluster)).astype(np.int32),
    )
    np.save(
        os.path.join(kdir, "amplitudes.npy"),
        np.full(samples.size, 10.0, dtype=np.float32),
    )
    return kdir


@pytest.fixture
def sorted_session(tmp_path):
    """A session, a probe with one epoch, and a curated sort on disk."""
    session, probe = _session(tmp_path)
    spikes = {
        1: np.arange(3000, N_SAMP - 3000, 5000),  # good
        2: np.arange(4000, N_SAMP - 3000, 7000),  # mua
        3: np.arange(5000, N_SAMP - 3000, 11000),  # noise, filtered out
    }
    kdir = _write_sort(session, probe, spikes, {1: "good", 2: "mua", 3: "noise"})
    return session, probe, kdir, spikes


# ----------------------------------------------------------------------
# reading what Phy wrote
# ----------------------------------------------------------------------
class TestLabels:
    def test_reads_cluster_group_tsv(self, sorted_session):
        _, _, kdir, _ = sorted_session
        ids, labels = kilosort.labels(kdir)
        assert list(ids) == [1.0, 2.0, 3.0]
        assert labels == ["good", "mua", "noise"]

    def test_prefers_manual_curation_over_kilosort_labels(self, tmp_path):
        """cluster_group.tsv is the curator's word; KSLabel is the machine's."""
        kdir = tmp_path / "ks"
        kdir.mkdir()
        (kdir / "cluster_KSLabel.tsv").write_text("cluster_id\tKSLabel\n1\tmua\n")
        (kdir / "cluster_group.tsv").write_text("cluster_id\tgroup\n1\tgood\n")
        _, labels = kilosort.labels(kdir)
        assert labels == ["good"]

    def test_falls_back_to_kslabel(self, tmp_path):
        kdir = tmp_path / "ks"
        kdir.mkdir()
        (kdir / "cluster_KSLabel.tsv").write_text("cluster_id\tKSLabel\n7\tmua\n")
        ids, labels = kilosort.labels(kdir)
        assert list(ids) == [7.0] and labels == ["mua"]

    def test_accepts_the_id_column_spelling_phy_sometimes_uses(self, tmp_path):
        kdir = tmp_path / "ks"
        kdir.mkdir()
        (kdir / "cluster_group.tsv").write_text("id\tgroup\n3\tgood\n")
        ids, _ = kilosort.labels(kdir)
        assert list(ids) == [3.0]

    def test_no_label_file_raises(self, tmp_path):
        kdir = tmp_path / "empty"
        kdir.mkdir()
        with pytest.raises(FileNotFoundError, match="No cluster label file"):
            kilosort.labels(kdir)


class TestParamsPy:
    def test_reads_the_keys_the_importer_needs(self, tmp_path):
        path = tmp_path / "params.py"
        path.write_text(
            "dat_path = r'temp_wh.dat'\n"
            "n_channels_dat = 385\n"
            "dtype = 'int16'\n"
            "offset = 0\n"
            "sample_rate = 30000.\n"
            "hp_filtered = True\n"
            "# a comment\n"
        )
        params = read_params_py(path)
        assert params["dat_path"] == "temp_wh.dat"
        assert params["n_channels_dat"] == 385
        assert params["dtype"] == "int16"
        assert params["sample_rate"] == 30000.0

    def test_a_trailing_comment_is_not_part_of_the_value(self, tmp_path):
        path = tmp_path / "params.py"
        path.write_text("n_channels_dat = 385  # 384 + sync\n")
        assert read_params_py(path)["n_channels_dat"] == 385


class TestBinaryInfo:
    def test_dat_path_is_reported_but_never_opened(self, tmp_path):
        """The whole point: for external sorts dat_path names a temp file."""
        kdir = tmp_path / "ks"
        kdir.mkdir()
        (kdir / "params.py").write_text("dat_path = 'temp_wh.dat'\nn_channels_dat = 385\n")
        (kdir / "temp_wh.dat").write_bytes(b"\x00" * 100)
        info = kilosort.binaryinfo(kdir)
        assert info["dat_path"] == "temp_wh.dat"
        assert info["found"] is False
        assert info["file"] == ""

    def test_the_ndi_metadata_sidecar_locates_the_binary(self, tmp_path):
        kdir = tmp_path / "ks"
        kdir.mkdir()
        (kdir / "ctx.bin").write_bytes(b"\x00" * 800)
        (kdir / "ctx.bin.metadata").write_text(
            "epoch_sample_counts: [100]\n"
            "epoch_sample_rates: [30000.0]\n"
            "multiplier: 5.128\n"
            "num_channels: 4\n"
        )
        info = kilosort.binaryinfo(kdir)
        assert info["found"] is True
        assert info["file"].endswith("ctx.bin")
        assert info["num_channels"] == 4
        assert info["multiplier"] == pytest.approx(5.128)
        assert info["sample_rate"] == pytest.approx(30000.0)

    def test_an_explicit_binary_file_that_is_missing_raises(self, tmp_path):
        kdir = tmp_path / "ks"
        kdir.mkdir()
        with pytest.raises(FileNotFoundError):
            kilosort.binaryinfo(kdir, binary_file=str(tmp_path / "nope.bin"))

    def test_a_binary_with_no_channel_count_is_not_usable(self, tmp_path):
        """Without the stride, reading the file would produce noise."""
        kdir = tmp_path / "ks"
        kdir.mkdir()
        (kdir / "ctx.bin").write_bytes(b"\x00" * 800)
        (kdir / "ctx.bin.metadata").write_text("multiplier: 1\n")
        assert kilosort.binaryinfo(kdir)["found"] is False


class TestSpikeGLXMeta:
    def test_reads_key_equals_value(self, tmp_path):
        binfile = tmp_path / "run_g0_t0.imec0.ap.bin"
        binfile.write_bytes(b"\x00" * 10)
        (tmp_path / "run_g0_t0.imec0.ap.meta").write_text(
            "nSavedChans=385\nimSampRate=30000\nfileName=run_g0_t0\n~imroTbl=(0,384)\n"
        )
        meta, path = kilosort.readspikeglxmeta(binfile)
        assert meta["nSavedChans"] == 385
        assert meta["fileName"] == "run_g0_t0"
        assert "imroTbl" in meta  # the '~' prefix is stripped
        assert path.endswith(".meta")

    def test_no_sidecar_is_not_an_error(self, tmp_path):
        binfile = tmp_path / "bare.bin"
        binfile.write_bytes(b"\x00")
        assert kilosort.readspikeglxmeta(binfile) == (None, "")


class TestNeuropixelsMultiplier:
    def test_np1_and_np2_match_matlab_s_documented_scales(self):
        m1, i1 = kilosort.neuropixelsmultiplier("NP1")
        m2, i2 = kilosort.neuropixelsmultiplier("NP2")
        assert m1 == pytest.approx(512 * 500 / 0.6)
        assert m2 == pytest.approx(8192 * 80 / 0.5)
        assert i1["uV_per_bit"] == pytest.approx(2.34, abs=0.01)
        assert i2["uV_per_bit"] == pytest.approx(0.763, abs=0.001)

    @pytest.mark.parametrize("spelling", ["np1", "NP1.0", "1", "neuropixels 1.0", "Neuropixels_1"])
    def test_the_spellings_matlab_accepts(self, spelling):
        _, info = kilosort.neuropixelsmultiplier(spelling)
        assert info["name"] == "NP1"

    def test_an_unknown_generation_raises(self):
        with pytest.raises(ValueError, match="Unrecognized probe type"):
            kilosort.neuropixelsmultiplier("NP3")


class TestMeanWaveform:
    def test_a_single_template_cluster_is_that_template_scaled(self):
        templates = np.zeros((2, 5, 3))
        templates[0, :, 1] = [0.0, -1.0, -2.0, -1.0, 0.0]
        result = kilosort.meanwaveform(
            1,
            spike_clusters=np.array([1, 1, 2]),
            spike_templates=np.array([0, 0, 1]),
            amplitudes=np.array([2.0, 4.0, 9.0]),
            templates=templates,
            winv=None,
        )
        # one contributing template, so the weighted average is the template
        # itself, scaled by the cluster's mean amplitude (3.0)
        assert result[:, 1] == pytest.approx(np.array([0.0, -3.0, -6.0, -3.0, 0.0]))

    def test_a_merged_cluster_weights_templates_by_summed_amplitude(self):
        templates = np.zeros((2, 3, 1))
        templates[0, :, 0] = [1.0, 1.0, 1.0]
        templates[1, :, 0] = [3.0, 3.0, 3.0]
        result = kilosort.meanwaveform(
            5,
            spike_clusters=np.array([5, 5]),
            spike_templates=np.array([0, 1]),
            amplitudes=np.array([1.0, 3.0]),
            templates=templates,
            winv=None,
        )
        # weights 1 and 3 -> (1*1 + 3*3)/4 = 2.5, times mean amplitude 2.0
        assert result[:, 0] == pytest.approx(np.full(3, 5.0))

    def test_a_cluster_with_no_spikes_is_zeros_of_the_right_shape(self):
        templates = np.zeros((1, 7, 2))
        result = kilosort.meanwaveform(99, np.array([1]), np.array([0]), np.array([1.0]), templates)
        assert result.shape == (7, 2)
        assert not result.any()


# ----------------------------------------------------------------------
# the numeric core: reading waveforms back out of a raw binary
# ----------------------------------------------------------------------
def _write_binary(path, n_channels, n_samples, spikes, shape, multiplier=1):
    """A raw int16 recording with SHAPE stamped at each spike sample."""
    data = np.zeros((n_samples, n_channels), dtype=np.int16)
    half = len(shape) // 2
    for spike in spikes:
        start = int(spike) - half
        data[start : start + len(shape), :] += np.asarray(
            np.round(np.outer(shape, np.ones(n_channels)) * multiplier), dtype=np.int16
        )
    data.tofile(path)
    return data


class TestWindowArithmetic:
    def test_the_window_is_inclusive_and_zero_is_the_spike(self):
        off0, off1, wst = window_offsets(1000.0, -0.005, 0.005)
        assert (off0, off1) == (-5, 5)
        assert wst.shape == (11, 1)
        assert wst[5, 0] == pytest.approx(0.0)

    def test_a_window_off_the_start_of_the_recording_is_dropped(self):
        kept = select_spikes(np.array([2, 500]), -5, 5, 1000)
        assert list(kept) == [500]

    def test_a_window_off_the_end_is_dropped(self):
        kept = select_spikes(np.array([500, 998]), -5, 5, 1000)
        assert list(kept) == [500]

    def test_a_window_straddling_an_epoch_seam_is_dropped(self):
        """The far side of a seam is a different recording session entirely."""
        kept = select_spikes(np.array([100, 498, 600]), -5, 5, 1000, epoch_bounds=[0, 500, 1000])
        assert list(kept) == [100, 600]

    def test_over_the_cap_an_evenly_spaced_subset_is_taken(self):
        kept = select_spikes(np.arange(100, 900), -5, 5, 1000, max_spikes=10)
        assert kept.size == 10
        assert kept[0] == 100 and kept[-1] == 899  # spans the whole recording


class TestRecalculateMeanWaveforms:
    def test_the_stamped_shape_comes_back(self, tmp_path):
        shape = np.array([0, -10, -40, -100, -40, -10, 0], dtype=float)
        spikes = np.arange(1000, 9000, 500)
        path = tmp_path / "raw.bin"
        _write_binary(path, N_CH, 10000, spikes, shape)

        waveforms, wst, n_used = kilosort.recalculatemeanwaveforms(
            path,
            N_CH,
            spikes,
            np.ones(spikes.size),
            [1],
            sample_rate=1000.0,
            t0=-0.003,
            t1=0.003,
        )
        assert n_used[0] == spikes.size
        assert waveforms[0].shape == (7, N_CH)
        # every channel carries the same stamped shape
        for channel in range(N_CH):
            assert waveforms[0][:, channel] == pytest.approx(shape)
        assert wst[3, 0] == pytest.approx(0.0)  # zero sits at the spike

    def test_the_multiplier_converts_counts_to_physical_units(self, tmp_path):
        shape = np.array([0, -100, 0], dtype=float)
        spikes = np.arange(500, 5000, 500)
        path = tmp_path / "raw.bin"
        _write_binary(path, 1, 6000, spikes, shape)

        waveforms, _, _ = kilosort.recalculatemeanwaveforms(
            path, 1, spikes, np.ones(spikes.size), [1], 1000.0, -0.001, 0.001, multiplier=10.0
        )
        assert waveforms[0][:, 0] == pytest.approx(shape / 10.0)

    def test_several_clusters_in_one_pass_match_their_own_shapes(self, tmp_path):
        path = tmp_path / "raw.bin"
        data = np.zeros((10000, 1), dtype=np.int16)
        spikes_a = np.arange(1000, 5000, 400)
        spikes_b = np.arange(5000, 9000, 400)
        for spike in spikes_a:
            data[spike - 1 : spike + 2, 0] += np.array([0, -50, 0], dtype=np.int16)
        for spike in spikes_b:
            data[spike - 1 : spike + 2, 0] += np.array([0, -20, 0], dtype=np.int16)
        data.tofile(path)

        samples = np.concatenate([spikes_a, spikes_b])
        clusters = np.concatenate([np.full(spikes_a.size, 1), np.full(spikes_b.size, 2)])
        waveforms, _, n_used = kilosort.recalculatemeanwaveforms(
            path, 1, samples, clusters, [1, 2], 1000.0, -0.001, 0.001
        )
        assert list(n_used) == [spikes_a.size, spikes_b.size]
        assert waveforms[0][1, 0] == pytest.approx(-50.0)
        assert waveforms[1][1, 0] == pytest.approx(-20.0)

    def test_the_chunked_pass_agrees_with_a_single_chunk(self, tmp_path):
        """Chunking is an optimisation; it must not change the answer."""
        shape = np.array([0, -30, -90, -30, 0], dtype=float)
        spikes = np.arange(1000, 9000, 137)
        path = tmp_path / "raw.bin"
        _write_binary(path, 2, 10000, spikes, shape)

        args = (path, 2, spikes, np.ones(spikes.size), [1], 1000.0, -0.002, 0.002)
        big, _, _ = kilosort.recalculatemeanwaveforms(*args, chunkSamples=100000)
        small, _, _ = kilosort.recalculatemeanwaveforms(*args, chunkSamples=200)
        assert small[0] == pytest.approx(big[0])

    def test_the_single_cluster_function_agrees_with_the_batched_one(self, tmp_path):
        shape = np.array([0, -60, 0], dtype=float)
        spikes = np.arange(1000, 9000, 300)
        path = tmp_path / "raw.bin"
        _write_binary(path, 3, 10000, spikes, shape)

        batched, _, used_batched = kilosort.recalculatemeanwaveforms(
            path, 3, spikes, np.ones(spikes.size), [1], 1000.0, -0.001, 0.001
        )
        single, _, used_single = kilosort.recalculatemeanwaveform(
            path, 3, spikes, 1000.0, -0.001, 0.001
        )
        assert used_single == used_batched[0]
        assert single == pytest.approx(batched[0])

    def test_high_pass_filtering_removes_a_dc_offset(self, tmp_path):
        """A hand-selected raw recording is unfiltered; this is why it matters."""
        shape = np.array([0, -100, 0], dtype=float)
        spikes = np.arange(2000, 8000, 200)
        path = tmp_path / "raw.bin"
        data = np.full((10000, 1), 500, dtype=np.int16)  # a large DC offset
        for spike in spikes:
            data[spike - 1 : spike + 2, 0] += np.asarray(shape, dtype=np.int16)
        data.tofile(path)

        unfiltered, _, _ = kilosort.recalculatemeanwaveforms(
            path, 1, spikes, np.ones(spikes.size), [1], 30000.0, -0.001, 0.001
        )
        filtered, _, _ = kilosort.recalculatemeanwaveforms(
            path, 1, spikes, np.ones(spikes.size), [1], 30000.0, -0.001, 0.001, highpass=True
        )
        assert unfiltered[0].mean() == pytest.approx(500, abs=20)
        assert abs(filtered[0].mean()) < 20  # the offset is gone

    def test_a_bad_window_raises(self, tmp_path):
        path = tmp_path / "raw.bin"
        path.write_bytes(b"\x00" * 100)
        with pytest.raises(ValueError, match="window end"):
            kilosort.recalculatemeanwaveforms(path, 1, [10], [1], [1], 1000.0, 0.005, -0.005)

    def test_an_unsupported_dtype_raises(self, tmp_path):
        path = tmp_path / "raw.bin"
        path.write_bytes(b"\x00" * 100)
        with pytest.raises(ValueError, match="Unsupported dtype"):
            kilosort.recalculatemeanwaveforms(
                path, 1, [10], [1], [1], 1000.0, -0.001, 0.001, dtype="complex"
            )


# ----------------------------------------------------------------------
# promptrawbinary: the checks that stop a wrong stride reading noise
# ----------------------------------------------------------------------
class Answers:
    """The three prompts, answered by a caller with no display."""

    def __init__(self, path="", probe_type="NP1", channels=None):
        self.path = path
        self._probe_type = probe_type
        self.channels = channels

    def raw_file(self):
        return self.path

    def probe_type(self, binfile):
        return self._probe_type

    def channel_count(self, binfile, suggested):
        return self.channels


class TestPromptRawBinary:
    def _base(self):
        return {
            "found": False,
            "file": "",
            "num_channels": float("nan"),
            "dtype": "int16",
            "byteOrder": "ieee-le",
            "headerOffsetBytes": 0,
            "multiplier": 1,
            "sample_rate": float("nan"),
            "dat_path": "",
        }

    def test_a_supplied_file_and_type_need_no_dialog(self, tmp_path):
        path = tmp_path / "raw.bin"
        path.write_bytes(b"\x00" * (2 * 4 * 100))  # 4 channels x 100 samples
        info = kilosort.promptrawbinary(
            self._base(),
            RawFile=str(path),
            ProbeType="NP1",
            PromptForRawFile=False,
            num_channels=4,
        )
        assert info["found"] is True
        assert info["num_channels"] == 4
        assert info["probe_type"] == "NP1"
        assert info["multiplier"] == pytest.approx(512 * 500 / 0.6)

    def test_the_stride_comes_from_the_spikeglx_sidecar(self, tmp_path):
        path = tmp_path / "run.ap.bin"
        path.write_bytes(b"\x00" * (2 * 385 * 50))
        (tmp_path / "run.ap.meta").write_text("nSavedChans=385\n")
        info = kilosort.promptrawbinary(
            self._base(), RawFile=str(path), ProbeType="NP1", PromptForRawFile=False
        )
        assert info["num_channels"] == 385

    def test_a_stride_that_does_not_divide_the_file_raises(self, tmp_path):
        path = tmp_path / "raw.bin"
        path.write_bytes(b"\x00" * 101)  # not a multiple of 2 x 3
        with pytest.raises(ValueError, match="not an exact multiple"):
            kilosort.promptrawbinary(
                self._base(),
                RawFile=str(path),
                ProbeType="NP1",
                PromptForRawFile=False,
                num_channels=3,
            )

    def test_a_duration_mismatch_raises(self, tmp_path):
        """The guard that catches 384-vs-385 before it reads noise."""
        path = tmp_path / "raw.bin"
        path.write_bytes(b"\x00" * (2 * 385 * 100))
        with pytest.raises(ValueError, match="mismatch"):
            kilosort.promptrawbinary(
                self._base(),
                RawFile=str(path),
                ProbeType="NP1",
                PromptForRawFile=False,
                num_channels=385,
                expectedSamples=250,
            )

    def test_a_matching_duration_passes(self, tmp_path):
        path = tmp_path / "raw.bin"
        path.write_bytes(b"\x00" * (2 * 385 * 100))
        info = kilosort.promptrawbinary(
            self._base(),
            RawFile=str(path),
            ProbeType="NP1",
            PromptForRawFile=False,
            num_channels=385,
            expectedSamples=100,
        )
        assert info["found"] is True

    def test_headless_without_a_file_raises_rather_than_blocking(self):
        with pytest.raises(ValueError, match="No raw recording available"):
            kilosort.promptrawbinary(self._base(), PromptForRawFile=False)

    def test_cancelling_the_file_dialog_is_not_an_error(self):
        info = kilosort.promptrawbinary(self._base(), ask=Answers(path=""))
        assert info["found"] is False

    def test_the_answers_object_supplies_every_prompt(self, tmp_path):
        path = tmp_path / "raw.bin"
        path.write_bytes(b"\x00" * (2 * 2 * 10))
        info = kilosort.promptrawbinary(
            self._base(), ask=Answers(path=str(path), probe_type="NP2", channels=2)
        )
        assert info["found"] is True
        assert info["probe_type"] == "NP2"


# ----------------------------------------------------------------------
# getInfo: what is on disk, before anything is imported
# ----------------------------------------------------------------------
class TestGetInfo:
    def test_reports_the_clusters_and_their_tags(self, sorted_session):
        session, probe, kdir, spikes = sorted_session
        info, summary = kilosort.getInfo(session, probe)
        assert info["num_clusters"] == 3
        assert list(info["cluster_ids"]) == [1.0, 2.0, 3.0]
        assert info["unique_tags"] == ["good", "mua", "noise"]
        assert info["num_spikes_total"] == sum(len(v) for v in spikes.values())
        assert info["directory"] == kdir
        assert "Kilosort/Phy summary" in summary

    def test_would_import_follows_the_quality_filter(self, sorted_session):
        session, probe, _, _ = sorted_session
        info, _ = kilosort.getInfo(session, probe)
        assert list(info["would_import"]) == [True, True, False]
        assert info["num_would_import"] == 2

        info_good, _ = kilosort.getInfo(session, probe, quality_labels=["good"])
        assert info_good["num_would_import"] == 1

    def test_template_dimensions_are_reported(self, sorted_session):
        session, probe, _, _ = sorted_session
        info, _ = kilosort.getInfo(session, probe)
        assert info["num_templates"] == 3
        assert info["num_channels"] == N_CH
        assert info["samples_per_template"] == 61

    def test_a_missing_directory_raises(self, tmp_path):
        session, probe = _session(tmp_path, "nosort")
        with pytest.raises(FileNotFoundError, match="Kilosort directory not found"):
            kilosort.getInfo(session, probe)

    def test_the_legacy_folder_name_is_still_found(self, tmp_path):
        """Folders written by older NDI used '|' in the element string."""
        session, probe = _session(tmp_path, "legacy")
        _, legacy = elementDirectoryName(probe)
        kdir = os.path.join(str(session.getpath()), "kilosort", legacy, "kilosort_output")
        os.makedirs(kdir)
        np.save(os.path.join(kdir, "spike_times.npy"), np.array([100], dtype=np.int64))
        np.save(os.path.join(kdir, "spike_clusters.npy"), np.array([1], dtype=np.int32))
        with open(os.path.join(kdir, "cluster_group.tsv"), "w") as handle:
            handle.write("cluster_id\tgroup\n1\tgood\n")
        info, _ = kilosort.getInfo(session, probe)
        assert info["num_clusters"] == 1

        found, name, is_legacy = elementDirectory(
            os.path.join(str(session.getpath()), "kilosort"), probe
        )
        assert is_legacy is True and name == legacy


# ----------------------------------------------------------------------
# the import itself
# ----------------------------------------------------------------------
class TestImport:
    def test_a_dry_run_changes_nothing(self, sorted_session):
        session, probe, _, _ = sorted_session
        n = kilosort.probe(
            session, probe, RecalculateMeanWaveforms=False, dryRun=True, verbose=False
        )
        assert n == 2
        assert extracellularInfo(session, probe)[0] == []
        assert session.database_search(ndi_query("").isa("kilosort_clusters")) == []

    def test_the_quality_filter_decides_what_is_imported(self, sorted_session):
        session, probe, _, _ = sorted_session
        assert kilosort.probe(session, probe, RecalculateMeanWaveforms=False, verbose=False) == 2
        entries, _ = extracellularInfo(session, probe)
        assert [e["quality_label"] for e in entries] == ["good", "mua"]
        assert [e["element_name"] for e in entries] == ["ctx_1_1", "ctx_1_2"]
        assert [e["quality_number"] for e in entries] == [1, 4]

    def test_the_neurons_are_spikes_elements_ndi_fun_ensemble_can_find(self, sorted_session):
        """The whole point of the port: this is what closes the gap."""
        session, probe, _, spikes = sorted_session
        kilosort.probe(session, probe, RecalculateMeanWaveforms=False, verbose=False)

        docs = session.database_search(
            ndi_query("").isa("element")
            & ndi_query("").depends_on("underlying_element_id", probe.id)
        )
        types = {doc.document_properties["element"]["type"] for doc in docs}
        classes = {doc.document_properties["element"]["ndi_element_class"] for doc in docs}
        assert types == {"spikes"}
        assert classes == {"ndi.neuron"}

    def test_the_spike_times_round_trip(self, sorted_session):
        session, probe, _, spikes = sorted_session
        kilosort.probe(session, probe, RecalculateMeanWaveforms=False, verbose=False)

        docs = session.database_search(
            ndi_query("").isa("element") & ndi_query("element.name", "exact_string", "ctx_1_1", "")
        )
        neuron = ndi_element_timeseries(session=session, document=docs[0])
        _, times, _ = neuron.readtimeseries("epoch_1", -np.inf, np.inf)
        # 0-based sample index / rate, NOT (index + 1) / rate: Python's
        # samples2times is 0-based where MATLAB's is 1-based
        assert np.asarray(times).ravel() == pytest.approx(spikes[1] / SR)

    def test_a_second_import_is_a_no_op(self, sorted_session):
        session, probe, _, _ = sorted_session
        kilosort.probe(session, probe, RecalculateMeanWaveforms=False, verbose=False)
        assert kilosort.probe(session, probe, RecalculateMeanWaveforms=False, verbose=False) == 0
        assert len(extracellularInfo(session, probe)[0]) == 2

    def test_force_re_imports_without_duplicating(self, sorted_session):
        session, probe, _, _ = sorted_session
        kilosort.probe(session, probe, RecalculateMeanWaveforms=False, verbose=False)
        assert (
            kilosort.probe(
                session, probe, RecalculateMeanWaveforms=False, force=True, verbose=False
            )
            == 2
        )
        assert len(extracellularInfo(session, probe)[0]) == 2
        assert len(session.database_search(ndi_query("").isa("kilosort_clusters"))) == 1

    def test_a_changed_curation_replaces_the_previous_import(self, sorted_session):
        """Re-assigning spikes changes spike_clusters.npy, which is the checksum."""
        session, probe, kdir, spikes = sorted_session
        kilosort.probe(session, probe, RecalculateMeanWaveforms=False, verbose=False)

        # a merge in Phy: cluster 3's spikes become part of cluster 1
        clusters = np.load(os.path.join(kdir, "spike_clusters.npy"))
        clusters[clusters == 3] = 1
        np.save(os.path.join(kdir, "spike_clusters.npy"), clusters)
        with open(os.path.join(kdir, "cluster_group.tsv"), "w") as handle:
            handle.write("cluster_id\tgroup\n1\tgood\n2\tmua\n")

        assert kilosort.probe(session, probe, RecalculateMeanWaveforms=False, verbose=False) == 2
        assert len(extracellularInfo(session, probe)[0]) == 2
        # the merged neuron carries both clusters' spikes now
        docs = session.database_search(
            ndi_query("").isa("element") & ndi_query("element.name", "exact_string", "ctx_1_1", "")
        )
        neuron = ndi_element_timeseries(session=session, document=docs[0])
        _, times, _ = neuron.readtimeseries("epoch_1", -np.inf, np.inf)
        assert len(np.atleast_1d(times)) == len(spikes[1]) + len(spikes[3])

    def test_a_relabel_alone_is_not_detected(self, sorted_session):
        """The checksum is of spike_clusters.npy, so LABELS are not covered.

        Changing only cluster_group.tsv leaves the checksum unchanged and the
        import reports nothing to do -- MATLAB's behaviour, and a real
        surprise worth pinning: force is what re-imports after a relabel.
        """
        session, probe, kdir, _ = sorted_session
        kilosort.probe(session, probe, RecalculateMeanWaveforms=False, verbose=False)
        with open(os.path.join(kdir, "cluster_group.tsv"), "w") as handle:
            handle.write("cluster_id\tgroup\n1\tgood\n2\tmua\n3\tgood\n")

        assert kilosort.probe(session, probe, RecalculateMeanWaveforms=False, verbose=False) == 0
        assert len(extracellularInfo(session, probe)[0]) == 2
        assert (
            kilosort.probe(
                session, probe, RecalculateMeanWaveforms=False, force=True, verbose=False
            )
            == 3
        )

    def test_spikes_past_the_end_of_the_epochs_raise(self, tmp_path):
        """A sort that does not belong to this probe is caught, not trimmed."""
        session, probe = _session(tmp_path, "wrong")
        _write_sort(session, probe, {1: np.array([10, N_SAMP + 5000])}, {1: "good"})
        with pytest.raises(ValueError, match="outside the probe's epochs"):
            kilosort.probe(session, probe, RecalculateMeanWaveforms=False, verbose=False)

    def test_spikes_are_split_across_epochs_by_the_sample_bounds(self, tmp_path):
        session, probe = _session(tmp_path, "two", n_epochs=2)
        table, _ = probe.epochtable()
        first_epoch = table[0]["epoch_id"]
        # one spike in the first epoch of the CONCATENATION, one in the second
        _write_sort(session, probe, {1: np.array([1000, N_SAMP + 2000])}, {1: "good"})
        kilosort.probe(session, probe, RecalculateMeanWaveforms=False, verbose=False)

        docs = session.database_search(
            ndi_query("").isa("element") & ndi_query("element.name", "exact_string", "ctx_1_1", "")
        )
        neuron = ndi_element_timeseries(session=session, document=docs[0])
        counts = {}
        neuron_table, _ = neuron.epochtable()
        for entry in neuron_table:
            _, times, _ = neuron.readtimeseries(entry["epoch_id"], -np.inf, np.inf)
            counts[entry["epoch_id"]] = len(np.atleast_1d(times))
        assert sorted(counts.values()) == [1, 1]
        # the first epoch of epochtable() order holds the first sample
        assert counts[first_epoch] == 1

    def test_waveform_source_none_stores_no_waveform(self, sorted_session):
        session, probe, _, _ = sorted_session
        kilosort.probe(
            session, probe, waveform_source="none", RecalculateMeanWaveforms=False, verbose=False
        )
        entries, _ = extracellularInfo(session, probe)
        properties = entries[0]["neuron_extracellular"]
        # DIVERGENCE, documented in _storable_waveform: MATLAB stores an empty
        # matrix here, which this port's schema validator rejects, so the
        # single zero sample its counts already describe is stored instead.
        assert properties["mean_waveform"] == [[0.0]]
        assert properties["number_of_samples_per_channel"] == 1
        assert properties["number_of_channels"] == 1

    def test_template_waveforms_are_stored_with_their_sample_times(self, sorted_session):
        session, probe, _, _ = sorted_session
        kilosort.probe(session, probe, RecalculateMeanWaveforms=False, verbose=False)
        entry = extracellularInfo(session, probe)[0][0]
        properties = entry["neuron_extracellular"]
        assert properties["number_of_samples_per_channel"] == 61
        assert properties["number_of_channels"] == N_CH
        assert len(properties["waveform_sample_times"]) == 61

    def test_mismatched_label_and_value_lists_raise(self, sorted_session):
        session, probe, _, _ = sorted_session
        with pytest.raises(ValueError, match="same length"):
            kilosort.probe(session, probe, quality_labels=["good"], quality_values=[1, 4])

    def test_an_unknown_waveform_source_raises(self, sorted_session):
        session, probe, _, _ = sorted_session
        with pytest.raises(ValueError, match="waveform_source"):
            kilosort.probe(session, probe, waveform_source="magic")

    def test_the_provenance_records_the_pipeline_and_version(self, sorted_session):
        session, probe, _, _ = sorted_session
        kilosort.probe(
            session, probe, RecalculateMeanWaveforms=False, kilosort_version="3.0", verbose=False
        )
        entry = extracellularInfo(session, probe)[0][0]
        assert entry["pipeline"].startswith("Kilosort3.0 to phy to")

    def test_removing_the_import_takes_the_neurons_with_it(self, sorted_session):
        session, probe, _, _ = sorted_session
        kilosort.probe(session, probe, RecalculateMeanWaveforms=False, verbose=False)
        cluster_docs = session.database_search(ndi_query("").isa("kilosort_clusters"))
        kilosort.removeold(session, cluster_docs[0])

        assert extracellularInfo(session, probe)[0] == []
        assert session.database_search(ndi_query("").isa("kilosort_clusters")) == []
        assert (
            session.database_search(
                ndi_query("").isa("element")
                & ndi_query("").depends_on("underlying_element_id", probe.id)
            )
            == []
        )


class TestImportWithRawBinary:
    def test_wide_waveforms_are_read_from_the_binary(self, tmp_path):
        """The path the whole binaryinfo/recalculate machinery exists for."""
        session, probe = _session(tmp_path, "raw")
        spikes = np.arange(3000, N_SAMP - 3000, 4000)
        kdir = _write_sort(session, probe, {1: spikes}, {1: "good"})

        # an NDI-style export beside the sort: binary plus .metadata sidecar
        shape = np.array([0, -20, -80, -200, -80, -20, 0], dtype=float)
        binary = os.path.join(kdir, "ctx.bin")
        _write_binary(binary, N_CH, N_SAMP, spikes, shape)
        with open(binary + ".metadata", "w") as handle:
            handle.write(
                f"epoch_sample_counts: [{N_SAMP}]\n"
                f"epoch_sample_rates: [{SR}]\n"
                "multiplier: 1\n"
                f"num_channels: {N_CH}\n"
            )

        info, _ = kilosort.getInfo(session, probe)
        assert info["binary_found"] is True

        n = kilosort.probe(
            session,
            probe,
            RecalculateMeanWaveformT0=-0.0001,  # +/- 3 samples at 30 kHz
            RecalculateMeanWaveformT1=0.0001,
            HighPassFilter=False,
            verbose=False,
        )
        assert n == 1
        entry = extracellularInfo(session, probe)[0][0]
        waveform = np.asarray(entry["neuron_extracellular"]["mean_waveform"])
        assert waveform.shape == (7, N_CH)
        assert waveform[:, 0] == pytest.approx(shape)
        # zero sits at the spike, so the trough is in the middle
        times = np.asarray(entry["neuron_extracellular"]["waveform_sample_times"])
        assert times[3] == pytest.approx(0.0)

    def test_a_missing_binary_falls_back_to_templates_with_a_warning(self, sorted_session):
        session, probe, _, _ = sorted_session
        with pytest.warns(UserWarning, match="no raw binary could be located"):
            kilosort.probe(session, probe, PromptForRawFile=False, verbose=False)
        entry = extracellularInfo(session, probe)[0][0]
        # the narrow template width, not a recalculated window
        assert entry["neuron_extracellular"]["number_of_samples_per_channel"] == 61


# ----------------------------------------------------------------------
# session-wide import
# ----------------------------------------------------------------------
class TestSessionImport:
    def test_imports_every_probe_that_has_a_sort(self, sorted_session, monkeypatch):
        session, probe, _, _ = sorted_session
        monkeypatch.setattr(type(session), "getprobes", lambda self, **kw: [probe], raising=False)
        with pytest.warns(UserWarning, match="no raw binary"):
            assert kilosort.session(session, verbose=False, PromptForRawFile=False) == 2

    def test_a_probe_with_no_sort_is_skipped_with_a_warning(self, tmp_path, monkeypatch):
        session, probe = _session(tmp_path, "nosort")
        monkeypatch.setattr(type(session), "getprobes", lambda self, **kw: [probe], raising=False)
        with pytest.warns(UserWarning, match="no kilosort output"):
            assert kilosort.session(session, verbose=False) == 0


# ----------------------------------------------------------------------
# extracellularInfo
# ----------------------------------------------------------------------
class TestExtracellularInfo:
    def test_nothing_imported_is_an_empty_list(self, sorted_session):
        session, probe, _, _ = sorted_session
        entries, summary = extracellularInfo(session, probe)
        assert entries == []
        assert "no neuron_extracellular documents" in summary

    def test_entries_are_sorted_by_cluster_index(self, sorted_session):
        session, probe, _, _ = sorted_session
        kilosort.probe(session, probe, RecalculateMeanWaveforms=False, verbose=False)
        entries, summary = extracellularInfo(session, probe)
        assert [e["cluster_index"] for e in entries] == [1, 2]
        assert "Imported extracellular neurons" in summary
        assert "good: 1 neuron(s)" in summary

    def test_the_quality_filter_narrows_the_list(self, sorted_session):
        session, probe, _, _ = sorted_session
        kilosort.probe(session, probe, RecalculateMeanWaveforms=False, verbose=False)
        entries, _ = extracellularInfo(session, probe, quality_labels=["good"])
        assert [e["quality_label"] for e in entries] == ["good"]

    def test_another_probe_s_neurons_are_not_listed(self, tmp_path):
        session, probe = _session(tmp_path, "two_probes")
        _write_sort(session, probe, {1: np.arange(3000, 20000, 4000)}, {1: "good"})
        kilosort.probe(session, probe, RecalculateMeanWaveforms=False, verbose=False)

        other = ProbeLike(
            session=session,
            name="other",
            reference=2,
            type="n-trode",
            direct=False,
            subject_id=probe.subject_id,
        )
        session.database_add(other.newdocument())
        assert extracellularInfo(session, other)[0] == []
        assert len(extracellularInfo(session, probe)[0]) == 1


# ----------------------------------------------------------------------
# add_multiple, the batched writer the importer commits through
# ----------------------------------------------------------------------
class TestAddMultiple:
    def test_creates_elements_epochs_and_extra_documents(self, tmp_path):
        from ndi.document import ndi_document

        session, probe = _session(tmp_path, "batch")
        clock = ndi_time_clocktype(CLOCK)
        extra = ndi_document(
            "neuron_extracellular",
            **{
                "neuron_extracellular.cluster_index": 7,
                "neuron_extracellular.number_of_samples_per_channel": 1,
                "neuron_extracellular.number_of_channels": 1,
                "neuron_extracellular.mean_waveform": [[0.0]],
                "neuron_extracellular.waveform_sample_times": [0.0],
                "neuron_extracellular.quality_number": 1,
                "neuron_extracellular.quality_label": "good",
            },
        )
        extra.set_session_id(session.id())

        ndi_element_timeseries.add_multiple(
            session,
            probe,
            [
                {
                    "name": "n1",
                    "reference": 1,
                    "type": "spikes",
                    "epochs": [
                        {
                            "epoch_id": "epoch_1",
                            "epoch_clock": clock,
                            "t0_t1": (0.0, 2.0),
                            "timepoints": np.array([0.1, 0.5]),
                            "datapoints": np.ones(2),
                        }
                    ],
                    "extra_documents": [extra],
                }
            ],
        )

        docs = session.database_search(
            ndi_query("").isa("element") & ndi_query("element.name", "exact_string", "n1", "")
        )
        assert len(docs) == 1
        assert docs[0].document_properties["element"]["ndi_element_class"] == "ndi.neuron"

        neuron = ndi_element_timeseries(session=session, document=docs[0])
        _, times, _ = neuron.readtimeseries("epoch_1", -np.inf, np.inf)
        assert np.asarray(times).ravel() == pytest.approx([0.1, 0.5])

        stored = session.database_search(ndi_query("").isa("neuron_extracellular"))
        assert stored[0].dependency_value("element_id") == docs[0].id

    def test_no_specs_writes_nothing(self, tmp_path):
        session, probe = _session(tmp_path, "empty_batch")
        before = len(session.database_search(ndi_query("").isa("element")))
        ndi_element_timeseries.add_multiple(session, probe, [])
        assert len(session.database_search(ndi_query("").isa("element"))) == before

    def test_the_matlab_spelling_is_the_same_function(self):
        assert ndi_element_timeseries.addMultiple == ndi_element_timeseries.add_multiple


class TestNames:
    def test_every_matlab_name_resolves_and_has_a_readable_alias(self):
        pairs = [
            ("binaryinfo", "binary_info"),
            ("getInfo", "get_info"),
            ("meanwaveform", "mean_waveform"),
            ("neuropixelsmultiplier", "neuropixels_multiplier"),
            ("promptrawbinary", "prompt_raw_binary"),
            ("readspikeglxmeta", "read_spikeglx_meta"),
            ("recalculatemeanwaveform", "recalculate_mean_waveform"),
            ("recalculatemeanwaveforms", "recalculate_mean_waveforms"),
            ("removeold", "remove_old"),
            ("waveformdata", "waveform_data"),
        ]
        for matlab_name, python_name in pairs:
            assert getattr(kilosort, matlab_name) is getattr(kilosort, python_name)
