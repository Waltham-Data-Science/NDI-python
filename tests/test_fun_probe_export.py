"""Tests for ndi.fun.probe.export.

MATLAB counterpart: +ndi/+fun/+probe/+export/

What these pin down is the shape of the bytes on disk, because nothing
downstream reports it. A binary written with the channels the wrong way
round, or with an encode multiplier used as a decode one, loads into a
sorter perfectly happily and yields a sort that is quietly wrong. The
sample-order and multiplier-direction tests are therefore the important
ones here.
"""

from __future__ import annotations

import numpy as np
import pytest

from ndi.fun.probe.export import (
    INTAN_MULTIPLIER,
    _colon,
    all_binary,
    autoMultiplier,
    binary,
    oneProbe,
)


class FakeProbe:
    """A probe with fabricated epochs, answering the export's API.

    Samples are ``value = channel * 1000 + sample_index``, so a byte order
    mistake is visible in the numbers rather than only in a checksum.
    """

    def __init__(
        self, *, name="ctx", reference=1, epochs=(2.0,), rate=1000.0, channels=4, dtype=np.float64
    ):
        self._name = name
        self._reference = reference
        self._rate = rate
        self._channels = channels
        self._dtype = dtype
        self._epochs = [
            {"epoch_id": f"e{i + 1}", "epoch_number": i + 1, "t0_t1": [[0.0, duration]]}
            for i, duration in enumerate(epochs)
        ]

    def epochtable(self):
        return self._epochs, "hash"

    def elementstring(self):
        return f"{self._name} | {self._reference}"

    def id(self):
        return f"{self._name}_id"

    def samplerate(self, epoch_id):  # noqa: ARG002
        return self._rate

    def times2samples(self, epoch_id, times):  # noqa: ARG002
        return np.round(np.asarray(times) * self._rate).astype(int)

    def readtimeseries(self, epoch=None, t0=0.0, t1=0.0, timeref=None):  # noqa: ARG002
        first = int(round(t0 * self._rate))
        last = int(round(t1 * self._rate))
        n = max(last - first + 1, 0)
        samples = np.arange(first, first + n)
        data = np.stack(
            [channel * 1000 + samples for channel in range(self._channels)], axis=1
        ).astype(self._dtype)
        return data, samples / self._rate, None

    def getchanneldevinfo(self, epoch):  # noqa: ARG002
        return (None, None, "ai", list(range(1, self._channels + 1)))


class FakeSession:
    def __init__(self, path, probes=(), reference="ses"):
        self.path = str(path)
        self.reference = reference
        self._probes = list(probes)

    def getprobes(self, **kwargs):  # noqa: ARG002
        return self._probes

    def database_search(self, query):  # noqa: ARG002
        return []


def read_int16(path):
    return np.fromfile(path, dtype="<i2")


class TestColon:
    def test_it_matches_matlabs_colon(self):
        assert _colon(0.0, 100.0, 250.0) == [0.0, 100.0, 200.0]

    def test_a_zero_length_epoch_still_yields_one_chunk(self):
        """MATLAB's ``t0:100:t0`` is ``t0``; numpy.arange is empty. Taking
        arange's answer would write nothing and report success."""
        assert _colon(5.0, 100.0, 5.0) == [5.0]

    def test_a_backwards_range_is_empty(self):
        assert _colon(10.0, 100.0, 5.0) == []


class TestBinary:
    def test_samples_are_written_channel_interleaved(self, tmp_path):
        """Kilosort reads ch1s1, ch2s1, ... ch1s2, ...; writing the array
        untransposed would put a whole channel first and still 'work'."""
        probe = FakeProbe(epochs=(0.002,), rate=1000.0, channels=3)
        out = tmp_path / "kiasort.bin"
        binary(probe, out, verbose=0)

        values = read_int16(out)
        # 3 samples (0, 1, 2) x 3 channels, channel index major within sample
        assert values.tolist() == [0, 1000, 2000, 1, 1001, 2001, 2, 1002, 2002]

    def test_the_multiplier_scales_in_the_encode_direction(self, tmp_path):
        probe = FakeProbe(epochs=(0.0,), rate=1000.0, channels=2)
        out = tmp_path / "kiasort.bin"
        binary(probe, out, multiplier=10.0, verbose=0)
        assert read_int16(out).tolist() == [0, 10000]

    def test_the_metadata_sidecar_is_the_matlab_one(self, tmp_path):
        from vlt.file import loadStructArray

        probe = FakeProbe(epochs=(0.002, 0.001), rate=1000.0, channels=4)
        out = tmp_path / "kiasort.bin"
        binary(probe, out, multiplier=2.0, verbose=0)

        meta = loadStructArray(str(tmp_path / "kiasort.bin.metadata"))
        assert len(meta) == 1
        assert int(float(meta[0]["num_channels"])) == 4
        assert float(meta[0]["multiplier"]) == 2.0
        assert meta[0]["probe_name"] == "ctx | 1"
        assert "3" in meta[0]["epoch_sample_counts"]

    def test_no_binary_writes_only_the_sidecar(self, tmp_path):
        probe = FakeProbe(epochs=(2.0,), channels=4)
        out = tmp_path / "kiasort.bin"
        binary(probe, out, noBinary=True, verbose=0)

        assert not out.exists()
        assert (tmp_path / "kiasort.bin.metadata").is_file()

    def test_progress_runs_from_above_zero_to_one_across_all_epochs(self, tmp_path):
        """Per-epoch progress restarting at 0 would show a bar that jumps
        backwards on a multi-epoch probe."""
        probe = FakeProbe(epochs=(250.0, 150.0), rate=100.0, channels=2)
        seen: list[float] = []
        binary(
            probe,
            tmp_path / "kiasort.bin",
            verbose=0,
            progressfcn=lambda fraction, message: seen.append(fraction),
        )

        assert seen == sorted(seen)
        assert seen[0] > 0
        assert seen[-1] == pytest.approx(1.0)
        assert len(seen) == 5  # 3 chunks in the first epoch, 2 in the second

    def test_no_progress_callback_is_fine(self, tmp_path):
        binary(FakeProbe(epochs=(0.001,)), tmp_path / "kiasort.bin", verbose=0)
        assert (tmp_path / "kiasort.bin").is_file()


class TestAutoMultiplier:
    def test_integer_data_passes_through_unscaled(self):
        assert autoMultiplier(FakeProbe(dtype=np.int16)) == 1.0

    def test_floating_point_data_gets_the_intan_default(self):
        assert autoMultiplier(FakeProbe(dtype=np.float64)) == pytest.approx(INTAN_MULTIPLIER)

    def test_an_unsamplable_probe_keeps_the_default(self):
        class Broken(FakeProbe):
            def readtimeseries(self, **kwargs):
                raise RuntimeError("no data")

        assert autoMultiplier(Broken()) == pytest.approx(INTAN_MULTIPLIER)

    def test_a_probe_with_no_epochs_keeps_the_default(self):
        probe = FakeProbe()
        probe._epochs = []
        assert autoMultiplier(probe) == pytest.approx(INTAN_MULTIPLIER)


class TestOneProbe:
    def test_it_writes_the_binary_into_the_sorters_probe_folder(self, tmp_path):
        probe = FakeProbe(epochs=(0.002,), rate=1000.0, channels=2)
        session = FakeSession(tmp_path, [probe])

        status = oneProbe(session, probe, verbose=0)

        expected = tmp_path / "kiasort" / "ctx_-_1" / "kiasort.bin"
        assert expected.is_file()
        assert status["binaryFile"] == str(expected)

    def test_a_probe_with_no_geometry_gets_a_placeholder_map(self, tmp_path):
        """hadGeometry False is the app's cue that the map is a guess."""
        from scipy.io import loadmat

        probe = FakeProbe(epochs=(0.002,), channels=3)
        session = FakeSession(tmp_path, [probe])

        status = oneProbe(session, probe, verbose=0)

        assert status["hadGeometry"] is False
        assert status["channelMapFile"].endswith("channel_map.mat")
        mat = loadmat(status["channelMapFile"])
        assert mat["xcoords"].ravel().tolist() == [0.0, 0.0, 0.0]
        assert mat["ycoords"].ravel().tolist() == [0.0, 20.0, 40.0]

    def test_the_multiplier_is_auto_detected_and_reported(self, tmp_path):
        probe = FakeProbe(epochs=(0.001,), dtype=np.int16)
        status = oneProbe(FakeSession(tmp_path, [probe]), probe, verbose=0)
        assert status["multiplier"] == 1.0

    def test_an_explicit_multiplier_wins(self, tmp_path):
        probe = FakeProbe(epochs=(0.001,))
        status = oneProbe(FakeSession(tmp_path, [probe]), probe, multiplier=7.0, verbose=0)
        assert status["multiplier"] == 7.0

    def test_channel_map_can_be_declined(self, tmp_path):
        probe = FakeProbe(epochs=(0.001,))
        status = oneProbe(FakeSession(tmp_path, [probe]), probe, channelMap=False, verbose=0)
        assert status["channelMapFile"] == ""

    def test_each_sorter_gets_its_own_folder(self, tmp_path):
        probe = FakeProbe(epochs=(0.001,))
        session = FakeSession(tmp_path, [probe])

        oneProbe(session, probe, binary_dir="kiasort", binaryFileName="kiasort.bin", verbose=0)
        oneProbe(session, probe, binary_dir="kilosort", binaryFileName="kilosort.bin", verbose=0)

        assert (tmp_path / "kiasort" / "ctx_-_1" / "kiasort.bin").is_file()
        assert (tmp_path / "kilosort" / "ctx_-_1" / "kilosort.bin").is_file()

    def test_a_legacy_probe_folder_is_reused_rather_than_duplicated(self, tmp_path):
        """Data written by an older NDI lives under 'ctx_|_1'. Exporting
        beside it would leave the user with two folders and no clue which
        their sorter read."""
        legacy = tmp_path / "kiasort" / "ctx_|_1"
        legacy.mkdir(parents=True)

        probe = FakeProbe(epochs=(0.001,))
        oneProbe(FakeSession(tmp_path, [probe]), probe, verbose=0)

        assert (legacy / "kiasort.bin").is_file()
        assert not (tmp_path / "kiasort" / "ctx_-_1").exists()


class TestAllBinary:
    def test_every_n_trode_probe_gets_a_folder_and_a_binary(self, tmp_path):
        probes = [
            FakeProbe(name="ctx", reference=1, epochs=(0.001,)),
            FakeProbe(name="ctx", reference=2, epochs=(0.001,)),
        ]
        all_binary(FakeSession(tmp_path, probes), verbose=0)

        assert (tmp_path / "kilosort" / "ctx_-_1" / "kilosort.bin").is_file()
        assert (tmp_path / "kilosort" / "ctx_-_2" / "kilosort.bin").is_file()

    def test_the_older_export_all_binary_name_still_works(self, tmp_path):
        from ndi.fun.probe import export_all_binary

        probe = FakeProbe(epochs=(0.001,))
        export_all_binary(FakeSession(tmp_path, [probe]), kilosort_dir="ks", verbose=False)
        assert (tmp_path / "ks" / "ctx_-_1" / "kilosort.bin").is_file()
