"""The launch says how far along a cloud fetch is, not just that one started.

stage() printed a label and then nothing moved until the step finished. On
a directory-backed session that is fine -- the reads are milliseconds. On a
cloud-backed one the cell table, the contour file and the gene list are
each a whole download before the window can appear, and a static label for
a minute is indistinguishable from a hang.

getFile is the one place every on-demand fetch passes through, so the byte
counts are taken there and surfaced through a module-level observer: DID
fixes the file handler's signature (it counts positional parameters to
choose between the two- and three-argument forms), so there is nowhere to
thread a callback through from a caller.
"""

import io
import sys
import unittest
from unittest import mock

from ndi.cloud import filehandler
from ndi.gui.app.genepyramid import progress


class TestHumanBytes(unittest.TestCase):
    def test_it_reads_at_a_glance(self):
        self.assertEqual(progress.humanBytes(0), "0 B")
        self.assertEqual(progress.humanBytes(900), "900 B")
        self.assertEqual(progress.humanBytes(26214400), "25.0 MB")

    def test_a_big_file_does_not_become_a_wall_of_digits(self):
        self.assertEqual(progress.humanBytes(3 * 1024**3), "3.0 GB")


class TestTheObserverHook(unittest.TestCase):
    def test_it_is_absent_by_default(self):
        self.assertIsNone(filehandler._fetch_observer)

    def test_it_is_installed_for_the_block_and_removed_after(self):
        seen = []
        with filehandler.watchFetches(lambda *a: seen.append(a)):
            self.assertIsNotNone(filehandler._fetch_observer)
        self.assertIsNone(filehandler._fetch_observer)

    def test_a_raise_inside_the_block_still_removes_it(self):
        with self.assertRaises(ValueError):
            with filehandler.watchFetches(lambda *a: None):
                raise ValueError("boom")
        self.assertIsNone(filehandler._fetch_observer)

    def test_nesting_restores_the_outer_one_rather_than_clearing(self):
        outer = lambda *a: None  # noqa: E731
        with filehandler.watchFetches(outer):
            with filehandler.watchFetches(lambda *a: None):
                pass
            self.assertIs(filehandler._fetch_observer, outer)
        self.assertIsNone(filehandler._fetch_observer)


class _FakeResponse:
    """Enough of requests.Response for getFile's streaming branch."""

    status_code = 200

    def __init__(self, chunks, length=None):
        self._chunks = chunks
        self.headers = {} if length is None else {"Content-Length": str(length)}

    def iter_content(self, chunk_size=8192):  # noqa: ARG002
        yield from self._chunks


class TestGetFileReportsBytes(unittest.TestCase):
    def _run(self, chunks, length, progress_fn, tmp):
        from ndi.cloud.api import files as files_api

        with mock.patch("requests.get", return_value=_FakeResponse(chunks, length)):
            return files_api.getFile("https://example.invalid/x", tmp, progress=progress_fn)

    def setUp(self):
        import tempfile
        from pathlib import Path

        self.dir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))
        self.tmp = Path(self.dir) / "out.bin"

    def test_the_running_total_is_cumulative_not_per_chunk(self):
        seen = []
        self._run([b"a" * 10, b"b" * 5], 15, lambda d, t: seen.append((d, t)), self.tmp)
        self.assertEqual(seen, [(10, 15), (15, 15)])

    def test_the_total_comes_from_content_length(self):
        seen = []
        self._run([b"x" * 4], 4, lambda d, t: seen.append((d, t)), self.tmp)
        self.assertEqual(seen[-1][1], 4)

    def test_a_chunked_response_reports_no_total_rather_than_guessing(self):
        seen = []
        self._run([b"x" * 4], None, lambda d, t: seen.append((d, t)), self.tmp)
        self.assertIsNone(seen[-1][1])

    def test_a_nonsense_content_length_is_no_total_rather_than_a_crash(self):
        from ndi.cloud.api import files as files_api

        resp = _FakeResponse([b"x"], None)
        resp.headers = {"Content-Length": "banana"}
        seen = []
        with mock.patch("requests.get", return_value=resp):
            files_api.getFile(
                "https://example.invalid/x", self.tmp, progress=lambda d, t: seen.append((d, t))
            )
        self.assertIsNone(seen[-1][1])

    def test_the_file_still_lands_when_the_callback_throws(self):
        # A reporting callback must never cost the download.
        def boom(done, total):
            raise RuntimeError("renderer died")

        ok = self._run([b"a" * 8, b"b" * 8], 16, boom, self.tmp)
        self.assertTrue(ok)
        self.assertEqual(self.tmp.read_bytes(), b"a" * 8 + b"b" * 8)

    def test_no_callback_is_the_untouched_path(self):
        ok = self._run([b"z" * 3], 3, None, self.tmp)
        self.assertTrue(ok)
        self.assertEqual(self.tmp.read_bytes(), b"z" * 3)


class TestTheRendererStaysOutOfLogs(unittest.TestCase):
    def test_a_non_tty_gets_no_redrawn_line(self):
        # A \r-redrawn bar becomes thousands of lines in a CI capture, so
        # it is suppressed there; the stage timings still say what happened.
        buf = io.StringIO()  # StringIO.isatty() is False
        with mock.patch.object(sys, "stderr", buf):
            with progress.cloudFetches("reading"):
                self.assertIsNone(filehandler._fetch_observer)
        self.assertEqual(buf.getvalue(), "")

    def test_quiet_suppresses_it_too(self):
        import os

        with mock.patch.dict(os.environ, {"NDI_GENEPYRAMID_QUIET": "1"}):
            with progress.cloudFetches("reading"):
                self.assertIsNone(filehandler._fetch_observer)


if __name__ == "__main__":
    unittest.main()
