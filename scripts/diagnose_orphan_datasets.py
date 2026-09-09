"""Inventory NDI_PYTEST_* datasets across (user, environment) for issue #106.

Read-only. Emits one JSON report per invocation to stdout (or to the file
named by ``--out``) with, for each of the four (user, environment) pairs:

- how many NDI_PYTEST_* datasets exist
- whether ``listAllDatasets`` returns more than ``listDatasets``' first page
- what state each dataset is in, so far as the API exposes it
- age distribution, for correlating leftover timestamps against nightly runs

No deletions. The delete-return-per-state probe in issue #106's fourth
diagnostic bullet is deliberately not here -- it is destructive and belongs
in a one-shot manual run once we have picked a target dataset.

Expects the four credentials the nightly already uses:
    NDI_CLOUD_TEST_USER_1_USERNAME / _PASSWORD
    NDI_CLOUD_TEST_USER_2_USERNAME / _PASSWORD
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import traceback
from collections import Counter
from typing import Any

# Buckets in seconds, matched in order. Anything older than the last threshold
# falls into "gt_30d".
_AGE_BUCKETS = [
    ("lt_1h", 60 * 60),
    ("1h_to_24h", 24 * 60 * 60),
    ("1d_to_7d", 7 * 24 * 60 * 60),
    ("7d_to_30d", 30 * 24 * 60 * 60),
]


def _parse_iso(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    # The API returns ``2026-08-24T12:34:56.789Z``.
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _age_bucket(created: dt.datetime | None, now: dt.datetime) -> str:
    if created is None:
        return "unknown_created"
    age = (now - created).total_seconds()
    for name, threshold in _AGE_BUCKETS:
        if age < threshold:
            return name
    return "gt_30d"


def _state_label(dataset: dict[str, Any]) -> str:
    """Pick a state string without assuming what the API calls the field.

    The whole point of the diagnostic is to learn the field name; until
    then, expose whichever flags are present so the report shows them.
    """
    published = dataset.get("isPublished")
    submitted = dataset.get("isSubmitted")
    explicit = dataset.get("state") or dataset.get("status")
    if isinstance(explicit, str) and explicit:
        return f"state:{explicit}"
    if published is True:
        return "published"
    if submitted is True:
        return "submitted"
    if published is False and submitted is False:
        return "draft"
    return "unknown"


def _run_one(user_index: int, environment: str, username: str, password: str) -> dict[str, Any]:
    """Log in as one user against one environment and inventory the orphans."""
    # Local imports: the module is invoked as a script from the repo root, so
    # the src layout has already been installed by the workflow.
    from ndi.cloud.api.datasets import listAllDatasets, listDatasets
    from ndi.cloud.auth import login
    from ndi.cloud.client import CloudClient
    from ndi.cloud.config import CloudConfig

    result: dict[str, Any] = {
        "user_index": user_index,
        "environment": environment,
        "login_ok": False,
        "org_id": "",
        "error": None,
    }

    # A per-user config, isolated from process env so a second call doesn't
    # inherit the first's token.
    config = CloudConfig(
        api_url="https://api.ndi-cloud.com/v1"
        if environment == "prod"
        else "https://dev-api.ndi-cloud.com/v1",
        username=username,
        password=password,
    )
    try:
        config = login(config=config)
    except Exception as exc:  # pragma: no cover -- diagnostic path
        result["error"] = f"login failed: {exc}"
        return result

    if not config.is_authenticated:
        result["error"] = "login returned no token"
        return result

    result["login_ok"] = True
    result["org_id"] = config.org_id

    client = CloudClient(config)

    try:
        first_page = listDatasets(config.org_id, client=client)
    except Exception as exc:
        result["error"] = f"listDatasets failed: {exc}"
        return result

    first_page_datasets = first_page.get("datasets", []) if isinstance(first_page, dict) else []
    result["list_first_page_count"] = len(first_page_datasets)
    result["list_first_page_totalNumber"] = (
        first_page.get("totalNumber") if isinstance(first_page, dict) else None
    )

    try:
        all_response = listAllDatasets(config.org_id, client=client)
    except Exception as exc:
        result["error"] = f"listAllDatasets failed: {exc}"
        return result

    all_datasets = list(all_response) if all_response is not None else []
    result["list_all_count"] = len(all_datasets)

    now = dt.datetime.now(dt.timezone.utc)

    orphans: list[dict[str, Any]] = []
    state_counter: Counter[str] = Counter()
    age_counter: Counter[str] = Counter()
    key_union: set[str] = set()

    for ds in all_datasets:
        name = ds.get("name", "") if isinstance(ds, dict) else ""
        if not isinstance(name, str) or not name.startswith("NDI_PYTEST"):
            continue
        key_union.update(k for k in ds.keys() if isinstance(k, str))
        created = _parse_iso(ds.get("createdAt") or ds.get("created_at"))
        state = _state_label(ds)
        state_counter[state] += 1
        age_counter[_age_bucket(created, now)] += 1
        orphans.append(
            {
                "_id": ds.get("_id") or ds.get("id"),
                "name": name,
                "createdAt": ds.get("createdAt"),
                "updatedAt": ds.get("updatedAt"),
                "isPublished": ds.get("isPublished"),
                "isSubmitted": ds.get("isSubmitted"),
                "state": ds.get("state"),
                "status": ds.get("status"),
                "state_label": state,
            }
        )

    result["orphan_count"] = len(orphans)
    result["by_state"] = dict(state_counter)
    result["age_buckets"] = dict(age_counter)
    result["observed_dataset_keys"] = sorted(key_union)
    result["orphans"] = orphans
    return result


def _collect(now_iso: str) -> dict[str, Any]:
    users = [
        (
            1,
            os.environ.get("NDI_CLOUD_TEST_USER_1_USERNAME", ""),
            os.environ.get("NDI_CLOUD_TEST_USER_1_PASSWORD", ""),
        ),
        (
            2,
            os.environ.get("NDI_CLOUD_TEST_USER_2_USERNAME", ""),
            os.environ.get("NDI_CLOUD_TEST_USER_2_PASSWORD", ""),
        ),
    ]
    runs: list[dict[str, Any]] = []
    for user_index, username, password in users:
        for environment in ("prod", "dev"):
            if not username or not password:
                runs.append(
                    {
                        "user_index": user_index,
                        "environment": environment,
                        "login_ok": False,
                        "error": "missing credentials in env",
                    }
                )
                continue
            try:
                runs.append(_run_one(user_index, environment, username, password))
            except Exception:  # pragma: no cover -- diagnostic path
                runs.append(
                    {
                        "user_index": user_index,
                        "environment": environment,
                        "login_ok": False,
                        "error": traceback.format_exc(limit=3),
                    }
                )
    return {"timestamp": now_iso, "script_version": 1, "runs": runs}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out",
        help="Path to write the JSON report to. Prints to stdout if omitted.",
    )
    args = ap.parse_args(argv)
    now_iso = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    report = _collect(now_iso)
    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(payload + "\n")
    else:
        print(payload)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
