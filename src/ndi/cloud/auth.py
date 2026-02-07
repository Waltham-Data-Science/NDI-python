"""
ndi.cloud.auth - Authentication helpers for NDI Cloud.

Provides JWT decoding, login/logout flows, and token management.

MATLAB equivalents:
    authenticate.m, login.m, logout.m
    +internal/decodeJwt.m, getTokenExpiration.m, getActiveToken.m
"""

from __future__ import annotations

import base64
import json
import os
import time as _time
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from .config import CloudConfig
from .exceptions import CloudAuthError

# ---------------------------------------------------------------------------
# JWT helpers (no cryptographic verification — matches MATLAB behaviour)
# ---------------------------------------------------------------------------


def decode_jwt(token: str) -> Dict:
    """Decode a JWT payload without signature verification.

    Matches MATLAB ``ndi.cloud.internal.decodeJwt``.

    Args:
        token: A three-part ``header.payload.signature`` JWT string.

    Returns:
        The decoded payload as a dict.

    Raises:
        CloudAuthError: If the token cannot be decoded.
    """
    try:
        parts = token.split('.')
        if len(parts) != 3:
            raise ValueError('JWT must have 3 parts')
        # Base64Url → standard Base64
        payload_b64 = parts[1].replace('-', '+').replace('_', '/')
        # Add padding
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += '=' * padding
        payload_bytes = base64.b64decode(payload_b64)
        return json.loads(payload_bytes)
    except Exception as exc:
        raise CloudAuthError(f'Failed to decode JWT: {exc}') from exc


def get_token_expiration(token: str) -> datetime:
    """Extract the ``exp`` claim from a JWT as a UTC datetime.

    Args:
        token: JWT string.

    Returns:
        Expiration time as a timezone-aware UTC datetime.

    Raises:
        CloudAuthError: If the token has no ``exp`` claim.
    """
    payload = decode_jwt(token)
    exp = payload.get('exp')
    if exp is None:
        raise CloudAuthError('JWT has no exp claim')
    return datetime.fromtimestamp(exp, tz=timezone.utc)


def verify_token(token: str) -> bool:
    """Check whether *token* is still valid (not expired).

    Does **not** contact the server — only checks the ``exp`` claim.
    """
    if not token:
        return False
    try:
        expiration = get_token_expiration(token)
        return datetime.now(timezone.utc) < expiration
    except CloudAuthError:
        return False


def get_active_token(config: Optional[CloudConfig] = None) -> Tuple[str, str]:
    """Return ``(token, org_id)`` from *config* or environment.

    Raises:
        CloudAuthError: If no valid token is available.
    """
    if config is None:
        config = CloudConfig.from_env()

    if not config.token:
        raise CloudAuthError('No token available (NDI_CLOUD_TOKEN not set)')

    if not verify_token(config.token):
        raise CloudAuthError('Token is expired')

    return config.token, config.org_id


# ---------------------------------------------------------------------------
# Login / logout  (require ``requests``)
# ---------------------------------------------------------------------------


def login(
    email: Optional[str] = None,
    password: Optional[str] = None,
    config: Optional[CloudConfig] = None,
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
            'The requests package is required for login. '
            'Install it with: pip install ndi[cloud]'
        ) from exc

    if config is None:
        config = CloudConfig.from_env()

    email = email or config.username or os.environ.get('NDI_CLOUD_USERNAME', '')
    password = password or config.password or os.environ.get('NDI_CLOUD_PASSWORD', '')

    if not email or not password:
        raise CloudAuthError('email and password are required for login')

    url = f'{config.api_url}/auth/login'
    try:
        resp = requests.post(
            url,
            json={'email': email, 'password': password},
            headers={'Accept': 'application/json'},
            timeout=30,
        )
    except requests.RequestException as exc:
        raise CloudAuthError(f'Login request failed: {exc}') from exc

    if resp.status_code != 200:
        raise CloudAuthError(
            f'Login failed (HTTP {resp.status_code}): {resp.text}'
        )

    data = resp.json()
    token = data.get('token', '')
    # Organisation ID from response
    org_id = ''
    user = data.get('user', {})
    orgs = user.get('organizations', {})
    if isinstance(orgs, dict):
        org_id = orgs.get('id', '')
    elif isinstance(orgs, list) and orgs:
        org_id = orgs[0].get('id', '')

    # Store in environment for other code to pick up
    os.environ['NDI_CLOUD_TOKEN'] = token
    if org_id:
        os.environ['NDI_CLOUD_ORGANIZATION_ID'] = org_id

    config.token = token
    config.org_id = org_id
    return config


def logout(config: Optional[CloudConfig] = None) -> None:
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
        url = f'{config.api_url}/auth/logout'
        try:
            requests.post(
                url,
                headers={
                    'Authorization': f'Bearer {config.token}',
                    'Accept': 'application/json',
                },
                timeout=30,
            )
        except requests.RequestException:
            pass  # Best-effort, matching MATLAB warning behaviour

    _clear_env_tokens()
    config.token = ''
    config.org_id = ''


def authenticate(config: Optional[CloudConfig] = None) -> str:
    """Return an active token, attempting login if needed.

    Priority (matching MATLAB ``authenticate.m``):
    1. Existing valid token in config/env.
    2. Username + password from env → login.

    Args:
        config: Optional config.

    Returns:
        A valid JWT token string.

    Raises:
        CloudAuthError: If authentication fails.
    """
    if config is None:
        config = CloudConfig.from_env()

    # 1. Already have a valid token?
    if config.token and verify_token(config.token):
        return config.token

    # 2. Try env-var credentials
    email = config.username or os.environ.get('NDI_CLOUD_USERNAME', '')
    password = config.password or os.environ.get('NDI_CLOUD_PASSWORD', '')
    if email and password:
        updated = login(email, password, config)
        return updated.token

    raise CloudAuthError(
        'No valid token and no credentials available. '
        'Set NDI_CLOUD_TOKEN or NDI_CLOUD_USERNAME/NDI_CLOUD_PASSWORD.'
    )


# ---------------------------------------------------------------------------
# Account management  (require ``requests``)
# ---------------------------------------------------------------------------


def change_password(
    old_password: str,
    new_password: str,
    config: Optional[CloudConfig] = None,
) -> bool:
    """Change the current user's password.

    MATLAB equivalent: +cloud/+api/+auth/changePassword.m
    """
    import requests

    if config is None:
        config = CloudConfig.from_env()

    url = f'{config.api_url}/auth/password'
    try:
        resp = requests.post(
            url,
            json={'oldPassword': old_password, 'newPassword': new_password},
            headers={
                'Authorization': f'Bearer {config.token}',
                'Accept': 'application/json',
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        raise CloudAuthError(f'Change password request failed: {exc}') from exc

    if resp.status_code != 200:
        raise CloudAuthError(
            f'Change password failed (HTTP {resp.status_code}): {resp.text}'
        )
    return True


def reset_password(
    email: str,
    config: Optional[CloudConfig] = None,
) -> bool:
    """Request a password reset email.

    MATLAB equivalent: +cloud/+api/+auth/resetPassword.m
    """
    import requests

    if config is None:
        config = CloudConfig.from_env()

    url = f'{config.api_url}/auth/password/forgot'
    try:
        resp = requests.post(
            url,
            json={'email': email},
            headers={'Accept': 'application/json'},
            timeout=30,
        )
    except requests.RequestException as exc:
        raise CloudAuthError(f'Reset password request failed: {exc}') from exc

    if resp.status_code != 200:
        raise CloudAuthError(
            f'Reset password failed (HTTP {resp.status_code}): {resp.text}'
        )
    return True


def verify_user(
    email: str,
    confirmation_code: str,
    config: Optional[CloudConfig] = None,
) -> bool:
    """Verify a user account with a confirmation code.

    MATLAB equivalent: +cloud/+api/+auth/verifyUser.m
    """
    import requests

    if config is None:
        config = CloudConfig.from_env()

    url = f'{config.api_url}/auth/verify'
    headers: Dict = {'Accept': 'application/json'}
    if config.token:
        headers['Authorization'] = f'Bearer {config.token}'

    try:
        resp = requests.post(
            url,
            json={'email': email, 'confirmationCode': confirmation_code},
            headers=headers,
            timeout=30,
        )
    except requests.RequestException as exc:
        raise CloudAuthError(f'Verify user request failed: {exc}') from exc

    if resp.status_code != 200:
        raise CloudAuthError(
            f'Verify user failed (HTTP {resp.status_code}): {resp.text}'
        )
    return True


def resend_confirmation(
    email: str,
    config: Optional[CloudConfig] = None,
) -> bool:
    """Resend account confirmation email.

    MATLAB equivalent: +cloud/+api/+auth/resendConfirmation.m
    """
    import requests

    if config is None:
        config = CloudConfig.from_env()

    url = f'{config.api_url}/auth/confirmation/resend'
    try:
        resp = requests.post(
            url,
            json={'email': email},
            headers={'Accept': 'application/json'},
            timeout=30,
        )
    except requests.RequestException as exc:
        raise CloudAuthError(f'Resend confirmation failed: {exc}') from exc

    if resp.status_code != 200:
        raise CloudAuthError(
            f'Resend confirmation failed (HTTP {resp.status_code}): {resp.text}'
        )
    return True


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


def _clear_env_tokens() -> None:
    """Remove cloud-related env vars."""
    for var in ('NDI_CLOUD_TOKEN', 'NDI_CLOUD_ORGANIZATION_ID'):
        os.environ.pop(var, None)
