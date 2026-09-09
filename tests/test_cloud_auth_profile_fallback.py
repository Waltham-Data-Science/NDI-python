"""Cloud credentials and the API they are sent to both come from the profile.

Two gaps, one after the other.

FIRST: ndi.cloud.profile is the documented place to keep a cloud password,
but nothing in the authentication path read it. Every implicit login -- each
@_auto_client API call, and the ndic:// file handler that fetches pyramid
tiles for a downloaded dataset -- went token -> environment -> raise, and
said "no credentials available" with a working default profile on disk.
MATLAB's authenticate.m has had the equivalent step (authenticatedWithSecret)
all along.

SECOND, once that worked: the profile's Stage picks prod vs dev, and applying
it only on the login path is not enough. login() exports NDI_CLOUD_TOKEN, so
every config built afterwards short-circuits at authenticate()'s first step
and never reaches the credential path -- a dev profile logged in against dev
and then issued every subsequent request against prod. NDI-matlab settles
this the same way, in profile.switchProfile:

    setenv('CLOUD_API_ENVIRONMENT', prof.Stage)

so the stage is resolved where the config is built, not where the login is.
"""

import base64
import json
import os
import time
import unittest
from unittest import mock

from ndi.cloud import auth
from ndi.cloud.config import CloudConfig
from ndi.cloud.exceptions import CloudAuthError
from ndi.cloud.profile import ProfileEntry

_ENV_KEYS = (
    "NDI_CLOUD_TOKEN",
    "NDI_CLOUD_ORGANIZATION_ID",
    "NDI_CLOUD_USERNAME",
    "NDI_CLOUD_PASSWORD",
    "NDI_CLOUD_URL",
    "CLOUD_API_ENVIRONMENT",
)

_PROD = "https://api.ndi-cloud.com/v1"
_DEV = "https://dev-api.ndi-cloud.com/v1"


class _NoEnvMixin(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        for key in _ENV_KEYS:
            os.environ.pop(key, None)


def _unexpired_token() -> str:
    """A JWT whose exp claim is far enough out that isTokenExpired says no."""

    def seg(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    return f"{seg({'alg': 'none'})}.{seg({'exp': int(time.time()) + 3600})}.sig"


def _login_spy(token="tok", org="org-1"):
    """Stand in for auth.login, recording what it was handed."""
    calls = []

    def fake(email=None, password=None, config=None):
        calls.append((email, password, config.api_url if config else None))
        config = config or CloudConfig()
        config.token = token
        config.org_id = org
        return config

    return fake, calls


class TestProfileCredentials(_NoEnvMixin):
    def test_a_current_profile_is_preferred_over_the_default(self):
        current = ProfileEntry(UID="u1", Email="current@example.com", Stage="prod")
        default = ProfileEntry(UID="u2", Email="default@example.com", Stage="prod")
        with (
            mock.patch("ndi.cloud.profile.get_current", return_value=current),
            mock.patch("ndi.cloud.profile.get_default", return_value=default),
            mock.patch("ndi.cloud.profile.get_password", return_value="pw"),
        ):
            self.assertEqual(auth._profile_credentials(), ("current@example.com", "pw"))

    def test_the_default_profile_is_used_when_no_current_one_is_set(self):
        default = ProfileEntry(UID="u2", Email="default@example.com", Stage="dev")
        with (
            mock.patch("ndi.cloud.profile.get_current", return_value=None),
            mock.patch("ndi.cloud.profile.get_default", return_value=default),
            mock.patch("ndi.cloud.profile.get_password", return_value="pw"),
        ):
            self.assertEqual(auth._profile_credentials(), ("default@example.com", "pw"))

    def test_no_profile_at_all_reports_emptiness_rather_than_raising(self):
        with (
            mock.patch("ndi.cloud.profile.get_current", return_value=None),
            mock.patch("ndi.cloud.profile.get_default", return_value=None),
        ):
            self.assertEqual(auth._profile_credentials(), ("", ""))

    def test_a_secrets_backend_that_throws_is_not_allowed_to_escape(self):
        entry = ProfileEntry(UID="u1", Email="a@example.com", Stage="prod")
        with (
            mock.patch("ndi.cloud.profile.get_current", return_value=entry),
            mock.patch(
                "ndi.cloud.profile.get_password", side_effect=RuntimeError("locked keyring")
            ),
        ):
            self.assertEqual(auth._profile_credentials(), ("", ""))

    def test_a_profile_with_no_stored_password_counts_as_no_credentials(self):
        entry = ProfileEntry(UID="u1", Email="a@example.com", Stage="prod")
        with (
            mock.patch("ndi.cloud.profile.get_current", return_value=entry),
            mock.patch("ndi.cloud.profile.get_password", return_value=""),
        ):
            self.assertEqual(auth._profile_credentials(), ("", ""))


class TestAuthenticateReachesTheProfile(_NoEnvMixin):
    def test_the_profile_logs_in_when_the_environment_is_empty(self):
        fake, calls = _login_spy()
        with (
            mock.patch.object(auth, "login", fake),
            mock.patch.object(auth, "_profile_credentials", return_value=("a@example.com", "pw")),
        ):
            self.assertEqual(auth.authenticate(), ("tok", "org-1"))
        self.assertEqual(calls[0][:2], ("a@example.com", "pw"))

    def test_an_exported_username_still_wins_over_the_profile(self):
        os.environ["NDI_CLOUD_USERNAME"] = "env@example.com"
        os.environ["NDI_CLOUD_PASSWORD"] = "envpw"
        fake, calls = _login_spy()
        with (
            mock.patch.object(auth, "login", fake),
            mock.patch.object(auth, "_profile_credentials", return_value=("a@example.com", "pw")),
        ):
            auth.authenticate()
        self.assertEqual(calls[0][:2], ("env@example.com", "envpw"))

    def test_a_dev_profiles_login_is_issued_against_dev(self):
        fake, calls = _login_spy()
        with (
            mock.patch("ndi.cloud.config._profile_stage", return_value="dev"),
            mock.patch.object(auth, "login", fake),
            mock.patch.object(auth, "_profile_credentials", return_value=("a@example.com", "pw")),
        ):
            auth.authenticate()
        self.assertEqual(calls[0][2], _DEV)

    def test_with_neither_environment_nor_profile_the_error_names_both(self):
        with mock.patch.object(auth, "_profile_credentials", return_value=("", "")):
            with self.assertRaises(CloudAuthError) as ctx:
                auth.authenticate()
        message = str(ctx.exception)
        self.assertIn("NDI_CLOUD_USERNAME", message)
        self.assertIn("profile", message)


class TestTheStageSurvivesTheTokenShortCircuit(_NoEnvMixin):
    """The bug a dev user actually hits.

    Each on-demand pyramid tile builds its own client, so this struck from
    the second request onwards, after a login that looked fine, as:

        Not found (HTTP 404): {"error":"Dataset ... does not exist or user
        does not have access"}

    which reads as a permissions problem rather than a wrong-server one.
    """

    def test_a_config_built_after_login_still_points_at_dev(self):
        os.environ["NDI_CLOUD_TOKEN"] = "already-have-one"
        os.environ["NDI_CLOUD_ORGANIZATION_ID"] = "org-1"
        with mock.patch("ndi.cloud.config._profile_stage", return_value="dev"):
            self.assertEqual(CloudConfig.from_env().api_url, _DEV)

    def test_authenticate_short_circuits_without_losing_the_dev_url(self):
        os.environ["NDI_CLOUD_TOKEN"] = _unexpired_token()
        os.environ["NDI_CLOUD_ORGANIZATION_ID"] = "org-1"
        with mock.patch("ndi.cloud.config._profile_stage", return_value="dev"):
            config = CloudConfig.from_env()
            _, org = auth.authenticate(config)
        self.assertEqual(org, "org-1")
        self.assertEqual(config.api_url, _DEV)


class TestApiUrlPrecedence(_NoEnvMixin):
    def test_an_explicit_url_beats_the_profile_stage(self):
        os.environ["NDI_CLOUD_URL"] = "https://example.invalid/v1"
        with mock.patch("ndi.cloud.config._profile_stage", return_value="dev"):
            self.assertEqual(CloudConfig.from_env().api_url, "https://example.invalid/v1")

    def test_an_explicit_environment_beats_the_profile_stage(self):
        os.environ["CLOUD_API_ENVIRONMENT"] = "prod"
        with mock.patch("ndi.cloud.config._profile_stage", return_value="dev"):
            self.assertEqual(CloudConfig.from_env().api_url, _PROD)

    def test_the_profile_stage_beats_the_prod_default(self):
        with mock.patch("ndi.cloud.config._profile_stage", return_value="dev"):
            self.assertEqual(CloudConfig.from_env().api_url, _DEV)

    def test_with_no_profile_at_all_it_is_prod(self):
        with mock.patch("ndi.cloud.config._profile_stage", return_value=""):
            self.assertEqual(CloudConfig.from_env().api_url, _PROD)

    def test_an_unrecognised_stage_falls_back_to_prod_rather_than_a_bad_url(self):
        with mock.patch("ndi.cloud.config._profile_stage", return_value="staging"):
            self.assertEqual(CloudConfig.from_env().api_url, _PROD)

    def test_a_profile_store_that_will_not_load_does_not_stop_a_config(self):
        with mock.patch("ndi.cloud.profile.get_current", side_effect=RuntimeError("locked")):
            self.assertEqual(CloudConfig.from_env().api_url, _PROD)


class TestProfileStage(_NoEnvMixin):
    def test_the_current_profile_is_preferred_over_the_default(self):
        from ndi.cloud.config import _profile_stage

        current = ProfileEntry(UID="u1", Email="a@example.com", Stage="dev")
        default = ProfileEntry(UID="u2", Email="b@example.com", Stage="prod")
        with (
            mock.patch("ndi.cloud.profile.get_current", return_value=current),
            mock.patch("ndi.cloud.profile.get_default", return_value=default),
        ):
            self.assertEqual(_profile_stage(), "dev")

    def test_no_profile_yields_no_stage_rather_than_a_guess(self):
        from ndi.cloud.config import _profile_stage

        with (
            mock.patch("ndi.cloud.profile.get_current", return_value=None),
            mock.patch("ndi.cloud.profile.get_default", return_value=None),
        ):
            self.assertEqual(_profile_stage(), "")


def _expired_token(ago_seconds: int = 3600) -> str:
    """A JWT whose exp claim is in the past."""

    def seg(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    return f"{seg({'alg': 'none'})}.{seg({'exp': int(time.time()) - ago_seconds})}.sig"


class TestWhatTheFailureSays(_NoEnvMixin):
    """Three quite different situations end at the same raise.

    The reader of this message is usually looking at a FAILED FILE FETCH,
    not at a login: a napari toast on a tile, one per tile, an hour into a
    session that was working. "No valid token and no credentials
    available" is equally true of never having logged in and of a token
    that lapsed while the viewer was open, and those want opposite
    responses -- so the message has to say which happened.
    """

    def _raised(self, config):
        with (
            mock.patch("ndi.cloud.profile.get_current", return_value=None),
            mock.patch("ndi.cloud.profile.get_default", return_value=None),
        ):
            with self.assertRaises(CloudAuthError) as caught:
                auth.authenticate(config)
        return str(caught.exception)

    def test_an_expired_token_is_named_as_expired(self):
        """The one that reads as missing data if it is not said out loud:
        the tile is there, the token lapsed."""
        message = self._raised(CloudConfig(token=_expired_token(), org_id="org-1"))
        self.assertIn("expired", message.lower())
        self.assertNotIn("Not logged in", message)

    def test_an_expired_token_says_when(self):
        message = self._raised(CloudConfig(token=_expired_token(), org_id="org-1"))
        self.assertIn("UTC", message)

    def test_an_expired_token_says_another_shell_will_not_do(self):
        """The token lives in os.environ, so logging in elsewhere does not
        reach a process that is already running. Without that sentence the
        obvious remedy looks like it did not work."""
        message = self._raised(CloudConfig(token=_expired_token(), org_id="org-1"))
        self.assertIn("another shell", message)
        self.assertIn("start it again", message)

    def test_no_token_at_all_says_so_instead(self):
        message = self._raised(CloudConfig(token="", org_id=""))
        self.assertIn("Not logged in", message)
        self.assertNotIn("expired", message.lower().split("only until")[0])

    def test_a_token_with_no_organization_is_its_own_case(self):
        """Step 1 wants both. A token that passes the expiry check and is
        still refused is otherwise indistinguishable from a bad password."""
        message = self._raised(CloudConfig(token=_unexpired_token(), org_id=""))
        self.assertIn("organization id", message)

    def test_every_case_says_how_to_stop_it_happening_again(self):
        """Credentials it can reach are the fix for all three: with them,
        authenticate renews the token itself and step 1 stops mattering."""
        for config in (
            CloudConfig(token="", org_id=""),
            CloudConfig(token=_expired_token(), org_id="org-1"),
            CloudConfig(token=_unexpired_token(), org_id=""),
        ):
            message = self._raised(config)
            self.assertIn("NDI_CLOUD_USERNAME", message)
            self.assertIn("profile", message)


class TestTheCredentialReport(_NoEnvMixin):
    """One line instead of a bisection.

    An authentication failure reaches most people through something else
    -- a tile that will not load -- and from there it is hard to say where
    the credentials were meant to come from. The report walks the same
    three steps authenticate walks and names each.
    """

    def _report(self, profile_entry=None, password=""):
        with (
            mock.patch("ndi.cloud.profile.get_current", return_value=profile_entry),
            mock.patch("ndi.cloud.profile.get_default", return_value=None),
            mock.patch("ndi.cloud.profile.get_password", return_value=password),
        ):
            return auth.credentialReport()

    def test_it_says_every_step_came_up_empty(self):
        report = self._report()
        self.assertIn("token in env   : no", report)
        self.assertIn("username in env: no", report)
        self.assertIn("profile        : none usable", report)
        self.assertIn("FAILED", report)

    def test_an_expired_token_is_reported_with_its_expiry(self):
        os.environ["NDI_CLOUD_TOKEN"] = _expired_token()
        report = self._report()
        self.assertIn("token in env   : yes", report)
        self.assertIn("EXPIRED", report)
        self.assertIn("UTC", report)

    def test_a_live_token_reads_as_valid(self):
        os.environ["NDI_CLOUD_TOKEN"] = _unexpired_token()
        os.environ["NDI_CLOUD_ORGANIZATION_ID"] = "org-1"
        report = self._report()
        self.assertIn("valid", report)
        self.assertIn("authenticate   : ok", report)

    def test_a_usable_profile_is_named(self):
        entry = ProfileEntry(UID="u1", Email="a@example.com", Stage="prod")
        with mock.patch.object(auth, "login", _login_spy()[0]):
            report = self._report(profile_entry=entry, password="pw")
        self.assertIn("profile        : a@example.com", report)

    def test_it_never_prints_the_secret(self):
        """It is meant to be pasted into a chat or an issue."""
        token = _unexpired_token()
        os.environ["NDI_CLOUD_TOKEN"] = token
        os.environ["NDI_CLOUD_ORGANIZATION_ID"] = "org-1"
        os.environ["NDI_CLOUD_USERNAME"] = "a@example.com"
        os.environ["NDI_CLOUD_PASSWORD"] = "hunter2"
        report = self._report()
        self.assertNotIn(token, report)
        self.assertNotIn("hunter2", report)


if __name__ == "__main__":
    unittest.main()
