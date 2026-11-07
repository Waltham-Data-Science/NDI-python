"""Tests for ndi.cloud.session_writer.SessionWriter against a fake cloud dataset.

MATLAB counterparts: tests/+ndi/+unittest/SessionWriterMockTest.m,
tests/+ndi/+unittest/CurlSenderOfflineTest.m and the fake
tests/+ndi/+test/+helper/FakeCloudDataset.m, mirrored here. The fake answers
SessionWriter's calls (SessionWriter.defaultApi) the way NDI Cloud does, and
can be made to fail the ways a live server cannot be made to on demand.

The last part tests the pieces behind the default API with the cloud
functions monkeypatched: ThreadSender (MATLAB's CurlSender, sent from a
thread pool with a fake HTTP session) and signedUploadURLs.
"""

from __future__ import annotations

import copy
import os
import shutil
import threading
import zipfile

import pytest
from did.datastructures import field_search
from did.document import Document

from ndi.cloud import session_writer as sw_mod
from ndi.cloud.session_writer import SessionWriter, SessionWriterError, ThreadSender
from ndi.document import ndi_document
from ndi.fun.file import crc32
from ndi.query import ndi_query

# ---------------------------------------------------------------------------
# The fake cloud (MATLAB: ndi.test.helper.FakeCloudDataset)
# ---------------------------------------------------------------------------


class _Sender:
    def __init__(self, fn):
        self._fn = fn

    def wait(self, *args):
        return self._fn()


class FakeCloudDataset:
    """An in-memory NDI Cloud dataset.

    Faults: CorruptOnce / CorruptAlways (uids stored wrong), RecordCrc
    (False: report no crc32), FailAdd, FailLookups (next N lookups fail),
    LoseAddReply, DeferSends (a background send stores on wait),
    FailSends, FailFirstSends (N), RecordLate (next N lookups report
    nothing uploaded).
    """

    DatasetId = "aaaaaaaaaaaaaaaaaaaaaaaa"

    def __init__(self, folder):
        self.fileDir = str(folder)
        os.makedirs(self.fileDir, exist_ok=True)
        self.docs: list[dict] = []
        self.CorruptOnce: list[str] = []
        self.CorruptAlways: list[str] = []
        self.RecordCrc = True
        self.FailAdd = False
        self.FailLookups = 0
        self.LoseAddReply = False
        self.DeferSends = False
        self.FailSends = False
        self.FailFirstSends = 0
        self.RecordLate = 0
        self.singleUploads = 0
        self.waitedFor: list[list[str]] = []
        self.batchUploads = 0
        self.backgroundSends = 0
        self.backgroundFiles = 0
        self.zipSends = 0
        self.urlBatches = 0
        self.addedJson: list[dict] = []

    def addSession(self, reference):
        d = ndi_document("session_in_a_dataset")
        sid = ndi_document("base").id
        d.document_properties["session_in_a_dataset"] = {
            "session_id": sid,
            "session_reference": reference,
            "is_linked": 0,
            "session_creator": "ndi.session.dir",
        }
        self.docs.append(d.document_properties)
        return sid

    def addSubject(self, sessionId, localIdentifier):
        d = ndi_document(
            "subject",
            **{"base.session_id": sessionId, "subject.local_identifier": localIdentifier},
        )
        self.docs.append(d.document_properties)
        return d.id

    def api(self):
        return {
            "findDocuments": self.findDocuments,
            "addDocument": self.addDocument,
            "uploadSingleFile": self.uploadSingleFile,
            "uploadFileBatch": self.uploadFileBatch,
            "uploadURL": self.uploadURL,
            "startSend": self.startSend,
            "uploadURLs": self.uploadURLs,
            "startZipSend": self.startZipSend,
            "waitForFileUpload": self.waitForFileUpload,
            "lookupFiles": self.lookupFiles,
            "downloadFile": self.downloadFile,
            "updateDocument": self.updateDocument,
        }

    def findDocuments(self, _d, q):
        ss = q.to_search_structure()
        return [d for d in self.docs if field_search(d, ss)]

    def docsOfClass(self, className):
        return self.findDocuments("", ndi_query("", "isa", className))

    def addDocument(self, _d, props):
        if self.FailAdd:
            return False, {"message": "refused by the fake"}
        self.addedJson.append(copy.deepcopy(props))
        self.docs.append(copy.deepcopy(props))
        if self.LoseAddReply:
            self.LoseAddReply = False
            return False, {"message": "connection reset (fake)"}
        return True, {"id": "fake"}

    def updateDocument(self, _d, ndiId, props):
        for i, d in enumerate(self.docs):
            if d["base"]["id"] == ndiId:
                self.docs[i] = copy.deepcopy(props)
                return True, {"id": "fake"}
        return False, {"message": "no such document in the fake"}

    def hasDocument(self, ndiId):
        return any(d["base"]["id"] == ndiId for d in self.docs)

    def uploadSingleFile(self, _d, uid, p):
        self.singleUploads += 1
        self._store(uid, p)
        return True, ""

    def uploadFileBatch(self, _d, paths, _bytes):
        self.batchUploads += 1
        for p in paths:
            self._store(os.path.basename(p), p)
        return True, ""

    def uploadURL(self, _d, uid, _crc):
        return True, f"https://fake.invalid/upload/{uid}"

    def uploadURLs(self, d, uids, crcs, _folder, _n):
        self.urlBatches += 1
        return True, [self.uploadURL(d, u, c)[1] for u, c in zip(uids, crcs)], ""

    def startZipSend(self, _d, uids, paths, _folder):
        self.zipSends += 1
        sender = self.startSend([], paths, [], uids, "", 1)
        self.backgroundSends -= 1
        return sender

    def startSend(self, _urls, paths, _crcs, uids, _folder, _n):
        self.backgroundSends += 1
        uids, paths = list(uids), list(paths)
        if self.FailSends:
            return _Sender(lambda: (False, "send failed (fake)", uids))
        if self.FailFirstSends > 0:
            k = min(self.FailFirstSends, len(uids))
            self._finishSend(uids[k:], paths[k:])
            return _Sender(lambda: (False, "send failed (fake)", uids[:k]))
        if self.DeferSends:
            return _Sender(lambda: self._finishSend(uids, paths))
        self._finishSend(uids, paths)
        return _Sender(lambda: (True, "", []))

    def _finishSend(self, uids, paths):
        for u, p in zip(uids, paths):
            if os.path.isfile(p):
                self._store(u, p)
                self.backgroundFiles += 1
        return True, "", []

    def waitForFileUpload(self, _d, uids, _t):
        self.waitedFor.append(list(uids))
        return True, {"state": "complete"}

    def lookupFiles(self, _d, uids):
        if self.FailLookups > 0:
            self.FailLookups -= 1
            return False, {"message": "network unreachable (fake)"}
        rows, missing = [], []
        for u in uids:
            p = os.path.join(self.fileDir, u)
            if not os.path.isfile(p):
                missing.append(u)
                continue
            rows.append(
                {
                    "uid": u,
                    "uploaded": True,
                    "size": os.path.getsize(p),
                    "crc32": crc32(p) if self.RecordCrc else None,
                }
            )
        if self.RecordLate > 0:
            self.RecordLate -= 1
            for r in rows:
                r["uploaded"] = False
        return True, {"files": rows, "missing": missing}

    def downloadFile(self, _d, uid, p):
        src = os.path.join(self.fileDir, uid)
        if not os.path.isfile(src):
            return False, "no such file"
        shutil.copyfile(src, p)
        return True, ""

    def hasFile(self, uid):
        return os.path.isfile(os.path.join(self.fileDir, uid))

    def fileBytes(self, uid):
        with open(os.path.join(self.fileDir, uid), "rb") as f:
            return f.read()

    def _store(self, uid, p):
        dest = os.path.join(self.fileDir, uid)
        shutil.copyfile(p, dest)
        if uid in self.CorruptOnce or uid in self.CorruptAlways:
            with open(dest, "ab") as f:
                f.write(b"\xff")
            if uid in self.CorruptOnce:
                self.CorruptOnce.remove(uid)


# ---------------------------------------------------------------------------
# Fixtures and builders
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_sleeping(monkeypatch):
    monkeypatch.setattr(sw_mod, "_sleep", lambda s: None)


@pytest.fixture
def cloud(tmp_path):
    c = FakeCloudDataset(tmp_path / "cloud")
    c.sessionId = c.addSession("exp1")
    c.subjectId = c.addSubject(c.sessionId, "mouse1@lab")
    return c


@pytest.fixture
def make_writer(cloud, tmp_path):
    made = []

    def make(**kw):
        opts = {"api": cloud.api(), "verbose": False, "retrySeconds": 0, "zipBatches": False}
        opts.setdefault("cacheDir", str(tmp_path / f"cache{len(made)}"))
        opts.update(kw)
        w = SessionWriter(cloud.DatasetId, cloud.sessionId, **opts)
        made.append(w)
        return w

    yield make
    for w in made:
        w.delete()


@pytest.fixture
def series_doc(tmp_path):
    counter = [0]

    def make(W, subjectId, n):
        """A lightsheetZarrLevel with an N-member chunk.bin series of random bytes."""
        counter[0] += 1
        src = tmp_path / f"src{counter[0]}"
        src.mkdir()
        paths, data = [], []
        for i in range(1, n + 1):
            b = os.urandom(100 + i)
            p = src / f"chunk_{i}"
            p.write_bytes(b)
            paths.append(str(p))
            data.append(b)
        d = W.newdocument("lightsheetZarrLevel")
        d.set_dependency_value("subject_id", subjectId)
        dd = Document(d.document_properties)
        dd.add_file_series("chunk.bin", paths, indices=list(range(1, n + 1)))
        return ndi_document(dd.document_properties), data

    return make


def locs_of(d):
    return d.document_properties["files"]["series_info"][0]["ingest_locations"]


def manifest_uid(d):
    return d.document_properties["files"]["file_info"][0]["locations"][0]["uid"]


# ---------------------------------------------------------------------------
# Sessions and subjects
# ---------------------------------------------------------------------------


def test_a_session_not_in_the_dataset_is_refused(cloud):
    with pytest.raises(SessionWriterError) as e:
        SessionWriter(cloud.DatasetId, "not_a_session", api=cloud.api(), verbose=False)
    assert e.value.identifier == "NDI:cloud:SessionWriter:noSuchSession"


def test_lists_sessions_and_their_subjects(cloud):
    other = cloud.addSession("exp2")
    cloud.addSubject(other, "mouse2@lab")
    s = SessionWriter.listSessions(cloud.DatasetId, api=cloud.api())
    assert sorted(x["session_reference"] for x in s) == ["exp1", "exp2"]
    subj = SessionWriter.listSubjects(cloud.DatasetId, cloud.sessionId, api=cloud.api())
    assert [x["local_identifier"] for x in subj] == ["mouse1@lab"]
    assert subj[0]["id"] == cloud.subjectId


def test_new_documents_belong_to_the_cloud_session(cloud, make_writer):
    W = make_writer()
    assert W.id() == cloud.sessionId
    d = W.newdocument("base", **{"base.name": "x"})
    assert isinstance(d, ndi_document)
    assert d.document_properties["base"]["session_id"] == cloud.sessionId
    assert d.document_properties["base"]["name"] == "x"


def test_require_subject_checks_the_session(cloud, make_writer):
    W = make_writer()
    W.requireSubject(cloud.subjectId)
    other = cloud.addSession("exp2")
    elsewhere = cloud.addSubject(other, "mouse2@lab")
    with pytest.raises(SessionWriterError) as e:
        W.requireSubject(elsewhere)
    assert e.value.identifier == "NDI:cloud:SessionWriter:subjectInOtherSession"
    with pytest.raises(SessionWriterError) as e:
        W.requireSubject("nobody")
    assert e.value.identifier == "NDI:cloud:SessionWriter:noSubject"
    with pytest.raises(SessionWriterError) as e:
        W.requireDocument("nothing")
    assert e.value.identifier == "NDI:cloud:SessionWriter:missingDependency"


def test_a_document_on_another_sessions_subject_is_refused(cloud, make_writer, series_doc):
    W = make_writer()
    other = cloud.addSession("exp2")
    elsewhere = cloud.addSubject(other, "mouse2@lab")
    d, _ = series_doc(W, elsewhere, 3)
    with pytest.raises(SessionWriterError) as e:
        W.database_add(d)
    assert e.value.identifier == "NDI:cloud:SessionWriter:subjectInOtherSession"
    assert cloud.singleUploads == 0 and cloud.backgroundSends == 0


def test_a_document_of_another_session_is_refused(make_writer):
    W = make_writer()
    d = ndi_document("base", **{"base.session_id": "some_other_session"})
    with pytest.raises(SessionWriterError) as e:
        W.database_add(d)
    assert e.value.identifier == "NDI:cloud:SessionWriter:wrongSession"


# ---------------------------------------------------------------------------
# database_add / commit
# ---------------------------------------------------------------------------


def test_files_go_first_and_documents_wait_for_commit(cloud, make_writer, series_doc):
    W = make_writer()
    d, data = series_doc(W, cloud.subjectId, 3)
    W.database_add(d)
    assert cloud.docsOfClass("lightsheetZarrLevel") == [], "the document waits for commit"
    for L in locs_of(d):
        assert cloud.fileBytes(L["uid"]) == data[L["index"] - 1]
    assert cloud.hasFile(manifest_uid(d)), "the series manifest is a file too"

    r = W.commit()
    assert (r["documents"], r["files"], r["resent"]) == (1, 4, 0)
    stored = cloud.docsOfClass("lightsheetZarrLevel")
    assert len(stored) == 1
    assert stored[0]["base"]["session_id"] == cloud.sessionId
    assert stored[0]["files"]["series_info"][0]["ingest_locations"] == []
    assert locs_of(d), "the caller's document keeps its member paths"
    assert W.committed
    assert W.commit() is r
    with pytest.raises(SessionWriterError) as e:
        W.database_add(W.newdocument("base"))
    assert e.value.identifier == "NDI:cloud:SessionWriter:alreadyCommitted"


def test_many_files_go_in_zip_batches_without_a_background_send(cloud, make_writer, series_doc):
    W = make_writer(bulkThreshold=2, parallelUploads=1)
    d, _ = series_doc(W, cloud.subjectId, 5)
    W.database_add(d)
    assert cloud.batchUploads == 1 and cloud.singleUploads == 0


def test_many_files_still_go_in_the_background(cloud, make_writer, series_doc):
    W = make_writer(bulkThreshold=2)
    d, _ = series_doc(W, cloud.subjectId, 5)
    W.database_add(d)
    assert (cloud.backgroundSends, cloud.batchUploads, cloud.singleUploads) == (1, 0, 0)


def test_a_wrong_upload_is_sent_again(cloud, make_writer, series_doc):
    W = make_writer(bulkThreshold=2, parallelUploads=1)
    d, data = series_doc(W, cloud.subjectId, 3)
    bad = locs_of(d)[1]
    cloud.CorruptOnce = [bad["uid"]]
    W.database_add(d)
    assert cloud.fileBytes(bad["uid"]) == data[bad["index"] - 1]
    assert cloud.singleUploads == 1, "only the bad file is sent again"
    assert W.commit()["resent"] == 1


def test_size_is_compared_when_the_cloud_has_no_checksum(cloud, make_writer, series_doc):
    cloud.RecordCrc = False
    W = make_writer()
    d, data = series_doc(W, cloud.subjectId, 2)
    bad = locs_of(d)[0]
    cloud.CorruptOnce = [bad["uid"]]
    W.database_add(d)
    assert cloud.fileBytes(bad["uid"]) == data[bad["index"] - 1]


def test_an_upload_that_stays_wrong_is_an_error(cloud, make_writer, series_doc):
    W = make_writer()
    d, _ = series_doc(W, cloud.subjectId, 2)
    cloud.CorruptAlways = [locs_of(d)[0]["uid"]]
    with pytest.raises(SessionWriterError) as e:
        W.database_add(d)
    assert e.value.identifier == "NDI:cloud:SessionWriter:uploadNotVerified"
    assert cloud.addedJson == [], "no document may be added when its files are not right"


def test_a_failed_add_is_an_error(cloud, make_writer):
    W = make_writer()
    W.database_add(W.newdocument("base"))
    cloud.FailAdd = True
    with pytest.raises(SessionWriterError) as e:
        W.commit()
    assert e.value.identifier == "NDI:cloud:SessionWriter:addDocumentFailed"


def test_open_binary_doc_reads_the_local_copy_or_downloads(cloud, make_writer, series_doc):
    W = make_writer(keepLocalCopies=True)
    d, data = series_doc(W, cloud.subjectId, 2)
    W.database_add(d)
    f = W.database_openbinarydoc(d, "chunk.bin_2")
    assert f.name == f.fullpathfilename
    with open(f.fullpathfilename, "rb") as h:
        assert h.read() == data[1]
    W.database_closebinarydoc(f)
    os.remove(f.fullpathfilename)
    f = W.database_openbinarydoc(d.id, "chunk.bin_2")
    with open(f.fullpathfilename, "rb") as h:
        assert h.read() == data[1], "a file no longer cached is downloaded"
    with pytest.raises(SessionWriterError) as e:
        W.database_openbinarydoc(d, "chunk.bin_9")
    assert e.value.identifier == "NDI:cloud:SessionWriter:noSuchFile"


# ---------------------------------------------------------------------------
# Streaming a series
# ---------------------------------------------------------------------------


def test_a_declared_document_goes_up_before_its_members(cloud, make_writer, series_doc):
    W = make_writer()
    d, data = series_doc(W, cloud.subjectId, 3)
    W.declare(d)
    assert cloud.hasDocument(d.id), "a declared document is in the cloud at once"
    assert cloud.hasFile(manifest_uid(d)), "its manifest is uploaded with it"
    L = locs_of(d)
    assert not cloud.hasFile(L[0]["uid"]), "members are not sent by declare"
    W.streamMembers(d, "chunk.bin", [1, 2], [L[0]["location"], L[1]["location"]])
    W.streamMembers(d, "chunk.bin", [3], [L[2]["location"]])
    r = W.commit()
    for x in L:
        assert cloud.fileBytes(x["uid"]) == data[x["index"] - 1]
    assert r["documents"] == 1


def test_members_whose_paths_do_not_exist_yet_can_be_declared(cloud, make_writer, tmp_path):
    # As makePyramid: the series is added with where each chunk WILL be.
    W = make_writer()
    future = [str(tmp_path / "later" / f"chunk_{i}.bin") for i in (1, 2)]
    d = W.newdocument("lightsheetZarrLevel")
    d.set_dependency_value("subject_id", cloud.subjectId)
    dd = Document(d.document_properties)
    dd.add_file_series("chunk.bin", future, indices=[1, 2])
    d = ndi_document(dd.document_properties)
    W.declare(d)
    (tmp_path / "later").mkdir()
    for p in future:
        with open(p, "wb") as f:
            f.write(b"chunk " + p.encode())
    W.streamMembers(d, "chunk.bin", [1, 2], future)
    W.commit()
    assert all(cloud.hasFile(x["uid"]) for x in locs_of(d))


def test_streamed_copies_are_deleted_once_checked(cloud, make_writer, series_doc):
    W = make_writer(keepLocalCopies=True)
    d, _ = series_doc(W, cloud.subjectId, 2)
    W.declare(d)
    L = locs_of(d)
    W.streamMembers(d, "chunk.bin", [1], [L[0]["location"]])
    W.streamMembers(d, "chunk.bin", [2], [L[1]["location"]])
    assert not os.path.isfile(os.path.join(W.cacheDir, L[0]["uid"])), "checked: gone"
    assert os.path.isfile(os.path.join(W.cacheDir, L[1]["uid"])), "the newest waits"
    W.commit()
    assert not os.path.isfile(os.path.join(W.cacheDir, L[1]["uid"]))


def test_retained_members_stay_until_released(cloud, make_writer, series_doc):
    W = make_writer(keepLocalCopies=True)
    d, data = series_doc(W, cloud.subjectId, 2)
    W.declare(d)
    L = locs_of(d)
    W.streamMembers(d, "chunk.bin", [1, 2], [x["location"] for x in L], True)
    W.streamMembers(d, "chunk.bin", [], [], True)  # checks the batch
    f = W.database_openbinarydoc(d, "chunk.bin_1")
    with open(f.name, "rb") as h:
        assert h.read() == data[0]
    W.releaseMembers(d)
    assert not os.path.isfile(os.path.join(W.cacheDir, L[0]["uid"]))


def test_commit_refuses_a_missing_declared_member(cloud, make_writer, series_doc):
    W = make_writer()
    d, _ = series_doc(W, cloud.subjectId, 3)
    W.declare(d)
    W.streamMembers(d, "chunk.bin", [1], [locs_of(d)[0]["location"]])
    with pytest.raises(SessionWriterError) as e:
        W.commit()
    assert e.value.identifier == "NDI:cloud:SessionWriter:membersMissing"


def test_an_undeclared_member_is_refused(cloud, make_writer, series_doc):
    W = make_writer()
    d, _ = series_doc(W, cloud.subjectId, 1)
    with pytest.raises(SessionWriterError) as e:
        W.streamMembers(d, "chunk.bin", [1], ["x"])
    assert e.value.identifier == "NDI:cloud:SessionWriter:notDeclared"


def test_replace_on_commit(cloud, make_writer):
    W = make_writer()
    d = W.newdocument("base", **{"base.name": "first (uploading)"})
    W.declare(d)
    final = ndi_document(d.document_properties).setproperties(**{"base.name": "first"})
    W.replaceOnCommit(final)
    q = ndi_query("base.id", "exact_string", d.id)
    assert cloud.findDocuments("", q)[0]["base"]["name"] == "first (uploading)"
    W.commit()
    assert cloud.findDocuments("", q)[0]["base"]["name"] == "first"


# ---------------------------------------------------------------------------
# Sending in the background
# ---------------------------------------------------------------------------


def test_a_batch_is_sent_in_the_background_and_verified_at_the_next_call(
    cloud, make_writer, series_doc
):
    cloud.DeferSends = True
    W = make_writer()
    d, data = series_doc(W, cloud.subjectId, 2)
    W.declare(d)
    L = locs_of(d)
    before = cloud.backgroundSends
    W.streamMembers(d, "chunk.bin", [1], [L[0]["location"]])
    assert cloud.backgroundSends == before + 1
    assert not cloud.hasFile(L[0]["uid"]), "streamMembers returns while the batch goes up"
    W.streamMembers(d, "chunk.bin", [2], [L[1]["location"]])
    assert cloud.fileBytes(L[0]["uid"]) == data[0], "waited for at the next call"
    r = W.commit()
    assert cloud.fileBytes(L[1]["uid"]) == data[1]
    assert cloud.singleUploads == 0 and r["resent"] == 0
    assert set(W.timing) == {"urls", "stage", "send", "verify"}


def test_documents_streamed_in_turn_do_not_wait_for_each_other(cloud, make_writer, series_doc):
    cloud.DeferSends = True
    W = make_writer()
    a, _ = series_doc(W, cloud.subjectId, 2)
    b, _ = series_doc(W, cloud.subjectId, 2)
    W.declare(a)
    W.declare(b)
    la, lb = locs_of(a), locs_of(b)
    W.streamMembers(a, "chunk.bin", [1], [la[0]["location"]])
    W.streamMembers(b, "chunk.bin", [1], [lb[0]["location"]])
    assert not cloud.hasFile(la[0]["uid"])
    W.streamMembers(a, "chunk.bin", [2], [la[1]["location"]])
    assert cloud.hasFile(la[0]["uid"]), "A's batch is checked at A's next call"
    assert not cloud.hasFile(lb[0]["uid"])
    W.streamMembers(b, "chunk.bin", [2], [lb[1]["location"]])
    assert W.commit()["documents"] == 2
    assert all(cloud.hasFile(x["uid"]) for x in la + lb)


def test_a_failed_background_send_is_sent_one_by_one(cloud, make_writer, series_doc):
    cloud.FailSends = True
    W = make_writer()
    d, data = series_doc(W, cloud.subjectId, 3)
    W.database_add(d)
    for x in locs_of(d):
        assert cloud.fileBytes(x["uid"]) == data[x["index"] - 1]
    assert cloud.singleUploads == 4, "three members and the manifest, each sent again"
    assert W.commit()["resent"] == 4


def test_files_the_send_did_not_send_are_resent_at_once(cloud, make_writer, series_doc):
    cloud.FailFirstSends = 1
    W = make_writer()
    d, data = series_doc(W, cloud.subjectId, 3)
    W.database_add(d)
    for x in locs_of(d):
        assert cloud.fileBytes(x["uid"]) == data[x["index"] - 1]
    assert cloud.singleUploads == 1, "only the one the send named"
    assert W.commit()["resent"] == 1


def test_a_file_the_cloud_records_late_is_checked_later(cloud, make_writer, series_doc):
    W = make_writer()
    d, data = series_doc(W, cloud.subjectId, 2)
    W.declare(d)
    L = locs_of(d)
    W.streamMembers(d, "chunk.bin", [1], [L[0]["location"]])
    cloud.RecordLate = 1
    W.streamMembers(d, "chunk.bin", [2], [L[1]["location"]])
    assert W._lagging, "the late file is kept for a later check"
    r = W.commit()
    assert cloud.singleUploads == 0 and r["resent"] == 0, "not sent again"
    assert [cloud.fileBytes(x["uid"]) for x in L] == data


def test_a_file_never_recorded_is_sent_again_by_commit(cloud, make_writer, series_doc):
    W = make_writer()
    d, _ = series_doc(W, cloud.subjectId, 1)
    W.declare(d)
    W.streamMembers(d, "chunk.bin", [1], [locs_of(d)[0]["location"]])
    cloud.RecordLate = 2  # the quick look, and the wait at commit
    r = W.commit()
    assert cloud.singleUploads == 1 and r["resent"] == 1


def test_one_parallel_upload_sends_one_by_one(cloud, make_writer, series_doc):
    W = make_writer(parallelUploads=1)
    d, _ = series_doc(W, cloud.subjectId, 3)
    W.database_add(d)
    assert cloud.backgroundSends == 0 and cloud.singleUploads == 4


def test_parallel_uploads_comes_from_the_preference(cloud, make_writer, series_doc, monkeypatch):
    from ndi import preferences

    real = preferences.get
    monkeypatch.setattr(
        preferences,
        "get",
        lambda name: 1 if name == "Cloud.Upload.Parallel_Uploads" else real(name),
    )
    W = make_writer()
    d, _ = series_doc(W, cloud.subjectId, 3)
    W.database_add(d)
    assert cloud.backgroundSends == 0 and cloud.singleUploads == 4


def test_the_batchs_upload_urls_come_at_once(cloud, make_writer, series_doc):
    W = make_writer()
    d, _ = series_doc(W, cloud.subjectId, 3)
    W.database_add(d)
    assert cloud.urlBatches == 1, "one request for all four"
    assert W.timing["urls"] >= 0


def test_a_batch_can_go_as_one_zip(cloud, make_writer, series_doc):
    cloud.DeferSends = True
    W = make_writer(zipBatches=True)
    d, data = series_doc(W, cloud.subjectId, 2)
    W.declare(d)
    L = locs_of(d)
    before = cloud.zipSends
    W.streamMembers(d, "chunk.bin", [1, 2], [x["location"] for x in L])
    assert cloud.zipSends == before + 1
    assert not cloud.hasFile(L[0]["uid"])
    W.commit()
    assert [cloud.fileBytes(x["uid"]) for x in L] == data
    assert cloud.singleUploads == 0


def test_a_stored_zip_holds_the_files_under_their_names(tmp_path):
    a, b = tmp_path / "a.bin", tmp_path / "b.bin"
    a.write_bytes(bytes(10000))
    b.write_bytes(bytes(range(200, 0, -1)))
    z = tmp_path / "batch.zip"
    SessionWriter.writeStoredZip(str(z), [str(a), str(b)], ["uid_a", "uid_b"])
    with zipfile.ZipFile(z) as zf:
        assert sorted(zf.namelist()) == ["uid_a", "uid_b"]
        assert zf.read("uid_a") == bytes(10000)
        assert zf.read("uid_b") == bytes(range(200, 0, -1))
        assert all(i.compress_type == zipfile.ZIP_STORED for i in zf.infolist())
    assert z.stat().st_size > 10200


# ---------------------------------------------------------------------------
# Riding out failures, resuming
# ---------------------------------------------------------------------------


def test_a_failing_lookup_is_retried(cloud, make_writer, series_doc):
    W = make_writer(retrySeconds=30)
    d, data = series_doc(W, cloud.subjectId, 2)
    cloud.FailLookups = 2
    W.database_add(d)
    assert cloud.fileBytes(locs_of(d)[0]["uid"]) == data[0]
    assert cloud.FailLookups == 0


def test_a_lost_add_reply_makes_no_duplicate(cloud, make_writer):
    W = make_writer(retrySeconds=30)
    d = W.newdocument("base", **{"base.name": "once"})
    cloud.LoseAddReply = True
    W.declare(d)
    assert len(cloud.findDocuments("", ndi_query("base.id", "exact_string", d.id))) == 1


def test_adopt_and_missing_members_for_a_resume(cloud, make_writer, series_doc):
    W = make_writer()
    d, _ = series_doc(W, cloud.subjectId, 3)
    W.declare(d)
    L = locs_of(d)
    W.streamMembers(d, "chunk.bin", [2], [L[1]["location"]])
    W.streamMembers(d, "chunk.bin", [], [])
    W2 = make_writer()  # as after a restart
    W2.adopt(d)
    missing = W2.missingMembers(d, "chunk.bin")
    assert sorted(missing) == [1, 3]
    W2.streamMembers(d, "chunk.bin", [1, 3], [L[0]["location"], L[2]["location"]])
    W2.commit()
    assert len(cloud.docsOfClass("lightsheetZarrLevel")) == 1, "adopt does not re-upload"
    assert W2.missingMembers(d, "nope") == []


def test_a_cached_copy_a_power_cut_shortened_is_fetched_again(cloud, make_writer, series_doc):
    W = make_writer(keepLocalCopies=True)
    d, data = series_doc(W, cloud.subjectId, 2)
    W.declare(d)
    L = locs_of(d)
    W.streamMembers(d, "chunk.bin", [1, 2], [x["location"] for x in L], True)
    W.commit()
    short = os.path.join(W.cacheDir, L[0]["uid"])
    with open(short, "wb") as f:
        f.write(b"\x01\x02\x03")

    W2 = make_writer(cacheDir=W.cacheDir, keepLocalCopies=True)
    W2.adopt(d)
    for i in (1, 2):
        f = W2.database_openbinarydoc(d, f"chunk.bin_{i}")
        with open(f.name, "rb") as h:
            assert h.read() == data[i - 1]


def test_on_upload_sees_each_document(make_writer):
    seen = []
    W = make_writer(onUpload=lambda doc: seen.append(doc.id))
    a = W.newdocument("base")
    b = W.newdocument("base")
    W.database_add(a)
    W.declare(b)
    assert seen == [a.id, b.id], "held documents go up before a declared one"


def test_delete_removes_the_cache_unless_kept(cloud, tmp_path):
    W = SessionWriter(
        cloud.DatasetId,
        cloud.sessionId,
        api=cloud.api(),
        verbose=False,
        cacheDir=str(tmp_path / "c1"),
    )
    assert os.path.isdir(W.cacheDir)
    W.delete()
    assert not os.path.isdir(W.cacheDir)
    with SessionWriter(
        cloud.DatasetId,
        cloud.sessionId,
        api=cloud.api(),
        verbose=False,
        cacheDir=str(tmp_path / "c2"),
        keepLocalCopies=True,
    ) as W2:
        pass
    assert os.path.isdir(W2.cacheDir)


# ---------------------------------------------------------------------------
# ThreadSender (MATLAB: CurlSender) with a fake HTTP session
# ---------------------------------------------------------------------------


class _Resp:
    def __init__(self, code):
        self.status_code = code
        self.text = "" if code < 300 else "nope"


class FakeHTTP:
    """A thread-safe stand-in for requests.Session: records each PUT."""

    def __init__(self, script=None):
        self.lock = threading.Lock()
        self.puts: list[tuple[str, bytes, dict]] = []
        self.script = dict(script or {})  # url -> list of status codes / exceptions

    def put(self, url, data=None, headers=None, timeout=None):
        body = data.read()
        with self.lock:
            self.puts.append((url, body, dict(headers)))
            seq = self.script.get(url)
            nxt = seq.pop(0) if seq else 200
        if isinstance(nxt, Exception):
            raise nxt
        return _Resp(nxt)


def _files(tmp_path, n):
    paths = []
    for i in range(n):
        p = tmp_path / f"f{i}"
        p.write_bytes(os.urandom(50 + i))
        paths.append(str(p))
    return paths


def test_thread_sender_puts_each_file_signed(tmp_path):
    paths = _files(tmp_path, 5)
    urls = [f"https://s3.example.com/u{i}" for i in range(5)]
    crcs = [crc32(p) for p in paths]
    uids = [f"uid{i}" for i in range(5)]
    http = FakeHTTP()
    s = ThreadSender(urls, paths, crcs, uids, str(tmp_path), parallel=3, session=http)
    ok, msg, failed = s.wait(30)
    assert ok and msg == "" and failed == []
    assert s.isDone()
    got = {u: (b, h) for u, b, h in http.puts}
    for i in range(5):
        body, headers = got[urls[i]]
        with open(paths[i], "rb") as f:
            assert body == f.read()
        assert headers["x-amz-checksum-crc32"] == crcs[i]
        assert headers["Content-Type"] == "application/octet-stream"


def test_thread_sender_retries_transient_failures_and_names_the_rest(tmp_path):
    import requests

    paths = _files(tmp_path, 3)
    urls = [f"https://s3.example.com/u{i}" for i in range(3)]
    http = FakeHTTP(
        {
            urls[0]: [503, requests.ConnectionError("reset"), 200],  # recovers
            urls[1]: [403],  # not transient: fails at once
            urls[2]: [500, 500, 500, 500],  # gives up after 3 retries
        }
    )
    s = ThreadSender(urls, paths, ["", "", ""], ["a", "b", "c"], parallel=2, session=http)
    ok, msg, failed = s.wait()
    assert not ok
    assert sorted(failed) == ["b", "c"]
    assert "2 of 3 file(s) not sent" in msg
    assert sum(1 for u, _, _ in http.puts if u == urls[0]) == 3
    assert sum(1 for u, _, _ in http.puts if u == urls[1]) == 1
    assert sum(1 for u, _, _ in http.puts if u == urls[2]) == 4
    assert all("x-amz-checksum-crc32" not in h for _, _, h in http.puts)


def test_thread_sender_refuses_bad_input(tmp_path):
    p = _files(tmp_path, 1)
    with pytest.raises(ValueError):
        ThreadSender(["https://x.example.com/a"], p, [], ["a"])
    with pytest.raises(ValueError):
        ThreadSender(["http://x.example.com/a"], p, [""], ["a"])
    with pytest.raises(ValueError):
        ThreadSender(["https://x.example.com/a"], p, [""], ["a b"])


def test_thread_sender_delete_removes_delete_after(tmp_path):
    p = _files(tmp_path, 1)
    extra = tmp_path / "batch.zip"
    extra.write_bytes(b"zip")
    s = ThreadSender(
        ["https://x.example.com/a"],
        p,
        [""],
        ["zip"],
        parallel=1,
        deleteAfter=[str(extra)],
        session=FakeHTTP(),
    )
    assert s.wait(10)[0]
    s.delete()
    assert not extra.exists()


# ---------------------------------------------------------------------------
# signedUploadURLs and the default API, with ndi.cloud.api monkeypatched
# ---------------------------------------------------------------------------


def test_signed_upload_urls_asks_concurrently_with_the_checksum(monkeypatch):
    from ndi.cloud import internal
    from ndi.cloud import signed_upload_urls as su
    from ndi.cloud.api import files as files_api

    su._ORGANIZATIONS.clear()
    org_calls = []
    monkeypatch.setattr(
        internal, "_datasetOrganizationId", lambda d, client=None: org_calls.append(d) or "org1"
    )
    asked = []

    def fake_url(org, ds, uid, *, checksum_crc32="", client=None):
        asked.append((org, ds, uid, checksum_crc32, client))
        return f"https://s3.example.com/{uid}?crc={checksum_crc32}"

    monkeypatch.setattr(files_api, "getFileUploadURL", fake_url)
    client = object()
    ok, urls, msg = su.signedUploadURLs(
        "ds1", ["u1", "u2", "u3"], ["AAAAAA==", "", "BBBBBB=="], "", parallel=2, client=client
    )
    assert ok and msg == ""
    assert urls == [
        "https://s3.example.com/u1?crc=AAAAAA==",
        "https://s3.example.com/u2?crc=",
        "https://s3.example.com/u3?crc=BBBBBB==",
    ]
    assert sorted(a[2] for a in asked) == ["u1", "u2", "u3"]
    assert all(a[0] == "org1" and a[4] is client for a in asked)
    su.signedUploadURLs("ds1", ["u4"], [""], client=client)
    assert org_calls == ["ds1"], "the organization is looked up once"

    def failing(org, ds, uid, *, checksum_crc32="", client=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(files_api, "getFileUploadURL", failing)
    ok, urls, msg = su.signedUploadURLs("ds1", ["u1"], [""], client=client)
    assert not ok and urls == [] and "boom" in msg
    su._ORGANIZATIONS.clear()


def test_default_api_lookup_and_wait_use_the_cloud_api(monkeypatch):
    from ndi.cloud.api import files as files_api

    state = {"calls": 0}

    def fake_lookup(d, uids, *, client=None):
        state["calls"] += 1
        up = state["calls"] >= 3
        return {
            "files": [{"uid": u, "uploaded": up, "size": 1, "crc32": None} for u in uids],
            "missing": [],
        }

    monkeypatch.setattr(files_api, "lookupFiles", fake_lookup)
    api = SessionWriter.defaultApi(client=object())
    ok, answer = api["lookupFiles"]("ds", ["a"])
    assert ok and answer["files"][0]["uid"] == "a"
    ok, answer = api["waitForFileUpload"]("ds", ["a"], 60)
    assert ok and answer["state"] == "complete" and state["calls"] == 3

    def broken(d, uids, *, client=None):
        raise RuntimeError("offline")

    monkeypatch.setattr(files_api, "lookupFiles", broken)
    ok, answer = api["lookupFiles"]("ds", ["a"])
    assert not ok and answer["message"] == "offline"
