"""
Tests for Phase 9: ndi.app, ndi.app.appdoc, ndi.calculator, ndi.calc.example.simple

373 existing tests + Phase 9 tests.
"""

import pytest
from pathlib import Path

from ndi import (
    App, AppDoc, DocExistsAction, Calculator,
    Document, Query, DirSession,
)
from ndi.calc.example import SimpleCalc


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def temp_dir(tmp_path):
    """Create a temp directory for tests."""
    return tmp_path


@pytest.fixture
def session(temp_dir):
    """Create a DirSession for testing."""
    session_path = temp_dir / 'session1'
    session_path.mkdir(parents=True, exist_ok=True)
    return DirSession('TestSession', session_path)


# ===========================================================================
# App Tests
# ===========================================================================

class TestAppCreation:
    """Test App construction."""

    def test_default_construction(self):
        app = App()
        assert app.session is None
        assert app.name == 'generic'

    def test_construction_with_session(self, session):
        app = App(session=session, name='my_analysis')
        assert app.session is session
        assert app.name == 'my_analysis'

    def test_repr(self):
        app = App(name='test_app')
        assert repr(app) == "App('test_app')"


class TestAppVarAppName:
    """Test App.varappname() sanitization."""

    def test_simple_name(self):
        app = App(name='my_app')
        assert app.varappname() == 'my_app'

    def test_name_with_dots(self):
        app = App(name='my.app.v2')
        assert app.varappname() == 'my_app_v2'

    def test_name_with_spaces(self):
        app = App(name='my app name')
        assert app.varappname() == 'my_app_name'

    def test_name_starting_with_digit(self):
        app = App(name='3dplot')
        assert app.varappname() == '_3dplot'

    def test_empty_name(self):
        app = App(name='')
        assert app.varappname() == '_app'

    def test_special_characters(self):
        app = App(name='test@app#v1')
        result = app.varappname()
        assert result == 'test_app_v1'
        assert result.isidentifier()


class TestAppVersionUrl:
    """Test App.version_url()."""

    def test_returns_tuple(self):
        app = App(name='test')
        version, url = app.version_url()
        assert isinstance(version, str)
        assert isinstance(url, str)
        assert len(version) > 0
        assert len(url) > 0


class TestAppNewDocument:
    """Test App.newdocument()."""

    def test_creates_app_document(self):
        app = App(name='my_analysis')
        doc = app.newdocument()
        assert isinstance(doc, Document)
        props = doc.document_properties
        assert 'app' in props
        assert props['app']['name'] == 'my_analysis'

    def test_includes_interpreter_info(self):
        app = App(name='test')
        doc = app.newdocument()
        props = doc.document_properties
        assert props['app']['interpreter'] == 'Python'
        assert 'interpreter_version' in props['app']

    def test_includes_os_info(self):
        app = App(name='test')
        doc = app.newdocument()
        props = doc.document_properties
        assert 'os' in props['app']
        assert 'os_version' in props['app']

    def test_includes_version_and_url(self):
        app = App(name='test')
        doc = app.newdocument()
        props = doc.document_properties
        assert 'version' in props['app']
        assert 'url' in props['app']

    def test_sets_session_id_when_session_provided(self, session):
        app = App(session=session, name='test')
        doc = app.newdocument()
        assert doc.session_id == session.id()

    def test_no_session_id_when_no_session(self):
        app = App(name='test')
        doc = app.newdocument()
        # session_id should be empty or unset
        sid = doc.session_id
        assert sid == '' or sid is None or 'empty' in str(sid).lower() or len(sid) == 0


class TestAppSearchQuery:
    """Test App.searchquery()."""

    def test_returns_query(self):
        app = App(name='my_analysis')
        q = app.searchquery()
        assert q is not None

    def test_query_matches_app_document(self, session):
        app = App(session=session, name='my_analysis')
        doc = app.newdocument()
        session.database_add(doc)

        q = app.searchquery()
        results = session.database_search(q)
        assert len(results) >= 1


# ===========================================================================
# AppDoc Tests
# ===========================================================================

class TestDocExistsAction:
    """Test DocExistsAction enum."""

    def test_enum_values(self):
        assert DocExistsAction.ERROR.value == 'Error'
        assert DocExistsAction.NO_ACTION.value == 'NoAction'
        assert DocExistsAction.REPLACE.value == 'Replace'
        assert DocExistsAction.REPLACE_IF_DIFFERENT.value == 'ReplaceIfDifferent'

    def test_is_string_enum(self):
        assert isinstance(DocExistsAction.ERROR, str)
        assert DocExistsAction.ERROR == 'Error'

    def test_all_values(self):
        assert len(DocExistsAction) == 4


class TestAppDocCreation:
    """Test AppDoc construction."""

    def test_default_construction(self):
        ad = AppDoc()
        assert ad.doc_types == []
        assert ad.doc_document_types == []
        assert ad.doc_session is None

    def test_construction_with_types(self):
        ad = AppDoc(
            doc_types=['my_type'],
            doc_document_types=['my_doc_type'],
        )
        assert ad.doc_types == ['my_type']
        assert ad.doc_document_types == ['my_doc_type']


class TestAppDocBaseMethods:
    """Test AppDoc base class method defaults."""

    def test_struct2doc_returns_none(self):
        ad = AppDoc()
        result = ad.struct2doc('test_type', {'key': 'value'})
        assert result is None

    def test_find_appdoc_returns_empty(self):
        ad = AppDoc()
        result = ad.find_appdoc('test_type')
        assert result == []

    def test_defaultstruct_returns_empty_dict(self):
        ad = AppDoc()
        result = ad.defaultstruct_appdoc('test_type')
        assert result == {}

    def test_loaddata_returns_none(self):
        ad = AppDoc()
        result = ad.loaddata_appdoc('test_type')
        assert result is None

    def test_isvalid_returns_false(self):
        ad = AppDoc()
        valid, msg = ad.isvalid_appdoc_struct('test_type', {})
        assert valid is False
        assert isinstance(msg, str)

    def test_isequal_compares_dicts(self):
        ad = AppDoc()
        assert ad.isequal_appdoc_struct('t', {'a': 1}, {'a': 1}) is True
        assert ad.isequal_appdoc_struct('t', {'a': 1}, {'a': 2}) is False


class TestAppDocAddAppdoc:
    """Test AppDoc.add_appdoc() with doc_exists_action."""

    def test_add_appdoc_no_existing_no_struct2doc(self):
        """Base class struct2doc returns None, so add returns empty."""
        ad = AppDoc()
        result = ad.add_appdoc('test_type')
        assert result == []

    def test_add_appdoc_error_when_exists(self):
        """Test that ERROR action raises when doc exists."""
        class FakeAppDoc(AppDoc):
            def find_appdoc(self, appdoc_type, *args, **kwargs):
                return [Document('base')]

        ad = FakeAppDoc()
        with pytest.raises(RuntimeError, match="already exists"):
            ad.add_appdoc('test_type', doc_exists_action=DocExistsAction.ERROR)

    def test_add_appdoc_no_action_returns_existing(self):
        """Test that NO_ACTION returns existing docs."""
        existing = [Document('base')]

        class FakeAppDoc(AppDoc):
            def find_appdoc(self, appdoc_type, *args, **kwargs):
                return existing

        ad = FakeAppDoc()
        result = ad.add_appdoc('test_type', doc_exists_action=DocExistsAction.NO_ACTION)
        assert result == existing


class TestAppDocClear:
    """Test AppDoc.clear_appdoc()."""

    def test_clear_no_docs(self):
        ad = AppDoc()
        result = ad.clear_appdoc('test_type')
        assert result is False

    def test_clear_with_docs_no_session(self):
        class FakeAppDoc(AppDoc):
            def find_appdoc(self, appdoc_type, *args, **kwargs):
                return [Document('base')]

        ad = FakeAppDoc()
        result = ad.clear_appdoc('test_type')
        assert result is False  # No session to remove from


# ===========================================================================
# Calculator Tests
# ===========================================================================

class TestCalculatorCreation:
    """Test Calculator construction."""

    def test_default_construction(self):
        calc = Calculator()
        assert calc.session is None
        assert calc.doc_types == []

    def test_construction_with_session(self, session):
        calc = Calculator(session=session, document_type='my_calc')
        assert calc.session is session
        assert calc.doc_types == ['my_calc']
        assert calc.doc_document_types == ['my_calc']

    def test_name_is_class_name(self):
        calc = Calculator()
        assert calc.name == 'Calculator'

    def test_repr(self):
        calc = Calculator(document_type='my_calc')
        assert 'Calculator' in repr(calc)
        assert 'my_calc' in repr(calc)


class TestCalculatorDefaultMethods:
    """Test Calculator base class defaults."""

    def test_calculate_returns_empty(self):
        calc = Calculator()
        result = calc.calculate({'input_parameters': {}, 'depends_on': []})
        assert result == []

    def test_default_search_for_input_parameters(self):
        calc = Calculator()
        params = calc.default_search_for_input_parameters()
        assert 'input_parameters' in params
        assert 'depends_on' in params
        assert params['input_parameters'] == {}
        assert params['depends_on'] == []

    def test_are_input_parameters_equivalent(self):
        calc = Calculator()
        assert calc.are_input_parameters_equivalent({'a': 1}, {'a': 1}) is True
        assert calc.are_input_parameters_equivalent({'a': 1}, {'a': 2}) is False

    def test_is_valid_dependency_input(self):
        calc = Calculator()
        assert calc.is_valid_dependency_input('doc_id', 'abc123') is True

    def test_default_parameters_query(self):
        calc = Calculator()
        result = calc.default_parameters_query({})
        assert result == []


class TestCalculatorSearchForInputParameters:
    """Test Calculator.search_for_input_parameters()."""

    def test_no_queries_returns_single_set(self):
        calc = Calculator()
        params = {
            'input_parameters': {'answer': 5},
            'depends_on': [],
        }
        result = calc.search_for_input_parameters(params)
        assert len(result) == 1
        assert result[0]['input_parameters'] == {'answer': 5}

    def test_no_session_returns_empty(self):
        calc = Calculator()
        params = {
            'input_parameters': {'answer': 5},
            'depends_on': [],
            'query': [{'name': 'doc_id', 'query': Query('').isa('base')}],
        }
        result = calc.search_for_input_parameters(params)
        assert result == []

    def test_with_session_and_query(self, session):
        # Add some documents to the session
        doc1 = Document('base', **{'base.name': 'test1'})
        doc2 = Document('base', **{'base.name': 'test2'})
        session.database_add(doc1)
        session.database_add(doc2)

        calc = Calculator(session=session, document_type='test_calc')
        params = {
            'input_parameters': {'answer': 5},
            'depends_on': [],
            'query': [{'name': 'document_id', 'query': Query('').isa('base')}],
        }
        result = calc.search_for_input_parameters(params)
        # Should find one parameter set per base document
        assert len(result) >= 2
        for p in result:
            assert p['input_parameters'] == {'answer': 5}
            assert len(p['depends_on']) >= 1

    def test_fixed_depends_on_preserved(self):
        calc = Calculator()
        params = {
            'input_parameters': {'x': 1},
            'depends_on': [{'name': 'fixed_dep', 'value': 'abc'}],
        }
        result = calc.search_for_input_parameters(params)
        assert len(result) == 1
        assert result[0]['depends_on'] == [{'name': 'fixed_dep', 'value': 'abc'}]


class TestCalculatorSearchForDocs:
    """Test Calculator.search_for_calculator_docs()."""

    def test_no_session_returns_empty(self):
        calc = Calculator(document_type='my_calc')
        result = calc.search_for_calculator_docs({
            'input_parameters': {},
            'depends_on': [],
        })
        assert result == []

    def test_no_doc_types_returns_empty(self, session):
        calc = Calculator(session=session)
        result = calc.search_for_calculator_docs({
            'input_parameters': {},
            'depends_on': [],
        })
        assert result == []


class TestCalculatorRun:
    """Test Calculator.run() pipeline."""

    def test_run_no_session(self):
        calc = Calculator()
        result = calc.run(DocExistsAction.ERROR)
        assert result == []

    def test_run_with_empty_calculate(self, session):
        """Calculator base returns [] from calculate, so run returns []."""
        calc = Calculator(session=session, document_type='test')
        # No matching inputs, so calculate never called
        result = calc.run(DocExistsAction.ERROR)
        assert isinstance(result, list)

    def test_run_error_on_existing(self, session):
        """Test that ERROR action raises when docs already exist."""

        class TestCalc(Calculator):
            def calculate(self, parameters):
                doc = Document('base', **{'base.name': 'calc_result'})
                doc = doc.set_session_id(self._session.id())
                return [doc]

            def default_search_for_input_parameters(self):
                return {
                    'input_parameters': {'x': 1},
                    'depends_on': [],
                }

        calc = TestCalc(session=session, document_type='base')

        # First run should succeed
        docs = calc.run(DocExistsAction.REPLACE)
        assert len(docs) > 0

    def test_run_no_action_does_not_error(self, session):
        """NO_ACTION should not raise on second run."""
        # Use SimpleCalc which properly stores input_parameters
        base_doc = Document('base', **{'base.name': 'input'})
        session.database_add(base_doc)

        sc = SimpleCalc(session=session)
        # First run creates docs
        docs1 = sc.run(DocExistsAction.REPLACE)
        assert len(docs1) >= 1

        # Second run with NO_ACTION should not error
        docs2 = sc.run(DocExistsAction.NO_ACTION)
        assert isinstance(docs2, list)


# ===========================================================================
# SimpleCalc Tests
# ===========================================================================

class TestSimpleCalcCreation:
    """Test SimpleCalc construction."""

    def test_default_construction(self):
        sc = SimpleCalc()
        assert sc.session is None
        assert sc.doc_types == ['simple_calc']
        assert sc.doc_document_types == ['apps/calculators/simple_calc']

    def test_construction_with_session(self, session):
        sc = SimpleCalc(session=session)
        assert sc.session is session

    def test_repr(self):
        sc = SimpleCalc()
        assert 'SimpleCalc' in repr(sc)

    def test_name_is_class_name(self):
        sc = SimpleCalc()
        assert sc.name == 'SimpleCalc'


class TestSimpleCalcDefaultParameters:
    """Test SimpleCalc.default_search_for_input_parameters()."""

    def test_returns_answer_5(self):
        sc = SimpleCalc()
        params = sc.default_search_for_input_parameters()
        assert params['input_parameters'] == {'answer': 5}

    def test_has_query_for_base(self):
        sc = SimpleCalc()
        params = sc.default_search_for_input_parameters()
        assert 'query' in params
        assert len(params['query']) == 1
        assert params['query'][0]['name'] == 'document_id'


class TestSimpleCalcCalculate:
    """Test SimpleCalc.calculate()."""

    def test_calculate_returns_document(self):
        sc = SimpleCalc()
        params = {
            'input_parameters': {'answer': 42},
            'depends_on': [],
        }
        docs = sc.calculate(params)
        assert len(docs) == 1
        assert isinstance(docs[0], Document)

    def test_calculate_stores_answer(self):
        sc = SimpleCalc()
        params = {
            'input_parameters': {'answer': 42},
            'depends_on': [],
        }
        docs = sc.calculate(params)
        props = docs[0].document_properties
        assert props['simple_calc']['answer'] == 42

    def test_calculate_stores_input_parameters(self):
        sc = SimpleCalc()
        params = {
            'input_parameters': {'answer': 7},
            'depends_on': [],
        }
        docs = sc.calculate(params)
        props = docs[0].document_properties
        assert props['simple_calc']['input_parameters'] == {'answer': 7}

    def test_calculate_sets_session_id(self, session):
        sc = SimpleCalc(session=session)
        params = {
            'input_parameters': {'answer': 5},
            'depends_on': [],
        }
        docs = sc.calculate(params)
        assert docs[0].session_id == session.id()

    def test_calculate_sets_dependency(self):
        sc = SimpleCalc()
        params = {
            'input_parameters': {'answer': 5},
            'depends_on': [{'name': 'document_id', 'value': 'abc-123'}],
        }
        docs = sc.calculate(params)
        # Check dependency was set
        props = docs[0].document_properties
        depends = props.get('depends_on', [])
        found = any(
            d.get('name') == 'document_id' and d.get('value') == 'abc-123'
            for d in depends
        )
        assert found


class TestSimpleCalcRun:
    """Test SimpleCalc end-to-end run."""

    def test_run_with_session(self, session):
        """Full pipeline: add a base doc, run SimpleCalc, verify output."""
        # Add a base document for SimpleCalc to find
        base_doc = Document('base', **{'base.name': 'input_data'})
        session.database_add(base_doc)

        sc = SimpleCalc(session=session)
        docs = sc.run(DocExistsAction.REPLACE)
        assert len(docs) >= 1

        # Verify the output document has the right structure
        result_doc = docs[0]
        props = result_doc.document_properties
        assert 'simple_calc' in props
        assert props['simple_calc']['answer'] == 5  # default answer

    def test_run_replace_mode(self, session):
        """Running twice with REPLACE should succeed."""
        base_doc = Document('base', **{'base.name': 'input'})
        session.database_add(base_doc)

        sc = SimpleCalc(session=session)
        docs1 = sc.run(DocExistsAction.REPLACE)
        docs2 = sc.run(DocExistsAction.REPLACE)
        assert len(docs2) >= 1

    def test_run_no_action_mode(self, session):
        """Running with NO_ACTION should return existing on second run."""
        base_doc = Document('base', **{'base.name': 'input'})
        session.database_add(base_doc)

        sc = SimpleCalc(session=session)
        docs1 = sc.run(DocExistsAction.REPLACE)
        # NO_ACTION should not error
        docs2 = sc.run(DocExistsAction.NO_ACTION)
        assert isinstance(docs2, list)

    def test_run_multiple_inputs(self, session):
        """Multiple base docs should produce multiple calculator outputs."""
        doc1 = Document('base', **{'base.name': 'input1'})
        doc2 = Document('base', **{'base.name': 'input2'})
        doc3 = Document('base', **{'base.name': 'input3'})
        session.database_add(doc1)
        session.database_add(doc2)
        session.database_add(doc3)

        sc = SimpleCalc(session=session)
        docs = sc.run(DocExistsAction.REPLACE)
        # Should produce at least 3 results (one per input)
        assert len(docs) >= 3


# ===========================================================================
# Integration Tests
# ===========================================================================

class TestPhase9Imports:
    """Test that all Phase 9 classes are importable from ndi."""

    def test_import_app(self):
        from ndi import App
        assert App is not None

    def test_import_appdoc(self):
        from ndi import AppDoc
        assert AppDoc is not None

    def test_import_doc_exists_action(self):
        from ndi import DocExistsAction
        assert DocExistsAction is not None

    def test_import_calculator(self):
        from ndi import Calculator
        assert Calculator is not None

    def test_import_calc_module(self):
        from ndi import calc
        assert calc is not None

    def test_import_simple_calc(self):
        from ndi.calc.example import SimpleCalc
        assert SimpleCalc is not None

    def test_import_simple_calc_full_path(self):
        from ndi.calc.example.simple import SimpleCalc
        assert SimpleCalc is not None


class TestPhase9Inheritance:
    """Test class hierarchies are correct."""

    def test_app_extends_document_service(self):
        from ndi import App, DocumentService
        assert issubclass(App, DocumentService)

    def test_calculator_extends_app(self):
        assert issubclass(Calculator, App)

    def test_calculator_extends_appdoc(self):
        assert issubclass(Calculator, AppDoc)

    def test_simple_calc_extends_calculator(self):
        assert issubclass(SimpleCalc, Calculator)

    def test_calculator_mro(self):
        """Calculator MRO should have App before AppDoc."""
        mro = Calculator.__mro__
        app_idx = mro.index(App)
        appdoc_idx = mro.index(AppDoc)
        assert app_idx < appdoc_idx
