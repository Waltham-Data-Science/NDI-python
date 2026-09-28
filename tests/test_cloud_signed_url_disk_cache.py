"""Tests for the persistent (on-disk) signed-URL-set cache.

Mirrors the MATLAB SignedUrlDiskCacheTest (VH-Lab/NDI-matlab commit
27661a3 on the same branch). Covers save/load round-trip, past-expiry,
30 min safety buffer, no-expiry uncacheable, forget, cacheDir env
override, atomic-write behavior under alternating writers, and series
name escaping.

Nothing here hits the network. Each test isolates its own cache dir via
``NDI_SIGNED_URL_CACHE_DIR`` so a leaked file cannot leak into the
user's real ``~/.ndi/signed-url-cache``, nor across tests.
"""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_cache_dir(tmp_path, monkeypatch):
    """One tempdir per test, wired through NDI_SIGNED_URL_CACHE_DIR."""
    cache = tmp_path / "signed-url-cache"
    monkeypatch.setenv("NDI_SIGNED_URL_CACHE_DIR", str(cache))
    # Ensure the safety-seconds override is not carried over from a
    # previous test / the ambient shell.
    monkeypatch.delenv("NDI_SIGNED_URL_CACHE_SAFETY_SECONDS", raising=False)
    return cache


def future_iso(seconds_ahead: float) -> str:
    """ISO-8601 UTC timestamp N seconds from now, server-shaped."""
    dt = datetime.now(timezone.utc) + timedelta(seconds=seconds_ahead)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def sample_payload(**overrides):
    """Signer-shaped payload the cache accepts."""
    payload = {
        "files": {
            "4192a3c0dd1b4e00_3fe8a1b2c3d4e5f6": "https://s3/one",
            "4192a3c0dd1b4e00_4fe8a1b2c3d4e5f6": "https://s3/two?sig=abc%2F123",
        },
        "filesExpireAt": future_iso(23 * 3600),
        "expiresAt": future_iso(23 * 3600),
        "generatedAt": future_iso(-30),
        "fileCount": 2,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class TestSaveLoadRoundTrip:
    """What goes in comes back out on the fields callers actually read."""

    def test_round_trip_preserves_files_and_expiry(self, isolated_cache_dir):
        from ndi.cloud import signed_url_disk_cache as cache

        payload = sample_payload()
        cache.save("ds1", "doc1", "chunk.bin", payload)

        got = cache.load("ds1", "doc1", "chunk.bin")

        assert got is not None, "a just-written scope should load"
        assert got["files"] == payload["files"]
        assert (
            got["files"]["4192a3c0dd1b4e00_4fe8a1b2c3d4e5f6"] == "https://s3/two?sig=abc%2F123"
        ), "URL with url-escaped bytes must survive JSON encoding"
        assert got["filesExpireAt"] == payload["filesExpireAt"]
        assert got["fileCount"] == 2

    def test_written_file_is_valid_gzipped_json(self, isolated_cache_dir):
        """The bytes on disk are the documented shape.

        NDI-matlab and NDI-python have to write the same file so a
        cache dir written by one can be read by the other. If the
        shape drifts, that portability is silently gone.
        """
        from ndi.cloud import signed_url_disk_cache as cache

        cache.save("ds1", "doc1", "", sample_payload())

        path = isolated_cache_dir / "ds1" / "doc1.json.gz"
        assert path.is_file(), "whole-doc scope lands at <ds>/<doc>.json.gz"

        with gzip.open(path, "rt", encoding="utf-8") as fh:
            data = json.load(fh)
        assert data["schemaVersion"] == 1
        assert data["datasetId"] == "ds1"
        assert data["documentId"] == "doc1"
        assert data["seriesName"] == ""
        assert isinstance(data["files"], dict)
        assert (
            "4192a3c0dd1b4e00_3fe8a1b2c3d4e5f6" in data["files"]
        ), "digit-prefixed uids must survive JSON as literal keys"


# ---------------------------------------------------------------------------
# Expiry / safety buffer
# ---------------------------------------------------------------------------


class TestExpiryAndSafetyBuffer:
    """Never hand a caller a URL that would 403 before they can use it."""

    def test_expired_payload_is_a_miss(self, isolated_cache_dir):
        from ndi.cloud import signed_url_disk_cache as cache

        cache.save(
            "ds1",
            "doc1",
            "",
            sample_payload(filesExpireAt=future_iso(-3600), expiresAt=""),
        )
        assert cache.load("ds1", "doc1", "") is None

    def test_safety_buffer_guards_against_almost_expired(self, isolated_cache_dir, monkeypatch):
        """20 min ≤ default 30 min buffer is a miss."""
        from ndi.cloud import signed_url_disk_cache as cache

        cache.save(
            "ds1",
            "doc1",
            "",
            sample_payload(filesExpireAt=future_iso(20 * 60), expiresAt=""),
        )

        assert cache.load("ds1", "doc1", "") is None, "20 min < 30 min safety buffer must be a miss"

        # Tighten the buffer and the SAME payload becomes visible --
        # proving the check is the buffer doing the work, not the
        # write refusing to persist.
        monkeypatch.setenv("NDI_SIGNED_URL_CACHE_SAFETY_SECONDS", "60")
        assert cache.load("ds1", "doc1", "") is not None

    def test_payload_without_expiry_is_uncacheable(self, isolated_cache_dir):
        """save() refuses; load() sees nothing on disk."""
        from ndi.cloud import signed_url_disk_cache as cache

        cache.save(
            "ds1",
            "doc1",
            "",
            sample_payload(filesExpireAt="", expiresAt=""),
        )
        assert cache.load("ds1", "doc1", "") is None
        # And nothing wrote itself into the tree either.
        ds_dir = isolated_cache_dir / "ds1"
        assert not ds_dir.exists() or not any(ds_dir.iterdir())

    def test_load_falls_back_to_expires_at(self, isolated_cache_dir):
        """The paging path's older field also age-checks the cache."""
        from ndi.cloud import signed_url_disk_cache as cache

        cache.save(
            "ds1",
            "doc1",
            "",
            sample_payload(filesExpireAt="", expiresAt=future_iso(3600)),
        )
        assert cache.load("ds1", "doc1", "") is not None


# ---------------------------------------------------------------------------
# Forget / invalidation
# ---------------------------------------------------------------------------


class TestForget:
    """The S3-403 hook: drop a scope whose cached URLs are dead."""

    def test_forget_removes_file(self, isolated_cache_dir):
        from ndi.cloud import signed_url_disk_cache as cache

        cache.save("ds1", "doc1", "chunk.bin", sample_payload())
        assert cache.load("ds1", "doc1", "chunk.bin") is not None

        cache.forget("ds1", "doc1", "chunk.bin")

        assert cache.load("ds1", "doc1", "chunk.bin") is None
        assert not (isolated_cache_dir / "ds1" / "doc1_chunk.bin.json.gz").exists()

    def test_forget_on_unknown_scope_is_silent(self, isolated_cache_dir):
        """S3-403 recovery must not need to check-first."""
        from ndi.cloud import signed_url_disk_cache as cache

        # No pytest.warns / raises: forget is best-effort and idempotent.
        cache.forget("nosuch-ds", "nosuch-doc", "nosuch-series")


# ---------------------------------------------------------------------------
# cacheDir env override
# ---------------------------------------------------------------------------


class TestCacheDir:
    """The env var override is documented on-disk contract for NDI-python."""

    def test_cache_dir_respects_env_override(self, isolated_cache_dir):
        from ndi.cloud import signed_url_disk_cache as cache

        assert Path(cache.cache_dir()) == Path(isolated_cache_dir)

    def test_cache_dir_default_when_env_unset(self, tmp_path, monkeypatch):
        from ndi.cloud import signed_url_disk_cache as cache

        # Pretend HOME is empty ground so we can see the default shape
        # without touching the user's real ~/.ndi/.
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.delenv("NDI_SIGNED_URL_CACHE_DIR", raising=False)

        result = Path(cache.cache_dir())
        assert result == home / ".ndi" / "signed-url-cache"


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


class TestAtomicWrite:
    """Two writers hitting the same scope: last write wins, no corruption."""

    def test_alternating_writes_leave_a_valid_file(self, isolated_cache_dir):
        from ndi.cloud import signed_url_disk_cache as cache

        payload_a = sample_payload(files={"aa_bb": "https://s3/first"})
        payload_b = sample_payload(files={"cc_dd": "https://s3/second"})

        for _ in range(10):
            cache.save("ds1", "doc1", "chunks", payload_a)
            cache.save("ds1", "doc1", "chunks", payload_b)

        got = cache.load("ds1", "doc1", "chunks")
        assert got is not None, "after alternating writes, file must be valid"
        assert isinstance(got["files"], dict)
        # Whichever landed last is fine; what matters is no half-write.
        assert len(got["files"]) == 1

    def test_temp_files_do_not_linger_next_to_the_cache_file(self, isolated_cache_dir):
        """A successful save leaves ONE file: no .tmp scraps around."""
        from ndi.cloud import signed_url_disk_cache as cache

        for _ in range(5):
            cache.save("ds1", "doc1", "chunks", sample_payload())

        ds_dir = isolated_cache_dir / "ds1"
        names = sorted(p.name for p in ds_dir.iterdir())
        # Under a race with a second process the two writers could each
        # briefly hold a .tmp file, but a fully successful run should
        # never leak one.
        assert names == ["doc1_chunks.json.gz"], f"expected exactly one cache file, got {names!r}"


# ---------------------------------------------------------------------------
# Series name escaping
# ---------------------------------------------------------------------------


class TestSeriesNameEscaping:
    """Real series names can hold '/', spaces, unicode -- the FS can't.

    The percent-encoding + SHA-1-hash-above-96-chars rule is the on-disk
    contract MATLAB mirrors byte-for-byte.
    """

    def test_pathy_series_name_saves_and_loads(self, isolated_cache_dir):
        from ndi.cloud import signed_url_disk_cache as cache

        pathy = "level 3/chunk.bin"
        cache.save("ds1", "doc1", pathy, sample_payload())
        assert cache.load("ds1", "doc1", pathy) is not None

    def test_two_series_names_land_in_two_files(self, isolated_cache_dir):
        """Distinct series must NOT collide on disk."""
        from ndi.cloud import signed_url_disk_cache as cache

        payload = sample_payload()
        cache.save("ds1", "doc1", "level 3/chunk.bin", payload)
        cache.save("ds1", "doc1", "level 3_chunk.bin", payload)

        ds_dir = isolated_cache_dir / "ds1"
        n_gz = sum(1 for p in ds_dir.iterdir() if p.name.endswith(".json.gz"))
        assert n_gz == 2, "two distinct series names must produce two distinct cache files"

    def test_very_long_series_name_hashes(self, isolated_cache_dir):
        """A 500-char series name lands as ``hash-<sha1>``, never overflows."""
        from ndi.cloud import signed_url_disk_cache as cache

        long_name = "x" * 500
        cache.save("ds1", "doc1", long_name, sample_payload())

        ds_dir = isolated_cache_dir / "ds1"
        files = list(ds_dir.iterdir())
        assert len(files) == 1
        name = files[0].name
        # Anything short-enough with 'hash-<40 hex>' is fine.
        assert name.startswith("doc1_hash-")
        assert name.endswith(".json.gz")
        assert len(name) < 100  # not 500+


# ---------------------------------------------------------------------------
# Path convention (on-disk contract with NDI-matlab)
# ---------------------------------------------------------------------------


class TestOnDiskLayout:
    """The layout MATLAB writes / reads: whole-doc vs. scoped file names."""

    def test_whole_doc_scope_lands_at_doc_json_gz(self, isolated_cache_dir):
        from ndi.cloud import signed_url_disk_cache as cache

        cache.save("ds1", "doc1", "", sample_payload())
        assert (isolated_cache_dir / "ds1" / "doc1.json.gz").is_file()

    def test_scoped_lands_at_doc_underscore_series(self, isolated_cache_dir):
        from ndi.cloud import signed_url_disk_cache as cache

        cache.save("ds1", "doc1", "chunk.bin", sample_payload())
        assert (isolated_cache_dir / "ds1" / "doc1_chunk.bin.json.gz").is_file()

    def test_corrupt_file_is_treated_as_miss(self, isolated_cache_dir):
        """A truncated / non-gzip file must not crash load()."""
        from ndi.cloud import signed_url_disk_cache as cache

        ds_dir = isolated_cache_dir / "ds1"
        ds_dir.mkdir(parents=True)
        (ds_dir / "doc1.json.gz").write_bytes(b"not a gzip")

        assert cache.load("ds1", "doc1", "") is None


# ---------------------------------------------------------------------------
# Integration with BatchSignedUrlLookup
# ---------------------------------------------------------------------------


class TestBatchLookupDiskCacheWiring:
    """Second call across a fresh in-memory cache must skip the signer.

    This is the whole reopen story: run 1 signs, disk saves; run 2
    reads disk and never touches the signer -- whether that signer
    would have been the paging walk or the async job.
    """

    def _counting_signer(self, files_map, expiry_iso):
        """Signer that counts calls and hands back a valid, cacheable answer."""

        state = {"count": 0}

        def signer(dataset_id, document_id, *, file_series="", client=None):
            state["count"] += 1
            return True, {
                "files": dict(files_map),
                "filesExpireAt": expiry_iso,
                "expiresAt": expiry_iso,
                "generatedAt": expiry_iso,
                "fileCount": len(files_map),
            }

        return signer, state

    def test_reopen_reads_disk_and_skips_signer(self, isolated_cache_dir):
        from ndi.cloud.batch_signed_url import BatchSignedUrlLookup

        files_map = {
            "4192a3c0dd1b4e00_3fe8a1b2c3d4e5f6": "https://s3/one",
            "4192a3c0dd1b4e00_4fe8a1b2c3d4e5f6": "https://s3/two",
        }
        signer, state = self._counting_signer(files_map, future_iso(23 * 3600))

        # Run 1: cold. One signer call answers both uids.
        lookup1 = BatchSignedUrlLookup(signer=signer, disk_cache=True)
        u1a = lookup1.lookup(
            "ds-e2e",
            "doc-e2e",
            "chunk.bin",
            "4192a3c0dd1b4e00_3fe8a1b2c3d4e5f6",
        )
        u1b = lookup1.lookup(
            "ds-e2e",
            "doc-e2e",
            "chunk.bin",
            "4192a3c0dd1b4e00_4fe8a1b2c3d4e5f6",
        )
        assert u1a == "https://s3/one"
        assert u1b == "https://s3/two"
        assert state["count"] == 1

        # And the disk file lands.
        disk_file = isolated_cache_dir / "ds-e2e" / "doc-e2e_chunk.bin.json.gz"
        assert disk_file.is_file()

        # Run 2: fresh in-memory cache; the disk should carry both uids.
        lookup2 = BatchSignedUrlLookup(signer=signer, disk_cache=True)
        u2a = lookup2.lookup(
            "ds-e2e",
            "doc-e2e",
            "chunk.bin",
            "4192a3c0dd1b4e00_3fe8a1b2c3d4e5f6",
        )
        u2b = lookup2.lookup(
            "ds-e2e",
            "doc-e2e",
            "chunk.bin",
            "4192a3c0dd1b4e00_4fe8a1b2c3d4e5f6",
        )
        assert u2a == "https://s3/one"
        assert u2b == "https://s3/two"
        assert state["count"] == 1, (
            "run 2 must have hit the disk cache -- signer must not have " "been called again"
        )

    def test_disk_cache_off_by_default_signs_every_cold_run(self, isolated_cache_dir):
        """The default (disk_cache=False) preserves pre-cache behaviour."""
        from ndi.cloud.batch_signed_url import BatchSignedUrlLookup

        signer, state = self._counting_signer({"aa_bb": "https://s3/x"}, future_iso(23 * 3600))

        for _ in range(3):
            lookup = BatchSignedUrlLookup(signer=signer)  # disk_cache=False
            lookup.lookup("ds-off", "doc-off", "", "aa_bb")

        assert state["count"] == 3
        # And nothing lands on disk.
        assert not (isolated_cache_dir / "ds-off").exists()
