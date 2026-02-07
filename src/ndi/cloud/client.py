"""
ndi.cloud.client - HTTP client wrapper for NDI Cloud API.

Provides :class:`CloudClient`, a thin wrapper around ``requests.Session``
that handles authentication headers, base URL construction, and error
mapping.

MATLAB equivalent: ndi.cloud.api.url(), +implementation classes.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from .config import CloudConfig
from .exceptions import (
    CloudAPIError,
    CloudAuthError,
    CloudNotFoundError,
)


class CloudClient:
    """HTTP client for the NDI Cloud REST API.

    Example::

        config = CloudConfig.from_env()
        client = CloudClient(config)
        dataset = client.get('/datasets/{datasetId}', datasetId='abc-123')
    """

    DEFAULT_TIMEOUT = 30  # seconds

    def __init__(self, config: CloudConfig):
        self.config = config
        try:
            import requests
        except ImportError as exc:
            raise ImportError(
                'The requests package is required for CloudClient. '
                'Install it with: pip install ndi[cloud]'
            ) from exc
        self._session = requests.Session()
        self._session.headers.update({
            'Accept': 'application/json',
        })

    # ------------------------------------------------------------------
    # Public convenience methods
    # ------------------------------------------------------------------

    def get(self, endpoint: str, params: Optional[Dict] = None, **path_params: str) -> Any:
        """HTTP GET."""
        return self._request('GET', endpoint, params=params, **path_params)

    def post(
        self,
        endpoint: str,
        json: Any = None,
        data: Any = None,
        **path_params: str,
    ) -> Any:
        """HTTP POST."""
        return self._request('POST', endpoint, json=json, data=data, **path_params)

    def put(
        self,
        endpoint: str,
        json: Any = None,
        data: Any = None,
        **path_params: str,
    ) -> Any:
        """HTTP PUT."""
        return self._request('PUT', endpoint, json=json, data=data, **path_params)

    def delete(self, endpoint: str, **path_params: str) -> Any:
        """HTTP DELETE."""
        return self._request('DELETE', endpoint, **path_params)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_url(self, endpoint: str, **path_params: str) -> str:
        """Build a full URL from a template endpoint and path params.

        Template variables like ``{datasetId}`` are substituted from
        *path_params*.  The result is joined to ``config.api_url``.
        """
        # Substitute {placeholders}
        url = endpoint
        for key, value in path_params.items():
            url = url.replace(f'{{{key}}}', str(value))

        # Warn about un-replaced placeholders
        remaining = re.findall(r'\{(\w+)\}', url)
        if remaining:
            raise ValueError(
                f"Missing path parameters: {remaining} in endpoint '{endpoint}'"
            )

        # Ensure single slash join
        base = self.config.api_url.rstrip('/')
        url = url if url.startswith('/') else f'/{url}'
        return f'{base}{url}'

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: Optional[Dict] = None,
        json: Any = None,
        data: Any = None,
        timeout: Optional[int] = None,
        **path_params: str,
    ) -> Any:
        """Execute an HTTP request with auth and error handling."""
        import requests as _requests

        url = self._build_url(endpoint, **path_params)
        headers: Dict[str, str] = {}
        if self.config.token:
            headers['Authorization'] = f'Bearer {self.config.token}'

        try:
            resp = self._session.request(
                method,
                url,
                params=params,
                json=json,
                data=data,
                headers=headers,
                timeout=timeout or self.DEFAULT_TIMEOUT,
            )
        except _requests.RequestException as exc:
            raise CloudAPIError(f'Request failed: {exc}') from exc

        return self._handle_response(resp)

    def _handle_response(self, resp: Any) -> Any:
        """Map HTTP responses to return values or exceptions."""
        status = resp.status_code

        # Auth errors
        if status in (401, 403):
            raise CloudAuthError(
                f'Authentication failed (HTTP {status}): {resp.text}'
            )

        # Not found
        if status == 404:
            raise CloudNotFoundError(
                f'Not found (HTTP 404): {resp.text}',
                status_code=404,
                response_body=resp.text,
            )

        # Other client/server errors
        if status >= 400:
            body = resp.text
            try:
                body = resp.json()
            except Exception:
                pass
            raise CloudAPIError(
                f'API error (HTTP {status})',
                status_code=status,
                response_body=body,
            )

        # Success — parse JSON if possible
        if not resp.content:
            return None
        try:
            return resp.json()
        except Exception:
            return resp.text

    def __repr__(self) -> str:
        return f'CloudClient(api_url={self.config.api_url!r})'
