"""Tests for ndi.fun — utility functions package."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


# ===========================================================================
# ndi.fun.utils tests
# ===========================================================================


class TestChannelName2PrefixNumber:
    """Tests for channelname2prefixnumber."""

    def test_basic(self):
        from ndi.fun.utils import channelname2prefixnumber
        prefix, number = channelname2prefixnumber('ai5')
        assert prefix == 'ai'
        assert number == 5

    def test_multi_digit(self):
        from ndi.fun.utils import channelname2prefixnumber
        prefix, number = channelname2prefixnumber('dev123')
        assert prefix == 'dev'
        assert number == 123

    def test_single_char_prefix(self):
        from ndi.fun.utils import channelname2prefixnumber
        prefix, number = channelname2prefixnumber('a1')
        assert prefix == 'a'
        assert number == 1

    def test_no_digits_raises(self):
        from ndi.fun.utils import channelname2prefixnumber
        with pytest.raises(ValueError, match='No digits'):
            channelname2prefixnumber('abc')

    def test_starts_with_digit_raises(self):
        from ndi.fun.utils import channelname2prefixnumber
        with pytest.raises(ValueError, match='starts with a digit'):
            channelname2prefixnumber('1abc')


class TestName2VariableName:
    """Tests for name2variable_name."""

    def test_basic(self):
        from ndi.fun.utils import name2variable_name
        assert name2variable_name('hello world') == 'helloWorld'

    def test_special_chars(self):
        from ndi.fun.utils import name2variable_name
        assert name2variable_name('my-variable.name') == 'myVariableName'

    def test_starts_with_digit(self):
        from ndi.fun.utils import name2variable_name
        result = name2variable_name('123test')
        assert result.startswith('x')
        assert not result[0].isdigit()

    def test_underscore_preserved(self):
        from ndi.fun.utils import name2variable_name
        result = name2variable_name('my_var')
        assert '_' in result or 'my' in result.lower()

    def test_empty(self):
        from ndi.fun.utils import name2variable_name
        assert name2variable_name('') == ''


class TestPseudorandomint:
    """Tests for pseudorandomint."""

    def test_returns_positive_int(self):
        from ndi.fun.utils import pseudorandomint
        val = pseudorandomint()
        assert isinstance(val, int)
        assert val > 0

    def test_different_values(self):
        from ndi.fun.utils import pseudorandomint
        vals = {pseudorandomint() for _ in range(10)}
        # Random component should give variety
        assert len(vals) > 1


class TestTimestamp:
    """Tests for timestamp."""

    def test_format(self):
        from ndi.fun.utils import timestamp
        ts = timestamp()
        # Should be ISO-like: YYYY-MM-DDTHH:MM:SS.mmm
        assert 'T' in ts
        assert len(ts) == 23  # 2026-02-06T12:34:56.789

    def test_recent(self):
        from ndi.fun.utils import timestamp
        ts = timestamp()
        assert ts.startswith('202')


# ===========================================================================
# ndi.fun.file tests
# ===========================================================================


class TestFileMd5:
    """Tests for file.md5."""

    def test_known_content(self, tmp_path):
        from ndi.fun.file import md5
        f = tmp_path / 'test.bin'
        f.write_bytes(b'hello world')
        result = md5(str(f))
        assert len(result) == 32
        # Known MD5 of 'hello world'
        assert result == '5eb63bbbe01eeed093cb22bb8f5acdc3'

    def test_file_not_found(self):
        from ndi.fun.file import md5
        with pytest.raises(FileNotFoundError):
            md5('/nonexistent/file.bin')


class TestFileDates:
    """Tests for date_created and date_updated."""

    def test_date_updated(self, tmp_path):
        from ndi.fun.file import date_updated
        f = tmp_path / 'test.txt'
        f.write_text('hello')
        dt = date_updated(str(f))
        assert dt is not None
        assert dt.tzinfo is not None

    def test_date_created(self, tmp_path):
        from ndi.fun.file import date_created
        f = tmp_path / 'test.txt'
        f.write_text('hello')
        dt = date_created(str(f))
        assert dt is not None

    def test_nonexistent_returns_none(self):
        from ndi.fun.file import date_updated, date_created
        assert date_updated('/nonexistent') is None
        assert date_created('/nonexistent') is None


# ===========================================================================
# ndi.fun.data tests
# ===========================================================================


class TestReadWriteNgrid:
    """Tests for readngrid and writengrid."""

    def test_roundtrip_double(self, tmp_path):
        from ndi.fun.data import readngrid, writengrid
        data = np.array([[1.0, 2.0], [3.0, 4.0]], dtype='<f8')
        f = tmp_path / 'grid.bin'
        writengrid(data, f, 'double')
        result = readngrid(f, (2, 2), 'double')
        np.testing.assert_array_equal(result, data)

    def test_roundtrip_int16(self, tmp_path):
        from ndi.fun.data import readngrid, writengrid
        data = np.array([100, 200, -300], dtype='<i2')
        f = tmp_path / 'grid.bin'
        writengrid(data, f, 'int16')
        result = readngrid(f, (3,), 'int16')
        np.testing.assert_array_equal(result, data)

    def test_unknown_type(self, tmp_path):
        from ndi.fun.data import readngrid, writengrid
        with pytest.raises(ValueError, match='Unknown'):
            writengrid(np.array([1]), tmp_path / 'x.bin', 'complex128')

    def test_size_mismatch(self, tmp_path):
        from ndi.fun.data import readngrid, writengrid
        data = np.array([1.0, 2.0], dtype='<f8')
        f = tmp_path / 'grid.bin'
        writengrid(data, f, 'double')
        with pytest.raises(ValueError, match='mismatch'):
            readngrid(f, (5,), 'double')

    def test_file_not_found(self):
        from ndi.fun.data import readngrid
        with pytest.raises(FileNotFoundError):
            readngrid('/nonexistent', (1,), 'double')


class TestMat2Ngrid:
    """Tests for mat2ngrid."""

    def test_basic(self):
        from ndi.fun.data import mat2ngrid
        data = np.zeros((3, 4), dtype='float64')
        result = mat2ngrid(data)
        assert result['data_dim'] == [3, 4]
        assert result['data_size'] == 8
        assert result['data_type'] == 'double'
        assert len(result['coordinates']) == 2
        np.testing.assert_array_equal(result['coordinates'][0], np.arange(3))
        np.testing.assert_array_equal(result['coordinates'][1], np.arange(4))

    def test_custom_coordinates(self):
        from ndi.fun.data import mat2ngrid
        data = np.zeros((2, 3))
        coords = [np.array([10, 20]), np.array([100, 200, 300])]
        result = mat2ngrid(data, coordinates=coords)
        np.testing.assert_array_equal(result['coordinates'][0], [10, 20])


# ===========================================================================
# ndi.fun.doc tests
# ===========================================================================


class TestDocDiff:
    """Tests for doc.diff."""

    def _make_doc(self, props):
        doc = MagicMock()
        doc.document_properties = props
        return doc

    def test_equal_docs(self):
        from ndi.fun.doc import diff
        d1 = self._make_doc({'base': {'id': '1'}, 'name': 'test'})
        d2 = self._make_doc({'base': {'id': '1'}, 'name': 'test'})
        result = diff(d1, d2)
        assert result['equal'] is True
        assert result['details'] == []

    def test_different_values(self):
        from ndi.fun.doc import diff
        d1 = self._make_doc({'base': {'id': '1'}, 'name': 'a'})
        d2 = self._make_doc({'base': {'id': '1'}, 'name': 'b'})
        result = diff(d1, d2)
        assert result['equal'] is False
        assert len(result['details']) > 0

    def test_exclude_fields(self):
        from ndi.fun.doc import diff
        d1 = self._make_doc({'base': {'session_id': 'x'}, 'name': 'test'})
        d2 = self._make_doc({'base': {'session_id': 'y'}, 'name': 'test'})
        result = diff(d1, d2, exclude_fields=['base.session_id'])
        assert result['equal'] is True

    def test_order_independent_depends_on(self):
        from ndi.fun.doc import diff
        d1 = self._make_doc({
            'depends_on': [{'name': 'a', 'value': '1'}, {'name': 'b', 'value': '2'}]
        })
        d2 = self._make_doc({
            'depends_on': [{'name': 'b', 'value': '2'}, {'name': 'a', 'value': '1'}]
        })
        result = diff(d1, d2)
        assert result['equal'] is True

    def test_missing_key(self):
        from ndi.fun.doc import diff
        d1 = self._make_doc({'a': 1, 'b': 2})
        d2 = self._make_doc({'a': 1})
        result = diff(d1, d2)
        assert result['equal'] is False
        assert any('missing' in d for d in result['details'])


class TestDocAllTypes:
    """Tests for doc.all_types."""

    def test_returns_list(self):
        from ndi.fun.doc import all_types
        types = all_types()
        assert isinstance(types, list)
        # Should find at least base types from schema_documents
        assert len(types) > 0

    def test_sorted(self):
        from ndi.fun.doc import all_types
        types = all_types()
        assert types == sorted(types)


class TestDocGetDocTypes:
    """Tests for doc.get_doc_types."""

    def test_with_mock_session(self):
        from ndi.fun.doc import get_doc_types
        doc1 = MagicMock()
        doc1.document_properties = {
            'document_class': {
                'class_list': [
                    {'class_name': 'base'},
                    {'class_name': 'element'},
                ]
            }
        }
        doc2 = MagicMock()
        doc2.document_properties = {
            'document_class': {
                'class_list': [{'class_name': 'base'}, {'class_name': 'subject'}]
            }
        }
        session = MagicMock()
        session.database_search.return_value = [doc1, doc2]

        types, counts = get_doc_types(session)
        assert 'element' in types
        assert 'subject' in types
        assert counts['element'] == 1
        assert counts['subject'] == 1


class TestDocFindFuid:
    """Tests for doc.find_fuid."""

    def test_found(self):
        from ndi.fun.doc import find_fuid
        doc = MagicMock()
        doc.document_properties = {
            'files': {
                'file_info': [{
                    'name': 'data.bin',
                    'locations': [{'uid': 'abc123'}],
                }]
            }
        }
        session = MagicMock()
        session.database_search.return_value = [doc]

        result_doc, filename = find_fuid(session, 'abc123')
        assert result_doc is doc
        assert filename == 'data.bin'

    def test_not_found(self):
        from ndi.fun.doc import find_fuid
        session = MagicMock()
        session.database_search.return_value = []
        result_doc, filename = find_fuid(session, 'nonexistent')
        assert result_doc is None
        assert filename == ''


# ===========================================================================
# ndi.fun.epoch tests
# ===========================================================================


class TestEpochId2Element:
    """Tests for epoch.epochid2element."""

    def test_basic(self):
        from ndi.fun.epoch import epochid2element
        doc = MagicMock()
        doc.document_properties = {
            'document_class': {'class_list': [{'class_name': 'element'}]},
            'element': {
                'name': 'probe1',
                'epoch_table': [
                    {'epoch_id': 'epoch_001'},
                    {'epoch_id': 'epoch_002'},
                ],
            },
        }
        session = MagicMock()
        session.database_search.return_value = [doc]

        result = epochid2element(session, ['epoch_001'])
        assert len(result['epoch_001']) == 1

    def test_case_insensitive(self):
        from ndi.fun.epoch import epochid2element
        doc = MagicMock()
        doc.document_properties = {
            'document_class': {'class_list': [{'class_name': 'element'}]},
            'element': {
                'epoch_table': [{'epoch_id': 'Epoch_001'}],
            },
        }
        session = MagicMock()
        session.database_search.return_value = [doc]

        result = epochid2element(session, ['epoch_001'])
        assert len(result['epoch_001']) == 1

    def test_not_found(self):
        from ndi.fun.epoch import epochid2element
        session = MagicMock()
        session.database_search.return_value = []
        result = epochid2element(session, ['nonexistent'])
        assert result['nonexistent'] == []


class TestFilename2EpochId:
    """Tests for epoch.filename2epochid."""

    def test_basic(self):
        from ndi.fun.epoch import filename2epochid
        doc = MagicMock()
        doc.document_properties = {
            'daqsystem': {
                'epoch_table': [{
                    'epoch_id': 'ep1',
                    'underlying_files': ['/data/recording_001.dat'],
                }],
            },
        }
        session = MagicMock()
        session.database_search.return_value = [doc]

        result = filename2epochid(session, ['recording_001.dat'])
        assert 'ep1' in result['recording_001.dat']


# ===========================================================================
# ndi.fun.stimulus tests
# ===========================================================================


class TestTuningCurveToResponseType:
    """Tests for stimulus.tuning_curve_to_response_type."""

    def test_direct_scalar(self):
        from ndi.fun.stimulus import tuning_curve_to_response_type
        tc_doc = MagicMock()
        tc_doc.document_properties = {
            'depends_on': [
                {'name': 'stimulus_response_scalar_id', 'value': 'srs_001'},
            ],
        }
        scalar_doc = MagicMock()
        scalar_doc.document_properties = {
            'stimulus_response_scalar': {'response_type': 'mean'},
        }
        session = MagicMock()
        session.database_search.return_value = [scalar_doc]

        rt, doc = tuning_curve_to_response_type(session, tc_doc)
        assert rt == 'mean'
        assert doc is scalar_doc

    def test_no_match(self):
        from ndi.fun.stimulus import tuning_curve_to_response_type
        tc_doc = MagicMock()
        tc_doc.document_properties = {'depends_on': []}
        session = MagicMock()
        rt, doc = tuning_curve_to_response_type(session, tc_doc)
        assert rt == ''
        assert doc is None


class TestFindMixtureName:
    """Tests for stimulus.find_mixture_name."""

    def test_match(self, tmp_path):
        from ndi.fun.stimulus import find_mixture_name
        dictionary = {
            'saline': [
                {'ontologyName': 'NaCl', 'name': 'NaCl', 'value': 0.9,
                 'ontologyUnit': '%', 'unitName': 'percent'},
            ],
        }
        f = tmp_path / 'mixtures.json'
        f.write_text(json.dumps(dictionary))

        mixture = [
            {'ontologyName': 'NaCl', 'name': 'NaCl', 'value': '0.9',
             'ontologyUnit': '%', 'unitName': 'percent'},
        ]
        result = find_mixture_name(str(f), mixture)
        assert 'saline' in result

    def test_no_match(self, tmp_path):
        from ndi.fun.stimulus import find_mixture_name
        dictionary = {'saline': [{'name': 'NaCl', 'ontologyName': 'NaCl',
                                   'value': 0.9, 'ontologyUnit': '%', 'unitName': 'percent'}]}
        f = tmp_path / 'mixtures.json'
        f.write_text(json.dumps(dictionary))
        result = find_mixture_name(str(f), [{'name': 'KCl', 'ontologyName': 'KCl',
                                              'value': '1.0', 'ontologyUnit': '%', 'unitName': 'percent'}])
        assert result == []

    def test_file_not_found(self):
        from ndi.fun.stimulus import find_mixture_name
        assert find_mixture_name('/nonexistent.json', []) == []


class TestStimulusTemporalFrequency:
    """Tests for stimulus.stimulus_temporal_frequency."""

    def test_basic_rule(self, tmp_path):
        from ndi.fun.stimulus import stimulus_temporal_frequency
        rules = [
            {'parameterName': 'tFrequency', 'multiplier': 1.0, 'adder': 0.0,
             'isPeriod': False},
        ]
        f = tmp_path / 'rules.json'
        f.write_text(json.dumps(rules))

        tf, name = stimulus_temporal_frequency({'tFrequency': 4.0}, config_path=str(f))
        assert tf == 4.0
        assert name == 'tFrequency'

    def test_period_inversion(self, tmp_path):
        from ndi.fun.stimulus import stimulus_temporal_frequency
        rules = [
            {'parameterName': 'period', 'multiplier': 1.0, 'adder': 0.0,
             'isPeriod': True},
        ]
        f = tmp_path / 'rules.json'
        f.write_text(json.dumps(rules))

        tf, name = stimulus_temporal_frequency({'period': 0.5}, config_path=str(f))
        assert tf == pytest.approx(2.0)

    def test_no_match(self, tmp_path):
        from ndi.fun.stimulus import stimulus_temporal_frequency
        rules = [{'parameterName': 'tFrequency', 'multiplier': 1.0, 'adder': 0.0}]
        f = tmp_path / 'rules.json'
        f.write_text(json.dumps(rules))

        tf, name = stimulus_temporal_frequency({'other': 5.0}, config_path=str(f))
        assert tf is None
        assert name == ''


# ===========================================================================
# ndi.fun.session and dataset tests
# ===========================================================================


class TestSessionDiff:
    """Tests for session.diff."""

    def _make_doc(self, doc_id, extra=None):
        d = MagicMock()
        props = {'base': {'id': doc_id, 'session_id': 's1'}}
        if extra:
            props.update(extra)
        d.document_properties = props
        return d

    def test_equal_sessions(self):
        from ndi.fun.session import diff
        d1 = self._make_doc('doc1', {'name': 'test'})
        s1 = MagicMock()
        s1.database_search.return_value = [d1]
        d2 = self._make_doc('doc1', {'name': 'test'})
        d2.document_properties['base']['session_id'] = 's2'
        s2 = MagicMock()
        s2.database_search.return_value = [d2]

        result = diff(s1, s2)
        assert result['equal'] is True

    def test_different_documents(self):
        from ndi.fun.session import diff
        s1 = MagicMock()
        s1.database_search.return_value = [self._make_doc('doc1')]
        s2 = MagicMock()
        s2.database_search.return_value = [self._make_doc('doc2')]

        result = diff(s1, s2)
        assert result['equal'] is False
        assert 'doc1' in result['only_in_s1']
        assert 'doc2' in result['only_in_s2']


class TestDatasetDiff:
    """Tests for dataset.diff."""

    def test_delegates_to_session(self):
        from ndi.fun.dataset import diff
        s1 = MagicMock()
        s1.database_search.return_value = []
        s2 = MagicMock()
        s2.database_search.return_value = []
        d1 = MagicMock()
        d1.session = s1
        d2 = MagicMock()
        d2.session = s2

        result = diff(d1, d2)
        assert 'equal' in result
        assert 'session_diff' in result


# ===========================================================================
# Import tests
# ===========================================================================


class TestFunImports:
    """Verify module structure."""

    def test_import_package(self):
        from ndi.fun import (
            channelname2prefixnumber,
            name2variable_name,
            pseudorandomint,
            timestamp,
        )
        assert callable(channelname2prefixnumber)

    def test_import_submodules(self):
        from ndi.fun import doc, epoch, file, data, stimulus, session, dataset
        assert hasattr(doc, 'diff')
        assert hasattr(epoch, 'epochid2element')
        assert hasattr(file, 'md5')
        assert hasattr(data, 'readngrid')
        assert hasattr(stimulus, 'tuning_curve_to_response_type')
        assert hasattr(session, 'diff')
        assert hasattr(dataset, 'diff')
