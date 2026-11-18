"""Leakage alarm (spec 4.5): results far better than the leakage-free literature => STOP."""

from __future__ import annotations


def sanity_alarms(rmse_by_h: dict[int, float], r2_h24: float | None, cfg: dict) -> list[str]:
    """Return alarm messages; an empty list means the check passed.

    Our split differs from the literature, so this is an alarm threshold, not a target.
    """
    s = cfg["forecast"]["sanity"]
    alarms = []
    for h, ref in s["rmse_ref"].items():
        got = rmse_by_h.get(int(h))
        if got is not None and got < ref * (1 - s["max_better_ratio"]):
            alarms.append(
                f"h={h}: RMSE {got:.1f} is more than {s['max_better_ratio']:.0%} below the "
                f"literature reference {ref:.1f} -> suspect leakage"
            )
    if r2_h24 is not None and r2_h24 > s["max_r2_h24"]:
        alarms.append(f"h=24: R2 {r2_h24:.3f} > {s['max_r2_h24']} -> suspect leakage")
    return alarms
