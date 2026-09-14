"""A file series through the cloud and back.

MATLAB counterpart:
    tests/+ndi/+unittest/+cloud/FileSeriesRoundTripTest.m

Builds a ``demoNDISeries`` document with a manifest and several chunk
members, uploads it to a fresh cloud dataset, and reads each member back
out of a fresh download. Two acceptance tests here, one per download mode:

- SyncFiles=true: the manifest bytes come down with the dataset. Members
  are still on the cloud (a series' members are deliberately left there,
  so opening a dataset does not drag down a 28,000-member series), so
  each open goes through the DID ``custom_file_handler`` -- which is what
  makes a member's uid pass through the batch signed-URL cache.

- SyncFiles=false: neither the manifest nor its members come down with
  the dataset. The manifest itself is fetched through the same handler
  now (VH-Lab/DID-python#88 / VH-Lab/DID-matlab#201), and its
  ``ingest_locations`` are rebuilt on the way in by
  :func:`ndi.cloud.filehandler.updateFileInfoForRemoteFiles`
  (VH-Lab/NDI-matlab#988, ported in Waltham-Data-Science/NDI-python#302).
  Both halves have to be working for a member of a series document to
  survive a SyncFiles=false round trip.

Both tests read every member byte-for-byte from the downloaded dataset,
so a transfer that returned the right count with the wrong bytes -- or
swapped two members by a uid mixup -- still fails. Both also insist the
batch signed-URL path answers rather than falling back to per-uid
``getFileDetails``: at 28,000 members that fallback is 28,000 API calls,
and a test that "works" through the fallback would prove nothing about
the path the series design exists to exercise (see NDI-matlab#968).

The offline path is pinned separately (no cloud creds) in
tests/test_cloud_series_reconstruction.py and
tests/test_cloud_series_reconstruction_remote.py; this file exists to
close the gap the closing note on Waltham-Data-Science/NDI-python#300
flagged: a live-cloud test that would have caught the retirement PR's
regression independently of the mocked path.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Skip entire module if no credentials
# ---------------------------------------------------------------------------

_has_creds = bool(os.environ.get("NDI_CLOUD_USERNAME") and os.environ.get("NDI_CLOUD_PASSWORD"))
pytestmark = pytest.mark.skipif(not _has_creds, reason="NDI cloud credentials not set")


MEMBER_COUNT = 4
DATASET_NAME_PREFIX = "NDI_PYTEST_FILE_SERIES_"
SERIES_NAME = "chunkdata.bin"


def _member_content(i: int) -> bytes:
    """Distinguishable content per member.

    All members are the same LENGTH so a length-only comparison would catch
    nothing: two members swapped by a uid mixup -- the failure this path is
    most prone to, since a member is addressed by uid the whole way through
    -- come back the right size and the wrong file. Byte values differ
    across members; the mod-251 keeps them in uint8 range regardless of i.
    """
    return bytes((k * (i + 1)) % 251 for k in range(1, 65))


# ---------------------------------------------------------------------------
# Module-scoped setup: authenticate, upload one series document, tear down
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cloud_client():
    """Authenticate once for the whole module and return an authenticated client.

    Login populates ``NDI_CLOUD_ORGANIZATION_ID`` on the process, so any
    subsequent call that resolves the org id from the environment sees it.
    """
    from ndi.cloud.auth import login
    from ndi.cloud.client import CloudClient
    from ndi.cloud.config import CloudConfig

    config = CloudConfig.from_env()
    config = login(config=config)
    assert config.is_authenticated, "Login failed -- no token received"
    return CloudClient(config)


@pytest.fixture(scope="module")
def uploaded_series(tmp_path_factory, cloud_client):
    """Build a small series document locally, upload it, wait for extraction.

    Yields ``(cloud_id, doc_id, member_uids, member_bytes)``.

    ``member_uids`` is the list of member uids the local manifest was
    written with; ``member_bytes`` is the parallel list of the bytes each
    member was uploaded with. The download tests compare bytes back
    byte-for-byte against ``member_bytes``. A uid mixup on the return
    path would return the right size and the wrong content, so length is
    not enough.

    Registers a cloud-side teardown that deletes the dataset when=now.
    """
    from did.document import Document as DIDDocument

    from ndi.cloud.api import datasets as ds_api
    from ndi.cloud.api.files import waitForAllBulkUploads
    from ndi.cloud.orchestration import uploadDataset
    from ndi.dataset import ndi_dataset_dir
    from ndi.document import ndi_document

    workdir = tmp_path_factory.mktemp("series_round_trip")

    # A local dataset to hold the doc.
    local = ndi_dataset_dir("test_series_ds", str(workdir))

    # Members with distinct bytes on disk.
    members_dir = workdir / "level0"
    members_dir.mkdir()
    member_paths: list[str] = []
    member_bytes: list[bytes] = []
    for i in range(MEMBER_COUNT):
        content = _member_content(i)
        p = members_dir / f"chunk_{i + 1:04d}.bin"
        p.write_bytes(content)
        member_paths.append(str(p))
        member_bytes.append(content)

    # demoNDISeries declares chunkdata.bin as a file series. ndi_document has
    # no add_file_series of its own, so build the file_info / series_info
    # through DIDDocument's helper on the properties dict, then wrap the
    # result back up as an ndi_document for database_add.
    seed = ndi_document(
        "demoNDISeries",
        **{
            "base.name": f"test_series_doc_{uuid.uuid4().hex[:8]}",
            "demoNDISeries.value": 1,
        },
    )
    did_doc = DIDDocument(seed.document_properties)
    did_doc.add_file_series(SERIES_NAME, member_paths)
    doc = ndi_document(did_doc.document_properties)

    local.database_add(doc)
    doc_id = doc.id

    # Read the local manifest and lift its member uids -- those are the ones
    # the SyncFiles=true test expects the downloaded manifest to still name,
    # and the ones every member fetch will go looking for.
    from did.file import read_series_manifest

    handle = local.database_openbinarydoc(doc, SERIES_NAME)
    manifest = read_series_manifest(handle.fullpathfilename)
    member_uids = [u for u in manifest.get("uids", []) if u]
    assert (
        len(member_uids) == MEMBER_COUNT
    ), f"the local manifest names {len(member_uids)} members; expected {MEMBER_COUNT}"

    unique_name = DATASET_NAME_PREFIX + uuid.uuid4().hex
    ok, cloud_id, message = uploadDataset(
        local,
        remote_name=unique_name,
        sync_files=True,
        verbose=False,
        client=cloud_client,
    )
    assert ok, f"uploadDataset failed: {message}"
    assert cloud_id, "uploadDataset returned an empty cloud id"

    # Server-side zip extraction has to finish before anything reads the
    # per-file objects back (NDI-matlab #755 / NDI-python analog): a
    # download that starts before extraction completes may miss files.
    waitForAllBulkUploads(cloud_id, client=cloud_client)

    yield cloud_id, doc_id, member_uids, member_bytes

    # Teardown: delete the cloud dataset. Best effort -- do not raise from
    # here, since a delete failure would mask a real assertion failure in
    # the test that produced it.
    try:
        ds_api.deleteDataset(cloud_id, when="now", client=cloud_client)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Helpers used by both tests
# ---------------------------------------------------------------------------


def _find_series_document(dataset, doc_id):
    """The series document as it comes back from a downloaded dataset."""
    from ndi.query import ndi_query

    results = dataset.database_search(ndi_query("base.id") == doc_id)
    assert len(results) == 1, (
        f"downloaded dataset returned {len(results)} matches for base.id "
        f"{doc_id!r}; expected exactly one"
    )
    return results[0]


def _open_every_member(dataset, doc):
    """Open every ``NAME_i`` member of the series, catching per-slot errors.

    Returns ``(opened, errors, bytes_)``: three lists, one entry per member
    slot. ``opened[i]`` is True/False, ``errors[i]`` names the exception if
    the open failed (empty string otherwise), and ``bytes_[i]`` holds what
    came back (empty bytes if the open failed).

    Each open is caught rather than allowed to throw: letting the first
    failure abort the loop would throw away exactly the slot-by-slot
    picture this test exists to produce. WHICH slots came back separates
    bugs with different owners.
    """
    opened: list[bool] = [False] * MEMBER_COUNT
    errors: list[str] = [""] * MEMBER_COUNT
    bytes_: list[bytes] = [b""] * MEMBER_COUNT
    for i in range(MEMBER_COUNT):
        name = f"{SERIES_NAME}_{i + 1}"
        try:
            handle = dataset.database_openbinarydoc(doc, name)
            bytes_[i] = Path(handle.fullpathfilename).read_bytes()
            opened[i] = True
        except Exception as exc:  # noqa: BLE001
            errors[i] = f"{type(exc).__name__}: {exc}"
    return opened, errors, bytes_


def _slot_list(mask: list[bool]) -> str:
    """Human-readable slot list for a diagnostic, mirroring MATLAB's helper."""
    return "[" + ", ".join(str(i + 1) for i, v in enumerate(mask) if v) + "]"


# ---------------------------------------------------------------------------
# The two acceptance tests
# ---------------------------------------------------------------------------


class TestFileSeriesRoundTrip:
    """A member's bytes make the full round trip through NDI Cloud.

    See VH-Lab/NDI-matlab#966 for why a suite of green tests managed to
    prove nothing about a member's bytes before the round-trip test was
    added on the MATLAB side -- every other test either reads from the
    LOCAL dataset (which no transfer touches) or checks the manifest
    (which is an ordinary document file). A server that accepted the
    member uploads and then dropped, truncated or swapped their bytes
    would pass all of them.
    """

    def test_members_survive_a_download_from_the_cloud(
        self,
        tmp_path,
        uploaded_series,
        cloud_client,
    ):
        """SyncFiles=true. The manifest arrives with its bytes; members
        stay on the cloud until wanted."""
        from ndi.cloud.batch_signed_url import get_default
        from ndi.cloud.orchestration import downloadDataset

        cloud_id, doc_id, member_uids, member_bytes = uploaded_series

        target = tmp_path / "download"
        target.mkdir()
        dataset = downloadDataset(
            cloud_id,
            str(target),
            sync_files=True,
            verbose=False,
            client=cloud_client,
        )
        assert dataset is not None, "downloadDataset returned nothing"

        doc = _find_series_document(dataset, doc_id)

        # The manifest itself came back byte-identical: the same member
        # uids point at the same slots. A manifest that lost or reshuffled
        # uids would resolve every member to the wrong file.
        from did.file import read_series_manifest

        manifest_handle = dataset.database_openbinarydoc(doc, SERIES_NAME)
        downloaded_manifest = read_series_manifest(manifest_handle.fullpathfilename)
        assert downloaded_manifest.get("count") == MEMBER_COUNT
        downloaded_uids = [u for u in downloaded_manifest.get("uids", []) if u]
        assert downloaded_uids == member_uids, (
            "downloaded manifest uids differ from the ones uploaded; a "
            "member would resolve to the wrong file"
        )

        # Clear the batch signed-URL cache so what follows is measured
        # against this test's opens, not against anything a prior test
        # populated. This is what makes the assertion below meaningful --
        # a run of per-uid getFileDetails could quietly do the work
        # otherwise, and the test would pass having proved nothing about
        # the batch presign path. See VH-Lab/NDI-matlab#968.
        get_default().clear()

        opened, errors, member_bytes_back = _open_every_member(dataset, doc)

        assert all(opened), (
            f"a series member of the downloaded dataset could not be "
            f"opened. Opened {sum(opened)}/{MEMBER_COUNT}, "
            f"slots {_slot_list(opened)}. First error: "
            f"{next((e for e in errors if e), '(none)')}"
        )

        # The bytes, member-by-member. Two members swapped by a uid mixup
        # would come back the right size and the wrong file.
        for i in range(MEMBER_COUNT):
            assert member_bytes_back[i] == member_bytes[i], (
                f"member {i + 1} came back from the cloud with different "
                f"bytes than were uploaded"
            )

        # The batch presign path answered every uid. Missing here means
        # the fallback to per-uid getFileDetails did the work -- correct
        # at runtime, exactly wrong for a test of the path this design
        # exists for. A 28,000-member series with uid_misses > 0 costs
        # 28,000 API calls.
        stats = get_default().stats()
        assert stats.uid_misses == 0, (
            f"a member fell back to per-uid getFileDetails. "
            f"Stats: signer_calls={stats.signer_calls}, "
            f"uid_hits={stats.uid_hits}, uid_misses={stats.uid_misses}, "
            f"failure_reason={stats.last_failure_reason!r}"
        )
        assert stats.signer_calls == 1, (
            f"the members of one series should cost ONE presign call: "
            f"the first fetch populates the scope and the rest resolve "
            f"from the in-process cache. Got {stats.signer_calls}."
        )

    def test_members_survive_a_download_from_the_cloud_with_sync_files_false(
        self,
        tmp_path,
        uploaded_series,
        cloud_client,
    ):
        """SyncFiles=false. Neither manifest nor members come down with
        the dataset; both go through the customFileHandler on demand."""
        from ndi.cloud.batch_signed_url import get_default
        from ndi.cloud.orchestration import downloadDataset

        cloud_id, doc_id, member_uids, member_bytes = uploaded_series

        target = tmp_path / "download"
        target.mkdir()
        dataset = downloadDataset(
            cloud_id,
            str(target),
            sync_files=False,
            verbose=False,
            client=cloud_client,
        )
        assert dataset is not None, "downloadDataset returned nothing"

        doc = _find_series_document(dataset, doc_id)

        # Precondition: no member is on this machine yet. The test would
        # still open every member if something quietly installed them,
        # and would say nothing about the path it exists to exercise.
        for i in range(MEMBER_COUNT):
            exists, _ = dataset.database_existbinarydoc(doc_id, f"{SERIES_NAME}_{i + 1}")
            assert not exists, (
                f"precondition: member {i + 1} should not be on this "
                f"machine before the first open (SyncFiles=false)"
            )

        get_default().clear()

        opened, errors, member_bytes_back = _open_every_member(dataset, doc)

        assert all(opened), (
            f"a series member of the SyncFiles=false downloaded dataset "
            f"could not be opened. Opened {sum(opened)}/{MEMBER_COUNT}, "
            f"slots {_slot_list(opened)}. First error: "
            f"{next((e for e in errors if e), '(none)')}"
        )

        for i in range(MEMBER_COUNT):
            assert member_bytes_back[i] == member_bytes[i], (
                f"member {i + 1} came back from a SyncFiles=false cloud "
                f"download with different bytes than were uploaded"
            )

        stats = get_default().stats()
        # uid_misses is pinned tightly; signer_calls is not. SyncFiles=false
        # may reasonably cost one call (a whole-document scope answers both
        # the manifest and the members) or two (manifest first, then a
        # series scope on the first member), and asserting one over the
        # other would guess at a server behaviour this suite does not
        # otherwise cover. See NDI-matlab#988.
        assert stats.uid_misses == 0, (
            f"a manifest or member of a SyncFiles=false download fell "
            f"back to per-uid getFileDetails. "
            f"Stats: signer_calls={stats.signer_calls}, "
            f"uid_hits={stats.uid_hits}, uid_misses={stats.uid_misses}, "
            f"failure_reason={stats.last_failure_reason!r}"
        )
