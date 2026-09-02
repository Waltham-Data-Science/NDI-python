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


class TestTheBlockedMethodsSayWhy:
    """A NotImplementedError that names its blocker is the difference between
    "nobody wrote this" and "this is waiting on a known, filed fix"."""

    @pytest.mark.parametrize(
        "call",
        [
            lambda a: a.calculate_all_oridir_indexes(object()),
            lambda a: a.calculate_oridir_indexes(FakeDoc({}, {})),
            lambda a: a.plot_oridir_response(FakeDoc({}, {})),
        ],
    )
    def test_each_points_at_the_toolbox_issue(self, call):
        app = ndi_app_oridirtuning(FakeSession([]))
        with pytest.raises(NotImplementedError, match="vhlab-toolbox-python#24"):
            call(app)


if __name__ == "__main__":
    pytest.main([__file__])
