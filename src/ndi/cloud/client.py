"""
ndi.cloud.client - HTTP client wrapper for NDI Cloud API.

Provides :class:`CloudClient`, a thin wrapper around ``requests.Session``
that handles authentication headers, base URL construction, and error
mapping.

MATLAB equivalent: ndi.cloud.api.url(), +implementation classes.
"""

from __future__ import annotations

import functools
import re
from typing import Any
from urllib.parse import quote as _url_quote

from .config import CloudConfig
from .exceptions import (
    CloudAPIError,
    CloudAuthError,
    CloudNotFoundError,
)


class APIResponse:
    """Wrapper around cloud API results with request metadata.

    MATLAB equivalent: the 4-output ``[b, answer, apiResponse, apiURL]``
    pattern returned by all ``ndi.cloud.api.call`` subclasses.

    This class **transparently proxies** dict and list operations to the
    underlying ``data`` payload so that existing code like
    ``result.get("field")`` or ``for doc in result`` keeps working.
    New code can access ``result.success``, ``result.status_code``, and
    ``result.url`` for diagnostics.

    Attributes:
        success: True if the request returned HTTP 2xx.
        data: The parsed response payload (dict, list, str, or None).
        status_code: The HTTP status code.
        url: The full request URL.
    """

    __slots__ = ("success", "data", "status_code", "url")

    def __init__(
        self,
        data: Any,
        *,
        success: bool = True,
        status_code: int = 200,
        url: str = "",
    ):
        self.success = success
        self.data = data
        self.status_code = status_code
        self.url = url

    # -- Dict proxy (when data is a dict) --

    def get(self, key: str, default: Any = None) -> Any:
        """Proxy ``dict.get()`` to the data payload."""
        if isinstance(self.data, dict):
            return self.data.get(key, default)
        return default

    def __getitem__(self, key: Any) -> Any:
        return self.data[key]

    def __contains__(self, key: Any) -> bool:
        return key in self.data

    def keys(self):
        return self.data.keys()

    def values(self):
        return self.data.values()

    def items(self):
        return self.data.items()

    # -- MATLAB-style tuple unpacking --

    def __iter__(self):
        """Enable ``b, answer, status, url = result`` unpacking.

        Mirrors MATLAB's ``[b, answer, apiResponse, apiURL]`` pattern.
        To iterate over the data payload, use ``result.data`` explicitly.
        """
        return iter((self.success, self.data, self.status_code, self.url))

    # -- General --

    def __bool__(self) -> bool:
        return bool(self.data) if self.data is not None else False

    def __repr__(self) -> str:
        status = "OK" if self.success else "FAIL"
        return f"APIResponse({status}, status={self.status_code}, url={self.url!r})"


class CloudClient:
    """HTTP client for the NDI Cloud REST API.

    Example::

        config = CloudConfig.from_env()
        client = CloudClient(config)
        dataset = client.get('/datasets/{datasetId}', datasetId='abc-123')
    """

    DEFAULT_TIMEOUT = 120  # seconds

    def __init__(self, config: CloudConfig):
        self.config = config
        try:
            import requests
        except ImportError as exc:
            raise ImportError(
                "The requests package is required for CloudClient. "
                "Install it with: pip install ndi[cloud]"
            ) from exc
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Accept": "application/json",
            }
        )

    # ------------------------------------------------------------------
    # Public convenience methods
    # ------------------------------------------------------------------

    def get(self, endpoint: str, params: dict | None = None, **path_params: str) -> Any:
        """HTTP GET."""
        return self._request("GET", endpoint, params=params, **path_params)

    def post(
        self,
        endpoint: str,
        json: Any = None,
        data: Any = None,
        **path_params: str,
    ) -> Any:
        """HTTP POST."""
        return self._request("POST", endpoint, json=json, data=data, **path_params)

    def put(
        self,
        endpoint: str,
        json: Any = None,
        data: Any = None,
        **path_params: str,
    ) -> Any:
        """HTTP PUT."""
        return self._request("PUT", endpoint, json=json, data=data, **path_params)

    def delete(self, endpoint: str, params: dict | None = None, **path_params: str) -> Any:
        """HTTP DELETE."""
        return self._request("DELETE", endpoint, params=params, **path_params)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_url(self, endpoint: str, **path_params: str) -> str:
        """Build a full URL from a template endpoint and path params.

        Template variables like ``{datasetId}`` are substituted from
        *path_params*.  The result is joined to ``config.api_url``.
        """
        # Substitute {placeholders} with URL-encoded values
        url = endpoint
        for key, value in path_params.items():
            url = url.replace(f"{{{key}}}", _url_quote(str(value), safe=""))

        # Warn about un-replaced placeholders
        remaining = re.findall(r"\{(\w+)\}", url)
        if remaining:
            raise ValueError(f"Missing path parameters: {remaining} in endpoint '{endpoint}'")

        # Ensure single slash join
        base = self.config.api_url.rstrip("/")
        url = url if url.startswith("/") else f"/{url}"
        return f"{base}{url}"

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict | None = None,
        json: Any = None,
        data: Any = None,
        timeout: int | None = None,
        **path_params: str,
    ) -> APIResponse:
        """Execute an HTTP request with auth and error handling.

        Returns:
            :class:`APIResponse` wrapping the parsed data with metadata
            (``success``, ``status_code``, ``url``).  On HTTP errors the
            method still raises the appropriate exception; the
            ``APIResponse`` is only returned for successful (2xx) requests.
        """
        import requests as _requests

        url = self._build_url(endpoint, **path_params)
        headers: dict[str, str] = {}
        if self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"

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
            raise CloudAPIError(f"Request failed: {exc}") from exc

        parsed = self._handle_response(resp)
        return APIResponse(
            parsed,
            success=True,
            status_code=resp.status_code,
            url=url,
        )

    def _handle_response(self, resp: Any) -> Any:
        """Map HTTP responses to return values or exceptions."""
        status = resp.status_code

        # Auth errors
        if status in (401, 403):
            raise CloudAuthError(f"Authentication failed (HTTP {status}): {resp.text}")

        # Not found
        if status == 404:
            raise CloudNotFoundError(
                f"Not found (HTTP 404): {resp.text}",
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
                f"API error (HTTP {status})",
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

    @classmethod
    def from_env(cls) -> CloudClient:
        """Create an authenticated client from environment variables.

        Uses :func:`~ndi.cloud.auth.authenticate` to obtain a valid
        token (checks ``NDI_CLOUD_TOKEN`` first, then falls back to
        ``NDI_CLOUD_USERNAME`` / ``NDI_CLOUD_PASSWORD``).  This matches
        the MATLAB behaviour where ``ndi.cloud.authenticate`` reads
        credentials from the environment automatically.

        Returns:
            An authenticated :class:`CloudClient`.

        Raises:
            CloudAuthError: If no valid credentials are available.
        """
        from .auth import authenticate

        config = CloudConfig.from_env()
        config.token = authenticate(config)
        return cls(config)

    def __repr__(self) -> str:
        return f"CloudClient(api_url={self.config.api_url!r})"


def _auto_client(func):
    """Decorator that makes the ``client`` keyword parameter optional.

    If the ``client`` keyword argument is ``None`` or absent, a client
    is created automatically from environment variables via
    :meth:`CloudClient.from_env`.

    All decorated functions must declare ``client`` as a keyword-only
    parameter with a default of ``None``::

        @_auto_client
        def get_dataset(dataset_id: str, *, client: CloudClient | None = None):
            return client.get(...)

    Callers can use either style (matching MATLAB's no-client API)::

        get_dataset("abc-123")                    # auto-built from env
        get_dataset("abc-123", client=my_client)  # explicit client
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("client") is None:
            kwargs["client"] = CloudClient.from_env()
        return func(*args, **kwargs)

    return wrapper
