"""authenticate() must reach the saved cloud profile, not just the environment.

The gap this pins closed: ndi.cloud.profile is the documented place to keep a
cloud password, but nothing in the authentication path ever read it. Every
implicit login -- each @_auto_client API call, and the ndic:// file handler
that fetches pyramid tiles for a downloaded dataset -- went environment-only
and raised "no credentials available" while a perfectly good default profile
sat on disk. MATLAB's authenticate.m has had the equivalent step
(authenticatedWithSecret) all along.
"""

import os
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


class _NoEnvMixin(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        for key in _ENV_KEYS:
            os.environ.pop(key, None)


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
            self.assertEqual(auth._profile_credentials(), ("current@example.com", "pw", "prod"))

    def test_the_default_profile_is_used_when_no_current_one_is_set(self):
        default = ProfileEntry(UID="u2", Email="default@example.com", Stage="dev")
        with (
            mock.patch("ndi.cloud.profile.get_current", return_value=None),
            mock.patch("ndi.cloud.profile.get_default", return_value=default),
            mock.patch("ndi.cloud.profile.get_password", return_value="pw"),
        ):
            self.assertEqual(auth._profile_credentials(), ("default@example.com", "pw", "dev"))

    def test_no_profile_at_all_reports_emptiness_rather_than_raising(self):
        with (
            mock.patch("ndi.cloud.profile.get_current", return_value=None),
            mock.patch("ndi.cloud.profile.get_default", return_value=None),
        ):
            self.assertEqual(auth._profile_credentials(), ("", "", ""))

    def test_a_secrets_backend_that_throws_is_not_allowed_to_escape(self):
        entry = ProfileEntry(UID="u1", Email="a@example.com", Stage="prod")
        with (
            mock.patch("ndi.cloud.profile.get_current", return_value=entry),
            mock.patch(
                "ndi.cloud.profile.get_password", side_effect=RuntimeError("locked keyring")
            ),
        ):
            self.assertEqual(auth._profile_credentials(), ("", "", ""))

    def test_a_profile_with_no_stored_password_counts_as_no_credentials(self):
        entry = ProfileEntry(UID="u1", Email="a@example.com", Stage="prod")
        with (
            mock.patch("ndi.cloud.profile.get_current", return_value=entry),
            mock.patch("ndi.cloud.profile.get_password", return_value=""),
        ):
            self.assertEqual(auth._profile_credentials(), ("", "", ""))


class TestAuthenticateReachesTheProfile(_NoEnvMixin):
    def test_the_profile_logs_in_when_the_environment_is_empty(self):
        fake, calls = _login_spy()
        with (
            mock.patch.object(auth, "login", fake),
            mock.patch.object(
                auth, "_profile_credentials", return_value=("a@example.com", "pw", "prod")
            ),
        ):
            self.assertEqual(auth.authenticate(), ("tok", "org-1"))
        self.assertEqual(calls[0][:2], ("a@example.com", "pw"))

    def test_an_exported_username_still_wins_over_the_profile(self):
        os.environ["NDI_CLOUD_USERNAME"] = "env@example.com"
        os.environ["NDI_CLOUD_PASSWORD"] = "envpw"
        fake, calls = _login_spy()
        with (
            mock.patch.object(auth, "login", fake),
            mock.patch.object(
                auth, "_profile_credentials", return_value=("a@example.com", "pw", "prod")
            ),
        ):
            auth.authenticate()
        self.assertEqual(calls[0][:2], ("env@example.com", "envpw"))

    def test_a_dev_profile_points_the_config_at_the_dev_api(self):
        fake, calls = _login_spy()
        with (
            mock.patch.object(auth, "login", fake),
            mock.patch.object(
                auth, "_profile_credentials", return_value=("a@example.com", "pw", "dev")
            ),
        ):
            auth.authenticate()
        self.assertEqual(calls[0][2], "https://dev-api.ndi-cloud.com/v1")

    def test_an_explicit_url_is_not_overridden_by_the_profile_stage(self):
        os.environ["NDI_CLOUD_URL"] = "https://example.invalid/v1"
        fake, calls = _login_spy()
        with (
            mock.patch.object(auth, "login", fake),
            mock.patch.object(
                auth, "_profile_credentials", return_value=("a@example.com", "pw", "dev")
            ),
        ):
            auth.authenticate()
        self.assertEqual(calls[0][2], "https://example.invalid/v1")

    def test_an_explicit_environment_choice_is_not_overridden_either(self):
        os.environ["CLOUD_API_ENVIRONMENT"] = "prod"
        fake, calls = _login_spy()
        with (
            mock.patch.object(auth, "login", fake),
            mock.patch.object(
                auth, "_profile_credentials", return_value=("a@example.com", "pw", "dev")
            ),
        ):
            auth.authenticate()
        self.assertEqual(calls[0][2], "https://api.ndi-cloud.com/v1")

    def test_with_neither_environment_nor_profile_the_error_names_both(self):
        with mock.patch.object(auth, "_profile_credentials", return_value=("", "", "")):
            with self.assertRaises(CloudAuthError) as ctx:
                auth.authenticate()
        message = str(ctx.exception)
        self.assertIn("NDI_CLOUD_USERNAME", message)
        self.assertIn("profile", message)


if __name__ == "__main__":
    unittest.main()
