"""Download and profile the MATLAB-built lightsheet blob fixture.

The fixture itself is built + uploaded by the MATLAB roundtrip:

    % In MATLAB, with NDI_CLOUD_USERNAME / NDI_CLOUD_PASSWORD set:
    info = ndi.test.cloud.lightsheet_blob_cloud_roundtrip(...);
    info.cloudDatasetId

That routine builds the synthetic blob (see
``+ndi/+test/+lightsheet/makeBlobFixture.m`` -- ring + Gaussian +
single-voxel-spike features that survive a mean-vs-max downsample),
ingests it to a session, adds the session to an ndi.dataset.dir, and
uploads it. The cloud dataset id it prints is the fixture handle
this Python script needs.

WHY LEAN ON MATLAB. ``ndi.fun.doc.lightsheet.fromOMEZarr`` -- the
ingest that turns an OME-Zarr store into ``lightsheetZarrPyramid`` +
``lightsheetZarrLevel`` documents with the right chunk file series
attached -- is MATLAB-only for now (see
src/ndi/fun/doc_lightsheet/ndi_matlab_python_bridge.yaml). Building
the same fixture in Python would mean porting that ingest first;
doing it here would delay the profiling we actually want. Once
fromOMEZarr lands on the Python side, this script can be extended
with a ``--build`` mode that runs the roundtrip end to end in
Python.

WHAT THIS SCRIPT DOES:

* --download <cloud_dataset_id>: pull the fixture to a local
  directory (SyncFiles=false by default, so the ndic:// URIs stay
  and the loader has cloud fetches to profile), open it with
  :class:`ImagePyramidLoader`, walk every level, and print per-level
  timing + byte counters. The result is a JSON envelope on stdout
  the integration test can consume.
* --local-path <dir>: skip the download and profile an
  already-downloaded copy. Useful when the operator has just
  finished the MATLAB roundtrip and wants to profile without
  redownloading.

The script does not commit any credentials. Downloading requires
the same environment variables ``napariViewLightsheet`` needs
(``NDI_CLOUD_USERNAME``, ``NDI_CLOUD_PASSWORD``,
``CLOUD_API_ENVIRONMENT``); the script prints a note and exits
non-zero if any are missing.

Usage
-----

Download the fixture and profile:

    python scripts/upload_lightsheet_test_fixture.py \\
        --download DATASET_ID \\
        --local-dir /tmp/lightsheet_fixture

Profile an already-downloaded copy:

    python scripts/upload_lightsheet_test_fixture.py \\
        --local-path /tmp/lightsheet_fixture

On success the script prints (to stdout) a JSON envelope with
identifiers and profile numbers:

    {
      "local_path": "/tmp/lightsheet_fixture",
      "cloud_dataset_id": "...",
      "pyramid_doc_id": "...",
      "levels": [
        {"level": 0, "shape": [2, 4, 32, 32], "chunks_read": 4,
         "wall_seconds": 3.14, "bytes_read": 16384, ...},
        ...
      ],
      "loader_stats": {"fetcher": "...", "fallback": "..."}
    }
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


def _check_cloud_env() -> str | None:
    """Return a warning message if cloud env vars are missing, else None."""
    missing = [
        name
        for name in ("NDI_CLOUD_USERNAME", "NDI_CLOUD_PASSWORD")
        if not os.environ.get(name, "").strip()
    ]
    if missing:
        return "missing " + ", ".join(missing)
    return None


def download_fixture(cloud_dataset_id: str, local_dir: Path) -> Path:
    """Download the fixture to ``local_dir``. Returns the dataset path.

    SyncFiles is left off so the loader profiling exercises the same
    cloud-fetch path the viewer does -- with SyncFiles on, every
    ``chunk.bin_#`` file lands during the download and the fetcher's
    cloud path never runs. Turn it on manually (via
    ``ndi.cloud.downloadDataset(..., sync_files=True)``) if the goal
    is just to have a local copy for offline poking.
    """
    from ndi.cloud.orchestration import downloadDataset

    local_dir = Path(local_dir).absolute()
    local_dir.mkdir(parents=True, exist_ok=True)
    ok, dataset_path, msg = downloadDataset(
        cloud_dataset_id,
        str(local_dir),
        sync_files=False,
        verbose=True,
    )
    if not ok:
        raise SystemExit(f"downloadDataset failed: {msg}")
    return Path(dataset_path or local_dir)


def _find_pyramid(session):
    """First lightsheetZarrPyramid document in the session, or None."""
    from ndi.query import ndi_query

    q = ndi_query("").isa("lightsheetZarrPyramid")
    docs = list(session.database_search(q))
    if not docs:
        return None
    return docs[0]


def profile_loader(local_path: Path) -> dict:
    """Open the fixture via ImagePyramidLoader and read every chunk.

    Reads each level by calling ``dask_array.compute()`` on a plain
    slice -- the same shape as napari's slicer would ask for -- and
    records wall-clock time per level. Then returns the loader's own
    stats snapshot (cache hits, cloud fetches, mean/max fetch time).
    """
    from ndi.pyramid.loader import ImagePyramidLoader

    session = _open_session(local_path)
    pyramid_doc = _find_pyramid(session)
    if pyramid_doc is None:
        raise SystemExit(f"no lightsheetZarrPyramid in {local_path}")

    loader = ImagePyramidLoader(session, pyramid_doc, reduction="mean")
    try:
        specs = loader.specs
        fetcher = loader.fetcher
        fetcher.warm()

        levels_info: list[dict] = []
        # specs is one per channel; each spec's `data` is a lazy
        # dask array of the coarsest level (single-level mode) or
        # the whole ladder (multiscale mode). The private
        # `_ndi_level_arrays` key on each spec holds the FULL per-
        # level ladder for that channel. Profile every level for
        # channel 0 -- reading channel 1 would double the work
        # without adding coverage.
        ladder = specs[0].get("_ndi_level_arrays", [])
        for i, arr in enumerate(ladder):
            t0 = time.perf_counter()
            arr.compute()
            dt = time.perf_counter() - t0
            shape = list(getattr(arr, "shape", []))
            n_chunks = 1
            chunks_desc = getattr(arr, "chunks", None)
            if chunks_desc is not None:
                # dask's chunks is a tuple of tuples of sizes per axis.
                for per_axis in chunks_desc:
                    n_chunks *= len(per_axis) if hasattr(per_axis, "__len__") else 1
            levels_info.append(
                {
                    "level": i,
                    "shape": shape,
                    "n_chunks": n_chunks,
                    "wall_seconds": round(dt, 3),
                }
            )
        return {
            "levels": levels_info,
            "loader_stats": loader.stats(),
        }
    finally:
        loader.close()


def _open_session(local_path: Path):
    """Open the downloaded artifact as a dataset first, session second.

    Same dispatch cli._open_session uses: a downloaded NDI dataset
    keeps its documents in LINKED SESSIONS, and only
    ``ndi.dataset.dir.database_search`` follows those links; a plain
    session directory looks identical on disk but resolves through
    ``ndi.session.dir.database_search``.
    """
    from ndi.dataset._dataset import ndi_dataset_dir
    from ndi.session.dir import ndi_session_dir

    # Try dataset first.
    try:
        dataset = ndi_dataset_dir(str(local_path))
        # A dataset's documents include those in its linked sessions;
        # if it finds a pyramid there, use the dataset for search.
        from ndi.query import ndi_query

        q = ndi_query("").isa("lightsheetZarrPyramid")
        if list(dataset.database_search(q)):
            return dataset
    except Exception:  # noqa: BLE001 - fall through to session below
        pass
    return ndi_session_dir(str(local_path))


# ---------------------------------------------------------------------------
# CLI.


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--local-dir",
        type=Path,
        help="Where to download the fixture (with --download) or where the "
        "already-downloaded copy lives (with --local-path).",
    )
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--download",
        metavar="CLOUD_DATASET_ID",
        help="Download the fixture from NDI cloud by dataset id.",
    )
    group.add_argument(
        "--local-path",
        type=Path,
        help="Profile an existing local copy (skip download).",
    )
    group.add_argument(
        "--build-with-matlab",
        action="store_true",
        help="Shell out to MATLAB and run "
        "ndi.test.cloud.lightsheet_blob_cloud_roundtrip to build + upload "
        "a fresh fixture. Prints the resulting cloud_dataset_id so the "
        "caller can pass it back through --download on a subsequent "
        "invocation. Requires MATLAB on the PATH.",
    )
    p.add_argument(
        "--matlab",
        default="matlab",
        help="MATLAB executable name / path (default: matlab). Used only "
        "with --build-with-matlab.",
    )
    return p.parse_args(argv)


def build_with_matlab(matlab_exe: str) -> dict:
    """Run the MATLAB roundtrip and parse the printed cloud_dataset_id.

    Shells to::

        matlab -batch "info = ndi.test.cloud.lightsheet_blob_cloud_roundtrip( ...
                       'ViewLocal', false, 'ViewCloud', false); ...
                       fprintf('CLOUD_DATASET_ID=%s\\n', info.cloudDatasetId)"

    Returns a dict with ``cloud_dataset_id`` on success. Raises
    :class:`SystemExit` on failure (with the MATLAB stderr in the
    message) so the calling flow surfaces the error rather than
    silently falling through.
    """
    import re
    import subprocess

    warn = _check_cloud_env()
    if warn:
        raise SystemExit(f"cannot run MATLAB roundtrip -- {warn}")

    matlab_cmd = (
        "info = ndi.test.cloud.lightsheet_blob_cloud_roundtrip("
        "'ViewLocal', false, 'ViewCloud', false); "
        "fprintf('CLOUD_DATASET_ID=%s\\n', info.cloudDatasetId);"
    )
    proc = subprocess.run(
        [matlab_exe, "-batch", matlab_cmd],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(
            "MATLAB roundtrip failed (exit "
            f"{proc.returncode}).\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    match = re.search(r"CLOUD_DATASET_ID=(\S+)", proc.stdout)
    if not match:
        raise SystemExit(
            "MATLAB roundtrip completed but no CLOUD_DATASET_ID line was "
            f"printed.\nSTDOUT:\n{proc.stdout}"
        )
    return {"cloud_dataset_id": match.group(1)}


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.build_with_matlab:
        # Fire the MATLAB roundtrip; it builds + ingests + uploads +
        # downloads the fixture into a MATLAB-managed temp directory
        # and prints the resulting cloud id. We surface the id so the
        # caller can re-run with --download to pull it into the
        # Python side.
        built = build_with_matlab(args.matlab)
        print(json.dumps(built, indent=2))
        return 0

    if args.download:
        if not args.local_dir:
            print(
                "[fixture] --local-dir is required with --download",
                file=sys.stderr,
            )
            return 2
        warn = _check_cloud_env()
        if warn:
            print(f"[fixture] refusing to download -- {warn}", file=sys.stderr)
            return 2
        local_path = download_fixture(args.download, args.local_dir)
        envelope = {
            "cloud_dataset_id": args.download,
            "local_path": str(local_path),
        }
    else:
        local_path = args.local_path
        envelope = {"local_path": str(local_path)}

    profile = profile_loader(local_path)
    envelope.update(profile)
    # pyramid_doc_id is useful to the integration test so it can
    # search for the same doc without re-listing.
    session = _open_session(local_path)
    pyramid_doc = _find_pyramid(session)
    if pyramid_doc is not None:
        envelope["pyramid_doc_id"] = pyramid_doc.id

    print(json.dumps(envelope, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
