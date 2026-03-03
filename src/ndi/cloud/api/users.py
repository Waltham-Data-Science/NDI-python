"""
ndi.cloud.api.users - User management.

All functions accept an optional ``client`` keyword argument.  When omitted,
a client is created automatically from environment variables.

MATLAB equivalents: +ndi/+cloud/+api/+users/*.m,
    +implementation/+users/*.m
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import SkipValidation, validate_call

from ..client import CloudClient, _auto_client
from ._validators import VALIDATE_CONFIG, NonEmptyStr

_Client = Annotated[CloudClient | None, SkipValidation()]


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def create_user(
    email: NonEmptyStr,
    name: NonEmptyStr,
    password: NonEmptyStr,
    *,
    client: _Client = None,
) -> dict[str, Any]:
    """POST /users -- Create a new user (no auth required)."""
    return client.post(
        "/users",
        json={"email": email, "name": name, "password": password},
    )


@_auto_client
def get_current_user(*, client: _Client = None) -> dict[str, Any]:
    """GET /users/me -- Get the authenticated user's profile.

    The response includes the user's organization memberships.
    """
    return client.get("/users/me")


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def get_user(user_id: NonEmptyStr, *, client: _Client = None) -> dict[str, Any]:
    """GET /users/{userId}"""
    return client.get("/users/{userId}", userId=user_id)
