"""Leftover-dataset janitor for the NDI Cloud test accounts.

Run it standalone (no pytest involved)::

    python -m tests.tools.cloud_janitor --prefix NDI_PYTEST --max-age 0 \
        --fail-on-residual

Why this module exists
----------------------
The August 2026 CI audit measured the previous in-test cleanup fixture
(``tests/test_cloud_live.py::_cleanup_stale_pytest_datasets``) against reality:
across four consecutive nightly runs it reported 72 -> 73 -> 74 -> 75 leftover
prod datasets, warned that it was "cleaning up N leftover NDI_PYTEST_*
dataset(s)", and deleted **0 of 294**.  It called ``deleteDataset`` inside
``except Exception: pass`` and it listed with the single-page ``listDatasets``.
The result was a remediation-shaped warning that remediated nothing while the
job stayed green.

This janitor is built so that cannot happen again:

* it lists with :func:`ndi.cloud.api.datasets.listAllDatasets` (auto-paginating)
  rather than a single page;
* every mutating call is retried on the AWS gateway's 502/504 responses;
* a submitted or published dataset is un-submitted / unpublished first, because
  the server appears to refuse a hard delete while ``isSubmitted`` is true --
  that is where the +1/day/env leak comes from;
* nothing is inferred from the absence of an exception: after the deletes the
  janitor **re-lists** and reports what is still there;
* ``--fail-on-residual`` turns anything still standing into a non-zero exit, so
  a broken sweep makes the workflow red instead of printing a warning.

Exit codes
----------
``0``  sweep completed and (if ``--fail-on-residual``) nothing remains
``1``  ``--fail-on-residual`` and at least one targeted dataset survived
``2``  the sweep could not be carried out at all (auth/listing failure)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

DEFAULT_PREFIX = "NDI_PYTEST"

#: HTTP statuses worth retrying.  The NDI Cloud API runs behind an AWS Lambda
#: gateway with a 30 s timeout, so write-heavy calls routinely return 504.
RETRYABLE_STATUS = frozenset({502, 503, 504})


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def default_api():
    """Return the real ``ndi.cloud.api.datasets`` module.

    Imported lazily so that ``--help`` works without a configured environment.
    """
    from ndi.cloud.api import datasets

    return datasets


def dataset_id_of(dataset: dict[str, Any]) -> str:
    """Return the cloud id of *dataset*, tolerating ``_id`` or ``id``."""
    return str(dataset.get("_id") or dataset.get("id") or "")


def parse_timestamp(value: Any) -> float | None:
    """Parse an ISO-8601 timestamp into a POSIX float, or return ``None``.

    Returns ``None`` for anything unparseable rather than guessing, so that
    callers can distinguish "definitely old" from "age unknown".
    """
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        # Cloud responses occasionally carry epoch milliseconds.
        return float(value) / 1000.0 if float(value) > 1e11 else float(value)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.timestamp()


_AGE_KEYS = ("createdAt", "created_at", "creationDate", "updatedAt", "updated_at")


def dataset_age_hours(dataset: dict[str, Any], now: float | None = None) -> float | None:
    """Age of *dataset* in hours, or ``None`` when no timestamp is parseable."""
    for key in _AGE_KEYS:
        stamp = parse_timestamp(dataset.get(key))
        if stamp is not None:
            reference = time.time() if now is None else now
            return (reference - stamp) / 3600.0
    return None


def select_stale(
    datasets: Iterable[dict[str, Any]],
    prefix: str = DEFAULT_PREFIX,
    min_age_hours: float = 0.0,
    now: float | None = None,
) -> list[dict[str, Any]]:
    """Return the datasets this janitor is allowed to remove.

    A dataset qualifies when its name *starts with* ``prefix`` (never a
    substring match -- a real dataset that merely mentions the prefix must be
    safe) and it carries a usable id.

    ``min_age_hours`` is a floor, not a filter to be guessed around: a dataset
    whose age cannot be determined is **excluded** whenever a floor is set.  A
    janitor that assumes unknown means old is one bad response away from
    deleting live data.
    """
    selected: list[dict[str, Any]] = []
    for dataset in datasets:
        name = str(dataset.get("name") or "")
        if not name.startswith(prefix):
            continue
        if not dataset_id_of(dataset):
            continue
        if min_age_hours > 0:
            age = dataset_age_hours(dataset, now=now)
            if age is None or age < min_age_hours:
                continue
        selected.append(dataset)
    return selected


def retry_on_server_error(
    fn: Callable[[], Any],
    retries: int = 3,
    delay: float = 10.0,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """Call *fn*, retrying with linear back-off on retryable server errors."""
    from ndi.cloud.exceptions import CloudAPIError

    for attempt in range(retries + 1):
        try:
            return fn()
        except CloudAPIError as exc:
            if getattr(exc, "status_code", 0) in RETRYABLE_STATUS and attempt < retries:
                sleep(delay * (attempt + 1))
                continue
            raise
    raise AssertionError("unreachable")  # pragma: no cover


def _describe(exc: BaseException) -> str:
    status = getattr(exc, "status_code", 0)
    return f"{type(exc).__name__}(status={status}): {exc}"


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass
class DatasetOutcome:
    """What happened to one dataset."""

    dataset_id: str
    name: str
    status: str  # "deleted" | "failed" | "dry-run"
    detail: str = ""
    steps: tuple[str, ...] = ()

    def render(self) -> str:
        line = f"  [{self.status:>7}] {self.dataset_id}  {self.name}"
        if self.steps:
            line += f"  steps={','.join(self.steps)}"
        if self.detail:
            line += f"\n            {self.detail}"
        return line


@dataclass
class SweepReport:
    """Outcome of a whole sweep, including the post-sweep verification."""

    org_id: str
    prefix: str
    min_age_hours: float
    dry_run: bool
    outcomes: list[DatasetOutcome] = field(default_factory=list)
    residual: list[dict[str, Any]] = field(default_factory=list)
    verified: bool = True

    @property
    def targeted(self) -> int:
        return len(self.outcomes)

    @property
    def deleted(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "deleted")

    @property
    def failed(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "failed")

    def exit_code(self, fail_on_residual: bool = False) -> int:
        if fail_on_residual and self.residual:
            return 1
        return 0

    def render(self) -> str:
        head = (
            f"cloud-janitor: org={self.org_id or '<from config>'} "
            f"prefix={self.prefix!r} min_age_hours={self.min_age_hours} "
            f"dry_run={self.dry_run}"
        )
        lines = [head, f"  targeted={self.targeted} deleted={self.deleted} failed={self.failed}"]
        lines.extend(o.render() for o in self.outcomes)
        if not self.verified:
            lines.append("  verification skipped (dry run)")
        elif self.residual:
            lines.append(f"  RESIDUAL: {len(self.residual)} dataset(s) still present after sweep:")
            lines.extend(
                f"    - {dataset_id_of(d)}  {d.get('name', '?')}"
                f"  isSubmitted={d.get('isSubmitted')} isPublished={d.get('isPublished')}"
                for d in self.residual
            )
        else:
            lines.append("  residual: none")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


def purge_dataset(
    dataset: dict[str, Any],
    *,
    api=None,
    client=None,
    dry_run: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> DatasetOutcome:
    """Un-submit / unpublish as needed, then hard-delete *dataset*.

    Never raises: the outcome carries the failure so the caller can report
    every dataset rather than stopping at the first error.
    """
    from ndi.cloud.exceptions import CloudError

    api = default_api() if api is None else api
    ds_id = dataset_id_of(dataset)
    name = str(dataset.get("name") or "")
    steps: list[str] = []
    notes: list[str] = []

    if dry_run:
        if dataset.get("isPublished"):
            steps.append("unpublish")
        if dataset.get("isSubmitted"):
            steps.append("unsubmit")
        steps.append("delete")
        return DatasetOutcome(ds_id, name, "dry-run", "would run: " + ",".join(steps), tuple(steps))

    # 1. Unpublish -- a published dataset is visible in the catalog and the
    #    delete endpoint refuses it.
    if dataset.get("isPublished"):
        try:
            retry_on_server_error(lambda: api.unpublishDataset(ds_id, client=client), sleep=sleep)
            steps.append("unpublish")
        except CloudError as exc:
            steps.append("unpublish-failed")
            notes.append(f"unpublish: {_describe(exc)}")

    # 2. Un-submit.  There is no dedicated endpoint; POST /datasets/{id} with
    #    isSubmitted=false is the only lever the API exposes.  If the server
    #    rejects it we record that and still try the delete -- the failure text
    #    is the evidence Steve needs for a server-side purge.
    if dataset.get("isSubmitted"):
        try:
            retry_on_server_error(
                lambda: api.updateDataset(ds_id, client=client, isSubmitted=False), sleep=sleep
            )
            steps.append("unsubmit")
        except CloudError as exc:
            steps.append("unsubmit-failed")
            notes.append(f"unsubmit: {_describe(exc)}")

    # 3. Hard delete.
    try:
        retry_on_server_error(
            lambda: api.deleteDataset(ds_id, when="now", client=client), sleep=sleep
        )
        steps.append("delete")
        status = "deleted"
    except CloudError as exc:
        steps.append("delete-failed")
        notes.append(f"delete: {_describe(exc)}")
        status = "failed"

    return DatasetOutcome(ds_id, name, status, "; ".join(notes), tuple(steps))


def sweep(
    *,
    api=None,
    client=None,
    org_id: str | None = None,
    prefix: str = DEFAULT_PREFIX,
    min_age_hours: float = 0.0,
    dry_run: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    now: float | None = None,
) -> SweepReport:
    """List, purge, then **re-list** to verify.  Returns a :class:`SweepReport`.

    The verification pass is the whole point.  ``deleteDataset`` returning 200
    is not evidence the dataset is gone -- the audit found 294 datasets that
    had been "successfully deleted" three days running.
    """
    api = default_api() if api is None else api

    datasets = _as_dataset_list(api.listAllDatasets(org_id, client=client))
    stale = select_stale(datasets, prefix=prefix, min_age_hours=min_age_hours, now=now)

    report = SweepReport(
        org_id=org_id or "", prefix=prefix, min_age_hours=min_age_hours, dry_run=dry_run
    )
    for dataset in stale:
        report.outcomes.append(
            purge_dataset(dataset, api=api, client=client, dry_run=dry_run, sleep=sleep)
        )

    if dry_run:
        report.verified = False
        return report

    targeted_ids = {dataset_id_of(d) for d in stale}
    if targeted_ids:
        remaining = _as_dataset_list(api.listAllDatasets(org_id, client=client))
        report.residual = [d for d in remaining if dataset_id_of(d) in targeted_ids]
    return report


def _as_dataset_list(result: Any) -> list[dict[str, Any]]:
    """Normalise ``listAllDatasets`` output (APIResponse, list, or dict)."""
    if result is None:
        return []
    data = getattr(result, "data", None)
    if isinstance(data, list):
        return list(data)
    if isinstance(result, dict):
        return list(result.get("datasets", []))
    if isinstance(result, list):
        return list(result)
    return []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tests.tools.cloud_janitor",
        description=(
            "Delete leftover NDI Cloud test datasets and verify they are " "actually gone."
        ),
    )
    parser.add_argument(
        "--org",
        default=None,
        help="Organization id. Defaults to the one resolved at login.",
    )
    parser.add_argument(
        "--prefix",
        default=DEFAULT_PREFIX,
        help=f"Only datasets whose name starts with this are removed (default: {DEFAULT_PREFIX}).",
    )
    parser.add_argument(
        "--max-age",
        type=float,
        default=0.0,
        metavar="HOURS",
        help=(
            "Only remove datasets at least this many hours old. 0 (default) "
            "removes every match. Datasets with no parseable timestamp are "
            "skipped whenever this is non-zero."
        ),
    )
    parser.add_argument(
        "--environment",
        default=None,
        choices=["prod", "dev"],
        help="Sets CLOUD_API_ENVIRONMENT before authenticating.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be deleted without calling any write endpoint.",
    )
    parser.add_argument(
        "--fail-on-residual",
        action="store_true",
        help="Exit 1 if any targeted dataset is still present after the sweep.",
    )
    return parser


def _make_client(environment: str | None):
    """Authenticate and return a CloudClient (imported lazily)."""
    from ndi.cloud.auth import login
    from ndi.cloud.client import CloudClient
    from ndi.cloud.config import CloudConfig

    if environment:
        os.environ["CLOUD_API_ENVIRONMENT"] = environment
    config = login(config=CloudConfig.from_env())
    if not config.is_authenticated:
        raise RuntimeError("NDI Cloud login failed -- no token received")
    return CloudClient(config)


def main(
    argv: Sequence[str] | None = None,
    *,
    api=None,
    client=None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    args = build_parser().parse_args(argv)

    try:
        if client is None:
            client = _make_client(args.environment)
        report = sweep(
            api=api,
            client=client,
            org_id=args.org,
            prefix=args.prefix,
            min_age_hours=args.max_age,
            dry_run=args.dry_run,
            sleep=sleep,
        )
    except Exception as exc:  # noqa: BLE001 - top-level CLI boundary
        print(f"cloud-janitor: sweep could not run: {_describe(exc)}", file=sys.stdout)
        return 2

    print(report.render())
    return report.exit_code(fail_on_residual=args.fail_on_residual)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
