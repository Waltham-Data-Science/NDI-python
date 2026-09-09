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


def tokenSecondsRemaining(token: str = "") -> float | None:
    """Seconds until the cloud token expires, or None if unreadable.

    Negative when it has already lapsed, which is the interesting case:
    "expired 20 minutes ago" and "expires in 20 minutes" are the same
    number with a sign, and a caller showing either wants both.

    None means the token is absent or opaque -- no ``exp`` claim to read.
    That is not the same as expired, and a caller must not treat it as
    such: an opaque token is the server's to judge.

    Args:
        token: the JWT. Defaults to whatever is in the environment, which
            is where a login leaves it.
    """
    token = token or os.environ.get("NDI_CLOUD_TOKEN", "")
    if not token:
        return None
    try:
        expires = getTokenExpiration(token)
    except CloudAuthError:
        return None
    return (expires - datetime.now(timezone.utc)).total_seconds()


def tokenStatusLine(token: str = "") -> str:
    """One line saying how much life the cloud token has left.

    For a viewer that stays open: a session outlives its token, and the
    first sign of that is otherwise a file that will not load. Said out
    loud and kept current, it is a clock instead of a surprise.
    """
    left = tokenSecondsRemaining(token)
    if left is None:
        return "not signed in" if not (token or os.environ.get("NDI_CLOUD_TOKEN")) else "unknown"
    if left <= 0:
        return f"EXPIRED {_roughly(-left)} ago"
    return f"signed in, {_roughly(left)} left"


def _roughly(seconds: float) -> str:
    """A duration in the largest unit that still says something.

    Seconds matter near zero and are noise at an hour, which is the whole
    range this is used over.
    """
    seconds = max(0.0, float(seconds))
    if seconds < 90:
        return f"{int(round(seconds))}s"
    minutes = seconds / 60.0
    if minutes < 90:
        return f"{int(round(minutes))} min"
    return f"{minutes / 60.0:.1f} hours"


def credentialReport() -> str:
    """What this process can and cannot authenticate with, as text.

    An authentication failure reaches most people through something else
    -- a tile that will not load, an API call that raises -- and from
    there it is hard to tell WHERE the credentials were supposed to come
    from. This walks the same three steps :func:`authenticate` walks and
    reports each one, so the answer is a line rather than a bisection.

    It answers, in particular, the question that a re-login does not: the
    token lives in ``os.environ``, so it belongs to ONE PROCESS. Logging
    in from a shell, or from MATLAB, leaves a separately launched viewer
    exactly as unauthenticated as it was. Run this IN THE ENVIRONMENT THAT
    FAILED, not in the one you logged in from.

    Nothing here prints a password or a token; the token is reported as
    present or absent and by its expiry, never by its value.

    Returns:
        A short multi-line report, safe to paste.
    """
    config = CloudConfig.from_env()
    lines = [
        f"api            : {config.api_url}",
        f"token in env   : {'yes' if os.environ.get('NDI_CLOUD_TOKEN') else 'no'}",
    ]
    if config.token:
        try:
            expires = getTokenExpiration(config.token)
            state = "EXPIRED" if isTokenExpired(config.token) else "valid"
            lines.append(f"token          : {state}, exp {expires:%Y-%m-%d %H:%M UTC}")
        except CloudAuthError as exc:
            lines.append(f"token          : unreadable ({exc})")
    lines.append(f"organization   : {config.org_id or '(none)'}")
    lines.append(f"username in env: {'yes' if os.environ.get('NDI_CLOUD_USERNAME') else 'no'}")
    email, password = _profile_credentials()
    if email and password:
        lines.append(f"profile        : {email}")
    else:
        lines.append("profile        : none usable")

    # The verdict last, because it is what the reader came for, and it is
    # the only line that can disagree with the ones above -- a credential
    # that is present but wrong fails here and nowhere else.
    try:
        _token, org = authenticate(config)
    except CloudAuthError as exc:
        lines.append(f"authenticate   : FAILED -- {exc}")
    else:
        lines.append(f"authenticate   : ok (organization {org})")
    return "\n".join(lines)


def _noCredentialsMessage(config: CloudConfig) -> str:
    """Say WHICH step of :func:`authenticate` came up empty.

    Three quite different situations end at the same raise, and the reader
    of the message is usually looking at a failed file fetch rather than at
    a login: a token that expired while the process ran, a token that was
    never set, or credentials that exist but did not resolve. Naming the
    one that happened is the difference between "log back in and relaunch"
    and "you have not set this up".

    The remedy is the same sentence in every case, because it is the one
    that also prevents the next occurrence: with a username and password
    reachable, :func:`authenticate` renews an expired token by itself and
    step 1 stops mattering.
    """
    fix = (
        "Set NDI_CLOUD_USERNAME/NDI_CLOUD_PASSWORD, or save a default cloud "
        "profile (ndi.cloud.profile.add(...) then set_default(...)), so the "
        "token can be renewed without you. NDI_CLOUD_TOKEN alone works only "
        "until it expires."
    )
    if not config.token:
        return f"Not logged in to NDI Cloud: no token, no username/password, no profile. {fix}"

    if isTokenExpired(config.token):
        when = ""
        try:
            when = f" (it expired at {getTokenExpiration(config.token):%Y-%m-%d %H:%M UTC})"
        except CloudAuthError:
            when = " (its expiry could not be read, which counts as expired)"
        # The token is held in os.environ, so a login in another shell does
        # NOT reach a process that is already running -- which is exactly
        # the shape of this failure when a viewer has been open a while.
        return (
            f"The NDI Cloud token has expired{when}, and there are no "
            f"credentials to renew it with. A login in another shell will "
            f"not reach this process: log in and start it again. "
            f"{fix}"
        )

    # A token that is neither absent nor expired: step 1 wanted an org id
    # too, and did not get one.
    return (
        "The NDI Cloud token is present and unexpired but carries no "
        f"organization id, so it cannot be used. {fix}"
    )


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
            "The requests package is required for login. " "Install it with: pip install ndi[cloud]"
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
        # resp.text often echoes the submitted credentials on this endpoint,
        # so keep it out of the raised message (which lands in tracebacks, CI
        # logs, and error reporters). A DEBUG line preserves the body for
        # local troubleshooting when the caller opts into it.
        logger.debug("POST /auth/login failed body: %s", resp.text)
        raise CloudAuthError(f"Login failed (HTTP {resp.status_code})")

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


def _profile_credentials() -> tuple[str, str]:
    """Return ``(email, password)`` from the saved cloud profile.

    The session's current profile wins over the persisted default, matching
    :func:`ndi.cloud.profile.get_current` / :func:`~ndi.cloud.profile.get_default`.

    Returns three empty strings when there is no usable profile. Every
    failure mode here is benign -- no profile file, no default set, a
    secrets backend that cannot decrypt -- and none of them should turn a
    missing credential into a traceback from an unrelated call site, so they
    all fall through to the caller's own "no credentials" error.
    """
    try:
        from . import profile as _profile

        entry = _profile.get_current() or _profile.get_default()
        if entry is None:
            return "", ""
        password = _profile.get_password(entry.UID)
        if not entry.Email or not password:
            return "", ""
        return entry.Email, password
    except Exception as exc:  # noqa: BLE001 - see docstring
        logger.debug("No usable cloud profile: %s", exc)
        return "", ""


def authenticate(config: CloudConfig | None = None) -> tuple[str, str]:
    """Return an active token and organization ID, attempting login if needed.

    Priority (matching MATLAB ``authenticate.m``):
    1. Existing valid token in config/env (local JWT exp pre-check).
    2. Username + password from env → login.
    3. The saved cloud profile (current, else default) → login.

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

    # 3. Fall back to the saved cloud profile.
    #
    #    MATLAB's authenticate.m has this step -- authenticatedWithSecret,
    #    which reads the MATLAB Vault -- ahead of the environment one. Python
    #    had no equivalent at all, so a user who had set up a profile (the
    #    documented way to keep a cloud password) still got "no credentials
    #    available" from anything that authenticated implicitly: every
    #    @_auto_client API call, and, most visibly, the ndic:// file handler
    #    that fetches pyramid tiles for a downloaded dataset.
    #
    #    It goes last rather than first because an explicitly exported
    #    NDI_CLOUD_USERNAME is a deliberate override and should keep winning
    #    over whatever is on disk.
    #    The profile's Stage picks prod vs dev, but that is resolved in
    #    CloudConfig.from_env rather than here, because it has to apply to a
    #    config that short-circuits at step 1 on an already-exported token.
    email, password = _profile_credentials()
    if email and password:
        updated = login(email, password, config)
        return updated.token, updated.org_id

    # WHICH OF THE THREE FAILED IS THE WHOLE DIAGNOSIS, and the old message
    # ran them together. "No valid token and no credentials available" is
    # true whether you never logged in or logged in two hours ago, and
    # those want opposite responses -- and it lands where it is least
    # legible: on a tile fetch, in a napari toast, one per tile, an hour
    # into a session that was working. An EXPIRED token in particular is
    # invisible from that sentence, so the tile reads as missing data.
    raise CloudAuthError(_noCredentialsMessage(config))


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
        logger.debug("POST /auth/password failed body: %s", resp.text)
        raise CloudAuthError(f"Change password failed (HTTP {resp.status_code})")
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
        logger.debug("POST /auth/password/forgot failed body: %s", resp.text)
        raise CloudAuthError(f"Reset password failed (HTTP {resp.status_code})")
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
        logger.debug("POST /auth/verify failed body: %s", resp.text)
        raise CloudAuthError(f"Verify user failed (HTTP {resp.status_code})")
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
        logger.debug("POST /auth/confirmation/resend failed body: %s", resp.text)
        raise CloudAuthError(f"Resend confirmation failed (HTTP {resp.status_code})")
    return True


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


def _clear_env_tokens() -> None:
    """Remove cloud-related env vars."""
    for var in ("NDI_CLOUD_TOKEN", "NDI_CLOUD_ORGANIZATION_ID"):
        os.environ.pop(var, None)
