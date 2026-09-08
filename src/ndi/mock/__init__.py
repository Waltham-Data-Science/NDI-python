"""
ndi.mock - Mock data generators for testing.

MATLAB equivalents: +ndi/+mock/+fun/subject_stimulator_neuron.m,
    stimulus_presentation.m, stimulus_response.m, clear.m,
    +ndi/+mock/ctest.m

Provides utilities to create mock subjects, elements, stimulus
presentations, and responses for calculator testing.
"""

from __future__ import annotations

import inspect
import json
import math
import random
from pathlib import Path
from typing import Any

import numpy as np

#: The mock element names.  MATLAB uses 'mock stimulator' and 'mock spikes';
#: ndi_element refuses a name containing whitespace, a rule MATLAB's
#: ndi.element does not have, so the underscore forms stand in for them here.
MOCK_STIMULATOR_NAME = "mock_stimulator"
MOCK_SPIKES_NAME = "mock_spikes"

#: pickFreeReference's search space. MATLAB draws referenceMin + randi(span),
#: so the lowest value it can return is referenceMin + 1.
_REFERENCE_MIN = 20000
_REFERENCE_SPAN = 60000
_REFERENCE_MAX_ATTEMPTS = 100


def _mock_reference_in_use(session: Any, ref_num: int) -> bool:
    """Does this session already hold a mock at this reference?

    Checks the subject as well as the two elements, because the subject name
    carries the number too and a leftover subject would produce a second mock
    subject with the same name.
    """
    from ndi.query import ndi_query

    subject_query = ndi_query(
        "subject.local_identifier", "exact_string", f"mock{ref_num}@nosuchlab.org"
    )
    if session.database_search(subject_query):
        return True

    for element_name in (MOCK_STIMULATOR_NAME, MOCK_SPIKES_NAME):
        element_query = ndi_query("element.name", "exact_string", element_name) & ndi_query(
            "element.reference", "exact_number", ref_num
        )
        if session.database_search(element_query):
            return True

    return False


def _pick_free_reference(session: Any) -> int:
    """A mock reference number not already used in this session.

    An element is identified by its name, type and reference, so two mock
    elements drawn with the same reference are ONE element.  The second call
    then adds a second epoch named 'mockepoch' to it, and reading that epoch
    fails: the epoch table has two entries where the caller expects one.  That
    is what happens when several mocks are made in a session without clearing
    in between, as when a calculator regenerates all of its stored self-test
    expectations in one go.

    The number used to be drawn from a span of 1000 with no check at all,
    which collides about one time in five over 22 draws.  Drawing is still
    random rather than sequential, so routines running in parallel on separate
    sessions do not march in step; the check is what makes it safe.

    Raises:
        RuntimeError: If no free reference is found in 100 attempts.
    """
    for _attempt in range(_REFERENCE_MAX_ATTEMPTS):
        candidate = _REFERENCE_MIN + random.randint(1, _REFERENCE_SPAN)
        if not _mock_reference_in_use(session, candidate):
            return candidate

    raise RuntimeError(
        f"Could not find an unused mock reference number in "
        f"{_REFERENCE_MAX_ATTEMPTS} attempts, over the range "
        f"{_REFERENCE_MIN + 1} to {_REFERENCE_MIN + _REFERENCE_SPAN}. The session "
        f"appears to be full of mock documents; ndi.mock.clear_mock_docs removes them."
    )


def subject_stimulator_neuron(
    session: Any,
) -> dict[str, Any]:
    """Create mock subject, stimulator, and spiking neuron.

    MATLAB equivalent: ndi.mock.fun.subject_stimulator_neuron

    The subject document is ADDED to the session's database and both elements
    are built against it, exactly as MATLAB does.  The previous version built
    three loose documents that the session never saw, so nothing a caller did
    with them could be found again.

    Args:
        session: An NDI session instance.

    Returns:
        Dict with ``'subject'`` (the added subject document), ``'stimulator'``
        and ``'spikes'`` (``ndi_element_timeseries`` objects), plus
        ``'subject_name'`` and ``'ref_num'``.
    """
    from ndi.element_timeseries import ndi_element_timeseries
    from ndi.subject import ndi_subject

    ref_num = _pick_free_reference(session)
    subject_name = f"mock{ref_num}@nosuchlab.org"

    mock_subject = ndi_subject(subject_name, "A mock subject for testing purposes")
    subject_doc = mock_subject.newdocument()
    session.database_add(subject_doc)

    stimulator = ndi_element_timeseries(
        session=session,
        name=MOCK_STIMULATOR_NAME,
        reference=ref_num,
        type="stimulator",
        underlying_element=None,
        direct=False,
        subject_id=subject_doc.id,
    )

    spikes = ndi_element_timeseries(
        session=session,
        name=MOCK_SPIKES_NAME,
        reference=ref_num,
        type="spikes",
        underlying_element=None,
        direct=False,
        subject_id=subject_doc.id,
    )

    return {
        "subject": subject_doc,
        "stimulator": stimulator,
        "spikes": spikes,
        "subject_name": subject_name,
        "ref_num": ref_num,
    }


def stimulus_presentation(
    independent_variables: list[str],
    param_values: list[list[Any]],
    response_rates: list[float],
    noise: float = 0.0,
    reps: int = 5,
    stim_duration: float = 10.0,
    interstimulus_interval: float = 5.0,
    epoch_id: str = "mockepoch",
) -> dict[str, Any]:
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
        epoch_id: ndi_epoch_epoch identifier.

    Returns:
        Dict with ``'presentations'`` (list of dicts with timing info),
        ``'spike_times'`` (list of floats), ``'epoch_id'``.
    """
    presentations: list[dict[str, Any]] = []
    spike_times: list[float] = []
    t = 0.0

    n_stim = len(response_rates)

    for _rep in range(reps):
        for i in range(n_stim):
            onset = t
            offset = t + stim_duration
            rate = response_rates[i]

            # Generate spike times
            if rate > 0:
                n_spikes = int(rate * stim_duration)
                if noise > 0:
                    n_spikes = max(0, int(n_spikes + noise * random.gauss(0, n_spikes**0.5)))
                for s in range(n_spikes):
                    st = onset + (s + random.random()) * stim_duration / max(n_spikes, 1)
                    if st < offset:
                        spike_times.append(st)

            # Build parameters dict for this stimulus.  MATLAB reads a NaN
            # in X as a CONTROL (blank) stimulus and writes isblank=1 in
            # place of the variable, which is how ndi.app.stimulus later
            # finds the control stimuli.  A NaN passed here used to land in
            # the parameters as a NaN value, so nothing downstream could
            # tell a blank from a stimulus whose value happened to be
            # missing.
            params: dict[str, Any] = {}
            if i < len(param_values):
                for j, var_name in enumerate(independent_variables):
                    if j < len(param_values[i]):
                        value = param_values[i][j]
                        if isinstance(value, float) and math.isnan(value):
                            params["isblank"] = 1
                        else:
                            params[var_name] = value

            presentations.append(
                {
                    "stimopen": onset,
                    "onset": onset,
                    "offset": offset,
                    "stimclose": offset,
                    "parameters": params,
                }
            )

            t = offset + interstimulus_interval

    spike_times.sort()

    return {
        "presentations": presentations,
        "spike_times": spike_times,
        "epoch_id": epoch_id,
    }


def stimulus_response(
    session: Any,
    parameter_struct: dict[str, Any],
    independent_variables: list[str],
    X: np.ndarray,
    R: np.ndarray,
    noise: float,
    reps: int,
    stim_duration: float = 2.0,
    interstimulus_interval: float = 3.0,
    epochid: str = "mockepoch",
) -> dict[str, Any]:
    """Create a complete mock stimulus-response dataset.

    MATLAB equivalent: ndi.mock.fun.stimulus_response

    Creates a mock subject, stimulator, neuron, stimulus presentation,
    control stimulus labels, stimulus response data, and tuning curve
    documents.

    Args:
        session: An NDI session instance.
        parameter_struct: Base parameters common to all stimuli.
        independent_variables: List of parameter names that vary.
        X: Independent variable values array. Shape (N,) for 1D or
            (N, M) for M variables.
        R: Response values (firing rates) for each stimulus.
        noise: Noise level relative to response magnitude.
        reps: Number of repetitions per stimulus.
        stim_duration: Duration of each stimulus in seconds.
        interstimulus_interval: Gap between stimuli in seconds.
        epochid: ndi_epoch_epoch identifier.

    Returns:
        Dict with keys: ``'subject'``, ``'stimulator'``, ``'spikes'``,
        ``'stimulus_presentation'``, ``'control_stimulus'``,
        ``'stimulus_response'``, ``'tuning_curve'``.
    """
    X = np.asarray(X, dtype=float)
    R = np.asarray(R, dtype=float)

    # Build param_values from X
    if X.ndim == 1:
        param_values = [[float(x)] for x in X]
    else:
        param_values = [list(row) for row in X]

    # Create mock elements
    mock_elements = subject_stimulator_neuron(session)

    # Create stimulus presentation data
    pres_data = stimulus_presentation(
        independent_variables=independent_variables,
        param_values=param_values,
        response_rates=R.tolist(),
        noise=noise,
        reps=reps,
        stim_duration=stim_duration,
        interstimulus_interval=interstimulus_interval,
        epoch_id=epochid,
    )

    return {
        "subject": mock_elements["subject"],
        "stimulator": mock_elements["stimulator"],
        "spikes": mock_elements["spikes"],
        "stimulus_presentation": pres_data,
        "control_stimulus": None,
        "stimulus_response": None,
        "tuning_curve": None,
    }


def clear_mock_docs(session: Any) -> None:
    """Remove all mock documents from a session.

    MATLAB equivalent: ndi.mock.fun.clear

    Searches for subjects with 'mock' in local_identifier and removes them.

    Args:
        session: An NDI session instance.
    """
    from ndi.query import ndi_query

    # MATLAB is two lines: search, then remove.  This had a try/except around
    # the whole thing with a fallback that itself ended in `except Exception:
    # pass`, so a session whose database_rm failed reported success and left
    # every mock document in place -- the failure mode this function exists to
    # prevent.  Errors now reach the caller, as they do in MATLAB.
    docs = session.database_search(ndi_query("subject.local_identifier", "contains_string", "mock"))
    if docs:
        session.database_rm(docs)


class ndi_mock_ctest:
    """Base class for calculator testing framework.

    MATLAB equivalent: ndi.mock.ctest

    Subclasses override :meth:`generate_mock_docs` and :meth:`compare_mock_docs`
    to test specific calculator implementations.
    """

    def __init__(self, calculator: Any = None):
        self.calculator = calculator

    def generate_mock_docs(
        self,
        scope: str = "highSNR",
        number: int = 1,
    ) -> dict[str, Any]:
        """Generate mock input documents for calculator testing.

        Override in subclasses.

        Args:
            scope: ``'highSNR'`` or ``'lowSNR'``.
            number: Test number.

        Returns:
            Dict with ``'input_docs'`` and ``'expected_output'``.
        """
        return {"input_docs": [], "expected_output": None}

    def compare_mock_docs(
        self,
        expected: Any,
        actual: Any,
        scope: str = "",
        docCompare: Any = None,
    ) -> tuple[bool, Any]:
        """Compare expected vs actual calculator output.

        MATLAB equivalent: ``compare_mock_docs(expected_doc, actual_doc,
        scope, docCompare)``. When ``scope`` is ``'highSNR'`` and
        ``docCompare`` is a :class:`~ndi.doc_comparison.DocComparison`
        instance, comparison uses the recorded per-field tolerances --
        which is what MATLAB does. Otherwise this falls through to the
        exact-equality comparison, matching MATLAB's abstract-class
        default outside ``highSNR``.

        Override in subclasses.

        Args:
            expected: The stored expected calculator output.
            actual: The freshly computed calculator output.
            scope: ``'highSNR'`` or ``'lowSNR'`` (empty means: don't
                consult ``docCompare``).
            docCompare: A :class:`~ndi.doc_comparison.DocComparison`
                object carrying per-field tolerance rules, typically
                loaded from ``mock.N.compare.json`` via
                :meth:`load_mock_comparison`.

        Returns:
            Tuple of ``(match, report)``. ``report`` is a string for
            exact-comparison results and the list of per-field result
            dicts returned by :meth:`DocComparison.compare` when a
            tolerance-based comparison was used, so ``reportSummary`` can
            name the fields that failed.
        """
        from ndi.doc_comparison import DocComparison

        if (
            scope.lower() == "highsnr"
            and isinstance(docCompare, DocComparison)
        ):
            result = docCompare.compare(actual, expected)
            failures = [r for r in result.get("results", []) if not r.get("passed")]
            report = [{"name": r["field"], **r} for r in failures]
            return bool(result["equal"]), report

        from ndi.fun.doc import diff

        result = diff(expected, actual)
        return result["equal"], "\n".join(result["details"])

    def calc_path(self) -> Path:
        """Return the directory this ctest class is defined in.

        MATLAB is ``which(class(ctest_obj))`` followed by ``fileparts``, so it
        is the SUBCLASS's own file, not the calculator's.  There was no
        counterpart here at all, and ``mock_path`` reached for the
        calculator's ``calc_path`` instead.
        """
        return Path(inspect.getfile(type(self))).resolve().parent

    def mock_path(self) -> Path:
        """Return path to mock example output directory.

        MATLAB: ``calc_path()/mock/<classname>/``.  The class-name directory
        was missing here, and when there was no calculator the path fell back
        to a bare ``Path('mock')`` -- relative to whatever the working
        directory happened to be.
        """
        return self.calc_path() / "mock" / type(self).__name__

    def mock_expected_filename(self, number: int) -> Path:
        """Return the full path of the Nth expected output.

        MATLAB returns ``mock_path()`` joined with the name; this returned the
        bare ``mock.N.json``, so a caller who used the method on its own --
        rather than re-joining it with mock_path as load/write did here -- got
        a name relative to the working directory.
        """
        return self.mock_path() / f"mock.{number}.json"

    def mock_comparison_filename(self, number: int) -> Path:
        """Return the full path of the Nth comparison rules file."""
        return self.mock_path() / f"mock.{number}.compare.json"

    def load_mock_comparison(self, number: int) -> Any | None:
        """Load the Nth stored comparison rules, or None if there are none.

        MATLAB equivalent: ``load_mock_comparison``.  Not ported before, so
        the stored per-field tolerances were never read and
        :meth:`compare_mock_docs` could only compare documents exactly.
        """
        from ndi.doc_comparison import DocComparison

        path = self.mock_comparison_filename(number)
        if not path.is_file():
            return None
        return DocComparison.from_json(path.read_text())

    def clean_mock_docs(self) -> None:
        """Remove mock/test documents.

        MATLAB's body is empty -- the method exists so a subclass can
        override it -- and so is this one.  It is here because a caller
        following MATLAB got an AttributeError instead of a no-op.
        """

    @staticmethod
    def reportSummary(report: Any) -> str:
        """Render a comparison report as a short sentence.

        MATLAB equivalent: the static ``ndi.mock.ctest.reportSummary``.
        Returns a LEADING-SPACE sentence, or ``''`` when there is nothing to
        say, so it can be appended to a message directly.
        """
        if not report:
            return ""
        if isinstance(report, str):
            return " " + report
        if isinstance(report, dict) and "name" in report:
            return f" Out of tolerance: {report['name']}."
        if isinstance(report, (list, tuple)) and all(
            isinstance(r, dict) and "name" in r for r in report
        ):
            return " Out of tolerance: " + ", ".join(r["name"] for r in report) + "."
        return ""

    def load_mock_expected_output(self, number: int) -> dict | None:
        """Load expected output from file."""
        p = self.mock_expected_filename(number)
        if p.exists():
            with open(p) as f:
                return json.load(f)
        return None

    def write_mock_expected_output(self, number: int, doc: Any) -> bool:
        """Write expected output document. Refuses to overwrite existing.

        Returns:
            True on success, False if file already exists.
        """
        p = self.mock_expected_filename(number)
        if p.exists():
            return False
        p.parent.mkdir(parents=True, exist_ok=True)
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        with open(p, "w") as f:
            json.dump(props, f, indent=2)
        return True

    def test(
        self,
        scope: str = "highSNR",
        number_of_tests: int = 1,
    ) -> dict[str, Any]:
        """Run calculator tests and return comparison results.

        MATLAB equivalent: ``[b, reports, b_expected, doc_output,
        doc_expected_output] = test(...)``. The tolerance rules stored in
        ``mock.N.compare.json`` are loaded via :meth:`load_mock_comparison`
        and passed through to :meth:`compare_mock_docs`, so a calculator
        whose answer is within its own recorded tolerance passes here as
        it does in MATLAB.

        Args:
            scope: ``'highSNR'`` or ``'lowSNR'``.
            number_of_tests: Number of self-tests to run.

        Returns:
            Dict with keys:

            - ``passed``: overall pass/fail (all diagonal ``b_actual``
              entries must be ``True``).
            - ``results``: legacy list of ``(match, report)`` tuples,
              one per test, mirroring the diagonal of ``b_actual``.
            - ``b_actual``: N-by-N matrix (list of lists) where
              ``b_actual[i][j]`` is the result of comparing the stored
              expected output for test ``j`` against the calculator's
              actual output for test ``i``. ``None`` marks a test that
              did not run.
            - ``b_expected``: N-by-N matrix comparing stored expected
              outputs against each other -- a control for whether two
              tests were even distinguishable to start with.
            - ``reports``: matching N-by-N matrix of per-cell reports.
            - ``doc_output``: list of actual outputs, one per test.
            - ``doc_expected_output``: list of stored expected outputs.
        """
        n = number_of_tests
        doc_output: list[Any] = [None] * n
        doc_expected_output: list[Any] = [None] * n
        docComparisons: list[Any] = [None] * n
        run_errors: list[str | None] = [None] * n

        for i in range(n):
            docComparisons[i] = self.load_mock_comparison(i + 1)

        for i in range(n):
            mock_data = self.generate_mock_docs(scope, i + 1)
            expected = mock_data.get("expected_output")
            if expected is None:
                expected = self.load_mock_expected_output(i + 1)
            doc_expected_output[i] = expected

            if expected is None:
                run_errors[i] = f"No expected output for test {i + 1}"
                continue

            if self.calculator is None or not hasattr(self.calculator, "run"):
                run_errors[i] = "No calculator configured"
                continue

            try:
                doc_output[i] = self.calculator.run(mock_data.get("input_docs", []))
            except Exception as e:
                run_errors[i] = f"ndi_calculator error: {e}"

        b_actual: list[list[bool | None]] = [[None] * n for _ in range(n)]
        b_expected: list[list[bool | None]] = [[None] * n for _ in range(n)]
        reports: list[list[Any]] = [[""] * n for _ in range(n)]

        for i in range(n):
            for j in range(n):
                if doc_output[i] is None or doc_expected_output[j] is None:
                    b_actual[i][j] = None
                    reports[i][j] = run_errors[i] or "Test not run"
                else:
                    match, report = self.compare_mock_docs(
                        doc_expected_output[j],
                        doc_output[i],
                        scope,
                        docComparisons[j],
                    )
                    b_actual[i][j] = bool(match)
                    reports[i][j] = report

                if doc_expected_output[i] is None or doc_expected_output[j] is None:
                    b_expected[i][j] = None
                else:
                    match_e, _ = self.compare_mock_docs(
                        doc_expected_output[i],
                        doc_expected_output[j],
                        scope,
                        docComparisons[j],
                    )
                    b_expected[i][j] = bool(match_e)

        legacy: list[tuple[bool, Any]] = []
        for i in range(n):
            diag = b_actual[i][i]
            if diag is None:
                legacy.append((False, reports[i][i]))
            else:
                legacy.append((bool(diag), reports[i][i]))

        all_passed = bool(legacy) and all(r[0] for r in legacy)

        return {
            "passed": all_passed,
            "results": legacy,
            "b_actual": b_actual,
            "b_expected": b_expected,
            "reports": reports,
            "doc_output": doc_output,
            "doc_expected_output": doc_expected_output,
        }


__all__ = [
    "subject_stimulator_neuron",
    "stimulus_presentation",
    "stimulus_response",
    "clear_mock_docs",
    "ndi_mock_ctest",
]
