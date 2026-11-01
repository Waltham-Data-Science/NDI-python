"""The vhlab vhneuropixelsGLX_nidq DAQ system (SpikeGLX NI-DAQ stream).

Mirrors NDI-matlab's ndi_common/daq_systems/vhlab/vhneuropixelsGLX_nidq.json
(VH-Lab/NDI-matlab#1127). vhneuropixelsGLX reads the IMEC .ap.bin, whose
digital lines are the IMEC SY bits; this system reads the .nidq.bin, so the
NI-DAQ lines are reachable: SpikeGLX XDn is channel di(n+1).
"""

from __future__ import annotations

import tempfile

import pytest

from ndi.daq.reader.mfdaq.ndr import ndi_daq_reader_mfdaq_ndr
from ndi.daq.system_mfdaq import ndi_daq_system_mfdaq
from ndi.file.navigator.epochdir import ndi_file_navigator_epochdir
from ndi.session.dir import ndi_session_dir
from ndi.setup.lab import lab as setup_lab


@pytest.fixture
def nidq_system():
    s = ndi_session_dir("vhtest", tempfile.mkdtemp())
    setup_lab(s, "vhlab")
    return s.daqsystem_load(name="vhneuropixelsGLX_nidq")


def test_reads_the_nidq_stream_with_the_ndr_glx_reader(nidq_system):
    assert isinstance(nidq_system, ndi_daq_system_mfdaq)
    assert isinstance(nidq_system.daqreader, ndi_daq_reader_mfdaq_ndr)
    assert nidq_system.daqreader.ndr_reader_string == "neuropixelsGLX"


def test_epochs_are_nidq_files_plus_epochprobemap(nidq_system):
    fn = nidq_system.filenavigator
    assert isinstance(fn, ndi_file_navigator_epochdir)
    assert fn.fileparameters["filematch"] == [
        "#.nidq\\.bin\\>",
        "#.nidq\\.meta\\>",
        "epochprobemap.txt",
    ]
    assert fn.epochprobemap_fileparameters["filematch"] == ["epochprobemap.txt"]
