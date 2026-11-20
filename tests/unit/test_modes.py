"""Senaryo Kontrol device modes (spec 9.2, test 11): pure logic, no broker."""

import numpy as np
import pandas as pd
import pytest

from airq.devices.modes import InterventionSet
from airq.iot.schemas import Command
from airq.perturb.inject import apply_perturbation

T0 = pd.Timestamp("2016-03-01 00:00")


def cmd(mode, params=None, duration_h=None, variables=("pm25",), **kw):
    return Command(
        cmd_id=f"c-{mode}", issued_at="2016-03-01T00:00:00", target="Dongsi",
        variables=list(variables), mode=mode, params=params or {}, duration_h=duration_h, **kw,
    )  # fmt: skip


def run(iv, hours, base=100.0, pm10=130.0, start=0):
    """Apply the set hour by hour to a constant recorded reading; returns [(pm25, pm10)]."""
    out = []
    for h in range(start, start + hours):
        r = iv.apply(T0 + pd.Timedelta(hours=h), {"pm25": base, "pm10": pm10})
        out.append((r["pm25"], r["pm10"]))
    return out


def test_replay_is_the_default_and_changes_nothing():
    iv = InterventionSet()
    assert run(iv, 3) == [(100.0, 130.0)] * 3


def test_manual_pins_the_value_for_the_duration_then_returns_to_replay():
    iv = InterventionSet()
    run(iv, 2)
    assert iv.add(cmd("manual", {"value": 250}, duration_h=3)) is None
    got = [p for p, _ in run(iv, 6, start=2)]
    assert got == [250.0, 250.0, 250.0, 100.0, 100.0, 100.0]  # 3 h, then recorded data again
    assert iv.count() == 0  # expired


def test_offset_and_scale_modify_the_recorded_value_until_reset():
    iv = InterventionSet()
    iv.add(cmd("offset", {"delta": 40}))
    assert [p for p, _ in run(iv, 3)] == [140.0] * 3
    iv.reset()
    assert [p for p, _ in run(iv, 2)] == [100.0] * 2
    iv.add(cmd("scale", {"factor": 1.5}))
    assert [p for p, _ in run(iv, 2)] == [150.0] * 2


def test_ramp_to_target_is_linear_then_holds_until_reset():
    iv = InterventionSet()
    iv.add(cmd("ramp", {"target": 200}, duration_h=4))
    got = [p for p, _ in run(iv, 7)]
    assert got == [125.0, 150.0, 175.0, 200.0, 200.0, 200.0, 200.0]
    iv.reset()
    assert run(iv, 1)[0][0] == 100.0


def test_ramp_delta_and_hold_h_return_to_replay():
    iv = InterventionSet()
    iv.add(cmd("ramp", {"delta": 80}, duration_h=2))  # 100 -> 140 -> 180
    assert [p for p, _ in run(iv, 3)] == [140.0, 180.0, 180.0]
    iv2 = InterventionSet()
    iv2.add(cmd("ramp", {"target": 200, "hold_h": 2}, duration_h=2))
    assert [p for p, _ in run(iv2, 6)] == [150.0, 200.0, 200.0, 200.0, 100.0, 100.0]


def test_coupled_moves_pm10_by_the_train_ratio_and_uncoupled_does_not():
    iv = InterventionSet(coupled_ratio=1.5)
    iv.add(cmd("offset", {"delta": 40}, coupled=True))
    assert run(iv, 1)[0] == (140.0, 130.0 + 40 * 1.5)
    iv = InterventionSet(coupled_ratio=1.5)
    iv.add(cmd("offset", {"delta": 40}, coupled=False))
    assert run(iv, 1)[0] == (140.0, 130.0)
    iv = InterventionSet(coupled_ratio=1.5, sigma={"pm25": 10.0})
    iv.add(cmd("perturb", {"type": "spike", "severity": 5}, duration_h=1, coupled=True))
    assert run(iv, 1)[0] == (150.0, 130.0)  # a sensor FAULT stays on its own channel


def test_spike_stuck_dropout_match_the_rq3b_injector():
    base = np.array([100.0, 110.0, 120.0, 130.0, 140.0, 150.0])
    sigma = 12.0
    for kind, sev in (("spike", 5), ("stuck", 0), ("dropout", 0)):
        iv = InterventionSet(sigma={"pm25": sigma})
        got = []
        for h in range(2):  # two clean hours, then the fault starts
            got.append(iv.apply(T0 + pd.Timedelta(hours=h), {"pm25": base[h]})["pm25"])
        assert iv.add(cmd("perturb", {"type": kind, "severity": sev}, duration_h=3)) is None
        for h in range(2, 6):
            got.append(iv.apply(T0 + pd.Timedelta(hours=h), {"pm25": base[h]})["pm25"])
        ref = base.copy()
        apply_perturbation(ref, 2, 3, kind, sev, sigma)  # offline reference, same function
        expect = [None if np.isnan(x) else x for x in ref]
        assert got == expect, kind


def test_a_missing_reading_stays_missing_for_spike_and_stuck_but_dropout_applies():
    iv = InterventionSet(sigma={"pm25": 10.0})
    iv.add(cmd("perturb", {"type": "spike", "severity": 3}, duration_h=2))
    assert iv.apply(T0, {"pm25": None})["pm25"] is None


def test_offline_window_and_replay_brings_the_device_back():
    iv = InterventionSet()
    iv.add(cmd("offline", duration_h=2))
    assert [iv.is_offline(T0 + pd.Timedelta(hours=h)) for h in range(4)] == [
        True,
        True,
        False,
        False,
    ]
    iv = InterventionSet()
    iv.add(cmd("offline"))  # open-ended
    assert iv.is_offline(T0) and iv.is_offline(T0 + pd.Timedelta(hours=500))
    assert iv.add(cmd("replay")) is None  # replay clears it
    assert not iv.is_offline(T0 + pd.Timedelta(hours=501))


def test_replay_clears_only_the_named_variables():
    iv = InterventionSet()
    iv.add(cmd("offset", {"delta": 10}, variables=("pm25", "pm10")))
    iv.add(cmd("replay", variables=("pm25",)))
    r = iv.apply(T0, {"pm25": 100.0, "pm10": 130.0})
    assert (r["pm25"], r["pm10"]) == (100.0, 140.0)


def test_interventions_compose_in_arrival_order():
    iv = InterventionSet()
    iv.add(cmd("offset", {"delta": 50}))
    iv.add(cmd("scale", {"factor": 2}))
    assert run(iv, 1)[0][0] == 300.0  # (100 + 50) * 2


def test_out_of_range_values_are_refused_unless_allow_invalid():
    iv = InterventionSet()
    err = iv.add(cmd("manual", {"value": 1500}))
    assert err and "outside the physical range" in err and iv.count() == 0
    assert iv.add(cmd("manual", {"value": -5})) is not None
    assert iv.add(cmd("manual", {"value": 1500}, allow_invalid=True)) is None
    assert run(iv, 1)[0][0] == 1500.0  # the faulty-input test goes through unclamped


def test_offset_and_scale_range_checks_use_the_last_emitted_value():
    iv = InterventionSet()
    run(iv, 1)  # last emitted pm25 = 100
    assert iv.add(cmd("offset", {"delta": 950})) is not None  # 1050
    assert iv.add(cmd("scale", {"factor": 20})) is not None  # 2000
    assert iv.add(cmd("offset", {"delta": -200})) is not None  # -100
    assert iv.add(cmd("offset", {"delta": 100})) is None


def test_clamped_to_the_range_when_it_only_gets_there_later():
    iv = InterventionSet()
    iv.add(cmd("scale", {"factor": 2}))  # fine now (200) ...
    out = iv.apply(T0, {"pm25": 900.0, "pm10": 950.0})  # ... but 1800 on a hazy hour
    assert out["pm25"] == 999.0


def test_spike_without_a_train_sigma_is_refused():
    iv = InterventionSet(sigma={})
    err = iv.add(cmd("perturb", {"type": "spike", "severity": 5}, duration_h=2))
    assert err and "sigma" in err


def test_other_variables_are_untouched():
    iv = InterventionSet()
    iv.add(cmd("manual", {"value": 7}, variables=("temp",)))
    r = iv.apply(T0, {"pm25": 100.0, "temp": 20.0})
    assert r == {"pm25": 100.0, "temp": 7.0}


def test_command_schema_rejects_inconsistent_parameters():
    with pytest.raises(ValueError):
        cmd("ramp", {"target": 1, "delta": 2}, duration_h=3)  # both
    with pytest.raises(ValueError):
        cmd("ramp", {"target": 100})  # no duration
    with pytest.raises(ValueError):
        cmd("manual", {})  # no value
    with pytest.raises(ValueError):
        cmd("perturb", {"type": "bogus"}, duration_h=1)
    with pytest.raises(ValueError):
        cmd("perturb", {"type": "spike"}, duration_h=1)  # severity missing
    with pytest.raises(ValueError):
        cmd("manual", {"value": float("nan")})
    with pytest.raises(ValueError):
        cmd("offset", {"delta": 1}, variables=("pm99",))
