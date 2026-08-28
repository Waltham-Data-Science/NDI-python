"""Tests for the image-series DAQ stack.

Covers ndi.daq.reader.image (the abstract frame API plus the generic
ingest / read-ingested path), ndi.daq.reader.image.ndr (the NDR bridge)
and ndi.daq.system.image.

The bridge tests drive a stand-in NDR reader rather than the real one:
NDR-python's frame API is what the bridge forwards to, so testing against
the real library would test NDR, not the adapter.
"""

from __future__ import annotations

import numpy as np
import pytest

from ndi.daq.reader.image import emptymetadata, ndi_daq_reader_image
from ndi.daq.reader.image.ndr import ndi_daq_reader_image_ndr
from ndi.daq.system_image import ndi_daq_system_image
from ndi.session.dir import ndi_session_dir
from ndi.time import ndi_time_clocktype

Y, X, C, Z, T = 4, 3, 2, 1, 5


def make_volume():
    """A frame block whose every voxel is distinguishable."""
    return np.arange(Y * X * C * Z * T, dtype=np.uint16).reshape((Y, X, C, Z, T), order="F")


class FakeImageReader(ndi_daq_reader_image):
    """A concrete image reader over an in-memory array."""

    NDI_DAQREADER_CLASS = "ndi.daq.reader.image.fake"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._data = make_volume()

    def numframes(self, epochfiles):
        return T

    def framesize(self, epochfiles):
        return [Y, X, C, Z, T]

    def datatype(self, epochfiles):
        return "uint16"

    def frametimes(self, epochfiles, frameind=None):
        allt = np.arange(T, dtype=float) * 0.1
        if frameind is None:
            return allt
        return allt[np.asarray(list(frameind), dtype=int) - 1]

    def readframes(self, epochfiles, frameind=None, select_c=None, select_z=None):
        if frameind is None:
            frameind = range(1, T + 1)
        out = self._data[:, :, :, :, np.asarray(list(frameind), dtype=int) - 1]
        if select_c:
            out = out[:, :, np.asarray(list(select_c), dtype=int) - 1, :, :]
        if select_z:
            out = out[:, :, :, np.asarray(list(select_z), dtype=int) - 1, :]
        return out

    def epochclock(self, epochfiles):
        return [ndi_time_clocktype("dev_local_time")]

    def t0_t1(self, epochfiles):
        return [(0.0, 0.4)]


# ======================================================================
# the abstract base
# ======================================================================


class BareReader(ndi_daq_reader_image):
    """Overrides nothing: the abstract surface must say so."""


@pytest.mark.parametrize(
    "method,args",
    [
        ("numframes", ([],)),
        ("framesize", ([],)),
        ("datatype", ([],)),
        ("frametimes", ([],)),
        ("readframes", ([],)),
    ],
)
def test_abstract_frame_methods_raise(method, args):
    with pytest.raises(NotImplementedError):
        getattr(BareReader(), method)(*args)


def test_dimensionorder_defaults_to_yxczt():
    assert BareReader().dimensionorder([]) == "YXCZT"


def test_default_channel_is_a_single_image_channel():
    ch = BareReader().getchannelsepoch([])
    assert len(ch) == 1
    assert ch[0]["name"] == "image1"
    assert ch[0]["type"] == "image"


def test_emptymetadata_fields():
    m = emptymetadata()
    assert m["israster"] is False
    assert m["bidirectional"] is False
    for k in ("frame_period", "line_period", "dwell_time", "lines_per_frame", "pixels_per_line"):
        assert np.isnan(m[k]), k


def test_default_metadata_is_the_empty_struct():
    assert BareReader().metadata([]) == emptymetadata()


# ======================================================================
# ingest / read-ingested round trip
# ======================================================================


@pytest.fixture
def ingested(tmp_path):
    d = tmp_path / "sess"
    d.mkdir(parents=True, exist_ok=True)
    S = ndi_session_dir("img", str(d))

    reader = FakeImageReader()
    doc = reader.ingest_epochfiles(["/live/epoch1.tif"], "epoch_img_1")
    S.database_add(doc)
    return S, reader, ["epochid://epoch_img_1"]


def test_ingested_header_round_trips(ingested):
    S, reader, ef = ingested
    assert reader.numframes_ingested(ef, S) == T
    assert reader.framesize_ingested(ef, S) == [Y, X, C, Z, T]
    assert reader.datatype_ingested(ef, S) == "uint16"
    assert reader.dimensionorder_ingested(ef, S) == "YXCZT"


def test_ingested_frames_match_the_live_frames(ingested):
    S, reader, ef = ingested
    live = reader.readframes(["/live/epoch1.tif"])
    back = reader.readframes_ingested(ef, session=S)
    assert back.shape == live.shape
    np.testing.assert_array_equal(back, live)


def test_ingested_frame_selection_is_one_based(ingested):
    S, reader, ef = ingested
    live = reader.readframes(["/live/epoch1.tif"], [2, 4])
    back = reader.readframes_ingested(ef, [2, 4], session=S)
    np.testing.assert_array_equal(back, live)


def test_ingested_channel_selection(ingested):
    S, reader, ef = ingested
    back = reader.readframes_ingested(ef, session=S, select_c=[2])
    assert back.shape == (Y, X, 1, Z, T)
    np.testing.assert_array_equal(back[:, :, 0, :, :], make_volume()[:, :, 1, :, :])


def test_ingested_frametimes(ingested):
    S, reader, ef = ingested
    np.testing.assert_allclose(reader.frametimes_ingested(ef, session=S), np.arange(T) * 0.1)
    np.testing.assert_allclose(reader.frametimes_ingested(ef, [1, 3], session=S), [0.0, 0.2])


def assert_metadata_equal(a, b):
    assert set(a) == set(b)
    for k in a:
        if isinstance(b[k], float) and np.isnan(b[k]):
            assert np.isnan(a[k]), f"{k}: expected NaN, got {a[k]!r}"
        else:
            assert a[k] == b[k], k


def test_ingested_metadata_round_trips(ingested):
    """The FakeImageReader supplies no metadata, so the round trip must
    return the all-unknown struct -- with NaN, not None."""
    S, reader, ef = ingested
    assert_metadata_equal(reader.metadata_ingested(ef, S), emptymetadata())


def test_ingested_document_holds_no_bare_nan_token(ingested):
    """json.dumps writes a bare NaN token for float NaN, which is not valid
    JSON and which MATLAB's jsondecode cannot read. Every NaN in the stored
    document must be null instead."""
    import json

    S, reader, ef = ingested
    d = reader.getingesteddocument(ef, S)
    assert "NaN" not in json.dumps(d.document_properties)


def test_frames_bin_is_written_column_major(ingested):
    """MATLAB's fwrite consumes the array column-major, so a MATLAB-written
    and a Python-written frames.bin must be byte-interchangeable."""
    S, reader, ef = ingested
    d = reader.getingesteddocument(ef, S)
    fh = S.database_openbinarydoc(d, "frames.bin")
    try:
        raw = fh.read()
    finally:
        S.database_closebinarydoc(fh)
    assert raw == make_volume().tobytes(order="F")


# ======================================================================
# the NDR bridge
# ======================================================================


class FakeNdrReader:
    """Stands in for an NDR-python reader with the image frame API."""

    def __init__(self):
        self.calls = []

    def _log(self, name, *a, **k):
        self.calls.append((name, a, k))

    def numframes(self, epochfiles, epoch_select):
        self._log("numframes", epochfiles, epoch_select)
        return T

    def framesize(self, epochfiles, epoch_select):
        return [Y, X, C, Z, T]

    def dimensionorder(self, epochfiles, epoch_select):
        return "YXCZT"

    def datatype(self, epochfiles, epoch_select):
        return "uint16"

    def frametimes(self, epochfiles, epoch_select, frameind=None):
        self._log("frametimes", epochfiles, epoch_select, frameind)
        allt = np.arange(T, dtype=float) * 0.1
        return allt if frameind is None else allt[np.asarray(frameind) - 1]

    def readframes(self, epochfiles, epoch_select, frameind=None, select_c=None, select_z=None):
        self._log(
            "readframes",
            epochfiles,
            epoch_select,
            frameind,
            select_c=select_c,
            select_z=select_z,
        )
        return make_volume()

    def getchannelsepoch(self, epochfiles, epoch_select):
        return [{"name": "image1", "type": "image", "time_channel": None}]

    def metadata(self, epochfiles, epoch_select):
        m = emptymetadata()
        m["israster"] = True
        m["frame_period"] = 0.1
        return m

    def epochclock(self, epochfiles, epoch_select):
        class _C:
            type = "dev_local_time"

        return [_C()]

    def t0_t1(self, epochfiles, epoch_select):
        return [[0.0, 0.4]]


@pytest.fixture
def bridge(monkeypatch):
    fake = FakeNdrReader()
    import ndr

    monkeypatch.setattr(ndr, "reader", lambda s: fake)
    return ndi_daq_reader_image_ndr("prairieview"), fake


def test_bridge_forwards_the_frame_api(bridge):
    r, fake = bridge
    ef = ["/x/reference.txt"]
    assert r.numframes(ef) == T
    assert r.framesize(ef) == [Y, X, C, Z, T]
    assert r.dimensionorder(ef) == "YXCZT"
    assert r.datatype(ef) == "uint16"


def test_bridge_pins_the_ndr_epoch_index_to_one(bridge):
    """NDI hands the reader exactly one epoch's files per call, so the NDR
    per-file epoch index is always 1."""
    r, fake = bridge
    r.numframes(["/x/reference.txt"])
    name, args, _ = fake.calls[-1]
    assert args[1] == 1


def test_bridge_converts_ndr_clocks_to_ndi_clocks(bridge):
    r, _ = bridge
    ec = r.epochclock(["/x"])
    assert len(ec) == 1
    assert isinstance(ec[0], ndi_time_clocktype)
    assert ec[0].value == "dev_local_time"


def test_bridge_forwards_selections_rather_than_post_filtering(bridge):
    """Passing the selection down lets a reader skip unread channels."""
    r, fake = bridge
    r.readframes(["/x"], [1, 2], select_c=[2], select_z=[1])
    name, args, kwargs = fake.calls[-1]
    assert args[2] == [1, 2]
    assert kwargs["select_c"] == [2]
    assert kwargs["select_z"] == [1]


def test_bridge_t0_t1(bridge):
    r, _ = bridge
    assert r.t0_t1(["/x"]) == [(0.0, 0.4)]


def test_bridge_metadata_comes_from_ndr(bridge):
    r, _ = bridge
    m = r.metadata(["/x"])
    assert m["israster"] is True
    assert m["frame_period"] == 0.1


def test_bridge_names_a_missing_frame_api(monkeypatch):
    """NDR-python grew the multichannel API before the frame API; a missing
    frame method is a version mismatch and must say so."""

    class NoFrameApi:
        pass

    import ndr

    monkeypatch.setattr(ndr, "reader", lambda s: NoFrameApi())
    r = ndi_daq_reader_image_ndr("intan")
    with pytest.raises(NotImplementedError, match="does not implement 'framesize'"):
        r.framesize(["/x"])


def test_bridge_construction_does_not_require_ndr_to_know_the_reader():
    """Deliberate divergence from MATLAB, which validates against
    ndr.known_readers() in the constructor. Deferring means a session
    naming an image DAQ system still loads on an installation whose NDR
    does not implement that format yet."""
    r = ndi_daq_reader_image_ndr("a_format_ndr_has_never_heard_of")
    assert r.ndr_reader_string == "a_format_ndr_has_never_heard_of"


def test_bridge_default_reader_string():
    assert ndi_daq_reader_image_ndr().ndr_reader_string == "tiffstack"


def test_bridge_newdocument_records_the_reader_string():
    r = ndi_daq_reader_image_ndr("prairieview")
    doc = r.newdocument()
    props = doc.document_properties
    assert props["daqreader"]["ndi_daqreader_class"] == "ndi.daq.reader.image.ndr"
    assert props["daqreader_ndr"]["ndr_reader_string"] == "prairieview"


def test_bridge_rebuilds_from_its_own_document():
    r = ndi_daq_reader_image_ndr("prairieview")
    r2 = ndi_daq_reader_image_ndr(document=r.newdocument())
    assert r2.ndr_reader_string == "prairieview"


# ======================================================================
# the DAQ system
# ======================================================================


def test_system_rejects_a_non_image_reader():
    from ndi.daq.reader.mfdaq.intan import ndi_daq_reader_mfdaq_intan

    with pytest.raises(TypeError, match="must be a type of ndi.daq.reader.image"):
        ndi_daq_system_image("sys1", None, ndi_daq_reader_mfdaq_intan())


def test_system_accepts_an_image_reader():
    sys = ndi_daq_system_image("sys1", None, FakeImageReader())
    assert sys.NDI_DAQSYSTEM_CLASS == "ndi.daq.system.image"


# ======================================================================
# vhprairieview end to end
# ======================================================================


@pytest.fixture
def vhlab_session(tmp_path):
    from ndi.setup.lab import lab

    d = tmp_path / "vhlab"
    d.mkdir(parents=True, exist_ok=True)
    S = ndi_session_dir("exp1", str(d))
    lab(S, "vhlab")
    return S


def test_vhlab_has_nine_daq_systems(vhlab_session):
    """The count MATLAB reports. Python surfaced eight because
    vhprairieview named classes that did not exist here, and
    daqsystem_load dropped it silently."""
    loaded = vhlab_session.daqsystem_load(name="(.*)")
    assert len(loaded) == 9


def test_vhlab_loads_without_warning(vhlab_session, recwarn):
    vhlab_session.daqsystem_load(name="(.*)")
    skips = [w for w in recwarn if "Skipping daqsystem document" in str(w.message)]
    assert not skips, [str(w.message) for w in skips]


def test_vhprairieview_builds_the_whole_image_chain(vhlab_session):
    loaded = vhlab_session.daqsystem_load(name="(.*)")
    sys = next(s for s in loaded if s.name == "vhprairieview")

    assert isinstance(sys, ndi_daq_system_image)
    assert sys.NDI_DAQSYSTEM_CLASS == "ndi.daq.system.image"

    assert isinstance(sys.daqreader, ndi_daq_reader_image_ndr)
    assert sys.daqreader.ndr_reader_string == "prairieview"

    from ndi.setup.file.navigator.vhprairie2p import ndi_setup_file_navigator_vhPrairie2p

    assert isinstance(sys.filenavigator, ndi_setup_file_navigator_vhPrairie2p)
