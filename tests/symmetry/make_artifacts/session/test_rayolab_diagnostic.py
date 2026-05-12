"""One-off diagnostic for the rayolab 1-vs-2 DAQ symmetry failure.

DELETE ME after the symmetry CI run reports the answers back into the chat.

v3: directly calls session._document_to_object(doc) on each daqsystem
doc to capture the swallowed exception inside daqsystem_load's
`except Exception: pass`. Hypothesis: rayo_stim fails because its
daqreader class (ndi.setup.daq.reader.mfdaq.stimulus.rayolab_intanseries)
or metadatareader class (ndi.daq.metadatareader.RayoLabStims) isn't
registered in class_registry.
"""

from __future__ import annotations

import traceback

import pytest

import ndi.setup
from ndi.query import ndi_query
from ndi.session.dir import ndi_session_dir


class TestRayolabDaqDiagnostic:
    """Probe-only: try to reconstruct each daqsystem doc, capture failures."""

    def test_rayolab_daq_diagnostic(self, tmp_path):
        session_dir = tmp_path / "exp1"
        session_dir.mkdir()

        session = ndi_session_dir("exp1", session_dir)
        session.cache.clear()

        ndi.setup.rayolab(session)

        # Re-open from disk so we exercise the load path the test failure
        # comes from.
        session2 = ndi_session_dir("exp1", session_dir)

        # Pull every daqsystem doc directly from the database (bypassing
        # daqsystem_load's swallow).
        q = ndi_query("").isa("daqsystem") & (ndi_query("base.session_id") == session2.id())
        daq_docs = list(session2.database_search(q))

        msg = ["RAYOLAB DAQ DIAGNOSTIC v3"]
        msg.append(f"  daqsystem docs via direct query: {len(daq_docs)}")
        msg.append("")
        for i, doc in enumerate(daq_docs):
            props = getattr(doc, "document_properties", None) or {}
            base = props.get("base") or {}
            name = base.get("name", "?")
            msg.append(f"  [{i}] daqsystem name={name!r}")
            msg.append(f"      depends_on: {props.get('depends_on')}")
            try:
                obj = session2._document_to_object(doc)
                msg.append(f"      _document_to_object: OK ({type(obj).__name__})")
                # If reconstruction succeeded, inspect what we got
                nav = getattr(obj, "filenavigator", None)
                rdr = getattr(obj, "daqreader", None)
                mr = getattr(obj, "daqmetadatareader", None)
                msg.append(f"      filenavigator: {type(nav).__name__ if nav else None}")
                msg.append(f"      daqreader:     {type(rdr).__name__ if rdr else None}")
                msg.append(f"      mdreader:      {type(mr).__name__ if mr else None}")
            except Exception as exc:  # noqa: BLE001
                tb = traceback.format_exc()
                msg.append(f"      _document_to_object: RAISED {type(exc).__name__}: {exc}")
                # Print the last ~6 frames of the traceback so we see the
                # exact code location that fails.
                tb_lines = tb.splitlines()
                tail = tb_lines[-20:] if len(tb_lines) > 20 else tb_lines
                for line in tail:
                    msg.append(f"      | {line}")
            msg.append("")

        # Also report the registry state for the suspect class names.
        from ndi.class_registry import get_class

        suspects = [
            "ndi.daq.system.mfdaq",
            "ndi.daq.reader.mfdaq.ndr",
            "ndi.setup.daq.reader.mfdaq.stimulus.rayolab_intanseries",
            "ndi.daq.metadatareader.RayoLabStims",
            "ndi.file.navigator.rhd_series",
        ]
        msg.append("  class_registry.get_class() probes:")
        for cls in suspects:
            resolved = get_class(cls)
            msg.append(f"    {cls!r} -> {resolved}")

        pytest.fail("\n".join(msg))
