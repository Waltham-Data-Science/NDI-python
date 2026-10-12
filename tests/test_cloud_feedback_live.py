"""
Live tests for the in-app problem report endpoints.

Ported from NDI-matlab tests/+ndi/+unittest/+cloud/feedbackTest.m
(75f937a76, NDI-matlab#1023). Exercises ndi.cloud.api.feedback against
the real API (ndi-cloud-node#158):

    POST   /feedback
    DELETE /feedback/{feedbackId}

Every report a test submits is deleted again -- by the test itself, or by
the ``submitted`` fixture's teardown if the test fails part-way -- so the
suite does not leave reports in the admin triage queue. Deleted reports do
not count against the server's limit of 10 reports per user per hour.

Where MATLAB checks ``b == false`` and a status code, Python checks the
exception the call raises and its ``status_code``, since every
ndi.cloud.api function raises on a non-2xx response.

The client-side validation tests of feedbackTest.m
(testWrapperRejectsUnknownCategory / testWrapperRejectsEmptyDescription)
need no network and live in tests/test_cloud_api_feedback.py.

Environment variables consumed:
    NDI_CLOUD_USERNAME / NDI_CLOUD_PASSWORD -- skip if absent (standard
        live-test pattern, matches test_cloud_live.py).
    CLOUD_API_ENVIRONMENT -- 'prod' (default) or 'dev'. The module skips
        in an environment that does not have the feedback endpoint yet.
"""

from __future__ import annotations

import os
import platform
import sys

import pytest

_has_creds = bool(os.environ.get("NDI_CLOUD_USERNAME") and os.environ.get("NDI_CLOUD_PASSWORD"))
pytestmark = pytest.mark.skipif(not _has_creds, reason="NDI cloud credentials not set")

APP_NAME = "NDI-python-unittest"
#: Valid 24-hex id that will not match any stored report.
NONEXISTENT_ID = "000000000000000000000000"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cloud_config():
    """Authenticate once for the entire module and return config."""
    from ndi.cloud.auth import login
    from ndi.cloud.config import CloudConfig

    config = CloudConfig.from_env()
    config = login(config=config)
    assert config.is_authenticated, "Login failed -- no token received"
    return config


@pytest.fixture(scope="module")
def client(cloud_config):
    """Return an authenticated CloudClient."""
    from ndi.cloud.client import CloudClient

    return CloudClient(cloud_config)


@pytest.fixture(scope="module", autouse=True)
def endpoint_deployed(client):
    """Skip (rather than fail) where the feedback endpoint is not deployed.

    The cloud suite runs against both prod and dev. Once deployed, a
    malformed id is answered 400 by the route; before that, the API's
    catch-all answers 404. Mirrors feedbackTest.checkEndpointDeployed.
    """
    from ndi.cloud.api.feedback import deleteFeedback
    from ndi.cloud.exceptions import CloudAPIError, CloudNotFoundError

    try:
        deleteFeedback("not-a-valid-id", client=client)
    except CloudNotFoundError:
        pytest.skip("The /feedback endpoint is not deployed in this API environment")
    except CloudAPIError:
        pass


@pytest.fixture()
def submitted(client):
    """Collect ids of submitted reports; delete any still present at teardown.

    Mirrors feedbackTest.registerCleanup. A 404 here just means the test
    already deleted the report itself.
    """
    from ndi.cloud.api.feedback import deleteFeedback
    from ndi.cloud.exceptions import CloudError

    ids: list[str] = []
    yield ids
    for feedback_id in ids:
        try:
            deleteFeedback(feedback_id, client=client)
        except CloudError:
            pass


def _submit_raw(client, body):
    """POST BODY as-is, bypassing the wrapper's own validation.

    MATLAB reaches the server's validation through the implementation class
    ndi.cloud.api.implementation.feedback.SubmitFeedback; feedback._submit
    is its counterpart.
    """
    from ndi.cloud.api.feedback import _submit

    return _submit(body, client=client)


def _expect_rejected(client, submitted, body, status):
    """Submit BODY raw and require the server to refuse it with STATUS."""
    from ndi.cloud.exceptions import CloudAPIError

    try:
        result = _submit_raw(client, body)
    except CloudAPIError as exc:
        assert exc.status_code == status, exc
        return
    submitted.append(result.data)
    pytest.fail(f"server accepted an invalid report (id {result.data}); expected HTTP {status}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFeedbackLive:
    def test_submit_and_delete(self, client, submitted):
        """Submit a minimal report, delete it, and confirm a second delete is 404."""
        from ndi.cloud.api.feedback import deleteFeedback, submitFeedback
        from ndi.cloud.exceptions import CloudNotFoundError

        b, feedback_id, status, url = submitFeedback(
            APP_NAME, "other", "feedbackTest: minimal report (safe to ignore)", client=client
        )
        assert b is True, url
        assert status == 201, url
        assert isinstance(feedback_id, str) and feedback_id, url
        submitted.append(feedback_id)

        b_del, answer, status_del, url_del = deleteFeedback(feedback_id, client=client)
        assert b_del is True, url_del
        assert status_del == 204, url_del
        assert answer == "Feedback deleted successfully."

        with pytest.raises(CloudNotFoundError):
            deleteFeedback(feedback_id, client=client)

    def test_submit_full_report(self, client, submitted):
        """Every optional field, including a log carrying credentials to redact.

        The reporter cannot read reports back, so redaction itself is
        checked in the server's own tests.
        """
        from ndi.cloud.api.feedback import deleteFeedback, submitFeedback

        environment = {
            "os": platform.platform(),
            "python": sys.version.split()[0],
            "launchedFrom": "pytest",
        }
        state = {"level": 3, "fetchStats": {"ok": 10, "failed": 2}}
        fake_token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1bml0dGVzdCJ9.c2lnbmF0dXJlX3VuaXR0ZXN0"
        log_text = (
            "[lightsheet] GET https://bucket.s3.amazonaws.com/k?X-Amz-Signature=deadbeef01\n"
            f"Authorization: Bearer {fake_token}"
        )

        result = submitFeedback(
            APP_NAME,
            "bug",
            "feedbackTest: full report (safe to ignore)",
            appVersion="NDI-python unittest",
            datasetId=NONEXISTENT_ID,
            documentId="unittest-document",
            environment=environment,
            state=state,
            log=log_text,
            traceback="feedbackTest: no real traceback",
            client=client,
        )
        assert result.success, result.url
        assert result.status_code == 201, result.url
        submitted.append(result.data)

        assert deleteFeedback(result.data, client=client).success

    def test_invalid_category_is_rejected(self, client, submitted):
        body = {
            "schemaVersion": 1,
            "app": APP_NAME,
            "category": "feature",
            "description": "feedbackTest: invalid category",
        }
        _expect_rejected(client, submitted, body, 400)

    def test_missing_description_is_rejected(self, client, submitted):
        body = {"schemaVersion": 1, "app": APP_NAME, "category": "bug"}
        _expect_rejected(client, submitted, body, 400)

    def test_unsupported_schema_version_is_rejected(self, client, submitted):
        body = {
            "schemaVersion": 99,
            "app": APP_NAME,
            "category": "bug",
            "description": "feedbackTest: bad schemaVersion",
        }
        _expect_rejected(client, submitted, body, 400)

    def test_oversize_log_is_rejected(self, client, submitted):
        """A log over the 500,000-character field cap but under the 1 MB request cap."""
        from ndi.cloud.api.feedback import submitFeedback
        from ndi.cloud.exceptions import CloudAPIError

        try:
            result = submitFeedback(
                APP_NAME,
                "performance",
                "feedbackTest: oversize log",
                log="x" * 600_000,
                client=client,
            )
        except CloudAPIError as exc:
            assert exc.status_code == 413, exc
            return
        submitted.append(result.data)
        pytest.fail("server accepted a 600,000-character log; expected HTTP 413")

    def test_unauthenticated_submit_is_rejected(self, cloud_config):
        """No token: refused. The API answers 403 throughout; 401 is accepted too."""
        from ndi.cloud.api.feedback import submitFeedback
        from ndi.cloud.client import CloudClient
        from ndi.cloud.config import CloudConfig
        from ndi.cloud.exceptions import CloudAuthError

        anonymous = CloudClient(CloudConfig(api_url=cloud_config.api_url, token=""))
        with pytest.raises(CloudAuthError):
            submitFeedback(APP_NAME, "bug", "feedbackTest: no token", client=anonymous)

    def test_delete_nonexistent_report(self, client):
        from ndi.cloud.api.feedback import deleteFeedback
        from ndi.cloud.exceptions import CloudNotFoundError

        with pytest.raises(CloudNotFoundError):
            deleteFeedback(NONEXISTENT_ID, client=client)

    def test_delete_malformed_id(self, client):
        from ndi.cloud.api.feedback import deleteFeedback
        from ndi.cloud.exceptions import CloudAPIError

        with pytest.raises(CloudAPIError) as excinfo:
            deleteFeedback("not-a-valid-id", client=client)
        assert excinfo.value.status_code == 400
