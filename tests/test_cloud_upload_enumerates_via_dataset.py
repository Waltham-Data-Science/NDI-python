"""``file_uploads_for_document`` asks the dataset where its binaries live.

TWO CONCERNS, one MATLAB counterpart.

1. A series manifest is written by ``did.document.Document.add_file_series``
   to ``tempfile.NamedTemporaryFile(prefix="did_manifest_")``, and
   ``add_file`` with the default ``delete_original=True`` removes that
   source once DID has ingested it. The doc's authoring record
   (``files.file_info[].locations[].location``) still names the tempfile,
   so a caller reading only that record uploads nothing for the manifest.
   Run 227 on TEST_USER_1 caught it (Waltham-Data-Science/NDI-python#306).

2. A series' MEMBERS have no ``file_info`` entry at all. They are named
   ``NAME_i`` for ``i in 1..series_info[k].count`` and their bytes live at
   ``<FileDir>/<member_uid>``. A caller that walks only ``file_info`` never
   sees any of them, so an upload that took the recorded-location path
   sent zero member files whichever way the manifest went.

NDI-matlab's ``+ndi/+database/+internal/list_binary_files.m`` handles
both by calling ``dataset.database_existbinarydoc(doc_id, filename)`` for
each name -- that is DID's storage-side ``exist_doc``, which knows where
the bytes actually live -- and by iterating ``series_info(k).count`` to
generate member names. This test pins the Python counterpart:
``file_uploads_for_document(doc, dataset=<real dataset>)`` produces the
same pairs on the same shapes.

Live-cloud coverage of the whole round trip is
``tests/test_cloud_file_series_round_trip.py``; this file is the offline
half, no credentials required.
"""

from __future__ import annotations

import os
import uuid

from did.document import Document as DIDDocument

from ndi.cloud.upload import file_uploads_for_document
from ndi.dataset import ndi_dataset_dir
from ndi.document import ndi_document

SERIES_NAME = "chunkdata.bin"
MEMBER_COUNT = 4


class _DatasetStub:
    """A minimal stand-in for :class:`ndi.dataset` -- one method, a routing
    table from ``(doc_id, filename)`` to ``(exists, path_or_None)``.

    The tests that use it don't need DID; they need to prove that the
    enumerator asks ``database_existbinarydoc`` for the right names in the
    right order, and passes its answers through. A real dataset covers the
    end-to-end shape below.
    """

    def __init__(self, table):
        self._table = dict(table)
        self.calls: list[tuple[str, str]] = []

    def database_existbinarydoc(self, doc_id, filename):
        self.calls.append((doc_id, filename))
        return self._table.get((doc_id, filename), (False, None))


def _series_doc_bare(doc_id, series_name, count):
    """A doc dict shaped like an ingested series -- names only, no live paths.

    ``file_info`` names the manifest. ``series_info`` records ``count``.
    Nothing here says where any of it lives; that is the dataset's job.
    """
    return {
        "base": {"id": doc_id},
        "files": {
            "file_info": [
                {
                    "name": series_name,
                    "locations": [{"uid": "manifest-uid", "location": "/gone/manifest"}],
                }
            ],
            "series_info": [
                {"name": series_name, "count": count},
            ],
        },
    }


class TestTheDatasetIsAsked:
    """The point of the reshape: ``database_existbinarydoc`` is the source
    of truth. Ordinary files come from ``file_info[].name``; series members
    come from ``series_info[k].count``, one-based."""

    def test_the_manifest_name_is_looked_up_by_database_existbinarydoc(self, tmp_path):
        doc = _series_doc_bare("doc1", SERIES_NAME, count=0)
        cached = tmp_path / "manifest-uid"
        cached.write_bytes(b"manifest bytes")
        stub = _DatasetStub({("doc1", SERIES_NAME): (True, str(cached))})

        pairs = file_uploads_for_document(doc, dataset=stub)

        assert pairs == [("manifest-uid", str(cached))]
        assert stub.calls == [("doc1", SERIES_NAME)]

    def test_series_members_are_enumerated_from_series_info_count(self, tmp_path):
        doc = _series_doc_bare("doc1", SERIES_NAME, count=MEMBER_COUNT)
        # Manifest present, plus one file per member slot.
        table = {("doc1", SERIES_NAME): (True, str(tmp_path / "manifest-uid"))}
        (tmp_path / "manifest-uid").write_bytes(b"m")
        for i in range(1, MEMBER_COUNT + 1):
            uid = f"member-{i}-uid"
            (tmp_path / uid).write_bytes(b"m")
            table[("doc1", f"{SERIES_NAME}_{i}")] = (True, str(tmp_path / uid))
        stub = _DatasetStub(table)

        pairs = file_uploads_for_document(doc, dataset=stub)

        # Manifest first (from file_info), then members in slot order.
        assert pairs == [
            ("manifest-uid", str(tmp_path / "manifest-uid")),
            ("member-1-uid", str(tmp_path / "member-1-uid")),
            ("member-2-uid", str(tmp_path / "member-2-uid")),
            ("member-3-uid", str(tmp_path / "member-3-uid")),
            ("member-4-uid", str(tmp_path / "member-4-uid")),
        ]
        # Slot names are one-based, as in DID's series API.
        assert stub.calls == [
            ("doc1", SERIES_NAME),
            ("doc1", f"{SERIES_NAME}_1"),
            ("doc1", f"{SERIES_NAME}_2"),
            ("doc1", f"{SERIES_NAME}_3"),
            ("doc1", f"{SERIES_NAME}_4"),
        ]

    def test_a_sparse_series_skips_absent_slots(self, tmp_path):
        """A sparse series is the case the mechanism exists for (gene
        pyramids write tiles 1, 4, 9, ...). An absent slot is normal;
        producing no pair for it is the right answer, not an error."""
        doc = _series_doc_bare("doc1", SERIES_NAME, count=3)
        (tmp_path / "manifest-uid").write_bytes(b"m")
        (tmp_path / "member-2-uid").write_bytes(b"m")
        stub = _DatasetStub(
            {
                ("doc1", SERIES_NAME): (True, str(tmp_path / "manifest-uid")),
                # slot 1: absent
                ("doc1", f"{SERIES_NAME}_2"): (True, str(tmp_path / "member-2-uid")),
                # slot 3: absent
            }
        )

        pairs = file_uploads_for_document(doc, dataset=stub)

        assert pairs == [
            ("manifest-uid", str(tmp_path / "manifest-uid")),
            ("member-2-uid", str(tmp_path / "member-2-uid")),
        ]

    def test_uid_is_the_basename_of_the_stored_path(self, tmp_path):
        """DID's file store keys files by uid at ``<FileDir>/<uid>``.
        ``exist_doc`` returns that path; the uid is its basename.
        NDI-matlab's ``list_binary_files.m`` does the same
        (``fileparts(full_file_path)``)."""
        doc = {
            "base": {"id": "doc1"},
            "files": {"file_info": [{"name": "plain.bin", "locations": []}]},
        }
        stored = tmp_path / "abc123def"
        stored.write_bytes(b"x")
        stub = _DatasetStub({("doc1", "plain.bin"): (True, str(stored))})

        pairs = file_uploads_for_document(doc, dataset=stub)

        assert pairs == [("abc123def", str(stored))]

    def test_matlab_shaped_single_element_dicts_still_work(self, tmp_path):
        """MATLAB's ``jsonencode`` writes a one-element struct array as a
        bare object. The enumerator has to normalise both ``file_info`` and
        ``series_info`` for that case, or a series-of-one gets skipped."""
        doc = {
            "base": {"id": "doc1"},
            "files": {
                # Single-element -> bare object, not a list.
                "file_info": {
                    "name": SERIES_NAME,
                    "locations": {"uid": "manifest-uid", "location": "/gone"},
                },
                "series_info": {"name": SERIES_NAME, "count": 1},
            },
        }
        (tmp_path / "manifest-uid").write_bytes(b"m")
        (tmp_path / "member-1-uid").write_bytes(b"m")
        stub = _DatasetStub(
            {
                ("doc1", SERIES_NAME): (True, str(tmp_path / "manifest-uid")),
                ("doc1", f"{SERIES_NAME}_1"): (True, str(tmp_path / "member-1-uid")),
            }
        )

        pairs = file_uploads_for_document(doc, dataset=stub)

        assert pairs == [
            ("manifest-uid", str(tmp_path / "manifest-uid")),
            ("member-1-uid", str(tmp_path / "member-1-uid")),
        ]

    def test_a_doc_with_no_id_yields_nothing(self):
        """``database_existbinarydoc`` needs an id; without one the
        enumerator declines rather than probing for the empty string."""
        doc = _series_doc_bare("", SERIES_NAME, count=1)
        stub = _DatasetStub({})

        assert file_uploads_for_document(doc, dataset=stub) == []
        assert stub.calls == []


class TestTheRawDictFallback:
    """A raw dict without a dataset keeps the pre-#306 shape: read the
    authoring record and skip anything gone. It never covers series members
    (they have no ``file_info`` entry) -- but nothing was covering them
    before either, and the dataset path is what does now."""

    def test_a_live_recorded_location_is_returned(self, tmp_path):
        live = tmp_path / "live.bin"
        live.write_bytes(b"x")
        doc = {
            "files": {
                "file_info": [
                    {"name": "live.bin", "locations": [{"uid": "u", "location": str(live)}]}
                ]
            }
        }
        assert file_uploads_for_document(doc) == [("u", str(live))]

    def test_a_gone_location_is_skipped(self, tmp_path):
        doc = {
            "files": {
                "file_info": [
                    {
                        "name": "gone.bin",
                        "locations": [{"uid": "u", "location": str(tmp_path / "gone")}],
                    }
                ]
            }
        }
        assert file_uploads_for_document(doc) == []

    def test_the_manifest_top_level_shape_still_works(self, tmp_path):
        path = tmp_path / "m.bin"
        path.write_bytes(b"x")
        doc = {"file_uid": "u", "file_path": str(path)}
        assert file_uploads_for_document(doc) == [("u", str(path))]

    def test_a_stub_without_database_existbinarydoc_falls_back(self, tmp_path):
        """A caller that hands an object which is not a real dataset should
        get the raw-dict behaviour, not a raise. Guards against a caller
        forgetting to pass the real dataset and getting silence instead of
        the fallback."""
        live = tmp_path / "live.bin"
        live.write_bytes(b"x")
        doc = {
            "files": {
                "file_info": [
                    {"name": "live.bin", "locations": [{"uid": "u", "location": str(live)}]}
                ]
            }
        }
        assert file_uploads_for_document(doc, dataset=object()) == [("u", str(live))]


class TestEndToEndAgainstARealDataset:
    """The actual failure mode #306 names, driven through the shape a live
    upload takes: build a series doc, ingest it into a real dataset, and
    ask the enumerator for its pairs. Both the manifest AND every member
    must appear, keyed by the uids DID assigned them."""

    def test_a_series_doc_yields_manifest_and_all_members(self, tmp_path):
        local = ndi_dataset_dir("test_series_ds", str(tmp_path))
        members_dir = tmp_path / "members"
        members_dir.mkdir()
        member_paths = []
        for i in range(MEMBER_COUNT):
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

        # The recorded manifest location must be gone -- that IS the shape
        # this test exists to prove the enumerator survives. Read it back
        # from the doc as stored and check.
        stored = local.database_search(None)
        stored_doc = next(d for d in stored if d.id == doc.id)
        fi = stored_doc.document_properties["files"]["file_info"]
        if isinstance(fi, dict):
            fi = [fi]
        manifest_entry = next(e for e in fi if e.get("name") == SERIES_NAME)
        locs = manifest_entry.get("locations")
        if isinstance(locs, dict):
            locs = [locs]
        recorded = locs[0].get("location", "")
        assert not os.path.exists(recorded), (
            "fixture: DID ingest should have removed the manifest tempfile; "
            "if this fires, the failure mode this test targets no longer "
            "reproduces and the test is testing something else."
        )

        pairs = file_uploads_for_document(stored_doc.document_properties, dataset=local)

        # One pair for the manifest, one per member. Every uid resolves to a
        # file under DID's FileDir -- so a live
        # ``uploadFilesForDatasetDocuments`` call would send the manifest
        # bytes and every member's bytes, keyed by their uids, and the
        # download side finds each one where it looks.
        assert (
            len(pairs) == MEMBER_COUNT + 1
        ), f"expected manifest + {MEMBER_COUNT} members; got {pairs!r}"
        for uid, path in pairs:
            assert uid, f"a pair with no uid: ({uid!r}, {path!r})"
            assert os.path.isfile(
                path
            ), f"pair points at a path that does not exist: ({uid!r}, {path!r})"
            # uid is the basename of the storage-side path -- DID keys by uid.
            assert os.path.basename(path) == uid
