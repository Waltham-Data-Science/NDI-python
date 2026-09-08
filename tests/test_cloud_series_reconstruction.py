"""A downloaded file series' members must be reachable, and provably so.

MATLAB counterparts:
    +ndi/+cloud/+sync/+internal/reconstructSeriesIngestLocations.m  (#958)
    +ndi/+cloud/+sync/+internal/updateFileInfoForLocalFiles.m       (#966)

A series keeps its members on the cloud deliberately: opening a dataset must
not drag down a 28,000-member series. So a downloaded series is a manifest on
disk and nothing else, and two things have to be true for its members to be
readable at all.

FIRST, the document has to be addable. ``ingest_locations`` is transient
authoring data that DID strips before storing, so a cloud round trip returns
``n_present`` with no way to locate any of the uids it counts -- and DID
refuses exactly that shape (DID-matlab#185). Not a warning: a ValueError from
``add_docs``, which loses the whole document.

SECOND, a member has no location of its own. DID resolves one by handing the
MANIFEST's location to the file handler with the member's uid in the context,
so the manifest has to keep its ``ndic://`` reference beside the local copy.
With the local path alone the handler is given something that does not start
with ``ndic://``, and every member of a downloaded series is unreadable --
silently, because DID reads that as a plain miss.

``TestThroughARealDatabase`` is what NDI-python#215 asks for: a member of a
downloaded series opened end to end. It fails if either half is missing.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from did.file import write_series_manifest

from ndi.cloud.filehandler import (
    NDIC_SCHEME,
    reconstructSeriesIngestLocations,
    updateFileInfoForLocalFiles,
)
from ndi.document import ndi_document
from ndi.session.dir import ndi_session_dir

#: demoNDI's one file slot, used here as a series NAME: the manifest is an
#: ordinary file in file_list, and its members are SLOT_1 ... SLOT_N.
SLOT = "filename1.ext"
CLOUD_ID = "ds_cloud_1"
MEMBER_BYTES = b"the member's own bytes, not the manifest's"


@pytest.fixture
def tag():
    """A fresh uid prefix per test.

    DID's file cache is MACHINE-GLOBAL and keyed by uid
    (``~/Documents/DID/fileCache/<uid>``), not scoped to tmp_path. A constant
    uid therefore lets the member-fetch test pass once and then resolve from
    that cache for ever after -- so the very fetch this file exists to check
    would silently stop happening while the test kept reporting success.
    Found the hard way: it passed, then failed on the next run.
    """
    return uuid.uuid4().hex[:8]


def manifest_uid(tag):
    return f"MANIFEST{tag}".ljust(33, "0")


def member_uid(tag, n):
    return f"MEMBER{tag}{n:019d}"


def series_props(session_id, tag, uids, count=None, n_present=None):
    """A demoNDI document declaring a series, in downloaded shape.

    Downloaded shape means: the manifest's file_info entry names a cloud
    location, series_info records how many members there are, and there is
    no ingest_locations -- storage stripped it.
    """
    present = [u for u in uids if u]
    props = ndi_document("demoNDI").document_properties
    props["base"]["session_id"] = session_id
    props["demoNDI"]["value"] = 1
    props["files"]["file_series"] = [SLOT]
    props["files"]["file_info"] = [
        {
            "name": SLOT,
            "locations": [
                {
                    "uid": manifest_uid(tag),
                    "location": f"{NDIC_SCHEME}{CLOUD_ID}/{manifest_uid(tag)}",
                    "location_type": "ndicloud",
                    "ingest": 0,
                    "delete_original": 0,
                    "parameters": "",
                }
            ],
        }
    ]
    props["files"]["series_info"] = [
        {
            "name": SLOT,
            "count": len(uids) if count is None else count,
            "n_present": len(present) if n_present is None else n_present,
            "source_root": "",
        }
    ]
    return props


@pytest.fixture
def staging(tmp_path, tag):
    """A staging folder holding a downloaded manifest for one member."""
    d = tmp_path / "download" / "files"
    d.mkdir(parents=True)
    write_series_manifest(str(d / manifest_uid(tag)), [member_uid(tag, 1)])
    return d


def locations_of(props):
    return props["files"]["file_info"][0]["locations"]


def ingest_locations_of(props):
    return props["files"]["series_info"][0].get("ingest_locations", [])


class TestTheManifestKeepsItsCloudReference:
    def test_a_manifest_gets_a_second_ndic_location(self, tag, staging):
        props = series_props("sess", tag, [member_uid(tag, 1)])
        updateFileInfoForLocalFiles(props, str(staging), CLOUD_ID)

        locations = locations_of(props)
        assert len(locations) == 2, "the manifest lost its cloud reference"

        local, cloud = locations
        assert local["location_type"] == "file" and local["ingest"] == 1
        assert cloud["location"] == f"{NDIC_SCHEME}{CLOUD_ID}/{manifest_uid(tag)}"
        assert cloud["location_type"] == "ndicloud"
        assert cloud["ingest"] == 0 and cloud["delete_original"] == 0

    def test_the_uri_names_the_manifests_original_uid(self, tag, staging):
        """The record gets a fresh uid; the URI keeps the cloud's.

        add_file mints a uid per location, which is harmless -- DID passes
        only the location STRING to the handler. What must not change is the
        uid INSIDE the reference, because that is what the cloud knows the
        manifest by.
        """
        props = series_props("sess", tag, [member_uid(tag, 1)])
        updateFileInfoForLocalFiles(props, str(staging), CLOUD_ID)

        cloud = locations_of(props)[1]
        assert manifest_uid(tag) in cloud["location"]
        assert cloud["uid"] != manifest_uid(tag)

    def test_an_ordinary_file_gets_no_second_location(self, tmp_path, tag):
        """Manifests only; a second location on every file is rows to no purpose."""
        d = tmp_path / "files"
        d.mkdir()
        (d / manifest_uid(tag)).write_bytes(b"ordinary")
        props = series_props("sess", tag, [member_uid(tag, 1)])
        props["files"]["file_series"] = []
        props["files"].pop("series_info")

        updateFileInfoForLocalFiles(props, str(d), CLOUD_ID)

        assert len(locations_of(props)) == 1

    def test_running_twice_does_not_add_it_twice(self, tag, staging):
        props = series_props("sess", tag, [member_uid(tag, 1)])
        updateFileInfoForLocalFiles(props, str(staging), CLOUD_ID)
        updateFileInfoForLocalFiles(props, str(staging), CLOUD_ID)

        assert len(locations_of(props)) == 2

    def test_a_matlab_shaped_manifest_keeps_both_locations(self, tag, staging):
        """MATLAB writes a one-element struct array as a bare object.

        So a manifest downloaded from a MATLAB-written dataset arrives with
        ``locations`` as a dict, not a list of one. Adding the cloud
        reference makes it two, and writing it back as a bare dict again
        would drop the very location the members are resolved through --
        which is the whole point of adding it.
        """
        props = series_props("sess", tag, [member_uid(tag, 1)])
        props["files"]["file_info"][0]["locations"] = props["files"]["file_info"][0]["locations"][0]

        updateFileInfoForLocalFiles(props, str(staging), CLOUD_ID)

        locations = locations_of(props)
        assert isinstance(locations, list), "the second location was dropped"
        assert len(locations) == 2
        assert locations[1]["location"] == f"{NDIC_SCHEME}{CLOUD_ID}/{manifest_uid(tag)}"

    def test_a_matlab_shaped_ordinary_file_stays_a_bare_dict(self, tmp_path, tag):
        """Only a grown list changes shape; everything else round-trips."""
        d = tmp_path / "files"
        d.mkdir()
        (d / manifest_uid(tag)).write_bytes(b"ordinary")
        props = series_props("sess", tag, [member_uid(tag, 1)])
        props["files"]["file_series"] = []
        props["files"].pop("series_info")
        props["files"]["file_info"][0]["locations"] = props["files"]["file_info"][0]["locations"][0]

        updateFileInfoForLocalFiles(props, str(d), CLOUD_ID)

        assert isinstance(props["files"]["file_info"][0]["locations"], dict)

    def test_no_cloud_id_means_no_second_location(self, tag, staging):
        props = series_props("sess", tag, [member_uid(tag, 1)])
        updateFileInfoForLocalFiles(props, str(staging))

        assert len(locations_of(props)) == 1


class TestReconstructSeriesIngestLocations:
    def test_one_entry_per_present_member(self, tmp_path, tag):
        d = tmp_path / "files"
        d.mkdir()
        uids = [member_uid(tag, n) for n in (1, 2, 3)]
        write_series_manifest(str(d / manifest_uid(tag)), uids)
        props = series_props("sess", tag, uids)

        reconstructSeriesIngestLocations(props, str(d), CLOUD_ID)

        entries = ingest_locations_of(props)
        assert [e["uid"] for e in entries] == uids
        assert [e["index"] for e in entries] == [1, 2, 3], "slots are one-based"
        for e in entries:
            assert e["location"] == f"{NDIC_SCHEME}{CLOUD_ID}/{e['uid']}"
            assert e["location_type"] == "ndicloud"
            assert e["ingest"] == 0, "reconstruction must not trigger a download"
            assert e["delete_original"] == 0

    def test_a_sparse_series_skips_its_gaps(self, tmp_path, tag):
        """An absent member is normal -- a member with nothing to store is
        not written. The INDEX still has to be the manifest slot, or every
        member after a gap resolves to the wrong file."""
        d = tmp_path / "files"
        d.mkdir()
        uids = ["", member_uid(tag, 2), "", member_uid(tag, 4)]
        write_series_manifest(str(d / manifest_uid(tag)), uids)
        props = series_props("sess", tag, uids)

        reconstructSeriesIngestLocations(props, str(d), CLOUD_ID)

        entries = ingest_locations_of(props)
        assert [e["index"] for e in entries] == [2, 4]
        assert [e["uid"] for e in entries] == [member_uid(tag, 2), member_uid(tag, 4)]

    def test_a_missing_manifest_leaves_the_guard_to_fire(self, tmp_path, tag):
        """Deliberately not a repair. If the manifest is not on disk the
        download was incomplete, and refusing the document at add_docs is a
        better outcome than storing a series recording half its members."""
        d = tmp_path / "files"
        d.mkdir()
        props = series_props("sess", tag, [member_uid(tag, 1)])

        reconstructSeriesIngestLocations(props, str(d), CLOUD_ID)

        assert ingest_locations_of(props) == []

    def test_a_corrupt_manifest_leaves_the_guard_to_fire(self, tmp_path, tag, caplog):
        d = tmp_path / "files"
        d.mkdir()
        (d / manifest_uid(tag)).write_bytes(b"not a manifest")
        props = series_props("sess", tag, [member_uid(tag, 1)])

        reconstructSeriesIngestLocations(props, str(d), CLOUD_ID)

        assert ingest_locations_of(props) == []
        assert "manifest" in caplog.text.lower(), "a corrupt manifest must be said"

    def test_an_existing_record_is_not_rebuilt(self, tmp_path, tag):
        d = tmp_path / "files"
        d.mkdir()
        write_series_manifest(str(d / manifest_uid(tag)), [member_uid(tag, 1)])
        props = series_props("sess", tag, [member_uid(tag, 1)])
        mine = [{"index": 1, "uid": "ALREADY", "location": "/somewhere", "ingest": 1}]
        props["files"]["series_info"][0]["ingest_locations"] = mine

        reconstructSeriesIngestLocations(props, str(d), CLOUD_ID)

        assert ingest_locations_of(props) == mine

    def test_an_empty_series_is_left_alone(self, tmp_path, tag):
        d = tmp_path / "files"
        d.mkdir()
        props = series_props("sess", tag, [], count=4, n_present=0)

        reconstructSeriesIngestLocations(props, str(d), CLOUD_ID)

        assert ingest_locations_of(props) == []

    def test_a_document_without_series_is_untouched(self, tmp_path, tag):
        props = series_props("sess", tag, [member_uid(tag, 1)])
        props["files"].pop("series_info")

        reconstructSeriesIngestLocations(props, str(tmp_path), CLOUD_ID)

        assert "series_info" not in props["files"]


class TestThroughARealDatabase:
    """The part that cannot be checked by inspecting a dict."""

    @staticmethod
    def _session(tmp_path):
        d = tmp_path / "sess"
        d.mkdir()
        return ndi_session_dir("exp", d)

    def test_a_reconstructed_document_is_accepted(self, tmp_path, tag, staging):
        session = self._session(tmp_path)
        props = series_props(session.id(), tag, [member_uid(tag, 1)])
        updateFileInfoForLocalFiles(props, str(staging), CLOUD_ID)

        session.database_add(ndi_document(props))  # must not raise

    def test_without_the_reconstruction_did_refuses_the_document(self, tmp_path, tag, staging):
        """The failure this whole change exists to prevent, stated as a test.

        Not a warning and not a mis-resolution: DID raises from add_docs, so
        every sync_files=True download would have lost the first document
        carrying a populated series.
        """
        session = self._session(tmp_path)
        props = series_props(session.id(), tag, [member_uid(tag, 1)])
        updateFileInfoForLocalFiles(props, str(staging))  # no cloud id

        with pytest.raises(ValueError, match="records no ingest_locations"):
            session.database_add(ndi_document(props))

    def test_a_member_of_a_downloaded_series_can_be_read(self, tmp_path, tag, staging):
        """End to end, and the test NDI-python#215 asks for.

        The member is NOT on this machine -- reconstruction records ingest=0
        precisely so that adding the document does not pull 28,000 files
        down. Reading one has to go out to the cloud, and the only route
        there is the manifest's ndic:// location plus the member's uid in
        the context. This fails if the manifest lost its cloud reference, if
        the ingest_locations were never rebuilt, or if the handler ignores
        the context and fetches the manifest instead.
        """
        session = self._session(tmp_path)
        props = series_props(session.id(), tag, [member_uid(tag, 1)])
        updateFileInfoForLocalFiles(props, str(staging), CLOUD_ID)
        doc = ndi_document(props)
        session.database_add(doc)

        asked = {}

        def fake_fetch(uri, target, client=None, **kwargs):
            asked["uri"] = uri
            asked["kwargs"] = kwargs
            Path(target).write_bytes(MEMBER_BYTES)
            return True

        with patch("ndi.cloud.filehandler.fetch_cloud_file", fake_fetch):
            handle = session.database_openbinarydoc(doc, f"{SLOT}_1")
            data = handle.read()

        assert asked.get("uri") == f"{NDIC_SCHEME}{CLOUD_ID}/{member_uid(tag, 1)}", (
            "the handler was asked for the wrong file: "
            f"{asked.get('uri')!r} rather than the member's own uid"
        )
        assert data == MEMBER_BYTES

    def test_the_manifest_itself_is_still_a_local_read(self, tmp_path, tag, staging):
        """The manifest was downloaded, so reading it must not hit the cloud.

        The second location is an ADDITION, not a replacement: giving the
        manifest a cloud reference must not cost a download every time the
        series is consulted.
        """
        session = self._session(tmp_path)
        manifest_bytes = (staging / manifest_uid(tag)).read_bytes()
        props = series_props(session.id(), tag, [member_uid(tag, 1)])
        updateFileInfoForLocalFiles(props, str(staging), CLOUD_ID)
        doc = ndi_document(props)
        session.database_add(doc)

        def refuse(*args, **kwargs):
            raise AssertionError("went to the cloud for a file already on disk")

        with patch("ndi.cloud.filehandler.fetch_cloud_file", refuse):
            handle = session.database_openbinarydoc(doc, SLOT)
            assert handle.read() == manifest_bytes
