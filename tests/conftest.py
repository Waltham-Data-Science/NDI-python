"""Pytest configuration and fixtures for NDI tests."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping

import pytest

# ---------------------------------------------------------------------------
# NDI_CLOUD_READONLY -- refuse to run destructive cloud tests
# ---------------------------------------------------------------------------
#
# The prod smoke job runs ``pytest -m "not destructive"``. That protects one
# sentence on one command line; it does not protect the surface. A new job that
# forgets the flag, or a destructive test added to a module the flag never
# covered, writes to the production catalog with no warning -- which is exactly
# how `ci.yml` came to run the full destructive lifecycle against prod on every
# pull request.
#
# So the read-only promise is enforced where the tests actually are: with
# NDI_CLOUD_READONLY set, the session errors out during collection if any
# destructive-marked test survived selection. It is deliberately a hard error
# rather than an auto-deselect -- silently dropping the tests would let a job
# claim it ran a lifecycle suite it never ran.

READONLY_ENV = "NDI_CLOUD_READONLY"
DESTRUCTIVE_MARKER = "destructive"

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def readonly_mode_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Return True when ``NDI_CLOUD_READONLY`` is set to a truthy value."""
    env = os.environ if environ is None else environ
    return str(env.get(READONLY_ENV, "")).strip().lower() in _TRUTHY


def destructive_nodeids(items: Iterable) -> list[str]:
    """Return the node ids of every collected item marked ``destructive``."""
    return [item.nodeid for item in items if item.get_closest_marker(DESTRUCTIVE_MARKER)]


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    """Fail the session if read-only mode collected a destructive test.

    ``trylast`` matters: pytest's own ``-m`` / ``-k`` deselection runs in this
    same hook, so running last means *items* holds what will actually execute.
    A job that correctly passes ``-m "not destructive"`` is therefore unaffected.
    """
    if not readonly_mode_enabled():
        return
    offenders = destructive_nodeids(items)
    if not offenders:
        return
    listed = "\n".join(f"  - {nodeid}" for nodeid in offenders[:20])
    if len(offenders) > 20:
        listed += f"\n  ... and {len(offenders) - 20} more"
    raise pytest.UsageError(
        f"{READONLY_ENV} is set, but {len(offenders)} test(s) marked "
        f"'{DESTRUCTIVE_MARKER}' were selected. Refusing to run: this session "
        f"would mutate the live NDI Cloud catalog.\n"
        f"{listed}\n"
        f'Deselect them with -m "not {DESTRUCTIVE_MARKER}", or unset '
        f"{READONLY_ENV} if writes are genuinely intended."
    )


@pytest.fixture(scope="session", autouse=True)
def _require_schema_document_path():
    """Fail the whole session if the bundled ndi_common document corpus is missing.

    The schema/validation tests used to wrap document creation in
    ``except FileNotFoundError: pytest.skip(...)``, so a DID-schema path or
    filename regression — exactly the cross-repo drift those tests exist to catch
    — turned them into silent no-ops. This asserts the corpus resolves ONCE, up
    front, so a missing/renamed schema directory is a hard failure instead of ten
    green skips.
    """
    from ndi.common import ndi_common_PathConstants

    doc_path = ndi_common_PathConstants.DOCUMENT_PATH
    assert doc_path.is_dir(), (
        f"ndi_common document corpus not found at {doc_path}. The bundled schema "
        f"definitions are missing or the path constant regressed; NDI document "
        f"creation is broken for every user."
    )
