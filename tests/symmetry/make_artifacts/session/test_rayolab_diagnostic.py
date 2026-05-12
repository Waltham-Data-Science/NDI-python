"""One-off diagnostic for the rayolab 1-vs-2 DAQ symmetry failure.

DELETE ME after the symmetry CI run on commit X reports the numbers
back into the chat.

Runs the rayolab setup, then probes three things:
  (a) how many daqs ``daqsystem_load(name="(.*)")`` finds before reload,
  (b) how many it finds after re-opening the session from disk,
  (c) how many on-disk JSON files mention ``ndi_document_class.class_name``
      = ``daqsystem`` (i.e. how many daqsystem docs persisted).

The test always fails so the message lands in the symmetry workflow's
captured pytest output.
"""

from __future__ import annotations

import json
from pathlib import Path

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


def _looks_like_daqsystem(props: dict) -> bool:
    # The doc has a top-level "daqsystem" struct iff it is a daqsystem doc.
    return "daqsystem" in props and "ndi_daqsystem_class" in (
        props.get("daqsystem") or {}
    )


class TestRayolabDaqDiagnostic:
    """Probe-only: dump counts, then fail with everything we observed."""

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

        # Scan all JSON files in the session tree for daqsystem-shaped docs
        json_files = list(session_dir.rglob("*.json"))
        daq_doc_paths: list[Path] = []
        daq_doc_names: list[str] = []
        for p in json_files:
            try:
                props = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(props, dict) and _looks_like_daqsystem(props):
                daq_doc_paths.append(p)
                base = props.get("base") or {}
                daq_doc_names.append(str(base.get("name", "<noname>")))

        # Also dump every doc class & name to learn what *did* get written
        all_doc_summaries: list[str] = []
        for p in json_files:
            try:
                props = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(props, dict):
                continue
            base = props.get("base") or {}
            doc_cls = (props.get("document_class") or {}).get("class_name", "?")
            all_doc_summaries.append(
                f"  {p.relative_to(session_dir)}  class={doc_cls}  name={base.get('name', '?')}"
            )

        # database_search via base.id match — same path the make_artifacts
        # test uses to dump per-document JSON.
        all_docs = session2.database_search(ndi_query("base.id").match("(.*)"))

        msg = [
            "RAYOLAB DAQ DIAGNOSTIC",
            f"  daqsystem_load in-memory:      {in_memory}",
            f"  daqsystem_load after reload:   {after_reload}",
            f"  daqsystem-shaped JSON on disk: {len(daq_doc_paths)}",
            f"  database_search '(.*)' count:  {len(all_docs)}",
            f"  daqsystem doc names on disk:   {daq_doc_names}",
            "",
            "  all docs on disk:",
            *all_doc_summaries,
        ]
        pytest.fail("\n".join(msg))
