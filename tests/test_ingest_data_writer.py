"""Ingestion writes the epoch's data, as NDI-matlab does.

MATLAB counterpart: ndi.daq.reader.mfdaq/ingest_epochfiles (with its
ProgressFcn, VH-Lab/NDI-matlab#1089), ndi.daq.metadatareader/ingest_epochfiles,
ndi.file.type.mfdaq_epoch_channel/writeToFile and
ndi.daq.reader.mfdaq.intan/underlying_datatype.

Ingestion used to create the epoch documents without any data, so nothing
could be read from an ingested epoch. These tests ingest a copy of the example
Intan session and read every channel type back from the ingested files,
comparing it with what the reader returns from the raw file.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from ndi.daq.fun import ingestEpochDocuments
from ndi.daq.mfdaq import ndi_daq_reader_mfdaq
from ndi.file.type.mfdaq_epoch_channel import ChannelInfo, ndi_file_type_mfdaq__epoch__channel
from ndi.gui.component.ProgressBarWindow import ndi_gui_component_ProgressBarWindow as PBW
from tests.test_ingest_progress_parallel import _have_intan, _intan_session, _prefs

ndicompress = pytest.importorskip("ndicompress")

#: channel type, channel numbers, largest difference allowed (time channels
#: are stored by a fit, so they round-trip to ~1e-12 s, not exactly)
_CHANNELS = [
    ("analog_in", list(range(1, 33)), 0.0),
    ("auxiliary_in", [1, 2, 3], 0.0),
    ("digital_in", [1], 0.0),
    ("time", [1], 1e-9),
]


@pytest.fixture(autouse=True)
def _silent():
    previous = PBW.silentModeDefault()
    PBW.silentModeDefault(True)
    yield
    PBW.silentModeDefault(previous)


def _daq(session):
    d = session.daqsystem_load(name="intan1")
    return d[0] if isinstance(d, list) else d


def _epochs(session):
    """(raw epoch files, 'epochid://' files) for each epoch."""
    return [
        (e["underlying_epochs"]["underlying"], ["epochid://" + e["epoch_id"]])
        for e in _daq(session).epochtable()
    ]


def _ingested(session, monkeypatch):
    _prefs(monkeypatch, OpenPoolIfNone=False)
    ok, msg = session.ingest()
    assert ok, msg
    return session


def _assert_reads_match(session, windows=None):
    reader = _daq(session).daqreader
    for files, ingested in _epochs(session):
        for channeltype, numbers, tolerance in _CHANNELS:
            if windows is None:
                last = int(
                    reader.epochtimes2samples(
                        channeltype, numbers, files, reader.t0_t1(files)[0][1]
                    )
                )
                spans = [(0, last)]
            else:
                spans = windows
            for s0, s1 in spans:
                raw = reader.readchannels_epochsamples(channeltype, numbers, files, s0 + 1, s1 + 1)
                stored = reader.readchannels_epochsamples_ingested(
                    channeltype, numbers, ingested, s0, s1, session
                )
                assert stored.shape == raw.shape, (channeltype, s0, s1)
                assert np.max(np.abs(stored - raw)) <= tolerance, (channeltype, s0, s1)


@pytest.mark.skipif(not _have_intan(), reason="Intan example data (.rhd) not found")
class TestIntanIngestion:
    def test_every_channel_type_reads_back(self, tmp_path, monkeypatch):
        session = _ingested(_intan_session(tmp_path / "exp1"), monkeypatch)
        _assert_reads_match(session)

    def test_document_files_and_channel_list(self, tmp_path, monkeypatch):
        session = _ingested(_intan_session(tmp_path / "exp1"), monkeypatch)
        reader = _daq(session).daqreader
        files, ingested = _epochs(session)[0]
        doc = reader.getingesteddocument(ingested, session)
        names = sorted(f["name"] for f in doc.document_properties["files"]["file_info"])
        assert names == [
            "ai_group1_seg.nbf_1",
            "ax_group1_seg.nbf_1",
            "channel_list.bin",
            "di_group1_seg.nbf_1",
            "ti_group1_seg.nbf_1",
        ]
        params = doc.document_properties["daqreader_mfdaq_epochdata_ingested"]["parameters"]
        assert params == {"sample_analog_segment": 1_000_000, "sample_digital_segment": 10_000_000}

        # channel_list.bin is MATLAB's tab-delimited saveStructArray format
        fobj = session.database_openbinarydoc(doc, "channel_list.bin")
        text = fobj.read()
        fobj.close()
        text = text.decode() if isinstance(text, bytes) else text
        assert text.splitlines()[0].split("\t") == [
            "name",
            "type",
            "time_channel",
            "sample_rate",
            "offset",
            "scale",
            "number",
            "group",
            "dataclass",
        ]
        channels = reader.getchannelsepoch_ingested(ingested, session)
        assert len(channels) == len(reader.getchannelsepoch(files))
        ai1 = next(c for c in channels if c.type == "analog_in" and c.number == 1)
        assert (ai1.sample_rate, ai1.offset, ai1.scale) == (20000.0, 32768.0, 0.195)
        assert (ai1.group, ai1.dataclass) == (1, "ephys")
        aux1 = next(c for c in channels if c.type == "auxiliary_in" and c.number == 1)
        assert (aux1.sample_rate, aux1.offset, aux1.scale) == (5000.0, 0.0, 3.74e-05)

    def test_analog_is_stored_as_uint16(self, tmp_path, monkeypatch):
        session = _ingested(_intan_session(tmp_path / "exp1"), monkeypatch)
        reader = _daq(session).daqreader
        _, ingested = _epochs(session)[0]
        doc = reader.getingesteddocument(ingested, session)
        import os
        import tarfile
        import tempfile

        from ndicompress.header import read_ndi_header

        from ndi.database_fun import copydocfile2temp

        for name in ("ai_group1_seg.nbf_1", "ax_group1_seg.nbf_1"):
            tname, _ = copydocfile2temp(doc, session, name, ".nbf.tgz")
            with tempfile.TemporaryDirectory() as d, tarfile.open(tname, "r:gz") as tar:
                member = next(m for m in tar.getmembers() if m.name.endswith(".nbh"))
                tar.extract(member, path=d, filter="data")
                header = read_ndi_header(os.path.join(d, member.name))
            os.remove(tname)
            assert header["original_isunsigned"] == 1, name
            assert header["original_bits_per_sample"] == 16, name

    def test_epochs_span_several_segments(self, tmp_path, monkeypatch):
        # small segments, so each epoch is split across files and reads cross
        # segment boundaries
        monkeypatch.setattr(ndi_daq_reader_mfdaq, "SAMPLE_ANALOG_SEGMENT", 7001)
        monkeypatch.setattr(ndi_daq_reader_mfdaq, "SAMPLE_DIGITAL_SEGMENT", 13003)
        session = _ingested(_intan_session(tmp_path / "exp1"), monkeypatch)
        reader = _daq(session).daqreader
        _, ingested = _epochs(session)[0]
        doc = reader.getingesteddocument(ingested, session)
        names = {f["name"] for f in doc.document_properties["files"]["file_info"]}
        assert "ai_group1_seg.nbf_9" in names  # 60000 samples / 7001
        assert "di_group1_seg.nbf_5" in names  # 60000 / 13003
        _assert_reads_match(session)
        _assert_reads_match(session, windows=[(6990, 7015), (0, 5), (13000, 14010), (14990, 14999)])

    def test_reader_reports_within_epoch_progress(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ndi_daq_reader_mfdaq, "SAMPLE_ANALOG_SEGMENT", 20000)
        session = _intan_session(tmp_path / "exp1")
        reader = _daq(session).daqreader
        files, _ = _epochs(session)[0]
        fractions = []
        reader.ingest_epochfiles(files, "epoch_x", ProgressFcn=fractions.append)
        assert fractions[0] == 0
        assert fractions[-1] == 1
        assert all(b >= a for a, b in zip(fractions, fractions[1:]))
        assert any(0 < f < 1 for f in fractions)

    def test_ingest_epoch_documents_reports_fractions(self, tmp_path, monkeypatch):
        _prefs(monkeypatch, OpenPoolIfNone=False)
        monkeypatch.setattr(ndi_daq_reader_mfdaq, "SAMPLE_ANALOG_SEGMENT", 20000)
        session = _intan_session(tmp_path / "exp1")
        dev = _daq(session)
        epochs = _epochs(session)
        calls = []
        docs, used_parallel = ingestEpochDocuments(
            dev.daqreader,
            [],
            [files for files, _ in epochs],
            [f"epoch_{k}" for k in range(len(epochs))],
            ProgressFcn=lambda done, total: calls.append((done, total)),
        )
        assert not used_parallel
        done = [c[0] for c in calls]
        assert all(b > a for a, b in zip(done, done[1:])), "reported only when it changes"
        assert done[-1] == len(epochs)
        assert any(d != int(d) for d in done), "fractional progress within an epoch"
        for whole in range(1, len(epochs) + 1):
            assert done.count(whole) == 1
        assert len(docs) == len(epochs)


class TestIntanUnderlyingDatatype:
    def test_matches_matlab(self):
        from ndi.daq.reader.mfdaq.intan import ndi_daq_reader_mfdaq_intan

        r = ndi_daq_reader_mfdaq_intan()
        dtype, poly, size = r.underlying_datatype([], "analog_in", [1, 2])
        assert (dtype, size) == ("uint16", 16)
        np.testing.assert_array_equal(poly, [[32768, 0.195], [32768, 0.195]])
        dtype, poly, size = r.underlying_datatype([], "auxiliary_in", 1)
        assert (dtype, size) == ("uint16", 16)
        np.testing.assert_array_equal(poly, [[0, 3.74e-05]])
        assert r.underlying_datatype([], "time", 1)[0] == "float64"
        assert r.underlying_datatype([], "digital_in", 1)[2] == 8


class TestChannelListFile:
    def test_round_trip_in_matlab_format(self, tmp_path):
        mec = ndi_file_type_mfdaq__epoch__channel().create_properties(
            [
                {"name": "ai1", "type": "analog_in", "time_channel": 1, "sample_rate": 20000.0},
                {"name": "t1", "type": "time", "time_channel": None, "sample_rate": 20000.0},
                {"name": "mk1", "type": "marker", "time_channel": 1, "sample_rate": np.nan},
            ]
        )
        fname = str(tmp_path / "channel_list.bin")
        ok, msg = mec.writeToFile(fname)
        assert ok, msg
        with open(fname) as f:
            assert f.readline().startswith("name\ttype\ttime_channel")
        back = ndi_file_type_mfdaq__epoch__channel().readFromFile(fname).channel_information
        assert [(c.name, c.type, c.number, c.group, c.dataclass) for c in back] == [
            (c.name, c.type, c.number, c.group, c.dataclass) for c in mec.channel_information
        ]
        t1 = next(c for c in back if c.name == "t1")
        assert t1.time_channel is None
        mk1 = next(c for c in back if c.name == "mk1")
        assert np.isnan(mk1.sample_rate)

    def test_reads_older_json_files(self, tmp_path):
        fname = tmp_path / "channel_list.bin"
        ch = ChannelInfo(name="ai1", type="analog_in", sample_rate=1000.0, number=1, group=1)
        fname.write_text(json.dumps({"channel_information": [ch.to_dict()]}))
        back = ndi_file_type_mfdaq__epoch__channel().readFromFile(str(fname))
        assert back.channel_information == [ch]


class TestMetadataIngestion:
    def test_parameters_are_stored_and_read_back(self, tmp_path):
        from ndi.daq.metadatareader import ndi_daq_metadatareader
        from ndi.session.dir import ndi_session_dir

        (tmp_path / "exp").mkdir()
        tsv = tmp_path / "exp" / "stims.tsv"
        tsv.write_text("stimid\tangle\n1\t0\n2\t90\n")
        session = ndi_session_dir("exp", tmp_path / "exp")
        reader = ndi_daq_metadatareader(r"stims\.tsv", session=session)
        expected = reader.readmetadata([str(tsv)])
        assert len(expected) == 2

        doc = reader.ingest_epochfiles([str(tsv)], "epoch_1")
        names = [f["name"] for f in doc.document_properties["files"]["file_info"]]
        assert names == ["data.bin"]
        session.database_add(reader.newdocument())
        session.database_add(doc)
        assert reader.readmetadata_ingested(["epochid://epoch_1"], session) == expected
