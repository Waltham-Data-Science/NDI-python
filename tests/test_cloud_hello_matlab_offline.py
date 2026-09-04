"""ndi.cloud.helloMatlab, without a cloud account or an EC2 instance.

MATLAB counterpart: ``src/ndi/+ndi/+cloud/helloMatlab.m``

``tests/test_cloud_hello_matlab.py`` runs the real pipeline: it needs
credentials, a registered MATLAB BYOL license, and an opt-in environment
variable, because a run boots a billed EC2 instance for two to four
minutes. That test is the proof the port works. It is not a test that can
run on every commit, and every branch in helloMatlab that MATTERS is a
branch it does not take -- the license refusal, the status endpoint
failing mid-poll, the pipeline never finishing.

So these tests drive the same function with a stubbed compute API. What
they are really about is the failure paths: helloMatlab exists to report
WHY a BYOL registration does not work, and a diagnostic that garbles the
diagnosis is worse than none.

The one difference from MATLAB worth watching is the start call. MATLAB's
``ndi.cloud.api.compute.startSession`` returns ``[b, answer, ...]`` and
helloMatlab branches on ``b``; the Python wrapper raises CloudAPIError
instead, so the payload that carries MATLAB_LICENSE_REQUIRED has to be
read off the exception. Getting that wrong turns a precise, actionable
message into "API error (HTTP 400)".
"""

from __future__ import annotations

import types

import pytest

from ndi.cloud.exceptions import CloudAPIError
from ndi.cloud.orchestration import (
    HELLO_MATLAB_PIPELINE_ID,
    HelloMatlabResult,
    _hello_matlab_verdict,
    _session_id_from,
    _start_failure_message,
    _verify_stage,
    helloMatlab,
)


class FakeClient:
    """Stands in for an authenticated CloudClient."""

    config = types.SimpleNamespace(org_id="org", api_url="https://example.invalid")


def session_doc(*, session_status="RUNNING", stage_status="RUNNING", message="", instance=""):
    """A compute session document shaped like the API's."""
    return {
        "status": session_status,
        "history": {
            "verify": {
                "status": stage_status,
                "statusMessage": message,
                "awsResourceId": instance,
            }
        },
    }


@pytest.fixture
def compute(monkeypatch):
    """Stub ndi.cloud.api.compute and record what helloMatlab asked for.

    ``polls`` is a list of documents returned one per call, so a test can
    describe a pipeline that runs for a while and then finishes.
    """
    box = types.SimpleNamespace(started=[], polls=[], start_result=None)

    def startSession(pipeline_id, input_params=None, *, client=None):  # noqa: N802
        box.started.append(pipeline_id)
        if isinstance(box.start_result, Exception):
            raise box.start_result
        return box.start_result

    def getSessionStatus(session_id, *, client=None):  # noqa: N802
        result = box.polls.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    # helloMatlab does ``from .api import compute as compute_api`` inside
    # the function, so the attribute on the package is what it resolves.
    import ndi.cloud.api

    fake = types.SimpleNamespace(startSession=startSession, getSessionStatus=getSessionStatus)
    monkeypatch.setattr(ndi.cloud.api, "compute", fake, raising=False)
    return box


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    """Nothing here should ever actually wait."""
    import time

    monkeypatch.setattr(time, "sleep", lambda s: None)


class TestTheHappyPath:
    def test_it_runs_the_hello_matlab_pipeline(self, compute):
        compute.start_result = {"sessionId": "sess-1"}
        compute.polls = [session_doc(stage_status="COMPLETED", message="MATLAB R2024b ready")]

        result = helloMatlab(verbose=False, client=FakeClient())

        assert compute.started == [HELLO_MATLAB_PIPELINE_ID]
        assert result.success is True
        assert result.sessionId == "sess-1"
        assert result.statusMessage == "MATLAB R2024b ready"

    def test_it_unpacks_in_matlabs_output_order(self, compute):
        """``[success, sessionId, statusMessage, sessionDoc] =
        ndi.cloud.helloMatlab()`` is the MATLAB call. A caller porting that
        line unpacks it positionally, so the order is part of the contract."""
        compute.start_result = {"sessionId": "sess-1"}
        compute.polls = [session_doc(stage_status="COMPLETED", message="ok")]

        success, session_id, status_message, doc = helloMatlab(verbose=False, client=FakeClient())

        assert (success, session_id, status_message) == (True, "sess-1", "ok")
        assert doc["status"] == "RUNNING"

    def test_it_polls_until_the_stage_terminates(self, compute):
        compute.start_result = {"sessionId": "sess-1"}
        compute.polls = [
            session_doc(stage_status="PENDING"),
            session_doc(stage_status="RUNNING", instance="i-abc"),
            session_doc(stage_status="COMPLETED", message="done"),
        ]

        result = helloMatlab(verbose=False, poll_interval_seconds=0, client=FakeClient())

        assert compute.polls == []
        assert result.success is True


class TestTheLicenseRefusal:
    """The failure a user will actually hit, and the reason this is a
    diagnostic rather than a smoke test.

    Without a registered BYOL license the API refuses the start call with
    HTTP 400 and a payload naming the code and the release it needs. The
    fix is the user's to make, so the message has to say what it is.
    """

    def test_matlab_license_required_names_the_release_and_the_fix(self, compute):
        compute.start_result = CloudAPIError(
            "API error (HTTP 400)",
            status_code=400,
            response_body={"code": "MATLAB_LICENSE_REQUIRED", "requiredRelease": "R2024b"},
        )

        result = helloMatlab(verbose=False, client=FakeClient())

        assert result.success is False
        assert "MATLAB_LICENSE_REQUIRED" in result.statusMessage
        assert "R2024b" in result.statusMessage
        assert "allocateMatlabLicenseMac" in result.statusMessage

    def test_decrypt_failure_carries_the_servers_error(self, compute):
        compute.start_result = CloudAPIError(
            "API error (HTTP 400)",
            status_code=400,
            response_body={
                "code": "MATLAB_LICENSE_DECRYPT_FAILED",
                "requiredRelease": "R2024b",
                "error": "bad key",
            },
        )

        result = helloMatlab(verbose=False, client=FakeClient())

        assert result.statusMessage == "MATLAB_LICENSE_DECRYPT_FAILED for R2024b: bad key"

    def test_an_unrecognized_code_is_still_reported_verbatim(self, compute):
        compute.start_result = CloudAPIError(
            "API error (HTTP 400)",
            status_code=400,
            response_body={"code": "PIPELINE_DISABLED", "message": "temporarily off"},
        )

        result = helloMatlab(verbose=False, client=FakeClient())

        assert result.statusMessage == "PIPELINE_DISABLED: temporarily off"

    def test_a_failure_with_no_payload_falls_back_to_the_exception(self, compute):
        """An error formatter that has nothing to format must still say
        something -- returning "" would report a refusal as a blank."""
        compute.start_result = CloudAPIError("Request failed: connection reset")

        result = helloMatlab(verbose=False, client=FakeClient())

        assert result.success is False
        assert "connection reset" in result.statusMessage

    def test_no_session_is_reported_when_the_start_failed(self, compute):
        compute.start_result = CloudAPIError("nope", status_code=400, response_body={})
        result = helloMatlab(verbose=False, client=FakeClient())
        assert result.sessionId == ""


class TestTheThingsThatGoWrongMidRun:
    def test_a_failed_stage_reports_matlabs_own_message(self, compute):
        """The License Manager string is the whole point: it is what MATLAB
        on the EC2 instance said about the license, and no other layer can
        produce it."""
        compute.start_result = {"sessionId": "sess-1"}
        compute.polls = [
            session_doc(
                stage_status="FAILED",
                message="License Manager Error -9: Your username does not match",
            )
        ]

        result = helloMatlab(verbose=False, client=FakeClient())

        assert result.success is False
        assert "License Manager Error -9" in result.statusMessage

    def test_an_aborted_session_is_a_failure_not_a_wait(self, compute):
        compute.start_result = {"sessionId": "sess-1"}
        compute.polls = [session_doc(session_status="ABORTED")]

        assert helloMatlab(verbose=False, client=FakeClient()).success is False

    def test_a_transient_status_failure_keeps_polling(self, compute):
        """A billed instance is already running; one failed status call must
        not end the run."""
        compute.start_result = {"sessionId": "sess-1"}
        compute.polls = [
            CloudAPIError("gateway timeout", status_code=504),
            session_doc(stage_status="COMPLETED", message="done"),
        ]

        result = helloMatlab(verbose=False, poll_interval_seconds=0, client=FakeClient())

        assert result.success is True

    def test_a_transient_status_failure_is_logged_not_swallowed(self, compute, caplog):
        """MATLAB retries silently. A status endpoint that fails on every one
        of the polls then looks exactly like a slow pipeline, and this
        function's entire job is to tell the caller which happened."""
        compute.start_result = {"sessionId": "sess-1"}
        compute.polls = [
            CloudAPIError("gateway timeout", status_code=504),
            session_doc(stage_status="COMPLETED"),
        ]

        with caplog.at_level("WARNING", logger="ndi.cloud.orchestration"):
            helloMatlab(verbose=False, poll_interval_seconds=0, client=FakeClient())

        assert any("gateway timeout" in r.getMessage() for r in caplog.records)

    def test_polling_stops_at_the_deadline(self, compute):
        compute.start_result = {"sessionId": "sess-1"}
        compute.polls = [session_doc() for _ in range(50)]

        result = helloMatlab(
            timeout_seconds=-1, poll_interval_seconds=0, verbose=False, client=FakeClient()
        )

        assert result.success is False
        assert "timed out" in result.statusMessage
        assert result.sessionId == "sess-1", "the session id is what lets a caller abort it"

    def test_a_start_with_no_session_id_says_so(self, compute):
        """The worst outcome: a session that may be running and billing,
        with no id to abort it. It must not be reported as a plain failure
        to start."""
        compute.start_result = {"unexpected": "shape"}

        result = helloMatlab(verbose=False, client=FakeClient())

        assert result.success is False
        assert result.statusMessage == "start response had no sessionId"
        assert result.sessionDoc == {"unexpected": "shape"}


class TestThePureParts:
    """The decisions, separated from the clock and the network.

    Each of these determines whether a twenty-minute wait ends at minute
    one, so they are worth testing directly rather than only through a
    stubbed run.
    """

    @pytest.mark.parametrize(
        "session_status,stage_status,expected",
        [
            ("RUNNING", "COMPLETED", True),
            ("COMPLETED", "RUNNING", True),
            ("RUNNING", "FAILED", False),
            ("FAILED", "RUNNING", False),
            ("ABORTED", "RUNNING", False),
            ("RUNNING", "RUNNING", None),
            ("PENDING", "", None),
            ("", "", None),
        ],
    )
    def test_the_terminal_state_rule(self, session_status, stage_status, expected):
        assert _hello_matlab_verdict(session_status, stage_status) is expected

    @pytest.mark.parametrize(
        "answer,expected",
        [
            ({"sessionId": "a"}, "a"),
            ({"id": "b"}, "b"),
            ({"sessionId": "a", "id": "b"}, "a"),
            ({}, ""),
            ({"sessionId": ""}, ""),
            (None, ""),
        ],
    )
    def test_the_session_id_is_read_under_either_spelling(self, answer, expected):
        """The API has answered with both. Reporting "no sessionId" for a
        session that started leaves it running with no way to abort it."""
        assert _session_id_from(answer) == expected

    def test_the_verify_stage_is_empty_rather_than_absent(self):
        """A session document without history is an ordinary early state,
        not an error -- so it must read as an empty stage, not raise."""
        assert _verify_stage({}) == {}
        assert _verify_stage({"history": None}) == {}
        assert _verify_stage({"history": {"other": {}}}) == {}
        assert _verify_stage(session_doc(stage_status="RUNNING"))["status"] == "RUNNING"

    def test_the_start_failure_message_is_never_empty(self):
        """Whatever shape the refusal arrives in, the caller gets words."""
        for body in ({}, None, "", {"code": ""}, [1, 2]):
            exc = CloudAPIError("boom", status_code=400, response_body=body)
            assert _start_failure_message(exc).strip()


class TestTheResultShape:
    def test_it_is_a_named_tuple_with_matlabs_names(self):
        assert HelloMatlabResult._fields == (
            "success",
            "sessionId",
            "statusMessage",
            "sessionDoc",
        )

    def test_the_live_test_reads_it_as_a_tuple(self):
        """tests/test_cloud_hello_matlab.py branches on ``isinstance(result,
        dict)`` and otherwise takes ``result[0]`` and ``result[2]``. A
        NamedTuple takes that second branch, so the live test activates
        without modification -- which was the shape it was written to."""
        result = HelloMatlabResult(True, "sess", "message", {})
        assert not isinstance(result, dict)
        assert result[0] is True
        assert result[2] == "message"


class TestItIsReachableTheWayMatlabSpellsIt:
    def test_ndi_cloud_hello_matlab(self):
        """``ndi.cloud.helloMatlab(...)`` is the MATLAB call site, and
        ``orchestration`` is an implementation detail of this port."""
        import ndi.cloud

        assert ndi.cloud.helloMatlab is helloMatlab
        assert "helloMatlab" in ndi.cloud.__all__


if __name__ == "__main__":
    pytest.main([__file__])
