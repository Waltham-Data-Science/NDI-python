"""A document that cannot be turned into an object must say so.

``daqsystem_load`` swallowed every failure with a bare ``except Exception:
pass``. Nine daqsystem documents went in and eight objects came out, with
no message anywhere, so a session whose DAQ class is not implemented in
Python was indistinguishable from a session that simply had fewer DAQ
systems.

That is how ``vhprairieview`` -- added to NDI-matlab on 2026-07-20 and
naming ``ndi.daq.reader.image.ndr``, which had no Python counterpart --
surfaced only as a symmetry test complaining that two summaries had
different lengths. The real message, ``Unknown DAQ reader class:
'ndi.daq.reader.image.ndr'``, was raised the whole time and thrown away.

That particular class is ported now, so these tests use a reader class
that genuinely does not exist. The behaviour under test is the reporting,
not the gap that first exposed it.
"""

from __future__ import annotations

import importlib
import warnings

import pytest

from ndi.session.dir import ndi_session_dir

# ndi.setup re-exports the lab() function under the name "lab", shadowing
# the module of the same name; reach the module itself to patch inside it.
lab_module = importlib.import_module("ndi.setup.lab")

# A real, loadable config (vhintan's shape) so the test distinguishes
# "skipped because unportable" from "skipped because the fixture is wrong".
GOOD = {
    "Name": "good_sys",
    "DaqSystemClass": "ndi.daq.system.mfdaq",
    "DaqReaderClass": "ndi.daq.reader.mfdaq.intan",
    "EpochProbeMapClass": "ndi.setup.epoch.epochprobemap_daqsystem_vhlab",
    "FileParameters": ["reference.txt", ".*\\.rhd\\>"],
    "EpochProbeMapFileParameters": "vhintan_channelgrouping.txt",
    "HasEpochDirectories": True,
}

# Same shape vhprairieview had: a reader class with no Python
# implementation. Deliberately a name nothing will ever register, so that
# porting a real reader cannot quietly turn this test green.
UNPORTABLE = {
    "Name": "unportable_sys",
    "DaqSystemClass": "ndi.daq.system.mfdaq",
    "DaqReaderClass": "ndi.daq.reader.mfdaq.no_such_reader",
    "FileParameters": ["reference.txt"],
    "DaqReaderFileParameters": "no_such_format",
    "HasEpochDirectories": False,
}


@pytest.fixture
def session_with_unportable(tmp_path, monkeypatch):
    monkeypatch.setattr(lab_module, "_find_daq_configs", lambda name: [GOOD, UNPORTABLE])
    d = tmp_path / "sess"
    d.mkdir(parents=True, exist_ok=True)
    S = ndi_session_dir("exp1", str(d))
    lab_module.lab(S, "anylab")
    return S


def test_both_documents_are_in_the_database(session_with_unportable):
    """Precondition: the drop happens on load, not on write."""
    from ndi.query import ndi_query

    S = session_with_unportable
    q = ndi_query("").isa("daqsystem") & (ndi_query("base.session_id") == S.id())
    assert len(S.database_search(q)) == 2


def test_skipped_document_raises_a_warning(session_with_unportable):
    S = session_with_unportable
    with pytest.warns(RuntimeWarning) as record:
        S.daqsystem_load(name="(.*)")

    messages = [str(w.message) for w in record]
    assert any("unportable_sys" in m for m in messages), messages
    # The underlying reason must survive, not just the fact of a skip.
    assert any("ndi.daq.reader.mfdaq.no_such_reader" in m for m in messages), messages


def test_loadable_systems_are_still_returned(session_with_unportable):
    """The warning must not cost the caller the documents that do work."""
    S = session_with_unportable
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        loaded = S.daqsystem_load(name="(.*)")
    if not isinstance(loaded, list):
        loaded = [loaded]
    assert [d.name for d in loaded] == ["good_sys"]


def test_no_warning_when_everything_loads(tmp_path, monkeypatch):
    """The common case must stay quiet."""
    monkeypatch.setattr(lab_module, "_find_daq_configs", lambda name: [GOOD])
    d = tmp_path / "sess2"
    d.mkdir(parents=True, exist_ok=True)
    S = ndi_session_dir("exp2", str(d))
    lab_module.lab(S, "anylab")

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        S.daqsystem_load(name="(.*)")
