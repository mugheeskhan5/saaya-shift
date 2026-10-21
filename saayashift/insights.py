"""Permission-cleared, extractive guidance prototype; no LLM completion claimed.

Raw publisher files and exact PDF extraction offsets support every quotation.
Numeric summaries are calculated from supplied processed rows, never generated.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

SOURCE_URL = "https://www.cdc.gov/niosh/docs/2016-106/pdfs/2016-106.pdf"
SOURCE_TITLE = "NIOSH: Occupational Exposure to Heat and Hot Environments (2016-106)"
REUSE_URL = "https://www.cdc.gov/other/agencymaterials.html"
ROBOTS_URL = "https://www.cdc.gov/robots.txt"
SECTION = "6.2.1 Limiting Exposure Time and/or Temperature"
PDF_PAGE = 107
PRINTED_PAGE = 75
MANIFEST_FIELDS = ["source", "query", "fetched_at_utc", "sha256", "license", "raw_file", "bytes"]
ATTRIBUTION = (
    "Source: CDC/NIOSH. Original guidance is available free on the CDC website. "
    "Use of this material does not imply endorsement by CDC, NIOSH, HHS, or the U.S. Government."
)
LIMITATION = (
    "This is general source guidance, not an assessment of worker safety or professional advice. "
    "For an emergency, contact local emergency medical services."
)
TOPICS = {
    "cooler_schedule": ("When possible, schedule hot jobs", {"schedule", "shift", "window", "timing", "cool", "cooler", "hottest", "morning", "evening", "heat", "work"}),
    "recovery": ("Provide cool areas", {"rest", "break", "recovery", "shade", "shaded", "cool", "cooling", "heat"}),
    "staffing": ("Add extra personnel", {"staff", "staffing", "personnel", "crew", "exposure", "reduce", "workers"}),
    "discomfort": ("Permit work interruption", {"discomfort", "break", "rest", "interrupt", "heat"}),
    "water": ("Increase workers", {"water", "drink", "hydration", "heat"}),
}
SYNONYMS = {"shifts": "shift", "windows": "window", "breaks": "break", "scheduling": "schedule", "scheduled": "schedule", "coolest": "cooler", "cooling": "cool", "hotter": "hottest", "resting": "rest"}
DOMAIN = {"heat", "hot", "shift", "window", "schedule", "rest", "break", "water", "hydration", "exposure", "forecast", "temperature", "cool", "cooler", "staffing"}
STOPWORDS = {"a", "an", "the", "to", "for", "of", "is", "it", "in", "and", "my", "me", "what", "how", "why", "can", "i", "we", "should", "be", "do", "does", "this", "that", "with", "about", "our", "are", "on", "please", "when"}


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    pending.replace(path)


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "SaayaShift/0.1 educational research; conservative one-time guidance fetch"})
    with urllib.request.urlopen(request, timeout=90) as response:
        if response.status != 200:
            raise RuntimeError(f"Guidance source returned HTTP {response.status}")
        return response.read()


def _normalize(text: str) -> str:
    # PDF line wrapping only; retain the original span separately for auditing.
    text = re.sub(r"\u00ad\s*", "", text)
    return re.sub(r"\s+", " ", text.replace("■", "")).strip()


def _fetch_sources(data_dir: Path, offline: bool = False) -> list[dict[str, Any]]:
    manifest = data_dir / "guidance_manifest.csv"
    rows = []
    if manifest.exists():
        with manifest.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            raw = data_dir / row["raw_file"]
            if not raw.is_file() or _sha(raw.read_bytes()) != row["sha256"]:
                raise ValueError(f"Guidance raw-file integrity failure: {row['raw_file']}")

    # Source policies and robots are retained alongside the document for audit.
    sources = [
        (ROBOTS_URL, "cdc-robots.txt", "CDC public access policy"),
        (REUSE_URL, "cdc-reuse.html", "CDC agency materials policy"),
        (SOURCE_URL, "niosh-2016-106.pdf", "Public domain; explicit NIOSH permission, PDF page 4"),
    ]
    for url, filename, license_name in sources:
        if any(row["query"] == url for row in rows):
            continue
        if offline:
            raise FileNotFoundError(f"Offline guidance cache missing {filename}")
        content = _download(url)
        if filename.endswith(".pdf") and not content.startswith(b"%PDF"):
            raise ValueError("NIOSH endpoint did not return a PDF")
        if filename == "cdc-robots.txt":
            from urllib.robotparser import RobotFileParser
            parser = RobotFileParser()
            parser.parse(content.decode("utf-8", errors="replace").splitlines())
            if not parser.can_fetch("SaayaShift", SOURCE_URL) or not parser.can_fetch("SaayaShift", REUSE_URL):
                raise ValueError("CDC robots policy does not allow the proposed guidance acquisition")
        relative = Path("raw/guidance") / filename
        target = data_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise ValueError(f"Unmanifested raw guidance file exists: {target}; do not overwrite evidence")
        target.write_bytes(content)
        rows.append({"source": "CDC/NIOSH", "query": url, "fetched_at_utc": _utc_now(), "sha256": _sha(content), "license": license_name, "raw_file": relative.as_posix(), "bytes": len(content)})
        # Persist provenance immediately, including before any later fetch fails.
        pending = manifest.with_suffix(".csv.tmp")
        with pending.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        pending.replace(manifest)
    return rows


def build_corpus(data_dir: Path = Path("data"), offline: bool = False) -> dict[str, Any]:
    """Fetch official bytes once, verify hashes, and extract a narrow approved corpus.

    Raises on unavailable sources or changed structure. Does not synthesize text.
    Writes a separate guidance_manifest.csv; the pipeline merges it into manifest.csv.
    """
    from pypdf import PdfReader

    data_dir = Path(data_dir)
    rows = _fetch_sources(data_dir, offline=offline)
    source = next(row for row in rows if row["query"] == SOURCE_URL)
    raw = data_dir / source["raw_file"]
    reader = PdfReader(io.BytesIO(raw.read_bytes()))
    permission_text = reader.pages[3].extract_text()
    if "public domain and may be freely copied or reprinted" not in _normalize(permission_text):
        raise ValueError("The expected explicit public-domain reuse statement is missing")
    page_text = reader.pages[PDF_PAGE - 1].extract_text()
    start_match = re.search(r"6\.2\.1\s+Limiting Exposure Time", page_text)
    end_match = re.search(r"6\.2\.2\s+Reducing Metabolic Heat Load", page_text)
    if not start_match or not end_match or end_match.start() <= start_match.end():
        raise ValueError("NIOSH section boundaries changed; manual source review required")
    section_start, section_end = start_match.start(), end_match.start()
    spans = list(re.finditer(r"■([^■]+)", page_text[section_start:section_end]))
    chunks = []
    for topic, (anchor, _) in TOPICS.items():
        matches = [span for span in spans if _normalize(span.group(1)).startswith(anchor)]
        if len(matches) != 1:
            raise ValueError(f"Expected one source bullet for {topic}; found {len(matches)}")
        match = matches[0]
        begin = section_start + match.start(1)
        end = section_start + match.end(1)
        original = page_text[begin:end]
        text = _normalize(original)
        if re.search(r"\d", text):
            raise ValueError(f"Numeric guidance excluded from corpus: {topic}")
        chunk_id = "niosh-6.2.1-" + _sha((source["sha256"] + original).encode())[:16]
        chunks.append({"chunk_id": chunk_id, "topic": topic, "text": text, "original_text": original,
            "source_title": SOURCE_TITLE, "source_url": SOURCE_URL + "#page=107", "section": SECTION,
            "printed_page": PRINTED_PAGE, "pdf_page": PDF_PAGE, "char_start": begin, "char_end": end,
            "source_sha256": source["sha256"], "raw_file": source["raw_file"], "fetched_at_utc": source["fetched_at_utc"],
            "page_text_sha256": _sha(page_text.encode()), "license": source["license"]})
    cleaned = data_dir / "cleaned/guidance/page-107.json"
    _write_json(cleaned, {"pdf_page": PDF_PAGE, "page_text": page_text, "source_sha256": source["sha256"], "extraction": "pypdf; zero-based Python character offsets into unchanged page_text"})
    destination = data_dir / "processed/guidance/corpus.jsonl"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".jsonl.tmp")
    temporary.write_text("".join(json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in chunks), encoding="utf-8")
    temporary.replace(destination)
    report = {"status": "PASS", "method": "extractive_retrieval", "llm_generation": "NOT IMPLEMENTED", "chunks": len(chunks), "source_sha256": source["sha256"], "source_url": SOURCE_URL, "attribution": ATTRIBUTION, "reuse_url": REUSE_URL, "manifest": "guidance_manifest.csv", "built_at_utc": _utc_now()}
    _write_json(data_dir / "processed/guidance/status.json", report)
    return report


def _load_chunks(data_dir: Path) -> list[dict[str, Any]]:
    chunks = [json.loads(line) for line in (data_dir / "processed/guidance/corpus.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    page = json.loads((data_dir / "cleaned/guidance/page-107.json").read_text(encoding="utf-8"))
    verified: dict[str, str] = {}
    for chunk in chunks:
        raw_file = chunk["raw_file"]
        if raw_file not in verified:
            verified[raw_file] = _sha((data_dir / raw_file).read_bytes())
        exact = page["page_text"][chunk["char_start"]:chunk["char_end"]]
        if (verified[raw_file] != chunk["source_sha256"] or page["source_sha256"] != chunk["source_sha256"] or
                _sha(page["page_text"].encode()) != chunk["page_text_sha256"] or exact != chunk["original_text"] or
                _normalize(exact) != chunk["text"] or re.search(r"\d", chunk["text"])):
            raise ValueError("Guidance evidence integrity failure")
    return chunks


def _tokens(question: str) -> set[str]:
    return {SYNONYMS.get(word, word) for word in re.findall(r"[a-z]+", question.lower())} - STOPWORDS


def _abstain(reason: str) -> dict[str, Any]:
    return {"answer": "I don't know. " + reason, "citations": [], "row_ids": [], "supported": False, "method": "abstention"}


def _numeric_summary(forecast: pd.DataFrame | None, plan: dict | None) -> tuple[str, list[str]]:
    if forecast is None or forecast.empty or not {"row_id", "apparent_temperature"}.issubset(forecast.columns):
        raise ValueError("processed forecast rows with row IDs and apparent_temperature are missing")
    rows = forecast.copy()
    if plan is not None:
        requested = plan.get("row_ids")
        if not isinstance(requested, list) or not requested:
            raise ValueError("the selected plan has no verifiable row IDs")
        requested = list(dict.fromkeys(str(value) for value in requested))
        rows = rows[rows["row_id"].astype(str).isin(requested)]
        if set(rows["row_id"].astype(str)) != set(requested):
            raise ValueError("some selected plan row IDs are absent from the supplied forecast")
    if rows["row_id"].isna().any() or rows["row_id"].astype(str).duplicated().any():
        raise ValueError("forecast row IDs are missing or duplicated")
    values = pd.to_numeric(rows["apparent_temperature"], errors="coerce")
    if values.isna().any() or not all(math.isfinite(float(v)) for v in values):
        raise ValueError("forecast values are missing or non-finite")
    if "estimated" in rows.columns and rows["estimated"].astype(str).str.lower().isin(["true", "1"]).any():
        raise ValueError("locally filled forecast values need explicit review")
    label = "selected window" if plan is not None else "supplied forecast rows"
    text = (f"For the {label}, code calculates mean apparent temperature {values.mean():.1f} °C "
            f"and maximum {values.max():.1f} °C across {len(rows)} hourly rows. "
            "These are weather-model values, not measured worker exposure or a medical safety threshold.")
    return text, rows["row_id"].astype(str).tolist()


def answer(question: str, forecast: pd.DataFrame | None = None, plan: dict | None = None, data_dir: Path = Path("data")) -> dict[str, Any]:
    """Answer narrow supported questions conservatively; never call an external LLM.

    Numerical answers require matching caller-supplied processed rows. The API does
    not claim multilingual embedding retrieval or a completed generation model.
    """
    if not isinstance(question, str) or not question.strip():
        return _abstain("Please ask a specific question about heat scheduling or the supplied forecast.")
    q = question.lower()
    if re.search(r"\b(ignore|override|pretend|fabricate|invent)\b|guarantee|prove.*safe|safe (?:to|for)|is .*safe|no (?:heat|health|illness).*risk|(?:heatstroke|heat stroke|unconscious|collapsed|fainted)|\bdiagnos|\bmedic|\bdosage|\bdeath|\bdied|\bprevent.*(?:illness|injury|death)", q):
        return _abstain("The evidence cannot establish individual safety, health outcomes, or medical treatment. For an emergency, contact local emergency medical services.")
    if re.search(r"\b(?:minutes?|litres?|liters?|cups?|degrees?|threshold|wbgt|heat index|probability|percent|percentage|how much|how many|risk score)\b", q):
        return _abstain("This corpus does not support numeric work/rest, hydration, illness-risk, or safety thresholds; consult qualified occupational health guidance.")
    if re.search(r"\d|\b(?:park|parks|trees|clinic|clinics|hospital|paid|salary|productivity|law|legal)\b|(?:skip|without).*(?:break|rest|water)", q):
        return _abstain("This narrow corpus does not establish that claim or the requested local, numeric, legal, or workplace condition.")
    tokens = _tokens(question)
    if not tokens & DOMAIN:
        return _abstain("The cleared corpus only covers selected general heat scheduling and recovery guidance.")
    try:
        chunks = _load_chunks(Path(data_dir))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return _abstain("Verified guidance files are unavailable or their integrity check failed; rebuild the guidance corpus.")
    ranked = []
    for chunk in chunks:
        topic_terms = TOPICS[chunk["topic"]][1]
        overlap = tokens & (_tokens(chunk["text"]) | topic_terms)
        substantive = overlap - {"heat", "work", "workers"}
        if substantive:
            ranked.append((len(substantive) + 0.2 * len(overlap), chunk))
    ranked.sort(key=lambda pair: (-pair[0], pair[1]["chunk_id"]))
    numeric_requested = bool(tokens & {"forecast", "temperature", "mean", "maximum", "average", "rank", "ranked", "ranking", "selected"})
    if not ranked and not numeric_requested:
        return _abstain("No passage meets the evidence threshold for this question; ask about cooler scheduling, rest areas, staffing, or water access.")
    row_ids: list[str] = []
    parts = []
    if numeric_requested:
        try:
            summary, row_ids = _numeric_summary(forecast, plan)
            parts.append(summary)
        except ValueError as error:
            return _abstain(str(error).capitalize() + ".")
    selected = [item[1] for item in ranked[:2]]
    if selected:
        parts.append("NIOSH general guidance: " + " ".join(chunk["text"] for chunk in selected))
    parts.extend([LIMITATION, ATTRIBUTION])
    citations = [{key: chunk[key] for key in ["chunk_id", "source_title", "source_url", "section", "printed_page", "pdf_page", "source_sha256", "char_start", "char_end"]} for chunk in selected]
    return {"answer": "\n\n".join(parts), "citations": citations, "row_ids": row_ids, "supported": True, "method": "extractive_retrieval"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build audited CDC/NIOSH guidance corpus")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    print(json.dumps(build_corpus(args.data_dir), indent=2))
