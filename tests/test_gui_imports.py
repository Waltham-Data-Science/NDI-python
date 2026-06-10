"""
Regression tests for the ndi_gui_ token-corruption cleanup.

A bad find/replace during the class-rename commit injected flattened class
names into module paths, prose, URLs, and MATLAB references.  These tests pin
the functional pieces: the GUI package must import (module files were never
renamed), the ProgressMonitor kwarg must keep the MATLAB property name, and
the repository must stay free of the corruption signatures.
"""

import importlib.util
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"


class TestGuiImports:
    def test_component_package_imports(self):
        """ndi.gui.component must import without PySide6 (eager pieces are Qt-free)."""
        from ndi.gui.component import ndi_gui_component_CommandWindowProgressMonitor

        assert ndi_gui_component_CommandWindowProgressMonitor is not None

    def test_component_internal_imports(self):
        from ndi.gui.component.abstract.ProgressMonitor import (
            ndi_gui_component_abstract_ProgressMonitor,
        )
        from ndi.gui.component.internal.AsynchProgressTracker import (
            ndi_gui_component_internal_AsynchProgressTracker,
        )
        from ndi.gui.component.internal.event import (
            ndi_gui_component_internal_event_MessageUpdatedEventData,
            ndi_gui_component_internal_event_ProgressUpdatedEventData,
        )
        from ndi.gui.component.internal.ProgressTracker import (
            ndi_gui_component_internal_ProgressTracker,
        )

        assert issubclass(
            ndi_gui_component_internal_AsynchProgressTracker,
            ndi_gui_component_internal_ProgressTracker,
        )
        assert ndi_gui_component_abstract_ProgressMonitor is not None
        assert ndi_gui_component_internal_event_MessageUpdatedEventData is not None
        assert ndi_gui_component_internal_event_ProgressUpdatedEventData is not None

    def test_gui_lazy_modules_resolve(self):
        """Every module path in ndi.gui's lazy-import table must exist."""
        for module in (
            "ndi.gui.gui",
            "ndi.gui.gui_v2",
            "ndi.gui.data",
            "ndi.gui.icon",
            "ndi.gui.lab",
            "ndi.gui.docViewer",
        ):
            assert importlib.util.find_spec(module) is not None, module

    def test_crossref_imports(self):
        """ndi.cloud.admin.crossref imports xml.etree names that actually exist."""
        import ndi.cloud.admin.crossref as crossref

        assert crossref.CrossrefConstants.DOI_PREFIX


class TestProgressMonitorKwargs:
    def test_progress_tracker_kwarg_matches_matlab_property(self):
        """MATLAB's ProgressMonitor property is 'ProgressTracker'; the Python
        kwarg and attribute must use the same name."""
        from ndi.gui.component import ndi_gui_component_CommandWindowProgressMonitor
        from ndi.gui.component.internal.ProgressTracker import (
            ndi_gui_component_internal_ProgressTracker,
        )

        tracker = ndi_gui_component_internal_ProgressTracker(TotalSteps=4)
        monitor = ndi_gui_component_CommandWindowProgressMonitor(ProgressTracker=tracker, Title="t")
        assert monitor.ProgressTracker is tracker


class TestNoCorruptionSignatures:
    def test_version_url(self):
        import ndi

        _, url = ndi.version()
        assert url == "https://github.com/Waltham-Data-Science/NDI-python"

    def test_no_spurious_token_outside_gui(self):
        """The flattened 'ndi_gui_' token is only legitimate inside the GUI
        package (and this test)."""
        allowed = {
            SRC / "ndi" / "gui",
            Path(__file__),
        }
        offenders = []
        for path in REPO_ROOT.rglob("*"):
            if not path.is_file():
                continue
            if ".git" in path.parts or path.suffix in {".png", ".sqlite", ".gz"}:
                continue
            if any(a == path or a in path.parents for a in allowed):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, PermissionError):
                continue
            if "ndi_gui_" in text:
                offenders.append(str(path.relative_to(REPO_ROOT)))
        assert not offenders, f"spurious ndi_gui_ token in: {offenders}"

    def test_no_corrupted_external_names(self):
        for path in (SRC / "ndi").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert "requests.ndi_session" not in text, path
            assert "Waltham-ndi_" not in text, path
            assert "VH-ndi_" not in text, path

    def test_bridge_python_paths_exist(self):
        """Every python_path recorded in a bridge YAML must point at a real file."""
        missing = []
        for yaml_path in (SRC / "ndi").rglob("ndi_matlab_python_bridge*.yaml"):
            for m in re.finditer(r'python_path:\s*"([^"]+)"', yaml_path.read_text()):
                rel = m.group(1)
                if rel.startswith("ndi/") and not (SRC / rel).exists():
                    missing.append(f"{yaml_path.name}: {rel}")
        assert not missing, f"bridge python_path entries without files: {missing}"
