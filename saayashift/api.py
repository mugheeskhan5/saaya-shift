"""Local React adapter over the same audited pipeline and ranking functions."""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .insights import answer
from .planner import rank_windows

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("SAAYASHIFT_DATA_DIR", ROOT / "data"))
EVIDENCE = Path(os.environ.get("SAAYASHIFT_EVIDENCE_DIR", ROOT / "evidence"))
app = FastAPI(title="SaayaShift API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=[
    "http://localhost:5173", "http://127.0.0.1:5173",
    "http://localhost:3000", "http://127.0.0.1:3000",
], allow_methods=["GET", "POST"], allow_headers=["Content-Type"])


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(503, "Verified saved artifact unavailable; run the data pipeline.")


def forecast_frame():
    try:
        frame = pd.read_csv(DATA / "processed/forecast.csv")
        stamps = pd.to_datetime(frame.timestamp_utc, utc=True)
        return frame.loc[stamps >= pd.Timestamp.now(tz="UTC").ceil("h")].copy()
    except (OSError, ValueError, AttributeError):
        raise HTTPException(503, "Saved forecast unavailable; run the data pipeline.")


def freshness():
    status = load_json(DATA / "status.json")
    source = status.get("sources", {}).get("forecast", {})
    stamp = pd.to_datetime(source.get("last_fetch_utc"), utc=True, errors="coerce")
    age = None if stamp is None or pd.isna(stamp) else (pd.Timestamp.now(tz="UTC")-stamp).total_seconds()/3600
    return {"status": status, "forecast_age_hours": age,
            "forecast_stale": age is None or not 0 <= age <= 3 or source.get("status") != "available",
            "checked_at_utc": datetime.now(timezone.utc).isoformat()}


class WindowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    duration_hours: int = Field(4, ge=1, le=12)
    earliest_hour: int = Field(6, ge=0, le=23)
    latest_hour: int = Field(18, ge=1, le=24)
    start_date: date | None = None
    end_date: date | None = None
    max_mean_c: float | None = None

    @model_validator(mode="after")
    def valid_range(self):
        if self.earliest_hour >= self.latest_hour:
            raise ValueError("Operating hours must be in increasing order")
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("Start date must not follow end date")
        return self


class InsightRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=2000)
    window_id: str | None = None
    constraints: WindowRequest = Field(default_factory=WindowRequest)


@app.get("/api/health")
def health():
    return {"ok": True, "service": "saayashift", "timezone": "Asia/Karachi"}


@app.get("/api/status")
def status():
    return freshness()


@app.get("/api/forecast")
def forecast():
    return {**freshness(), "rows": json.loads(forecast_frame().to_json(orient="records"))}


@app.post("/api/windows")
def windows(request: WindowRequest):
    return {**freshness(), "windows": rank_windows(forecast_frame(), **request.model_dump()),
            "limitation": "Lower forecast heat does not certify safe working conditions."}


@app.post("/api/insights")
def insights(request: InsightRequest):
    frame = forecast_frame()
    plan = None
    if request.window_id:
        candidates = rank_windows(frame, **request.constraints.model_dump())
        plan = next((p for p in candidates if p["window_id"] == request.window_id), None)
        if plan is None:
            raise HTTPException(409, "Selected window changed or expired. Refresh rankings and select again.")
    # Never trust frontend-provided values or row IDs; recalculate on the server.
    return {**answer(request.question, frame, plan, data_dir=DATA), **freshness()}


@app.get("/api/evaluation")
def evaluation():
    return load_json(EVIDENCE / "model_report.json")
