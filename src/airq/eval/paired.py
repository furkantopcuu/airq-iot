"""Paired edge off / on differences (pandas only: no MQTT or server imports, so the figure and
table stages run on a plain ML install)."""

import pandas as pd


def paired_differences(df: pd.DataFrame) -> pd.DataFrame:
    """Per fault and start: metric(edge off) - metric(edge on) (positive = the filter helped)."""
    out = []
    for (fault, start), g in df.groupby(["fault", "start"]):
        off, on = g[g["edge"] == "off"], g[g["edge"] == "on"]
        if off.empty or on.empty:
            continue
        row = {"fault": fault, "start": start}
        for c in ("mae_window_h1", "mae_window_h6", "peak_forecast_h6"):
            row[f"{c}_off"], row[f"{c}_on"] = off[c].iloc[0], on[c].iloc[0]
            row[f"{c}_diff"] = off[c].iloc[0] - on[c].iloc[0]
        out.append(row)
    return pd.DataFrame(out)
