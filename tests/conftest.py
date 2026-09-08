"""Pytest configuration and fixtures for NDI tests.

A SKIP IN A BRIDGE TEST IS A FAILURE WHEN STRICT MODE IS ON.

The bridge guard rests on one idea: a check that could not run must not
report the same result as a check that ran and passed (#77). Strict mode is
how CI says "the NDI-matlab tree is there, so anything that cannot run is a
broken job, not a missing developer checkout" -- and every gate that reaches
for the tree honours it today by calling :func:`pytest.fail` instead of
:func:`pytest.skip`.

Nothing enforced that. It was a convention each new gate had to remember,
and the failure mode when one forgot is silent by construction: a skipped
test is green, so the check that was supposed to be watching reports
nothing and the build stays clean. NDR-python hit this three times over --
a bridge job that named only one of its test files, 79 skips per matrix
job, and three ungated skips inside the drift self-tests, which are the
positive controls for the drift rule itself (VH-Lab/NDR-python#25). Both
repos share this suite's shape and #211's strict-mode convention, so both
want the same backstop.

This turns the convention into a rule: under ``NDI_BRIDGE_CHECK_STRICT``,
any skip in a ``test_matlab_bridge_*.py`` module fails. It is deliberately
a blanket rule rather than a list of known gates -- a list is the thing
that goes stale, and the point is to catch the gate nobody remembered to
add.

Skips elsewhere in the suite are untouched: an optional dependency or a
platform-specific test is a legitimate skip, and this says nothing about
those.
"""

from __future__ import annotations

import os

import pytest

#: CI sets this after checking NDI-matlab out. See #77 and section 7 of
#: docs/developer_notes/ndi_matlab_python_bridge.yaml.
STRICT_ENV_VAR = "NDI_BRIDGE_CHECK_STRICT"

#: Modules the rule covers. Every bridge gate lives in one of these.
BRIDGE_MODULE_PREFIX = "test_matlab_bridge_"


def _strict() -> bool:
    return bool(os.environ.get(STRICT_ENV_VAR, "").strip())


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Report a skipped bridge test as a failure under strict mode.

    Rewriting the report rather than the test is what makes this a
    backstop: it catches ``pytest.skip`` called anywhere the test reaches,
    a ``skipif`` marker, and a skip raised inside a helper several frames
    down -- none of which a check reading the test's own source would see.
    """
    outcome = yield
    report = outcome.get_result()

    if not report.skipped or not _strict():
        return
    if not os.path.basename(str(item.fspath)).startswith(BRIDGE_MODULE_PREFIX):
        return

    report.outcome = "failed"
    report.longrepr = (
        f"{item.nodeid} SKIPPED while {STRICT_ENV_VAR} is set.\n\n"
        "Strict mode means the NDI-matlab tree was supposed to be present, so "
        "a bridge test that skips is a check reporting nothing while the build "
        "stays green -- the exact failure the bridge guard exists to prevent "
        "(#77). Either make the gate call pytest.fail under strict mode, the "
        "way require_matlab_root does, or fix whatever made the test "
        "unrunnable.\n\n"
        f"Original skip reason: {report.longrepr}"
    )


# ---------------------------------------------------------------------------
# A local dataset the sync tests can hand to ndi.cloud.sync
#
# The sync operations take an ``ndi.dataset`` rather than a path
# (NDI-python#232), because only a dataset can answer "what are my
# documents" -- the question an upload has to ask. This is the smallest
# thing that answers it: a path for the sync index, and a
# ``database_search`` returning documents the test chose.
#
# It deliberately holds document PROPERTIES rather than ids. A fake that
# only knew ids could not have caught the bug #232 describes, because the
# whole bug was that ids are all the old code had.
# ---------------------------------------------------------------------------

import pytest as _pytest


class FakeDocument:
    """Just enough of ndi.document: it has ``document_properties``."""

    def __init__(self, properties):
        self.document_properties = dict(properties)

    @property
    def id(self):
        return self.document_properties.get("base", {}).get("id", "")


class FakeDataset:
    """A local dataset backed by a directory and a list of documents."""

    def __init__(self, path, documents=()):
        self._path = str(path)
        self.documents = [d if isinstance(d, FakeDocument) else FakeDocument(d) for d in documents]

    # -- what the sync operations use -------------------------------------
    def getpath(self):
        return self._path

    def database_search(self, query=None):
        return list(self.documents)

    def database_add(self, document):
        """Ingest downloaded documents, as ndi.dataset.database_add does.

        A download that never reaches the database is not local, so without
        this the next sync fetches it again -- which is exactly what the
        real datasets do too.
        """
        incoming = document if isinstance(document, list) else [document]
        have = {d.id for d in self.documents}
        for doc in incoming:
            props = getattr(doc, "document_properties", doc)
            wrapped = FakeDocument(props) if not isinstance(doc, FakeDocument) else doc
            if wrapped.id and wrapped.id not in have:
                self.documents.append(wrapped)
                have.add(wrapped.id)
        return self

    # -- convenience for tests --------------------------------------------
    @property
    def ids(self):
        return [d.id for d in self.documents]

    def add(self, doc_id, **extra):
        props = {
            "base": {"id": doc_id, "session_id": "s1"},
            "document_class": {"class_name": "base"},
        }
        props.update(extra)
        self.documents.append(FakeDocument(props))
        return self

    def remove(self, doc_id):
        self.documents = [d for d in self.documents if d.id != doc_id]
        return self


def make_document(doc_id, **extra):
    """A document properties dict with the fields an upload actually sends."""
    props = {
        "base": {"id": doc_id, "session_id": "s1", "name": doc_id},
        "document_class": {"class_name": "base", "property_list_name": "base"},
    }
    props.update(extra)
    return props


@_pytest.fixture
def fake_dataset(tmp_path):
    """A :class:`FakeDataset` rooted at ``tmp_path`` with no documents yet."""
    return FakeDataset(tmp_path)


# ---------------------------------------------------------------------------
# Isolate DID's machine-global file cache for the whole test session.
#
# NDI-python#261: DID's file cache lives at ``~/Documents/DID/fileCache/<uid>``
# -- machine-global and keyed only by uid. A test that uses a constant uid can
# pass once, warm that cache, and from then on resolve from disk before the
# code it exists to check is ever consulted -- the retrieval silently stops
# happening while the test keeps reporting success. It happened in
# NDI-python#215; a per-test uid convention (see tests/test_cloud_series_
# reconstruction.py) works but relies on every future author remembering it.
#
# This fixture makes the hazard structurally impossible: it points
# ``did.common.PathConstants._file_cache_path`` at a session-scoped tmp
# directory and clears the memoized ``FileCache`` handle so the next
# ``did.common.get_cache()`` picks up the new path. It also stops the suite
# writing into a developer's home directory on their local runs.
# ---------------------------------------------------------------------------


@_pytest.fixture(autouse=True, scope="session")
def _isolate_did_file_cache(tmp_path_factory):
    # DID is not installed in every CI job -- the bridge-completeness job
    # only reads YAML metadata and has no DID runtime dep. Silently no-op in
    # that case so the fixture stays out of a job it has no work to do in.
    try:
        from did import common as did_common
    except ImportError:
        yield None
        return

    cache_dir = tmp_path_factory.mktemp("did-file-cache")
    original_path = did_common.PathConstants._file_cache_path
    did_common.PathConstants._file_cache_path = str(cache_dir)
    did_common._cached_cache = None
    try:
        yield cache_dir
    finally:
        did_common.PathConstants._file_cache_path = original_path
        did_common._cached_cache = None
