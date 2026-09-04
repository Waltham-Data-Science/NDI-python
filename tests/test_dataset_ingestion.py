"""``dataset.isIngested`` and ``convertLinkedSessionToIngested``.

Issue #136. Two different methods share the name ``isIngested``:

* ``ndi.session/isIngested`` asks whether ONE session's raw data has been
  ingested. Python has had it (as ``is_fully_ingested``, aliased) for a while.
* ``ndi.dataset/isIngested`` asks whether a DATASET is self-contained -- every
  session in it ingested rather than linked. This one was missing, and its
  absence had a consequence beyond a gap in the API: ``uploadDataset`` is
  supposed to refuse a dataset that is not fully ingested (MATLAB does it
  first thing, ``uploadDataset.m:53``), and Python could not make the check
  because there was nothing to call. Datasets with linked sessions uploaded,
  and whatever lived outside the dataset directory silently did not go.

``convertLinkedSessionToIngested`` is the operation that fixes such a dataset:
it copies a linked session's documents and binary files in, so the dataset
stops depending on the original session path.

The tests run against real sessions, real datasets and real files on disk.
The thing being tested is whether bytes arrive somewhere, and no mock can
answer that -- ``test_converted_session_survives_deleting_the_original`` in
particular deletes the source session and then reads the data back out.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import pytest

import ndi.cloud.orchestration as orch
from ndi.dataset import ndi_dataset_dir
from ndi.dataset._dataset import ndi_dataset as ndi_dataset_base
from ndi.document import ndi_document
from ndi.query import ndi_query
from ndi.session.dir import ndi_session_dir

FILE_SLOT = "filename1.ext"
PAYLOAD = "hello world"


def _add_doc_with_file(session: ndi_session_dir, number: int = 1) -> ndi_document:
    """Add one demoNDI document carrying a real file. Mirrors the MATLAB helper."""
    path = Path(session.path) / f"payload_{number}.txt"
    path.write_text(PAYLOAD)

    doc = ndi_document("demoNDI")
    props = doc.document_properties
    props["base"]["name"] = f"doc_{number}"
    props["demoNDI"]["value"] = number
    props["base"]["session_id"] = session.id()
    doc = ndi_document(props).add_file(FILE_SLOT, str(path))
    session.database_add(doc)
    return doc


@pytest.fixture
def session(tmp_path):
    """A real directory session holding one document with one file."""
    d = tmp_path / "sess"
    d.mkdir()
    s = ndi_session_dir("exp1", d)
    _add_doc_with_file(s)
    return s


@pytest.fixture
def dataset(tmp_path):
    """An empty dataset, ready to have sessions added."""
    d = tmp_path / "ds"
    d.mkdir()
    return ndi_dataset_dir("myds", str(d))


@pytest.fixture
def linked(dataset, session):
    """A dataset with SESSION linked into it -- the state to be converted."""
    dataset.add_linked_session(session)
    return dataset, session


def _session_info(dataset, session_id):
    dataset.build_session_info()
    return dataset._find_session_in_info(session_id)


def _own_doc_count(dataset) -> int:
    """Documents in the DATASET'S OWN database.

    Not ``dataset.database_search``: that spans linked sessions, so a linked
    session's documents are already in its results before anything is copied
    and the total cannot see the copy happen. It is also the weaker check for
    a partial copy -- what "nothing was written" has to mean is that nothing
    landed in the dataset's own store.
    """
    return len(dataset._session._database.search(ndi_query("").isa("base")))


# ======================================================================
# dataset.isIngested
# ======================================================================
class TestDatasetIsIngested:
    """``ndi.dataset/isIngested`` -- the method uploadDataset needs."""

    def test_the_dataset_has_its_own_is_ingested(self):
        """Not inherited, not the session's: the dataset defines its own.

        The gap in issue #136 was exactly this -- ``session.isIngested``
        existed and ``dataset.isIngested`` did not, which made the two look
        like one method that was already present.
        """
        assert "isIngested" in vars(ndi_dataset_base)

    def test_an_empty_dataset_is_ingested(self, dataset):
        """MATLAB says so explicitly (dataset.m:241-247) and it inverts easily.

        "No sessions" is not "nothing has been ingested"; there is nothing
        left outside the dataset, which is what the question means.
        """
        assert dataset.isIngested() is True

    def test_a_linked_but_ingested_session_leaves_the_dataset_ingested(self, linked):
        """A linked session whose own data IS ingested does not fail the check.

        MATLAB asks each session ``S.isIngested()``; it does not ask whether
        the session is linked. Reading the method as "no linked sessions"
        would be wrong, and this is the case that tells the two apart.
        """
        dataset, _session = linked
        assert dataset.isIngested() is True

    def test_a_session_that_is_not_ingested_makes_the_dataset_not_ingested(
        self, linked, monkeypatch
    ):
        """One un-ingested session is enough -- this is the upload gate's job."""
        dataset, _session = linked
        monkeypatch.setattr(ndi_session_dir, "isIngested", lambda self: False)
        assert dataset.isIngested() is False

    def test_an_unopenable_session_counts_as_not_ingested(self, linked, caplog):
        """A session nobody can read must not be reported as ingested.

        MATLAB never faces this: its ``open_session`` raises. Python's returns
        None, and answering True would let a dataset whose data cannot be
        found upload as if it were complete. It is reported, not swallowed.
        """
        dataset, _session = linked
        dataset.open_session = lambda session_id: None  # type: ignore[method-assign]

        with caplog.at_level(logging.WARNING, logger="ndi.dataset._dataset"):
            result = dataset.isIngested()

        assert result is False
        assert "could not be opened" in caplog.text

    def test_snake_case_alias_is_the_same_method(self):
        assert ndi_dataset_base.is_ingested is ndi_dataset_base.isIngested


# ======================================================================
# dataset.convertLinkedSessionToIngested
# ======================================================================
class TestConvertLinkedSessionToIngested:
    """Copying a linked session's data into the dataset."""

    def test_the_session_becomes_ingested(self, linked):
        dataset, session = linked
        assert _session_info(dataset, session.id())["is_linked"] is True

        dataset.convertLinkedSessionToIngested(session.id(), are_you_sure=True)

        info = _session_info(dataset, session.id())
        assert info["is_linked"] is False

    def test_the_stored_session_path_is_cleared(self, linked):
        """The whole point: the dataset must stop pointing at the old path.

        MATLAB clears ``session_creator_input2`` for the same reason
        (dataset.m:487), so ``open_session`` reads from the dataset.
        """
        dataset, session = linked
        dataset.convertLinkedSessionToIngested(session.id(), are_you_sure=True)

        info = _session_info(dataset, session.id())
        assert info["session_creator_input2"] == ""

        reopened = dataset.open_session(session.id())
        assert Path(reopened.path) == Path(dataset.getpath())

    def test_the_documents_come_across(self, linked):
        """They must land in the dataset's own store, not just be reachable.

        Before the conversion the session's documents already answer a
        ``dataset.database_search`` -- through the link. What changes is where
        they live, so that is what is asserted.
        """
        dataset, session = linked
        before = _own_doc_count(dataset)

        dataset.convertLinkedSessionToIngested(session.id(), are_you_sure=True)

        assert _own_doc_count(dataset) > before
        own = dataset._session._database.search(ndi_query("base.session_id") == session.id())
        assert own, "no document from the session reached the dataset's own database"

    def test_converted_session_survives_deleting_the_original(self, linked, tmp_path):
        """THE POINT: self-contained means the source can go away.

        Copying the documents but not the binaries would pass every assertion
        above and fail here, which is why this test deletes the session
        directory outright and then reads the file back out of a freshly
        opened dataset.
        """
        dataset, session = linked
        doc_id = dataset.database_search(ndi_query("").isa("demoNDI"))[0].id
        session_path = Path(session.path)
        dataset_path = Path(dataset.getpath())

        dataset.convertLinkedSessionToIngested(session.id(), are_you_sure=True)

        del dataset, session
        shutil.rmtree(session_path)
        assert not session_path.exists()

        reopened = ndi_dataset_dir("myds", str(dataset_path))
        found, resolved = reopened._session._database.exist_binary(doc_id, FILE_SLOT)
        assert found, "the binary file did not come across; the dataset is not self-contained"
        assert Path(resolved).read_text() == PAYLOAD

    # -- the gates ----------------------------------------------------
    def test_it_refuses_without_are_you_sure(self, linked):
        dataset, session = linked
        with pytest.raises(ValueError, match="are_you_sure"):
            dataset.convertLinkedSessionToIngested(session.id())

        assert _session_info(dataset, session.id())["is_linked"] is True

    def test_an_unconfirmed_call_copies_nothing(self, linked):
        """Refusing after a partial copy would be worse than not refusing."""
        dataset, session = linked
        before = _own_doc_count(dataset)

        with pytest.raises(ValueError):
            dataset.convertLinkedSessionToIngested(session.id())

        assert _own_doc_count(dataset) == before

    def test_an_unknown_session_is_rejected(self, dataset):
        with pytest.raises(ValueError, match="not found"):
            dataset.convertLinkedSessionToIngested("no_such_id", are_you_sure=True)

    def test_an_already_ingested_session_is_rejected(self, dataset, session):
        """MATLAB raises here too (dataset.m:424); converting twice is a no-op
        at best and a duplicate copy at worst."""
        dataset.add_ingested_session(session)

        with pytest.raises(ValueError, match="already an INGESTED session"):
            dataset.convertLinkedSessionToIngested(session.id(), are_you_sure=True)

    def test_a_session_that_is_not_ingested_is_rejected(self, linked, monkeypatch):
        """A session still reading raw files has nothing to copy.

        MATLAB requires ``S.isIngested()`` before converting (dataset.m:433),
        and the ordering in the issue follows from it: isIngested first.
        """
        dataset, session = linked
        monkeypatch.setattr(ndi_session_dir, "isIngested", lambda self: False)
        before = _own_doc_count(dataset)

        with pytest.raises(ValueError, match="not yet fully ingested"):
            dataset.convertLinkedSessionToIngested(session.id(), are_you_sure=True)

        assert _own_doc_count(dataset) == before
        assert _session_info(dataset, session.id())["is_linked"] is True

    def test_snake_case_alias_is_the_same_method(self):
        assert (
            ndi_dataset_base.convert_linked_session_to_ingested
            is ndi_dataset_base.convertLinkedSessionToIngested
        )


# ======================================================================
# The disk-space precheck -- an addition, not a port
# ======================================================================
class TestDiskSpacePrecheck:
    """MATLAB documents the ~2x disk requirement and checks nothing.

    Running out of space part way through leaves the dataset holding some of
    the session's documents under a record that still says ``linked`` -- a
    state no later call repairs. Checking first turns that into a refusal.
    """

    def test_it_refuses_when_the_copy_would_not_fit(self, linked, monkeypatch):
        dataset, session = linked
        monkeypatch.setattr(shutil, "disk_usage", lambda _p: shutil._ntuple_diskusage(1, 1, 0))

        with pytest.raises(OSError, match="Not enough free space"):
            dataset.convertLinkedSessionToIngested(session.id(), are_you_sure=True)

    def test_a_refused_copy_writes_nothing(self, linked, monkeypatch):
        """The reason the check exists: no half-converted dataset."""
        dataset, session = linked
        before = _own_doc_count(dataset)
        monkeypatch.setattr(shutil, "disk_usage", lambda _p: shutil._ntuple_diskusage(1, 1, 0))

        with pytest.raises(OSError):
            dataset.convertLinkedSessionToIngested(session.id(), are_you_sure=True)

        assert _own_doc_count(dataset) == before
        assert _session_info(dataset, session.id())["is_linked"] is True

    def test_it_measures_the_session_files(self, linked):
        """The estimate is the session's ingested bytes, not a guess."""
        dataset, session = linked
        measured = dataset._session_file_bytes(session)
        assert measured == len(PAYLOAD)

    def test_an_unmeasurable_session_does_not_block_the_copy(self, linked, monkeypatch):
        """A check that cannot be made must not become a new way to fail."""
        dataset, session = linked
        monkeypatch.setattr(ndi_dataset_base, "_session_file_bytes", staticmethod(lambda _s: None))

        dataset.convertLinkedSessionToIngested(session.id(), are_you_sure=True)

        assert _session_info(dataset, session.id())["is_linked"] is False


# ======================================================================
# uploadDataset's gate
# ======================================================================
class FakeClient:
    class config:
        org_id = "org"


class TestUploadDatasetRefusesUningestedDatasets:
    """MATLAB checks this first (uploadDataset.m:53). Python could not."""

    @pytest.fixture
    def captured(self, monkeypatch):
        import ndi.cloud.api.datasets as ds_api
        import ndi.cloud.upload as upload_mod

        box: dict = {"docs": None, "created": 0}

        def create_dataset(org, name, client=None):
            box["created"] += 1
            return {"id": f"CLOUD-{box['created']}"}

        def upload_docs(cloud_id, doc_jsons, client=None, **kw):
            box["docs"] = doc_jsons
            return {"uploaded": len(doc_jsons), "skipped": 0}

        monkeypatch.setattr(ds_api, "createDataset", create_dataset)
        monkeypatch.setattr(upload_mod, "uploadDocumentCollection", upload_docs)
        return box

    def test_an_uningested_dataset_is_refused(self, linked, captured, monkeypatch):
        dataset, _session = linked
        monkeypatch.setattr(ndi_session_dir, "isIngested", lambda self: False)

        ok, cloud_id, message = orch.uploadDataset(dataset, sync_files=False, client=FakeClient())

        assert ok is False
        assert cloud_id == ""
        assert "not fully ingested" in message

    def test_nothing_is_sent_and_no_remote_dataset_is_created(self, linked, captured, monkeypatch):
        """The refusal has to happen BEFORE the remote dataset exists.

        Creating it and then bailing would leave an empty dataset on NDI Cloud
        and a local link pointing at it -- worse than the upload it prevents.
        """
        dataset, _session = linked
        monkeypatch.setattr(ndi_session_dir, "isIngested", lambda self: False)

        orch.uploadDataset(dataset, sync_files=False, client=FakeClient())

        assert captured["docs"] is None
        assert captured["created"] == 0
        assert dataset.is_in_cloud() == (False, "")

    def test_an_ingested_dataset_still_uploads(self, linked, captured):
        """Guards the gate against over-firing: this one must go through."""
        dataset, _session = linked
        assert dataset.isIngested() is True

        ok, _cloud_id, _message = orch.uploadDataset(dataset, sync_files=False, client=FakeClient())

        assert ok is True
        assert captured["docs"], "the gate blocked a dataset that is fully ingested"

    def test_a_dataset_without_the_method_is_not_blocked(self, captured, tmp_path):
        """uploadDataset takes Any; a stand-in dataset keeps working."""

        class MinimalDataset:
            def __init__(self):
                self.docs = []

            def database_search(self, _q):
                return []

            def database_add(self, doc):
                self.docs.append(doc)
                return self

        ok, _cloud_id, _message = orch.uploadDataset(
            MinimalDataset(), sync_files=False, client=FakeClient()
        )
        assert ok is True
