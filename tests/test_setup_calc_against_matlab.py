"""ndi.setup and ndi.calc.example.simple against MATLAB.

MATLAB gives six labs a named setup wrapper; only one had a Python
counterpart, so ``ndi.setup.vhlab(session)`` -- the call every MATLAB
example for that lab uses -- raised AttributeError. ``ndi.setup.labNames``,
the way to ask which labs are installed at all, had no counterpart either.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import ndi.setup
from ndi.calc.example.simple import ndi_calc_example_simple
from ndi.common import ndi_common_PathConstants
from ndi.setup import LAB_WRAPPERS, labNames


class TestLabWrappers:
    """MATLAB has a .m file for each of six labs."""

    @pytest.mark.parametrize("name", LAB_WRAPPERS)
    def test_each_wrapper_exists(self, name):
        assert callable(getattr(ndi.setup, name, None)), name

    @pytest.mark.parametrize("name", LAB_WRAPPERS)
    def test_each_wrapper_is_exported(self, name):
        assert name in ndi.setup.__all__

    @staticmethod
    def _module(name):
        # ndi.setup.<name> resolves to the re-exported FUNCTION, so the
        # module has to be fetched deliberately to patch its `lab`.
        import importlib

        return importlib.import_module(f"ndi.setup.{name}")

    @pytest.mark.parametrize("name", LAB_WRAPPERS)
    def test_each_wrapper_names_its_own_lab(self, name, monkeypatch):
        seen = {}

        def fake_lab(session, lab_name, force_update=False):
            seen["lab_name"] = lab_name
            seen["force_update"] = force_update

        monkeypatch.setattr(self._module(name), "lab", fake_lab)
        getattr(ndi.setup, name)(MagicMock())
        assert seen == {"lab_name": name, "force_update": False}

    @pytest.mark.parametrize("name", LAB_WRAPPERS)
    def test_force_update_is_passed_through(self, name, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            self._module(name),
            "lab",
            lambda session, lab_name, force_update=False: seen.update(force_update=force_update),
        )
        getattr(ndi.setup, name)(MagicMock(), force_update=True)
        assert seen["force_update"] is True

    @pytest.mark.parametrize("name", LAB_WRAPPERS)
    def test_each_wrapper_has_configs_to_load(self, name):
        # A wrapper for a lab with no daq_systems directory would fail the
        # moment it was called.
        assert (ndi_common_PathConstants.COMMON_FOLDER / "daq_systems" / name).is_dir()


class TestLabNames:
    """MATLAB's ndi.setup.labNames, which had no Python counterpart."""

    def test_it_lists_the_installed_labs(self):
        names = labNames()
        assert "vhlab" in names
        assert "marderlab" in names

    def test_the_names_are_sorted(self):
        assert labNames() == sorted(labNames())

    def test_every_wrapper_lab_is_listed(self):
        assert set(LAB_WRAPPERS) <= set(labNames())

    def test_hidden_directories_are_dropped(self, tmp_path, monkeypatch):
        daq = tmp_path / "daq_systems"
        (daq / "goodlab").mkdir(parents=True)
        (daq / ".hidden").mkdir()
        (daq / "notadir.txt").write_text("x")
        monkeypatch.setattr(ndi_common_PathConstants, "COMMON_FOLDER", tmp_path)
        assert labNames() == ["goodlab"]

    def test_no_daq_systems_directory_gives_an_empty_list(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ndi_common_PathConstants, "COMMON_FOLDER", tmp_path)
        assert labNames() == []

    def test_the_snake_case_alias_is_the_same_function(self):
        assert ndi.setup.lab_names is labNames


class TestSimpleCalcValidation:
    """MATLAB validates with mustHaveFields and then reads answer directly."""

    def test_both_required_fields_are_checked(self):
        calc = ndi_calc_example_simple()
        with pytest.raises(ValueError, match="depends_on"):
            calc.calculate({"input_parameters": {"answer": 1}})
        with pytest.raises(ValueError, match="input_parameters"):
            calc.calculate({"depends_on": []})

    def test_a_missing_answer_is_an_error_not_a_zero(self):
        # Every read used to be a .get() with a default, so calculate({})
        # produced a well-formed document asserting that the answer is 0.
        calc = ndi_calc_example_simple()
        with pytest.raises(ValueError, match="'answer'"):
            calc.calculate({"input_parameters": {}, "depends_on": []})

    def test_a_complete_call_still_works(self):
        calc = ndi_calc_example_simple()
        docs = calc.calculate({"input_parameters": {"answer": 42}, "depends_on": []})
        assert docs[0].document_properties["simple_calc"]["answer"] == 42
