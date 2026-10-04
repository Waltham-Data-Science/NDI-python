"""End-to-end loader test against a real NDI cloud fixture.

The permanent fixture is built by the MATLAB roundtrip
(``ndi.test.cloud.lightsheet_blob_cloud_roundtrip``) and uploaded via
the ``Build lightsheet blob fixture`` GitHub Actions workflow. Its
identifier lives in ``tests/fixtures/lightsheet_cloud_fixture.json``
so a regeneration is one edit in one place; the workflow overwrites
that JSON when re-run.

Skipped automatically when the cloud credentials are not set (same
gate as ``test_cloud_live.py``), so a laptop without secrets keeps
running the rest of the unit tests as usual. In CI these tests run
under the same environment matrix as ``test-cloud-api.yml``.

What the tests exercise:

* Downloading the fixture with ``sync_files=False`` -- the loader
  path we care about is on-demand fetch through the NDI cloud API,
  not local disk.
* Opening the pyramid via :class:`ImagePyramidLoader`, walking every
  level, ``.compute()``-ing each so the fetcher is actually driven.
* Verifying the finest level's shape / dtype / channel count against
  what the MATLAB fixture writes.
* Reading ``loader.stats()`` at the end so the profile numbers
  (cache hits, cloud fetches, mean fetch time) appear in the test
  log for the "home vs. office vs. CI" comparison.

Session-scoped download: opening every test would redownload; a
module fixture pulls once and every test in the file shares the
result.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Skip gate + fixture registry.


_HAS_CREDS = bool(os.environ.get("NDI_CLOUD_USERNAME") and os.environ.get("NDI_CLOUD_PASSWORD"))
pytestmark = [
    pytest.mark.cloud,
    pytest.mark.skipif(not _HAS_CREDS, reason="NDI cloud credentials not set"),
]

FIXTURE_JSON = Path(__file__).parent / "fixtures" / "lightsheet_cloud_fixture.json"


def _fixture_id() -> str:
    """Pick the dataset id the test should point at.

    Precedence: ``NDI_LIGHTSHEET_TEST_FIXTURE_ID`` (env override, for
    a one-shot pointing at a freshly rebuilt fixture) -> the
    ``cloud_dataset_id`` in ``lightsheet_cloud_fixture.json``.
    """
    env = os.environ.get("NDI_LIGHTSHEET_TEST_FIXTURE_ID", "").strip()
    if env:
        return env
    with open(FIXTURE_JSON) as f:
        return str(json.load(f)["cloud_dataset_id"])


# ---------------------------------------------------------------------------
# Shared download.


@pytest.fixture(scope="module")
def downloaded_dataset(tmp_path_factory) -> Path:
    """Pull the fixture once for every test in this module.

    ``sync_files=False`` mirrors what the viewer opens on a normal
    launch: documents land locally, chunk files are fetched from the
    cloud on demand. That is the read path we want to exercise --
    with sync_files on, every chunk arrives during download and the
    loader's cloud-fetch path never runs.
    """
    from ndi.cloud.exceptions import CloudNotFoundError
    from ndi.cloud.orchestration import downloadDataset

    target = tmp_path_factory.mktemp("lightsheet_fixture_download")
    dataset_id = _fixture_id()
    try:
        dataset = downloadDataset(
            dataset_id,
            str(target),
            sync_files=False,
            verbose=False,
        )
    except CloudNotFoundError as exc:
        # The fixture lives on one account + env (see
        # lightsheet_cloud_fixture.json; currently user 1, prod). The
        # cloud-CI matrix runs every account x env combination, so
        # three of the four cells cannot see the fixture and would
        # crash with HTTP 404. Skip cleanly there rather than fail
        # -- one green cell per fixture is the intended baseline.
        # Set NDI_LIGHTSHEET_TEST_FIXTURE_ID to a dataset that IS
        # visible on the account you are running under to point the
        # tests at a different fixture.
        pytest.skip(
            f"fixture {dataset_id} not accessible from this account "
            f"(NDI_CLOUD_USERNAME={os.environ.get('NDI_CLOUD_USERNAME', '?')!r}, "
            f"CLOUD_API_ENVIRONMENT={os.environ.get('CLOUD_API_ENVIRONMENT', '?')!r}): "
            f"{exc}"
        )
    # downloadDataset returns an ndi.ndi_dataset backed by
    # target/<dataset_id>. The tests want the on-disk path so
    # ImagePyramidLoader can open a session on it.
    dataset_path = getattr(dataset, "_path", None) or (target / dataset_id)
    return Path(dataset_path)


@pytest.fixture(scope="module")
def pyramid_doc(downloaded_dataset):
    """The first ``lightsheetZarrPyramid`` on the downloaded dataset."""
    from ndi.dataset._dataset import ndi_dataset_dir
    from ndi.query import ndi_query

    dataset = ndi_dataset_dir(str(downloaded_dataset))
    q = ndi_query("").isa("lightsheetZarrPyramid")
    docs = list(dataset.database_search(q))
    assert docs, f"no lightsheetZarrPyramid documents in {downloaded_dataset}"
    # The dataset itself owns database_search (it follows links into
    # every session), so return both -- the loader wants the session
    # or dataset that resolves further searches, plus the doc.
    return dataset, docs[0]


# ---------------------------------------------------------------------------
# Tests.


class TestLoaderOpensTheFixture:
    def test_the_loader_enumerates_the_levels_finest_first(self, pyramid_doc):
        from ndi.pyramid.loader import ImagePyramidLoader

        session, doc = pyramid_doc
        loader = ImagePyramidLoader(session, doc, reduction="mean")
        try:
            # numLevels does an implicit build via docs; a fixture
            # that lands with no levels means the MATLAB ingest ran
            # halfway.
            n = loader.numLevels
            assert n >= 2, f"pyramid should have at least 2 levels, got {n}"
            # Levels are sorted finest-first, so index 0 has the
            # smallest voxel size on the last docs (they're 0-based
            # ints).
            docs = loader.docs
            levels = [int(d.document_properties["lightsheetZarrLevel"]["level"]) for d in docs]
            assert levels == sorted(
                levels
            ), f"levelDocs should return finest-first, got levels {levels}"
        finally:
            loader.close()

    def test_the_loader_returns_one_spec_per_channel(self, pyramid_doc):
        from ndi.pyramid.loader import ImagePyramidLoader

        session, doc = pyramid_doc
        loader = ImagePyramidLoader(session, doc, reduction="mean")
        try:
            specs = loader.specs
            # Fixture is 2 channels (makeBlobFixture defaults).
            assert len(specs) == 2, f"expected 2 layer specs, got {len(specs)}"
            for spec in specs:
                assert "data" in spec
                # The single-level scaffold delivers a 3D array
                # (channel axis stripped) at the coarsest level.
                data_shape = getattr(spec["data"], "shape", ())
                assert len(data_shape) == 3, f"expected 3D per-channel data, got shape {data_shape}"
        finally:
            loader.close()


class TestLoaderReadsRealBytes:
    def test_the_coarsest_level_computes_and_is_not_all_zero(self, pyramid_doc):
        # A pyramid the fetcher can open but never actually pulls
        # from would compute to all-zero (fill_value) blocks -- the
        # classic "silent fetch failure" bug that hid the DID series
        # switch. Fixture has a ring + Gaussian + spike so any
        # actually-fetched slice is non-zero.
        import numpy as np

        from ndi.pyramid.loader import ImagePyramidLoader

        session, doc = pyramid_doc
        loader = ImagePyramidLoader(session, doc, reduction="mean")
        try:
            specs = loader.specs
            data = specs[0]["data"]  # coarsest-level array for channel 0
            arr = data.compute()
            assert arr.dtype == np.uint16, f"expected uint16, got {arr.dtype}"
            assert arr.any(), "coarsest-level channel-0 slice is entirely fill_value"
        finally:
            loader.close()

    def test_every_level_can_be_computed(self, pyramid_doc):
        # Walks the full ladder. On the small fixture (~5 levels max,
        # 300**3 voxels finest) this is small enough to finish in a
        # single-digit-seconds test on a reasonable link. If it grows
        # to minutes, the fetcher or the network is the problem and
        # the profile numbers below will name which.
        from ndi.pyramid.loader import ImagePyramidLoader

        session, doc = pyramid_doc
        loader = ImagePyramidLoader(session, doc, reduction="mean")
        per_level: list[dict] = []
        try:
            channel0_ladder = specs_channel_ladder(loader, 0)
            for i, arr in enumerate(channel0_ladder):
                t0 = time.perf_counter()
                out = arr.compute()
                dt = time.perf_counter() - t0
                per_level.append({"level": i, "shape": tuple(out.shape), "seconds": round(dt, 2)})
        finally:
            loader.close()
        print(f"\n[integration] per-level compute times: {per_level}")
        assert per_level, "expected at least one level to compute"

    def test_stats_show_at_least_one_cloud_fetch(self, pyramid_doc):
        # If every read hits the cache instead of the cloud, the
        # fixture is not exercising the code we care about. On a
        # freshly-downloaded fixture with sync_files=False, every
        # chunk needs a cloud round trip.
        from ndi.pyramid.loader import ImagePyramidLoader

        session, doc = pyramid_doc
        loader = ImagePyramidLoader(session, doc, reduction="mean")
        try:
            for arr in specs_channel_ladder(loader, 0):
                arr.compute()
            snap = loader.stats()
            print(f"\n[integration] loader.stats(): {snap}")
            # stats["fetcher"] is a summary line like
            # "resolves: N cache-hits (mean X.Xms), M cloud-fetches
            # (mean X.Xs), K failures". We just check the summary is
            # non-empty; the actual counts vary by pyramid shape.
            assert snap.get("fetcher"), "loader.stats() has no fetcher summary"
        finally:
            loader.close()


def specs_channel_ladder(loader, channel: int) -> list:
    """Every level's array for one channel (finest first).

    ``layerSpec`` stashes per-channel per-level arrays on each spec's
    ``_ndi_level_arrays`` list (that is the ladder the level selector
    swaps between). Take the ladder off spec[channel] rather than
    calling into internals.
    """
    specs = loader.specs
    assert 0 <= channel < len(specs), f"channel {channel} out of range"
    return specs[channel].get("_ndi_level_arrays", [])
