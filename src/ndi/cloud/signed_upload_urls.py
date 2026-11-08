"""
ndi.cloud.signed_upload_urls - many pre-signed upload URLs at once.

MATLAB equivalents: +ndi/+cloud/+upload/signedUploadURLs.m and
+ndi/+cloud/+upload/signedUploadURLs_config.m

MATLAB asks for a batch's URLs from one ``curl --parallel`` process, fed a
config file (written by ``signedUploadURLs_config``) on its standard input so
the login token is never on disk or on a command line. Python needs neither
curl nor the config: the same GET requests are made concurrently from a
thread pool, through :func:`ndi.cloud.api.files.getFileUploadURL`, sharing
one authenticated client. The dataset's organization is looked up once per
dataset per process, as MATLAB's ``organizationOf`` does.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any

__all__ = ["signedUploadURLs"]

# cloud dataset id -> organization id, asked once per dataset per process
# (MATLAB keeps the same map in a persistent variable).
_ORGANIZATIONS: dict[str, str] = {}
_ORGANIZATIONS_LOCK = threading.Lock()


def _organization_of(cloud_dataset_id: str, client: Any) -> str:
    """The dataset's organization id, or "" if it could not be looked up."""
    with _ORGANIZATIONS_LOCK:
        known = _ORGANIZATIONS.get(cloud_dataset_id)
    if known:
        return known
    from . import internal

    try:
        org = internal._datasetOrganizationId(cloud_dataset_id, client=client)
    except Exception:
        return ""
    if org:
        with _ORGANIZATIONS_LOCK:
            _ORGANIZATIONS[cloud_dataset_id] = org
    return org or ""


def signedUploadURLs(
    cloudDatasetId: str,
    uids: list[str],
    crcs: list[str],
    folder: str = "",
    *,
    parallel: int = 8,
    timeout: float = 120,
    client: Any = None,
) -> tuple[bool, list[str], str]:
    """Many signed upload URLs at once.

    MATLAB equivalent: ndi.cloud.upload.signedUploadURLs

    Asks NDI Cloud for a pre-signed upload URL for each file uid in *uids*,
    each signed for the CRC-32 in *crcs* (:func:`ndi.fun.file.crc32`; ``""``
    for none), as :func:`ndi.cloud.api.files.getFileUploadURL` does one at a
    time -- but *parallel* requests at a time, with the dataset's
    organization looked up once.

    Args:
        cloudDatasetId: The cloud dataset id.
        uids: File uids, one per URL wanted.
        crcs: The CRC-32 each URL is signed for, one per uid ("" for none).
        folder: Kept for MATLAB's argument order. MATLAB writes each answer
            there and deletes it once read; Python holds the answers in
            memory, so it is not used.
        parallel: Requests at a time (MATLAB's ``'Parallel'``). Default 8.
        timeout: Seconds to wait for all of them (MATLAB's ``'Timeout'``).
            Default 120.
        client: An authenticated :class:`~ndi.cloud.client.CloudClient`,
            shared by every request. Default: one made from the environment.

    Returns:
        ``(ok, urls, msg)``. *ok* is False (and *urls* empty) if any URL could
        not be had; *msg* then says why. The caller then asks one at a time.
    """
    del folder  # answers are held in memory, not written to a folder
    n = len(uids)
    if len(crcs) != n:
        return False, [], "UIDS and CRCS must have one entry per file"
    if n == 0:
        return True, [], ""
    if client is None:
        try:
            from .client import CloudClient

            client = CloudClient.from_env()
        except Exception as exc:
            return False, [], f"could not log in to NDI Cloud ({exc})"
    org = _organization_of(str(cloudDatasetId), client)
    if not org:
        return False, [], "could not look up the dataset's organization"

    from .api import files as files_api

    def one(i: int) -> str:
        return str(
            files_api.getFileUploadURL(
                org,
                str(cloudDatasetId),
                str(uids[i]),
                checksum_crc32=str(crcs[i] or ""),
                client=client,
            )
            or ""
        )

    urls: list[str] = [""] * n
    pool = ThreadPoolExecutor(max_workers=max(1, int(parallel)), thread_name_prefix="ndi-urls")
    deadline = time.monotonic() + float(timeout)
    try:
        futures = [pool.submit(one, i) for i in range(n)]
        for i, fut in enumerate(futures):
            try:
                urls[i] = fut.result(timeout=max(0.0, deadline - time.monotonic()))
            except FuturesTimeout:
                return False, [], f"the upload URLs did not come back within {timeout:g} s"
            except Exception as exc:
                detail = str(exc)[:300]
                return False, [], f"no upload URL came back for {uids[i]} ({detail})"
            if not urls[i]:
                return False, [], f"no upload URL came back for {uids[i]}"
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return True, urls, ""
