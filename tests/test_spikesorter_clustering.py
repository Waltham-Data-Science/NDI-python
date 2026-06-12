"""
Tests for the implemented automatic spike-sorting path of ndi.app.spikesorter.

Three layers:

  * ``cluster_initializeclusterinfo`` math -- a pure (numpy-only) port of the
    MATLAB ``InitClusterInfo`` computation; runs everywhere.
  * ``ndi.util.klustakwik.cluster_spikewaves`` -- the KlustaKwik2 wrapper;
    ``importorskip('klustakwik2')`` so it skips cleanly when the optional
    dependency is absent.
  * End-to-end ``spike_sort`` / ``clusters2neurons`` against a real
    ``ndi_session_dir`` with synthetic, separable spike waveforms. These need
    both ``vlt`` (feature prep) and ``klustakwik2`` (clustering) and the session
    infra, so they skip cleanly if any is unavailable.

MATLAB equivalent: src/ndi/+ndi/+app/spikesorter.m (spike_sort / clusters2neurons)
"""

from __future__ import annotations

import numpy as np
import pytest

from ndi.app.spikesorter import ndi_app_spikesorter

# ---------------------------------------------------------------------------
# cluster_initializeclusterinfo (pure numpy, no optional deps)
# ---------------------------------------------------------------------------


def test_cluster_initializeclusterinfo_basic_math():
    # 3 samples x 2 channels x 4 spikes; clusters [1,1,2,2].
    waves = np.zeros((3, 2, 4))
    waves[:, :, 0] = 1.0
    waves[:, :, 1] = 3.0  # cluster 1 mean -> 2.0
    waves[:, :, 2] = 10.0
    waves[:, :, 3] = 20.0  # cluster 2 mean -> 15.0
    clusterids = np.array([1, 1, 2, 2])
    epochinfo = {"EpochStartSamples": [1, 3], "EpochNames": ["epA", "epB"]}

    ci = ndi_app_spikesorter.cluster_initializeclusterinfo(clusterids, waves, epochinfo)

    assert len(ci) == 2
    assert ci[0]["number"] == "1"
    assert ci[0]["qualitylabel"] == "Unselected"
    assert ci[0]["number_of_spikes"] == 2
    assert ci[0]["EpochStart"] == "epA"
    assert ci[0]["EpochStop"] == "epB"
    # meanshape is NumSamples x NumChannels, the mean across the cluster's spikes.
    np.testing.assert_allclose(np.asarray(ci[0]["meanshape"]), np.full((3, 2), 2.0))
    np.testing.assert_allclose(np.asarray(ci[1]["meanshape"]), np.full((3, 2), 15.0))
    assert ci[1]["number_of_spikes"] == 2


def test_cluster_initializeclusterinfo_empty_epochnames():
    waves = np.ones((2, 1, 2))
    ci = ndi_app_spikesorter.cluster_initializeclusterinfo(
        np.array([1, 1]), waves, {"EpochNames": []}
    )
    assert len(ci) == 1
    assert ci[0]["EpochStart"] == "" and ci[0]["EpochStop"] == ""


# ---------------------------------------------------------------------------
# ndi.util.klustakwik.cluster_spikewaves (needs klustakwik2)
# ---------------------------------------------------------------------------


def _three_blobs(per=40, f=5, seed=0):
    rng = np.random.default_rng(seed)
    centers = [np.zeros(f), np.array([10.0, 10, 0, 0, 0]), np.array([0.0, 0, 10, 10, 0])]
    feats = np.vstack([c + 0.3 * rng.standard_normal((per, f)) for c in centers])
    true = np.repeat([0, 1, 2], per)
    return feats, true


def test_cluster_spikewaves_separates_and_is_one_based():
    pytest.importorskip("klustakwik2")
    from ndi.util.klustakwik import cluster_spikewaves

    feats, true = _three_blobs()
    ids, nclust = cluster_spikewaves(feats, min_clusters=3, max_clusters=8, num_start=3, seed=1)

    assert len(ids) == feats.shape[0]
    assert ids.min() == 1 and ids.max() == nclust  # contiguous 1..K
    assert nclust == 3
    # each recovered cluster is pure (separable blobs)
    purity = sum(np.bincount(true[ids == u]).max() for u in np.unique(ids)) / len(true)
    assert purity > 0.95


def test_cluster_spikewaves_deterministic_with_seed():
    pytest.importorskip("klustakwik2")
    from ndi.util.klustakwik import cluster_spikewaves

    feats, _ = _three_blobs()
    a, _ = cluster_spikewaves(feats, max_clusters=8, num_start=2, seed=7)
    b, _ = cluster_spikewaves(feats, max_clusters=8, num_start=2, seed=7)
    np.testing.assert_array_equal(a, b)


def test_cluster_spikewaves_edge_cases():
    pytest.importorskip("klustakwik2")
    from ndi.util.klustakwik import cluster_spikewaves

    ids, n = cluster_spikewaves(np.empty((0, 5)), seed=1)
    assert ids.shape == (0,) and n == 0
    ids, n = cluster_spikewaves(np.ones((1, 5)), seed=1)
    assert list(ids) == [1] and n == 1


# ---------------------------------------------------------------------------
# End-to-end spike_sort / clusters2neurons against a real session
# ---------------------------------------------------------------------------

SR = 30000.0
S0, S1 = -10, 10  # 21 samples per waveform
NCHAN = 2


def _real_session(tmp_path):
    try:
        from ndi.session.dir import ndi_session_dir
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"ndi_session_dir unavailable: {exc}")
    p = tmp_path / "sess"
    p.mkdir(exist_ok=True)
    try:
        return ndi_session_dir("T", p)
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"could not create ndi_session_dir: {exc}")


class _FakeElement:
    """A timeseries element with a deterministic 2-epoch table.

    Registered as a real ndi.element so it has a real document id (needed by the
    spikewaves dependency and by addMultiple's underlying_element_id).
    """

    EPOCHS = ("ep0", "ep1")

    def __init__(self, session, name="ntrode", reference=1):
        from ndi.element import ndi_element

        self._elem = ndi_element(
            session=session,
            name=name,
            reference=reference,
            type="n-trode",
            direct=False,
            subject_id="subj1",
        )
        session.database_add(self._elem.newdocument())
        self._name = name
        self._reference = reference

    @property
    def id(self):
        return self._elem.id

    @property
    def name(self):
        return self._name

    @property
    def reference(self):
        return self._reference

    @property
    def subject_id(self):
        return self._elem.subject_id

    def epochtable(self, force_rebuild=False):
        from ndi.time.clocktype import ndi_time_clocktype as CT

        et = [
            {"epoch_id": e, "epoch_clock": [CT.DEV_LOCAL_TIME], "t0_t1": [[0.0, 1.0]]}
            for e in self.EPOCHS
        ]
        return et, "hash"


def _archetype_waveforms(labels, rng):
    """Build (21, 2, N) waveforms whose shape is set by the integer label.

    Three clearly distinct archetypes (negative bump on ch0, negative bump on
    ch1, bipolar) so the PCA features separate cleanly.
    """
    s = np.arange(S0, S1 + 1)
    bump = np.exp(-(s**2) / 8.0)
    arch = {
        1: np.stack([-8.0 * bump, -1.0 * bump], axis=1),
        2: np.stack([-1.0 * bump, -8.0 * bump], axis=1),
        3: np.stack([-8.0 * bump, 8.0 * bump], axis=1),
    }
    n = len(labels)
    w = np.zeros((len(s), NCHAN, n))
    for i, lab in enumerate(labels):
        w[:, :, i] = arch[lab] + 0.15 * rng.standard_normal((len(s), NCHAN))
    return w


def _make_extraction_and_spikewaves(session, elem, extraction_name="test"):
    """Create an extraction_parameters doc and per-epoch spikewaves docs.

    Returns (labels_per_spike, spiketimes_per_spike) concatenated in the same
    order loadwaveforms reconstructs (epoch 0 then epoch 1).
    """
    from ndi.app.spikeextractor import ndi_app_spikeextractor

    ext = ndi_app_spikeextractor(session)
    ext_doc = ext.struct2doc(
        "extraction_parameters",
        ndi_app_spikeextractor.default_extraction_parameters(),
        extraction_name,
    )
    session.database_add(ext_doc)

    rng = np.random.default_rng(0)
    waveparams = {"numchannels": NCHAN, "S0": S0, "S1": S1, "samplerate": SR}

    all_labels: list[int] = []
    all_times: list[float] = []
    # 18 spikes per epoch: 6 of each of the 3 clusters, interleaved.
    for epoch in elem.EPOCHS:
        labels = [1, 2, 3] * 6
        rng.shuffle(labels)
        waves = _archetype_waveforms(labels, rng)
        times = np.sort(rng.uniform(0.0, 1.0, size=len(labels)))
        ext._store_spikewaves(elem, epoch, extraction_name, ext_doc, waves, times, waveparams)
        all_labels.extend(labels)
        all_times.extend(times.tolist())
    return ext_doc, np.array(all_labels), np.array(all_times)


def _make_sorting_params(session, sorter, name="test_sort", **overrides):
    params = ndi_app_spikesorter.default_sorting_parameters()
    params.update(
        {
            "graphical_mode": 0,
            "interpolation": 1,
            "num_pca_features": 4,
            "min_clusters": 3,
            "max_clusters": 8,
            "num_start": 3,
        }
    )
    params.update(overrides)
    doc = sorter.struct2doc("sorting_parameters", params, name)
    session.database_add(doc)
    return doc


def test_spike_sort_creates_spike_clusters_document(tmp_path):
    pytest.importorskip("vlt")
    pytest.importorskip("klustakwik2")
    from ndi.query import ndi_query

    session = _real_session(tmp_path)
    elem = _FakeElement(session)
    _ext_doc, labels, _times = _make_extraction_and_spikewaves(session, elem)
    sorter = ndi_app_spikesorter(session)
    _make_sorting_params(session, sorter)

    np.random.seed(0)  # keep the (stochastic) clustering deterministic
    docs = sorter.spike_sort(elem, "test", "test_sort")
    assert len(docs) == 1
    doc = docs[0]

    # Exactly one spike_clusters doc landed in the database.
    found = session.database_search(ndi_query("").isa("spike_clusters"))
    assert len(found) == 1

    # spike_cluster.bin decodes to one uint16 cluster id per spike.
    clusterids, _doc2 = sorter.loaddata_appdoc("spike_clusters", elem, "test", "test_sort")
    n_spikes = labels.size
    assert clusterids.shape == (n_spikes,)
    assert clusterids.min() >= 1

    sc = doc.document_properties["spike_clusters"]
    ci = sc["clusterinfo"]
    # one clusterinfo entry per distinct cluster id; spike counts sum to all spikes.
    assert len(ci) == len({int(c) for c in clusterids})
    assert sum(e["number_of_spikes"] for e in ci) == n_spikes
    # meanshape geometry: 21 samples x 2 channels (interpolation=1).
    assert np.asarray(ci[0]["meanshape"]).shape == (S1 - S0 + 1, NCHAN)
    assert len(sc["waveform_sample_times"]) == (S1 - S0 + 1)
    for e in ci:
        assert e["qualitylabel"] == "Unselected"


def test_spike_sort_idempotent_and_redo(tmp_path):
    pytest.importorskip("vlt")
    pytest.importorskip("klustakwik2")
    from ndi.query import ndi_query

    session = _real_session(tmp_path)
    elem = _FakeElement(session)
    _make_extraction_and_spikewaves(session, elem)
    sorter = ndi_app_spikesorter(session)
    _make_sorting_params(session, sorter)

    np.random.seed(0)  # keep the (stochastic) clustering deterministic
    first = sorter.spike_sort(elem, "test", "test_sort")[0]
    # Second call without redo returns the same document, makes no new ones.
    again = sorter.spike_sort(elem, "test", "test_sort")[0]
    assert again.id == first.id
    assert len(session.database_search(ndi_query("").isa("spike_clusters"))) == 1
    # redo replaces it (still exactly one).
    redone = sorter.spike_sort(elem, "test", "test_sort", redo=True)[0]
    assert redone.id != first.id
    assert len(session.database_search(ndi_query("").isa("spike_clusters"))) == 1


def test_spike_sort_graphical_mode_routes_to_gui(tmp_path, monkeypatch):
    """graphical_mode=1 launches the GUI and persists its curated result.

    The interactive editor is replaced with a stub that returns a canned
    (clusterids, clusterinfo); we assert spike_sort writes those into the
    spike_clusters document with the same layout as the automatic path. (The GUI
    itself is exercised offscreen in tests/test_spikesorter_gui.py.)
    """
    pytest.importorskip("vlt")
    from ndi.query import ndi_query

    session = _real_session(tmp_path)
    elem = _FakeElement(session)
    _ext_doc, labels, _times = _make_extraction_and_spikewaves(session, elem)
    sorter = ndi_app_spikesorter(session)
    _make_sorting_params(session, sorter, name="gui_sort", graphical_mode=1, interpolation=1)

    captured = {}

    def _fake_gui(waves, waveparameters, **kwargs):
        captured["waves_shape"] = np.asarray(waves).shape
        captured["epoch_names"] = kwargs.get("epoch_names")
        n = np.asarray(waves).shape[2]
        # canned 2-cluster curation; one spike left unclassified (NaN).
        ids = np.array([1.0, 2.0] * (n // 2) + [1.0] * (n % 2))
        ids[0] = np.nan
        ci = ndi_app_spikesorter.cluster_initializeclusterinfo(
            np.where(np.isnan(ids), 0, ids),
            np.asarray(waves),
            {"EpochNames": kwargs["epoch_names"]},
        )
        return ids, ci

    import ndi.app.spikesorter_gui as gui_mod

    monkeypatch.setattr(gui_mod, "cluster_spikewaves_gui", _fake_gui)

    docs = sorter.spike_sort(elem, "test", "gui_sort")
    assert len(docs) == 1
    # the GUI received the prepared waveforms + epoch names.
    assert captured["waves_shape"][2] == labels.size
    assert captured["epoch_names"] == list(elem.EPOCHS)
    # exactly one spike_clusters doc; bin decodes with NaN -> 0.
    found = session.database_search(ndi_query("").isa("spike_clusters"))
    assert len(found) == 1
    clusterids, _doc2 = sorter.loaddata_appdoc("spike_clusters", elem, "test", "gui_sort")
    assert clusterids.shape == (labels.size,)
    assert clusterids[0] == 0  # the unclassified spike


def test_graphical_curated_path_creates_neurons(tmp_path, monkeypatch):
    """End-to-end: the GUI's curation logic (ClusterModel) -> neurons.

    Drives the real headless ClusterModel (the same object the PyQt window edits)
    as the editor: it auto-clusters the prepared waveforms with KMeans, labels
    every cluster 'Good', and finalises. spike_sort(graphical_mode=1) writes the
    curated spike_clusters document, and clusters2neurons turns the Good clusters
    into neuron_extracellular documents -- proving the graphical output is
    consumable by the downstream pipeline on a real session/database.
    """
    pytest.importorskip("vlt")
    pytest.importorskip("sklearn")
    from ndi.app.spikesorter_clustermodel import ClusterModel
    from ndi.query import ndi_query

    session = _real_session(tmp_path)
    elem = _FakeElement(session)
    _ext_doc, labels, _times = _make_extraction_and_spikewaves(session, elem)
    sorter = ndi_app_spikesorter(session)
    _make_sorting_params(session, sorter, name="gui_sort", graphical_mode=1, interpolation=1)

    def _curating_gui(waves, waveparameters, **kwargs):
        m = ClusterModel(
            waves,
            epoch_start_samples=kwargs.get("epoch_start_samples"),
            epoch_names=kwargs.get("epoch_names"),
        )
        m.compute_features("pca3")
        m.cluster_all("KMeans", 3, seed=0)  # deterministic 3-way split
        for ci in m.clusterinfo:
            m.set_quality(ci["number"], "Good")
        m.finalize()
        return m.clusterids, m.clusterinfo

    import ndi.app.spikesorter_gui as gui_mod

    monkeypatch.setattr(gui_mod, "cluster_spikewaves_gui", _curating_gui)

    docs = sorter.spike_sort(elem, "test", "gui_sort")
    assert len(docs) == 1
    sc = docs[0].document_properties["spike_clusters"]
    assert len(sc["clusterinfo"]) == 3
    assert all(c["qualitylabel"] == "Good" for c in sc["clusterinfo"])

    created = sorter.clusters2neurons(elem, "gui_sort", "test")
    assert len(created) == 3  # three Good clusters -> three neurons
    ne = session.database_search(ndi_query("").isa("neuron_extracellular"))
    assert len(ne) == 3
    for d in ne:
        props = d.document_properties["neuron_extracellular"]
        assert props["quality_label"] == "Good"
        assert np.asarray(props["mean_waveform"]).shape == (S1 - S0 + 1, NCHAN)


def test_spike_sort_graphical_mode_cancel_writes_nothing(tmp_path, monkeypatch):
    pytest.importorskip("vlt")
    from ndi.query import ndi_query

    session = _real_session(tmp_path)
    elem = _FakeElement(session)
    _make_extraction_and_spikewaves(session, elem)
    sorter = ndi_app_spikesorter(session)
    _make_sorting_params(session, sorter, name="gui_sort", graphical_mode=1, interpolation=1)

    import ndi.app.spikesorter_gui as gui_mod

    monkeypatch.setattr(gui_mod, "cluster_spikewaves_gui", lambda *a, **k: (None, None))

    docs = sorter.spike_sort(elem, "test", "gui_sort")
    assert docs == []
    assert session.database_search(ndi_query("").isa("spike_clusters")) == []


def test_clusters2neurons_unselected_yields_no_neurons(tmp_path):
    pytest.importorskip("vlt")
    pytest.importorskip("klustakwik2")
    from ndi.query import ndi_query

    session = _real_session(tmp_path)
    elem = _FakeElement(session)
    _make_extraction_and_spikewaves(session, elem)
    sorter = ndi_app_spikesorter(session)
    _make_sorting_params(session, sorter)
    np.random.seed(0)  # keep the (stochastic) clustering deterministic
    sorter.spike_sort(elem, "test", "test_sort")

    # A freshly auto-sorted document labels everything 'Unselected' -> no neurons.
    created = sorter.clusters2neurons(elem, "test_sort", "test")
    assert created == []
    assert session.database_search(ndi_query("").isa("neuron_extracellular")) == []


def _author_curated_spike_clusters(session, sorter, elem, ext_doc, labels, times, label_map):
    """Author a spike_clusters document with curated quality labels.

    *label_map* maps 1-based cluster number -> qualitylabel. Cluster ids are the
    per-spike *labels* (already 1..K). Returns the created document.
    """
    from ndi.document import ndi_document

    et, _ = elem.epochtable()
    # epoch start indices (1-based) in the concatenated spike order: 18 per epoch.
    per = labels.size // len(elem.EPOCHS)
    epochinfo = {
        "EpochStartSamples": [1 + i * per for i in range(len(elem.EPOCHS))],
        "EpochNames": list(elem.EPOCHS),
    }
    # Build per-cluster mean shapes from the real waveforms.
    rng = np.random.default_rng(99)
    waves = _archetype_waveforms(list(labels), rng)
    clusterinfo = ndi_app_spikesorter.cluster_initializeclusterinfo(labels, waves, epochinfo)
    for ci in clusterinfo:
        lab = label_map.get(int(ci["number"]))
        if lab:
            ci["qualitylabel"] = lab

    sorting_doc = sorter.find_appdoc("sorting_parameters", "test_sort")[0]
    spike_clusters = {
        "epoch_info": epochinfo,
        "clusterinfo": clusterinfo,
        "waveform_sample_times": list(range(S0, S1 + 1)),
    }
    doc = ndi_document("apps/spikesorter/spike_clusters", **{"spike_clusters": spike_clusters})
    doc = doc.set_session_id(session.id())
    doc = doc.set_dependency_value("element_id", elem.id, error_if_not_found=False)
    doc = doc.set_dependency_value(
        "sorting_parameters_id", sorting_doc.id, error_if_not_found=False
    )
    doc = doc.set_dependency_value("extraction_parameters_id", ext_doc.id, error_if_not_found=False)

    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp()) / "spike_cluster.bin"
    with open(tmp, "wb") as fh:
        fh.write(np.asarray(labels, dtype="<u2").tobytes())
    doc = doc.add_file("spike_cluster.bin", str(tmp))
    session.database_add(doc)
    return doc


def test_clusters2neurons_creates_curated_neurons(tmp_path):
    pytest.importorskip("vlt")
    pytest.importorskip("klustakwik2")
    from ndi.query import ndi_query

    session = _real_session(tmp_path)
    elem = _FakeElement(session)
    ext_doc, labels, times = _make_extraction_and_spikewaves(session, elem)
    sorter = ndi_app_spikesorter(session)
    _make_sorting_params(session, sorter)

    # Curate: cluster 1 -> Good, cluster 2 -> Unselected (skip), cluster 3 -> Excellent.
    _author_curated_spike_clusters(
        session,
        sorter,
        elem,
        ext_doc,
        labels,
        times,
        {1: "Good", 2: "Unselected", 3: "Excellent"},
    )

    created = sorter.clusters2neurons(elem, "test_sort", "test")
    # Two usable clusters -> two neurons.
    assert len(created) == 2

    ne = session.database_search(ndi_query("").isa("neuron_extracellular"))
    assert len(ne) == 2
    labels_seen = sorted(d.document_properties["neuron_extracellular"]["quality_label"] for d in ne)
    assert labels_seen == ["Excellent", "Good"]
    # cluster_index matches the curated cluster numbers (1 and 3).
    idxs = sorted(d.document_properties["neuron_extracellular"]["cluster_index"] for d in ne)
    assert idxs == [1, 3]
    # each neuron_extracellular records a 21x2 mean waveform.
    for d in ne:
        mw = np.asarray(d.document_properties["neuron_extracellular"]["mean_waveform"])
        assert mw.shape == (S1 - S0 + 1, NCHAN)

    # idempotent: re-running without redo creates no duplicates.
    again = sorter.clusters2neurons(elem, "test_sort", "test")
    assert again == []
    assert len(session.database_search(ndi_query("").isa("neuron_extracellular"))) == 2


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
