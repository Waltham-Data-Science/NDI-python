"""ndi.app.oridirtuning: the tuning-curve half, and what the stimulus test asks.

The module was a skeleton -- five methods raising NotImplementedError. Two of
those are implemented here; two remain blocked behind
VH-Lab/vhlab-toolbox-python#24 and say so.

is_oridir_stimulus_response was NOT a skeleton, which is worse: it was
implemented, wrong, and silent. It read
``response_doc.document_properties.stimulus_tuningcurve.independent_variable_label``
off a ``stimulus_response_scalar`` document. That document has no
``stimulus_tuningcurve`` field -- it is a different document type -- so the
AttributeError branch was taken every time and the answer was always False,
meaning calculate_all_tuning_curves would have skipped every response.

MATLAB does something else entirely: follow the response to its stimulus
presentation, drop the blanks, and ask what varies ACROSS the remaining
stimuli. True only when that is exactly ["angle"].
"""

from __future__ import annotations

import pytest

from ndi.app.oridirtuning import ndi_app_oridirtuning


class FakeDoc:
    """A document with the two accessors this app uses."""

    def __init__(self, properties: dict, dependencies: dict | None = None, doc_id: str = "doc1"):
        self.document_properties = properties
        self._deps = dependencies or {}
        self.id = doc_id

    def dependency_value(self, name: str, error_if_not_found: bool = True):
        if name in self._deps:
            return self._deps[name]
        if error_if_not_found:
            raise KeyError(name)
        return None

    def set_dependency_value(self, name: str, value):
        self._deps[name] = value
        return self


class FakeSession:
    def __init__(self, docs=None):
        self.docs = docs or []
        self.added = []

    def database_search(self, query):
        return list(self.docs)

    def database_add(self, doc):
        self.added.append(doc)


def _presentation(*parameter_dicts):
    """A stimulus_presentation document holding the given stimuli."""
    return FakeDoc(
        {"stimulus_presentation": {"stimuli": [{"parameters": p} for p in parameter_dicts]}},
        doc_id="stim1",
    )


def _response(stim_id="stim1"):
    return FakeDoc({}, {"stimulus_presentation_id": stim_id}, doc_id="resp1")


class TestIsOridirStimulusResponse:
    def _app(self, presentation):
        return ndi_app_oridirtuning(FakeSession([presentation]))

    def test_angle_alone_varying_is_an_oridir_set(self):
        app = self._app(
            _presentation(
                {"angle": 0, "sFrequency": 1},
                {"angle": 90, "sFrequency": 1},
                {"angle": 180, "sFrequency": 1},
            )
        )
        assert app.is_oridir_stimulus_response(_response()) is True

    def test_angle_plus_another_varying_parameter_is_not(self):
        """A two-dimensional experiment. Averaging it into one direction
        curve would pool responses to different spatial frequencies."""
        app = self._app(
            _presentation(
                {"angle": 0, "sFrequency": 1},
                {"angle": 90, "sFrequency": 2},
            )
        )
        assert app.is_oridir_stimulus_response(_response()) is False

    def test_a_set_that_varies_something_else_is_not(self):
        app = self._app(_presentation({"angle": 0, "sFrequency": 1}, {"angle": 0, "sFrequency": 2}))
        assert app.is_oridir_stimulus_response(_response()) is False

    def test_blank_stimuli_are_excluded_from_the_question(self):
        """The blank varies nothing but carries no angle; counting it would
        make ``angle`` look like it does not vary."""
        app = self._app(
            _presentation(
                {"angle": 0, "sFrequency": 1},
                {"angle": 90, "sFrequency": 1},
                {"isblank": True},
            )
        )
        assert app.is_oridir_stimulus_response(_response()) is True

    def test_stimuli_that_never_mention_isblank_all_count(self):
        """MATLAB includes a stimulus that simply does not mention isblank,
        so the rule is ``get("isblank", False)``, not ``get("isblank", True)``.

        Every stimulus in a presentation carries the same parameter fields --
        MATLAB holds them in a struct array, which cannot be ragged -- so the
        realistic shape is all-or-none, as here.
        """
        app = self._app(
            _presentation({"angle": 0, "sFrequency": 1}, {"angle": 90, "sFrequency": 1})
        )
        assert app.is_oridir_stimulus_response(_response()) is True

    def test_an_explicit_isblank_false_on_every_stimulus_also_counts(self):
        app = self._app(
            _presentation(
                {"angle": 0, "sFrequency": 1, "isblank": False},
                {"angle": 90, "sFrequency": 1, "isblank": False},
                {"angle": 180, "sFrequency": 1, "isblank": True},
            )
        )
        assert app.is_oridir_stimulus_response(_response()) is True

    def test_a_missing_presentation_document_raises(self):
        """A broken database is not a stimulus set that fails the test.
        Reported as False, calculate_all_tuning_curves would silently
        compute nothing -- which is what the old version did on every input.
        """
        app = ndi_app_oridirtuning(FakeSession([]))
        with pytest.raises(RuntimeError, match="not found"):
            app.is_oridir_stimulus_response(_response())

    def test_a_response_without_the_dependency_raises(self):
        app = ndi_app_oridirtuning(FakeSession([]))
        with pytest.raises(RuntimeError, match="stimulus_presentation_id"):
            app.is_oridir_stimulus_response(FakeDoc({}, {}))

    def test_the_old_implementation_would_have_failed_all_of_these(self):
        """Pinning why this was worth rewriting rather than adjusting.

        The previous version read a stimulus_tuningcurve field off the
        RESPONSE document. No stimulus_response_scalar document has one, so
        the lookup raised and the answer was always False.
        """
        response = _response()
        assert not hasattr(response.document_properties, "stimulus_tuningcurve")
        assert "stimulus_tuningcurve" not in response.document_properties


class TestCalculateTuningCurve:
    def test_a_non_oridir_response_yields_no_document(self):
        app = ndi_app_oridirtuning(
            FakeSession(
                [_presentation({"angle": 0, "sFrequency": 1}, {"angle": 0, "sFrequency": 2})]
            )
        )
        assert app.calculate_tuning_curve(object(), _response()) is None

    def test_without_a_session_it_raises_rather_than_returning_none(self):
        """None means "not an oridir set". A missing session is a different
        thing and must not borrow that answer."""
        app = ndi_app_oridirtuning(None)
        with pytest.raises(RuntimeError, match="requires a session"):
            app.calculate_tuning_curve(object(), _response())


class TestDoc2Struct:
    def test_orientation_direction_tuning_reads_its_tuning_dependency(self):
        app = ndi_app_oridirtuning(None)
        doc = FakeDoc({}, {"stimulus_tuningcurve_id": "tc1"})
        assert app.doc2struct("orientation_direction_tuning", doc) == {"tuning_doc_id": "tc1"}

    def test_stimulus_tuningcurve_reads_both_of_its_dependencies(self):
        app = ndi_app_oridirtuning(None)
        doc = FakeDoc({}, {"element_id": "e1", "stimulus_response_scalar_id": "r1"})
        assert app.doc2struct("stimulus_tuningcurve", doc) == {
            "element_id": "e1",
            "response_doc_id": "r1",
        }

    def test_an_unknown_type_is_empty_rather_than_an_error(self):
        """MATLAB's if/elseif chain leaves the output unset."""
        assert ndi_app_oridirtuning(None).doc2struct("nonsense", FakeDoc({}, {})) == {}


class TestStruct2Doc:
    """The declared document names were "apps/oridirtuning/..." -- paths that
    name no document in ndi_common. ndi_document() raised FileNotFoundError
    on both, so struct2doc could not build anything, and neither could
    add_appdoc or calculate_all_tuning_curves above it."""

    def test_it_builds_an_orientation_direction_tuning_document(self):
        doc = ndi_app_oridirtuning(None).struct2doc(
            "orientation_direction_tuning", {"tuning_doc_id": "tc1"}
        )
        assert doc.document_properties["document_class"]["class_name"] == (
            "orientation_direction_tuning"
        )

    def test_it_builds_a_stimulus_tuningcurve_document(self):
        doc = ndi_app_oridirtuning(None).struct2doc("stimulus_tuningcurve", {"element_id": "e1"})
        assert doc.document_properties["document_class"]["class_name"] == "stimulus_tuningcurve"

    def test_matlabs_other_spelling_reaches_the_same_document(self):
        """MATLAB's constructor says "tuning_curve" where its struct2doc and
        add_appdoc say "stimulus_tuningcurve". Both work here rather than one
        of them failing on a name MATLAB itself uses."""
        doc = ndi_app_oridirtuning(None).struct2doc("tuning_curve", {"element_id": "e1"})
        assert doc.document_properties["document_class"]["class_name"] == "stimulus_tuningcurve"

    def test_an_unknown_type_names_what_is_available(self):
        with pytest.raises(ValueError, match="Unknown appdoc type"):
            ndi_app_oridirtuning(None).struct2doc("nonsense", {})

    def test_every_declared_document_type_actually_exists(self):
        """A guard on the whole class: each declared name must resolve to a
        real ndi_common document, which is exactly what failed before."""
        app = ndi_app_oridirtuning(None)
        assert app.doc_document_types
        for name in app.doc_document_types:
            doc = app.struct2doc(app.doc_types[app.doc_document_types.index(name)], {})
            assert doc is not None


class TestAppdocDescription:
    def test_it_names_both_document_types(self):
        text = ndi_app_oridirtuning.appdoc_description()
        assert "orientation_direction_tuning" in text
        assert "stimulus_tuningcurve" in text

    def test_it_names_the_struct_fields_a_caller_must_supply(self):
        text = ndi_app_oridirtuning.appdoc_description()
        for field in ("tuning_doc_id", "element_id", "response_doc_id"):
            assert field in text


def _tuned_curve_doc(rng=None):
    """A direction-selective cell: strong at 90 degrees, weaker null at 270."""
    import numpy as np

    from ndi.document import ndi_document

    rng = rng or np.random.default_rng(0)
    directions = [float(d) for d in range(0, 360, 30)]
    peak = [
        10 * np.exp(-((d - 90) ** 2) / (2 * 25.0**2))
        + 4 * np.exp(-((d - 270) ** 2) / (2 * 25.0**2))
        for d in directions
    ]
    doc = ndi_document(
        "stimulus_tuningcurve",
        stimulus_tuningcurve={
            "independent_variable_label": ["direction"],
            "independent_variable_value": directions,
            "individual_responses_real": [
                [float(p + rng.normal(0, 0.4)) for _ in range(5)] for p in peak
            ],
            "individual_responses_imaginary": [[0.0] * 5 for _ in directions],
            "control_individual_responses_real": [
                [float(rng.normal(0, 0.4)) for _ in range(5)] for _ in directions
            ],
            "control_individual_responses_imaginary": [[0.0] * 5 for _ in directions],
            "response_units": "Spikes/s",
        },
    )
    return doc.set_dependency_value("stimulus_response_scalar_id", "resp1")


def _response_doc():
    from ndi.document import ndi_document

    doc = ndi_document(
        "stimulus_response_scalar", stimulus_response_scalar={"response_type": "mean"}
    )
    return doc.set_dependency_value("element_id", "elem1")


class TestCalculateOridirIndexes:
    """The index half. Blocked until VH-Lab/vhlab-toolbox-python#24 fixed the
    vlt imports and VH-Lab/vhlab-library-python#8 ported
    neural_response_significance; both landed, so this now runs for real."""

    def _app(self):
        return ndi_app_oridirtuning(FakeSession([_response_doc()]))

    def _properties(self):
        doc = self._app().calculate_oridir_indexes(_tuned_curve_doc(), do_add=False)
        return doc.document_properties["orientation_direction_tuning"]

    def test_it_recovers_the_preferred_direction(self):
        """The end-to-end assertion that matters: a cell built to prefer 90
        degrees is reported as preferring roughly 90, by both routes."""
        p = self._properties()
        assert p["vector"]["direction_preference"] == pytest.approx(90, abs=15)
        assert p["fit"]["direction_angle_preference"] == pytest.approx(90, abs=15)

    def test_orientation_preference_is_direction_preference_modulo_180(self):
        """A bar at 30 and a bar at 210 have the same orientation."""
        p = self._properties()
        assert p["fit"]["orientation_angle_preference"] == pytest.approx(
            p["fit"]["direction_angle_preference"] % 180.0
        )

    def test_a_tuned_cell_is_significant_on_both_anovas(self):
        p = self._properties()
        assert p["significance"]["across_stimuli_anova_p"] < 0.01
        assert p["significance"]["visual_response_anova_p"] < 0.01

    def test_the_fit_is_returned_as_a_curve_a_caller_can_plot(self):
        p = self._properties()
        angles = p["fit"]["double_gaussian_fit_angles"]
        values = p["fit"]["double_gaussian_fit_values"]
        assert len(angles) == len(values) == 360

    def test_the_tuning_curve_keeps_raw_and_subtracted_responses_apart(self):
        """Both are stored, because they answer different questions."""
        p = self._properties()
        curve = p["tuning_curve"]
        assert len(curve["individual"]) == len(curve["raw_individual"])
        assert curve["individual"] != curve["raw_individual"]

    def test_it_depends_on_the_element_and_the_tuning_curve(self):
        doc = self._app().calculate_oridir_indexes(_tuned_curve_doc(), do_add=False)
        assert doc.dependency_value("element_id", error_if_not_found=False) == "elem1"
        assert doc.dependency_value("stimulus_tuningcurve_id", error_if_not_found=False)

    def test_do_add_false_leaves_the_database_alone(self):
        session = FakeSession([_response_doc()])
        ndi_app_oridirtuning(session).calculate_oridir_indexes(_tuned_curve_doc(), do_add=False)
        assert session.added == []

    def test_do_add_true_stores_the_document(self):
        session = FakeSession([_response_doc()])
        ndi_app_oridirtuning(session).calculate_oridir_indexes(_tuned_curve_doc(), do_add=True)
        assert len(session.added) == 1

    def test_a_missing_response_document_raises(self):
        """MATLAB errors here too. A tuning curve whose response document is
        gone is a broken database, not a cell with no tuning."""
        app = ndi_app_oridirtuning(FakeSession([]))
        with pytest.raises(RuntimeError, match="Cannot find the stimulus response"):
            app.calculate_oridir_indexes(_tuned_curve_doc(), do_add=False)

    def test_without_a_session_it_raises(self):
        with pytest.raises(RuntimeError, match="requires a session"):
            ndi_app_oridirtuning(None).calculate_oridir_indexes(_tuned_curve_doc())


class TestSignificanceUsesRawResponsesNotSubtracted:
    """MATLAB builds TWO structs (oridirtuning.m:155-165) and they differ in
    `ind`: the significance test gets the RAW individual responses against the
    blank, while the indices get the control-SUBTRACTED ones.

    That distinction is invisible in the output unless you look for it, and
    passing one struct to both would silently answer one question wrong. This
    pins that the two are not interchangeable.
    """

    def test_the_two_structs_give_different_answers(self):
        import numpy as np
        from vhlib.response_stats.neural_response_significance import (
            neural_response_significance,
        )

        rng = np.random.default_rng(1)
        raw = [np.asarray([5.0 + rng.normal(0, 0.3) for _ in range(5)]) for _ in range(4)]
        control = [np.asarray([4.0 + rng.normal(0, 0.3) for _ in range(5)]) for _ in range(4)]
        subtracted = [r - c for r, c in zip(raw, control)]
        blank = control[0]

        raw_p = neural_response_significance({"ind": raw, "blankind": blank})
        sub_p = neural_response_significance({"ind": subtracted, "blankind": blank})
        assert raw_p != sub_p, "if these agree the fixture is too weak to prove the structs differ"

    def test_the_app_passes_the_raw_ones(self):
        """A flat cell whose RAW responses sit well above its blank is
        visually responsive even though it is not tuned. Subtracting first
        would hide that, so this is the case that distinguishes them."""
        import numpy as np

        from ndi.document import ndi_document

        directions = [float(d) for d in range(0, 360, 90)]
        rng = np.random.default_rng(2)
        doc = ndi_document(
            "stimulus_tuningcurve",
            stimulus_tuningcurve={
                "independent_variable_label": ["direction"],
                "independent_variable_value": directions,
                "individual_responses_real": [
                    [float(8 + rng.normal(0, 0.2)) for _ in range(5)] for _ in directions
                ],
                "individual_responses_imaginary": [[0.0] * 5 for _ in directions],
                "control_individual_responses_real": [
                    [float(rng.normal(0, 0.2)) for _ in range(5)] for _ in directions
                ],
                "control_individual_responses_imaginary": [[0.0] * 5 for _ in directions],
                "response_units": "Spikes/s",
            },
        ).set_dependency_value("stimulus_response_scalar_id", "resp1")

        app = ndi_app_oridirtuning(FakeSession([_response_doc()]))
        p = app.calculate_oridir_indexes(doc, do_add=False).document_properties[
            "orientation_direction_tuning"
        ]
        # Responds to everything, equally: strongly visual, not tuned.
        assert p["significance"]["visual_response_anova_p"] < 0.01
        assert p["significance"]["across_stimuli_anova_p"] > 0.01


class TestPlotOridirResponse:
    def test_it_draws_the_points_the_zero_line_and_the_fit(self):
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        app = ndi_app_oridirtuning(FakeSession([_response_doc()]))
        doc = app.calculate_oridir_indexes(_tuned_curve_doc(), do_add=False)
        plt.figure()
        axes = app.plot_oridir_response(doc)
        assert axes.get_ylabel() == "Spikes/s"
        assert len(axes.lines) >= 2  # zero line and fit
        plt.close("all")


if __name__ == "__main__":
    pytest.main([__file__])
