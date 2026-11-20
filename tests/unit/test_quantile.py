"""RQ4 building blocks: pinball, coverage, non-crossing, widening, the validation-only fit."""

import numpy as np
import pandas as pd
import pytest

from airq.config import load_config
from airq.eval.metrics import mean_width, pinball
from airq.models.quantile import (
    choose_scale,
    interval_coverage,
    quantile_params,
    rearrange,
    train_quantile,
    widen,
)


def test_pinball_matches_hand_values_and_penalises_the_right_side():
    y = np.array([10.0, 10.0])
    assert pinball(y, np.array([8.0, 12.0]), 0.9) == pytest.approx((0.9 * 2 + 0.1 * 2) / 2)
    assert pinball(y, np.array([8.0, 12.0]), 0.1) == pytest.approx((0.1 * 2 + 0.9 * 2) / 2)
    # an upper quantile punishes under-prediction nine times harder than over-prediction
    assert pinball(y, np.array([9.0, 9.0]), 0.9) == pytest.approx(0.9)
    assert pinball(y, np.array([11.0, 11.0]), 0.9) == pytest.approx(0.1)
    assert pinball(y, y, 0.5) == 0.0


def test_coverage_and_width_ignore_missing_rows():
    y = np.array([1.0, 5.0, 9.0, np.nan])
    lo, hi = np.array([0.0, 0.0, 0.0, 0.0]), np.array([2.0, 4.0, 10.0, 10.0])
    assert interval_coverage(y, lo, hi) == pytest.approx(2 / 3)  # 1 in, 5 out, 9 in, nan skipped
    assert mean_width(lo, hi) == pytest.approx((2 + 4 + 10 + 10) / 4)
    assert np.isnan(interval_coverage(np.array([np.nan]), np.array([0.0]), np.array([1.0])))


def test_rearrange_removes_quantile_crossing():
    q = np.array([[5.0, 3.0, 9.0], [1.0, 2.0, 3.0], [4.0, 8.0, 6.0]])
    out = rearrange(q)
    assert (np.diff(out, axis=1) >= 0).all()
    assert out[0].tolist() == [3.0, 5.0, 9.0] and out[1].tolist() == [1.0, 2.0, 3.0]


def test_widen_scales_around_the_median_and_never_goes_below_zero():
    q10, q50, q90 = np.array([6.0]), np.array([10.0]), np.array([16.0])
    lo, hi = widen(q10, q50, q90, 1.0)
    assert (lo[0], hi[0]) == (6.0, 16.0)
    lo, hi = widen(q10, q50, q90, 2.0)
    assert (lo[0], hi[0]) == (2.0, 22.0)
    lo, hi = widen(q10, q50, q90, 3.0)
    assert lo[0] == 0.0  # PM2.5 cannot be negative


def synthetic(n=20000, sd_true=1.0, sd_model=0.5, seed=0):
    """Observations ~ N(50, sd_true); a model whose 10 / 90 % quantiles assume sd_model."""
    rng = np.random.default_rng(seed)
    y = 50.0 + rng.normal(0.0, sd_true, n)
    z = 1.2816  # normal 10 / 90 % point
    return y, np.full(n, 50.0 - z * sd_model), np.full(n, 50.0), np.full(n, 50.0 + z * sd_model)


def test_a_clearly_too_narrow_interval_is_widened_to_about_the_target():
    y, q10, q50, q90 = synthetic(sd_model=0.5)  # raw coverage ~0.48
    c, info = choose_scale(y, q10, q50, q90)
    assert info["calibrated"] and info["coverage_raw_val"] < 0.6
    assert 1.8 <= c <= 2.2  # true factor is sd_true / sd_model = 2
    assert abs(info["coverage_cal_val"] - 0.8) < 0.01


def test_an_interval_that_is_already_close_is_left_alone():
    y, q10, q50, q90 = synthetic(sd_model=1.0)  # raw coverage ~0.80
    c, info = choose_scale(y, q10, q50, q90)
    assert c == 1.0 and info["calibrated"] is False


def test_the_scale_is_fitted_on_the_rows_it_is_given_only():
    y, q10, q50, q90 = synthetic(sd_model=0.5)
    c_val, _ = choose_scale(y[:10000], q10[:10000], q50[:10000], q90[:10000])
    wild = y.copy()
    wild[10000:] *= 50  # a different "test" half must not influence a fit on the first half
    c_again, _ = choose_scale(wild[:10000], q10[:10000], q50[:10000], q90[:10000])
    assert c_val == c_again


def test_quantile_params_override_only_the_objective_keys():
    p = quantile_params(0.9, {"num_leaves": 31, "lambda_l2": 1.0})
    assert p["objective"] == "quantile" and p["alpha"] == 0.9 and p["metric"] == "quantile"
    assert p["num_leaves"] == 31 and quantile_params(0.1, None)["alpha"] == 0.1


def test_trained_quantiles_are_ordered_and_roughly_calibrated_on_held_out_data():
    cfg = load_config()
    rng = np.random.default_rng(1)
    n = 6000
    x = pd.DataFrame({"a": rng.normal(size=n), "b": rng.normal(size=n)})
    y = 3 * x["a"].to_numpy() + rng.normal(0, 1 + np.abs(x["b"].to_numpy()), n)  # heteroscedastic
    tr, va, te = slice(0, 3500), slice(3500, 4700), slice(4700, n)
    names = ["a", "b"]
    preds = []
    for a in (0.1, 0.5, 0.9):
        model = train_quantile(x[tr], y[tr], x[va], y[va], names, cfg, a, {"num_leaves": 15})
        preds.append(model.predict(x[te][names], num_iteration=model.best_iteration))
    q = rearrange(np.column_stack(preds))
    assert (np.diff(q, axis=1) >= 0).all()
    coverage = interval_coverage(y[te], q[:, 0], q[:, 2])
    assert 0.70 < coverage < 0.90  # nominal 0.80 on data the model never saw
    assert abs(np.mean(y[te] <= q[:, 1]) - 0.5) < 0.06  # the median really is a median
