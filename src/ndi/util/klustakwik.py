"""
ndi.util.klustakwik - automatic spike clustering via KlustaKwik2.

This wraps the ``klustakwik2`` package (a maintained Python port of the masked
KlustaKwik clustering algorithm) so that :mod:`ndi.app.spikesorter` has a working
automatic ("non-graphical") sorting path. The MATLAB ``ndi.app.spikesorter``
automatic path calls ``klustakwik_cluster``, a thin wrapper around the *external*
classic KlustaKwik binary; that binary is not available as a Python library, so
this module uses ``klustakwik2`` instead.

PARITY NOTE (honest): ``klustakwik2`` implements the *masked* KlustaKwik variant.
On fully-dense feature matrices (every PCA feature present for every spike, which
is what :func:`ndi.app.spikesorter._prepare_waveforms_for_sorting` produces) the
masked variant with all features unmasked reduces to a classic-style CEM, but it
is **not bit-identical** to MATLAB's external classic-KlustaKwik binary, and
clustering is stochastic (depends on random starts). Results are in the same
family -- clearly separable units separate -- but cluster *counts and labels*
will differ run-to-run and from MATLAB. Like classic KlustaKwik, the automatic
pass tends to over-split and is intended as the input to a curation/merge step
(the spike-sorter GUI), not as a final answer.

``klustakwik2`` is an OPTIONAL dependency (extra ``[sorting]``); importing this
module does not import it. :func:`cluster_spikewaves` imports it lazily and
raises a clear, actionable error if it is missing.
"""

from __future__ import annotations

from typing import Any

import numpy as np

# Whether the numpy>=2 compatibility shim (below) has been installed. The shim is
# idempotent and installed lazily on first use, so importing this module has no
# side effects on klustakwik2.
_numpy2_compat_installed = False


def _install_numpy2_compat() -> None:
    """Patch klustakwik2 0.2.x for numpy>=2 (``ndarray.tostring`` was removed).

    ``klustakwik2`` 0.2.6 calls the long-deprecated ``ndarray.tostring()`` in
    ``klustakwik2.precomputations.reduce_masks_from_arrays`` (used to lexically
    sort unique mask patterns). numpy 2.0 removed ``tostring``; ``tobytes`` is
    its exact, byte-identical replacement. We swap in a corrected function -- the
    behaviour is unchanged -- at the two module references that hold it
    (``precomputations`` defines it; ``data`` imported it by value at load). This
    is a pure environment-compatibility shim, not an algorithm change.
    """
    global _numpy2_compat_installed
    if _numpy2_compat_installed:
        return

    import klustakwik2.data as _kd
    import klustakwik2.precomputations as _pc

    if hasattr(np.ndarray, "tostring"):
        # numpy still provides tostring; nothing to patch.
        _numpy2_compat_installed = True
        return

    def reduce_masks_from_arrays(Ostart, Oend, I):  # noqa: N803, E741 (match upstream sig)
        # Verbatim port of klustakwik2.precomputations.reduce_masks_from_arrays
        # with ``.tostring()`` -> ``.tobytes()`` (identical bytes). The string is
        # only used as a consistent sort/equality key for mask patterns.
        x = np.arange(len(Ostart))
        x = np.array(sorted(x, key=lambda p: I[Ostart[p] : Oend[p]].tobytes()), dtype=int)
        y = np.empty_like(x)
        y[x] = np.arange(len(x))
        oldstr = None
        new_indices: list[np.ndarray] = []
        start = np.zeros(len(Ostart), dtype=int)
        end = np.zeros(len(Ostart), dtype=int)
        curstart = 0
        curend = 0
        for i, p in enumerate(x):
            curind = I[Ostart[p] : Oend[p]]
            curstr = curind.tobytes()
            if curstr != oldstr:
                new_indices.append(curind)
                oldstr = curstr
                curstart = curend
                curend += len(curind)
            start[i] = curstart
            end[i] = curend
        new_indices = np.hstack(new_indices)
        return new_indices, start[y], end[y]

    _pc.reduce_masks_from_arrays = reduce_masks_from_arrays
    _kd.reduce_masks_from_arrays = reduce_masks_from_arrays
    _numpy2_compat_installed = True


def is_available() -> bool:
    """Return True if ``klustakwik2`` can be imported."""
    try:
        import klustakwik2  # noqa: F401

        return True
    except Exception:
        return False


def _build_raw_sparse_data(features: np.ndarray) -> Any:
    """Build a klustakwik2 ``RawSparseData`` for a dense feature matrix.

    Args:
        features: ``NumSpikes x NumFeatures`` float array. Every feature is
            present for every spike (dense), so all features are "unmasked".

    Returns:
        A ``klustakwik2.RawSparseData`` for the dense, all-unmasked layout.

    Features are normalised per-feature to [0, 1] (mirroring how klustakwik2's
    own ``load_fet_fmask_to_raw`` normalises ``.fet`` files); this puts the
    masked-EM distances on the scale the algorithm expects. Because nothing is
    masked, ``noise_mean``/``noise_variance`` (used only for masked features)
    are never consulted; we still supply the per-feature mean/variance.
    """
    from klustakwik2 import RawSparseData

    features = np.ascontiguousarray(np.asarray(features, dtype=float))
    n, f = features.shape
    vmin = features.min(axis=0)
    vmax = features.max(axis=0)
    vdiff = vmax - vmin
    vdiff[vdiff == 0] = 1.0
    norm = (features - vmin) / vdiff

    flat = norm.ravel()
    masks = np.ones(n * f, dtype=float)
    unmasked = np.tile(np.arange(f), n).astype(int)
    offsets = np.arange(0, n * f + 1, f).astype(int)
    noise_mean = norm.mean(axis=0)
    noise_variance = norm.var(axis=0)
    return RawSparseData(noise_mean, noise_variance, flat, masks, unmasked, offsets)


def cluster_spikewaves(
    features: np.ndarray,
    min_clusters: int = 3,
    max_clusters: int = 10,
    num_start: int = 5,
    *,
    seed: int | None = None,
) -> tuple[np.ndarray, int]:
    """Cluster spike PCA features with KlustaKwik2 (automatic sorting path).

    Python counterpart of the MATLAB ``klustakwik_cluster(features,
    min_clusters, max_clusters, num_start, 0)`` call inside
    ``ndi.app.spikesorter/spike_sort``.

    Args:
        features: ``NumSpikes x NumFeatures`` PCA feature matrix (from
            ``vlt.neuro.spikesorting.spikewaves2pca``).
        min_clusters: advisory lower bound on cluster count. KlustaKwik2's masked
            CEM with cluster deletion does not enforce a hard minimum, so this is
            used only to size the random starting partition; the algorithm may
            settle below it.
        max_clusters: maximum number of clusters (``max_possible_clusters``).
        num_start: number of random restarts; the assignment with the best
            (lowest) KlustaKwik score is kept, mirroring MATLAB's ``num_start``.
        seed: optional base RNG seed for reproducible starting partitions
            (restart ``r`` uses ``seed + r``). ``None`` leaves numpy's global RNG
            untouched (non-deterministic, like the MATLAB sorter).

    Returns:
        ``(clusterids, numclusters)`` where ``clusterids`` is a length-NumSpikes
        ``int`` array of **1-based, contiguous** cluster numbers (1..numclusters)
        -- matching the MATLAB convention used by ``cluster_initializeclusterinfo``
        and the ``spike_cluster.bin`` ``uint16`` layout -- and ``numclusters`` is
        the number of distinct clusters found.

    Raises:
        ImportError: if ``klustakwik2`` is not installed (install the optional
            ``[sorting]`` extra).
    """
    try:
        from klustakwik2 import KK
    except Exception as exc:  # pragma: no cover - exercised only without the dep
        raise ImportError(
            "Automatic spike sorting requires the optional 'klustakwik2' package. "
            "Install it with:  pip install 'ndi[sorting]'  (or directly:  "
            "pip install klustakwik2 --no-build-isolation  -- the package needs "
            "numpy present at build time, so a plain 'pip install klustakwik2' may "
            "fail). Alternatively use the graphical sorting path."
        ) from exc

    _install_numpy2_compat()

    features = np.asarray(features, dtype=float)
    if features.ndim != 2:
        raise ValueError("features must be a NumSpikes x NumFeatures 2-D array")
    n = features.shape[0]
    if n == 0:
        return np.empty((0,), dtype=int), 0
    if n == 1:
        return np.ones((1,), dtype=int), 1

    data = _build_raw_sparse_data(features).to_sparse_data()

    max_c = max(2, int(max_clusters))
    # Start rich (one group per allowed cluster, capped at the spike count) and
    # let the penalty-free CEM settle; experiments show this reliably separates
    # clearly-separated units, where a non-zero BIC penalty tended to over-merge
    # on single-mask dense data.
    k0 = min(max(2, int(max_clusters)), n)

    best_labels: np.ndarray | None = None
    best_score = np.inf
    for r in range(max(1, int(num_start))):
        if seed is not None:
            np.random.seed(int(seed) + r)
        init = np.random.randint(0, k0, size=n)
        kk = KK(
            data,
            max_possible_clusters=max_c,
            penalty_k_log_n=0.0,
            use_noise_cluster=False,
            use_mua_cluster=False,
        )
        score = kk.cluster_from(init)
        labels = np.asarray(kk.clusters, dtype=int)
        if float(score) < best_score:
            best_score = float(score)
            best_labels = labels

    assert best_labels is not None  # num_start >= 1 guarantees one run
    # Relabel to contiguous 1..K in order of first appearance of each cluster id.
    _, inverse = np.unique(best_labels, return_inverse=True)
    clusterids = (inverse + 1).astype(int)
    numclusters = int(clusterids.max()) if clusterids.size else 0
    return clusterids, numclusters
