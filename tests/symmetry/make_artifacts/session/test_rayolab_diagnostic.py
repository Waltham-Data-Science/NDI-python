"""One-off diagnostic for the rayolab 1-vs-2 DAQ symmetry failure.

DELETE ME after the symmetry CI run reports the numbers back into the chat.

Runs the rayolab setup, then probes:
  (a) how many daqs ``daqsystem_load(name="(.*)")`` finds before reload,
  (b) how many it finds after re-opening the session from disk,
  (c) a per-document dump of every doc returned by ``database_search``
      (document_class.class_name + base.name + base.id + which top-level
      sections are present).

The test always fails so the message lands in the symmetry workflow's
captured pytest output.
"""

from __future__ import annotations

import pytest

import ndi.setup
from ndi.query import ndi_query
from ndi.session.dir import ndi_session_dir


def _count(result) -> int:
    if result is None:
        return 0
    if isinstance(result, list):
        return len(result)
    return 1


def _doc_summary(doc) -> str:
    props = getattr(doc, "document_properties", None) or {}
    base = props.get("base") or {}
    doc_cls = (props.get("document_class") or {}).get("class_name", "?")
    # Which top-level sections are populated tells us the doc's shape.
    sections = sorted(k for k in props.keys() if k not in ("base", "document_class"))
    return (
        f"id={base.get('id', '?')[:18]}  "
        f"class={doc_cls}  "
        f"name={base.get('name', '?')!r}  "
        f"sections={sections}"
    )


class TestRayolabDaqDiagnostic:
    """Probe-only: dump counts + every doc, then fail."""

    def test_rayolab_daq_diagnostic(self, tmp_path):
        session_dir = tmp_path / "exp1"
        session_dir.mkdir()

        session = ndi_session_dir("exp1", session_dir)
        session.cache.clear()

        ndi.setup.rayolab(session)

        in_memory = _count(session.daqsystem_load(name="(.*)"))

        # Reload from disk
        session2 = ndi_session_dir("exp1", session_dir)
        after_reload = _count(session2.daqsystem_load(name="(.*)"))

        # Pull every document via database_search (same path the
        # make_artifacts test uses to dump per-doc JSON).
        all_docs = list(session2.database_search(ndi_query("base.id").match("(.*)")))

        # Group by class_name so we can see at a glance how many of each
        # shape exist.
        by_class: dict[str, list[str]] = {}
        for d in all_docs:
            props = getattr(d, "document_properties", None) or {}
            doc_cls = (props.get("document_class") or {}).get("class_name", "?")
            base = props.get("base") or {}
            by_class.setdefault(doc_cls, []).append(str(base.get("name", "?")))

        # Try daqsystem_load WITHOUT name filter, in case the regex match
        # is what's narrowing the result.
        no_name_filter = _count(session2.daqsystem_load())

        msg = ["RAYOLAB DAQ DIAGNOSTIC v2"]
        msg.append(f"  daqsystem_load(name='(.*)') in-memory:  {in_memory}")
        msg.append(f"  daqsystem_load(name='(.*)') after-rld:  {after_reload}")
        msg.append(f"  daqsystem_load() (no name filter):       {no_name_filter}")
        msg.append(f"  database_search '(.*)' count:           {len(all_docs)}")
        msg.append("")
        msg.append("  docs grouped by class_name:")
        for cls, names in sorted(by_class.items()):
            msg.append(f"    {cls}  count={len(names)}  names={names}")
        msg.append("")
        msg.append("  per-doc detail (database_search order):")
        for i, d in enumerate(all_docs):
            msg.append(f"    [{i}] {_doc_summary(d)}")

        pytest.fail("\n".join(msg))
