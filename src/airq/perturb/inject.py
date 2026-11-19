"""Synthetic faulty-sensor inputs (spec 6.2): spike, stuck, dropout.

Names follow the fault taxonomies of Ni et al. [R22] and Sharma et al. [R21]. These faults are
SYNTHETIC and are used only to measure how much faulty INPUT degrades the forecast and how much the
edge validation recovers (RQ3b). They are not a fault-detection benchmark (out of scope, 1.5).
The same `apply_perturbation` is used by the live Senaryo Kontrol `perturb` mode.
"""

from __future__ import annotations

import numpy as np

SPIKE, STUCK, DROPOUT = "spike", "stuck", "dropout"
TYPES = (SPIKE, STUCK, DROPOUT)
TYPE_CODE = {SPIKE: 1, STUCK: 2, DROPOUT: 3}


def robust_sigma(values: np.ndarray) -> float:
    """sigma_s = 1.4826 * MAD of the observed values (fit on TRAIN only by the caller)."""
    v = np.asarray(values, dtype=float)
    v = v[~np.isnan(v)]
    return float(1.4826 * np.median(np.abs(v - np.median(v))))


def apply_perturbation(
    values: np.ndarray, start: int, duration: int, kind: str, severity: float, sigma: float
) -> int:
    """Corrupt values[start:start+duration] IN PLACE; returns the number of hours changed.

    spike:   x + severity * sigma   (severity = k in {3, 5, 8})
    stuck:   frozen at the last valid value before `start` (no earlier value -> nothing is done)
    dropout: NaN (measurement missing)
    Missing hours stay missing (a missing reading cannot be spiked or frozen).
    """
    end = min(start + duration, len(values))
    if start < 0 or start >= end:
        return 0
    seg = slice(start, end)
    if kind == SPIKE:
        obs = ~np.isnan(values[seg])
        values[seg][obs] += severity * sigma
        return int(obs.sum())
    if kind == STUCK:
        prev = np.flatnonzero(~np.isnan(values[:start]))
        if len(prev) == 0:
            return 0
        frozen = values[prev[-1]]
        obs = ~np.isnan(values[seg])
        values[seg][obs] = frozen
        return int(obs.sum())
    if kind == DROPOUT:
        changed = int((~np.isnan(values[seg])).sum())
        values[seg] = np.nan
        return changed
    raise ValueError(f"unknown perturbation type {kind!r}")


def inject(
    values: np.ndarray,
    sigma: float,
    cfg_perturb: dict,
    rng: np.random.Generator,
    lo: int = 0,
    hi: int | None = None,
) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """Inject faults into rows [lo, hi) of ONE station's series.

    Segments of random type/duration (config `perturb.types`) are placed without overlap until the
    corrupted share reaches a target drawn from `perturb.target_rate`. The target (y) is never
    touched: callers corrupt model INPUTS only. Returns (perturbed copy, mask, segments) where
    mask holds 0 (clean) or the type code (1 spike, 2 stuck, 3 dropout) per row.
    """
    hi = len(values) if hi is None else hi
    out = np.asarray(values, dtype=float).copy()
    mask = np.zeros(len(out), dtype=np.int8)
    segments: list[dict] = []
    span = hi - lo
    target = rng.uniform(*cfg_perturb["target_rate"])
    corrupted, tries = 0, 0
    types = cfg_perturb["types"]
    while corrupted < target * span and tries < 5000:
        tries += 1
        kind = TYPES[int(rng.integers(len(TYPES)))]
        d_lo, d_hi = types[kind]["dur_h"]
        dur = int(rng.integers(d_lo, d_hi + 1))
        start = int(rng.integers(lo, max(lo + 1, hi - dur)))
        if mask[max(lo, start - 1) : start + dur + 1].any():  # keep a clean gap between segments
            continue
        k = float(rng.choice(types[kind]["k"])) if kind == SPIKE else 0.0
        changed = apply_perturbation(out, start, dur, kind, k, sigma)
        if changed == 0:
            continue
        mask[start : start + dur] = TYPE_CODE[kind]
        segments.append({"type": kind, "start": start, "duration": dur, "severity": k})
        corrupted += dur
    return out, mask, segments
