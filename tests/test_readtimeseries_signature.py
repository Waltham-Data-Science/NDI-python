"""readtimeseries names its first parameter the same thing everywhere.

Issue: Waltham-Data-Science/NDI-python#166

MATLAB spells it ``timeref_or_epoch`` in all three classes that declare the
method -- ndi.time.timeseries, ndi.element.timeseries and ndi.probe.timeseries
-- and the argument genuinely takes either an ndi.time.timereference or an
epoch. Python's probe class used to call it ``epoch``, so the two classes could
not be used interchangeably by keyword:

    TypeError: ndi_element_timeseries.readtimeseries() got an unexpected
               keyword argument 'epoch'

That made ndi.fun.probe.export.binary silently probe-only, since it passed
``epoch=``. These tests pin the spelling and the substitutability rather than
the call sites, so a future caller cannot quietly reintroduce the split.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import numpy as np
import pytest

from ndi.element_timeseries import ndi_element_timeseries
from ndi.probe.timeseries import ndi_probe_timeseries
from ndi.time.clocktype import ndi_time_clocktype
from ndi.time.timereference import ndi_time_timereference

MATLAB_NAME = "timeref_or_epoch"


def _timereference(probe):
    """A reference to PROBE's first epoch. session_id is passed explicitly so
    the probe needs no session of its own -- what is under test is which
    argument the reference arrives in, not how it was built."""
    return ndi_time_timereference(
        referent=probe,
        clocktype=ndi_time_clocktype("dev_local_time"),
        epoch="epoch_1",
        time=0.0,
        session_id="session_for_this_test",
    )


def _first_parameter(cls) -> str:
    parameters = list(inspect.signature(cls.readtimeseries).parameters)
    return parameters[1] if parameters[0] == "self" else parameters[0]


class TestTheNameMatchesMatlab:
    @pytest.mark.parametrize("cls", [ndi_probe_timeseries, ndi_element_timeseries])
    def test_the_first_parameter_is_timeref_or_epoch(self, cls):
        assert _first_parameter(cls) == MATLAB_NAME

    def test_the_two_classes_agree_with_each_other(self):
        """The point of the issue: one spelling, so a caller passing by
        keyword works against either class."""
        assert _first_parameter(ndi_probe_timeseries) == _first_parameter(ndi_element_timeseries)

    def test_readtimeseriesepoch_still_says_epoch(self):
        """It takes an epoch and nothing else, so ``epoch`` is correct there.
        A blanket rename would have swept this up with the rest."""
        parameters = list(inspect.signature(ndi_probe_timeseries.readtimeseriesepoch).parameters)
        assert parameters[1] == "epoch"


class TestTheArgumentTakesEither:
    """MATLAB dispatches on the type of the first argument
    (+ndi/+probe/timeseries.m:39). A name promising 'timeref or epoch' that
    accepted only an epoch would be worse than the honest old name."""

    def test_a_timereference_in_the_first_position_reaches_the_syncgraph(self):
        probe = ndi_probe_timeseries(name="ctx", reference=1, type="n-trode")
        seen = {}

        def record(timeref, t0, t1):
            seen.update(timeref=timeref, t0=t0, t1=t1)
            return None, None, None

        probe._readtimeseries_via_syncgraph = record
        reference = _timereference(probe)

        probe.readtimeseries(reference, 1.0, 2.0)

        assert seen["timeref"] is reference
        assert (seen["t0"], seen["t1"]) == (1.0, 2.0)

    def test_an_epoch_in_the_first_position_still_reads_that_epoch(self):
        probe = ndi_probe_timeseries(name="ctx", reference=1, type="n-trode")
        seen = {}

        def record(epoch, t0, t1):
            seen.update(epoch=epoch, t0=t0, t1=t1)
            return None, None, None

        probe.readtimeseriesepoch = record

        probe.readtimeseries("epoch_1", 1.0, 2.0)

        assert seen == {"epoch": "epoch_1", "t0": 1.0, "t1": 2.0}

    def test_the_timeref_keyword_still_works(self):
        """It is not MATLAB's shape, but it is public API and predates this
        change, so removing it is not in scope here."""
        probe = ndi_probe_timeseries(name="ctx", reference=1, type="n-trode")
        seen = {}
        probe._readtimeseries_via_syncgraph = lambda timeref, t0, t1: (
            seen.update(timeref=timeref),
            (None, None, None),
        )[1]
        reference = _timereference(probe)

        probe.readtimeseries(timeref=reference)

        assert seen["timeref"] is reference

    def test_neither_one_is_still_an_error(self):
        probe = ndi_probe_timeseries(name="ctx", reference=1, type="n-trode")
        with pytest.raises(ValueError):
            probe.readtimeseries()


class TestNoCallerReintroducesTheSplit:
    def test_nothing_in_src_calls_readtimeseries_with_epoch_as_a_keyword(self):
        """``readtimeseries(epoch=...)`` binds on a probe and raises on an
        element. Calling positionally works against both, which is what every
        call site in src/ndi now does.
        """
        source = Path(__file__).resolve().parent.parent / "src" / "ndi"
        offenders = [
            f"{path.relative_to(source.parent.parent)}:{number}"
            for path in source.rglob("*.py")
            for number, line in enumerate(path.read_text().splitlines(), start=1)
            if "readtimeseries(" in line
            and "epoch=" in line.split("readtimeseries(", 1)[1]
            and "readtimeseriesepoch(" not in line
            and "def readtimeseries" not in line
        ]
        assert offenders == []

    def test_the_guard_would_notice(self):
        """The check above is a string search over real files; this pins that
        the pattern it looks for is the one that actually breaks."""
        with pytest.raises(TypeError):
            ndi_element_timeseries.readtimeseries(object(), epoch=1)


class TestAnElementCanStandInForAProbe:
    """The concrete consequence, end to end: export.binary against an
    ndi_element_timeseries, which raised TypeError before this change."""

    def test_export_binary_accepts_an_element(self, tmp_path):
        from ndi.fun.probe import export_binary
        from ndi.session import ndi_session_dir
        from ndi.subject import ndi_subject

        rate, channels, samples = 100.0, 2, 20
        directory = tmp_path / "sess"
        directory.mkdir(parents=True, exist_ok=True)
        session = ndi_session_dir("stand_in", str(directory))
        subject = ndi_subject("mouse23@vhlab.org", "test mouse").newdocument()
        subject.set_session_id(session.id())
        session.database_add(subject)

        class Element(ndi_element_timeseries):
            """Only the sample-rate API a probe adds; readtimeseries is the
            element's own, unmodified."""

            def samplerate(self, epoch=None):
                return rate

            def times2samples(self, epoch, times):
                return np.round(np.asarray(times, dtype=float) * rate).astype(int)

            def samples2times(self, epoch, samples):
                return np.asarray(samples, dtype=float) / rate

        element = Element(
            session=session,
            name="ctx",
            reference=1,
            type="n-trode",
            direct=False,
            subject_id=subject.id,
        )
        session.database_add(element.newdocument())
        element.addepoch(
            "epoch_1",
            [ndi_time_clocktype("dev_local_time")],
            [(0.0, samples / rate)],
            np.arange(samples) / rate,
            np.full((samples, channels), 7.0),
        )

        binary = tmp_path / "ctx.bin"
        export_binary(element, str(binary), multiplier=1, verbose=False)

        written = np.fromfile(binary, dtype=np.int16).reshape(-1, channels)
        assert written.shape == (samples, channels)
        assert (written == 7).all()
