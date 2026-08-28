"""Tests for the vhlab Prairie 2-photon file navigator.

Python port of:
    tests/+ndi/+unittest/+setup/+file/+navigator/vhPrairie2pTest.m

Synthesizes a session whose epochs are <BASE> / <BASE>-NNN directory pairs
and checks that the navigator assembles each epoch's file group correctly:
the reference/frametrigger index files from <BASE> plus the non-TIFF config
of each <BASE>-NNN acquisition directory, with the epoch id equal to <BASE>.
"""

from __future__ import annotations

import os

import pytest

from ndi.session.dir import ndi_session_dir
from ndi.setup.file.navigator.vhprairie2p import ndi_setup_file_navigator_vhPrairie2p


def write_text(path, contents):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(contents + "\n")


def has(group, relpath):
    """True if any file in the group ends with this relative path."""
    rel = relpath.replace("/", os.sep)
    return any(rel in f for f in group)


def group_for_base(groups, base):
    for g in groups:
        if has(g, f"{base}/reference.txt"):
            return g
    return []


@pytest.fixture
def paired_session(tmp_path):
    d = str(tmp_path / "prairie")

    # epoch A: a single acquisition directory (the common case)
    write_text(os.path.join(d, "expA", "reference.txt"), "index")
    write_text(os.path.join(d, "expA", "frametrigger.txt"), "0 1 2")
    write_text(os.path.join(d, "expA-001", "expA-001.xml"), "<PVScan/>")
    write_text(os.path.join(d, "expA-001", "expA-001_Cycle001_Ch1_000001.tif"), "tiffbytes")

    # epoch B: several acquisition directories -> still ONE epoch (rare)
    write_text(os.path.join(d, "expB", "reference.txt"), "index")
    write_text(os.path.join(d, "expB", "frametrigger.txt"), "0 1")
    for n in ("001", "002", "003"):
        write_text(os.path.join(d, f"expB-{n}", "expB.xml"), "<PVScan/>")

    # a distractor directory with no reference.txt -> not an epoch
    write_text(os.path.join(d, "misc", "notes.txt"), "ignore me")

    S = ndi_session_dir("prairieexp", d)
    return ndi_setup_file_navigator_vhPrairie2p(S, ["reference.txt"])


def test_directory_pair_grouping(paired_session):
    groups = paired_session.selectfilegroups_disk()
    assert len(groups) == 2, "Expected exactly two epochs (expA, expB)."


def test_epoch_a_contents(paired_session):
    gA = group_for_base(paired_session.selectfilegroups_disk(), "expA")
    assert gA, "Did not find the expA epoch."
    assert has(gA, "expA/reference.txt")
    assert has(gA, "expA/frametrigger.txt")
    assert has(gA, "expA-001/expA-001.xml")


def test_tiff_frames_are_not_listed(paired_session):
    """The reader resolves TIFFs from the config file's directory; listing
    them here would put thousands of paths in every epoch."""
    gA = group_for_base(paired_session.selectfilegroups_disk(), "expA")
    assert not any(f.lower().endswith((".tif", ".tiff")) for f in gA)


def test_epoch_b_spans_several_acquisition_dirs(paired_session):
    gB = group_for_base(paired_session.selectfilegroups_disk(), "expB")
    assert gB, "Did not find the expB epoch."
    for n in ("001", "002", "003"):
        assert has(gB, f"expB-{n}/expB.xml"), f"expB missing -{n} xml."


def test_epoch_id_is_the_base_directory_name(paired_session):
    groups = paired_session.selectfilegroups_disk()
    gA = group_for_base(groups, "expA")
    gB = group_for_base(groups, "expB")
    assert paired_session.epochid(1, gA) == "expA"
    assert paired_session.epochid(1, gB) == "expB"


def test_base_without_acquisition_is_skipped(tmp_path):
    """A <BASE> with reference.txt but no <BASE>-NNN directory is not an epoch."""
    d = str(tmp_path / "prairie2")
    write_text(os.path.join(d, "lonely", "reference.txt"), "index")
    write_text(os.path.join(d, "good", "reference.txt"), "index")
    write_text(os.path.join(d, "good-001", "good.xml"), "<PVScan/>")

    S = ndi_session_dir("prairieexp2", d)
    nav = ndi_setup_file_navigator_vhPrairie2p(S, ["reference.txt"])

    groups = nav.selectfilegroups_disk()
    assert len(groups) == 1, "Only the paired <BASE> should yield an epoch."
    assert nav.epochid(1, groups[0]) == "good"


def test_hidden_directories_are_ignored(tmp_path):
    d = str(tmp_path / "prairie3")
    write_text(os.path.join(d, ".hidden", "reference.txt"), "index")
    write_text(os.path.join(d, ".hidden-001", "x.xml"), "<PVScan/>")
    write_text(os.path.join(d, "good", "reference.txt"), "index")
    write_text(os.path.join(d, "good-001", "good.xml"), "<PVScan/>")

    S = ndi_session_dir("prairieexp3", d)
    nav = ndi_setup_file_navigator_vhPrairie2p(S, ["reference.txt"])
    assert len(nav.selectfilegroups_disk()) == 1
