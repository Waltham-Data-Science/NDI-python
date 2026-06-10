"""PR8 parity: session/dataset isIngested, convertLinkedSessionToIngested, stimulator pairOnOff.

Covers the remaining §3.4-8/9/10 items beyond the C8b neuron registry:
- session.isIngested (renamed from is_fully_ingested, MATLAB 3cde88c8) + alias
- dataset.isIngested (aggregates sessions)
- dataset.convertLinkedSessionToIngested (copies a linked session's docs into the
  dataset and marks it ingested)
- stimulator.pairOnOff (NaN-fills orphaned on/off events, MATLAB f1e2ff8c / issue #248)
"""

from __future__ import annotations

import numpy as np
import pytest

from ndi.dataset import ndi_dataset
from ndi.document import ndi_document
from ndi.probe.timeseries_stimulator import ndi_probe_timeseries_stimulator as Stim
from ndi.session.dir import ndi_session_dir


def _session(base, name, ref):
    """Create a session in a freshly-made directory (ndi_session_dir needs it to exist)."""
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    return ndi_session_dir(ref, d)


def _dataset(base, name, ref):
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    return ndi_dataset(d, ref)


# ---------------------------------------------------------------------------
# stimulator.pairOnOff
# ---------------------------------------------------------------------------
class TestPairOnOff:
    def test_balanced_pairs(self):
        times = np.array([1.0, 2.0, 3.0, 4.0])
        signs = np.array([1, -1, 1, -1])
        on, off = Stim.pairOnOff(times, signs)
        assert np.array_equal(on, [1.0, 3.0])
        assert np.array_equal(off, [2.0, 4.0])
        assert len(on) == len(off)

    def test_orphan_on_gets_nan_off(self):
        # window clipped after the last 'on' (no closing 'off')
        times = np.array([1.0, 2.0, 3.0])
        signs = np.array([1, -1, 1])
        on, off = Stim.pairOnOff(times, signs)
        assert np.array_equal(on, [1.0, 3.0])
        assert off[0] == 2.0 and np.isnan(off[1])
        assert len(on) == len(off)

    def test_orphan_off_gets_nan_on(self):
        # window clipped before the first 'on' (a leading 'off')
        times = np.array([1.0, 2.0, 3.0])
        signs = np.array([-1, 1, -1])
        on, off = Stim.pairOnOff(times, signs)
        assert np.isnan(on[0]) and off[0] == 1.0
        assert on[1] == 2.0 and off[1] == 3.0
        assert len(on) == len(off)

    def test_unsorted_input_is_sorted(self):
        times = np.array([4.0, 1.0, 2.0, 3.0])
        signs = np.array([-1, 1, -1, 1])
        on, off = Stim.pairOnOff(times, signs)
        assert np.array_equal(on, [1.0, 3.0])
        assert np.array_equal(off, [2.0, 4.0])

    def test_empty(self):
        on, off = Stim.pairOnOff(np.array([]), np.array([]))
        assert on.size == 0 and off.size == 0


# ---------------------------------------------------------------------------
# session.isIngested + back-compat alias
# ---------------------------------------------------------------------------
class TestSessionIsIngested:
    def test_fresh_session_is_ingested(self, tmp_path):
        s = _session(tmp_path, "s", "ref_s")
        # No DAQ systems with pending files -> fully ingested.
        assert s.isIngested() is True

    def test_back_compat_alias(self, tmp_path):
        s = _session(tmp_path, "s", "ref_s")
        assert s.is_fully_ingested() == s.isIngested()


# ---------------------------------------------------------------------------
# dataset.isIngested
# ---------------------------------------------------------------------------
class TestDatasetIsIngested:
    def test_empty_dataset_is_ingested(self, tmp_path):
        ds = _dataset(tmp_path, "ds", "ds_ref")
        assert ds.isIngested() is True

    def test_dataset_with_ingested_session(self, tmp_path):
        s = _session(tmp_path, "s", "exp")
        ds = _dataset(tmp_path, "ds", "ds_ref")
        ds.add_ingested_session(s)
        assert ds.isIngested() is True


# ---------------------------------------------------------------------------
# dataset.convertLinkedSessionToIngested
# ---------------------------------------------------------------------------
def _linked_dataset(tmp_path):
    """A dataset with one *linked* (not ingested) session carrying a doc+file."""
    s = _session(tmp_path, "linked", "linked_ref")
    # give the session a document with a binary file to copy
    fp = (tmp_path / "linked") / "d1"
    fp.write_text("d1")
    doc = ndi_document("demoNDI")
    props = doc.document_properties
    props["base"]["name"] = "d1"
    props["demoNDI"]["value"] = 1
    props["base"]["session_id"] = s.id()
    doc = ndi_document(props).add_file("filename1.ext", str(fp))
    s.database_add(doc)

    ds = _dataset(tmp_path, "ds", "ds_ref")
    ds.add_linked_session(s)
    return ds, s


class TestConvertLinkedSessionToIngested:
    def test_converts_linked_to_ingested(self, tmp_path):
        ds, s = _linked_dataset(tmp_path)
        assert ds._find_session_in_info(s.id())["is_linked"] in (True, 1)

        ds.convertLinkedSessionToIngested(s.id(), are_you_sure=True)

        info = ds._find_session_in_info(s.id())
        is_linked = info["is_linked"]
        if isinstance(is_linked, (int, float)):
            is_linked = bool(is_linked)
        assert is_linked is False
        # still listed in the dataset
        _refs, ids, *_ = ds.session_list()
        assert s.id() in ids

    def test_requires_confirmation(self, tmp_path):
        ds, s = _linked_dataset(tmp_path)
        with pytest.raises(ValueError):
            ds.convertLinkedSessionToIngested(s.id(), are_you_sure=False)

    def test_unknown_session_errors(self, tmp_path):
        ds, _s = _linked_dataset(tmp_path)
        with pytest.raises(ValueError):
            ds.convertLinkedSessionToIngested("nonexistent_id", are_you_sure=True)

    def test_already_ingested_errors(self, tmp_path):
        s = _session(tmp_path, "s", "exp")
        ds = _dataset(tmp_path, "ds", "ds_ref")
        ds.add_ingested_session(s)
        with pytest.raises(ValueError):
            ds.convertLinkedSessionToIngested(s.id(), are_you_sure=True)
