"""
ndi.app.spikesorter_clustermodel - headless cluster-curation model.

Pure-numpy port of the data operations behind
``vlt.neuro.spikesorting.cluster_spikewaves_gui`` -- the interactive MATLAB
spike-sorter. :class:`ClusterModel` holds the spike waveforms, the per-spike
cluster assignment, and the per-cluster ``clusterinfo`` array, and implements
every cluster edit the GUI offers (cluster-all, merge, split, move-to-front,
relabel quality, set epoch presence, finalize) **without importing Qt**, so the
curation logic is unit-testable headlessly. The Qt widgets in
:mod:`ndi.app.spikesorter_gui` drive an instance of this model and the resulting
``clusterids`` / ``clusterinfo`` are written to the ``spike_clusters`` document
in exactly the layout :meth:`ndi.app.spikesorter.ndi_app_spikesorter.spike_sort`
produces, so :meth:`~ndi.app.spikesorter.ndi_app_spikesorter.clusters2neurons`
consumes a curated result unchanged.

MATLAB equivalent: the command dispatch inside
``+vlt/+neuro/+spikesorting/cluster_spikewaves_gui.m`` (``ReOrderMinToMax``,
``InitClusterInfo`` / ``InitClusterInfoExtra``, ``MakeClusters1toN``, ``MergeBt``,
``SplitCluster``, ``MoveTo1Menu``, ``QualityMenu``, ``DoneBt`` finalisation, and
the ``features`` / ``algorithms`` tables). Unclassified spikes are represented as
``NaN`` cluster ids, exactly as in MATLAB; on export they become ``0`` in the
``uint16`` ``spike_cluster.bin`` (MATLAB ``uint16(NaN) == 0``).

PARITY NOTE: ``cluster_all`` rebuilds ``clusterinfo`` from scratch after a
(re-)clustering (the ``InitClusterInfoExtra`` semantics), rather than MATLAB
``ClusterAllBt``'s append-only ``InitClusterInfo`` which leaves stale mean
shapes/labels on the first clusters. The mean shape is the neuron's
``mean_waveform`` (scientifically load-bearing), so the correct, fresh
recomputation is used; manual edits (merge/split/relabel) still preserve labels
in place exactly as MATLAB does.
"""

from __future__ import annotations

from typing import Any

import numpy as np

# Quality labels, in the MATLAB QualityMenu order (cluster_spikewaves_gui.m).
QUALITY_LABELS = ["Unselected", "Not usable", "Multi-unit", "Good", "Excellent"]

# Default per-cluster draw colours (MATLAB ColorOrder), as 0..1 RGB triples.
DEFAULT_COLOR_ORDER = [
    (0.0, 0.0, 1.0),
    (0.0, 0.5, 0.0),
    (1.0, 0.0, 0.0),
    (0.0, 0.75, 0.75),
    (0.75, 0.0, 0.75),
    (0.75, 0.75, 0.0),
    (0.25, 0.25, 0.25),
]
UNCLASSIFIED_COLOR = (0.5, 0.5, 0.5)
NOT_PRESENT_COLOR = (1.0, 0.5, 0.5)


def points_in_polygon(points_xy: np.ndarray, polygon_xy: np.ndarray) -> np.ndarray:
    """Boolean mask of which 2-D points lie inside a polygon (ray casting).

    A pure-numpy point-in-polygon test (even-odd rule) used by the GUI's lasso
    selection so the geometry is testable without Qt. ``points_xy`` is
    ``(N, 2)`` and ``polygon_xy`` is ``(M, 2)`` (the polygon is treated as
    closed; the last vertex connects back to the first).
    """
    points_xy = np.asarray(points_xy, dtype=float)
    polygon_xy = np.asarray(polygon_xy, dtype=float)
    if points_xy.size == 0 or polygon_xy.shape[0] < 3:
        return np.zeros(points_xy.shape[0], dtype=bool)
    x = points_xy[:, 0]
    y = points_xy[:, 1]
    inside = np.zeros(x.shape[0], dtype=bool)
    xv = polygon_xy[:, 0]
    yv = polygon_xy[:, 1]
    n = polygon_xy.shape[0]
    j = n - 1
    # Horizontal edges (yv[j]==yv[i]) make the crossing test's denominator zero,
    # but for those edges the (yv[i]>y)!=(yv[j]>y) guard is always False, so the
    # NaN/inf they produce is masked out; silence the transient warnings.
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        for i in range(n):
            # edge from vertex j to vertex i; does a rightward ray from (x,y) cross it?
            cond = ((yv[i] > y) != (yv[j] > y)) & (
                x < (xv[j] - xv[i]) * (y - yv[i]) / (yv[j] - yv[i]) + xv[i]
            )
            inside ^= cond
            j = i
    return inside


def spikewaves2Npointfeature(waves: np.ndarray, samplelist: list[int]) -> np.ndarray:
    """Sample spike waveforms at fixed sample offsets (2-point-style feature).

    Port of ``vlt.neuro.spikesorting.spikewaves2Npointfeature``. ``waves`` is
    ``NumSamples x NumChannels x NumSpikes`` and ``samplelist`` is a list of
    **1-based** sample indices. Returns a
    ``(len(samplelist) * NumChannels) x NumSpikes`` feature matrix, with each
    column holding the sampled values on the first channel followed by the
    second, and so on (MATLAB column-major ``reshape``).
    """
    waves = np.asarray(waves, dtype=float)
    idx = np.asarray(samplelist, dtype=int) - 1  # 1-based -> 0-based
    sub = waves[idx, :, :]
    length, channels, spikes = sub.shape
    return sub.reshape(length * channels, spikes, order="F")


def spikewaves2pca(waves: np.ndarray, n: int, rng: Any = None) -> np.ndarray:
    """First ``n`` principal-component scores of spike waveforms.

    Port of ``vlt.neuro.spikesorting.spikewaves2pca``. ``waves`` is
    ``NumSamples x NumChannels x NumSpikes``; ``rng`` is an optional 1-based
    ``[start, stop]`` inclusive sample range. Returns an ``n x NumSpikes``
    feature matrix (PCA scores of the channel-concatenated waveforms, computed
    via the SVD of the mean-centred data -- equivalent to MATLAB ``princomp``).
    """
    waves = np.asarray(waves, dtype=float)
    if rng is not None:
        waves = waves[int(rng[0]) - 1 : int(rng[1]), :, :]
    s, c, k = waves.shape
    flat = waves.transpose(2, 1, 0).reshape(k, c * s)
    centered = flat - flat.mean(axis=0)
    u, sv, _vh = np.linalg.svd(centered, full_matrices=False)
    scores = u * sv  # (k, min(k, c*s))
    n = int(min(n, scores.shape[1]))
    return scores[:, :n].T


class ClusterModel:
    """Headless model of an in-progress spike clustering.

    Attributes:
        waves: ``NumSamples x NumChannels x NumSpikes`` waveform array.
        clusterids: length-NumSpikes float array of cluster numbers; ``NaN`` for
            unclassified spikes (MATLAB convention).
        clusterinfo: list of per-cluster dicts (``number`` str, ``qualitylabel``,
            ``number_of_spikes``, ``meanshape`` nested list, ``EpochStart`` /
            ``EpochStop`` epoch ids), aligned with the cluster numbering.
        epoch_names: epoch ids, in recording order.
        epoch_start_samples: 1-based spike index that begins each epoch (the
            ``EpochStartSamples`` from ``loadwaveforms``).
        wavetimes: optional length-NumSpikes spike-time array.
        wavesamples: optional sample-time axis for the waveforms (the
            ``waveform_sample_times`` written to the ``spike_clusters`` doc).
        npoint_samplelist: 1-based sample offsets for the 2-point feature.
        pca_range: 1-based ``[start, stop]`` sample range for the PCA feature.
        features: the most recently computed ``NumSpikes x NumFeatures`` matrix.
    """

    def __init__(
        self,
        waves: np.ndarray,
        clusterids: np.ndarray | None = None,
        clusterinfo: list[dict[str, Any]] | None = None,
        *,
        wavetimes: np.ndarray | None = None,
        epoch_start_samples: list[int] | None = None,
        epoch_names: list[str] | None = None,
        wavesamples: np.ndarray | None = None,
        npoint_samplelist: list[int] | None = None,
        pca_range: list[int] | None = None,
        color_order: list[tuple[float, float, float]] | None = None,
    ):
        waves = np.asarray(waves, dtype=float)
        if waves.ndim != 3:
            raise ValueError("waves must be NumSamples x NumChannels x NumSpikes (3-D)")
        self.waves = waves
        n_spikes = waves.shape[2]

        if clusterids is None:
            self.clusterids = np.full(n_spikes, np.nan)
        else:
            ids = np.asarray(clusterids, dtype=float).ravel()
            if ids.size < n_spikes:  # pad missing assignments with NaN (MATLAB)
                ids = np.concatenate([ids, np.full(n_spikes - ids.size, np.nan)])
            self.clusterids = ids[:n_spikes].copy()

        self.epoch_names = list(epoch_names) if epoch_names else ["Epoch1"]
        self.epoch_start_samples = (
            [int(x) for x in epoch_start_samples] if epoch_start_samples else [1]
        )
        if len(self.epoch_start_samples) != len(self.epoch_names):
            raise ValueError("epoch_start_samples and epoch_names must have equal length")

        self.wavetimes = None if wavetimes is None else np.asarray(wavetimes, dtype=float).ravel()
        self.wavesamples = (
            None if wavesamples is None else np.asarray(wavesamples, dtype=float).ravel()
        )
        self.color_order = list(color_order) if color_order else list(DEFAULT_COLOR_ORDER)

        n = self.n_samples
        if npoint_samplelist:
            self.npoint_samplelist = [int(x) for x in npoint_samplelist]
        else:
            # MATLAB: [ (N/2 - mod(N,2)) round(5/6 * N) ]
            self.npoint_samplelist = [int(n // 2 - (n % 2)) or 1, int(round((5 / 6) * n))]
        if pca_range:
            self.pca_range = [int(pca_range[0]), int(pca_range[1])]
        else:
            self.pca_range = [int(round(8 / 24 * n)), int(round(22 / 24 * n))]
        self._clamp_feature_params()

        self.features: np.ndarray | None = None

        self.clusterinfo = [dict(c) for c in clusterinfo] if clusterinfo else []
        if not self.clusterinfo:
            # MATLAB Main: if there are NaN ids, ensure a NaN clusterinfo exists;
            # then InitClusterInfo populates the rest.
            self.init_cluster_info(rebuild=True)

    # ------------------------------------------------------------------
    # geometry helpers
    # ------------------------------------------------------------------

    @property
    def n_samples(self) -> int:
        return int(self.waves.shape[0])

    @property
    def n_channels(self) -> int:
        return int(self.waves.shape[1])

    @property
    def n_spikes(self) -> int:
        return int(self.waves.shape[2])

    def _clamp_feature_params(self) -> None:
        n = self.n_samples
        if n <= 0:
            return
        self.pca_range[0] = min(max(1, self.pca_range[0]), n)
        self.pca_range[1] = min(max(self.pca_range[0], self.pca_range[1]), n)
        self.npoint_samplelist = [min(max(1, x), n) for x in self.npoint_samplelist]

    # ------------------------------------------------------------------
    # cluster-number bookkeeping
    # ------------------------------------------------------------------

    def unique_clusters(self) -> list[float]:
        """Sorted finite cluster numbers, with a single trailing ``NaN`` if any.

        Mirrors MATLAB ``clusters = unique(ud.clusterids)`` followed by the
        "keep only one NaN" trim used throughout ``cluster_spikewaves_gui``.
        """
        ids = self.clusterids
        finite = np.unique(ids[~np.isnan(ids)])
        out: list[float] = [float(v) for v in finite]
        if np.isnan(ids).any():
            out.append(float("nan"))
        return out

    @staticmethod
    def _is_nan_number(number: Any) -> bool:
        if isinstance(number, str):
            return number.strip().lower() == "nan"
        try:
            return bool(np.isnan(float(number)))
        except (TypeError, ValueError):
            return False

    def _indices_of_value(self, value: float) -> np.ndarray:
        if np.isnan(value):
            return np.flatnonzero(np.isnan(self.clusterids))
        return np.flatnonzero(self.clusterids == value)

    def _indices_of_number(self, number: Any) -> np.ndarray:
        if self._is_nan_number(number):
            return np.flatnonzero(np.isnan(self.clusterids))
        return np.flatnonzero(self.clusterids == float(int(number)))

    def _meanshape(self, indices: np.ndarray) -> np.ndarray:
        if indices.size == 0:
            return np.zeros((self.n_samples, self.n_channels))
        return np.nanmean(self.waves[:, :, indices], axis=2)

    def _info_index_for_number(self, number: Any) -> int | None:
        target = "NaN" if self._is_nan_number(number) else str(int(number))
        for i, ci in enumerate(self.clusterinfo):
            if str(ci.get("number")) == target:
                return i
        return None

    def _make_info(self, value: float, indices: np.ndarray) -> dict[str, Any]:
        number = "NaN" if np.isnan(value) else str(int(value))
        return {
            "number": number,
            "qualitylabel": "Unselected",
            "number_of_spikes": int(indices.size),
            "meanshape": np.asarray(self._meanshape(indices), dtype=float).tolist(),
            "EpochStart": self.epoch_names[0],
            "EpochStop": self.epoch_names[-1],
        }

    # ------------------------------------------------------------------
    # cluster-info construction / renumbering (faithful command ports)
    # ------------------------------------------------------------------

    def init_cluster_info(self, *, rebuild: bool = False) -> None:
        """Build per-cluster ``clusterinfo`` entries.

        ``rebuild=True`` is MATLAB ``InitClusterInfoExtra`` -- start over and
        create a fresh entry (count + mean shape + ``Unselected``) for every
        current cluster. ``rebuild=False`` is MATLAB ``InitClusterInfo`` --
        append entries only for clusters that do not yet have one, preserving
        existing labels/epochs.
        """
        clusters = self.unique_clusters()
        if rebuild:
            self.clusterinfo = []
            for value in clusters:
                self.clusterinfo.append(self._make_info(value, self._indices_of_value(value)))
            return
        for i, value in enumerate(clusters):
            if i >= len(self.clusterinfo):
                self.clusterinfo.append(self._make_info(value, self._indices_of_value(value)))

    def reorder_min_to_max(self) -> None:
        """Renumber clusters 1..K in order of ascending mean-waveform minimum.

        MATLAB ``ReOrderMinToMax``: the cluster with the most negative mean
        sample becomes cluster 1, and so on. NaN spikes are left untouched.
        """
        clusters = [c for c in self.unique_clusters() if not np.isnan(c)]
        if not clusters:
            return
        inds_here = [self._indices_of_value(c) for c in clusters]
        minvalues = [float(np.min(self._meanshape(idx))) for idx in inds_here]
        order = np.argsort(minvalues, kind="stable")
        new_ids = self.clusterids.copy()
        for new_number, src in enumerate(order, start=1):
            new_ids[inds_here[src]] = new_number
        self.clusterids = new_ids

    def make_clusters_1_to_n(self) -> None:
        """Renumber clusters to a contiguous 1..N and align ``clusterinfo``.

        MATLAB ``MakeClusters1toN``: relabels each distinct cluster id (in
        ``unique`` order, a single NaN last) to its 1-based position, sets each
        ``clusterinfo(i).number`` to that position, and trims a trailing empty
        ``clusterinfo`` entry. As in MATLAB, a trailing NaN cluster is folded
        into the contiguous numbering here.
        """
        clusters = self.unique_clusters()
        inds = [self._indices_of_value(c) for c in clusters]
        for i, idx in enumerate(inds):
            self.clusterids[idx] = i + 1
            if i >= len(self.clusterinfo):
                self.clusterinfo.append(self._make_info(float(i + 1), idx))
            else:
                self.clusterinfo[i]["number"] = str(i + 1)
        if len(self.clusterinfo) > len(clusters):
            self.clusterinfo = self.clusterinfo[: len(clusters)]

    # ------------------------------------------------------------------
    # feature computation
    # ------------------------------------------------------------------

    def compute_features(self, kind: str = "pca3") -> np.ndarray:
        """Compute and store the ``NumSpikes x NumFeatures`` feature matrix.

        ``kind`` is ``'2points'`` (samples at ``npoint_samplelist``) or
        ``'pca3'`` (first 3 PCA scores over ``pca_range``), matching the two
        entries of the MATLAB ``features`` table.
        """
        if kind == "2points":
            feats = spikewaves2Npointfeature(self.waves, self.npoint_samplelist).T
        elif kind == "pca3":
            feats = spikewaves2pca(self.waves, 3, self.pca_range).T
        else:
            raise ValueError(f"unknown feature kind {kind!r} (expected '2points' or 'pca3')")
        self.features = np.asarray(feats, dtype=float)
        return self.features

    # ------------------------------------------------------------------
    # clustering algorithms (ClusterAllBt)
    # ------------------------------------------------------------------

    def cluster_all(
        self,
        algorithm: str = "KlustaKwik",
        clusters_spec: Any = (2, 4),
        *,
        feature_kind: str = "pca3",
        seed: int | None = None,
    ) -> None:
        """Run an automatic clustering on the current features, then tidy up.

        MATLAB ``ClusterAllBt`` -> ``ReOrderMinToMax`` -> ``InitClusterInfo`` ->
        ``MakeClusters1toN``. ``algorithm`` is ``'KlustaKwik'`` (``clusters_spec``
        = ``[min, max]``) or ``'KMeans'`` (``clusters_spec`` = ``k``).

        Raises:
            ImportError: if the algorithm's optional backend is not installed
                (``klustakwik2`` for KlustaKwik, ``scikit-learn`` for KMeans).
        """
        if self.features is None:
            self.compute_features(feature_kind)
        feats = self.features
        spec = np.atleast_1d(np.asarray(clusters_spec)).ravel()

        algo = algorithm.lower()
        if algo == "klustakwik":
            from ..util.klustakwik import cluster_spikewaves

            min_c = int(spec[0])
            max_c = int(spec[1]) if spec.size > 1 else int(spec[0])
            ids, _n = cluster_spikewaves(
                feats, min_clusters=min_c, max_clusters=max_c, num_start=10, seed=seed
            )
            self.clusterids = np.asarray(ids, dtype=float)
        elif algo == "kmeans":
            try:
                from sklearn.cluster import KMeans
            except Exception as exc:  # pragma: no cover - exercised only without sklearn
                raise ImportError(
                    "KMeans clustering requires scikit-learn (pip install scikit-learn)."
                ) from exc
            k = int(spec[0])
            km = KMeans(n_clusters=k, n_init=10, random_state=seed)
            self.clusterids = (km.fit_predict(feats) + 1).astype(float)
        else:
            raise ValueError(f"unknown algorithm {algorithm!r} (expected 'KlustaKwik' or 'KMeans')")

        self.reorder_min_to_max()
        self.init_cluster_info(rebuild=True)
        self.make_clusters_1_to_n()

    # ------------------------------------------------------------------
    # manual edits (MergeBt / SplitCluster / MoveTo1Menu / QualityMenu / Epochs)
    # ------------------------------------------------------------------

    def merge(self, number_a: Any, number_b: Any) -> None:
        """Merge cluster ``number_b`` into ``number_a`` (MATLAB ``MergeBt``).

        The lower-numbered cluster absorbs the higher-numbered one (NaN counts as
        higher), the absorbed ``clusterinfo`` entry is removed, and the surviving
        cluster's count + mean shape are recomputed. Then the clustering is
        renumbered 1..N.

        Raises:
            ValueError: if either cluster cannot be found, or there is only one
                cluster to merge.
        """
        va = float("nan") if self._is_nan_number(number_a) else float(int(number_a))
        vb = float("nan") if self._is_nan_number(number_b) else float(int(number_b))
        # lower number first; NaN (via the not-less comparison) sorts last.
        if not np.isnan(va) and not np.isnan(vb) and va > vb:
            va, vb = vb, va
        if np.isnan(va) and not np.isnan(vb):
            va, vb = vb, va  # keep the finite cluster as the survivor

        loc1 = self._info_index_for_number("NaN" if np.isnan(va) else int(va))
        loc2 = self._info_index_for_number("NaN" if np.isnan(vb) else int(vb))
        if loc1 is None or loc2 is None:
            raise ValueError("merge: both clusters must exist")
        if loc1 == loc2:
            raise ValueError("merge: cannot merge a cluster with itself")

        self.clusterids[self._indices_of_value(vb)] = va
        del self.clusterinfo[loc2]
        loc1 = self._info_index_for_number("NaN" if np.isnan(va) else int(va))
        new_idx = self._indices_of_value(va)
        assert loc1 is not None
        self.clusterinfo[loc1]["number_of_spikes"] = int(new_idx.size)
        self.clusterinfo[loc1]["meanshape"] = np.asarray(self._meanshape(new_idx)).tolist()
        self.make_clusters_1_to_n()

    def split_cluster(self, parent_number: Any, indexes: np.ndarray) -> None:
        """Move ``indexes`` out of ``parent_number`` into a new cluster.

        MATLAB ``SplitCluster``: clones the parent's ``clusterinfo`` entry as a
        new (Unselected) cluster numbered ``len(clusterinfo)+1``, reassigns the
        given spikes to it, recomputes both clusters' counts + mean shapes
        (dropping the parent's entry if it is emptied), and renumbers 1..N.

        Args:
            parent_number: the cluster the spikes currently belong to.
            indexes: 0-based spike indices to move into the new cluster.
        """
        indexes = np.asarray(indexes, dtype=int).ravel()
        if indexes.size == 0:
            return
        parent_loc = self._info_index_for_number(parent_number)
        if parent_loc is None:
            raise ValueError("split_cluster: parent cluster not found")

        new_number = len(self.clusterinfo) + 1
        new_info = dict(self.clusterinfo[parent_loc])
        new_info["number"] = str(new_number)
        new_info["qualitylabel"] = "Unselected"
        self.clusterids[indexes] = new_number
        new_info["number_of_spikes"] = int(indexes.size)
        new_info["meanshape"] = np.asarray(self._meanshape(indexes)).tolist()
        self.clusterinfo.append(new_info)

        parent_idx = self._indices_of_number(parent_number)
        if parent_idx.size == 0:
            del self.clusterinfo[parent_loc]
        else:
            self.clusterinfo[parent_loc]["number_of_spikes"] = int(parent_idx.size)
            self.clusterinfo[parent_loc]["meanshape"] = np.asarray(
                self._meanshape(parent_idx)
            ).tolist()
        self.make_clusters_1_to_n()

    def move_to_front(self, number: Any) -> None:
        """Make cluster ``number`` cluster 1, shifting the others down.

        MATLAB ``MoveTo1Menu``: rotates the selected cluster to position 1 and
        renumbers ``clusterinfo`` to the new 1..N order.
        """
        finite = [c for c in self.unique_clusters() if not np.isnan(c)]
        target = None if self._is_nan_number(number) else float(int(number))
        if target is None or target not in finite:
            return
        v = finite.index(target) + 1  # 1-based position
        ids = self.clusterids
        ids[ids == finite[v - 1]] = 0  # temporary holding value
        for i in range(v - 1, -1, -1):  # MATLAB: for i=v-1:-1:0
            src = finite[i - 1] if i > 0 else 0  # finite[i-1] is the (i)th, 1-based
            ids[ids == src] = finite[i]  # finite[i] is the (i+1)th, 1-based
        # reorder clusterinfo: selected entry to the front, renumber 1..N.
        moved = self.clusterinfo.pop(v - 1)
        self.clusterinfo.insert(0, moved)
        for i in range(len(self.clusterinfo)):
            self.clusterinfo[i]["number"] = str(i + 1)

    def set_quality(self, number: Any, label: str) -> None:
        """Set the quality label of cluster ``number`` (MATLAB ``QualityMenu``)."""
        if label not in QUALITY_LABELS:
            raise ValueError(f"unknown quality label {label!r}; expected one of {QUALITY_LABELS}")
        loc = self._info_index_for_number(number)
        if loc is None:
            raise ValueError(f"set_quality: cluster {number} not found")
        self.clusterinfo[loc]["qualitylabel"] = label

    def set_epochs(self, number: Any, epoch_start: str, epoch_stop: str) -> None:
        """Set the present-from/present-to epoch ids of cluster ``number``."""
        if epoch_start not in self.epoch_names or epoch_stop not in self.epoch_names:
            raise ValueError("set_epochs: epoch ids must be members of epoch_names")
        loc = self._info_index_for_number(number)
        if loc is None:
            raise ValueError(f"set_epochs: cluster {number} not found")
        self.clusterinfo[loc]["EpochStart"] = epoch_start
        self.clusterinfo[loc]["EpochStop"] = epoch_stop

    # ------------------------------------------------------------------
    # epoch / visibility helpers (samplesinepochs)
    # ------------------------------------------------------------------

    def _samples_in_epochs(
        self, indices: np.ndarray, epoch_start: int, epoch_stop: int
    ) -> tuple[np.ndarray, np.ndarray]:
        """Split 0-based spike ``indices`` by epoch membership.

        Port of ``vlt.signal.samplesinepochs``: ``epoch_start`` / ``epoch_stop``
        are 1-based epoch numbers; a spike at 0-based index ``j`` has 1-based
        "sample number" ``j + 1`` and is *in* the range when
        ``start[epoch_start] <= j+1 < start[epoch_stop+1]``. Returns
        ``(inside, outside)`` index arrays.
        """
        indices = np.asarray(indices, dtype=int).ravel()
        if indices.size == 0:
            return indices, indices
        starts = list(self.epoch_start_samples) + [np.inf]
        lo = starts[epoch_start - 1]
        hi = starts[epoch_stop]  # start of epoch_stop+1
        sample_numbers = indices + 1
        mask = (sample_numbers >= lo) & (sample_numbers < hi)
        return indices[mask], indices[~mask]

    def _epoch_number(self, epoch_id: str, default: int) -> int:
        try:
            return self.epoch_names.index(epoch_id) + 1
        except ValueError:
            return default

    def visible_indices(
        self, view_start: int = 1, view_stop: int | None = None, indices: np.ndarray | None = None
    ) -> np.ndarray:
        """Spike indices visible in the epoch view window (MATLAB ``FindVisibleSpikes``)."""
        if view_stop is None:
            view_stop = len(self.epoch_names)
        if indices is None:
            indices = np.arange(self.n_spikes)
        inside, _ = self._samples_in_epochs(indices, view_start, view_stop)
        return inside

    def present_indices(self, number: Any, indices: np.ndarray | None = None) -> np.ndarray:
        """Spikes of cluster ``number`` that are 'present' in its epoch range."""
        loc = self._info_index_for_number(number)
        if indices is None:
            indices = self._indices_of_number(number)
        if loc is None:
            return np.asarray(indices, dtype=int)
        ci = self.clusterinfo[loc]
        start = self._epoch_number(ci.get("EpochStart", self.epoch_names[0]), 1)
        stop = self._epoch_number(ci.get("EpochStop", self.epoch_names[-1]), len(self.epoch_names))
        inside, _ = self._samples_in_epochs(indices, start, stop)
        return inside

    # ------------------------------------------------------------------
    # finalisation (DoneBt) + export
    # ------------------------------------------------------------------

    def all_quality_assigned(self) -> bool:
        """True if no cluster is still labelled ``'Unselected'`` (DoneBt gate)."""
        return all(ci.get("qualitylabel") != "Unselected" for ci in self.clusterinfo)

    def finalize(self) -> None:
        """Apply the MATLAB ``DoneBt`` cleanup before returning a result.

        For every cluster, spikes that fall outside the cluster's
        ``EpochStart``..``EpochStop`` window are marked ``NaN`` (not present),
        and the cluster's count + mean shape are recomputed over the present
        spikes. If any spikes ended up ``NaN`` and there is no ``'NaN'``
        ``clusterinfo`` entry, one is appended.
        """
        for ci in self.clusterinfo:
            number = ci["number"]
            indices = self._indices_of_number(number)
            start = self._epoch_number(ci.get("EpochStart", self.epoch_names[0]), 1)
            stop = self._epoch_number(
                ci.get("EpochStop", self.epoch_names[-1]), len(self.epoch_names)
            )
            present, not_present = self._samples_in_epochs(indices, start, stop)
            self.clusterids[not_present] = np.nan
            ci["number_of_spikes"] = int(present.size)
            ci["meanshape"] = np.asarray(self._meanshape(present)).tolist()
        if np.isnan(self.clusterids).any():
            if self._info_index_for_number("NaN") is None:
                self.clusterinfo.append(
                    self._make_info(float("nan"), np.flatnonzero(np.isnan(self.clusterids)))
                )

    def clusterids_for_export(self) -> np.ndarray:
        """Per-spike cluster ids as ``uint16`` for ``spike_cluster.bin``.

        ``NaN`` (unclassified) maps to ``0``, matching MATLAB ``uint16(NaN)``.
        """
        ids = self.clusterids.copy()
        ids[np.isnan(ids)] = 0
        return ids.astype("<u2")

    def epoch_info(self) -> dict[str, Any]:
        """The ``epoch_info`` block for the ``spike_clusters`` document."""
        return {
            "EpochStartSamples": list(self.epoch_start_samples),
            "EpochNames": list(self.epoch_names),
        }

    def color_for_position(self, position: int, is_nan: bool = False) -> tuple[float, float, float]:
        """Draw colour for the cluster at 1-based menu ``position``."""
        if is_nan:
            return UNCLASSIFIED_COLOR
        return self.color_order[(position - 1) % len(self.color_order)]
