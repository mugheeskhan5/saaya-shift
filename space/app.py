"""SaayaShift Gradio evidence dashboard for a Hugging Face Space (ZeroGPU compatible).

Every view re-reads the evidence files copied from the Windows pipeline host by
scripts/space_sync.py. Nothing is hard-coded or simulated: if a file is missing or old,
the dashboard says so. Insight answers are extractive retrieval; GPU semantic ranking
only orders verified NIOSH excerpts and cannot add claims.
"""
import json
import html
import re
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import spaces
import torch
from transformers import AutoModel, AutoTokenizer
import gradio as gr
import pandas as pd
from saayashift.planner import rank_windows
from saayashift.insights import answer, _load_chunks, LIMITATION, ATTRIBUTION

DATA = ROOT / "data"
EVIDENCE = ROOT / "evidence"
TZ = "Asia/Karachi"
FORECAST_STALE_HOURS = 3
MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
# ZeroGPU emulates CUDA at startup; weights must be placed there before calls.
DEVICE = "cuda" if os.environ.get("SPACE_ID") or torch.cuda.is_available() else "cpu"
TOKENIZER = AutoTokenizer.from_pretrained(MODEL_ID, revision=MODEL_REVISION)
ENCODER = AutoModel.from_pretrained(MODEL_ID, revision=MODEL_REVISION, use_safetensors=True).to(DEVICE).eval()

RUN_HEADERS = ["Run", "Status", "Started (PKT)", "Finished (PKT)", "Errors"]


@spaces.GPU(duration=20)
def semantic_search(question, passages):
    """Run transformer inference and cosine ranking on the allocated GPU."""
    inputs = TOKENIZER([question] + passages, padding=True, truncation=True,
                       max_length=256, return_tensors="pt").to(DEVICE)
    with torch.inference_mode():
        hidden = ENCODER(**inputs).last_hidden_state
        mask = inputs["attention_mask"].unsqueeze(-1)
        embeddings = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1)
        embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)
        scores = (embeddings[1:] @ embeddings[0]).cpu().tolist()
    return sorted(enumerate(scores), key=lambda item: (-item[1], item[0]))


# ---- live readers: every call re-reads the synced files -------------------------------
def read_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def read_jsonl(path):
    records = []
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict):
                    records.append(record)
    except OSError:
        pass
    return records


def read_forecast():
    try:
        return pd.read_csv(DATA / "processed/forecast.csv")
    except (OSError, ValueError):
        return pd.DataFrame()


def timestamp(value):
    stamp = pd.to_datetime(value, utc=True, errors="coerce") if value else pd.NaT
    return "Unavailable" if pd.isna(stamp) else stamp.tz_convert(TZ).strftime("%d %b %Y, %H:%M PKT")


def age_hours(value):
    stamp = pd.to_datetime(value, utc=True, errors="coerce") if value else pd.NaT
    return None if pd.isna(stamp) else (pd.Timestamp.now(tz="UTC") - stamp).total_seconds() / 3600


def last_success(runs, status):
    for run in reversed(runs):
        ok = run.get("ok") is True or str(run.get("status", "")).lower() in {"completed", "success", "succeeded", "pass"}
        if ok:
            return run.get("finished_at_utc") or run.get("updated_at_utc") or run.get("started_at_utc")
    return status.get("last_success_utc")


def freshness():
    status = read_json(DATA / "status.json")
    runs = read_jsonl(DATA / "runs.jsonl")
    if not status:
        return "### Forecast: NO DATA\nThe evidence files have not been synced to this Space yet."
    source = status.get("sources", {}).get("forecast", {})
    age = age_hours(source.get("last_fetch_utc"))
    current = age is not None and 0 <= age <= FORECAST_STALE_HOURS and source.get("status") == "available"
    quality = status.get("quality", {})
    age_label = "Unavailable" if age is None else (f"{int(age * 60)} min" if age < 1 else f"{age:.1f} hours")
    return (
        f"### Forecast: {'Current' if current else 'STALE / unavailable'}\n"
        f"Fetched **{timestamp(source.get('last_fetch_utc'))}** · Age **{age_label}**  \n"
        f"Data quality: **{str(quality.get('status', 'unavailable')).upper()}** · "
        f"{quality.get('checks', '—')} checks · {quality.get('findings', '—')} findings  \n"
        f"Last successful pipeline run: **{timestamp(last_success(runs, status))}**\n\n"
        "_The pipeline runs hourly on the team's Windows host; its files are copied here after each completed run. "
        "If the pipeline or the copy stops, the age above keeps growing and this turns STALE. Nothing here is simulated._"
    )


def runs_table():
    rows = []
    for run in reversed(read_jsonl(DATA / "runs.jsonl")[-50:]):
        ok = run.get("ok")
        state = run.get("status") or ("success" if ok is True else "failure" if ok is False else "unknown")
        rows.append([str(run.get("run_id", "")), str(state), timestamp(run.get("started_at_utc")),
                     timestamp(run.get("finished_at_utc")), "; ".join(map(str, run.get("errors", [])))])
    return pd.DataFrame(rows, columns=RUN_HEADERS)


def quality_table():
    records = read_jsonl(DATA / "quality_log.jsonl")[-80:]
    if not records:
        return pd.DataFrame({"Info": ["No quality decisions synced yet."]})
    frame = pd.DataFrame(records)
    return frame.map(lambda v: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)


def evidence_view():
    return runs_table(), quality_table(), read_json(DATA / "status.json")


def model_view():
    report = read_json(EVIDENCE / "model_report.json")
    if not report:
        return "No evaluation evidence has been synced yet.", {}
    try:
        text = (
            "### Separate archived-series experiment\n"
            f"2025 held-out MAE **{report['model_mae_c']:.3f} °C**; declared H−24 baseline **{report['baseline_mae_c']:.3f} °C**. "
            f"Nominal 90% interval coverage **{report['interval_coverage']:.1%}**.\n\n"
            "This predicts archived weather-model output, not measured exposure or illness. "
            "The shift planner uses the provider's future forecasts separately."
        )
    except (KeyError, TypeError, ValueError):
        text = "The evaluation report is present but incomplete; see the JSON below."
    return text, report


# ---- planner and insight ----------------------------------------------------------------
def compare(duration, earliest, latest, day):
    if earliest >= latest:
        raise gr.Error("Latest finish must be later than earliest start.")
    try:
        selected_date = pd.Timestamp(day).date()
    except (ValueError, TypeError):
        raise gr.Error("Enter a working date as YYYY-MM-DD.")
    forecast = read_forecast()
    if forecast.empty:
        return [], gr.Dropdown(choices=[], value=None), [], "No forecast has been synced to this Space yet."
    future = forecast.loc[pd.to_datetime(forecast.timestamp_utc, utc=True) >= pd.Timestamp.now(tz="UTC").ceil("h")]
    windows = rank_windows(future, int(duration), int(earliest), int(latest), selected_date, selected_date)
    table = [[w["rank"], timestamp(w["start_local"]), timestamp(w["end_local"]),
              round(w["mean_c"], 2), round(w["peak_c"], 2)] for w in windows]
    options = [(f"#{w['rank']} · {timestamp(w['start_local'])} · {w['mean_c']:.1f} °C", w["window_id"]) for w in windows]
    message = (f"**{len(windows)} complete windows.** Ranked by mean, then peak, then earliest start."
               if windows else "No complete future windows meet these constraints. Change the date or hours.")
    return table, gr.Dropdown(choices=options, value=options[0][1] if options else None), windows, message


def inspect(selected, windows):
    return next((w for w in windows if w["window_id"] == selected), {})


def ask(question, selected, windows):
    plan = next((w for w in windows if w["window_id"] == selected), None)
    if plan is None and any(word in question.lower() for word in ["selected", "mean", "temperature", "forecast"]):
        return "Select a valid working window first.", {}
    forecast = read_forecast()
    response = answer(question, forecast if not forecast.empty else None, plan, data_dir=DATA)
    if response["supported"] and response["citations"]:
        # Conservative scope/abstention gate stays in charge. Semantic ranking only orders
        # its verified candidate excerpts; it cannot introduce new claims.
        chunks = _load_chunks(DATA)
        try:
            ranking = semantic_search(question, [c["text"] for c in chunks])
        except Exception:
            return "Semantic search is temporarily unavailable. Please retry; no unverified answer was substituted.", {"supported": False, "method": "retrieval_unavailable"}
        allowed = {c["chunk_id"]: c for c in response["citations"]}
        chosen = [chunks[i] for i, _ in ranking if chunks[i]["chunk_id"] in allowed]
        prefix = response["answer"].split("\n\n")[0] + "\n\n" if response["row_ids"] else ""
        response["answer"] = prefix + "NIOSH general guidance: " + " ".join(c["text"] for c in chosen) + "\n\n" + LIMITATION + "\n\n" + ATTRIBUTION
        response["citations"] = [allowed[c["chunk_id"]] for c in chosen]
        response["method"] = "scope_filtered_semantic_reranking"
        response["retrieval"] = {"model": MODEL_ID, "revision": MODEL_REVISION,
                                 "scores": [{"chunk_id": chunks[i]["chunk_id"], "cosine_similarity": score} for i, score in ranking]}
    citations = "\n\n".join(
        f"[{c['source_title']} · §{c['section']}, p. {c['printed_page']}]({c['source_url']})"
        for c in response["citations"]
    )
    return response["answer"] + "\n\n" + citations, response


UI_CSS = r"""
gradio-app { width:100%; min-width:0; }
.gradio-container .main, .gradio-container .contain { min-width:0!important; width:100%!important; padding:0!important; }
.gradio-container [role="tabpanel"] { min-width:0!important; }

.gradio-container { --ss-forest:#123e34; --ss-muted:#66776f; width:100%!important; min-width:0!important; max-width:1240px!important; margin:auto!important; padding:18px clamp(12px,2.4vw,32px) 30px!important; font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif!important; }
body, .gradio-container { background:#f6f7f2!important; }
.dark .gradio-container { --ss-forest:#b8e6d0; --ss-muted:#a5b5ab; background:#14231e!important; }
.ss-nav { display:flex; justify-content:space-between; align-items:center; gap:16px; padding:0 0 22px; border-bottom:1px solid #dce4db; }
.ss-brand {display:flex;align-items:center;gap:12px;font-weight:750;font-size:23px;letter-spacing:-1px;color:#153e34;}
.ss-mark {display:grid;place-items:center;width:39px;height:39px;border-radius:12px;background:#164e3c;color:#f6d78c;font-size:24px;box-shadow:0 5px 14px #164e3c20;}
.ss-nav-note {font-size:12px;color:#66776f;letter-spacing:.04em;}
.ss-location {padding:8px 13px;border:1px solid #dce4db;border-radius:30px;background:#fff;color:#355c4b;font-size:12px;font-weight:600;}
.ss-hero {position:relative;overflow:hidden;display:flex;align-items:center;justify-content:space-between;gap:24px;background:#123e34;border-radius:24px;padding:38px 42px;margin:15px 0 8px;color:#fff;}
.ss-eyebrow {font-size:11px;font-weight:750;letter-spacing:.16em;text-transform:uppercase;color:#c2d6a9;margin-bottom:14px;}
.ss-hero h1 {font-size:clamp(30px,4.2vw,50px);line-height:1.12;letter-spacing:-1.9px;font-weight:650;margin:0 0 15px;color:#fff;max-width:650px;}
.ss-hero h1 em {font-style:normal;color:#e9d291;}
.ss-hero p {color:#d0e0d5;font-size:14px;line-height:1.8;max-width:560px;margin:0;}
.ss-orbit {flex:0 0 180px;height:180px;border:1px solid #ffffff18;border-radius:50%;display:grid;place-items:center;position:relative;background:radial-gradient(circle,#efcf8620 0,transparent 68%);}
.ss-orbit:before {content:"";width:122px;height:122px;border:1px dashed #ffffff35;border-radius:50%;position:absolute;}
.ss-sun {height:73px;width:73px;background:#eed293;border-radius:50%;box-shadow:0 0 55px #e4c47725;}
.ss-orbit span {position:absolute;bottom:3px;background:#234e41;color:#d8e4d8;border:1px solid #ffffff20;padding:7px 12px;border-radius:24px;font-size:10px;letter-spacing:.08em;}
#freshness-card {border:1px solid #dce4db!important;border-radius:18px!important;background:#fff!important;padding:22px 26px!important;box-shadow:0 4px 18px #1b3e2a04;}
#freshness-card h3 {font-size:18px!important;letter-spacing:-.4px;color:var(--ss-forest)!important;margin-bottom:10px!important;}
#freshness-card p {line-height:1.95!important;color:var(--ss-muted);font-size:13px!important;}
#freshness-card strong {color:var(--ss-forest);font-weight:650;}
#freshness-card em {font-size:11px;line-height:1.65;display:block;max-width:920px;}
#refresh-freshness {align-self:flex-end;min-width:0!important;max-width:225px;margin-bottom:12px;background:transparent!important;border:1px solid #d3ddd2!important;border-radius:10px!important;box-shadow:none!important;color:var(--ss-forest)!important;font-size:12px!important;}
.gradio-container [role="tablist"] {gap:10px!important;border-bottom:1px solid #dce4db!important;padding:0 0 12px!important;margin:8px 0 16px!important;}
.gradio-container [role="tablist"] button {border:0!important;border-radius:10px!important;padding:11px 18px!important;color:var(--ss-muted)!important;font-size:13px!important;font-weight:600!important;transition:background .15s;}
.gradio-container [role="tablist"] button[aria-selected="true"] {background:#164e3c!important;color:#fff!important;box-shadow:0 3px 9px #164e3c15!important;}
.gradio-container .tabitem {padding:4px 0 0!important;border:0!important;background:transparent!important;}
.ss-section {margin:5px 0 21px;}
.ss-section .ss-kicker {color:#73845b;font-size:10px;letter-spacing:.14em;text-transform:uppercase;font-weight:750;}
.ss-section h2 {color:var(--ss-forest);font-size:25px;letter-spacing:-.8px;font-weight:650;margin:7px 0;}
.ss-section p {font-size:13px;color:var(--ss-muted);line-height:1.7;margin:0;}
#shift-controls {padding:22px!important;background:#fff!important;border:1px solid #dce4db!important;border-radius:16px!important;gap:20px!important;}
.gradio-container label span, .gradio-container .block-title {font-size:12px!important;font-weight:600!important;}
.gradio-container input[type=text], .gradio-container textarea {border-radius:9px!important;}
.gradio-container input[type=range] {accent-color:#21614b!important;}
#compare-action,#ask-action {border:1px solid #164e3c!important;border-radius:11px!important;background:#164e3c!important;color:white!important;font-weight:650!important;min-height:47px;box-shadow:0 4px 12px #164e3c14!important;transition:filter .15s,transform .15s;}
#compare-action:hover,#ask-action:hover {filter:brightness(1.15);transform:translateY(-1px);}
#compare-action {max-width:295px!important;margin:5px 0 10px;}
#ranking-message {color:var(--ss-forest);font-size:13px;padding:8px 0!important;}
.gradio-container .ss-table {border:1px solid #dce4db!important;border-radius:14px!important;overflow:hidden;background:#fff!important;}
.gradio-container .ss-table th {background:#edf2e9!important;color:#345442!important;font-weight:650!important;font-size:12px!important;}
.gradio-container .ss-table td {font-size:12px!important;padding-top:13px!important;padding-bottom:13px!important;}
.gradio-container .ss-table tbody tr:nth-child(even) {background:#f8faf6;}
.gradio-container .ss-table table {font-variant-numeric:tabular-nums;}
.gradio-container .ss-evidence {border:1px solid #dce4db!important;border-radius:14px!important;overflow:hidden;}
.gradio-container .ss-evidence .json-holder {max-height:360px;overflow:auto;}
#scope-note {padding:17px 20px!important;border:1px solid #e5d9b8!important;border-left:3px solid #b79b56!important;border-radius:12px!important;background:#faf5e8!important;font-size:12px!important;color:#68582f!important;margin:12px 0!important;}
#question-box {border-radius:14px!important;border:1px solid #dce4db!important;background:#fff!important;padding:18px!important;}
#answer-card {border:1px solid #dce4db!important;background:#fff!important;border-radius:15px!important;padding:24px!important;min-height:90px;line-height:1.85!important;}
#answer-card:empty:before {content:"Your source-backed answer will appear here.";color:#7a897e;font-size:13px;}
#retrieval-note {font-size:12px!important;line-height:1.8!important;color:var(--ss-muted);padding:17px 20px!important;background:#edf2e9!important;border-radius:12px!important;}
#model-summary {padding:25px!important;border:1px solid #dce4db!important;border-radius:16px!important;background:#fff!important;line-height:1.9!important;}
.ss-footer {border-top:1px solid #dce4db;padding-top:22px!important;margin-top:28px!important;color:var(--ss-muted)!important;font-size:11px!important;line-height:1.85!important;}
.ss-footer a {color:var(--ss-forest)!important;text-decoration:underline;text-underline-offset:3px;}
.ss-footer-secondary {color:var(--ss-muted)!important;font-size:11px!important;line-height:1.8!important;}
.gradio-container :is(button,input,textarea,[role=tab]):focus-visible {outline:3px solid #b6964e!important;outline-offset:3px!important;}
.dark .ss-brand {color:#d8e8db;}
.dark .ss-nav-note {color:#d8e8db;}
.dark :is(#freshness-card,#shift-controls,#question-box,#answer-card,#model-summary) {background:#1b3027!important;border-color:#385044!important;}
.dark .ss-table {background:#1b3027!important;border-color:#385044!important;}
.dark .ss-location {background:#233a2d!important;color:#cbdaca!important;border-color:#385044;}
.dark #retrieval-note {background:#233a2d!important;color:#cbdaca!important;border-color:#385044;}
.dark .ss-table th {background:#294234!important;color:#d8e8db!important;}
.dark .ss-table tbody tr:nth-child(even) {background:#20362b;}
.dark #scope-note {background:#353022!important;color:#e7d8b0!important;}
@media(max-width:700px){.gradio-container{padding:14px 16px 25px!important;}.ss-nav-note,.ss-orbit{display:none;}.ss-brand{font-size:21px;}.ss-location{font-size:10px;padding:7px 9px;}.ss-hero{padding:28px 24px;border-radius:18px;}.ss-hero h1{letter-spacing:-1px;}.ss-hero p{font-size:13px;}#freshness-card{padding:18px!important;}#shift-controls{padding:16px!important;gap:14px!important;}[role="tablist"]{gap:3px!important;flex-wrap:wrap!important;}[role="tablist"] button{font-size:11px!important;padding:9px 10px!important;}#compare-action{max-width:none!important;}.ss-section h2{font-size:23px;}}
@media(prefers-reduced-motion:reduce){*{transition:none!important;scroll-behavior:auto!important;}}

/* Refined workspace: compact overview, readable metrics and progressive detail. */
.gradio-container {padding-top:18px!important; --ss-border:#dbe4d9;}
.ss-nav {padding-bottom:16px;}
.ss-hero {padding:26px 32px;margin-top:8px;min-height:160px;border-radius:18px;}
.ss-hero h1 {font-size:clamp(29px,3.2vw,40px);line-height:1.15;letter-spacing:-1.3px;margin-bottom:10px;}
.ss-hero h1 br {display:none;}
.ss-hero p {font-size:13px;line-height:1.65;max-width:680px;}
.ss-eyebrow {margin-bottom:10px;font-size:10px;}
.ss-orbit {flex-basis:118px;height:118px;}
.ss-orbit:before {width:91px;height:91px;}
.ss-sun {width:55px;height:55px;}
.ss-orbit span {display:none;}
.ss-status-grid {display:grid;grid-template-columns:1fr 1fr 1.15fr;gap:14px;margin:8px 0 0;}
.ss-stat {padding:20px 22px;background:#fff;border:1px solid var(--ss-border);border-radius:15px;box-shadow:0 3px 12px #143c2503;min-width:0;}
.ss-stat-label {display:block;text-transform:uppercase;letter-spacing:.09em;font-size:10px;color:#667b6b;font-weight:700;margin-bottom:12px;}
.ss-stat strong {display:flex;align-items:center;gap:9px;color:#163f32;font-size:23px;font-weight:650;line-height:1.35;letter-spacing:-.5px;overflow-wrap:anywhere;}
.ss-stat p {margin:9px 0 5px;font-size:12px;line-height:1.6;color:#566d5e;}
.ss-stat small {display:block;font-size:10px;color:#718273;line-height:1.7;}
.ss-stat .ss-run-time {font-size:18px;line-height:1.6;letter-spacing:-.2px;}
.ss-dot {width:8px;height:8px;background:#26805b;border-radius:50%;flex-shrink:0;box-shadow:0 0 0 4px #26805b12;}
.ss-attention .ss-dot {background:#a87522;box-shadow:0 0 0 4px #a8752215;}
.ss-attention strong {color:#8b5d1a;}
.ss-stat-empty {grid-column:1/-1;}
.ss-details {border:1px solid var(--ss-border)!important;border-radius:12px!important;background:transparent!important;overflow:hidden;}
.ss-details > button {padding:13px 17px!important;min-height:44px!important;}
.ss-details .label-wrap {color:var(--ss-muted)!important;font-size:12px!important;}
#freshness-card {border:none!important;box-shadow:none!important;border-radius:0!important;background:transparent!important;padding:4px 18px 14px!important;}
#refresh-freshness {margin:0 0 10px;min-height:36px!important;}
[role="tablist"] {margin-top:0!important;padding-bottom:10px!important;gap:7px!important;}
[role="tablist"] button {padding:10px 17px!important;min-height:40px;border-radius:9px!important;}
.ss-section {margin:9px 0 18px;}
.ss-section h2 {font-size:25px;margin-top:7px;}
.ss-window-card {background:#eaf1e5;border:1px solid #ccdbc3;border-radius:16px;padding:22px 25px;margin:10px 0;}
.ss-window-heading {display:flex;justify-content:space-between;align-items:center;gap:15px;margin-bottom:22px;}
.ss-window-tag {font-size:10px;letter-spacing:.1em;font-weight:750;color:#315a39;}
.ss-window-context {font-size:10px;color:#62765c;}
.ss-window-metrics {display:grid;grid-template-columns:1.6fr 1fr 1fr;gap:24px;}
.ss-window-metrics > div {min-width:0;}
.ss-window-metrics > div+div {border-left:1px solid #ccdbc3;padding-left:26px;}
.ss-window-metrics span {display:block;font-size:11px;color:#59724f;line-height:1.8;}
.ss-window-metrics strong {display:block;color:#173f2b;font-size:33px;letter-spacing:-1.1px;font-weight:650;margin:4px 0;line-height:1.35;}
.ss-window-metrics strong small {font-size:17px;font-weight:500;letter-spacing:0;}
.ss-window-metrics .ss-window-time strong {font-size:20px;letter-spacing:-.5px;line-height:1.5;}
.ss-window-limit {font-size:10px!important;color:#5a7051!important;border-top:1px solid #ccdbc3;margin:20px 0 0!important;padding-top:12px;}
.ss-window-empty {display:flex;align-items:center;gap:16px;border:1px dashed #cdd9c9;background:#f1f5ee;border-radius:14px;padding:19px 22px;margin:8px 0;}
.ss-window-empty > span {font-size:27px;color:#6c8561;}
.ss-window-empty strong {font-size:13px;color:var(--ss-forest);font-weight:600;}
.ss-window-empty p {font-size:11px;color:var(--ss-muted);line-height:1.7;margin:5px 0 0;}
.ss-ranking-table [role="gridcell"][data-row="0"] {background:#edf4e7!important;font-weight:650!important;color:#1d5037!important;border-top:1px solid #cbdec0!important;border-bottom:1px solid #cbdec0!important;}
.ss-ranking-table td:first-child {font-weight:650!important;}
.ss-table td {font-size:13px!important;padding-top:12px!important;padding-bottom:12px!important;}
.ss-table th {font-size:11px!important;letter-spacing:.025em;}
.ss-table {overflow-x:auto;}
input[type=text],textarea {font-size:14px!important;line-height:1.65!important;}
.ss-evidence {max-height:380px;overflow:auto!important;background:#fbfcf9!important;}
.ss-evidence .json-holder {max-height:none;}
.ss-results-label {margin:14px 0 5px;display:flex;justify-content:space-between;gap:16px;color:#48614d;font-size:11px;}
.ss-results-label strong {font-weight:650;letter-spacing:.025em;}
.ss-results-label span {color:#748273;}
#answer-card {min-height:0;border:none!important;padding:0!important;background:transparent!important;}
#answer-card:not(:empty) {padding:22px!important;border:1px solid var(--ss-border)!important;background:#fff!important;}
.ss-footer {padding-top:17px!important;margin-top:16px!important;}
.dark {--ss-border:#355044;}
.dark .ss-stat {background:#193027;border-color:#355044;}
.dark .ss-stat strong {color:#d7e8d8;}
.dark .ss-stat :is(p,small,.ss-stat-label) {color:#a8bda9;}
.dark .ss-attention strong {color:#e6c48e;}
.dark .ss-window-card {background:#203f2b;border-color:#3a5a3d;}
.dark .ss-window-metrics strong {color:#d6e8c5;}
.dark .ss-window-tag {color:#d6e8c5;}
.dark .ss-window-metrics span {color:#b2c3a6!important;}
.dark .ss-window-context {color:#b2c3a6!important;}
.dark .ss-window-limit {color:#b2c3a6!important;}
.dark .ss-window-metrics > div+div {border-color:#3e5e3f;}
.dark .ss-window-limit {border-color:#3e5e3f;}
.dark .ss-window-empty {background:#1b3023;border-color:#3c5640;}
.dark .ss-ranking-table [role="gridcell"][data-row="0"] {background:#254731!important;color:#d6e8c5!important;border-color:#406444!important;}
.dark .ss-evidence {background:#15271f!important;}
.dark #answer-card:not(:empty) {background:#193027!important;}
.dark .ss-results-label {color:#c0d2bd;}
@media(max-width:700px){
 .ss-hero{padding:23px 22px;min-height:0;}.ss-hero h1{font-size:30px;max-width:360px;}.ss-hero h1 br{display:block;}.ss-hero p br{display:none;}
 .ss-status-grid{grid-template-columns:1fr;gap:9px;}.ss-stat{padding:16px 18px;}.ss-stat-label{font-size:10px;margin-bottom:7px;}.ss-stat strong{font-size:21px;}.ss-stat p{margin-top:6px;}.ss-stat small{font-size:11px;}
 .ss-window-card{padding:19px 18px;}.ss-window-heading{align-items:flex-start;margin-bottom:16px;}.ss-window-context{display:none;}.ss-window-metrics{grid-template-columns:1fr 1fr;gap:16px;}.ss-window-metrics .ss-window-time{grid-column:1/-1;}.ss-window-metrics > div+div{padding-left:0;border:0;}.ss-window-metrics > div:last-child{border-left:1px solid #ccdbc3;padding-left:18px;}.ss-window-metrics strong{font-size:30px;}.ss-window-metrics .ss-window-time strong{font-size:19px;}
 .ss-results-label{flex-direction:column;gap:4px;}.ss-section h2{font-size:23px;}[role="tablist"] button{padding:9px 12px!important;}.ss-evidence{max-height:300px;}
}
"""



# Presentation-only renderers. Inputs are existing UI outputs; no data acquisition,
# ranking, freshness decisions, retrieval, or persisted state is performed here.
def render_status_cards(text):
    text = str(text or "")
    values = re.findall(r"\*\*(.*?)\*\*", text)
    heading = text.split("\n", 1)[0].removeprefix("### Forecast: ")
    if len(values) < 4:
        return '<div class="ss-status-grid"><div class="ss-stat ss-stat-empty"><span class="ss-stat-label">Forecast availability</span><strong>No data available</strong><p>Open the source details below for the recorded status.</p></div></div>'
    fetched, age, quality, success = [html.escape(v) for v in values[:4]]
    quality_detail = re.search(r"· ([^\n]+)  \nLast successful", text)
    detail = html.escape(quality_detail.group(1)) if quality_detail else "See recorded source details"
    current = heading == "Current"
    tone = "ss-current" if current else "ss-attention"
    return (
        '<div class="ss-status-grid">'
        f'<div class="ss-stat {tone}"><span class="ss-stat-label">Forecast freshness</span><strong><span class="ss-dot" aria-hidden="true"></span>{html.escape(heading)}</strong><p>Age {age}</p><small>Fetched {fetched}</small></div>'
        f'<div class="ss-stat"><span class="ss-stat-label">Data quality</span><strong>{quality}</strong><p>{detail}</p><small>Latest recorded quality assessment</small></div>'
        f'<div class="ss-stat"><span class="ss-stat-label">Last successful run</span><strong class="ss-run-time">{success}</strong><p>Pipeline evidence received by this app</p><small>All times shown in Pakistan Standard Time</small></div>'
        '</div>'
    )


def render_selected_window(plan):
    if not isinstance(plan, dict) or not plan:
        return '<div class="ss-window-empty"><span aria-hidden="true">◷</span><div><strong>Your selected shift, at a glance</strong><p>Compare windows and choose one to view its recorded times and temperatures here.</p></div></div>'
    esc = lambda value: html.escape(str(value))
    # Display the already-ranked selection and existing metrics; do not rerank it.
    return (
        '<div class="ss-window-card">'
        f'<div class="ss-window-heading"><span class="ss-window-tag">SELECTED WINDOW · RANK {esc(plan.get("rank", "—"))}</span><span class="ss-window-context">Karachi · forecast apparent temperature</span></div>'
        '<div class="ss-window-metrics">'
        f'<div class="ss-window-time"><span>Starts</span><strong>{esc(timestamp(plan.get("start_local")))}</strong><span>Finishes {esc(timestamp(plan.get("end_local")))}</span></div>'
        f'<div><span>Mean feels-like</span><strong>{esc(format(plan["mean_c"], ".2f"))}<small> °C</small></strong><span>Across the selected shift</span></div>'
        f'<div><span>Peak feels-like</span><strong>{esc(format(plan["peak_c"], ".2f"))}<small> °C</small></strong><span>Highest hourly forecast</span></div>'
        '</div><p class="ss-window-limit">A comparison of forecast heat, not a safe-work certification.</p></div>'
    )


def ui_theme():
    return gr.themes.Base(primary_hue="emerald", secondary_hue="stone", neutral_hue="stone").set(
        body_background_fill="#f5f6f1", body_background_fill_dark="#10231c",
        block_background_fill="#ffffff", block_background_fill_dark="#193027",
        block_label_background_fill="transparent", block_label_background_fill_dark="transparent",
        block_label_text_color="#455b4f", block_label_text_color_dark="#c2d6c7",
        input_background_fill="#f8faf6", input_background_fill_dark="#14271f",
        block_radius="14px", button_primary_background_fill="#174f3c",
        button_primary_background_fill_dark="#174f3c")


def build():
    with gr.Blocks(title="SaayaShift | Karachi") as demo:
        gr.HTML('<div class="ss-nav"><div class="ss-brand"><span class="ss-mark" aria-hidden="true">☀</span>SaayaShift</div><span class="ss-nav-note">HEAT-AWARE WORK PLANNING</span><span class="ss-location">Karachi &nbsp;·&nbsp; PKT / UTC+5</span></div><div class="ss-hero"><div><div class="ss-eyebrow">A clearer outlook for outdoor work</div><h1>Plan the day.<br> Work around <em>the heat.</em></h1><p>Compare complete shift windows using forecast temperatures.<br> Make informed decisions with traceable evidence behind every comparison.</p></div><div class="ss-orbit" aria-hidden="true"><div class="ss-sun"></div><span>FORECAST → COMPARE → PLAN</span></div></div>')
        initial_status = freshness()
        status_cards = gr.HTML(render_status_cards(initial_status), elem_id="status-overview")
        with gr.Accordion("Source freshness & recorded status", open=False, elem_classes=["ss-details"]):
            status = gr.Markdown(initial_status, elem_id="freshness-card")
        status.change(render_status_cards, inputs=status, outputs=status_cards)
        refresh = gr.Button("↻  Refresh freshness display", elem_id="refresh-freshness")
        refresh.click(freshness, outputs=status)
        timer = gr.Timer(60)
        timer.tick(freshness, outputs=status)
        with gr.Tab("Compare shifts"):
            gr.HTML("<div class=\"ss-section\"><div class=\"ss-kicker\">01 / Planning desk</div><h2>Find your working window</h2><p>Choose a date, set your hours, and compare the complete shifts available in the forecast.</p></div>")
            with gr.Row(elem_id="shift-controls"):
                day = gr.Textbox(label="Working date (YYYY-MM-DD)", value=pd.Timestamp.now(tz=TZ).date().isoformat())
                duration = gr.Slider(1, 12, value=4, step=1, label="Shift duration (hours)")
                earliest = gr.Slider(0, 23, value=6, step=1, label="Earliest start (PKT hour)")
                latest = gr.Slider(1, 24, value=18, step=1, label="Latest finish (PKT hour)")
            compare_button = gr.Button("Compare working windows  →", variant="primary", elem_id="compare-action")
            message = gr.Markdown(elem_id="ranking-message")
            selected_summary = gr.HTML(render_selected_window({}), elem_id="selected-summary")
            gr.HTML('<div class="ss-results-label"><strong>Complete working windows</strong><span>Ordered by mean · then peak · then earliest start</span></div>')
            table = gr.Dataframe(headers=["Rank", "Start", "End", "Mean °C", "Peak °C"], interactive=False, elem_classes=["ss-table", "ss-ranking-table"])
            selected = gr.Dropdown(label="Selected window", choices=[])
            windows = gr.State([])
            with gr.Accordion("Selected window · source rows & calculation evidence", open=False, elem_classes=["ss-details"]):
                selected_evidence = gr.JSON(label="Selected window and source row IDs", elem_classes=["ss-evidence"])
            selected_evidence.change(render_selected_window, inputs=selected_evidence, outputs=selected_summary)
            compare_button.click(compare, [duration, earliest, latest, day], [table, selected, windows, message])
            demo.load(compare, [duration, earliest, latest, day], [table, selected, windows, message])
            for control in [duration, earliest, latest, day]:
                control.change(compare, [duration, earliest, latest, day], [table, selected, windows, message])
            selected.change(inspect, [selected, windows], selected_evidence)
            gr.Markdown("**Lower forecast heat does not certify safe working conditions.** One Karachi weather grid; individual health, workload, clothing and on-site shade are not assessed.", elem_id="scope-note")
        with gr.Tab("Ask the evidence"):
            gr.HTML("<div class=\"ss-section\"><div class=\"ss-kicker\">02 / Evidence assistant</div><h2>Ask with confidence. Check the source.</h2><p>Explore the guidance behind heat-aware scheduling, with original citations and traceable forecast values.</p></div>")
            gr.Markdown("Verified NIOSH excerpts with GPU semantic ranking and code-calculated values. Extractive answers; no LLM generation is claimed. Search may queue when shared GPU capacity is busy. Unsupported questions get \"I don't know\".", elem_id="retrieval-note")
            question = gr.Textbox(label="Question", value="Why schedule hot jobs during cooler parts of the day?", max_length=2000, elem_id="question-box")
            ask_button = gr.Button("Check evidence  →", variant="primary", elem_id="ask-action")
            response = gr.Markdown(elem_id="answer-card")
            with gr.Accordion("Answer evidence · citations & source rows", open=False, elem_classes=["ss-details"]):
                response_evidence = gr.JSON(label="Answer evidence", elem_classes=["ss-evidence"])
            ask_button.click(ask, [question, selected, windows], [response, response_evidence])
        with gr.Tab("Model evaluation"):
            gr.HTML("<div class=\"ss-section\"><div class=\"ss-kicker\">03 / Research & validation</div><h2>The experiment, in perspective.</h2><p>Explore the frozen evaluation results and their limits. This experiment is separate from the live shift planner.</p></div>")
            model_text = gr.Markdown(elem_id="model-summary")
            with gr.Accordion("Frozen report · full evaluation evidence", open=False, elem_classes=["ss-details"]):
                model_json = gr.JSON(label="Frozen evaluation report", elem_classes=["ss-evidence"])
            demo.load(model_view, outputs=[model_text, model_json])
        with gr.Tab("Pipeline evidence"):
            gr.HTML("<div class=\"ss-section\"><div class=\"ss-kicker\">04 / Pipeline observability</div><h2>Follow the evidence trail.</h2><p>Inspect recorded runs, quality decisions, and the status received from the pipeline.</p></div>")
            gr.Markdown("Real hourly run history and Data Quality Agent decisions, copied unchanged from the Windows host's Prefect pipeline. Gaps, failures and delays are shown as recorded.")
            runs_out = gr.Dataframe(label="Pipeline runs (latest 50)", headers=RUN_HEADERS, interactive=False, elem_classes=["ss-table"])
            quality_out = gr.Dataframe(label="Latest quality decisions (80)", interactive=False, elem_classes=["ss-table"])
            with gr.Accordion("Recorded pipeline status · full source record", open=False, elem_classes=["ss-details"]):
                status_out = gr.JSON(label="Recorded pipeline status", elem_classes=["ss-evidence"])
            demo.load(evidence_view, outputs=[runs_out, quality_out, status_out])
            timer.tick(evidence_view, outputs=[runs_out, quality_out, status_out])
        gr.Markdown("Weather: [Open-Meteo](https://open-meteo.com/), CC BY 4.0. Guidance: CDC/NIOSH, public domain; no agency endorsement. [Original NIOSH guidance](https://www.cdc.gov/niosh/docs/2016-106/pdfs/2016-106.pdf).", elem_classes=["ss-footer"])
        gr.Markdown("Semantic search: [sentence-transformers/all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2), Apache 2.0. Embedding similarity is not a safety probability.", elem_classes=["ss-footer-secondary"])
    return demo


demo = build()
if __name__ == "__main__":
    demo.launch(css=UI_CSS, theme=ui_theme(),
                server_name=os.environ.get("GRADIO_SERVER_NAME", "0.0.0.0"),
                server_port=int(os.environ.get("PORT", "7860")))
