"""ndi.job LightsheetToCloud: a lightsheet build streamed to a cloud session, resumably.

MATLAB counterpart: tests/+ndi/+unittest/+job/TestLightsheetToCloud.m. A
SmartSPIM fixture is built through the real SessionWriter into a fake cloud
dataset (tests/test_cloud_session_writer.py), paused part-way, resumed, and
every chunk the cloud ends up with is compared with a local build of the same
volume.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("tifffile")
pytest.importorskip("imagecodecs")
pytest.importorskip("numcodecs")

import ndi.cloud.session_writer as sw_mod  # noqa: E402
from ndi.job import ndi_job_ForeignJob, ndi_job_Job, ndi_job_LightsheetToCloud  # noqa: E402
from ndi.job.lightsheet_to_cloud import addMessage, addPlan  # noqa: E402
from tests.test_cloud_session_writer import FakeCloudDataset  # noqa: E402

SMALL = {"chunks": [1, 1, 2, 16, 8], "prefetchBytes": 600, "readWorkers": 2}


@pytest.fixture(autouse=True)
def jobs_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("NDI_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setattr(ndi_job_Job, "_holdAwake", staticmethod(lambda key, label: None))
    monkeypatch.setattr(sw_mod, "_sleep", lambda s: None)
    yield tmp_path / "jobs"


@pytest.fixture
def cloud(tmp_path):
    c = FakeCloudDataset(tmp_path / "cloud")
    c.sessionId = c.addSession("exp1")
    c.subjectId = c.addSubject(c.sessionId, "mouse1@lab")
    return c


@pytest.fixture
def spim(tmp_path):
    from tests._smartspim_fixture import make_example_fixture

    return make_example_fixture(tmp_path / "acq", all_channels=True)


def choices(cloud, spim, **kw):
    c = {
        "destination": "cloud", "datasetId": cloud.DatasetId, "datasetName": "Brains",
        "sessionId": cloud.sessionId, "sessionReference": "exp1",
        "subjectID": cloud.subjectId, "subjectName": "mouse1@lab",
        "sourcePath": str(spim), "sourceKind": "smartspim", "label": "",
        "voxelSizeUm": [], "clevel": 3, "reductions": ["mean", "max"], "numWorkers": 2,
    }  # fmt: skip
    c.update(kw)
    return c


def make_job(cloud, spim, **kw):
    job = ndi_job_LightsheetToCloud.create(choices(cloud, spim, **kw))
    job.Api = cloud.api()
    job.ExtraIngestArgs = dict(SMALL, minLevelSize=8)
    return job


def cloud_levels(cloud) -> dict[tuple[int, str], dict[int, bytes]]:
    """Each streamed level's chunks in the cloud, by (level, reduction) and member number."""
    out = {}
    for d in cloud.docsOfClass("lightsheetZarrLevel"):
        lp = d["lightsheetZarrLevel"]
        series = d["files"]["series_info"]
        series = series[0] if isinstance(series, list) else series
        uids = _member_uids(cloud, d)
        out[(int(lp["level"]), lp["reduction_function"])] = {
            i: cloud.fileBytes(u) for i, u in uids.items()
        }
        assert series["count"] == len(uids)
    return out


def _member_uids(cloud, props) -> dict[int, str]:
    import os
    import tempfile

    from did.file import read_series_manifest

    info = props["files"]["file_info"]
    info = info if isinstance(info, list) else [info]
    man = next(f for f in info if f["name"].lower() == "chunk.bin")
    uid = (
        man["locations"][0]["uid"]
        if isinstance(man["locations"], list)
        else man["locations"]["uid"]
    )
    p = os.path.join(tempfile.mkdtemp(), "m")
    with open(p, "wb") as fh:
        fh.write(cloud.fileBytes(uid))
    m = read_series_manifest(p)
    uids = m["uids"] if isinstance(m, dict) else m[0]
    return {i + 1: u for i, u in enumerate(uids) if u}


def local_levels(spim) -> dict[tuple[int, str], dict[int, bytes]]:
    """The same build into a local session: the bytes the cloud should hold."""
    import tempfile

    from ndi.fun.doc_lightsheet.fromSPIM import fromSPIM
    from ndi.session import ndi_session_dir

    s = ndi_session_dir("local", tempfile.mkdtemp())
    subj = s.newdocument("subject", **{"subject.local_identifier": "m@lab"})
    s.database_add(subj)
    _, levelDocs, _ = fromSPIM(s, str(spim), subjectID=subj.id, clevel=3, numWorkers=2,
                               progressFcn=None, minLevelSize=8, **SMALL)  # fmt: skip
    out = {}
    for d in levelDocs:
        lp = d.document_properties["lightsheetZarrLevel"]
        n = 1
        for g in lp["chunk_grid"]:
            n *= g
        chunks = {}
        for i in range(1, n + 1):
            f = s.database_openbinarydoc(d, f"chunk.bin_{i}")
            chunks[i] = f.read()
            s.database_closebinarydoc(f)
        out[(int(lp["level"]), lp["reduction_function"])] = chunks
    return out


class TestCreate:
    def test_only_a_cloud_destination(self, cloud, spim):
        with pytest.raises(ValueError, match="destination 'cloud'"):
            ndi_job_LightsheetToCloud.create(choices(cloud, spim, destination="local"))

    def test_every_missing_choice_is_reported_at_once(self, cloud, spim):
        c = choices(cloud, spim, datasetId="", subjectID="", clevel=12)
        with pytest.raises(ValueError) as err:
            ndi_job_LightsheetToCloud.create(c)
        msg = str(err.value)
        assert "Not ready yet" in msg
        assert "dataset" in msg and "subject" in msg and "Compression" in msg

    def test_title_and_kind(self, cloud, spim):
        job = make_job(cloud, spim)
        assert job.title == "BOTTOM to session exp1 of the NDI Cloud dataset Brains"
        again = ndi_job_Job.load(job.id)
        assert isinstance(again, ndi_job_LightsheetToCloud)
        assert again.kind == "lightsheetToCloud" and again.runtime == "python"

    def test_plan_and_message(self, cloud, spim):
        plan = addPlan(choices(cloud, spim, clevel=9, voxelSizeUm=[4, 1.8, 1.8]))
        assert plan["errors"] == [] and plan["ingest"] == "fromSPIM"
        assert any("slowest" in w for w in plan["warnings"])
        msg = addMessage(plan)
        assert msg.startswith(f'Add the image\n  {spim}\nas "BOTTOM", of subject mouse1@lab')
        assert "Compression 9, mean and max ladder(s), 2 parallel workers." in msg
        zarr = addPlan(choices(cloud, spim, sourceKind="omezarr", reductions=["mean"],
                               voxelSizeUm=[1, 1, 1]))  # fmt: skip
        assert any("ignored for an OME-Zarr" in w for w in zarr["warnings"])


class TestARun:
    def test_runs_to_done_and_matches_a_local_build(self, cloud, spim):
        job = make_job(cloud, spim)
        job.run()
        assert job.state == "done", job.lastError
        assert job.checkpoint["report"]["documents"] > 0
        assert not (job.folder() / "cache").exists()
        assert (job.folder() / "profile.csv").is_file()
        assert cloud_levels(cloud) == local_levels(spim)
        pyr = cloud.docsOfClass("lightsheetZarrPyramid")
        assert len(pyr) == 1 and pyr[0]["lightsheetZarrPyramid"]["label"] == "BOTTOM"

    def test_a_paused_build_resumes_without_resending(self, cloud, spim):
        job = make_job(cloud, spim)
        job.PauseAfterBeats = 4
        job.run()
        assert job.state == "paused", job.lastError
        saved = list((job.folder() / "documents").glob("*.json"))
        assert saved, "uploaded documents are kept for the next run"
        sends_before = cloud.backgroundFiles + cloud.singleUploads
        again = ndi_job_Job.load(job.id)
        again.Api = cloud.api()
        again.ExtraIngestArgs = dict(SMALL, minLevelSize=8)
        again.run()
        assert again.state == "done", again.lastError
        assert cloud_levels(cloud) == local_levels(spim)
        assert len(cloud.docsOfClass("lightsheetZarrPyramid")) == 1, "the pyramid was adopted"
        assert cloud.backgroundFiles + cloud.singleUploads > sends_before

    def test_restart_forgets_the_saved_documents(self, cloud, spim):
        job = make_job(cloud, spim)
        job.PauseAfterBeats = 2
        job.run()
        job.restart()
        assert not (job.folder() / "documents").exists()


class TestSharedWithMatlab:
    def test_matlabs_job_record_loads_as_this_kind(self, jobs_dir):
        from tests.test_job import matlab_example

        rec = matlab_example()
        (jobs_dir / rec["id"]).mkdir(parents=True)
        (jobs_dir / rec["id"] / "job.json").write_text(json.dumps(rec))
        job = ndi_job_Job.load(rec["id"])
        assert isinstance(job, ndi_job_LightsheetToCloud)
        assert not isinstance(job, ndi_job_ForeignJob)
        assert job.spec["numWorkers"] == 12
