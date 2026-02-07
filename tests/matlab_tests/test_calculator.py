"""
Port of MATLAB ndi.unittest.calc.* tests.

MATLAB source files:
  +calc/+example/testSimple.m               -> TestSimpleCalc
  +calc/+stimulus/testCalcTuningCurve.m     -> TestTuningCurveCalc

Tests for:
- ndi.calc.example.simple.SimpleCalc
- ndi.calc.stimulus.tuningcurve.TuningCurveCalc

These calculators require a session. Tests use the session_with_docs
fixture from conftest.py and also test sessionless instantiation.
"""

from ndi.calc.example.simple import SimpleCalc
from ndi.calc.stimulus.tuningcurve import TuningCurveCalc

# ===========================================================================
# TestSimpleCalc
# Port of: ndi.unittest.calc.example.testSimple
# ===========================================================================


class TestSimpleCalc:
    """Port of ndi.unittest.calc.example.testSimple.

    Verifies SimpleCalc instantiation, interface properties, and
    basic calculation output.
    """

    def test_simple_calc_instantiation_no_session(self):
        """SimpleCalc can be created without a session.

        MATLAB equivalent: testSimple (setup)
        """
        calc = SimpleCalc()
        assert calc is not None
        assert calc._session is None

    def test_simple_calc_instantiation(self, session_with_docs):
        """SimpleCalc can be created with a session.

        MATLAB equivalent: testSimple.testCalcSimple
        """
        session, _ = session_with_docs
        calc = SimpleCalc(session=session)
        assert calc is not None
        assert calc._session is session

    def test_simple_calc_doc_types(self):
        """SimpleCalc has doc_types=['simple_calc'].

        MATLAB equivalent: testSimple (property check)
        """
        calc = SimpleCalc()
        assert hasattr(calc, "doc_types")
        assert isinstance(calc.doc_types, list)
        assert len(calc.doc_types) == 1
        assert calc.doc_types[0] == "simple_calc"

    def test_simple_calc_doc_document_types(self):
        """SimpleCalc has doc_document_types=['apps/calculators/simple_calc'].

        MATLAB equivalent: testSimple (property check)
        """
        calc = SimpleCalc()
        assert hasattr(calc, "doc_document_types")
        assert isinstance(calc.doc_document_types, list)
        assert len(calc.doc_document_types) == 1
        assert calc.doc_document_types[0] == "apps/calculators/simple_calc"

    def test_simple_calc_has_run_method(self):
        """SimpleCalc inherits run() from Calculator.

        MATLAB equivalent: testSimple (interface check)
        """
        calc = SimpleCalc()
        assert hasattr(calc, "run")
        assert callable(calc.run)

    def test_simple_calc_has_calculate_method(self):
        """SimpleCalc implements calculate().

        MATLAB equivalent: testSimple (interface check)
        """
        calc = SimpleCalc()
        assert hasattr(calc, "calculate")
        assert callable(calc.calculate)

    def test_simple_calc_default_search_params(self):
        """default_search_for_input_parameters returns valid structure.

        MATLAB equivalent: testSimple (default parameters)
        """
        calc = SimpleCalc()
        params = calc.default_search_for_input_parameters()
        assert isinstance(params, dict)
        assert "input_parameters" in params
        assert "depends_on" in params
        assert params["input_parameters"]["answer"] == 5

    def test_simple_calc_calculate(self):
        """calculate() returns a list of documents.

        MATLAB equivalent: testSimple.testCalcSimple (calculation)
        """
        calc = SimpleCalc()
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
        """SimpleCalc has a useful repr.

        MATLAB equivalent: testSimple (implicit)
        """
        calc = SimpleCalc()
        r = repr(calc)
        assert "SimpleCalc" in r


# ===========================================================================
# TestTuningCurveCalc
# Port of: ndi.unittest.calc.stimulus.testCalcTuningCurve
# ===========================================================================


class TestTuningCurveCalc:
    """Port of ndi.unittest.calc.stimulus.testCalcTuningCurve.

    Verifies TuningCurveCalc instantiation, interface properties,
    and mock doc generation.
    """

    def test_tuning_curve_instantiation_no_session(self):
        """TuningCurveCalc can be created without a session.

        MATLAB equivalent: testCalcTuningCurve (setup)
        """
        calc = TuningCurveCalc()
        assert calc is not None
        assert calc._session is None

    def test_tuning_curve_instantiation(self, session_with_docs):
        """TuningCurveCalc can be created with a session.

        MATLAB equivalent: testCalcTuningCurve.testCalcTuningCurve
        """
        session, _ = session_with_docs
        calc = TuningCurveCalc(session=session)
        assert calc is not None
        assert calc._session is session

    def test_tuning_curve_doc_types(self):
        """TuningCurveCalc has doc_types=['tuningcurve_calc'].

        MATLAB equivalent: testCalcTuningCurve (property check)
        """
        calc = TuningCurveCalc()
        assert hasattr(calc, "doc_types")
        assert isinstance(calc.doc_types, list)
        assert len(calc.doc_types) == 1
        assert calc.doc_types[0] == "tuningcurve_calc"

    def test_tuning_curve_doc_document_types(self):
        """TuningCurveCalc has doc_document_types for schema path.

        MATLAB equivalent: testCalcTuningCurve (property check)
        """
        calc = TuningCurveCalc()
        assert hasattr(calc, "doc_document_types")
        assert isinstance(calc.doc_document_types, list)
        assert len(calc.doc_document_types) == 1
        assert calc.doc_document_types[0] == "apps/calculators/tuningcurve_calc"

    def test_tuning_curve_has_run_method(self):
        """TuningCurveCalc inherits run() from Calculator.

        MATLAB equivalent: testCalcTuningCurve (interface check)
        """
        calc = TuningCurveCalc()
        assert hasattr(calc, "run")
        assert callable(calc.run)

    def test_tuning_curve_has_calculate_method(self):
        """TuningCurveCalc implements calculate().

        MATLAB equivalent: testCalcTuningCurve (interface check)
        """
        calc = TuningCurveCalc()
        assert hasattr(calc, "calculate")
        assert callable(calc.calculate)

    def test_tuning_curve_default_search_params(self):
        """default_search_for_input_parameters returns valid structure.

        MATLAB equivalent: testCalcTuningCurve (default parameters)
        """
        calc = TuningCurveCalc()
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
        calc = TuningCurveCalc()
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
        calc = TuningCurveCalc()
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
        """TuningCurveCalc has a useful repr.

        MATLAB equivalent: testCalcTuningCurve (implicit)
        """
        calc = TuningCurveCalc()
        r = repr(calc)
        assert "TuningCurveCalc" in r
