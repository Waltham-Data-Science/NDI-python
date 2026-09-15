"""``file_uploads_for_document`` finds an ingested binary in DID's file cache.

The recorded ``files.file_info[].locations[].location`` is the source path
the caller passed to ``add_file``. For a series manifest,
``did.document.Document.add_file_series`` writes that source path to a
``tempfile.NamedTemporaryFile(prefix="did_manifest_")`` -- and add_file
defaults ``delete_original=True`` on a ``file`` location, so
``did.database.add_docs`` copies the manifest into DID's ``FileDir/<uid>``
and removes the source. By the time :func:`ndi.cloud.upload.uploadDataset`'s
file pass runs, the recorded location no longer resolves and the manifest
would be silently missing from the upload -- which is what run 227 caught
on TEST_USER_1 (Waltham-Data-Science/NDI-python#306).

The fix: teach :func:`ndi.cloud.upload.file_uploads_for_document` to fall
back to ``did.file.cached_path_for_uid(uid, additional_roots=[...])`` when
the recorded location is gone. Callers pass the local dataset's
``binary_path`` in *additional_roots*.

Live-cloud coverage of the whole round trip is
``tests/test_cloud_file_series_round_trip.py``; this file is the offline
half, no credentials required.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from did.document import Document as DIDDocument

from ndi.cloud.orchestration import _did_file_store_roots
from ndi.cloud.upload import file_uploads_for_document
from ndi.dataset import ndi_dataset_dir
from ndi.document import ndi_document

SERIES_NAME = "chunkdata.bin"


@pytest.fixture
def cache_dir(tmp_path):
    """A directory that stands in for DID's FileDir.

    Just a folder holding ``<uid>`` blobs. Nothing else about DID is
    reached in these tests -- ``file_uploads_for_document``'s fallback is
    :func:`did.file.cached_path_for_uid`, which is a pure function of the
    uid and the roots.
    """
    d = tmp_path / "file_cache"
    d.mkdir()
    return d


class TestTheFallbackFindsAnIngestedManifest:
    """The MATLAB-style file_info shape (one entry, one location) and the
    minimum every caller of ``file_uploads_for_document`` promises.

    The recorded location has vanished (as it does after DID ingests a
    manifest tempfile), so this pins the shape of the fallback rather than
    driving it through a real ``database_add``. That case has its own test
    below; here the minimum is a ``file_info`` doc with one uid and a
    missing location.
    """

    @staticmethod
    def _doc(uid, gone_location):
        return {
            "base": {"id": "doc1"},
            "files": {
                "file_info": [
                    {
                        "name": SERIES_NAME,
                        "locations": [
                            {
                                "uid": uid,
                                "location": str(gone_location),
                                "location_type": "file",
                                "ingest": 1,
                                "delete_original": 0,
                                "parameters": "",
                            }
                        ],
                    }
                ]
            },
        }

    def test_the_manifest_is_found_by_uid_in_the_file_cache(self, tmp_path, cache_dir):
        uid = "u" + uuid.uuid4().hex
        (cache_dir / uid).write_bytes(b"manifest bytes")
        doc = self._doc(uid, tmp_path / "gone.manifest")

        pairs = file_uploads_for_document(doc, additional_roots=[str(cache_dir)])

        assert pairs == [(uid, str(cache_dir / uid))]

    def test_without_roots_the_fallback_does_not_fire(self, tmp_path, cache_dir):
        """The default remains what it was: a doc whose location is gone
        produces no pair. Callers that had this working before this fix
        still do."""
        uid = "u" + uuid.uuid4().hex
        (cache_dir / uid).write_bytes(b"manifest bytes")
        doc = self._doc(uid, tmp_path / "gone.manifest")

        assert file_uploads_for_document(doc) == []

    def test_a_live_recorded_location_is_still_preferred(self, tmp_path, cache_dir):
        """When the recorded path resolves, use it. Test data is separable
        from DID's cache, and preferring the recorded path avoids reading
        from the cache while the source is still there.
        """
        uid = "u" + uuid.uuid4().hex
        live = tmp_path / "live.bin"
        live.write_bytes(b"live source bytes")
        (cache_dir / uid).write_bytes(b"cached bytes")
        doc = self._doc(uid, live)

        pairs = file_uploads_for_document(doc, additional_roots=[str(cache_dir)])

        assert pairs == [(uid, str(live))]

    def test_a_missing_uid_produces_nothing(self, tmp_path, cache_dir):
        """No uid means nothing to look up; the fallback stays quiet."""
        doc = self._doc("", tmp_path / "gone")

        assert file_uploads_for_document(doc, additional_roots=[str(cache_dir)]) == []

    def test_neither_recorded_nor_cached_produces_nothing(self, tmp_path, cache_dir):
        """The caller learns of it as a failed document, not as a silent
        skip. Same shape as before this fix: no pair, no upload, and the
        report at :func:`uploadFilesForDatasetDocuments` marks the doc's
        binary as failed."""
        uid = "u" + uuid.uuid4().hex
        # cache_dir has no <uid> file this time.
        doc = self._doc(uid, tmp_path / "gone.manifest")

        assert file_uploads_for_document(doc, additional_roots=[str(cache_dir)]) == []

    def test_a_matlab_shaped_locations_dict_still_works(self, tmp_path, cache_dir):
        """MATLAB's jsonencode writes a one-element locations struct as a
        bare object. Same shape guard :func:`file_uploads_for_document`
        already had for the recorded-path case; it has to apply to the
        fallback too.
        """
        uid = "u" + uuid.uuid4().hex
        (cache_dir / uid).write_bytes(b"manifest bytes")
        doc = self._doc(uid, tmp_path / "gone.manifest")
        # Collapse the single-element list into a bare dict, MATLAB-style.
        doc["files"]["file_info"][0]["locations"] = doc["files"]["file_info"][0]["locations"][0]

        pairs = file_uploads_for_document(doc, additional_roots=[str(cache_dir)])

        assert pairs == [(uid, str(cache_dir / uid))]


class TestEndToEndAgainstARealDatabase:
    """The actual failure mode #306 names, driven through the same code
    path a live upload uses.

    ``add_file_series`` writes the manifest to a tempfile; ``database_add``
    copies it into DID's FileDir and removes the source. The recorded
    location is then gone. ``file_uploads_for_document`` with the
    dataset's FileDir in *additional_roots* recovers the manifest by uid
    and yields a ``(uid, cached_path)`` pair the upload can send.
    """

    def test_the_manifest_bytes_are_uploadable_after_ingest(self, tmp_path):
        local = ndi_dataset_dir("test_series_ds", str(tmp_path))
        members_dir = tmp_path / "members"
        members_dir.mkdir()
        member_paths = []
        for i in range(3):
            p = members_dir / f"m_{i + 1}.bin"
            p.write_bytes(bytes((k * (i + 1)) % 251 for k in range(1, 65)))
            member_paths.append(str(p))

        seed = ndi_document(
            "demoNDISeries",
            **{
                "base.name": f"series_doc_{uuid.uuid4().hex[:8]}",
                "demoNDISeries.value": 1,
            },
        )
        did_doc = DIDDocument(seed.document_properties)
        did_doc.add_file_series(SERIES_NAME, member_paths)
        doc = ndi_document(did_doc.document_properties)

        local.database_add(doc)

        # Pull the manifest's uid off the doc so we can prove the cache
        # lookup is what recovered it (rather than an unnoticed leftover
        # at the tempfile path).
        fi = doc.document_properties["files"]["file_info"]
        if isinstance(fi, dict):
            fi = [fi]
        entry = next(e for e in fi if e.get("name") == SERIES_NAME)
        locs = entry.get("locations")
        if isinstance(locs, dict):
            locs = [locs]
        manifest_uid = locs[0]["uid"]
        recorded_path = locs[0]["location"]

        # The recorded location must be gone -- that IS the shape this
        # test exists to prove the fallback survives.
        assert not os.path.exists(recorded_path), (
            "fixture: DID ingest should have removed the manifest tempfile; "
            "if this fires, the failure mode this test targets no longer "
            "reproduces and the test is testing something else."
        )

        roots = _did_file_store_roots(local)
        assert roots, "the local dataset should expose its DID FileDir as a root"
        cached_path = Path(roots[0]) / manifest_uid
        assert cached_path.is_file(), "DID should have copied the manifest into its FileDir"

        pairs = file_uploads_for_document(doc.document_properties, additional_roots=roots)

        # Exactly one pair, and it names the cached path -- so a live
        # ``uploadFilesForDatasetDocuments`` call would send the manifest
        # bytes and the server would have a record of that uid on the
        # dataset. Without this pair, the download side sees "manifest
        # not a file of this dataset" and every member reads as absent.
        assert (manifest_uid, str(cached_path)) in pairs, (
            f"the manifest uid must be uploaded from DID's file cache; " f"pairs were {pairs!r}"
        )

    def test_a_stand_in_dataset_still_uploads_what_it_can(self, tmp_path):
        """``_did_file_store_roots`` reads defensively.

        A caller passing an object that is not a real ``ndi_dataset``
        should not stop the upload of a doc whose recorded location is
        still on disk. Recorded elsewhere in this file that a live
        recorded location is preferred; here we prove the roots resolver
        does not raise on the way to that call.
        """
        assert _did_file_store_roots(None) == []
        assert _did_file_store_roots(object()) == []
