import numpy as np
import pytest

from airq.config import load_config
from airq.perturb.inject import (
    DROPOUT,
    SPIKE,
    STUCK,
    TYPE_CODE,
    apply_perturbation,
    inject,
    robust_sigma,
)

CFG = load_config()["perturb"]


def test_robust_sigma_matches_the_mad_definition_and_ignores_missing():
    x = np.array([1.0, 2.0, 3.0, 4.0, 100.0, np.nan])
    med = np.median([1, 2, 3, 4, 100])
    expected = 1.4826 * np.median(np.abs(np.array([1, 2, 3, 4, 100]) - med))
    assert robust_sigma(x) == pytest.approx(expected)
    assert robust_sigma(np.full(10, 5.0)) == 0.0


def test_spike_adds_k_sigma_to_observed_hours_only():
    v = np.array([10.0, 10.0, np.nan, 10.0, 10.0])
    n = apply_perturbation(v, start=1, duration=3, kind=SPIKE, severity=5, sigma=4.0)
    assert n == 2 and v.tolist()[:2] == [10.0, 30.0] and np.isnan(v[2]) and v[3] == 30.0
    assert v[4] == 10.0  # outside the segment


def test_stuck_freezes_at_the_last_valid_value_before_the_segment():
    v = np.array([5.0, 7.0, np.nan, 9.0, 11.0, 13.0])
    apply_perturbation(v, start=3, duration=3, kind=STUCK, severity=0, sigma=1.0)
    assert v[:2].tolist() == [5.0, 7.0] and np.isnan(v[2])
    assert v[3:].tolist() == [7.0, 7.0, 7.0]  # frozen at 7.0, the last valid value before index 3
    lone = np.array([np.nan, np.nan, 4.0])
    assert apply_perturbation(lone, 2, 1, STUCK, 0, 1.0) == 0  # nothing earlier to freeze at


def test_dropout_makes_the_measurement_missing_and_unknown_type_is_rejected():
    v = np.array([1.0, 2.0, 3.0, 4.0])
    assert apply_perturbation(v, 1, 2, DROPOUT, 0, 1.0) == 2
    assert np.isnan(v[1:3]).all() and v[0] == 1.0 and v[3] == 4.0
    with pytest.raises(ValueError):
        apply_perturbation(v, 0, 1, "gaussian", 1, 1.0)


def _series(n=6000, seed=0):
    return np.abs(np.random.default_rng(seed).normal(80, 30, n)).round()


def test_inject_hits_the_target_rate_never_overlaps_and_only_changes_masked_rows():
    x = _series()
    out, mask, segs = inject(x, robust_sigma(x), CFG, np.random.default_rng(1), lo=1000, hi=5000)
    share = (mask > 0).sum() / 4000
    assert (
        CFG["target_rate"][0] <= share <= CFG["target_rate"][1] + 0.02
    )  # last segment may overshoot
    assert (mask[:1000] == 0).all() and (mask[5000:] == 0).all()  # only inside the window
    assert np.array_equal(out[mask == 0], x[mask == 0], equal_nan=True)  # clean rows untouched
    changed = ~np.isclose(out, x, equal_nan=True)
    assert changed.sum() > 0 and (mask[changed] > 0).all()
    assert {s["type"] for s in segs} <= {SPIKE, STUCK, DROPOUT} and len(segs) >= 5
    ranges = sorted((s["start"], s["start"] + s["duration"]) for s in segs)
    assert all(
        a[1] < b[0] for a, b in zip(ranges, ranges[1:], strict=False)
    )  # gaps between segments


def test_inject_respects_the_configured_durations_and_spike_severities():
    x = _series()
    _, _, segs = inject(x, robust_sigma(x), CFG, np.random.default_rng(2), 0, 6000)
    for s in segs:
        lo, hi = CFG["types"][s["type"]]["dur_h"]
        assert lo <= s["duration"] <= hi
        if s["type"] == SPIKE:
            assert s["severity"] in CFG["types"][SPIKE]["k"]
    assert {TYPE_CODE[s["type"]] for s in segs} == {1, 2, 3}


def test_same_seed_gives_the_same_mask_and_different_seeds_differ():
    x = _series()
    a = inject(x, 30.0, CFG, np.random.default_rng(7), 0, 6000)
    b = inject(x, 30.0, CFG, np.random.default_rng(7), 0, 6000)
    c = inject(x, 30.0, CFG, np.random.default_rng(8), 0, 6000)
    assert np.array_equal(a[1], b[1]) and np.array_equal(a[0], b[0], equal_nan=True)
    assert not np.array_equal(a[1], c[1])


def test_inject_never_modifies_its_input_array():
    x = _series()
    before = x.copy()
    inject(x, 30.0, CFG, np.random.default_rng(3), 0, 6000)
    assert np.array_equal(x, before)
