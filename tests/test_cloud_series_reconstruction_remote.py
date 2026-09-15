"""Offline coverage for ``updateFileInfoForRemoteFiles``'s SyncFiles=false path.

MATLAB counterpart:
    tests/+ndi/+unittest/+database/TestUpdateFileInfoForRemoteFilesShape.m

The SyncFiles=false download rewrites every file_info location to ``ndic://``
and marks it ``ingest=0``. That already worked. What did not, until
VH-Lab/NDI-matlab#988, was the series half: a document that carries a
populated file series returns from a cloud round trip with ``n_present``
still populated but ``ingest_locations`` stripped (DID strips it before
storing), and DID's ``MembersNotLocatable`` guard (DID-matlab#185) then
refuses the document on the following ``add_docs``. The whole
SyncFiles=false path was blocked on that guard for any series document.

The port teaches ``updateFileInfoForRemoteFiles`` to rebuild those
``ingest_locations`` on the way out by fetching each qualifying series'
manifest bytes through the DID ``custom_file_handler`` contract -- the
same one DID uses on the read side (VH-Lab/DID-matlab#201 /
VH-Lab/DID-python#88), so a caller with a handler already can pass it in
and both sides use the same one. The bytes are dropped when the function
returns; a subsequent member open trips DID#201's lazy fetch, which is
what populates the file cache. Covered here through a mock handler; the
real cloud round trip lives on the cloud side.
"""

from __future__ import annotations

import copy
import uuid
from pathlib import Path

import pytest
from did.file import write_series_manifest

from ndi.cloud.filehandler import (
    NDIC_SCHEME,
    updateFileInfoForRemoteFiles,
)
from ndi.document import ndi_document
from ndi.query import ndi_query
from ndi.session.dir import ndi_session_dir

SLOT = "filename1.ext"
CLOUD_ID = "ds_remote_1"


@pytest.fixture
def tag():
    """A fresh uid prefix per test.

    DID's file cache is machine-global and keyed by uid, so a constant uid
    lets a fetch pass once and resolve from cache forever after -- and the
    fetch this file exists to exercise would silently stop happening.
    """
    return uuid.uuid4().hex[:8]


def manifest_uid(tag):
    return f"MANIFEST{tag}".ljust(33, "0")


def member_uid(tag, n):
    return f"MEMBER{tag}{n:019d}"


def local_series_props(session_id, tag, member_uids, manifest_bytes):
    """A demoNDI document declaring a series, in freshly-authored shape.

    file_info names the manifest by uid but points at a local file (the
    manifest bytes on disk); series_info carries ingest_locations with
    ``ingest=0`` per member. This is the shape ``updateFileInfoForRemoteFiles``
    normally receives from a caller; the point of the test suite is what
    happens AFTER DID has stripped the ingest_locations on store.
    """
    present = [u for u in member_uids if u]
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
                    "location": str(manifest_bytes),
                    "location_type": "file",
                    "ingest": 1,
                    "delete_original": 0,
                    "parameters": "",
                }
            ],
        }
    ]
    props["files"]["series_info"] = [
        {
            "name": SLOT,
            "count": len(member_uids),
            "n_present": len(present),
            "source_root": "",
            "ingest_locations": [
                {
                    "index": i + 1,
                    "uid": u,
                    "location": f"/tmp/nowhere/{u}",
                    "location_type": "file",
                    "ingest": 0,
                    "delete_original": 0,
                }
                for i, u in enumerate(member_uids)
                if u
            ],
        }
    ]
    return props


def stripped_series_props(session_id, tag, member_uids):
    """The shape a SyncFiles=false cloud round trip produces.

    file_info's location is still local -- the caller has not yet
    rewritten it to ndic://, that is what ``updateFileInfoForRemoteFiles``
    does -- but ingest_locations is empty. In practice DID does the
    stripping on store; the test helper mimics the resulting shape without
    touching a database.
    """
    props = local_series_props(session_id, tag, member_uids, "/tmp/nowhere/manifest")
    props["files"]["series_info"][0].pop("ingest_locations")
    return props


class TestFileInfoReshape:
    """Every file_info location must come out ndic://, whether or not the
    document carries a series."""

    def test_a_plain_document_gets_ndic_locations(self, tmp_path, tag):
        props = ndi_document("demoNDI").document_properties
        props["base"]["session_id"] = "s"
        props["files"]["file_info"] = [
            {
                "name": SLOT,
                "locations": [
                    {
                        "uid": "UID_A",
                        "location": "/local/UID_A",
                        "location_type": "file",
                        "ingest": 1,
                        "delete_original": 0,
                        "parameters": "",
                    }
                ],
            }
        ]

        updateFileInfoForRemoteFiles(props, CLOUD_ID)

        loc = props["files"]["file_info"][0]["locations"][0]
        assert loc["location"] == f"{NDIC_SCHEME}{CLOUD_ID}/UID_A"
        assert loc["location_type"] == "ndicloud"
        assert loc["ingest"] == 0
        assert loc["delete_original"] == 0
        assert loc["uid"] == "UID_A", "uid must survive the reshape"

    def test_a_series_document_reshapes_file_info_the_same_way(self, tag):
        """The manifest's file_info entry goes ndic:// just like a plain file."""
        props = stripped_series_props("s", tag, [member_uid(tag, 1)])

        # No handler: the reconstruction branch will fail to fetch, which
        # is fine -- this test is only about the file_info reshape half.
        updateFileInfoForRemoteFiles(props, CLOUD_ID)

        loc = props["files"]["file_info"][0]["locations"][0]
        assert loc["location"] == f"{NDIC_SCHEME}{CLOUD_ID}/{manifest_uid(tag)}"
        assert loc["location_type"] == "ndicloud"


class TestReconstructionSkipsWhenNotNeeded:
    """A document that does not need reconstruction must not invoke the
    handler at all -- no fetch, no scratch dir, no network."""

    def test_a_populated_ingest_locations_is_left_alone(self, tmp_path, tag):
        props = local_series_props(
            "s", tag, [member_uid(tag, 1), member_uid(tag, 2)], tmp_path / "m"
        )
        before = copy.deepcopy(props["files"]["series_info"][0]["ingest_locations"])

        called = {"n": 0}

        def refuse_handler(dest, source, ctx):
            called["n"] += 1
            raise AssertionError("the handler must not be called")

        updateFileInfoForRemoteFiles(props, CLOUD_ID, custom_file_handler=refuse_handler)

        assert called["n"] == 0
        after = props["files"]["series_info"][0]["ingest_locations"]
        assert after == before, "ingest_locations must survive unchanged"

    def test_a_document_without_series_info_is_left_alone(self, tag):
        props = ndi_document("demoNDI").document_properties
        props["base"]["session_id"] = "s"
        props["files"]["file_info"] = [
            {
                "name": SLOT,
                "locations": [
                    {
                        "uid": "UID_A",
                        "location": "/local/UID_A",
                        "location_type": "file",
                        "ingest": 1,
                        "delete_original": 0,
                        "parameters": "",
                    }
                ],
            }
        ]

        def refuse_handler(dest, source, ctx):
            raise AssertionError("the handler must not be called")

        updateFileInfoForRemoteFiles(props, CLOUD_ID, custom_file_handler=refuse_handler)

        # file_info still reshaped; nothing else touched.
        assert props["files"]["file_info"][0]["locations"][0]["location_type"] == "ndicloud"


class TestReconstructionThroughAMockHandler:
    """The reconstruction path end-to-end, but offline.

    A mock handler serves manifest bytes by uid. The rebuilt
    ``ingest_locations`` must name every present member's uid with an
    ``ndic://`` location and ``ingest=0``.

    Uses ``ndi_session_dir`` + ``database_add`` to walk the doc through DID's
    store/read cycle so ``ingest_locations`` gets stripped -- the exact
    shape a cloud round trip returns. Reshaping the stripped doc is what
    the port exists to fix.
    """

    def test_ingest_locations_are_rebuilt(self, tmp_path, tag):
        # A fresh session and a series doc with two present members.
        session_dir = tmp_path / "sess"
        session_dir.mkdir()
        session = ndi_session_dir("exp", session_dir)

        members = [member_uid(tag, 1), member_uid(tag, 2)]
        manifest_path = tmp_path / "manifest.bin"
        write_series_manifest(str(manifest_path), members)
        manifest_bytes = manifest_path.read_bytes()

        props = local_series_props(session.id(), tag, members, manifest_path)
        doc = ndi_document(props)
        session.database_add(doc)

        # Read the doc back from the store; ingest_locations is now stripped.
        results = session.database_search(ndi_query("base.id") == doc.id)
        assert len(results) == 1, "the doc should be readable back"
        stored_props = results[0].document_properties
        assert not stored_props["files"]["series_info"][0].get("ingest_locations"), (
            "fixture: DID should have stripped ingest_locations so this test "
            "is exercising the reconstruction, not a shortcut"
        )

        # A uid-keyed mock handler. Records every call so the test can
        # pin how many times, with what context, it was invoked.
        src_by_uid = {manifest_uid(tag): manifest_bytes}
        call_log = {"uids": [], "series_names": [], "modes": []}

        def mock_handler(dest_path, source_path, context):
            uid = ""
            series_name = ""
            mode = ""
            if isinstance(context, dict):
                uid = str(context.get("uid", "") or "")
                series_name = str(context.get("seriesName", "") or "")
                mode = str(context.get("mode", "") or "")
            call_log["uids"].append(uid)
            call_log["series_names"].append(series_name)
            call_log["modes"].append(mode)
            if uid not in src_by_uid:
                raise AssertionError(f"mock has no bytes for uid {uid!r}")
            Path(dest_path).write_bytes(src_by_uid[uid])

        # Reshape through updateFileInfoForRemoteFiles with the mock. It
        # must reconstruct ingest_locations without writing anything
        # durable outside the temp dir it manages.
        updateFileInfoForRemoteFiles(stored_props, CLOUD_ID, custom_file_handler=mock_handler)

        il = stored_props["files"]["series_info"][0].get("ingest_locations", [])
        assert len(il) == 2, "one ingest_locations entry per present member"
        for entry in il:
            assert entry["ingest"] == 0
            assert entry["delete_original"] == 0
            assert entry["location_type"] == "ndicloud"
            assert entry["location"].startswith(f"{NDIC_SCHEME}{CLOUD_ID}/")
            assert entry["uid"]

        # One handler call, for the manifest uid, seriesName '' (a
        # manifest, not a member). Multiple present slots must not
        # provoke multiple manifest fetches -- that guarantee is what
        # makes reconstruction cheap for a 28,000-member series.
        assert call_log["uids"] == [manifest_uid(tag)], "exactly one manifest fetch expected"
        assert call_log["series_names"] == [""], (
            "the manifest fetch must carry seriesName='' in its context "
            "(non-empty marks a MEMBER fetch)"
        )
        assert call_log["modes"] == ["open"]

    def test_a_handler_failure_leaves_ingest_locations_empty(self, tmp_path, tag):
        """A partial download must not silently succeed.

        A handler that cannot serve the manifest bytes leaves the entry
        un-reconstructed; DID's #185 guard then fires on ``add_docs`` with
        the document's own identity, which is the right signal for a
        partial download.
        """
        props = stripped_series_props("s", tag, [member_uid(tag, 1)])

        def failing_handler(dest, source, ctx):
            raise RuntimeError("cloud unreachable")

        updateFileInfoForRemoteFiles(props, CLOUD_ID, custom_file_handler=failing_handler)

        # ingest_locations still empty -- DID's guard will fire on add.
        assert not props["files"]["series_info"][0].get("ingest_locations")

    def test_a_two_argument_handler_is_supported(self, tmp_path, tag):
        """Older DID handlers took only ``(dest_path, source_path)``.

        The dispatch mirrors DID's own arity-aware dispatch, so a
        two-argument handler still works.
        """
        members = [member_uid(tag, 1)]
        manifest_path = tmp_path / "m"
        write_series_manifest(str(manifest_path), members)
        bytes_ = manifest_path.read_bytes()

        props = stripped_series_props("s", tag, members)

        def two_arg_handler(dest_path, source_path):
            Path(dest_path).write_bytes(bytes_)

        updateFileInfoForRemoteFiles(props, CLOUD_ID, custom_file_handler=two_arg_handler)

        il = props["files"]["series_info"][0].get("ingest_locations", [])
        assert len(il) == 1
        assert il[0]["uid"] == members[0]
