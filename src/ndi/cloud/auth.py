"""
ndi.cloud.auth - Authentication helpers for NDI Cloud.

Provides JWT decoding, login/logout flows, and token management.

MATLAB equivalents:
    authenticate.m, login.m, logout.m, testLogin.m
    +internal/decodeJwt.m, getTokenExpiration.m, getActiveToken.m,
    +internal/isTokenExpired.m
"""

from __future__ import annotations

import base64
import json
import logging
import os
from datetime import datetime, timezone

from .config import CloudConfig
from .exceptions import CloudAuthError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JWT helpers (no cryptographic verification — matches MATLAB behaviour)
# ---------------------------------------------------------------------------


def decodeJwt(token: str) -> dict:
    """Decode a JWT payload without signature verification.

    Matches MATLAB ``ndi.cloud.internal.decodeJwt``.

    .. warning::
        This function does **not** verify the JWT signature.  It is
        used only for reading expiration times and other metadata
        from tokens that have already been issued by a trusted server.
        **Never** use the decoded claims for authorization decisions
        without server-side verification.

    Args:
        token: A three-part ``header.payload.signature`` JWT string.

    Returns:
        The decoded payload as a dict.

    Raises:
        CloudAuthError: If the token cannot be decoded.
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("JWT must have 3 parts")
        # Base64Url → standard Base64
        payload_b64 = parts[1].replace("-", "+").replace("_", "/")
        # Add padding
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload_bytes = base64.b64decode(payload_b64)
        return json.loads(payload_bytes)
    except Exception as exc:
        raise CloudAuthError(f"Failed to decode JWT: {exc}") from exc


def getTokenExpiration(token: str) -> datetime:
    """Extract the ``exp`` claim from a JWT as a UTC datetime.

    Args:
        token: JWT string.

    Returns:
        Expiration time as a timezone-aware UTC datetime.

    Raises:
        CloudAuthError: If the token has no ``exp`` claim.
    """
    payload = decodeJwt(token)
    exp = payload.get("exp")
    if exp is None:
        raise CloudAuthError("JWT has no exp claim")
    return datetime.fromtimestamp(exp, tz=timezone.utc)


def isTokenExpired(token: str) -> bool:
    """Return True if *token* is expired, malformed, or empty.

    Performs a local-only check by decoding the JWT's ``exp`` claim.
    Does **not** contact the server.  Mirrors the MATLAB helper
    ``ndi.cloud.internal.isTokenExpired`` which was extracted from
    ``authenticate.m`` so that callers can do a cheap pre-check
    before issuing an authenticated request.

    MATLAB equivalent: +cloud/+internal/isTokenExpired.m
    """
    if not token:
        return True
    try:
        expiration = getTokenExpiration(token)
    except CloudAuthError:
        return True
    return datetime.now(timezone.utc) >= expiration


def verifyToken(token: str) -> bool:
    """Check whether *token* is still valid (not expired).

    Does **not** contact the server — only checks the ``exp`` claim.
    Equivalent to ``not isTokenExpired(token)`` and kept for backward
    compatibility.
    """
    return not isTokenExpired(token)


def getActiveToken(config: CloudConfig | None = None) -> tuple[str, str]:
    """Return ``(token, org_id)`` from *config* or environment.

    Raises:
        CloudAuthError: If no valid token is available, or if the
            organization id is missing.  Mirrors the MATLAB requirement
            that the organization id be populated before the token can
            be used for cached auth.
    """
    if config is None:
        config = CloudConfig.from_env()

    if not config.token:
        raise CloudAuthError("No token available (NDI_CLOUD_TOKEN not set)")

    if isTokenExpired(config.token):
        raise CloudAuthError("Token is expired")

    if not config.org_id:
        raise CloudAuthError(
            "Token is present but NDI_CLOUD_ORGANIZATION_ID is empty; "
            "cached auth requires an organization id."
        )

    return config.token, config.org_id


# ---------------------------------------------------------------------------
# Organization-id extraction (handles struct / list / dict shapes)
# ---------------------------------------------------------------------------


def _extract_first_organization_id(user: dict) -> str:
    """Extract the first organization id from a login response's user.

    Mirrors MATLAB ``extractFirstOrganizationId``: accepts dict, list of
    dicts, or a single dict; warns when multiple organizations are
    present (we pick the first; explicit selection is not yet
    implemented).
    """
    if not isinstance(user, dict) or "organizations" not in user:
        raise CloudAuthError("Login response did not include an organizations field.")

    orgs = user["organizations"]
    org_id = ""
    n_orgs = 0

    if isinstance(orgs, dict) and "id" in orgs:
        org_id = orgs.get("id", "")
        n_orgs = 1
    elif isinstance(orgs, list) and orgs:
        first = orgs[0]
        if isinstance(first, dict) and "id" in first:
            org_id = first.get("id", "")
            n_orgs = len(orgs)

    if not org_id:
        raise CloudAuthError("Could not extract an organization id from the login response.")

    if n_orgs > 1:
        logger.warning(
            "Login response contained %d organizations; using the first (%r). "
            "Selection among multiple organizations is not yet supported.",
            n_orgs,
            org_id,
        )

    return str(org_id)


# ---------------------------------------------------------------------------
# Login / logout  (require ``requests``)
# ---------------------------------------------------------------------------


def login(
    email: str | None = None,
    password: str | None = None,
    config: CloudConfig | None = None,
) -> CloudConfig:
    """Authenticate with the NDI Cloud API and store the token.

    Args:
        email: User email. Falls back to ``config.username`` or
            ``NDI_CLOUD_USERNAME``.
        password: User password. Falls back to ``config.password`` or
            ``NDI_CLOUD_PASSWORD``.
        config: Optional base config. Defaults to ``CloudConfig.from_env()``.

    Returns:
        Updated :class:`CloudConfig` with token and org_id populated.

    Raises:
        CloudAuthError: On failed login.
    """
    try:
        import requests
    except ImportError as exc:
        raise CloudAuthError(
            "The requests package is required for login. "
            "Install it with: pip install ndi[cloud]"
        ) from exc

    if config is None:
        config = CloudConfig.from_env()

    email = email or config.username or os.environ.get("NDI_CLOUD_USERNAME", "")
    password = password or config.password or os.environ.get("NDI_CLOUD_PASSWORD", "")

    if not email or not password:
        raise CloudAuthError("email and password are required for login")

    url = f"{config.api_url}/auth/login"
    try:
        resp = requests.post(
            url,
            json={"email": email, "password": password},
            headers={"Accept": "application/json"},
            timeout=30,
        )
    except requests.RequestException as exc:
        raise CloudAuthError(f"Login request failed: {exc}") from exc

    if resp.status_code != 200:
        raise CloudAuthError(f"Login failed (HTTP {resp.status_code}): {resp.text}")

    data = resp.json()
    token = data.get("token", "")
    user = data.get("user", {}) or {}
    org_id = _extract_first_organization_id(user)

    # Store in environment for other code to pick up
    os.environ["NDI_CLOUD_TOKEN"] = token
    if org_id:
        os.environ["NDI_CLOUD_ORGANIZATION_ID"] = org_id

    config.token = token
    config.org_id = org_id
    return config


def logout(config: CloudConfig | None = None) -> None:
    """Log out of the NDI Cloud API and clear stored credentials.

    Args:
        config: Config with token. Defaults to ``CloudConfig.from_env()``.
    """
    try:
        import requests
    except ImportError:
        # No requests — just clear env vars
        _clear_env_tokens()
        return

    if config is None:
        config = CloudConfig.from_env()

    if config.token:
        url = f"{config.api_url}/auth/logout"
        try:
            requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {config.token}",
                    "Accept": "application/json",
                },
                timeout=30,
            )
        except requests.RequestException:
            pass  # Best-effort, matching MATLAB warning behaviour

    _clear_env_tokens()
    config.token = ""
    config.org_id = ""


def authenticate(config: CloudConfig | None = None) -> tuple[str, str]:
    """Return an active token and organization ID, attempting login if needed.

    Priority (matching MATLAB ``authenticate.m``):
    1. Existing valid token in config/env (local JWT exp pre-check).
    2. Username + password from env → login.

    Args:
        config: Optional config.

    Returns:
        A ``(token, organization_id)`` tuple, matching the two-output
        convention of the MATLAB ``authenticate.m`` function.

    Raises:
        CloudAuthError: If authentication fails.
    """
    if config is None:
        config = CloudConfig.from_env()

    # 1. Already have a non-expired token AND an org id? Use it.
    #    Mirrors MATLAB isAuthenticated() which requires both token and
    #    organization_id to be present before short-circuiting.
    if config.token and config.org_id and not isTokenExpired(config.token):
        return config.token, config.org_id

    # 2. Try env-var credentials
    email = config.username or os.environ.get("NDI_CLOUD_USERNAME", "")
    password = config.password or os.environ.get("NDI_CLOUD_PASSWORD", "")
    if email and password:
        updated = login(email, password, config)
        return updated.token, updated.org_id

    raise CloudAuthError(
        "No valid token and no credentials available. "
        "Set NDI_CLOUD_TOKEN or NDI_CLOUD_USERNAME/NDI_CLOUD_PASSWORD."
    )


# ---------------------------------------------------------------------------
# testLogin — non-mutating probe of the currently held token
# ---------------------------------------------------------------------------


def testLogin(
    *,
    user_name: str | None = None,
    use_ui_login: bool = False,
    verbose: bool = False,
) -> bool:
    """Test whether the current process has a good NDI Cloud login.

    Returns True iff there is currently a valid login token in this
    process from which a username (the JWT ``email`` claim) can be
    extracted, AND that exact token is accepted by the server via a
    direct ``GET /users/me`` with the token as the Bearer credential.

    The probe is deliberately issued as a raw HTTP request rather than
    via :func:`ndi.cloud.api.users.me` (which routes through
    :func:`authenticate` and could silently re-auth as a different user
    mid-call).

    Order of operations:

        1. Probe the currently active token. If it is valid and the
           server accepts it, return True.
        2. Otherwise log out (clearing any stale token) and check for
           silent credentials in the environment
           (``NDI_CLOUD_USERNAME`` / ``NDI_CLOUD_PASSWORD``).
        3. If those env credentials are set, attempt a non-interactive
           re-login via :func:`login`.  Probe again.  The UI login is
           **never** shown when env credentials are present.
        4. Only if env credentials are empty AND ``use_ui_login`` is
           True, would a UI login be shown — but Python has no GUI
           equivalent, so this branch always returns False.

    Args:
        user_name: If provided, the JWT in the active token must have
            been issued for this email; otherwise the login is
            considered not good even if the API call succeeds.
        use_ui_login: Reserved for parity with MATLAB; always False in
            effect for the Python implementation (no GUI).
        verbose: If True, print step-by-step diagnostics to stderr.

    Returns:
        True if the user has a valid login (and, when ``user_name`` is
        provided, the token belongs to that user), False otherwise.

    MATLAB equivalent: +cloud/testLogin.m
    """

    def _log(msg: str) -> None:
        if verbose:
            print(f"[testLogin] {msg}")

    _log("Starting NDI Cloud login test.")
    if user_name is None:
        _log("No user_name specified; token-user check will be skipped.")
    else:
        _log(f"user_name specified: {user_name} (token must match).")
    _log(f"use_ui_login = {use_ui_login}.")

    # Attempt 1: probe the currently active token.
    _log("Attempt 1: probing the currently active token.")
    if _probe(user_name, verbose):
        _log("Attempt 1 succeeded. Returning True.")
        return True

    # No good current token; clear stale state.
    _log("Attempt 1 failed. Logging out to clear stale state.")
    try:
        logout()
    except Exception as exc:  # pragma: no cover - defensive
        _log(f"  logout raised: {exc}")

    # Attempt 2: silent re-auth via env credentials.
    env_user = os.environ.get("NDI_CLOUD_USERNAME", "")
    env_pass = os.environ.get("NDI_CLOUD_PASSWORD", "")
    have_env_creds = bool(env_user) and bool(env_pass)

    if have_env_creds:
        _log("Attempt 2: env credentials are set; attempting silent re-auth.")
        if user_name is not None and env_user != user_name:
            _log(
                f"  NDI_CLOUD_USERNAME ({env_user}) does not match requested "
                f"user_name ({user_name}); skipping silent login."
            )
        else:
            try:
                login(env_user, env_pass)
                _log("  silent login completed.")
            except Exception as exc:
                _log(f"  silent login raised: {exc}")
        ok = _probe(user_name, verbose)
        _log(f"Attempt 2 {'succeeded' if ok else 'failed'}. Returning {ok}.")
        return ok

    # Attempt 3: env credentials are empty.  Python has no GUI login,
    # so when use_ui_login is True we still return False here.
    _log("No env credentials available; Python has no UI login. " "Returning False.")
    return False


def _probe(user_name: str | None, verbose: bool) -> bool:
    """Direct GET /users/me probe of the current NDI_CLOUD_TOKEN.

    Implementation note: we deliberately do NOT go through
    :func:`authenticate` or the CloudClient, both of which can silently
    re-auth via env credentials.  If that happened, the API call would
    succeed and the probe would falsely report the original login as
    good.  Instead we read the raw token from the environment, do
    local JWT validity checks, and send the request ourselves.
    """

    def _log(msg: str) -> None:
        if verbose:
            print(f"[testLogin]   probe: {msg}")

    raw_token = os.environ.get("NDI_CLOUD_TOKEN", "")
    if not raw_token:
        _log("NDI_CLOUD_TOKEN is empty (no token in env). probe = False.")
        return False

    try:
        decoded = decodeJwt(raw_token)
    except CloudAuthError as exc:
        _log(f"decodeJwt failed: {exc}. probe = False.")
        return False

    # Local expiration check.
    if "exp" in decoded:
        try:
            exp_time = datetime.fromtimestamp(decoded["exp"], tz=timezone.utc)
        except (TypeError, ValueError, OSError) as exc:
            _log(f"could not parse exp claim: {exc}. probe = False.")
            return False
        if datetime.now(timezone.utc) >= exp_time:
            _log(f"token expired at {exp_time.isoformat()}. probe = False.")
            return False

    email_claim = decoded.get("email", "")
    if not email_claim:
        _log("token has no extractable username (no 'email' claim). probe = False.")
        return False

    _log(f"token email = {email_claim}.")
    if user_name is not None and email_claim != user_name:
        _log(f"token email does NOT match user_name ({user_name}). probe = False.")
        return False

    # Server-side verification with this exact token.
    try:
        import requests
    except ImportError:
        _log("requests not installed. probe = False.")
        return False

    config = CloudConfig.from_env()
    url = f"{config.api_url}/users/me"
    _log(f"sending GET {url} with the current token.")
    try:
        resp = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {raw_token}",
                "Accept": "application/json",
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        _log(f"GET /users/me raised: {exc}")
        return False

    if resp.status_code != 200:
        _log(f"GET /users/me returned {resp.status_code}. probe = False.")
        return False

    _log("GET /users/me returned 200 OK.")

    # Defense in depth: cross-check server email against JWT email.
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if isinstance(body, dict) and body.get("email"):
        server_email = str(body["email"])
        if server_email.lower() != str(email_claim).lower():
            _log(
                f"server email ({server_email}) does NOT match JWT email "
                f"({email_claim}). probe = False."
            )
            return False
        _log("server email matches JWT email. probe = True.")
    else:
        _log("server response had no email field; trusting 200 status. probe = True.")
    return True


# ---------------------------------------------------------------------------
# Account management  (require ``requests``)
# ---------------------------------------------------------------------------


def changePassword(
    old_password: str,
    new_password: str,
    config: CloudConfig | None = None,
) -> bool:
    """Change the current user's password.

    MATLAB equivalent: +cloud/+api/+auth/changePassword.m
    """
    import requests

    if config is None:
        config = CloudConfig.from_env()

    url = f"{config.api_url}/auth/password"
    try:
        resp = requests.post(
            url,
            json={"oldPassword": old_password, "newPassword": new_password},
            headers={
                "Authorization": f"Bearer {config.token}",
                "Accept": "application/json",
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        raise CloudAuthError(f"Change password request failed: {exc}") from exc

    if resp.status_code != 200:
        raise CloudAuthError(f"Change password failed (HTTP {resp.status_code}): {resp.text}")
    return True


def resetPassword(
    email: str,
    config: CloudConfig | None = None,
) -> bool:
    """Request a password reset email.

    MATLAB equivalent: +cloud/+api/+auth/resetPassword.m
    """
    import requests

    if config is None:
        config = CloudConfig.from_env()

    url = f"{config.api_url}/auth/password/forgot"
    try:
        resp = requests.post(
            url,
            json={"email": email},
            headers={"Accept": "application/json"},
            timeout=30,
        )
    except requests.RequestException as exc:
        raise CloudAuthError(f"Reset password request failed: {exc}") from exc

    if resp.status_code != 200:
        raise CloudAuthError(f"Reset password failed (HTTP {resp.status_code}): {resp.text}")
    return True


def verifyUser(
    email: str,
    confirmation_code: str,
    config: CloudConfig | None = None,
) -> bool:
    """Verify a user account with a confirmation code.

    MATLAB equivalent: +cloud/+api/+auth/verifyUser.m
    """
    import requests

    if config is None:
        config = CloudConfig.from_env()

    url = f"{config.api_url}/auth/verify"
    headers: dict = {"Accept": "application/json"}
    if config.token:
        headers["Authorization"] = f"Bearer {config.token}"

    try:
        resp = requests.post(
            url,
            json={"email": email, "confirmationCode": confirmation_code},
            headers=headers,
            timeout=30,
        )
    except requests.RequestException as exc:
        raise CloudAuthError(f"Verify user request failed: {exc}") from exc

    if resp.status_code != 200:
        raise CloudAuthError(f"Verify user failed (HTTP {resp.status_code}): {resp.text}")
    return True


def resendConfirmation(
    email: str,
    config: CloudConfig | None = None,
) -> bool:
    """Resend account confirmation email.

    MATLAB equivalent: +cloud/+api/+auth/resendConfirmation.m
    """
    import requests

    if config is None:
        config = CloudConfig.from_env()

    url = f"{config.api_url}/auth/confirmation/resend"
    try:
        resp = requests.post(
            url,
            json={"email": email},
            headers={"Accept": "application/json"},
            timeout=30,
        )
    except requests.RequestException as exc:
        raise CloudAuthError(f"Resend confirmation failed: {exc}") from exc

    if resp.status_code != 200:
        raise CloudAuthError(f"Resend confirmation failed (HTTP {resp.status_code}): {resp.text}")
    return True


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


def _clear_env_tokens() -> None:
    """Remove cloud-related env vars."""
    for var in ("NDI_CLOUD_TOKEN", "NDI_CLOUD_ORGANIZATION_ID"):
        os.environ.pop(var, None)
