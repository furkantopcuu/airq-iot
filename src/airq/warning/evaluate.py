"""Warning evaluation (spec 5.2): hourly classification and event-level lead time.

Event catch: an exceedance event is CAUGHT if the station has at least one alert at an issue time
t in [onset - window_h, onset]. Lead time = onset - first such alert (hours; 0 = at the onset).
False-alarm rate = alerts with no observed exceedance in the following 24 h / all alerts.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

from airq.warning.rules import fbeta, hourly_scores, warning_flags


def hourly_metrics(y_bool: np.ndarray, yhat: np.ndarray, theta: float, delta: float) -> dict:
    """Precision, recall, F1, F2 of the hourly warnings and PR-AUC of the continuous score."""
    flags = warning_flags(yhat, theta, delta)
    p, r = hourly_scores(y_bool, flags)
    score = np.where(
        np.isnan(yhat), np.nanmin(yhat) - 1.0 if np.any(~np.isnan(yhat)) else 0.0, yhat
    )
    pr_auc = float(average_precision_score(y_bool, score)) if y_bool.any() else float("nan")
    return {
        "precision": p, "recall": r, "f1": fbeta(p, r, 1.0), "f2": fbeta(p, r, 2.0),
        "pr_auc": pr_auc, "n": int(len(y_bool)), "n_pos": int(y_bool.sum()),
        "n_warnings": int(flags.sum()),
    }  # fmt: skip


def event_leads(
    onsets: pd.Series, alert_times: np.ndarray, window_h: int = 24
) -> list[float | None]:
    """Lead time (hours) per onset, or None when no alert fell in [onset-window, onset]."""
    alert_times = np.sort(np.asarray(alert_times, dtype="datetime64[ns]"))
    out: list[float | None] = []
    for onset in pd.to_datetime(onsets):
        lo = np.datetime64(onset - pd.Timedelta(hours=window_h), "ns")
        hi = np.datetime64(onset, "ns")
        i = np.searchsorted(alert_times, lo, side="left")
        if i < len(alert_times) and alert_times[i] <= hi:
            out.append(float((hi - alert_times[i]) / np.timedelta64(1, "h")))
        else:
            out.append(None)
    return out


def false_alarm_stats(alert_idx: np.ndarray, obs: np.ndarray, theta: float, within_h: int = 24):
    """(false alerts, total alerts) for one station: an alert at row i is false if no observed
    value in rows i+1 .. i+within_h exceeds theta (missing values never count as exceedances)."""
    exceed = np.nan_to_num(obs, nan=-1.0) > theta
    csum = np.concatenate([[0], np.cumsum(exceed)])
    n = len(obs)
    false = 0
    for i in alert_idx:
        hi = min(n, i + 1 + within_h)
        if csum[hi] - csum[i + 1] == 0:
            false += 1
    return false, int(len(alert_idx))


def summarize_leads(leads: list[float | None]) -> dict:
    caught = [x for x in leads if x is not None]
    out = {
        "n_events": len(leads),
        "n_caught": len(caught),
        "event_recall": len(caught) / len(leads) if leads else float("nan"),
    }
    if caught:
        q = np.percentile(caught, [25, 50, 75])
        out.update(lead_median=float(q[1]), lead_q25=float(q[0]), lead_q75=float(q[2]),
                   lead_mean=float(np.mean(caught)))  # fmt: skip
    else:
        out.update(lead_median=float("nan"), lead_q25=float("nan"), lead_q75=float("nan"),
                   lead_mean=float("nan"))  # fmt: skip
    return out
