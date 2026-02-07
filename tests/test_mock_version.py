"""Tests for ndi.mock and ndi.version — mock data generators and version function."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# ndi.version() tests
# ===========================================================================


class TestVersion:
    """Tests for ndi.version()."""

    def test_returns_tuple(self):
        import ndi
        result = ndi.version()
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_version_string(self):
        import ndi
        v, url = ndi.version()
        assert isinstance(v, str)
        assert len(v) > 0

    def test_url(self):
        import ndi
        _, url = ndi.version()
        assert 'github.com' in url

    def test_fallback_version(self):
        """When git is unavailable, falls back to __version__."""
        import ndi
        with patch('subprocess.run', side_effect=FileNotFoundError):
            v, url = ndi.version()
        assert v == ndi.__version__

    def test_git_version(self):
        """When git works, returns git describe output."""
        import ndi
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = 'abc1234-dirty\n'
        with patch('subprocess.run', return_value=mock_result):
            v, url = ndi.version()
        assert v == 'abc1234-dirty'


# ===========================================================================
# ndi.mock.subject_stimulator_neuron tests
# ===========================================================================


class TestSubjectStimulatorNeuron:
    """Tests for subject_stimulator_neuron."""

    def test_creates_three_docs(self):
        from ndi.mock import subject_stimulator_neuron
        session = MagicMock()
        result = subject_stimulator_neuron(session)
        assert 'subject' in result
        assert 'stimulator' in result
        assert 'spikes' in result

    def test_subject_name_format(self):
        from ndi.mock import subject_stimulator_neuron
        session = MagicMock()
        result = subject_stimulator_neuron(session)
        assert 'mock' in result['subject_name']
        assert '@nosuchlab.org' in result['subject_name']

    def test_ref_num_range(self):
        from ndi.mock import subject_stimulator_neuron
        session = MagicMock()
        result = subject_stimulator_neuron(session)
        assert 20000 <= result['ref_num'] <= 20999


# ===========================================================================
# ndi.mock.stimulus_presentation tests
# ===========================================================================


class TestStimulusPresentationMock:
    """Tests for stimulus_presentation mock generator."""

    def test_basic_creation(self):
        from ndi.mock import stimulus_presentation
        result = stimulus_presentation(
            independent_variables=['contrast'],
            param_values=[[0.5], [1.0]],
            response_rates=[10.0, 20.0],
            reps=2,
            stim_duration=1.0,
        )
        assert 'presentations' in result
        assert 'spike_times' in result
        # 2 stimuli * 2 reps = 4 presentations
        assert len(result['presentations']) == 4

    def test_spike_times_sorted(self):
        from ndi.mock import stimulus_presentation
        result = stimulus_presentation(
            independent_variables=['x'],
            param_values=[[1]],
            response_rates=[50.0],
            reps=3,
            stim_duration=2.0,
        )
        st = result['spike_times']
        assert st == sorted(st)

    def test_zero_rate_no_spikes(self):
        from ndi.mock import stimulus_presentation
        result = stimulus_presentation(
            independent_variables=['x'],
            param_values=[[0]],
            response_rates=[0.0],
            reps=1,
            stim_duration=1.0,
        )
        assert len(result['spike_times']) == 0

    def test_epoch_id(self):
        from ndi.mock import stimulus_presentation
        result = stimulus_presentation(
            independent_variables=['x'],
            param_values=[[1]],
            response_rates=[5.0],
            epoch_id='test_epoch',
        )
        assert result['epoch_id'] == 'test_epoch'

    def test_presentation_timing(self):
        from ndi.mock import stimulus_presentation
        result = stimulus_presentation(
            independent_variables=['x'],
            param_values=[[1]],
            response_rates=[10.0],
            reps=1,
            stim_duration=2.0,
            interstimulus_interval=1.0,
        )
        pres = result['presentations'][0]
        assert pres['onset'] == 0.0
        assert pres['offset'] == 2.0

    def test_noisy_spikes(self):
        from ndi.mock import stimulus_presentation
        result = stimulus_presentation(
            independent_variables=['x'],
            param_values=[[1]],
            response_rates=[100.0],
            noise=1.0,
            reps=1,
            stim_duration=5.0,
        )
        # With noise, spike count varies but should be non-zero
        assert len(result['spike_times']) > 0


# ===========================================================================
# ndi.mock.clear_mock_docs tests
# ===========================================================================


class TestClearMockDocs:
    """Tests for clear_mock_docs."""

    def test_removes_mock_docs(self):
        from ndi.mock import clear_mock_docs
        doc = MagicMock()
        doc.document_properties = {
            'subject': {'local_identifier': 'mock20123@nosuchlab.org'},
        }
        session = MagicMock()
        session.database_search.return_value = [doc]
        session.database_rm.return_value = None

        count = clear_mock_docs(session)
        assert count == 1
        session.database_rm.assert_called_once()

    def test_skips_non_mock(self):
        from ndi.mock import clear_mock_docs
        doc = MagicMock()
        doc.document_properties = {
            'subject': {'local_identifier': 'real_subject@lab.org'},
        }
        session = MagicMock()
        session.database_search.return_value = [doc]

        count = clear_mock_docs(session)
        assert count == 0
        session.database_rm.assert_not_called()

    def test_empty_session(self):
        from ndi.mock import clear_mock_docs
        session = MagicMock()
        session.database_search.return_value = []
        count = clear_mock_docs(session)
        assert count == 0


# ===========================================================================
# ndi.mock.CalculatorTest tests
# ===========================================================================


class TestCalculatorTest:
    """Tests for CalculatorTest base class."""

    def test_default_generate(self):
        from ndi.mock import CalculatorTest
        ct = CalculatorTest()
        result = ct.generate_mock_docs()
        assert 'input_docs' in result
        assert 'expected_output' in result

    def test_mock_filenames(self):
        from ndi.mock import CalculatorTest
        ct = CalculatorTest()
        assert ct.mock_expected_filename(1) == 'mock.1.json'
        assert ct.mock_comparison_filename(3) == 'mock.3.compare.json'

    def test_write_and_load(self, tmp_path):
        from ndi.mock import CalculatorTest
        ct = CalculatorTest()
        # Override mock_path to use tmp
        ct.mock_path = lambda: tmp_path

        doc = MagicMock()
        doc.document_properties = {'test': 'data'}

        assert ct.write_mock_expected_output(1, doc) is True
        # Should refuse to overwrite
        assert ct.write_mock_expected_output(1, doc) is False

        loaded = ct.load_mock_expected_output(1)
        assert loaded == {'test': 'data'}

    def test_load_nonexistent(self, tmp_path):
        from ndi.mock import CalculatorTest
        ct = CalculatorTest()
        ct.mock_path = lambda: tmp_path
        assert ct.load_mock_expected_output(99) is None

    def test_compare_equal_docs(self):
        from ndi.mock import CalculatorTest
        ct = CalculatorTest()
        d1 = MagicMock()
        d1.document_properties = {'a': 1, 'b': 2}
        d2 = MagicMock()
        d2.document_properties = {'a': 1, 'b': 2}
        match, report = ct.compare_mock_docs(d1, d2)
        assert match is True

    def test_compare_different_docs(self):
        from ndi.mock import CalculatorTest
        ct = CalculatorTest()
        d1 = MagicMock()
        d1.document_properties = {'a': 1}
        d2 = MagicMock()
        d2.document_properties = {'a': 2}
        match, report = ct.compare_mock_docs(d1, d2)
        assert match is False

    def test_test_no_calculator(self):
        from ndi.mock import CalculatorTest
        ct = CalculatorTest()
        result = ct.test()
        assert result['passed'] is False


# ===========================================================================
# Import tests
# ===========================================================================


class TestMockVersionImports:
    """Verify module structure."""

    def test_import_mock(self):
        from ndi.mock import (
            subject_stimulator_neuron,
            stimulus_presentation,
            clear_mock_docs,
            CalculatorTest,
        )
        assert callable(subject_stimulator_neuron)
        assert callable(stimulus_presentation)
        assert callable(clear_mock_docs)

    def test_import_version(self):
        import ndi
        assert callable(ndi.version)
        assert 'version' in ndi.__all__

    def test_ndi_version_string(self):
        import ndi
        assert hasattr(ndi, '__version__')
        assert isinstance(ndi.__version__, str)
