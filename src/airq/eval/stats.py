"""Significance tests for forecast comparison (spec 4.4, Appendix B).

* Diebold-Mariano with the Harvey-Leybourne-Newbold correction [R24][R25]
* Holm step-down correction for the 12 per-station tests
* paired Wilcoxon over stations, block bootstrap (24 h blocks) for RMSE differences [R13]
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def dm_test(e1: np.ndarray, e2: np.ndarray, h: int) -> tuple[float, float]:
    """DM test of equal squared-error accuracy of forecast 1 vs forecast 2 (two-sided).

    d_t = e1_t^2 - e2_t^2; DM = mean(d) / sqrt(V/T) with V the Newey-West long-run variance
    (Bartlett weights, lag h-1); HLN correction DM* = DM * sqrt((T+1-2h+h(h-1)/T)/T), compared
    with a t distribution with T-1 degrees of freedom. A NEGATIVE statistic means forecast 1 is
    more accurate than forecast 2. Returns (DM*, p-value).
    """
    d = np.asarray(e1, dtype=float) ** 2 - np.asarray(e2, dtype=float) ** 2
    t_len = len(d)
    if t_len < 3:
        return float("nan"), float("nan")
    dbar = d.mean()
    dc = d - dbar
    v = float(np.dot(dc, dc) / t_len)  # gamma_0
    for k in range(1, h):
        gamma_k = float(np.dot(dc[k:], dc[:-k]) / t_len)
        v += 2.0 * (1.0 - k / h) * gamma_k
    if v <= 0:
        return float("nan"), float("nan")
    dm = dbar / np.sqrt(v / t_len)
    hln = np.sqrt((t_len + 1 - 2 * h + h * (h - 1) / t_len) / t_len)
    stat = float(dm * hln)
    p = float(2 * stats.t.sf(abs(stat), df=t_len - 1))
    return stat, p


def holm(pvalues: list[float], alpha: float = 0.05) -> tuple[list[float], list[bool]]:
    """Holm-Bonferroni adjusted p-values and rejection flags (NaN p-values never reject)."""
    p = np.asarray(pvalues, dtype=float)
    m = int(np.sum(~np.isnan(p)))
    order = np.argsort(np.where(np.isnan(p), np.inf, p))
    adj = np.full(len(p), np.nan)
    running = 0.0
    for rank, idx in enumerate(order[:m]):
        running = max(running, (m - rank) * p[idx])
        adj[idx] = min(1.0, running)
    reject = [bool(a <= alpha) if not np.isnan(a) else False for a in adj]
    return [float(a) for a in adj], reject


def wilcoxon_paired(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Paired Wilcoxon signed-rank test (two-sided) on per-station RMSEs."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if np.allclose(x, y):
        return 0.0, 1.0
    res = stats.wilcoxon(x, y, alternative="two-sided")
    return float(res.statistic), float(res.pvalue)


def block_bootstrap_rmse_diff(
    ts: pd.Series, e_ref: np.ndarray, e_mod: np.ndarray, reps: int = 1000, seed: int = 0
) -> dict:
    """95% CI of RMSE_ref - RMSE_model (and of the % improvement) with 24-hour blocks.

    A block is one calendar day across ALL stations (cross-section kept together, serial
    correlation inside the day kept). Days are resampled with replacement.
    """
    day = pd.to_datetime(ts).dt.floor("D").to_numpy()
    codes, _ = pd.factorize(day)
    n_days = codes.max() + 1
    s_ref = np.bincount(codes, weights=np.asarray(e_ref, dtype=float) ** 2, minlength=n_days)
    s_mod = np.bincount(codes, weights=np.asarray(e_mod, dtype=float) ** 2, minlength=n_days)
    cnt = np.bincount(codes, minlength=n_days).astype(float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n_days, size=(reps, n_days))
    n = cnt[idx].sum(axis=1)
    rmse_ref = np.sqrt(s_ref[idx].sum(axis=1) / n)
    rmse_mod = np.sqrt(s_mod[idx].sum(axis=1) / n)
    diff = rmse_ref - rmse_mod
    pct = 100 * diff / rmse_ref
    lo, hi = np.percentile(diff, [2.5, 97.5])
    plo, phi = np.percentile(pct, [2.5, 97.5])
    point = float(np.sqrt(s_ref.sum() / cnt.sum()) - np.sqrt(s_mod.sum() / cnt.sum()))
    return {
        "diff": point,
        "diff_lo": float(lo),
        "diff_hi": float(hi),
        "pct_lo": float(plo),
        "pct_hi": float(phi),
        "n_blocks": int(n_days),
        "reps": reps,
    }
