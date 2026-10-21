"""Auditable acquisition of Open-Meteo model forecasts and non-personal OSM geometry.

Raw bodies are immutable content-addressed files. The manifest is append-only,
every cached body is hash-checked, and validated data is published atomically.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import duckdb
import pandas as pd
import requests

from .quality import QualityAgent, QualityError, WEATHER_RANGES, utc_now

USER_AGENT = "SaayaShift/0.1 (noncommercial hackathon research; one Karachi grid cell)"
MODEL = "icon_global"
HISTORY_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
WEATHER_LICENSE = "CC BY 4.0; Open-Meteo non-commercial API terms"
OSM_LICENSE = "ODbL 1.0; copyright OpenStreetMap contributors"
MANIFEST_FIELDS = [
    "source", "request_id", "method", "url", "query", "fetched_at_utc", "raw_file",
    "sha256", "bytes", "http_status", "license", "osm_base", "model", "robots_url",
]
DEFAULT_CITY = {"label": "Karachi", "latitude": 24.8607, "longitude": 67.0011,
                "timezone": "Asia/Karachi", "bbox": [24.80, 66.95, 24.94, 67.12]}


class IntegrityError(ValueError):
    """Cached raw bytes or their manifest no longer match."""


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def publish_csv_pair(frame: pd.DataFrame, data_dir: Path, name: str) -> None:
    """Stage both layers first, then replace; roll back if either replace fails."""
    targets = [data_dir / layer / f"{name}.csv" for layer in ("cleaned", "processed")]
    staged: list[Path] = []
    previous: dict[Path, bytes | None] = {}
    replaced: list[Path] = []
    try:
        for target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
            frame.to_csv(temporary, index=False)
            staged.append(temporary)
            previous[target] = target.read_bytes() if target.exists() else None
        for temporary, target in zip(staged, targets):
            os.replace(temporary, target)
            replaced.append(target)
    except Exception:
        for target in reversed(replaced):
            old_bytes = previous[target]
            if old_bytes is None:
                target.unlink(missing_ok=True)
            else:
                rollback = target.with_name(target.name + ".rollback.tmp")
                rollback.write_bytes(old_bytes)
                os.replace(rollback, target)
        raise
    finally:
        for temporary in staged:
            temporary.unlink(missing_ok=True)


def read_manifest(data_dir: Path) -> list[dict[str, str]]:
    path = Path(data_dir) / "manifest.csv"
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def verify_manifest(data_dir: Path) -> dict[str, int]:
    """Verify every prior acquisition, not just the file selected for this run."""
    data_dir = Path(data_dir).resolve()
    records = read_manifest(data_dir)
    verified: set[str] = set()
    for record in records:
        relative = record["raw_file"]
        target = (data_dir / relative).resolve()
        if data_dir not in target.parents:
            raise IntegrityError(f"Manifest raw path escapes data folder: {relative}")
        if relative in verified:
            # Still check the recorded hash agrees, even for a repeated fetch.
            if digest(target.read_bytes()) != record["sha256"]:
                raise IntegrityError(f"Conflicting manifest hash for {relative}")
            continue
        if not target.is_file() or digest(target.read_bytes()) != record["sha256"]:
            raise IntegrityError(f"Raw SHA-256 mismatch or missing file: {relative}")
        if target.stat().st_size != int(record["bytes"]):
            raise IntegrityError(f"Raw byte-size mismatch: {relative}")
        verified.add(relative)
    return {"manifest_rows": len(records), "unique_raw_files_verified": len(verified)}


class Acquisition:
    def __init__(self, data_dir: Path, offline: bool = False):
        self.data_dir = Path(data_dir)
        self.offline = offline
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
        self.records = read_manifest(data_dir)
        self.robots: dict[str, RobotFileParser] = {}
        self.last_request: dict[str, float] = {}
        self.api_calls = 0
        self.cache_hits = 0

    def _save(self, content: bytes, source: str, url: str, query: str,
              license_name: str, status: int = 200, request_id: str = "",
              method: str = "GET", osm_base: str = "") -> dict[str, str]:
        sha = digest(content)
        relative = Path("raw") / source / f"{sha}.json"
        target = self.data_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != content:
                raise IntegrityError("Content-addressed path contains different bytes")
        else:
            with target.open("xb") as handle:
                handle.write(content)
        origin = "{0.scheme}://{0.netloc}".format(urlsplit(url))
        row = {
            "source": source, "request_id": request_id, "method": method,
            "url": url, "query": query, "fetched_at_utc": utc_now(),
            "raw_file": relative.as_posix(), "sha256": sha, "bytes": str(len(content)),
            "http_status": str(status), "license": license_name, "osm_base": osm_base,
            "model": MODEL if source in {"weather", "forecast"} else "",
            "robots_url": origin + "/robots.txt",
        }
        path = self.data_dir / "manifest.csv"
        exists = path.exists()
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
            if not exists:
                writer.writeheader()
            writer.writerow(row)
        self.records.append(row)
        return row

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        host = urlsplit(url).netloc
        minimum_gap = 5.0 if "overpass" in host else 1.0
        for attempt in range(3):
            wait = minimum_gap - (time.monotonic() - self.last_request.get(host, 0.0))
            if wait > 0:
                time.sleep(wait)
            self.last_request[host] = time.monotonic()
            self.api_calls += 1
            try:
                response = self.session.request(method, url, timeout=(20, 120), **kwargs)
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(2 ** (attempt + 1))
                continue
            if response.status_code not in {429, 500, 502, 503, 504} or attempt == 2:
                return response
            retry_after = response.headers.get("Retry-After", "")
            delay = float(retry_after) if retry_after.isdigit() else 2 ** (attempt + 1)
            time.sleep(min(max(delay, minimum_gap), 60))
        raise RuntimeError("Unreachable retry state")

    def _respect_robots(self, url: str) -> None:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self.robots:
            robots_url = origin + "/robots.txt"
            response = self._request("GET", robots_url)
            self._save(response.content, "robots", robots_url, "", "Public robots policy snapshot",
                       response.status_code, digest(robots_url.encode()))
            parser = RobotFileParser(robots_url)
            if response.status_code in {401, 403}:
                parser.disallow_all = True
            elif 400 <= response.status_code < 500:
                parser.allow_all = True
            else:
                response.raise_for_status()
                parser.parse(response.text.splitlines())
            self.robots[origin] = parser
        parser = self.robots[origin]
        if not parser.can_fetch(USER_AGENT, url):
            # These are documented query APIs, not crawling targets. Preserve the
            # crawler policy and narrow the exception to the exact permitted path.
            documented = {
                "https://historical-forecast-api.open-meteo.com/v1/forecast": "https://open-meteo.com/en/docs/historical-forecast-api",
                "https://api.open-meteo.com/v1/forecast": "https://open-meteo.com/en/terms",
                "https://overpass-api.de/api/interpreter": "https://dev.overpass-api.de/overpass-doc/en/preface/commons.html",
            }
            endpoint = f"{parts.scheme}://{parts.netloc}{parts.path}"
            if endpoint not in documented or parser.disallow_all:
                raise PermissionError(f"robots.txt disallows {url}")
            with (self.data_dir / "api_access_decisions.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"timestamp_utc":utc_now(), "endpoint":endpoint,
                    "crawler_allowed":False,"operation":"documented noncommercial API query",
                    "publisher_permission":documented[endpoint],"decision":"API terms apply; no crawling or indexing"})+"\n")
        delay = parser.crawl_delay(USER_AGENT) or parser.crawl_delay("*")
        if delay:
            since = time.monotonic() - self.last_request.get(parts.netloc, 0.0)
            if since < delay:
                time.sleep(delay - since)

    def fetch(self, source: str, url: str, params: dict[str, Any] | None = None,
              query: str = "", refresh: bool = False,
              max_age_hours: float | None = None) -> tuple[dict[str, Any], dict[str, str]]:
        params = params or {}
        method = "POST" if query else "GET"
        prepared_url = requests.Request("GET", url, params=params).prepare().url or url
        key = digest(json.dumps({"method": method, "url": prepared_url, "body": query}, sort_keys=True).encode())
        cached = [r for r in self.records if r["request_id"] == key and r["http_status"] == "200"]
        latest = cached[-1] if cached else None
        age = ((datetime.now(timezone.utc) - datetime.fromisoformat(latest["fetched_at_utc"].replace("Z", "+00:00"))).total_seconds() / 3600) if latest else None
        usable = latest is not None and (max_age_hours is None or age is not None and age <= max_age_hours)
        if latest and (self.offline or not refresh and usable):
            path = self.data_dir / latest["raw_file"]
            content = path.read_bytes()
            if digest(content) != latest["sha256"]:
                raise IntegrityError(f"Cache hash mismatch: {path}")
            self.cache_hits += 1
            return json.loads(content), latest
        if self.offline:
            raise FileNotFoundError(f"Offline cache unavailable: {source} {key[:12]}")
        self._respect_robots(prepared_url)
        response = self._request(method, prepared_url, data={"data": query} if query else None)
        # Preserve error response bodies too, with honest status in the manifest.
        license_name = OSM_LICENSE if source.startswith("osm") else WEATHER_LICENSE
        try:
            parsed = response.json()
        except ValueError:
            parsed = {}
        osm_base = parsed.get("osm3s", {}).get("timestamp_osm_base", "")
        record = self._save(response.content, source, prepared_url, query, license_name,
                            response.status_code, key, method, osm_base)
        response.raise_for_status()
        if not parsed or parsed.get("error") or parsed.get("remark"):
            raise ValueError(f"{source}: invalid or incomplete source response: {parsed.get('reason', parsed.get('remark', 'not JSON'))}")
        return parsed, record


def city_config() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[1] / "config" / "cities.json"
    if not path.exists():
        return dict(DEFAULT_CITY)
    configuration = json.loads(path.read_text(encoding="utf-8"))
    city_name = os.environ.get("SAAYASHIFT_CITY", "karachi")
    cities = configuration.get("cities", configuration)
    if isinstance(cities, list):
        chosen = next((c for c in cities if c.get("id") == city_name), None)
    else:
        chosen = cities.get(city_name)
    if chosen is None:
        raise ValueError(f"City {city_name!r} missing from config/cities.json")
    return {**DEFAULT_CITY, **chosen}


def weather_params(city: dict[str, Any]) -> dict[str, Any]:
    return {"latitude": city["latitude"], "longitude": city["longitude"],
            "hourly": ",".join(WEATHER_RANGES), "models": MODEL,
            "timezone": city["timezone"], "timeformat": "unixtime",
            "temperature_unit": "celsius", "wind_speed_unit": "kmh",
            "precipitation_unit": "mm"}


def parse_weather(payload: dict[str, Any], record: dict[str, str]) -> pd.DataFrame:
    hourly = payload.get("hourly", {})
    times = hourly.get("time", [])
    if not times:
        raise QualityError("Weather response contains no hourly data")
    units = payload.get("hourly_units", {})
    if units.get("apparent_temperature") not in {"°C", "C", "celsius"}:
        raise QualityError("Unexpected apparent_temperature units; expected Celsius")
    timestamps = pd.to_datetime(times, unit="s", utc=True)
    latitude, longitude = float(payload["latitude"]), float(payload["longitude"])
    grid = f"{MODEL}:{latitude:.5f}:{longitude:.5f}"
    frame = pd.DataFrame({"timestamp_utc": timestamps.strftime("%Y-%m-%dT%H:%M:%SZ")})
    for name in WEATHER_RANGES:
        values = hourly.get(name)
        if values is None or len(values) != len(times):
            raise QualityError(f"Weather response has missing or misaligned {name}")
        frame[name] = pd.to_numeric(pd.Series(values), errors="coerce").astype(float)
    frame["grid_id"] = grid
    vintage = record["sha256"] if record.get("source") == "forecast" else "archive"
    frame["row_id"] = ["weather-" + digest(f"{grid}|{stamp}|{vintage}".encode())[:24] for stamp in frame["timestamp_utc"]]
    frame["latitude"], frame["longitude"] = latitude, longitude
    frame["estimated"] = False
    frame["source_model"] = MODEL
    frame["raw_file"] = record["raw_file"]
    frame["source_sha256"] = record["sha256"]
    frame["fetched_at_utc"] = record["fetched_at_utc"]
    return frame


def osm_query(kind: str, bbox: list[float]) -> str:
    bounds = ",".join(str(float(x)) for x in bbox)
    selectors = {
        "road": f'way["highway"~"^(primary|secondary|tertiary|residential|unclassified|living_street)$"]({bounds});',
        "park": f'nwr["leisure"="park"]({bounds});',
        "hospital": f'nwr["amenity"="hospital"]({bounds});',
        "clinic": f'nwr["amenity"="clinic"]({bounds});',
    }
    # `skel` excludes tags and contributor metadata at the server, so even raw
    # archives contain no phone numbers, doctor names, addresses or user names.
    return f"[out:json][timeout:60];{selectors[kind]}out skel center;"


def parse_osm(payload: dict[str, Any], record: dict[str, str], kind: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for element in payload.get("elements", []):
        if element.get("tags") or element.get("user"):
            raise QualityError("Unexpected OSM tags or user metadata; privacy-minimized query required")
        center = element.get("center", element)
        if "lat" not in center or "lon" not in center:
            continue
        rows.append({
            "row_id": f"osm-{kind}-{element['type']}-{element['id']}",
            "name": f"Mapped {kind}", "kind": kind,
            "latitude": float(center["lat"]), "longitude": float(center["lon"]),
            "osm_type": element["type"], "osm_id": str(element["id"]),
            "raw_file": record["raw_file"], "source_sha256": record["sha256"],
            "fetched_at_utc": record["fetched_at_utc"], "osm_base": record.get("osm_base", ""),
        })
    return pd.DataFrame(rows, columns=["row_id", "name", "kind", "latitude", "longitude",
                                      "osm_type", "osm_id", "raw_file", "source_sha256", "fetched_at_utc", "osm_base"])


def source_status(frame: pd.DataFrame, records: list[dict[str, str]], source: str,
                  now: datetime, city: dict[str, Any]) -> dict[str, Any]:
    last_fetch = max(r["fetched_at_utc"] for r in records)
    age = max(0.0, (now - datetime.fromisoformat(last_fetch.replace("Z", "+00:00"))).total_seconds() / 3600)
    threshold = {"weather": None, "forecast": 3, "osm": 168}[source]
    result: dict[str, Any] = {
        "status": "available", "rows": len(frame), "last_fetch_utc": last_fetch,
        "age_hours": round(age, 3), "stale": bool(threshold is not None and age > threshold),
        "stale_after_hours": threshold,
        "requested_latitude": city["latitude"], "requested_longitude": city["longitude"],
        "kind": "historical forecast model series" if source == "weather" else ("live forecast model series" if source == "forecast" else "mapped geometry snapshot"),
    }
    if source in {"weather", "forecast"}:
        result.update(data_start_utc=str(frame["timestamp_utc"].min()),
                      data_end_utc=str(frame["timestamp_utc"].max()),
                      returned_latitude=float(frame["latitude"].iloc[0]),
                      returned_longitude=float(frame["longitude"].iloc[0]),
                      grid_ids=sorted(frame["grid_id"].unique().tolist()), model=MODEL)
        if source == "forecast":
            result["stale"] = result["stale"] or pd.Timestamp(result["data_end_utc"]) < pd.Timestamp(now)
    else:
        result["osm_base"] = min((r["osm_base"] for r in records if r.get("osm_base")), default="")
        result["category_counts"] = {str(k): int(v) for k, v in frame["kind"].value_counts().items()}
    return result


def build_warehouse(data_dir: Path, raw_frames: dict[str, pd.DataFrame]) -> Path:
    """Build raw/cleaned/processed schemas in a new DB, then publish by replace."""
    destination = data_dir / "warehouse.duckdb"
    temporary = data_dir / f"warehouse.{uuid.uuid4().hex}.duckdb"
    try:
        with duckdb.connect(str(temporary)) as connection:
            for schema in ("raw", "cleaned", "processed"):
                connection.execute(f"CREATE SCHEMA {schema}")
            manifest = pd.DataFrame(read_manifest(data_dir), columns=MANIFEST_FIELDS)
            connection.register("manifest_frame", manifest)
            connection.execute("CREATE TABLE raw.manifest AS SELECT * FROM manifest_frame")
            for name in ("weather", "forecast", "osm"):
                if name in raw_frames:
                    connection.register("raw_frame", raw_frames[name])
                    connection.execute(f"CREATE TABLE raw.{name} AS SELECT * FROM raw_frame")
                    connection.unregister("raw_frame")
                for layer in ("cleaned", "processed"):
                    path = data_dir / layer / f"{name}.csv"
                    if path.exists():
                        frame = pd.read_csv(path)
                        connection.register("layer_frame", frame)
                        connection.execute(f"CREATE TABLE {layer}.{name} AS SELECT * FROM layer_frame")
                        connection.unregister("layer_frame")
            connection.execute("CHECKPOINT")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def run_data(data_dir: Path = Path("data"), refresh_live: bool = True,
             offline: bool = False) -> dict[str, Any]:
    """Rebuild all three data layers and DQ evidence from original/cached sources.

    Returns a JSON-serializable status. `ok=False` means at least one required
    source or warehouse operation failed; prior validated CSVs remain available.
    """
    started = time.monotonic()
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    agent = QualityAgent(data_dir / "quality_log.jsonl", run_id)
    city = city_config()
    status: dict[str, Any] = {"ok": False, "run_id": run_id, "updated_at_utc": utc_now(),
                              "sources": {}, "errors": [], "offline": offline}
    # Integrity failure aborts before any cleaned/processed artifacts are changed.
    try:
        status["integrity"] = verify_manifest(data_dir)
    except (IntegrityError, OSError, ValueError) as exc:
        agent.record("manifest", "sha256_integrity", 1, "flag", str(exc))
        status["errors"].append(str(exc))
        status["quality"] = agent.summary()
        status["quality"]["status"] = "fail"
        atomic_json(data_dir / "status.json", status)
        return status
    acquisition = Acquisition(data_dir, offline)
    raw_frames: dict[str, pd.DataFrame] = {}
    now = datetime.now(timezone.utc)
    previous_path = data_dir / "status.json"
    previous = json.loads(previous_path.read_text(encoding="utf-8")) if previous_path.exists() else {}

    for source in ("weather", "forecast", "osm"):
        records: list[dict[str, str]] = []
        try:
            frames: list[pd.DataFrame] = []
            if source == "weather":
                for year in (2023, 2024, 2025):
                    params = {**weather_params(city), "start_date": f"{year}-01-01", "end_date": f"{year}-12-31"}
                    payload, record = acquisition.fetch(source, HISTORY_URL, params)
                    frames.append(parse_weather(payload, record))
                    records.append(record)
                raw = pd.concat(frames, ignore_index=True)
                start = pd.Timestamp("2023-01-01", tz=city["timezone"]).tz_convert("UTC").isoformat()
                end = pd.Timestamp("2025-12-31 23:00", tz=city["timezone"]).tz_convert("UTC").isoformat()
                cleaned = agent.weather(raw, source, start, end)
            elif source == "forecast":
                params = {**weather_params(city), "forecast_days": 7}
                payload, record = acquisition.fetch(source, FORECAST_URL, params,
                                                    refresh=refresh_live, max_age_hours=3)
                records.append(record)
                raw = parse_weather(payload, record)
                cleaned = agent.weather(raw, source)
            else:
                for kind in ("road", "park", "hospital", "clinic"):
                    payload, record = acquisition.fetch(f"osm_{kind}", OVERPASS_URL,
                                                        query=osm_query(kind, city["bbox"]), max_age_hours=168)
                    frames.append(parse_osm(payload, record, kind))
                    records.append(record)
                raw = pd.concat(frames, ignore_index=True)
                cleaned = agent.osm(raw)
            source_info = source_status(cleaned, records, source, datetime.now(timezone.utc), city)
            agent.record(source, "timeliness", int(source_info["stale"]), "flag",
                         "Historical archive is frozen; live forecast must be fetched within 3 h and cover the future; OSM snapshot refreshes after 7 d",
                         age_hours=source_info["age_hours"], stale_after_hours=source_info["stale_after_hours"])
            publish_csv_pair(cleaned, data_dir, source)
            raw_frames[source] = raw
            status["sources"][source] = source_info
        except Exception as exc:
            error = f"{source}: {type(exc).__name__}: {exc}"
            status["errors"].append(error)
            agent.record(source, "acquisition_or_publication", 1, "flag",
                         "New batch failed; prior published data is preserved", error=error)
            fallback = dict(previous.get("sources", {}).get(source, {}))
            fallback.update(status="error", error=error, previous_data_preserved=(data_dir / "processed" / f"{source}.csv").exists())
            if fallback.get("last_fetch_utc"):
                age = max(0.0, (now - datetime.fromisoformat(fallback["last_fetch_utc"].replace("Z", "+00:00"))).total_seconds() / 3600)
                fallback["age_hours"] = round(age, 3)
                threshold = fallback.get("stale_after_hours")
                fallback["stale"] = bool(threshold is not None and age > threshold)
            status["sources"][source] = fallback
    try:
        status["integrity"] = verify_manifest(data_dir)
        status["warehouse"] = str(build_warehouse(data_dir, raw_frames))
    except Exception as exc:
        status["errors"].append(f"warehouse/integrity: {type(exc).__name__}: {exc}")
        agent.record("warehouse", "warehouse_publication", 1, "flag", str(exc))
    status["ok"] = not status["errors"] and all(s.get("status") == "available" for s in status["sources"].values())
    status["quality"] = agent.summary()
    if not status["ok"]:
        status["quality"]["status"] = "fail"
    status["updated_at_utc"] = utc_now()
    status["duration_seconds"] = round(time.monotonic() - started, 3)
    status["acquisition"] = {"http_calls": acquisition.api_calls, "cache_hits": acquisition.cache_hits}
    atomic_json(data_dir / "status.json", status)
    return status
