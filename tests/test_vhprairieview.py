"""Tests for the vhlab PrairieView image DAQ system (issue #71).

The symmetry failure this closes was a count: a vhlab blank session built
8 DAQ systems in Python and 9 in MATLAB. The count is checked here, but so
are the classes behind the ninth entry -- a wrong ninth entry would make the
count match while still being wrong.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from ndi.class_registry import get_class
from ndi.daq.reader.image import ndi_daq_reader_image
from ndi.daq.reader.image.ndr import ndi_daq_reader_image_ndr
from ndi.daq.system_image import ndi_daq_system_image
from ndi.session.dir import ndi_session_dir
from ndi.setup.epoch.epochprobemap_daqsystem_vhlab import (
    ndi_setup_epoch_epochprobemap_daqsystem_vhlab,
)
from ndi.setup.file.navigator.vhprairie2p import ndi_setup_file_navigator_vhPrairie2p
from ndi.setup.lab import lab as setup_lab
from ndi.util.session_summary import sessionSummary


class TestVhlabDaqSystemCount:
    """The blank-session count that the symmetry test compares."""

    @pytest.fixture
    def vhlab_session(self):
        d = tempfile.mkdtemp()
        s = ndi_session_dir("vhtest", d)
        setup_lab(s, "vhlab")
        return s

    def test_nine_daq_systems_including_vhprairieview(self, vhlab_session):
        summary = sessionSummary(vhlab_session)
        assert len(summary["daqSystemNames"]) == 9
        assert "vhprairieview" in summary["daqSystemNames"]

    def test_vhprairieview_uses_the_image_classes(self, vhlab_session):
        """Not just present -- present with the right navigator and reader."""
        summary = sessionSummary(vhlab_session)
        i = summary["daqSystemNames"].index("vhprairieview")
        details = summary["daqSystemDetails"][i]
        assert details["filenavigator_class"] == "ndi.setup.file.navigator.vhPrairie2p"
        assert details["daqreader_class"] == "ndi.daq.reader.image.ndr"

    def test_names_and_details_stay_aligned(self, vhlab_session):
        summary = sessionSummary(vhlab_session)
        assert len(summary["daqSystemNames"]) == len(summary["daqSystemDetails"])

    def test_the_loaded_system_is_an_image_daq_system(self, vhlab_session):
        daqs = vhlab_session.daqsystem_load(name="vhprairieview")
        assert isinstance(daqs, ndi_daq_system_image)
        assert isinstance(daqs.daqreader, ndi_daq_reader_image_ndr)
        assert daqs.daqreader.ndr_reader_string == "prairieview"


class TestClassRegistration:
    """The registry is what _document_to_object uses to rebuild these."""

    @pytest.mark.parametrize(
        ("name", "cls"),
        [
            ("ndi.daq.system.image", ndi_daq_system_image),
            ("ndi.daq.reader.image.ndr", ndi_daq_reader_image_ndr),
            ("ndi.setup.file.navigator.vhPrairie2p", ndi_setup_file_navigator_vhPrairie2p),
        ],
    )
    def test_registered(self, name, cls):
        assert get_class(name) is cls

    def test_image_ndr_is_an_image_reader(self):
        """ndi_daq_system_image rejects a reader that is not an image reader."""
        assert issubclass(ndi_daq_reader_image_ndr, ndi_daq_reader_image)


class TestVhPrairie2pNavigator:
    """The <BASE> / <BASE>-NNN directory-pairing rule."""

    @staticmethod
    def _make_epoch(root, base, acq_suffixes=("-001",), sync=True, frames=True):
        os.makedirs(os.path.join(root, base), exist_ok=True)
        with open(os.path.join(root, base, "reference.txt"), "w") as f:
            f.write("name\tref\ttype\ntp\t1\tprairieTP\n")
        if sync:
            with open(os.path.join(root, base, "frametrigger.txt"), "w") as f:
                f.write("0.0\n")
        for suf in acq_suffixes:
            adir = os.path.join(root, base + suf)
            os.makedirs(adir, exist_ok=True)
            with open(os.path.join(adir, f"{base}{suf}.xml"), "w") as f:
                f.write("<PVScan/>")
            if frames:
                # Frames must NOT be enumerated: the reader resolves them.
                for n in range(3):
                    with open(os.path.join(adir, f"frame_{n}.tif"), "w") as f:
                        f.write("x")

    def _nav(self, root):
        session = ndi_session_dir("vhtest", root)
        return ndi_setup_file_navigator_vhPrairie2p(session, "reference.txt")

    def test_pairs_base_with_acquisition_directory(self, tmp_path):
        root = str(tmp_path)
        self._make_epoch(root, "t00001")
        groups = self._nav(root).selectfilegroups_disk()
        assert len(groups) == 1
        assert groups[0][0].endswith(os.path.join("t00001", "reference.txt"))

    def test_tiffs_are_not_listed(self, tmp_path):
        """Thousands of frames must not land in the epoch file list."""
        root = str(tmp_path)
        self._make_epoch(root, "t00001")
        (group,) = self._nav(root).selectfilegroups_disk()
        assert not [f for f in group if f.lower().endswith((".tif", ".tiff"))]
        assert any(f.endswith(".xml") for f in group)

    def test_sync_file_included_when_present(self, tmp_path):
        root = str(tmp_path)
        self._make_epoch(root, "t00001", sync=True)
        (group,) = self._nav(root).selectfilegroups_disk()
        assert any(f.endswith("frametrigger.txt") for f in group)

    def test_sync_file_optional(self, tmp_path):
        root = str(tmp_path)
        self._make_epoch(root, "t00001", sync=False)
        (group,) = self._nav(root).selectfilegroups_disk()
        assert not [f for f in group if f.endswith("frametrigger.txt")]

    def test_multiple_cycles_are_one_epoch(self, tmp_path):
        """-001 and -002 are cycles of one run, not two epochs."""
        root = str(tmp_path)
        self._make_epoch(root, "t00001", acq_suffixes=("-001", "-002"))
        groups = self._nav(root).selectfilegroups_disk()
        assert len(groups) == 1
        assert len([f for f in groups[0] if f.endswith(".xml")]) == 2

    def test_base_without_acquisition_directory_is_skipped(self, tmp_path):
        root = str(tmp_path)
        os.makedirs(os.path.join(root, "t00001"))
        with open(os.path.join(root, "t00001", "reference.txt"), "w") as f:
            f.write("name\tref\ttype\ntp\t1\tprairieTP\n")
        assert self._nav(root).selectfilegroups_disk() == []

    def test_directory_without_reference_txt_is_not_an_epoch(self, tmp_path):
        root = str(tmp_path)
        os.makedirs(os.path.join(root, "notanepoch-001"))
        assert self._nav(root).selectfilegroups_disk() == []

    def test_two_epochs(self, tmp_path):
        root = str(tmp_path)
        self._make_epoch(root, "t00001")
        self._make_epoch(root, "t00002")
        assert len(self._nav(root).selectfilegroups_disk()) == 2

    def test_epochid_is_the_base_directory_name(self, tmp_path):
        root = str(tmp_path)
        self._make_epoch(root, "t00001")
        (group,) = self._nav(root).selectfilegroups_disk()
        assert self._nav(root).epochid(0, group) == "t00001"


class TestVhlabEpochProbeMap:
    """reference.txt parsing."""

    @staticmethod
    def _write(tmp_path, body, subject="mysubject@vhlab.org"):
        epochdir = tmp_path / "t00001"
        epochdir.mkdir()
        ref = epochdir / "reference.txt"
        ref.write_text(body)
        (tmp_path / "subject.txt").write_text(subject + "\n")
        return str(ref)

    def test_parses_prairie_reference(self, tmp_path):
        ref = self._write(tmp_path, "name\tref\ttype\ntp\t1\tprairieTP\n")
        (epm,) = ndi_setup_epoch_epochprobemap_daqsystem_vhlab.from_file(ref)
        assert epm.name == "tp"
        assert epm.reference == 1
        assert epm.devicestring == "vhprairieview:image1"

    def test_prairietp_maps_to_canonical_probe_type(self, tmp_path):
        ref = self._write(tmp_path, "name\tref\ttype\ntp\t1\tprairieTP\n")
        (epm,) = ndi_setup_epoch_epochprobemap_daqsystem_vhlab.from_file(ref)
        assert epm.type == "two-photon-imaging"

    def test_shorthand_is_case_insensitive_and_whitespace_tolerant(self, tmp_path):
        """reference.txt is written by hand."""
        ref = self._write(tmp_path, "name\tref\ttype\ntp\t1\t  PrairieTP  \n")
        (epm,) = ndi_setup_epoch_epochprobemap_daqsystem_vhlab.from_file(ref)
        assert epm.type == "two-photon-imaging"

    def test_subject_read_from_parent_directory(self, tmp_path):
        ref = self._write(tmp_path, "name\tref\ttype\ntp\t1\tprairieTP\n", subject="s@vhlab.org")
        (epm,) = ndi_setup_epoch_epochprobemap_daqsystem_vhlab.from_file(ref)
        assert epm.subjectstring == "s@vhlab.org"

    def test_multiple_probes(self, tmp_path):
        ref = self._write(tmp_path, "name\tref\ttype\ntp\t1\tprairieTP\ntp\t2\tprairieTP\n")
        epms = ndi_setup_epoch_epochprobemap_daqsystem_vhlab.from_file(ref)
        assert [e.reference for e in epms] == [1, 2]

    def test_wrong_header_rejected(self, tmp_path):
        ref = self._write(tmp_path, "name\treference\ttype\ntp\t1\tprairieTP\n")
        with pytest.raises(ValueError, match="name, ref, type"):
            ndi_setup_epoch_epochprobemap_daqsystem_vhlab.from_file(ref)

    def test_missing_subject_file_is_an_error(self, tmp_path):
        epochdir = tmp_path / "t00001"
        epochdir.mkdir()
        ref = epochdir / "reference.txt"
        ref.write_text("name\tref\ttype\ntp\t1\tprairieTP\n")
        with pytest.raises(FileNotFoundError, match="subject.txt"):
            ndi_setup_epoch_epochprobemap_daqsystem_vhlab.from_file(str(ref))

    def test_unported_vhlab_forms_say_so(self, tmp_path):
        """The other vhlab epoch files are not guessed at."""
        f = tmp_path / "vhintan_channelgrouping.txt"
        f.write_text("x\n")
        with pytest.raises(NotImplementedError, match="reference.txt"):
            ndi_setup_epoch_epochprobemap_daqsystem_vhlab.from_file(str(f))
