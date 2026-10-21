"""Frozen chronological experiment; next-hour model-series prediction, not health."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import psutil
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

LAGS = [1, 2, 3, 24, 25, 48]
FEATURES = [f"lag_{h}" for h in LAGS] + ["hour_sin", "hour_cos", "year_sin", "year_cos"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def features(frame):
    data = frame.copy()
    data["timestamp_utc"] = pd.to_datetime(data.timestamp_utc, utc=True)
    if data.timestamp_utc.duplicated().any():
        raise ValueError("Model requires one returned grid cell and unique target timestamps")
    data = data.sort_values("timestamp_utc").set_index("timestamp_utc")
    data["apparent_temperature"] = pd.to_numeric(data.apparent_temperature, errors="coerce")
    if "estimated" in data:
        data.loc[data.estimated.astype(str).str.lower().eq("true"), "apparent_temperature"] = np.nan
    series = data.apparent_temperature.copy()
    for lag in LAGS:
        data[f"lag_{lag}"] = series.reindex(data.index - pd.Timedelta(hours=lag)).to_numpy()
    local = data.index.tz_convert("Asia/Karachi")
    data["local_year"] = local.year
    data["local_month"] = local.month
    data["local_hour"] = local.hour
    data["hour_sin"] = np.sin(2 * np.pi * local.hour / 24)
    data["hour_cos"] = np.cos(2 * np.pi * local.hour / 24)
    data["year_sin"] = np.sin(2 * np.pi * (local.dayofyear - 1) / 365.25)
    data["year_cos"] = np.cos(2 * np.pi * (local.dayofyear - 1) / 365.25)
    return data


def paired_block_intervals(errors, baseline_errors, repeats=500):
    """Fixed-seed circular moving-block bootstrap, seven days of hourly errors."""
    rng = np.random.default_rng(2026)
    n, block = len(errors), min(168, len(errors))
    metrics, differences = [], []
    for _ in range(repeats):
        starts = rng.integers(0, n, size=int(np.ceil(n / block)))
        idx = ((starts[:, None] + np.arange(block)) % n).ravel()[:n]
        metrics.append(float(errors[idx].mean()))
        differences.append(float((baseline_errors[idx] - errors[idx]).mean()))
    return np.quantile(metrics, [0.025, 0.975]).tolist(), np.quantile(differences, [0.025, 0.975]).tolist()


def evaluate(data_dir=Path("data"), evidence_dir=Path("evidence")):
    data_dir, evidence_dir = Path(data_dir), Path(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    report_path = evidence_dir / "model_report.json"
    input_path = data_dir / "processed/weather.csv"
    protocol_path = Path(__file__).resolve().parents[1] / "docs/EVALUATION_PROTOCOL.md"
    provenance = {"weather_sha256": sha(input_path), "protocol_sha256": sha(protocol_path),
                  "implementation_sha256": sha(__file__)}
    if report_path.exists():
        previous = json.loads(report_path.read_text())
        if previous["provenance"] != provenance:
            raise RuntimeError("Held-out report already exists with different inputs/code. Do not retune on 2025; review the integrity change explicitly.")
        return previous
    started = time.perf_counter()
    all_rows = features(pd.read_csv(input_path))
    valid = all_rows.dropna(subset=FEATURES + ["apparent_temperature"])
    train = valid.loc[valid.local_year == 2023]
    validation = valid.loc[(valid.local_year == 2024) & (valid.local_month <= 6)]
    calibration = valid.loc[(valid.local_year == 2024) & (valid.local_month >= 7)]
    test = valid.loc[valid.local_year == 2025]
    if min(map(len, [train, validation, calibration, test])) < 720:
        raise ValueError("Insufficient chronological data; no held-out evaluation performed")
    scaler = StandardScaler().fit(train[FEATURES])
    ridge = Ridge(alpha=1.0).fit(scaler.transform(train[FEATURES]), train.apparent_temperature)
    val_ridge = float(np.mean(np.abs(ridge.predict(scaler.transform(validation[FEATURES])) - validation.apparent_temperature)))
    val_persistence = float(np.mean(np.abs(validation.lag_1 - validation.apparent_temperature)))
    model_name = "Ridge(alpha=1)" if val_ridge < val_persistence else "lag-one persistence"
    development = pd.concat([train, validation])
    if model_name.startswith("Ridge"):
        scaler = StandardScaler().fit(development[FEATURES])
        ridge = Ridge(alpha=1.0).fit(scaler.transform(development[FEATURES]), development.apparent_temperature)
        def predict(rows):
            return ridge.predict(scaler.transform(rows[FEATURES]))
        parameters = {"coefficients": ridge.coef_.tolist(), "intercept": float(ridge.intercept_),
                      "scaler_mean": scaler.mean_.tolist(), "scaler_scale": scaler.scale_.tolist()}
    else:
        def predict(rows):
            return rows.lag_1.to_numpy()
        parameters = {}
    cal_errors = np.abs(predict(calibration) - calibration.apparent_temperature.to_numpy())
    radius = float(np.quantile(cal_errors, 0.9, method="higher"))
    artifact = {"model_name": model_name, "features": FEATURES, "parameters": parameters,
                "interval_radius_c": radius, "fit_end_local": "2024-06-30T23:00:00+05:00",
                "calibration_period": "2024-07-01 through 2024-12-31 local", "provenance": provenance,
                "frozen_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
                "validation_mae_c": {"ridge": val_ridge, "lag_one": val_persistence}}
    # Persist the selection and parameters BEFORE inspecting the held-out target errors.
    artifact_path = evidence_dir / "frozen_model.json"
    artifact_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    predictions = predict(test)
    errors = np.abs(predictions - test.apparent_temperature.to_numpy())
    baseline_errors = np.abs(test.lag_24.to_numpy() - test.apparent_temperature.to_numpy())
    ci, delta_ci = paired_block_intervals(errors, baseline_errors)
    result_rows = pd.DataFrame({"timestamp_utc": test.index, "row_id": test.row_id,
                               "target_c": test.apparent_temperature, "prediction_c": predictions,
                               "baseline_c": test.lag_24, "lower_c": predictions - radius,
                               "upper_c": predictions + radius, "error_c": errors,
                               "baseline_error_c": baseline_errors, "covered": errors <= radius})
    seasons = {12:"winter",1:"winter",2:"winter",3:"pre-monsoon",4:"pre-monsoon",5:"pre-monsoon",
               6:"monsoon",7:"monsoon",8:"monsoon",9:"monsoon",10:"post-monsoon",11:"post-monsoon"}
    result_rows["season"] = test.local_month.map(seasons)
    result_rows["time_of_day"] = pd.cut(test.local_hour, [-1,5,11,17,23], labels=["night", "morning", "afternoon", "evening"])
    groups = []
    for group_col in ["season", "time_of_day"]:
        for group, rows in result_rows.groupby(group_col, observed=True):
            groups.append({"group": f"{group_col}:{group}", "n": len(rows),
                           "model_mae_c": float(rows.error_c.mean()),
                           "baseline_mae_c": float(rows.baseline_error_c.mean()),
                           "interval_coverage": float(rows.covered.mean())})
    report = {"status": "PASS" if errors.mean() < baseline_errors.mean() else "FAIL",
              "evaluated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
              "model_name": model_name, "baseline_name": "H-24 same-local-hour persistence (frozen)",
              "baseline_mae_c": float(baseline_errors.mean()), "model_mae_c": float(errors.mean()),
              "improvement_c": float((baseline_errors-errors).mean()), "mae_ci95_c": ci,
              "improvement_ci95_c": delta_ci, "interval_radius_c": radius,
              "interval_coverage": float(np.mean(errors <= radius)), "groups": groups,
              "weakest_group": max(groups, key=lambda x:x["model_mae_c"]),
              "split_counts": {"train_2023": len(train), "selection_2024_h1":len(validation),
                               "calibration_2024_h2":len(calibration),"test_2025":len(test),
                               "excluded_missing_target_or_predictors":len(all_rows)-len(valid)},
              "validation_mae_c": artifact["validation_mae_c"],
              "runtime_seconds": time.perf_counter()-started,
              "rss_mb_at_end": psutil.Process().memory_info().rss / 1024**2,
              "provenance": provenance, "frozen_artifact_sha256":sha(artifact_path),
              "limitations":["Retrospective rolling one-hour modeled-series prediction; no station observations or operational issue-time validation.",
                             "One Karachi grid cell; no district, occupation, demographic or nationwide validation.",
                             "90% interval calibrated on 2024; actual 2025 coverage is empirical and may differ.",
                             "Seven-day block bootstrap assumes approximate local stability; model-version changes and temporal dependence remain.",
                             "Live shift ranking uses provider forecasts, not this experimental model."]}
    result_rows.to_csv(evidence_dir / "test_predictions.csv", index=False)
    pd.DataFrame(groups).to_csv(evidence_dir / "group_errors.csv", index=False)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
