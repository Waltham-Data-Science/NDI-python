"""ndi.update._github - GET one GitHub REST API resource (private helper).

MATLAB counterpart: ``src/ndi/+ndi/+update/private/githubApi.m``
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

API_ROOT = "https://api.github.com/"


def github_api(api_path: str, timeout: float = 10) -> Any:
    """Request ``https://api.github.com/API_PATH`` and decode its JSON.

    ``api_path`` may include a query string. If the environment variable
    ``GITHUB_TOKEN`` is set it is sent with the request, which raises
    GitHub's limit of 60 unauthenticated requests per hour. Network and HTTP
    errors propagate (as ``urllib.error.URLError`` and its subclasses).
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "NDI-python-update-check",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(API_ROOT + api_path, headers=headers)
    with urllib.request.urlopen(
        request, timeout=timeout
    ) as response:  # noqa: S310 - fixed https host
        return json.loads(response.read().decode("utf-8"))
