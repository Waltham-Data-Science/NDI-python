"""Hygiene guards on the cloud auth/profile secrets paths.

Two small hardening findings from #187:

  - #187.3: the AES-fallback secrets file must be 0600 (was 0644), and the
    prefdir it lives in must be 0700, so a shared-workstation neighbour
    cannot read the ciphertext -- the AES key is derived from
    hostname+username, which they may already know.

  - #187.4: exceptions raised by the auth endpoints must not carry the raw
    ``resp.text`` in their message. Login/change-password/reset-password
    endpoints often echo the submitted credentials in error responses, and
    the message ends up in tracebacks, CI logs, and error reporters. The
    body is kept for local troubleshooting via a DEBUG log line.
"""

from __future__ import annotations

import logging
import os
import stat
import sys

import pytest

from ndi.cloud import profile as profile_mod

# ---------------------------------------------------------------------------
# #187.3 -- file mode 0600, prefdir 0700
# ---------------------------------------------------------------------------


class TestSecretsFilePermissions:
    """Only relevant on POSIX; Windows has no equivalent mode-bit story."""

    pytestmark = pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX mode bits only")

    def _mode(self, path):
        return stat.S_IMODE(os.stat(path).st_mode)

    def test_a_freshly_written_secrets_file_is_owner_read_write_only(self, tmp_path):
        target = tmp_path / "secrets.json"
        profile_mod._write_secrets_file(target, {"NDI_Cloud_uid": "value"})
        assert target.is_file()
        assert self._mode(target) == 0o600

    def test_an_existing_wider_mode_file_gets_tightened_on_next_write(self, tmp_path):
        """A user who upgraded from a version that wrote 0644 must end up at
        0600 on the first write after the upgrade -- not stay at 0644 until
        they manually delete the file."""
        target = tmp_path / "secrets.json"
        target.write_text('{"stale": "value"}')
        os.chmod(target, 0o644)
        assert self._mode(target) == 0o644

        profile_mod._write_secrets_file(target, {"NDI_Cloud_uid": "value"})
        assert self._mode(target) == 0o600

    def test_the_write_is_atomic_via_tempfile_replace(self, tmp_path):
        """A partial write must not leave a truncated file where the previous
        contents were. Enforced by the os.replace pattern; asserted here so a
        future refactor cannot silently drop it."""
        target = tmp_path / "secrets.json"
        profile_mod._write_secrets_file(target, {"a": "1"})
        original_contents = target.read_text()

        # A write that fails inside the fdopen block must not leave `target`
        # containing anything but the original bytes.
        with pytest.raises(TypeError):
            # dict with a non-serialisable value: json.dumps raises TypeError
            # after the temp file has been created but before it replaces
            # `target`.
            profile_mod._write_secrets_file(target, {"a": object()})
        assert target.read_text() == original_contents

    def test_prefdir_is_owner_only_when_freshly_created(self, tmp_path, monkeypatch):
        """The prefdir has to be 0700 so the wider audience the old default
        (0755) gave is closed. Simulated by pointing HOME at a scratch dir."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        # NDI_PREFDIR is honoured verbatim if set; unset it so we exercise the
        # default ~/.ndi path.
        monkeypatch.delenv("NDI_PREFDIR", raising=False)

        d = profile_mod._prefdir()
        assert d == home / ".ndi"
        assert self._mode(d) == 0o700


# ---------------------------------------------------------------------------
# #187.4 -- auth exceptions do not carry resp.text
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text

    def json(self):
        raise ValueError("not JSON")


def _login_401_with_body(monkeypatch, body: str) -> None:
    """Stub requests.post so an auth call receives 401 + ``body``."""
    import requests

    def fake_post(url, **kwargs):
        return _FakeResponse(401, body)

    monkeypatch.setattr(requests, "post", fake_post)


class TestAuthErrorsDoNotEchoResponseBody:
    """Bodies containing anything that looks like a credential must not
    surface in the raised exception's ``str()``. The status code stays."""

    _BODY_WITH_SECRETS = (
        '{"error":"Invalid password for user@example.com","echoedPassword":"hunter2"}'
    )

    def _assert_body_absent_and_status_present(self, exc: Exception) -> None:
        msg = str(exc)
        assert "HTTP 401" in msg
        # The specific secret-looking substrings that a naive raise would leak
        assert "hunter2" not in msg
        assert "user@example.com" not in msg
        assert "echoedPassword" not in msg
        assert "Invalid password" not in msg

    def test_login_401_message_does_not_echo_body(self, monkeypatch):
        from ndi.cloud import auth
        from ndi.cloud.auth import CloudConfig

        _login_401_with_body(monkeypatch, self._BODY_WITH_SECRETS)
        cfg = CloudConfig(api_url="https://example.invalid", token="", org_id="")
        with pytest.raises(auth.CloudAuthError) as exc_info:
            auth.login("user@example.com", "hunter2", config=cfg)
        self._assert_body_absent_and_status_present(exc_info.value)

    def test_change_password_401_message_does_not_echo_body(self, monkeypatch):
        from ndi.cloud import auth
        from ndi.cloud.auth import CloudConfig

        _login_401_with_body(monkeypatch, self._BODY_WITH_SECRETS)
        cfg = CloudConfig(api_url="https://example.invalid", token="tok", org_id="")
        with pytest.raises(auth.CloudAuthError) as exc_info:
            auth.changePassword("old", "new", config=cfg)
        self._assert_body_absent_and_status_present(exc_info.value)

    def test_reset_password_401_message_does_not_echo_body(self, monkeypatch):
        from ndi.cloud import auth
        from ndi.cloud.auth import CloudConfig

        _login_401_with_body(monkeypatch, self._BODY_WITH_SECRETS)
        cfg = CloudConfig(api_url="https://example.invalid", token="", org_id="")
        with pytest.raises(auth.CloudAuthError) as exc_info:
            auth.resetPassword("user@example.com", config=cfg)
        self._assert_body_absent_and_status_present(exc_info.value)

    def test_verify_user_401_message_does_not_echo_body(self, monkeypatch):
        from ndi.cloud import auth
        from ndi.cloud.auth import CloudConfig

        _login_401_with_body(monkeypatch, self._BODY_WITH_SECRETS)
        cfg = CloudConfig(api_url="https://example.invalid", token="", org_id="")
        with pytest.raises(auth.CloudAuthError) as exc_info:
            auth.verifyUser("user@example.com", "code123", config=cfg)
        self._assert_body_absent_and_status_present(exc_info.value)

    def test_resend_confirmation_401_message_does_not_echo_body(self, monkeypatch):
        from ndi.cloud import auth
        from ndi.cloud.auth import CloudConfig

        _login_401_with_body(monkeypatch, self._BODY_WITH_SECRETS)
        cfg = CloudConfig(api_url="https://example.invalid", token="", org_id="")
        with pytest.raises(auth.CloudAuthError) as exc_info:
            auth.resendConfirmation("user@example.com", config=cfg)
        self._assert_body_absent_and_status_present(exc_info.value)

    def test_body_is_still_available_at_debug_level(self, monkeypatch, caplog):
        """A developer chasing a login failure locally can turn DEBUG on and
        see the body -- the redaction is about tracebacks and CI logs, not
        about hiding the payload from the caller who wants it."""
        from ndi.cloud import auth
        from ndi.cloud.auth import CloudConfig

        _login_401_with_body(monkeypatch, self._BODY_WITH_SECRETS)
        cfg = CloudConfig(api_url="https://example.invalid", token="", org_id="")

        with caplog.at_level(logging.DEBUG, logger="ndi.cloud.auth"):
            with pytest.raises(auth.CloudAuthError):
                auth.login("user@example.com", "hunter2", config=cfg)

        # The body reaches DEBUG output, so operators who want it can have it.
        assert any(self._BODY_WITH_SECRETS in rec.getMessage() for rec in caplog.records)


if __name__ == "__main__":
    pytest.main([__file__])
