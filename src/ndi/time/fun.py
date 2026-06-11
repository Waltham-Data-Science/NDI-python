"""ndi.time.fun - trigger-train synchronization helpers.

Port of MATLAB ``ndi.time.fun.syncTriggerTrains`` and
``ndi.time.fun.syncRandomTriggers``: align two independent clocks that recorded
a common digital pulse train, robust to clock drift, partial overlap, and (for
the trigger-train case) a single dropped pulse. Both use quantized inter-pulse
interval "fingerprints" to find candidate alignments cheaply, then validate and
fit a linear model.
"""

from __future__ import annotations

import numpy as np


def _round_half_away(x: np.ndarray) -> np.ndarray:
    """Round half away from zero, matching MATLAB ``round`` (numpy rounds half to
    even). Keeps interval quantization buckets identical to MATLAB at exact
    ``k + 0.5`` boundaries."""
    x = np.asarray(x, dtype=float)
    return np.sign(x) * np.floor(np.abs(x) + 0.5)


def _quantize(intervals: np.ndarray, bucket: float) -> np.ndarray:
    """Quantize intervals into integer buckets (MATLAB-compatible rounding)."""
    return _round_half_away(intervals / bucket).astype(int)


def _fingerprint_key(q: np.ndarray, i: int, f: int) -> str:
    """A comma-joined key for the f quantized intervals starting at index i."""
    return ",".join(str(int(v)) for v in q[i : i + f])


def sync_trigger_trains(
    t1: np.ndarray,
    t2: np.ndarray,
    alignment_tolerance: float = 0.005,
    min_match_rate: float = 0.8,
    fingerprint_size: int = 5,
) -> tuple[float, float]:
    """Synchronize two clocks recording a common pulse train (drift/drop robust).

    Port of MATLAB ``ndi.time.fun.syncTriggerTrains``. Returns ``(shift, scale)``
    such that ``t2 = shift + scale * t1``, or ``(nan, nan)`` if no confident
    alignment is found.

    Args:
        t1, t2: pulse onset times (seconds) from the two devices.
        alignment_tolerance: max allowable jitter (s).
        min_match_rate: fraction of pulses that must align to accept a model.
        fingerprint_size: number of consecutive intervals per hash key.

    Raises:
        ValueError: ``ndi:time:sync:ambiguous`` if multiple distinct
            high-certainty alignments are found (data too periodic).
    """
    t1 = np.asarray(t1, dtype=float).reshape(-1)
    t2 = np.asarray(t2, dtype=float).reshape(-1)
    f = int(fingerprint_size)

    if len(t1) < f or len(t2) < f:
        return float("nan"), float("nan")

    # Standardize: the longer recording is the hashing target. Then invert if
    # needed so the returned model is always t2 = shift + scale * t1.
    if len(t1) >= len(t2):
        s_raw, m_raw = _robust_global_sync(t1, t2, alignment_tolerance, min_match_rate, f)
        if not np.isnan(s_raw) and m_raw != 0:
            return -s_raw / m_raw, 1.0 / m_raw
        return float("nan"), float("nan")
    return _robust_global_sync(t2, t1, alignment_tolerance, min_match_rate, f)


def _robust_global_sync(
    target: np.ndarray, prober: np.ndarray, tol: float, min_match_rate: float, f: int
) -> tuple[float, float]:
    """Return ``(shift, scale)`` such that ``target = shift + scale * prober``."""
    # 1. Hash the target's quantized interval fingerprints. The quantization
    #    bucket is 2*tol so modest drift does not jump the bucket immediately.
    q_target = _quantize(np.diff(target), tol * 2)
    hashmap: dict[str, list[int]] = {}
    for i in range(len(q_target) - f + 1):
        hashmap.setdefault(_fingerprint_key(q_target, i, f), []).append(i)

    # 2. Probe with the prober's fingerprints to collect candidate offsets.
    q_prober = _quantize(np.diff(prober), tol * 2)
    offsets: set[int] = set()
    for i in range(len(q_prober) - f + 1):
        hit = hashmap.get(_fingerprint_key(q_prober, i, f))
        if hit:
            for it in hit:
                offsets.add(it - i)

    # 3. Validate each offset across the whole prober train with a drift-aware
    #    dynamic tolerance, allowing at most one dropped pulse.
    results: list[tuple[float, float, float]] = []  # (shift, scale, score)
    for offset in sorted(offsets):
        idx_p_seed = max(0, -offset)
        idx_t_seed = idx_p_seed + offset
        if idx_t_seed >= len(target) or idx_t_seed < 0:
            continue
        rough_shift = target[idx_t_seed] - prober[idx_p_seed]

        matched_p: list[float] = []
        matched_t: list[float] = []
        missed = 0
        for i in range(len(prober)):
            expected_t = prober[i] + rough_shift
            diffs = np.abs(target - expected_t)
            t_idx = int(np.argmin(diffs))
            val = float(diffs[t_idx])
            dist_from_seed = abs(prober[i] - prober[idx_p_seed])
            dynamic_tol = max(tol * 5, dist_from_seed * 0.001)
            if val <= dynamic_tol:
                matched_p.append(float(prober[i]))
                matched_t.append(float(target[t_idx]))
            else:
                missed += 1

        rate = len(matched_p) / len(prober)
        if rate >= min_match_rate and missed <= 1 and len(matched_p) >= 2:
            scale, shift = np.polyfit(matched_p, matched_t, 1)
            results.append((float(shift), float(scale), rate))

    if not results:
        return float("nan"), float("nan")

    results.sort(key=lambda r: r[2], reverse=True)

    # 4. Ambiguity check: distinct competing offsets with comparable scores.
    best_shift = results[0][0]
    for shift, _scale, score in results[1:]:
        if abs(shift - best_shift) > tol * 10 and score > 0.8 * results[0][2]:
            raise ValueError(
                "ndi:time:sync:ambiguous: found "
                f"{len(results)} distinct global alignments. Data is too periodic."
            )

    return results[0][0], results[0][1]


def sync_random_triggers(
    t1: np.ndarray,
    t2: np.ndarray,
    alignment_tolerance: float = 0.002,
    fingerprint_size: int = 4,
) -> tuple[float, float]:
    """Synchronize two clocks recording the same random trigger sequence.

    Port of MATLAB ``ndi.time.fun.syncRandomTriggers``. Returns ``(shift, scale)``
    such that ``t1 = shift + scale * t2``, or ``(nan, nan)`` if no match is found.
    Optimized for long recordings with partial temporal overlap.

    Args:
        t1, t2: transition times (seconds) from the two devices.
        alignment_tolerance: max jitter (s) to consider pulses a match.
        fingerprint_size: number of consecutive intervals per hash key.
    """
    t1 = np.asarray(t1, dtype=float).reshape(-1)
    t2 = np.asarray(t2, dtype=float).reshape(-1)
    f = int(fingerprint_size)

    if len(t1) <= f or len(t2) <= f:
        return float("nan"), float("nan")

    # Hash the longer-duration recording, probe with the shorter one.
    dur1 = float(t1.max() - t1.min())
    dur2 = float(t2.max() - t2.min())
    if dur1 >= dur2:
        return _hash_sync(t1, t2, alignment_tolerance, f)  # t1 = shift + scale * t2
    s_inv, m_inv = _hash_sync(t2, t1, alignment_tolerance, f)  # t2 = s_inv + m_inv * t1
    if not np.isnan(s_inv) and m_inv != 0:
        return -s_inv / m_inv, 1.0 / m_inv
    return float("nan"), float("nan")


def _hash_sync(target: np.ndarray, prober: np.ndarray, tol: float, f: int) -> tuple[float, float]:
    """Return ``(shift, scale)`` such that ``target = shift + scale * prober``."""
    q_target = _quantize(np.diff(target), tol)
    hashmap: dict[str, int] = {}
    for i in range(len(q_target) - f + 1):
        key = _fingerprint_key(q_target, i, f)
        if key not in hashmap:  # keep the first occurrence (MATLAB behavior)
            hashmap[key] = i

    q_prober = _quantize(np.diff(prober), tol)
    # MATLAB randomizes the probe order purely for expected-time speed; we iterate
    # deterministically — the validated result is identical for unambiguous data.
    for i in range(len(q_prober) - f + 1):
        idx_target = hashmap.get(_fingerprint_key(q_prober, i, f))
        if idx_target is None:
            continue
        p_target = target[idx_target : idx_target + f + 1]
        p_prober = prober[i : i + f + 1]
        seed_scale, seed_shift = np.polyfit(p_prober, p_target, 1)

        # Verify with a further pulse to reject coincidental interval matches.
        if (i + f + 1 < len(prober)) and (idx_target + f + 1 < len(target)):
            test_p = prober[i + f + 1]
            test_t = target[idx_target + f + 1]
            if abs(test_t - (seed_scale * test_p + seed_shift)) > tol:
                continue

        return float(seed_shift), float(seed_scale)

    return float("nan"), float("nan")
