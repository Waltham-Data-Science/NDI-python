"""
ndi.cloud.api.users - User management.

MATLAB equivalents: +ndi/+cloud/+api/+users/*.m,
    +implementation/+users/*.m
"""

from __future__ import annotations

from typing import Any, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from ..client import CloudClient


def create_user(
    client: 'CloudClient',
    email: str,
    name: str,
    password: str,
) -> Dict[str, Any]:
    """POST /users — Create a new user (no auth required)."""
    return client.post(
        '/users',
        json={'email': email, 'name': name, 'password': password},
    )


def get_current_user(client: 'CloudClient') -> Dict[str, Any]:
    """GET /users/me — Get the authenticated user's profile.

    The response includes the user's organization memberships.
    """
    return client.get('/users/me')


def get_user(client: 'CloudClient', user_id: str) -> Dict[str, Any]:
    """GET /users/{userId}"""
    return client.get('/users/{userId}', userId=user_id)
