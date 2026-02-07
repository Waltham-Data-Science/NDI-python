"""
ndi.mock - Mock data generators for testing.

MATLAB equivalents: +ndi/+mock/+fun/subject_stimulator_neuron.m,
    stimulus_presentation.m, stimulus_response.m, clear.m,
    +ndi/+mock/ctest.m

Provides utilities to create mock subjects, elements, stimulus
presentations, and responses for calculator testing.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def subject_stimulator_neuron(
    session: Any,
) -> Dict[str, Any]:
    """Create mock subject, stimulator, and spiking neuron.

    MATLAB equivalent: ndi.mock.fun.subject_stimulator_neuron

    Args:
        session: An NDI session instance.

    Returns:
        Dict with ``'subject'``, ``'stimulator'``, ``'spikes'`` keys
        containing document/element objects.
    """
    from ndi.document import Document

    ref_num = 20000 + random.randint(0, 999)
    subject_name = f'mock{ref_num}@nosuchlab.org'

    # Create subject document
    subject_doc = Document('subject')
    subject_doc._set_nested_property('subject.local_identifier', subject_name)

    # Create stimulator element document
    stim_doc = Document('element')
    stim_doc._set_nested_property('element.name', f'mock_stimulator_{ref_num}')
    stim_doc._set_nested_property('element.type', 'stimulator')

    # Create spiking neuron element document
    spikes_doc = Document('element')
    spikes_doc._set_nested_property('element.name', f'mock_spikes_{ref_num}')
    spikes_doc._set_nested_property('element.type', 'spikes')

    return {
        'subject': subject_doc,
        'stimulator': stim_doc,
        'spikes': spikes_doc,
        'subject_name': subject_name,
        'ref_num': ref_num,
    }


def stimulus_presentation(
    independent_variables: List[str],
    param_values: List[List[Any]],
    response_rates: List[float],
    noise: float = 0.0,
    reps: int = 5,
    stim_duration: float = 10.0,
    interstimulus_interval: float = 5.0,
    epoch_id: str = 'mockepoch',
) -> Dict[str, Any]:
    """Create mock stimulus presentation data.

    MATLAB equivalent: ndi.mock.fun.stimulus_presentation

    Args:
        independent_variables: List of parameter names that vary.
        param_values: 2-D list: ``param_values[i][j]`` is the value
            of variable *j* for stimulus *i*.
        response_rates: Desired firing rates (spikes/sec) per stimulus.
        noise: Noise scaling factor (0 = clean).
        reps: Number of repetitions of each stimulus.
        stim_duration: Duration of each stimulus in seconds.
        interstimulus_interval: Gap between stimuli in seconds.
        epoch_id: Epoch identifier.

    Returns:
        Dict with ``'presentations'`` (list of dicts with timing info),
        ``'spike_times'`` (list of floats), ``'epoch_id'``.
    """
    presentations: List[Dict[str, Any]] = []
    spike_times: List[float] = []
    t = 0.0

    n_stim = len(response_rates)

    for rep in range(reps):
        for i in range(n_stim):
            onset = t
            offset = t + stim_duration
            rate = response_rates[i]

            # Generate spike times
            if rate > 0:
                n_spikes = int(rate * stim_duration)
                if noise > 0:
                    n_spikes = max(0, int(n_spikes + noise * random.gauss(0, n_spikes ** 0.5)))
                for s in range(n_spikes):
                    st = onset + (s + random.random()) * stim_duration / max(n_spikes, 1)
                    if st < offset:
                        spike_times.append(st)

            # Build parameters dict for this stimulus
            params: Dict[str, Any] = {}
            if i < len(param_values):
                for j, var_name in enumerate(independent_variables):
                    if j < len(param_values[i]):
                        params[var_name] = param_values[i][j]

            presentations.append({
                'stimopen': onset,
                'onset': onset,
                'offset': offset,
                'stimclose': offset,
                'parameters': params,
            })

            t = offset + interstimulus_interval

    spike_times.sort()

    return {
        'presentations': presentations,
        'spike_times': spike_times,
        'epoch_id': epoch_id,
    }


def clear_mock_docs(session: Any) -> int:
    """Remove all mock documents from a session.

    MATLAB equivalent: ndi.mock.fun.clear

    Searches for subjects with 'mock' in local_identifier and removes them.

    Args:
        session: An NDI session instance.

    Returns:
        Number of documents removed.
    """
    from ndi.query import Query

    count = 0
    try:
        docs = session.database_search(Query('').isa('subject'))
        for doc in docs:
            props = doc.document_properties if hasattr(doc, 'document_properties') else doc
            if isinstance(props, dict):
                local_id = props.get('subject', {}).get('local_identifier', '')
                if 'mock' in local_id.lower():
                    try:
                        session.database_rm(doc)
                        count += 1
                    except Exception:
                        pass
    except Exception:
        pass
    return count


class CalculatorTest:
    """Base class for calculator testing framework.

    MATLAB equivalent: ndi.mock.ctest

    Subclasses override :meth:`generate_mock_docs` and :meth:`compare_mock_docs`
    to test specific calculator implementations.
    """

    def __init__(self, calculator: Any = None):
        self.calculator = calculator

    def generate_mock_docs(
        self,
        scope: str = 'highSNR',
        number: int = 1,
    ) -> Dict[str, Any]:
        """Generate mock input documents for calculator testing.

        Override in subclasses.

        Args:
            scope: ``'highSNR'`` or ``'lowSNR'``.
            number: Test number.

        Returns:
            Dict with ``'input_docs'`` and ``'expected_output'``.
        """
        return {'input_docs': [], 'expected_output': None}

    def compare_mock_docs(
        self,
        expected: Any,
        actual: Any,
    ) -> Tuple[bool, str]:
        """Compare expected vs actual calculator output.

        Override in subclasses.

        Returns:
            Tuple of ``(match, report_string)``.
        """
        from ndi.fun.doc import diff
        result = diff(expected, actual)
        return result['equal'], '\n'.join(result['details'])

    def mock_path(self) -> Path:
        """Return path to mock example output directory."""
        if self.calculator is not None and hasattr(self.calculator, 'calc_path'):
            return Path(self.calculator.calc_path()) / 'mock'
        return Path('mock')

    def mock_expected_filename(self, number: int) -> str:
        """Return filename for Nth expected output."""
        return f'mock.{number}.json'

    def mock_comparison_filename(self, number: int) -> str:
        """Return filename for Nth comparison rules."""
        return f'mock.{number}.compare.json'

    def load_mock_expected_output(self, number: int) -> Optional[Dict]:
        """Load expected output from file."""
        p = self.mock_path() / self.mock_expected_filename(number)
        if p.exists():
            with open(p, 'r') as f:
                return json.load(f)
        return None

    def write_mock_expected_output(self, number: int, doc: Any) -> bool:
        """Write expected output document. Refuses to overwrite existing.

        Returns:
            True on success, False if file already exists.
        """
        p = self.mock_path() / self.mock_expected_filename(number)
        if p.exists():
            return False
        p.parent.mkdir(parents=True, exist_ok=True)
        props = doc.document_properties if hasattr(doc, 'document_properties') else doc
        with open(p, 'w') as f:
            json.dump(props, f, indent=2)
        return True

    def test(
        self,
        scope: str = 'highSNR',
        number_of_tests: int = 1,
    ) -> Dict[str, Any]:
        """Run calculator tests and return comparison results.

        Returns:
            Dict with ``'passed'`` (bool), ``'results'`` (list of tuples).
        """
        results: List[Tuple[bool, str]] = []
        for i in range(1, number_of_tests + 1):
            mock_data = self.generate_mock_docs(scope, i)
            expected = mock_data.get('expected_output')
            if expected is None:
                expected = self.load_mock_expected_output(i)
            if expected is None:
                results.append((False, f'No expected output for test {i}'))
                continue

            # Run calculator if available
            if self.calculator is not None and hasattr(self.calculator, 'run'):
                try:
                    actual = self.calculator.run(mock_data.get('input_docs', []))
                except Exception as e:
                    results.append((False, f'Calculator error: {e}'))
                    continue
            else:
                results.append((False, 'No calculator configured'))
                continue

            match, report = self.compare_mock_docs(expected, actual)
            results.append((match, report))

        all_passed = all(r[0] for r in results) if results else False
        return {'passed': all_passed, 'results': results}


__all__ = [
    'subject_stimulator_neuron',
    'stimulus_presentation',
    'clear_mock_docs',
    'CalculatorTest',
]
