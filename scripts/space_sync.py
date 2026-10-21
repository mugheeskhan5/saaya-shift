"""Publish SaayaShift evidence to a Hugging Face Space.

Standalone helper. It is NOT imported by the pipeline, the Prefect flow or the app, so a
failure here can never affect data acquisition, quality checks or the hourly runs. It only
READS local evidence files and uploads copies. It never edits or fabricates any data.

Commands (run from the repo root):
  python scripts/space_sync.py bundle                      build work/space_bundle, no network
  python scripts/space_sync.py init --space USER/NAME      first full upload of the bundle
  python scripts/space_sync.py once --space USER/NAME      manual push of the latest evidence
  python scripts/space_sync.py loop --space USER/NAME      automatic push after each new run

The Hugging Face token is read only from the HF_TOKEN environment variable.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / "work" / "operations"
LOG = OPS / "space_sync.log"
STATE = OPS / "space_sync_state.json"
BUNDLE = ROOT / "work" / "space_bundle"

# Files the dashboard re-reads on every run. Pushed unchanged, byte for byte.
DYNAMIC = [
    "data/status.json",
    "data/runs.jsonl",
    "data/quality_log.jsonl",
    "data/processed/forecast.csv",
    "evidence/model_report.json",
]
# Files the Space needs once (code, static data, source guidance).
STATIC_FILES = [
    "data/guidance_manifest.csv",
    "data/manifest.csv",
    "ATTRIBUTION.md",
    "DATASET_DECLARATION.md",
]
# (source in repo, path inside the Space): the Gradio app and its own requirements live in space/.
RENAMED_FILES = [
    ("space/app.py", "app.py"),
    ("space/requirements.txt", "requirements.txt"),
]
# The insight code verifies raw PDF -> cleaned page -> corpus hashes, so all three layers ship.
STATIC_DIRS = ["saayashift", "data/processed/guidance", "data/cleaned/guidance", "data/raw/guidance"]

SPACE_README = """---
title: SaayaShift Karachi
emoji: 🌤️
colorFrom: green
colorTo: green
sdk: gradio
sdk_version: 6.30.0
python_version: "3.12"
app_file: app.py
pinned: false
---

# SaayaShift - Karachi shift planner (HackInsight 2026)

Gradio evidence dashboard. Data is produced by an hourly Prefect pipeline on the team's
Windows host and copied here unchanged by `scripts/space_sync.py`. The Pipeline evidence tab
shows the real run history and the time of the last successful run. Insight answers are
extractive retrieval only; no language-model generation is claimed.
"""


def log(message: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {message}"
    print(line, flush=True)
    try:
        OPS.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def collect() -> dict[str, bytes]:
    """Read every dynamic file once and check that it is complete and parseable."""
    files: dict[str, bytes] = {}
    for rel in DYNAMIC:
        path = ROOT / rel
        if not path.is_file():
            raise ValueError(f"missing file: {rel}")
        files[rel] = path.read_bytes()
    for rel in ("data/status.json", "evidence/model_report.json"):
        if not isinstance(json.loads(files[rel].decode("utf-8")), dict):
            raise ValueError(f"{rel} is not a JSON object")
    lines = [ln for ln in files["data/runs.jsonl"].decode("utf-8").splitlines() if ln.strip()]
    if not lines:
        raise ValueError("runs.jsonl has no records")
    for ln in lines:
        json.loads(ln)
    for ln in files["data/quality_log.jsonl"].decode("utf-8").splitlines():
        if ln.strip():
            json.loads(ln)
    if len(files["data/processed/forecast.csv"]) < 200:
        raise ValueError("forecast.csv looks empty")
    return files


def signature(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for rel in sorted(files):
        digest.update(rel.encode("utf-8"))
        digest.update(hashlib.sha256(files[rel]).digest())
    return digest.hexdigest()


def latest_run_id(files: dict[str, bytes]) -> str:
    lines = [ln for ln in files["data/runs.jsonl"].decode("utf-8").splitlines() if ln.strip()]
    return str(json.loads(lines[-1]).get("run_id", "unknown"))


def read_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_state(sig: str, run_id: str) -> None:
    try:
        OPS.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps({"signature": sig, "run_id": run_id,
                                     "pushed_at_utc": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
    except OSError as exc:
        log(f"WARN could not write state: {exc}")


def api_and_token():
    token = os.environ.get("HF_TOKEN", "").strip()
    if not token:
        raise SystemExit("HF_TOKEN is not set. In PowerShell: $env:HF_TOKEN = 'hf_...' (never commit it).")
    try:
        from huggingface_hub import HfApi
    except ImportError:
        raise SystemExit("huggingface_hub is missing. Run: pip install huggingface_hub")
    return HfApi(token=token)


def push_dynamic(api, space: str, files: dict[str, bytes], run_id: str) -> None:
    from huggingface_hub import CommitOperationAdd
    operations = [CommitOperationAdd(path_in_repo=rel, path_or_fileobj=io.BytesIO(data)) for rel, data in files.items()]
    api.create_commit(repo_id=space, repo_type="space", operations=operations,
                      commit_message=f"Sync evidence after pipeline run {run_id}")


def build_bundle() -> Path:
    resolved = BUNDLE.resolve()
    if resolved.parent != (ROOT / "work").resolve():
        raise SystemExit(f"Refusing to clear unexpected folder: {resolved}")
    if BUNDLE.exists():
        shutil.rmtree(BUNDLE)
    BUNDLE.mkdir(parents=True)
    copied: list[tuple[str, int]] = []
    for rel in STATIC_FILES + DYNAMIC:
        src = ROOT / rel
        if not src.is_file():
            log(f"WARN skipped missing file: {rel}")
            continue
        dest = BUNDLE / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    for source_rel, bundle_rel in RENAMED_FILES:
        src = ROOT / source_rel
        if not src.is_file():
            raise SystemExit(f"Required Space file is missing: {source_rel}")
        dest = BUNDLE / bundle_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    for rel in STATIC_DIRS:
        src = ROOT / rel
        if not src.is_dir():
            log(f"WARN skipped missing folder: {rel}")
            continue
        shutil.copytree(src, BUNDLE / rel, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.tmp"))
    (BUNDLE / "README.md").write_text(SPACE_README, encoding="utf-8")
    total = 0
    for path in sorted(BUNDLE.rglob("*")):
        if path.is_file():
            size = path.stat().st_size
            total += size
            copied.append((path.relative_to(BUNDLE).as_posix(), size))
    for rel, size in copied:
        print(f"  {size / 1024:10.1f} KB  {rel}")
    log(f"Bundle ready at {BUNDLE}: {len(copied)} files, {total / 1024 / 1024:.1f} MB")
    return BUNDLE


def cmd_init(space: str) -> None:
    api = api_and_token()
    files = collect()
    folder = build_bundle()
    api.upload_folder(repo_id=space, repo_type="space", folder_path=str(folder),
                      commit_message="Initial SaayaShift Space bundle")
    write_state(signature(files), latest_run_id(files))
    log(f"Initial upload finished: https://huggingface.co/spaces/{space}")


def cmd_once(space: str) -> None:
    api = api_and_token()
    files = collect()
    push_dynamic(api, space, files, latest_run_id(files))
    write_state(signature(files), latest_run_id(files))
    log(f"Manual sync finished (run {latest_run_id(files)}): https://huggingface.co/spaces/{space}")


def cmd_loop(space: str, interval: int) -> None:
    api = api_and_token()
    log(f"Auto-sync started for {space}; checking every {interval}s. Ctrl+C to stop.")
    while True:
        try:
            first = collect()
            time.sleep(8)  # let a run that is still writing files finish
            second = collect()
            sig = signature(second)
            if signature(first) != sig:
                log("Files changed while reading (run in progress); will retry next cycle.")
            elif read_state().get("signature") == sig:
                pass  # nothing new since the last successful push
            else:
                run_id = latest_run_id(second)
                push_dynamic(api, space, second, run_id)
                write_state(sig, run_id)
                log(f"Pushed evidence for run {run_id}.")
        except KeyboardInterrupt:
            log("Auto-sync stopped by user.")
            return
        except Exception as exc:  # never crash the loop; the pipeline is unaffected
            log(f"WARN sync attempt failed, will retry: {type(exc).__name__}: {exc}")
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            log("Auto-sync stopped by user.")
            return


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["bundle", "init", "once", "loop"])
    parser.add_argument("--space", default=os.environ.get("SAAYASHIFT_SPACE_ID", ""), help="USER/SPACE_NAME")
    parser.add_argument("--interval", type=int, default=300, help="loop check interval in seconds")
    args = parser.parse_args()
    if args.command == "bundle":
        collect()
        build_bundle()
        return 0
    if "/" not in args.space:
        raise SystemExit("Give the Space as --space USER/NAME (or set SAAYASHIFT_SPACE_ID).")
    if args.command == "init":
        cmd_init(args.space)
    elif args.command == "once":
        cmd_once(args.space)
    else:
        cmd_loop(args.space, max(60, args.interval))
    return 0


if __name__ == "__main__":
    sys.exit(main())
