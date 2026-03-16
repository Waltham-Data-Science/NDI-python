"""
Port of MATLAB ndi.unittest.calc.* tests.

MATLAB source files:
  +calc/+example/testSimple.m               -> TestSimpleCalc
  +calc/+stimulus/testCalcTuningCurve.m     -> TestTuningCurveCalc

Tests for:
- ndi.calc.example.simple.ndi_calc_example_simple
- ndi.calc.stimulus.tuningcurve.ndi_calc_stimulus_tuningcurve

These calculators require a session. Tests use the session_with_docs
fixture from conftest.py and also test sessionless instantiation.
"""

from ndi.calc.example.simple import ndi_calc_example_simple
from ndi.calc.stimulus.tuningcurve import ndi_calc_stimulus_tuningcurve

# ===========================================================================
# TestSimpleCalc
# Port of: ndi.unittest.calc.example.testSimple
# ===========================================================================


class TestSimpleCalc:
    """Port of ndi.unittest.calc.example.testSimple.

    Verifies ndi_calc_example_simple instantiation, interface properties, and
    basic calculation output.
    """

    def test_simple_calc_instantiation_no_session(self):
        """ndi_calc_example_simple can be created without a session.

        MATLAB equivalent: testSimple (setup)
        """
        calc = ndi_calc_example_simple()
        assert calc is not None
        assert calc._session is None

    def test_simple_calc_instantiation(self, session_with_docs):
        """ndi_calc_example_simple can be created with a session.

        MATLAB equivalent: testSimple.testCalcSimple
        """
        session, _ = session_with_docs
        calc = ndi_calc_example_simple(session=session)
        assert calc is not None
        assert calc._session is session

    def test_simple_calc_doc_types(self):
        """ndi_calc_example_simple has doc_types=['simple_calc'].

        MATLAB equivalent: testSimple (property check)
        """
        calc = ndi_calc_example_simple()
        assert hasattr(calc, "doc_types")
        assert isinstance(calc.doc_types, list)
        assert len(calc.doc_types) == 1
        assert calc.doc_types[0] == "simple_calc"

    def test_simple_calc_doc_document_types(self):
        """ndi_calc_example_simple has doc_document_types=['apps/calculators/simple_calc'].

        MATLAB equivalent: testSimple (property check)
        """
        calc = ndi_calc_example_simple()
        assert hasattr(calc, "doc_document_types")
        assert isinstance(calc.doc_document_types, list)
        assert len(calc.doc_document_types) == 1
        assert calc.doc_document_types[0] == "apps/calculators/simple_calc"

    def test_simple_calc_has_run_method(self):
        """ndi_calc_example_simple inherits run() from ndi_calculator.

        MATLAB equivalent: testSimple (interface check)
        """
        calc = ndi_calc_example_simple()
        assert hasattr(calc, "run")
        assert callable(calc.run)

    def test_simple_calc_has_calculate_method(self):
        """ndi_calc_example_simple implements calculate().

        MATLAB equivalent: testSimple (interface check)
        """
        calc = ndi_calc_example_simple()
        assert hasattr(calc, "calculate")
        assert callable(calc.calculate)

    def test_simple_calc_default_search_params(self):
        """default_search_for_input_parameters returns valid structure.

        MATLAB equivalent: testSimple (default parameters)
        """
        calc = ndi_calc_example_simple()
        params = calc.default_search_for_input_parameters()
        assert isinstance(params, dict)
        assert "input_parameters" in params
        assert "depends_on" in params
        assert params["input_parameters"]["answer"] == 5

    def test_simple_calc_calculate(self):
        """calculate() returns a list of documents.

        MATLAB equivalent: testSimple.testCalcSimple (calculation)
        """
        calc = ndi_calc_example_simple()
        parameters = {
            "input_parameters": {"answer": 42},
            "depends_on": [],
        }
        docs = calc.calculate(parameters)
        assert isinstance(docs, list)
        assert len(docs) == 1

        doc = docs[0]
        # Check that the document has the expected structure
        props = doc.document_properties
        assert "simple_calc" in props
        assert props["simple_calc"]["answer"] == 42

    def test_simple_calc_repr(self):
        """ndi_calc_example_simple has a useful repr.

        MATLAB equivalent: testSimple (implicit)
        """
        calc = ndi_calc_example_simple()
        r = repr(calc)
        assert "ndi_calc_example_simple" in r


# ===========================================================================
# TestTuningCurveCalc
# Port of: ndi.unittest.calc.stimulus.testCalcTuningCurve
# ===========================================================================


class TestTuningCurveCalc:
    """Port of ndi.unittest.calc.stimulus.testCalcTuningCurve.

    Verifies ndi_calc_stimulus_tuningcurve instantiation, interface properties,
    and mock doc generation.
    """

    def test_tuning_curve_instantiation_no_session(self):
        """ndi_calc_stimulus_tuningcurve can be created without a session.

        MATLAB equivalent: testCalcTuningCurve (setup)
        """
        calc = ndi_calc_stimulus_tuningcurve()
        assert calc is not None
        assert calc._session is None

    def test_tuning_curve_instantiation(self, session_with_docs):
        """ndi_calc_stimulus_tuningcurve can be created with a session.

        MATLAB equivalent: testCalcTuningCurve.testCalcTuningCurve
        """
        session, _ = session_with_docs
        calc = ndi_calc_stimulus_tuningcurve(session=session)
        assert calc is not None
        assert calc._session is session

    def test_tuning_curve_doc_types(self):
        """ndi_calc_stimulus_tuningcurve has doc_types=['tuningcurve_calc'].

        MATLAB equivalent: testCalcTuningCurve (property check)
        """
        calc = ndi_calc_stimulus_tuningcurve()
        assert hasattr(calc, "doc_types")
        assert isinstance(calc.doc_types, list)
        assert len(calc.doc_types) == 1
        assert calc.doc_types[0] == "tuningcurve_calc"

    def test_tuning_curve_doc_document_types(self):
        """ndi_calc_stimulus_tuningcurve has doc_document_types for schema path.

        MATLAB equivalent: testCalcTuningCurve (property check)
        """
        calc = ndi_calc_stimulus_tuningcurve()
        assert hasattr(calc, "doc_document_types")
        assert isinstance(calc.doc_document_types, list)
        assert len(calc.doc_document_types) == 1
        assert calc.doc_document_types[0] == "apps/calculators/tuningcurve_calc"

    def test_tuning_curve_has_run_method(self):
        """ndi_calc_stimulus_tuningcurve inherits run() from ndi_calculator.

        MATLAB equivalent: testCalcTuningCurve (interface check)
        """
        calc = ndi_calc_stimulus_tuningcurve()
        assert hasattr(calc, "run")
        assert callable(calc.run)

    def test_tuning_curve_has_calculate_method(self):
        """ndi_calc_stimulus_tuningcurve implements calculate().

        MATLAB equivalent: testCalcTuningCurve (interface check)
        """
        calc = ndi_calc_stimulus_tuningcurve()
        assert hasattr(calc, "calculate")
        assert callable(calc.calculate)

    def test_tuning_curve_default_search_params(self):
        """default_search_for_input_parameters returns valid structure.

        MATLAB equivalent: testCalcTuningCurve (default parameters)
        """
        calc = ndi_calc_stimulus_tuningcurve()
        params = calc.default_search_for_input_parameters()
        assert isinstance(params, dict)
        assert "input_parameters" in params
        assert "depends_on" in params
        ip = params["input_parameters"]
        assert "independent_label" in ip
        assert "independent_parameter" in ip

    def test_tuning_curve_calculate(self):
        """calculate() returns a list of documents.

        MATLAB equivalent: testCalcTuningCurve (calculation)
        """
        calc = ndi_calc_stimulus_tuningcurve()
        parameters = {
            "input_parameters": {
                "independent_label": "angle",
                "independent_parameter": "angle",
            },
            "depends_on": [],
        }
        docs = calc.calculate(parameters)
        assert isinstance(docs, list)
        assert len(docs) == 1

        doc = docs[0]
        props = doc.document_properties
        assert "tuningcurve_calc" in props

    def test_tuning_curve_generate_mock_docs(self):
        """generate_mock_docs() creates synthetic test data.

        MATLAB equivalent: testCalcTuningCurve.testGenerateMockDocs
        """
        calc = ndi_calc_stimulus_tuningcurve()
        docs, doc_output, doc_expected = calc.generate_mock_docs(
            scope="standard",
            number_of_tests=4,
        )

        assert isinstance(docs, list)
        assert len(docs) == 4
        assert isinstance(doc_output, list)
        assert len(doc_output) == 4

        # First test case should be contrast tuning
        assert docs[0] is not None
        assert "X" in docs[0]
        assert "R" in docs[0]
        assert "independent_variables" in docs[0]

    def test_tuning_curve_repr(self):
        """ndi_calc_stimulus_tuningcurve has a useful repr.

        MATLAB equivalent: testCalcTuningCurve (implicit)
        """
        calc = ndi_calc_stimulus_tuningcurve()
        r = repr(calc)
        assert "ndi_calc_stimulus_tuningcurve" in r
