"""Tests for ndi.fun.calc.

Mirrors MATLAB ndi.fun.calc.stimulus_tuningcurve_log.
"""

from __future__ import annotations

from ndi.fun.calc import stimulus_tuningcurve_log


class _Doc:
    def __init__(self, dep_value, properties=None):
        self._dep = dep_value
        self.document_properties = properties or {}

    def dependency_value(self, name):
        assert name == "stimulus_tuningcurve_id"
        return self._dep


class _Session:
    """Returns whatever it was seeded with, ignoring the query."""

    def __init__(self, result):
        self._result = result
        self.searches = 0

    def database_search(self, query):  # noqa: ARG002
        self.searches += 1
        return self._result


class TestStimulusTuningcurveLog:
    def test_returns_the_log_field(self):
        found = _Doc(None, {"tuningcurve_calc": {"log": "fit converged in 4 steps"}})
        s = _Session([found])
        assert stimulus_tuningcurve_log(s, _Doc("abc123")) == "fit converged in 4 steps"
        assert s.searches == 1

    def test_empty_when_dependency_resolves_to_nothing(self):
        assert stimulus_tuningcurve_log(_Session([]), _Doc("missing")) == ""

    def test_empty_when_document_has_no_log_field(self):
        """MATLAB guards with isfield and leaves log_str = '' -- so do we."""
        found = _Doc(None, {"tuningcurve_calc": {"other": 1}})
        assert stimulus_tuningcurve_log(_Session([found]), _Doc("abc123")) == ""

    def test_empty_when_document_has_no_tuningcurve_calc_at_all(self):
        found = _Doc(None, {"base": {"id": "abc123"}})
        assert stimulus_tuningcurve_log(_Session([found]), _Doc("abc123")) == ""

    def test_first_document_wins(self):
        """MATLAB indexes {1}; a multi-hit search must not change that."""
        a = _Doc(None, {"tuningcurve_calc": {"log": "first"}})
        b = _Doc(None, {"tuningcurve_calc": {"log": "second"}})
        assert stimulus_tuningcurve_log(_Session([a, b]), _Doc("abc123")) == "first"
