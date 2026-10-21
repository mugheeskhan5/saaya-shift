"""Deterministic complete-window ranking; no medical safety thresholds."""
from __future__ import annotations

import hashlib
import pandas as pd


def rank_windows(forecast, duration_hours=4, earliest_hour=6, latest_hour=18,
                 start_date=None, end_date=None, max_mean_c=None,
                 timezone="Asia/Karachi"):
    if not 1 <= duration_hours <= 24:
        raise ValueError("Shift duration must be between 1 and 24 hours")
    if not 0 <= earliest_hour < latest_hour <= 24:
        raise ValueError("Operating hours must satisfy 0 <= start < end <= 24")
    if forecast.empty:
        return []
    frame = forecast.copy()
    frame["timestamp_utc"] = pd.to_datetime(frame.timestamp_utc, utc=True)
    if frame.timestamp_utc.duplicated().any():
        raise ValueError("Select exactly one forecast grid and one forecast vintage")
    frame = frame.sort_values("timestamp_utc").set_index("timestamp_utc")
    results = []
    for start in frame.index:
        local = start.tz_convert(timezone)
        if start_date and local.date() < pd.Timestamp(start_date).date():
            continue
        if end_date and local.date() > pd.Timestamp(end_date).date():
            continue
        if local.hour < earliest_hour or local.hour + duration_hours > latest_hour:
            continue
        hours = pd.date_range(start, periods=duration_hours, freq="h")
        window = frame.reindex(hours)
        if window.apparent_temperature.isna().any() or window.row_id.isna().any():
            continue
        if "estimated" in window and window.estimated.astype(str).str.lower().eq("true").any():
            continue
        if "quality_flag" in window and window.quality_flag.fillna("").astype(str).ne("").any():
            continue
        values = pd.to_numeric(window.apparent_temperature, errors="coerce")
        if values.isna().any():
            continue
        mean = float(values.mean())
        if max_mean_c is not None and mean > max_mean_c:
            continue
        row_ids = window.row_id.tolist()
        results.append({
            "window_id": hashlib.sha256("|".join(row_ids).encode()).hexdigest()[:20],
            "start_local": local.isoformat(),
            "end_local": (start + pd.Timedelta(hours=duration_hours)).tz_convert(timezone).isoformat(),
            "mean_c": mean, "peak_c": float(values.max()),
            "degree_hours": float(values.sum()), "row_ids": row_ids,
            "score_reason": "Lowest mean apparent temperature, then lowest peak, then earliest start. No safe-work certification.",
        })
    results.sort(key=lambda x: (x["mean_c"], x["peak_c"], x["start_local"]))
    for rank, result in enumerate(results, 1):
        result["rank"] = rank
    return results
