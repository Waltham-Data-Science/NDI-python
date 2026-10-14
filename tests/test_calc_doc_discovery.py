"""Calculator document definitions are found in installed packages.

MATLAB counterpart: ``ndi.fun.find_calc_directories`` and the ``CalcDoc`` /
``CalcDocSchema`` constants of ``ndi.common.PathConstants``. MATLAB scans for
sibling ``NDIcalc*-matlab`` toolbox folders; NDI-python asks every package
registering an ``ndi.calc`` entry point for its toolbox directory, and appends
``ndi_common/database_documents`` (resp. ``schema_documents``) to each.

Every test here builds a FAKE calculator package in ``tmp_path`` -- a module
plus a ``.dist-info`` carrying the entry point -- so none depends on the
network or on ndicalc-vis-matlab being installed. The last class is the
exception: it checks the real package, and skips when it is absent.
"""

from __future__ import annotations

import json
import sys
import textwrap
import uuid
import warnings
from pathlib import Path

import pytest

from ndi.common import ndi_common_PathConstants, updateDIDConstants
from ndi.fun import find_calc_directories


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def _make_fake_calc_package(base: Path, body: str, *, with_docs: bool = True) -> tuple[str, Path]:
    """A calculator package that registers ``ndi.calc`` and nothing else.

    ``body`` is the source of the module's ``toolbox_dir``. Returns the
    entry-point name and the toolbox directory the module would report.
    """
    module = f"fake_ndicalc_{uuid.uuid4().hex[:8]}"
    ep_name = f"NDIcalc-fake-{module[-8:]}"
    toolbox = base / "toolbox"

    (base / f"{module}.py").write_text(
        "from pathlib import Path\n" f"TOOLBOX = Path({str(toolbox)!r})\n\n" + textwrap.dedent(body)
    )
    dist_info = base / f"{module}-0.0.1.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {module.replace('_', '-')}\nVersion: 0.0.1\n"
    )
    (dist_info / "entry_points.txt").write_text(f"[ndi.calc]\n{ep_name} = {module}:toolbox_dir\n")

    if with_docs:
        docs = toolbox / "ndi_common" / "database_documents"
        schemas = toolbox / "ndi_common" / "schema_documents"
        _write_json(
            docs / "fakecalc" / "fake_calc_result.json",
            {
                "document_class": {
                    "definition": "$NDICALCDOCUMENTPATH/fakecalc/fake_calc_result.json",
                    "validation": "$NDICALCSCHEMAPATH/fakecalc/fake_calc_result_schema.json",
                    "class_name": "fake_calc_result",
                    "property_list_name": "fake_calc_result",
                    "class_version": 1,
                    "superclasses": [{"definition": "$NDIDOCUMENTPATH/base.json"}],
                },
                "fake_calc_result": {"value": 0},
            },
        )
        _write_json(
            schemas / "fakecalc" / "fake_calc_result_schema.json",
            {"classname": "fake_calc_result", "superclasses": ["base"], "properties": []},
        )
    return ep_name, toolbox


@pytest.fixture
def calc_path(monkeypatch, tmp_path):
    """Put ``tmp_path`` on sys.path and make discovery re-run before and after."""
    from ndi.validate import _schema_cache

    monkeypatch.syspath_prepend(str(tmp_path))
    del ndi_common_PathConstants.CalcDoc
    del ndi_common_PathConstants.CalcDocSchema
    yield tmp_path
    # monkeypatch undoes sys.path after this teardown runs, so drop the cache
    # now and rediscover once the fake package is gone.
    _schema_cache.pop("fake_calc_result", None)
    monkeypatch.undo()
    for name in [m for m in sys.modules if m.startswith("fake_ndicalc_")]:
        del sys.modules[name]
    del ndi_common_PathConstants.CalcDoc
    del ndi_common_PathConstants.CalcDocSchema
    updateDIDConstants(force=True)


GOOD = """
def toolbox_dir():
    return TOOLBOX
"""


class TestFindCalcDirectories:
    def test_an_entry_point_contributes_its_toolbox_dir(self, calc_path):
        _name, toolbox = _make_fake_calc_package(calc_path, GOOD)
        assert toolbox in find_calc_directories()

    def test_a_raising_entry_point_warns_and_is_skipped(self, calc_path):
        name, toolbox = _make_fake_calc_package(
            calc_path,
            """
            def toolbox_dir():
                raise FileNotFoundError("ndi_common is missing")
            """,
        )
        with pytest.warns(RuntimeWarning, match=name):
            found = find_calc_directories()
        assert toolbox not in found

    def test_an_unimportable_entry_point_warns_and_is_skipped(self, calc_path):
        name, toolbox = _make_fake_calc_package(calc_path, "raise ImportError('broken')\n")
        with pytest.warns(RuntimeWarning, match=name):
            found = find_calc_directories()
        assert toolbox not in found

    def test_a_non_directory_warns_and_is_skipped(self, calc_path):
        name, toolbox = _make_fake_calc_package(calc_path, GOOD, with_docs=False)
        with pytest.warns(RuntimeWarning, match="not a directory"):
            found = find_calc_directories()
        assert toolbox not in found

    def test_a_broken_entry_point_does_not_break_calcdoc(self, calc_path):
        _make_fake_calc_package(calc_path, "raise ImportError('broken')\n")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            assert isinstance(ndi_common_PathConstants.CalcDoc, list)


class TestCalcDocConstants:
    def test_calcdoc_appends_ndi_common_subfolders(self, calc_path):
        _name, toolbox = _make_fake_calc_package(calc_path, GOOD)
        assert toolbox / "ndi_common" / "database_documents" in ndi_common_PathConstants.CalcDoc
        assert toolbox / "ndi_common" / "schema_documents" in ndi_common_PathConstants.CalcDocSchema

    def test_calcdoc_can_be_overridden_and_reset(self, calc_path, tmp_path):
        override = [tmp_path / "elsewhere"]
        ndi_common_PathConstants.CalcDoc = override
        assert ndi_common_PathConstants.CalcDoc == override
        ndi_common_PathConstants.CalcDoc = None
        assert ndi_common_PathConstants.CalcDoc != override

    def test_did_placeholders_hold_the_lists(self, calc_path):
        from did.common import PathConstants

        _name, toolbox = _make_fake_calc_package(calc_path, GOOD)
        updateDIDConstants(force=True)
        value = PathConstants.DEFINITIONS["$NDICALCDOCUMENTPATH"]
        assert isinstance(value, list)
        assert str(toolbox / "ndi_common" / "database_documents") in value

    def test_an_empty_list_is_not_registered(self, calc_path):
        """MATLAB leaves an empty CalcDoc unregistered; so does this."""
        from did.common import PathConstants

        ndi_common_PathConstants.CalcDoc = []
        ndi_common_PathConstants.CalcDocSchema = []
        updateDIDConstants(force=True)
        assert "$NDICALCDOCUMENTPATH" not in PathConstants.DEFINITIONS
        assert "$NDICALCSCHEMAPATH" not in PathConstants.DEFINITIONS


class TestLookupsSearchCalcDoc:
    def test_document_type_resolves_from_the_package(self, calc_path):
        from ndi.document import ndi_document

        _make_fake_calc_package(calc_path, GOOD)
        d = ndi_document("fakecalc/fake_calc_result")
        assert "fake_calc_result" in d.document_properties
        assert "base" in d.document_properties

    def test_bare_name_resolves_from_the_package(self, calc_path):
        from ndi.document import ndi_document

        _make_fake_calc_package(calc_path, GOOD)
        assert ndi_document("fake_calc_result").doc_class() == "fake_calc_result"

    def test_did_resolves_the_calc_placeholder(self, calc_path):
        from did.validate import resolve_definition_path

        _name, toolbox = _make_fake_calc_package(calc_path, GOOD)
        updateDIDConstants(force=True)
        path = resolve_definition_path("$NDICALCSCHEMAPATH/fakecalc/fake_calc_result_schema.json")
        assert Path(path) == (
            toolbox
            / "ndi_common"
            / "schema_documents"
            / "fakecalc"
            / "fake_calc_result_schema.json"
        )

    def test_schema_is_found_by_ndi_validate(self, calc_path):
        from ndi.validate import _load_schema

        _make_fake_calc_package(calc_path, GOOD)
        schema = _load_schema("fake_calc_result")
        assert schema is not None
        assert schema["classname"] == "fake_calc_result"

    def test_alltypes_lists_calc_types(self, calc_path):
        from ndi.fun.doc import allTypes

        _make_fake_calc_package(calc_path, GOOD)
        assert "fake_calc_result" in allTypes()


# ---------------------------------------------------------------------------
# The real package
# ---------------------------------------------------------------------------


def _ndicalc_vis_matlab_installed() -> bool:
    try:
        import ndicalc_vis_matlab  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.mark.skipif(
    not _ndicalc_vis_matlab_installed(),
    reason="ndicalc-vis-matlab is not installed",
)
class TestNDIcalcVisMatlab:
    def test_it_is_discovered(self):
        import ndicalc_vis_matlab

        assert Path(ndicalc_vis_matlab.toolbox_dir()) in find_calc_directories()

    def test_contrast_tuning_resolves(self):
        from ndi.document import ndi_document

        d = ndi_document("vision/contrast_tuning")
        assert "contrast_tuning" in d.document_properties
        assert "base" in d.document_properties

    def test_contrast_tuning_schema_resolves_through_did(self):
        from did.validate import get_document_schema

        schema = get_document_schema("$NDICALCSCHEMAPATH/vision/contrast_tuning_schema.json")
        assert schema["classname"] == "contrast_tuning"
