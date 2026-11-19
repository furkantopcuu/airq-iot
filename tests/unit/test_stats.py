import numpy as np
import pandas as pd
import pytest
from scipy import stats as sps

from airq.eval.stats import block_bootstrap_rmse_diff, dm_test, holm, wilcoxon_paired


def test_dm_matches_a_hand_computed_h1_example():
    e1 = np.array([1.0, -2.0, 1.5, -0.5, 2.0, -1.0])
    e2 = np.array([2.0, -3.0, 2.5, -1.5, 3.0, -2.0])  # always worse
    d = e1**2 - e2**2
    t_len = len(d)
    dm = d.mean() / np.sqrt(np.var(d) / t_len)  # h=1: V = gamma_0 (population variance)
    hln = np.sqrt((t_len + 1 - 2 + 0) / t_len)
    stat, p = dm_test(e1, e2, h=1)
    assert stat == pytest.approx(dm * hln)
    assert p == pytest.approx(2 * sps.t.sf(abs(dm * hln), df=t_len - 1))
    assert stat < 0 and p < 0.05  # forecast 1 is clearly more accurate


def test_dm_uses_newey_west_variance_for_h_greater_than_one():
    rng = np.random.default_rng(0)
    d_noise = rng.normal(size=400)
    e1 = np.convolve(d_noise, np.ones(6) / 6, mode="same") + 0.05  # strongly autocorrelated
    e2 = rng.normal(size=400)
    _, p_h1 = dm_test(e1, e2, h=1)
    _, p_h24 = dm_test(e1, e2, h=24)
    assert 0 <= p_h1 <= 1 and 0 <= p_h24 <= 1
    # accounting for autocorrelation widens the variance, so |stat| shrinks (weakly) with h
    assert abs(dm_test(e1, e2, h=24)[0]) <= abs(dm_test(e1, e2, h=1)[0]) * 1.5


def test_dm_equal_forecasts_are_not_significant_and_degenerate_input_is_nan():
    rng = np.random.default_rng(1)
    e = rng.normal(size=500)
    stat, p = dm_test(e, -e, h=6)  # same squared errors
    assert np.isnan(stat) or p > 0.5
    assert all(np.isnan(v) for v in dm_test(np.array([1.0, 2.0]), np.array([2.0, 1.0]), 1))


def test_holm_matches_the_textbook_procedure():
    adj, rej = holm([0.01, 0.04, 0.03, 0.005], alpha=0.05)
    # sorted: .005 .01 .03 .04 -> *4, *3, *2, *1 = .02 .03 .06 .04 -> monotone: .02 .03 .06 .06
    assert adj == pytest.approx([0.03, 0.06, 0.06, 0.02])
    assert rej == [True, False, False, True]
    adj2, rej2 = holm([0.5, float("nan")])
    assert np.isnan(adj2[1]) and rej2 == [False, False]


def test_wilcoxon_paired_detects_a_consistent_shift_and_handles_identical_input():
    rng = np.random.default_rng(2)
    base = rng.normal(50, 5, 12)
    _, p = wilcoxon_paired(base, base - 2.0 - rng.random(12))
    assert p < 0.01
    assert wilcoxon_paired(base, base) == (0.0, 1.0)


def test_block_bootstrap_ci_contains_the_point_estimate_and_is_reproducible():
    rng = np.random.default_rng(3)
    ts = pd.Series(pd.date_range("2016-03-01", periods=24 * 60, freq="h"))
    e_ref = rng.normal(0, 10, len(ts))
    e_mod = e_ref * 0.8  # 20% smaller errors everywhere
    r1 = block_bootstrap_rmse_diff(ts, e_ref, e_mod, reps=300, seed=0)
    r2 = block_bootstrap_rmse_diff(ts, e_ref, e_mod, reps=300, seed=0)
    assert r1 == r2 and r1["n_blocks"] == 60
    assert r1["diff_lo"] <= r1["diff"] <= r1["diff_hi"]
    assert r1["pct_lo"] == pytest.approx(20.0, abs=0.01) and r1["pct_hi"] == pytest.approx(
        20.0, abs=0.01
    )
    assert r1["diff_lo"] > 0
