"""The cloud client repeats a transient failure instead of giving up on it.

Issue #137. ``client.py`` had no retry of any kind -- it was byte-identical
to its version at the fork point -- so every request was a single attempt.

That matters here more than it would elsewhere. The API sits behind an API
Gateway whose Lambda cap is 29 s, and exceeding it surfaces as a **504**
rather than as a slow success. On large documents that is a routine
outcome, not an exceptional one, and a repeat of an idempotent request
usually succeeds once the backend catches up. Without a retry, one such
blip anywhere in a long multi-document sync failed that call and the
operation above it.

WHAT THESE TESTS PIN, AND WHY EACH ONE
The retry is easy to write and easy to get subtly wrong, and every wrong
version still passes a naive "it retried" test:

* Retrying a POST would be a correctness bug, not a tuning mistake: most
  POST routes create resources, so a repeat can duplicate them. The method
  allow-list is therefore asserted from both sides.
* Retrying a 4xx wastes the caller's time on a failure that will never
  change.
* Retrying without a bound turns an outage into a hang.
* Retrying without jitter synchronises every waiting client onto the
  moment the gateway recovers.

The transport is a stub rather than a mock: it counts what it was asked to
do and hands back canned responses, so an assertion about "how many
attempts" is about the request actually issued.
"""

from __future__ import annotations

import types

import pytest
import requests

from ndi.cloud.client import CloudClient
from ndi.cloud.config import CloudConfig
from ndi.cloud.exceptions import CloudAPIError, CloudAuthError


def response(status=200, body=None, text="", reason=""):
    """Something shaped like a ``requests.Response``."""

    def json():
        if body is None:
            raise ValueError("no json")
        return body

    return types.SimpleNamespace(
        status_code=status,
        reason=reason,
        json=json,
        text=text,
        content=text.encode() if text else b"",
        headers={},
        elapsed=None,
    )


class Transport:
    """A stub ``requests.Session`` that replays a scripted sequence.

    Each entry is either a response to return or an exception to raise.
    The last entry repeats forever, so "always 504" is one entry rather
    than a guess about how many attempts the client will make.
    """

    def __init__(self, *script):
        self.script = list(script)
        self.calls: list[dict] = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        item = self.script[min(len(self.calls) - 1, len(self.script) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    @property
    def attempts(self) -> int:
        return len(self.calls)


@pytest.fixture
def slept(monkeypatch):
    """Record backoff waits instead of taking them.

    Patches ``time.sleep`` on the stdlib module rather than reaching for
    ``ndi.cloud.client.time``. Both reach the same function -- the client
    calls it through the module object -- but the indirect form binds the
    fixture to the client happening to import ``time``, so on a tree
    without the retry every test using it would ERROR in setup instead of
    failing on behaviour. A guard that cannot run on the broken code is
    not evidence about the broken code.
    """
    import time as _time

    waits: list[float] = []
    monkeypatch.setattr(_time, "sleep", waits.append)
    return waits


def make_client(*script, can_reauth: bool = True):
    """A client whose transport is the given script.

    ``__new__`` rather than the constructor: the real one builds a
    ``requests.Session`` that would have to be replaced anyway.

    ``can_reauth`` defaults to True so ordinary retry tests continue to
    behave as if the client were obtained via ``from_env()``. Tests that
    verify the "hand-built CloudClient(CloudConfig(token=...)) does not
    refresh against env credentials" behavior pass ``can_reauth=False``.
    """
    client = CloudClient.__new__(CloudClient)
    client.config = CloudConfig()
    client._session = Transport(*script)
    client._can_reauth = can_reauth
    return client


OK = response(200, text='{"ok": true}')
GATEWAY_TIMEOUT = response(504, text="upstream timeout", reason="Gateway Timeout")


# ======================================================================
# It retries what it should
# ======================================================================
class TestTransientStatusesAreRepeated:
    def test_a_504_on_a_get_is_retried_and_succeeds(self, slept):
        """The case the issue is about."""
        client = make_client(GATEWAY_TIMEOUT, OK)

        result = client.get("/datasets")

        assert client._session.attempts == 2
        assert result.status_code == 200

    @pytest.mark.parametrize("status", [502, 503, 504])
    def test_every_transient_status_is_retried(self, status, slept):
        client = make_client(response(status, text="nope"), OK)

        client.get("/datasets")

        assert client._session.attempts == 2

    @pytest.mark.parametrize("method", ["get", "put", "delete"])
    def test_every_idempotent_method_is_retried(self, method, slept):
        client = make_client(GATEWAY_TIMEOUT, OK)

        getattr(client, method)("/datasets")

        assert client._session.attempts == 2

    def test_a_success_is_not_retried(self, slept):
        client = make_client(OK)

        client.get("/datasets")

        assert client._session.attempts == 1
        assert slept == [], "a successful request must not wait"


# ======================================================================
# It does not retry what it must not
# ======================================================================
class TestPostIsNeverRetried:
    """The correctness constraint, not a tuning knob.

    Most POST routes create resources; repeating one can create a second.
    A duplicate remote dataset is worse than the error the retry avoids.
    """

    def test_a_504_on_a_post_fails_immediately(self, slept):
        client = make_client(GATEWAY_TIMEOUT)

        with pytest.raises(CloudAPIError):
            client.post("/datasets", json={"name": "x"})

        assert client._session.attempts == 1, "POST was repeated; it can duplicate a resource"
        assert slept == []

    def test_post_is_absent_from_the_allow_list(self):
        """Pins the intent, so widening the set is a deliberate act."""
        assert "POST" not in CloudClient.RETRY_METHODS
        assert {"GET", "PUT", "DELETE"} <= CloudClient.RETRY_METHODS


class TestNonTransientFailuresAreNotRetried:
    @pytest.mark.parametrize("status", [400, 409, 422, 500])
    def test_a_non_transient_status_fails_on_the_first_attempt(self, status, slept):
        client = make_client(response(status, text="nope"))

        with pytest.raises(CloudAPIError):
            client.get("/datasets")

        assert client._session.attempts == 1
        assert slept == []

    def test_a_401_that_reauth_cannot_fix_still_surfaces(self, slept, monkeypatch):
        """A 401 triggers reauthentication once; if reauth itself fails, the
        original 401 surfaces without the client entering a retry storm.

        Bad or missing creds are the same class of failure they always
        were -- credentials do not become valid by asking again. The
        reauth branch that :meth:`_request` gained to survive
        token-expired-mid-run is a one-shot per request; when it cannot
        produce a fresh token, the original 4xx is what the caller sees.
        """
        client = make_client(response(401, text="nope"))

        def failing_reauth():
            raise CloudAuthError("no creds available for reauth")

        monkeypatch.setattr(client, "_reauthenticate", failing_reauth)

        with pytest.raises(CloudAuthError):
            client.get("/datasets")

        # Reauth failed -- the original request was made once and the
        # 401 surfaces from _handle_response. Reauth itself does not go
        # through this session.
        assert client._session.attempts == 1

    def test_a_404_is_not_retried(self, slept):
        client = make_client(response(404, text="nope"))

        with pytest.raises(CloudAPIError):
            client.get("/datasets")

        assert client._session.attempts == 1


# ======================================================================
# Connection-level failures
# ======================================================================
class TestTransportErrors:
    """A dropped connection on a GET is as transient as a 503.

    The reference implementation did not retry these; the issue asks
    whether they should be, and they should: the failure mode is the same
    and so is the remedy.
    """

    @pytest.mark.parametrize(
        "exc",
        [requests.ConnectionError("connection reset"), requests.Timeout("read timed out")],
    )
    def test_a_transient_transport_error_on_a_get_is_retried(self, exc, slept):
        client = make_client(exc, OK)

        client.get("/datasets")

        assert client._session.attempts == 2

    def test_a_transient_transport_error_on_a_post_is_not_retried(self, slept):
        client = make_client(requests.ConnectionError("connection reset"))

        with pytest.raises(CloudAPIError):
            client.post("/datasets", json={"name": "x"})

        assert client._session.attempts == 1

    def test_a_permanent_transport_error_is_not_retried(self, slept):
        """A malformed URL fails identically every time.

        Retrying every RequestException would repeat these too, turning an
        instant report into a delayed one for no chance of success.
        """
        client = make_client(requests.exceptions.InvalidURL("not a url"))

        with pytest.raises(CloudAPIError):
            client.get("/datasets")

        assert client._session.attempts == 1
        assert slept == []


# ======================================================================
# The budget, and what a failure says
# ======================================================================
class TestTheRetryBudget:
    def test_a_persistent_504_gives_up_after_max_attempts(self, slept):
        client = make_client(GATEWAY_TIMEOUT)

        with pytest.raises(CloudAPIError):
            client.get("/datasets")

        assert client._session.attempts == CloudClient.MAX_ATTEMPTS

    def test_it_waits_between_attempts_and_not_after_the_last(self, slept):
        """N attempts means N-1 waits; a wait after the final failure is
        time spent for nothing."""
        client = make_client(GATEWAY_TIMEOUT)

        with pytest.raises(CloudAPIError):
            client.get("/datasets")

        assert len(slept) == CloudClient.MAX_ATTEMPTS - 1

    def test_the_error_says_it_was_retried(self, slept):
        """A failure that survived the budget reads differently from one
        that never got a second chance -- and the exception is usually all
        a log line keeps."""
        client = make_client(GATEWAY_TIMEOUT)

        with pytest.raises(CloudAPIError) as caught:
            client.get("/datasets")

        assert f"after {CloudClient.MAX_ATTEMPTS} attempts" in str(caught.value)

    def test_a_first_attempt_failure_does_not_claim_retries(self, slept):
        client = make_client(response(400, text="bad"))

        with pytest.raises(CloudAPIError) as caught:
            client.get("/datasets")

        assert "attempts" not in str(caught.value)

    def test_a_transport_failure_that_survived_the_budget_says_so(self, slept):
        client = make_client(requests.ConnectionError("connection reset"))

        with pytest.raises(CloudAPIError) as caught:
            client.get("/datasets")

        assert f"after {CloudClient.MAX_ATTEMPTS} attempts" in str(caught.value)


# ======================================================================
# The backoff policy
# ======================================================================
class TestBackoff:
    """Exponential with full jitter, capped.

    Tested through ``_retry_delay`` rather than by timing anything: the
    property that matters is the distribution the delay is drawn from, and
    a test that measured elapsed time would be slow and flaky both.
    """

    def test_the_ceiling_doubles_per_attempt(self):
        client = CloudClient.__new__(CloudClient)
        ceilings = [max(client._retry_delay(n) for _ in range(200)) for n in (1, 2, 3)]

        assert ceilings[0] <= CloudClient.RETRY_BACKOFF
        assert ceilings[1] > CloudClient.RETRY_BACKOFF
        assert ceilings[2] > ceilings[1]

    def test_no_delay_exceeds_its_ceiling(self):
        client = CloudClient.__new__(CloudClient)
        for attempt in range(1, 6):
            ceiling = min(
                CloudClient.RETRY_BACKOFF * (2 ** (attempt - 1)),
                CloudClient.RETRY_BACKOFF_CAP,
            )
            for _ in range(200):
                assert 0.0 <= client._retry_delay(attempt) <= ceiling

    def test_the_ceiling_is_capped(self):
        """Without the cap, raising MAX_ATTEMPTS would turn a retry into a
        stall of minutes."""
        client = CloudClient.__new__(CloudClient)
        assert all(client._retry_delay(40) <= CloudClient.RETRY_BACKOFF_CAP for _ in range(200))

    def test_the_delay_is_jittered(self):
        """A fixed backoff synchronises every waiting client onto the
        moment the gateway recovers -- the repeats become the next
        outage. Distinct draws are the whole defence."""
        client = CloudClient.__new__(CloudClient)
        draws = {client._retry_delay(3) for _ in range(50)}

        assert len(draws) > 1, "delays are identical; the backoff has no jitter"


# ======================================================================
# Token-expired-mid-run: reauth once and retry
# ======================================================================
class TestReauthOnTokenExpiry:
    """A long-running operation can outlive its bearer token's TTL.

    Observed today on a signed-URL-set-job poll loop: the server was
    signing steadily, the client polled every ~30 s, and at ~9 min the
    token expired. Every subsequent poll returned 401/403 with a "Token
    is invalid or expired" body, but the client kept using the same
    stale token until the outer timeout fired. A reauth-and-retry
    branch in :meth:`_request` turns that quietly-fatal case into one
    invisible-to-the-caller refresh followed by success.

    A second 401/403 after reauth is a real auth failure (bad creds,
    revoked key) and must not loop -- one refresh per request is the
    invariant these tests pin.
    """

    def test_a_401_triggers_reauth_and_retries_once(self, slept, monkeypatch):
        """Happy path: token expired, reauth succeeds, retry succeeds."""
        client = make_client(response(401, text="expired"), OK)

        refreshed = {"n": 0}

        def fresh_token():
            refreshed["n"] += 1
            client.config.token = f"new-token-{refreshed['n']}"

        monkeypatch.setattr(client, "_reauthenticate", fresh_token)

        result = client.get("/datasets")

        assert result.status_code == 200
        assert client._session.attempts == 2, "expected one retry after reauth"
        assert refreshed["n"] == 1, "reauth should fire exactly once"

    def test_a_403_also_triggers_reauth(self, slept, monkeypatch):
        """The server returned 403 with 'Token is invalid or expired' in
        our real observation; the client must treat 403 the same way as
        401 for reauth purposes."""
        client = make_client(response(403, text="expired"), OK)
        monkeypatch.setattr(
            client, "_reauthenticate", lambda: setattr(client.config, "token", "new")
        )

        result = client.get("/datasets")
        assert result.status_code == 200
        assert client._session.attempts == 2

    def test_a_second_401_after_reauth_does_not_loop(self, slept, monkeypatch):
        """Reauth is one-shot per request. A 401 that persists past a
        successful reauth is a real auth problem and belongs at the
        surface, not in a retry storm."""
        client = make_client(response(401, text="expired"), response(401, text="still expired"))

        calls = {"n": 0}

        def refresh():
            calls["n"] += 1
            client.config.token = f"new-{calls['n']}"

        monkeypatch.setattr(client, "_reauthenticate", refresh)

        with pytest.raises(CloudAuthError):
            client.get("/datasets")

        assert calls["n"] == 1, "reauth must fire exactly once, not once per 401"
        assert client._session.attempts == 2

    def test_reauth_updates_the_authorization_header(self, slept, monkeypatch):
        """The retry uses the NEW token, not the stale one. Without
        this, we'd refresh in place and then send the old header
        anyway -- and the whole exercise would be for nothing.

        Captures the header at request time (rather than reading the
        session's post-facto record, which holds a single mutating dict
        for both calls).
        """
        client = make_client(response(401, text="expired"), OK)

        captured_authorizations: list[str] = []
        real_request = client._session.request

        def capturing_request(method, url, **kwargs):
            captured_authorizations.append(kwargs.get("headers", {}).get("Authorization"))
            return real_request(method, url, **kwargs)

        client._session.request = capturing_request

        def refresh():
            client.config.token = "the-fresh-token"

        monkeypatch.setattr(client, "_reauthenticate", refresh)
        client.config.token = "the-stale-token"

        client.get("/datasets")

        assert captured_authorizations[0] == "Bearer the-stale-token"
        assert captured_authorizations[1] == "Bearer the-fresh-token"

    def test_a_hand_built_client_does_not_reauth_against_env(self, slept, monkeypatch):
        """``CloudClient(CloudConfig(token=...))`` uses the given token as
        given: a 401 surfaces as ``CloudAuthError`` rather than silently
        being replaced by whatever ``authenticate()`` would return from
        env. Without this, a test that hard-codes a bad token to verify
        auth failure "passes" because CI happens to have valid
        ``NDI_CLOUD_USERNAME``/``NDI_CLOUD_PASSWORD`` in env, and the
        client swaps in a fresh valid token behind the caller's back.
        """
        client = make_client(response(401, text="expired"), can_reauth=False)

        reauth_calls = {"n": 0}

        def should_not_be_called():
            reauth_calls["n"] += 1
            client.config.token = "would-be-fresh"

        monkeypatch.setattr(client, "_reauthenticate", should_not_be_called)

        with pytest.raises(CloudAuthError):
            client.get("/datasets")

        assert reauth_calls["n"] == 0, "hand-built client must not refresh from env"
        assert client._session.attempts == 1, "no retry when reauth is disabled"


if __name__ == "__main__":
    pytest.main([__file__])
