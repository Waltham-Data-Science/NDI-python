"""A user can report a problem from inside a viewer in one step.

The report carries what the viewer knows (versions, state, recent log)
without carrying credentials -- viewer logs do contain signed S3 URLs
and can contain bearer tokens -- and fits the server's size limits.
"""

import io
import json
import os
import sys

import pytest

from ndi.gui import feedback

# ------------------------------------------------------------ scrub


class TestScrub:
    def test_signed_url_credentials_are_removed(self):
        url = (
            "https://bucket.s3.amazonaws.com/chunk.bin_7?X-Amz-Algorithm=AWS4-HMAC-SHA256"
            "&X-Amz-Credential=ASIAXYZ%2F20261012&X-Amz-Security-Token=IQoJb3JpZ2lu"
            "&X-Amz-Signature=deadbeef1234&X-Amz-Expires=3600"
        )
        out = feedback.scrub(url)
        for secret in ("ASIAXYZ", "IQoJb3JpZ2lu", "deadbeef1234"):
            assert secret not in out
        # The non-secret parts stay, so the log is still readable.
        assert "chunk.bin_7" in out and "X-Amz-Expires=3600" in out

    def test_bearer_tokens_and_jwts_are_removed(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.c2lnbmF0dXJl"
        out = feedback.scrub(f"Authorization: Bearer abc.def-123 and later {jwt}")
        assert "abc.def-123" not in out and jwt not in out

    def test_secret_named_values_are_removed(self):
        out = feedback.scrub('password=hunter2 "api_key": "k-999" NDI_CLOUD_TOKEN=xyz')
        for secret in ("hunter2", "k-999", "xyz"):
            assert secret not in out

    def test_ordinary_log_lines_survive(self):
        line = "12:00:01.123 [lightsheet] tiles: 56 loaded / 112 requested (in flight: 8)"
        assert feedback.scrub(line) == line


# ------------------------------------------------------------ log buffer


class TestLogBuffer:
    def test_lines_are_kept_and_redraws_keep_their_last_state(self):
        buf = feedback.LogBuffer(max_lines=10)
        buf.feed("first line\n[lightsheet] 10%\r[lightsheet] 50%\r[lightsheet] 100%\nthird")
        assert buf.text().splitlines() == ["first line", "[lightsheet] 100%", "third"]

    def test_only_the_newest_lines_are_kept(self):
        buf = feedback.LogBuffer(max_lines=3)
        buf.feed("".join(f"line {i}\n" for i in range(10)))
        assert buf.text().splitlines() == ["line 7", "line 8", "line 9"]

    def test_the_tee_still_writes_through(self):
        real = io.StringIO()
        buf = feedback.LogBuffer()
        tee = feedback._Tee(real, buf)
        print("hello", file=tee)
        assert real.getvalue() == "hello\n"
        assert buf.text() == "hello"


# ------------------------------------------------------------ report


class TestBuildReport:
    def test_payload_fields_match_the_api(self):
        rep = feedback.buildReport(
            "lightsheetZarr-viewer",
            "performance",
            "slow zoom",
            datasetId="ds1",
            documentId="doc1",
            state={"view": {"ready": 56, "needed": 112}},
            log="a\nb",
        )
        assert rep["app"] == "lightsheetZarr-viewer"
        assert rep["category"] == "performance"
        assert rep["description"] == "slow zoom"
        assert rep["datasetId"] == "ds1" and rep["documentId"] == "doc1"
        assert rep["state"] == {"view": {"ready": 56, "needed": 112}}
        assert rep["log"] == "a\nb"
        assert rep["appVersion"].startswith("NDI-python")
        assert "python" in rep["environment"]
        # Every key is one submitFeedback accepts.
        import inspect

        from ndi.cloud.api.feedback import submitFeedback

        params = inspect.signature(submitFeedback).parameters
        assert set(rep) <= set(params)

    def test_unset_optional_fields_are_left_out(self):
        rep = feedback.buildReport("app", "bug", "d")
        for key in ("datasetId", "documentId", "state", "log", "traceback"):
            assert key not in rep

    def test_secrets_in_state_env_and_log_are_scrubbed(self, monkeypatch):
        monkeypatch.setenv("NDI_CLOUD_PASSWORD", "hunter2")
        monkeypatch.setenv("NDI_LIGHTSHEET_DEBUG", "1")
        rep = feedback.buildReport(
            "app",
            "bug",
            "d",
            state={"url": "https://x/y?X-Amz-Signature=abc123", "token": "t0k"},
            log="Bearer sekrit",
        )
        blob = json.dumps(rep)
        for secret in ("hunter2", "abc123", "t0k", "sekrit"):
            assert secret not in blob
        assert rep["environment"]["flags"]["NDI_LIGHTSHEET_DEBUG"] == "1"

    def test_a_huge_log_is_cut_to_the_server_limit_keeping_the_end(self):
        log = "".join(f"line {i}\n" for i in range(200_000))
        rep = feedback.buildReport("app", "bug", "d", log=log)
        assert len(rep["log"]) <= feedback.MAX_LOG
        assert rep["log"].rstrip().endswith("line 199999")
        assert "earlier characters cut" in rep["log"]

    def test_an_oversized_state_is_replaced_by_a_note(self):
        rep = feedback.buildReport("app", "bug", "d", state={"big": "x" * 300_000})
        assert "_note" in rep["state"]
        assert len(json.dumps(rep["state"])) < feedback.MAX_STATE_JSON + 1000


class TestSendAndSave:
    def test_send_returns_the_stored_id(self, monkeypatch):
        seen = {}

        def fake_submit(**kwargs):
            seen.update(kwargs)
            return (True, "6710aa", 201, "https://api/v1/feedback")

        import ndi.cloud.api.feedback as api

        monkeypatch.setattr(api, "submitFeedback", fake_submit)
        rep = feedback.buildReport("app", "bug", "d")
        assert feedback.sendReport(rep) == "6710aa"
        assert seen["app"] == "app"

    def test_save_writes_the_report_with_its_schema_version(self, tmp_path):
        path = tmp_path / "r.json"
        feedback.saveReport(feedback.buildReport("app", "other", "d"), str(path))
        body = json.loads(path.read_text())
        assert body["schemaVersion"] == 1 and body["description"] == "d"

    @pytest.mark.parametrize(
        "status, phrase",
        [(429, "Too many"), (413, "too large"), (404, "does not accept"), (500, "HTTP 500")],
    )
    def test_errors_read_as_something_a_user_can_act_on(self, status, phrase):
        from ndi.cloud.exceptions import CloudAPIError

        assert phrase in feedback.describeSendError(CloudAPIError("x", status_code=status))

    def test_not_signed_in_says_so(self):
        from ndi.cloud.exceptions import CloudAuthError

        assert "Not signed in" in feedback.describeSendError(CloudAuthError("no"))


# ------------------------------------------------------------ dialog


@pytest.fixture
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from qtpy.QtWidgets import QApplication
    except Exception:
        pytest.skip("no Qt binding")
    return QApplication.instance() or QApplication([])


def _wait(qapp, cond, timeout=5.0):
    import time

    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.02)
    return cond()


class TestDialog:
    def test_send_is_off_until_the_user_says_something(self, qapp):
        dlg = feedback.FeedbackDialog(app="a", collect=dict, send=lambda r: "id")
        assert not dlg.sendButton.isEnabled()
        dlg.description.setPlainText("it froze")
        assert dlg.sendButton.isEnabled()

    def test_sending_reports_the_id_and_carries_the_collected_state(self, qapp):
        sent = []
        dlg = feedback.FeedbackDialog(
            app="lightsheetZarr-viewer",
            collect=lambda: {"state": {"view": {"ready": 1, "needed": 2}}, "documentId": "p1"},
            send=lambda rep: sent.append(rep) or "6710aa",
        )
        dlg.category.setCurrentIndex(1)  # Slow
        dlg.description.setPlainText("zoom is slow")
        dlg.sendButton.click()
        assert _wait(qapp, lambda: dlg.feedbackID == "6710aa")
        assert "6710aa" in dlg.status.text()
        assert not dlg.sendButton.isEnabled(), "one report per dialog"
        (rep,) = sent
        assert rep["category"] == "performance"
        assert rep["state"]["view"] == {"ready": 1, "needed": 2}
        assert rep["documentId"] == "p1"

    def test_a_failed_send_says_what_to_do_and_can_be_retried(self, qapp):
        from ndi.cloud.exceptions import CloudAuthError

        def boom(rep):
            raise CloudAuthError("no token")

        dlg = feedback.FeedbackDialog(app="a", collect=dict, send=boom)
        dlg.description.setPlainText("x")
        dlg.sendButton.click()
        assert _wait(qapp, lambda: "Not signed in" in dlg.status.text())
        assert dlg.sendButton.isEnabled()

    def test_the_preview_shows_exactly_the_report(self, qapp):
        dlg = feedback.FeedbackDialog(
            app="a", collect=lambda: {"log": "Bearer sekrit"}, send=lambda r: "id"
        )
        dlg.description.setPlainText("x")
        dlg.toggle.setChecked(True)
        shown = json.loads(dlg.preview.toPlainText())
        assert shown["app"] == "a" and "sekrit" not in shown["log"]

    def test_a_broken_collector_still_produces_a_report(self, qapp):
        def broken():
            raise RuntimeError("viewer is wedged")

        dlg = feedback.FeedbackDialog(app="a", collect=broken, send=lambda r: "id")
        dlg.description.setPlainText("x")
        assert "viewer is wedged" in json.dumps(dlg.report())


def test_installing_the_log_buffer_tees_stderr(monkeypatch):
    monkeypatch.setattr(feedback, "_installed", None)
    real = io.StringIO()
    monkeypatch.setattr(sys, "stderr", real)
    buf = feedback.installLogBuffer()
    print("[lightsheet] hello", file=sys.stderr)
    assert "[lightsheet] hello" in buf.text()
    assert real.getvalue() == "[lightsheet] hello\n"
    assert feedback.installLogBuffer() is buf
    import logging

    for h in list(logging.getLogger().handlers):
        if isinstance(h, feedback._BufferHandler):
            logging.getLogger().removeHandler(h)
