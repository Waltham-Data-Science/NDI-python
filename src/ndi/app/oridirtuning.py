"""
ndi.app.oridirtuning - Orientation/direction tuning analysis.

Turns ``stimulus_response_scalar`` documents into orientation and direction
tuning curves, and then into the selectivity indices most callers want.

MATLAB equivalent: src/ndi/+ndi/+app/oridirtuning.m

TWO HALVES, ONE OF THEM BLOCKED
The tuning-curve half is here and works: it delegates to
:meth:`ndi.app.stimulus.tuning_response.tuning_curve`, so nothing about the
averaging is reimplemented.

The index half -- calculate_oridir_indexes and calculate_all_oridir_indexes
-- is NOT implemented, and deliberately not worked around. Both indices come
from vlt, and the math there is complete and correct: on a synthetic cell
tuned to 90 degrees, oridir_vectorindexes returns dir_pref 92.3 with
significant Hotelling p-values, and oridir_fitindexes returns the
double-gaussian fit with dirpref 90.6. What stops them running is two import
lines in the toolbox, where the alias names a function rather than the module
it is called as:

    oridir_vectorindexes.py:2   hotelling.hotellingt2test(...)
    oridir_fitindexes.py:2      otfit.otfit_carandini(...)

Reported as VH-Lab/vhlab-toolbox-python#24, which names both files. Once that
lands, the two methods below are a thin translation of the MATLAB, because
the arithmetic is already written and tested on the other side. Vendoring a
workaround here would put a copy of another project's bug in this one, and
would have to be removed again.

THE STIMULUS TEST IS NOT A FIELD LOOKUP
is_oridir_stimulus_response has to follow the response document to its
stimulus presentation and ask what varies ACROSS the stimuli, ignoring
blanks. It is true only when the single varying parameter is ``angle``: a
set that also varies spatial frequency is a different experiment and its
tuning curve would average across conditions that are not comparable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import ndi_app
from .appdoc import ndi_app_appdoc

if TYPE_CHECKING:
    from ..document import ndi_document
    from ..session.session_base import ndi_session


def _parameters_of(stimulus: Any) -> dict:
    """One stimulus's parameters, whatever shape the document holds.

    MATLAB reads ``stimuli.parameters`` off a struct array. A document read
    back from the database gives plain dicts, while a hand-built test double
    may give the parameters directly.
    """
    if isinstance(stimulus, dict):
        params = stimulus.get("parameters", stimulus)
        return params if isinstance(params, dict) else {}
    return getattr(stimulus, "parameters", {}) or {}


def _is_blank(parameters: dict) -> bool:
    """MATLAB's rule: a stimulus counts unless it says it is blank.

    A stimulus with no ``isblank`` field at all is INCLUDED, which is why
    this is not ``parameters.get("isblank", True)``.
    """
    return bool(parameters.get("isblank", False))


class ndi_app_oridirtuning(ndi_app, ndi_app_appdoc):
    """
    ndi_app for orientation/direction tuning analysis.

    Computes orientation and direction selectivity measures from
    stimulus tuning curves, including:
    - Circular variance
    - Direction selectivity index
    - Orientation selectivity index
    - Von Mises fit parameters

    Doc types:
        - orientation_direction_tuning: Computed tuning properties
        - tuning_curve: Stimulus tuning curves

    Example:
        >>> odt = ndi_app_oridirtuning(session)
        >>> odt.calculate_all_tuning_curves(element_obj)
        >>> odt.calculate_all_oridir_indexes(element_obj)
    """

    def __init__(self, session: ndi_session | None = None):
        ndi_app.__init__(self, session=session, name="ndi_app_oridirtuning")
        # Bare document names, as in MATLAB's constructor. The previous
        # "apps/oridirtuning/..." prefix named no document that exists --
        # ndi_document(path) raised FileNotFoundError -- so struct2doc, and
        # with it add_appdoc and calculate_all_tuning_curves, could not have
        # produced anything.
        #
        # "stimulus_tuningcurve" rather than MATLAB's "tuning_curve":
        # MATLAB is inconsistent with itself here. Its constructor declares
        # {'orientation_direction_tuning','tuning_curve'} while its
        # struct2doc branches on 'stimulus_tuningcurve' and
        # calculate_all_tuning_curves calls add_appdoc with that same name.
        # The document that exists in ndi_common is stimulus_tuningcurve, so
        # that is the name carried here; struct2doc below still answers to
        # "tuning_curve" so a caller ported from the MATLAB constructor's
        # spelling is not silently wrong.
        ndi_app_appdoc.__init__(
            self,
            doc_types=["orientation_direction_tuning", "stimulus_tuningcurve"],
            doc_document_types=[
                "orientation_direction_tuning",
                "stimulus_tuningcurve",
            ],
        )

    def calculate_all_tuning_curves(
        self,
        ndi_element_obj: Any,
        docexistsaction: str = "Replace",
    ) -> list[ndi_document]:
        """
        Calculate tuning curves for all stimulus responses.

        MATLAB equivalent: ndi.app.oridirtuning/calculate_all_tuning_curves

        Args:
            ndi_element_obj: Neural element
            docexistsaction: What to do if docs exist

        Returns:
            One ``stimulus_tuningcurve`` document per angle-varying response.
            Responses from other stimulus sets are skipped, not errors.
        """
        from ..fun.utils import identifier
        from ..query import ndi_query

        if self._session is None:
            raise RuntimeError("calculate_all_tuning_curves requires a session.")

        element_id = identifier(ndi_element_obj)
        responses = self._session.database_search(
            ndi_query("").isa("stimulus_response_scalar")
            & ndi_query("").depends_on("element_id", element_id)
        )

        tuning_docs: list[ndi_document] = []
        for response_doc in responses:
            if not self.is_oridir_stimulus_response(response_doc):
                continue
            made = self.add_appdoc(
                "stimulus_tuningcurve",
                {
                    "element_id": element_id,
                    "response_doc_id": identifier(response_doc),
                },
                docexistsaction,
                ndi_element_obj,
                response_doc,
            )
            tuning_docs.extend(made)
        return tuning_docs

    def calculate_tuning_curve(
        self,
        ndi_element_obj: Any,
        ndi_response_doc: ndi_document,
        do_add: bool = True,
    ) -> ndi_document | None:
        """
        Calculate a single tuning curve from a response document.

        MATLAB equivalent: ndi.app.oridirtuning/calculate_tuning_curve

        Args:
            ndi_element_obj: Neural element
            ndi_response_doc: Stimulus response document
            do_add: If True, add to database

        Returns:
            The ``stimulus_tuningcurve`` document, or None when the response
            did not come from an angle-varying stimulus set.
        """
        from ..fun.utils import identifier
        from .stimulus.tuning_response import ndi_app_stimulus_tuning__response

        if self._session is None:
            raise RuntimeError("calculate_tuning_curve requires a session.")

        if not self.is_oridir_stimulus_response(ndi_response_doc):
            return None

        responder = ndi_app_stimulus_tuning__response(self._session)
        tuning_doc = responder.tuning_curve(
            ndi_response_doc,
            independent_parameter=["angle"],
            independent_label=["direction"],
            # Only stimuli that carry a spatial frequency, matching MATLAB.
            # hasfield takes no operands, but fieldsearch expects the pair to
            # be present, so both stay empty rather than absent.
            constraint={
                "field": "sFrequency",
                "operation": "hasfield",
                "param1": "",
                "param2": "",
            },
            do_add=False,
        )
        if tuning_doc is None:
            return None

        # identifier(), not .id(): an element's id is a property and a
        # session's is a method, so .id() raises TypeError on real objects
        # while passing against a double that defines it as a method.
        tuning_doc = tuning_doc.set_dependency_value("element_id", identifier(ndi_element_obj))
        tuning_doc = tuning_doc.set_dependency_value(
            "stimulus_response_scalar_id", identifier(ndi_response_doc)
        )

        if do_add:
            self._session.database_add(tuning_doc)
        return tuning_doc

    def calculate_all_oridir_indexes(
        self,
        ndi_element_obj: Any,
        docexistsaction: str = "Replace",
    ) -> list[ndi_document]:
        """
        Calculate orientation/direction indices for all responses.

        MATLAB equivalent: ndi.app.oridirtuning/calculate_all_oridir_indexes

        Args:
            ndi_element_obj: Neural element
            docexistsaction: What to do if docs exist

        Returns:
            List of orientation_direction_tuning documents
        """
        raise NotImplementedError(
            "The orientation/direction indices come from vlt, where the math is complete and correct, but two import lines stop it running (oridir_vectorindexes reaches its helper as module.function where the package has bound the bare function to that name). Reported as VH-Lab/vhlab-toolbox-python#24. Not worked around here: vendoring a copy of another project's bug would have to be removed again."
        )

    def calculate_oridir_indexes(
        self,
        tuning_doc: ndi_document,
        do_add: bool = True,
        do_plot: bool = False,
    ) -> ndi_document | None:
        """
        Calculate orientation/direction indices from a tuning curve.

        MATLAB equivalent: ndi.app.oridirtuning/calculate_oridir_indexes

        Args:
            tuning_doc: Tuning curve document
            do_add: If True, add to database
            do_plot: If True, plot results (not applicable in Python)

        Returns:
            Orientation/direction tuning document, or None
        """
        raise NotImplementedError(
            "The orientation/direction indices come from vlt, where the math is complete and correct, but two import lines stop it running (oridir_fitindexes reaches its helper as module.function where the package has bound the bare function to that name). Reported as VH-Lab/vhlab-toolbox-python#24. Not worked around here: vendoring a copy of another project's bug would have to be removed again."
        )

    def is_oridir_stimulus_response(self, response_doc: ndi_document) -> bool:
        """
        Does this response come from a stimulus set that varies only in angle?

        MATLAB equivalent: ``ndi.app.oridirtuning/is_oridir_stimulus_response``

        The question cannot be answered from the response document alone. It
        follows the document's ``stimulus_presentation_id`` to the
        presentation, collects each stimulus's parameters, drops the blanks,
        and asks what varies across the rest. The answer is True only when
        that is exactly ``["angle"]``.

        "Exactly" is the point, and it is why this is not a substring test on
        a label. A set that varies angle AND spatial frequency is a
        two-dimensional experiment; averaging it into a single direction
        tuning curve would pool responses to different spatial frequencies
        and report the result as one curve.

        Blanks are excluded because a blank is not a condition: MATLAB keeps
        a stimulus when it has no ``isblank`` field at all, or when that
        field is false, and this does the same.

        Args:
            response_doc: a ``stimulus_response_scalar`` document.

        Returns:
            True when angle is the only parameter that varies.

        Raises:
            RuntimeError: when there is no session, or the referenced
                stimulus presentation document cannot be found. MATLAB errors
                here too ("empty stimulus response doc, do not know what to
                do"), and it is the right call: a missing presentation is a
                broken database, not a stimulus set that fails the test.
        """
        from vlt.data.structwhatvaries import structwhatvaries

        from ..query import ndi_query

        if self._session is None:
            raise RuntimeError("is_oridir_stimulus_response requires a session.")

        stim_id = response_doc.dependency_value(
            "stimulus_presentation_id", error_if_not_found=False
        )
        if not stim_id:
            raise RuntimeError(
                "Response document has no stimulus_presentation_id dependency; "
                "cannot tell what the stimulus varied."
            )

        found = self._session.database_search(ndi_query("base.id") == stim_id)
        if not found:
            raise RuntimeError(
                f"Stimulus presentation document {stim_id!r} was not found; "
                "do not know what to do."
            )

        stimuli = found[0].document_properties.get("stimulus_presentation", {}).get("stimuli", [])
        included = [
            _parameters_of(stimulus)
            for stimulus in stimuli
            if not _is_blank(_parameters_of(stimulus))
        ]
        if not included:
            return False

        return list(structwhatvaries(included)) == ["angle"]

    def plot_oridir_response(self, oriprops_doc: ndi_document) -> None:
        """
        Plot orientation/direction response.

        MATLAB equivalent: ndi.app.oridirtuning/plot_oridir_response

        Args:
            oriprops_doc: Orientation/direction tuning document

        Python-specific Notes:
            Not applicable in Python without GUI. Use matplotlib
            directly for plotting.
        """
        raise NotImplementedError(
            "plot_oridir_response draws an orientation_direction_tuning document, "
            "which calculate_oridir_indexes cannot yet produce. Blocked behind the "
            "same VH-Lab/vhlab-toolbox-python#24 as the index methods."
        )

    #: MATLAB's constructor spells the tuning-curve type "tuning_curve" while
    #: the rest of that class uses "stimulus_tuningcurve". Both reach the
    #: same document here.
    _TYPE_ALIASES = {"tuning_curve": "stimulus_tuningcurve"}

    def _resolve_type(self, appdoc_type: str) -> str:
        """The declared type name for APPDOC_TYPE, however it was spelled."""
        resolved = self._TYPE_ALIASES.get(appdoc_type, appdoc_type)
        if resolved not in self.doc_types:
            raise ValueError(
                f"Unknown appdoc type {appdoc_type!r}; " f"this app declares {self.doc_types}."
            )
        return resolved

    def struct2doc(self, appdoc_type: str, appdoc_struct: dict, *args, **kwargs) -> ndi_document:
        """Build this app's document for APPDOC_TYPE.

        MATLAB equivalent: ``ndi.app.oridirtuning/struct2doc``

        Extra positional arguments are what add_appdoc forwards from its
        caller (the element and the response document). They are accepted and
        ignored: the struct already carries their ids, and MATLAB re-derives
        the objects from those ids rather than from the arguments.
        """
        from ..document import ndi_document

        resolved = self._resolve_type(appdoc_type)
        return ndi_document(
            self.doc_document_types[self.doc_types.index(resolved)],
            **{resolved: appdoc_struct},
        )

    def find_appdoc(self, appdoc_type: str, **kwargs) -> list[ndi_document]:
        if self._session is None:
            return []
        from ..query import ndi_query

        return self._session.database_search(ndi_query("").isa(appdoc_type))

    def isvalid_appdoc_struct(self, appdoc_type: str, appdoc_struct: dict) -> tuple[bool, str]:
        """
        Validate an appdoc struct.

        MATLAB equivalent: ndi.app.oridirtuning/isvalid_appdoc_struct

        Returns:
            Tuple of (is_valid, error_message)
        """
        return True, ""

    def doc2struct(self, appdoc_type: str, doc: ndi_document) -> dict:
        """The appdoc struct a document was built from.

        MATLAB equivalent: ``ndi.app.oridirtuning/doc2struct``

        The inverse of :meth:`struct2doc` for this app's two types. Both
        structs are made entirely of dependency values, so this reads them
        back rather than reaching into the document's own fields.

        An unknown ``appdoc_type`` returns an empty dict rather than raising,
        matching MATLAB, whose if/elseif chain simply leaves the output
        unset.
        """
        if appdoc_type.lower() == "orientation_direction_tuning":
            return {
                "tuning_doc_id": doc.dependency_value(
                    "stimulus_tuningcurve_id", error_if_not_found=False
                )
            }
        if appdoc_type.lower() in ("stimulus_tuningcurve", "tuning_curve"):
            return {
                "element_id": doc.dependency_value("element_id", error_if_not_found=False),
                "response_doc_id": doc.dependency_value(
                    "stimulus_response_scalar_id", error_if_not_found=False
                ),
            }
        return {}

    @staticmethod
    def appdoc_description() -> str:
        """A description of this app's document types.

        MATLAB equivalent: ``ndi.app.oridirtuning/appdoc_description``, which
        prints a comment block. Returning the text instead of printing it
        lets a caller show it wherever it belongs -- a docstring, a GUI
        panel, a log -- and makes it testable.
        """
        return (
            "ndi.app.oridirtuning appdoc types\n"
            "\n"
            "  orientation_direction_tuning\n"
            "      Orientation and direction tuning properties computed from a\n"
            "      tuning curve: vector and fit indices, preferred angles and\n"
            "      the double-gaussian fit. Depends on element_id and\n"
            "      stimulus_tuningcurve_id.\n"
            "      Struct: tuning_doc_id\n"
            "\n"
            "  stimulus_tuningcurve\n"
            "      A direction tuning curve averaged from the responses to an\n"
            "      angle-varying stimulus set. Depends on element_id and\n"
            "      stimulus_response_scalar_id.\n"
            "      Struct: element_id, response_doc_id\n"
        )

    def __repr__(self) -> str:
        return f"ndi_app_oridirtuning(session={self._session is not None})"
