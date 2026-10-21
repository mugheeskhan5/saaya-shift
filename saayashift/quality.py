"""Deterministic data-quality decisions; no target imputation or model fitting."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pandera.pandas as pa

WEATHER_RANGES = {
    "apparent_temperature": (-80.0, 80.0),
    "temperature_2m": (-60.0, 60.0),
    "relative_humidity_2m": (0.0, 100.0),
    "wind_speed_10m": (0.0, 250.0),
    "shortwave_radiation": (0.0, 1500.0),
    "precipitation": (0.0, 500.0),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class QualityError(ValueError):
    """A batch cannot be safely published."""


class QualityAgent:
    """Run Pandera and statistical checks, recording each decision as JSONL.

    `estimated` means locally filled, NOT whether the publisher uses a weather
    model. All weather here is forecast-model output, not station observations.
    """

    def __init__(self, log_path: Path, run_id: str | None = None):
        self.log_path = Path(log_path)
        self.run_id = run_id or utc_now()
        self.decisions: list[dict[str, Any]] = []

    def record(self, source: str, rule: str, count: int, action: str,
               reason: str, *, estimated: bool = False, **details: Any) -> None:
        if action not in {"fix", "fill", "flag"}:
            raise ValueError("Unknown DQ action")
        decision = {
            "timestamp_utc": utc_now(), "run_id": self.run_id,
            "source": source, "rule": rule, "affected_count": int(count),
            "action": action, "reason": reason, "estimated": estimated,
            **details,
        }
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(decision, ensure_ascii=False, allow_nan=False) + "\n")
        self.decisions.append(decision)

    def weather(self, frame: pd.DataFrame, source: str,
                expected_start: str | None = None,
                expected_end: str | None = None) -> pd.DataFrame:
        df = frame.copy()
        required = {"row_id", "grid_id", "timestamp_utc", "latitude", "longitude",
                    "apparent_temperature", "estimated", "raw_file", "source_sha256"}
        missing = sorted(required - set(df.columns))
        if missing or df.empty:
            self.record(source, "required_schema", max(len(missing), int(df.empty)), "flag",
                        "Batch rejected: missing required fields or empty response", fields=missing)
            raise QualityError(f"{source}: missing {missing} or empty response")

        value_cols = [c for c in df if c not in {"raw_file", "source_sha256", "fetched_at_utc"}]
        duplicates = df.duplicated(subset=value_cols, keep="first")
        self.record(source, "exact_duplicate_rows", int(duplicates.sum()), "fix",
                    "Identical source values collapse to one stable row; raw bytes remain unchanged")
        df = df.loc[~duplicates].copy()
        conflicts = df.duplicated(subset=["grid_id", "timestamp_utc"], keep=False)
        self.record(source, "conflicting_duplicate_hours", int(conflicts.sum()), "flag",
                    "Conflicting records are not resolved by arbitrary row order; reject batch if present")
        if conflicts.any():
            raise QualityError(f"{source}: conflicting duplicate hours")

        parsed = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
        if parsed.isna().any():
            self.record(source, "invalid_timestamp", int(parsed.isna().sum()), "flag",
                        "Invalid times prevent chronology and the batch is rejected")
            raise QualityError(f"{source}: invalid timestamps")
        normalized = parsed.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.record(source, "utc_normalization", int((normalized != df["timestamp_utc"]).sum()), "fix",
                    "Normalize unambiguous timezone-aware instants to ISO 8601 UTC")
        df["timestamp_utc"] = normalized

        for column, (lower, upper) in WEATHER_RANGES.items():
            if column not in df:
                continue
            numeric = pd.to_numeric(df[column], errors="coerce").astype(float)
            malformed = df[column].notna() & numeric.isna()
            self.record(source, f"numeric_type:{column}", int(malformed.sum()), "flag",
                        "Unparseable numeric source values retained as missing, never estimated")
            outside = numeric.notna() & (~np.isfinite(numeric) | ~numeric.between(lower, upper))
            self.record(source, f"physical_range:{column}", int(outside.sum()), "flag",
                        "Values outside broad physical bounds are quarantined as missing; raw evidence preserved",
                        lower=lower, upper=upper)
            df[column] = numeric.mask(outside)
            self.record(source, f"missingness:{column}", int(df[column].isna().sum()), "flag",
                        "Missing source values remain missing; no interpolation or target filling")

        for grid_id, group in df.groupby("grid_id"):
            observed = pd.DatetimeIndex(pd.to_datetime(group["timestamp_utc"], utc=True))
            start = pd.Timestamp(expected_start) if expected_start else observed.min()
            end = pd.Timestamp(expected_end) if expected_end else observed.max()
            expected = pd.date_range(start, end, freq="h")
            gaps = expected.difference(observed)
            self.record(source, "hourly_continuity", len(gaps), "flag",
                        "Absent hours are reported and not fabricated", grid_id=str(grid_id),
                        examples=[t.isoformat() for t in gaps[:5]])

        times = pd.to_datetime(df["timestamp_utc"], utc=True)
        local_year = times.dt.tz_convert("Asia/Karachi").dt.year
        medians = df.groupby(local_year)["apparent_temperature"].median().dropna()
        shifts = medians.diff().abs().dropna()
        self.record(source, "annual_median_shift", int((shifts > 5).sum()), "flag",
                    "Year-to-year median changes above 5 C require review; no correction is inferred",
                    annual_medians={str(k): float(v) for k, v in medians.items()})
        columns = {
            "row_id": pa.Column(str, unique=True, nullable=False),
            "grid_id": pa.Column(str, nullable=False),
            "timestamp_utc": pa.Column(str, pa.Check.str_matches(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")),
            "latitude": pa.Column(float, pa.Check.in_range(-90, 90), coerce=True),
            "longitude": pa.Column(float, pa.Check.in_range(-180, 180), coerce=True),
            "estimated": pa.Column(bool, pa.Check.eq(False)),
            "source_sha256": pa.Column(str, pa.Check.str_matches(r"^[a-f0-9]{64}$")),
            "raw_file": pa.Column(str, nullable=False),
        }
        columns.update({name: pa.Column(float, pa.Check.in_range(*bounds), nullable=True)
                        for name, bounds in WEATHER_RANGES.items() if name in df})
        try:
            df = pa.DataFrameSchema(columns, strict=False).validate(df, lazy=True)
        except pa.errors.SchemaErrors as exc:
            self.record(source, "pandera_schema", len(exc.failure_cases), "flag",
                        "Pandera schema rejected batch", sample=str(exc.failure_cases.head(5).to_dict("records")))
            raise QualityError(f"{source}: Pandera schema failed") from exc
        self.record(source, "pandera_schema", 0, "flag", "Pandera schema validation passed")
        return df.sort_values(["grid_id", "timestamp_utc"]).reset_index(drop=True)

    def osm(self, frame: pd.DataFrame) -> pd.DataFrame:
        df = frame.copy()
        if df.empty:
            self.record("osm", "empty_batch", 1, "flag", "No mapped features returned; reject empty batch")
            raise QualityError("OSM returned no features")
        duplicates = df.duplicated("row_id")
        self.record("osm", "duplicate_features", int(duplicates.sum()), "fix",
                    "Deduplicate stable OSM object IDs within each category")
        df = df.loc[~duplicates].copy()
        schema = pa.DataFrameSchema({
            "row_id": pa.Column(str, unique=True),
            "name": pa.Column(str),
            "kind": pa.Column(str, pa.Check.isin(["road", "park", "hospital", "clinic"])),
            "latitude": pa.Column(float, pa.Check.in_range(-90, 90), coerce=True),
            "longitude": pa.Column(float, pa.Check.in_range(-180, 180), coerce=True),
            "raw_file": pa.Column(str),
            "source_sha256": pa.Column(str, pa.Check.str_matches(r"^[a-f0-9]{64}$")),
        }, strict=False)
        try:
            result = schema.validate(df, lazy=True)
        except pa.errors.SchemaErrors as exc:
            self.record("osm", "pandera_schema", len(exc.failure_cases), "flag", "OSM schema rejected batch")
            raise QualityError("OSM schema failed") from exc
        self.record("osm", "pandera_schema", 0, "flag", "OSM schema validation passed; only generic feature labels retained")
        return result.reset_index(drop=True)

    def summary(self) -> dict[str, Any]:
        findings = [d for d in self.decisions if d["affected_count"] > 0]
        flagged = [d for d in findings if d["action"] == "flag"]
        return {
            "status": "warning" if flagged else "pass", "checked_at_utc": utc_now(),
            "checks": len(self.decisions), "findings": len(findings),
            "flagged_findings": len(flagged),
            "fixed_rows": sum(d["affected_count"] for d in findings if d["action"] == "fix"),
            "filled_values": 0, "log": str(self.log_path),
        }
