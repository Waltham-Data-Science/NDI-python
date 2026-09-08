"""ndi.fun.plot and ndi.fun.stimulus against MATLAB.

Three findings, in order of how quietly they failed:

* ``bar3`` could not run at all -- ``plt.cm.get_cmap`` was removed in
  matplotlib 3.9.
* ``f0_f1_responses`` never looked up the partner tuning curve, so one of
  the pair it exists to return was always absent.
* ``findMixtureName`` required the dictionary entry and the mixture to be
  the same length and compared every field as a string, so a one-component
  entry could never match and 1 never equalled 1.0.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")
pd = pytest.importorskip("pandas")

from ndi.fun.plot import bar3, multichan  # noqa: E402
from ndi.fun.stimulus import f0_f1_responses, findMixtureName  # noqa: E402

# ---------------------------------------------------------------------------
# bar3
# ---------------------------------------------------------------------------


@pytest.fixture
def frame():
    return pd.DataFrame(
        {
            "Region": ["A", "A", "B", "B"] * 3,
            "Quarter": ["Q1", "Q2"] * 6,
            "Product": ["X"] * 4 + ["Y"] * 4 + ["Z"] * 4,
            "Sales": list(range(12)),
        }
    )


class TestBar3Runs:
    def test_it_runs_at_all(self, frame):
        # plt.cm.get_cmap was removed in matplotlib 3.9, so this raised
        # AttributeError on any current install.
        assert bar3(frame, ["Region", "Quarter", "Product"], "Sales") is not None

    def test_the_supported_colormap_api_is_available(self):
        # plt.cm.get_cmap was removed in matplotlib 3.9; plt.get_cmap is the
        # spelling that works on every version this project supports. This
        # asserts the API bar3 now uses, not the absence of the old one --
        # older matplotlib still has both, and a test that fails on an older
        # matplotlib is testing the environment rather than the code.
        import matplotlib.pyplot as plt

        assert callable(plt.get_cmap)

    def test_one_subplot_per_first_variable(self, frame):
        fig = bar3(frame, ["Region", "Quarter", "Product"], "Sales")
        assert len(fig.axes) == frame["Region"].nunique()

    def test_three_grouping_variables_are_required(self, frame):
        with pytest.raises(ValueError, match="exactly 3"):
            bar3(frame, ["Region", "Quarter"], "Sales")


class TestBar3CategoryOrder:
    def test_numeric_categories_sort_numerically(self):
        df = pd.DataFrame(
            {"a": ["A"] * 6, "b": [2, 10, 2, 10, 2, 10], "c": ["X"] * 6, "v": range(6)}
        )
        fig = bar3(df, ["a", "b", "c"], "v")
        labels = [t.get_text() for t in fig.axes[0].get_xticklabels()]
        # Sorting every category by str() put "10" before "2".
        assert labels == ["2", "10"]

    def test_text_categories_still_sort_alphabetically(self, frame):
        fig = bar3(frame, ["Region", "Quarter", "Product"], "Sales")
        labels = [t.get_text() for t in fig.axes[0].get_xticklabels()]
        assert labels == ["Q1", "Q2"]

    def test_mixed_types_do_not_raise(self):
        df = pd.DataFrame({"a": ["A"] * 4, "b": [1, "x", 1, "x"], "c": ["X"] * 4, "v": range(4)})
        assert bar3(df, ["a", "b", "c"], "v") is not None


class TestBar3NaNPropagates:
    def test_a_missing_value_makes_the_bar_nan(self):
        # MATLAB's mean() propagates NaN; np.nanmean quietly reported the
        # mean of the rest.
        df = pd.DataFrame(
            {
                "a": ["A", "A"],
                "b": ["Q", "Q"],
                "c": ["X", "X"],
                "v": [1.0, float("nan")],
            }
        )
        fig = bar3(df, ["a", "b", "c"], "v")
        heights = [p.get_height() for p in fig.axes[0].patches]
        assert len(heights) == 1
        assert math.isnan(heights[0])


class TestMultichan:
    def test_one_line_per_channel(self):
        data = np.zeros((10, 3))
        handles = multichan(data, np.arange(10), 5.0)
        assert len(handles) == 3

    def test_channels_are_offset_by_space(self):
        data = np.zeros((4, 3))
        handles = multichan(data, np.arange(4), 5.0)
        # MATLAB: (i-1)*space with 1-based i, i.e. 0, space, 2*space.
        offsets = [h.get_ydata()[0] for h in handles]
        assert offsets == [0.0, 5.0, 10.0]

    def test_a_one_dimensional_input_is_one_channel(self):
        assert len(multichan(np.zeros(6), np.arange(6), 1.0)) == 1


# ---------------------------------------------------------------------------
# findMixtureName
# ---------------------------------------------------------------------------


def component(name="n", ontology="o", value=1, unit="u", unit_name="un"):
    return {
        "ontologyName": ontology,
        "name": name,
        "value": value,
        "ontologyUnit": unit,
        "unitName": unit_name,
    }


@pytest.fixture
def dictionary_file(tmp_path):
    def write(mapping):
        path = tmp_path / "mixtures.json"
        path.write_text(json.dumps(mapping))
        return str(path)

    return write


class TestFindMixtureName:
    def test_a_single_component_entry_can_match(self, dictionary_file):
        # jsondecode gives MATLAB a scalar struct here, which it wraps.
        # `if not isinstance(entry_components, list): continue` skipped it,
        # so no one-component entry could ever match.
        path = dictionary_file({"m": component()})
        assert findMixtureName(path, [component()]) == ["m"]

    def test_an_entry_that_is_a_subset_of_the_mixture_matches(self, dictionary_file):
        # MATLAB: all(entryMatch) where each entryMatch(j) = any(...).
        # Every entry component must find A match; the mixture may hold more.
        path = dictionary_file({"m": [component("a")]})
        assert findMixtureName(path, [component("a"), component("b")]) == ["m"]

    def test_an_entry_with_an_unmatched_component_does_not_match(self, dictionary_file):
        path = dictionary_file({"m": [component("a"), component("z")]})
        assert findMixtureName(path, [component("a")]) == []

    def test_an_integer_matches_the_same_value_as_a_float(self, dictionary_file):
        # Comparing every field as a string made 1 and 1.0 different.
        path = dictionary_file({"m": [component(value=1)]})
        assert findMixtureName(path, [component(value=1.0)]) == ["m"]

    def test_a_different_value_still_does_not_match(self, dictionary_file):
        path = dictionary_file({"m": [component(value=1)]})
        assert findMixtureName(path, [component(value=2)]) == []

    def test_a_scalar_mixture_is_accepted(self, dictionary_file):
        path = dictionary_file({"m": [component()]})
        assert findMixtureName(path, component()) == ["m"]

    def test_every_compared_field_matters(self, dictionary_file):
        from ndi.fun.stimulus import MIXTURE_COMPARE_FIELDS

        for field in MIXTURE_COMPARE_FIELDS:
            entry = component()
            other = dict(entry, **{field: "different"})
            path = dictionary_file({"m": [entry]})
            assert findMixtureName(path, [other]) == [], field

    def test_a_missing_dictionary_gives_no_matches(self, tmp_path):
        assert findMixtureName(str(tmp_path / "nope.json"), [component()]) == []


# ---------------------------------------------------------------------------
# f0_f1_responses
# ---------------------------------------------------------------------------


class FakeDoc:
    def __init__(self, doc_id, properties):
        self._id = doc_id
        self.document_properties = properties

    @property
    def id(self):
        return self._id

    def doc_isa(self, name):
        return name in self.document_properties

    def dependency_value(self, name, error_if_not_found=True):
        for dep in self.document_properties.get("depends_on", []):
            if dep["name"] == name:
                return dep["value"]
        if error_if_not_found:
            raise KeyError(name)
        return None


def tuning_curve(doc_id, scalar_id, label, means):
    """A tuning curve whose vhlab curve row 2 is `means`."""
    n = len(means)
    return FakeDoc(
        doc_id,
        {
            "base": {"id": doc_id},
            "stimulus_tuningcurve": {
                "independent_variable_label": label,
                "independent_variable_value": list(range(1, n + 1)),
                # Two identical samples per stimulus: one would leave the
                # stddev undefined and fill the log with numpy warnings.
                "individual_responses_real": [[m, m] for m in means],
                "individual_responses_imaginary": [[0.0, 0.0] for _ in means],
                "control_individual_responses_real": [[0.0, 0.0] for _ in means],
                "control_individual_responses_imaginary": [[0.0, 0.0] for _ in means],
            },
            "depends_on": [
                {"name": "element_id", "value": "elem-1"},
                {"name": "stimulus_response_scalar_id", "value": scalar_id},
            ],
        },
    )


def scalar(doc_id, response_type):
    return FakeDoc(
        doc_id,
        {
            "base": {"id": doc_id},
            "stimulus_response_scalar": {"response_type": response_type},
            "stimulus_response": {
                "stimulator_epochid": "ep-stim",
                "element_epochid": "ep-elem",
            },
            "depends_on": [{"name": "element_id", "value": "elem-1"}],
        },
    )


class FakeSession:
    """Answers the five queries f0_f1_responses makes, by inspection."""

    def __init__(self, docs):
        self.docs = docs

    def database_search(self, query):
        return [d for d in self.docs if self._matches(query.search_structure, d)]

    def _matches(self, structure, doc):
        return all(self._one(s, doc) for s in structure)

    def _one(self, s, doc):
        props = doc.document_properties
        op = s["operation"]
        if op == "or":
            return self._matches(s["param1"], doc) or self._matches(s["param2"], doc)
        if op == "isa":
            return s["param1"] in props
        if op == "depends_on":
            return any(
                d["name"] == s["param1"] and d["value"] == s["param2"]
                for d in props.get("depends_on", [])
            )
        if op == "exact_string":
            value = props
            for part in s["field"].split("."):
                value = value.get(part, {}) if isinstance(value, dict) else None
            return value == s["param1"]
        return False


@pytest.fixture
def paired_session():
    mean_scalar = scalar("sc-mean", "mean")
    f1_scalar = scalar("sc-f1", "F1")
    mean_curve = tuning_curve("tc-mean", "sc-mean", "angle", [1.0, 5.0, 2.0])
    f1_curve = tuning_curve("tc-f1", "sc-f1", "angle", [0.5, 0.25, 9.0])
    return FakeSession([mean_scalar, f1_scalar, mean_curve, f1_curve]), mean_curve, f1_curve


class TestF0F1Responses:
    def test_both_values_come_back(self, paired_session):
        session, mean_curve, _ = paired_session
        f0, f1, f0_doc, f1_doc = f0_f1_responses(session, mean_curve, response_index=1)
        # Neither used to be findable: the partner curve was never looked up,
        # so one of the pair was always None.
        assert f0 == pytest.approx(5.0)
        assert f1 == pytest.approx(0.25)
        assert f0_doc.id == "tc-mean"
        assert f1_doc.id == "tc-f1"

    def test_it_works_from_either_end_of_the_pair(self, paired_session):
        session, _, f1_curve = paired_session
        f0, f1, f0_doc, f1_doc = f0_f1_responses(session, f1_curve, response_index=0)
        assert f0 == pytest.approx(1.0)
        assert f1 == pytest.approx(0.5)
        assert f0_doc.id == "tc-mean"
        assert f1_doc.id == "tc-f1"

    def test_without_an_index_the_larger_peak_chooses_it(self, paired_session):
        session, mean_curve, _ = paired_session
        # F1 peaks at 9.0 (index 2), higher than the mean's 5.0, so MATLAB
        # takes the F1 peak's location for both.
        f0, f1, _, _ = f0_f1_responses(session, mean_curve)
        assert f1 == pytest.approx(9.0)
        assert f0 == pytest.approx(2.0)

    def test_no_partner_gives_nan_and_no_documents(self):
        lonely_scalar = scalar("sc-mean", "mean")
        lonely_curve = tuning_curve("tc-mean", "sc-mean", "angle", [1.0])
        session = FakeSession([lonely_scalar, lonely_curve])
        f0, f1, f0_doc, f1_doc = f0_f1_responses(session, lonely_curve)
        assert math.isnan(f0) and math.isnan(f1)
        assert f0_doc is None and f1_doc is None

    def test_a_mismatched_independent_variable_is_not_a_partner(self):
        mean_scalar = scalar("sc-mean", "mean")
        f1_scalar = scalar("sc-f1", "F1")
        mean_curve = tuning_curve("tc-mean", "sc-mean", "angle", [1.0])
        f1_curve = tuning_curve("tc-f1", "sc-f1", "contrast", [1.0])
        session = FakeSession([mean_scalar, f1_scalar, mean_curve, f1_curve])
        with pytest.raises(ValueError, match="No corresponding F1 found"):
            f0_f1_responses(session, mean_curve)

    def test_an_unknown_response_type_is_rejected(self):
        odd_scalar = scalar("sc-odd", "F2")
        odd_curve = tuning_curve("tc-odd", "sc-odd", "angle", [1.0])
        session = FakeSession([odd_scalar, odd_curve])
        with pytest.raises(ValueError, match="expected mean or F1"):
            f0_f1_responses(session, odd_curve)
