"""Tests for ndi.fun.plot_extracellular_spikeshapes.

Mirrors MATLAB ndi.fun.plot_extracellular_spikeshapes. Rendering is driven
through matplotlib's non-interactive Agg backend so these run headless.
"""

from __future__ import annotations

import numpy as np
import pytest

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import ndi.fun as ndi_fun  # noqa: E402


def _doc(times, waveform):
    return {
        "neuron_extracellular": {
            "waveform_sample_times": np.asarray(times),
            "mean_waveform": np.asarray(waveform),
        }
    }


class _Session:
    def __init__(self, docs):
        self._docs = docs
        self.searches = 0

    def database_search(self, query):  # noqa: ARG002
        self.searches += 1
        return self._docs


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    plt.close("all")


class TestPlotExtracellularSpikeshapes:
    def test_reachable_at_the_matlab_mirror_path(self):
        """MATLAB puts this at the top of +fun, not in +fun/+plot."""
        assert hasattr(ndi_fun, "plot_extracellular_spikeshapes")

    def test_searches_when_documents_are_not_supplied(self):
        s = _Session([_doc([0, 1, 2], [[0.0], [1.0], [0.0]])])
        out = ndi_fun.plot_extracellular_spikeshapes(s, 1.0)
        assert s.searches == 1
        assert len(out) == 1

    def test_does_not_search_when_documents_are_supplied(self):
        """MATLAB's `if nargin<3` guard: supplying g skips the query."""
        s = _Session([])
        docs = [_doc([0, 1], [[0.0], [1.0]])]
        out = ndi_fun.plot_extracellular_spikeshapes(s, 1.0, docs)
        assert s.searches == 0
        assert out is docs

    def test_shared_x_limits_span_every_document(self):
        """The upper limit must accumulate the max across all documents.

        MATLAB reads x_axis(1) -- the running minimum -- when computing the
        upper limit, so with these inputs it would land on 5 (the last
        document's max) only by luck of ordering, and on a lower value when
        the widest document is not last. Ordering here puts the widest
        document FIRST, which is where the MATLAB expression gives the wrong
        answer.
        """
        docs = [
            _doc([-10, 0, 10], [[0.0], [1.0], [0.0]]),
            _doc([-1, 0, 1], [[0.0], [1.0], [0.0]]),
        ]
        ndi_fun.plot_extracellular_spikeshapes(_Session([]), 1.0, docs)
        left, right = plt.gca().get_xlim()
        assert left == pytest.approx(-10.0)
        assert right == pytest.approx(10.0)

    def test_empty_document_list_is_harmless(self):
        out = ndi_fun.plot_extracellular_spikeshapes(_Session([]), 1.0, [])
        assert out == []
