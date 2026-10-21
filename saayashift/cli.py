"""Reproducible command line entry points and honest local run records."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import time
from pathlib import Path
import psutil
from .data import run_data, atomic_json, verify_manifest, read_manifest, MANIFEST_FIELDS
from .quality import utc_now


def merge_guidance_manifest(data_dir):
    path = data_dir / "guidance_manifest.csv"
    if not path.exists():
        return
    existing = read_manifest(data_dir)
    keys = {(x["raw_file"],x["sha256"]) for x in existing}
    with path.open(newline="",encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if (row["raw_file"], row["sha256"]) not in keys:
                item = {k:row.get(k, "") for k in MANIFEST_FIELDS}
                item.update(url=row["query"], method="GET", http_status="200",
                            request_id=hashlib.sha256(row["query"].encode()).hexdigest())
                existing.append(item)
    temp = data_dir / "manifest.csv.tmp"
    with temp.open("w",newline="",encoding="utf-8") as handle:
        writer=csv.DictWriter(handle,fieldnames=MANIFEST_FIELDS)
        writer.writeheader(); writer.writerows(existing)
    temp.replace(data_dir / "manifest.csv")


def rebuild(data_dir=Path("data"), offline=False, refresh_live=True):
    data_dir = Path(data_dir)
    started = utc_now()
    before = time.perf_counter()
    status = run_data(data_dir, refresh_live=refresh_live, offline=offline)
    try:
        from .insights import build_corpus
        if offline and not (data_dir / "guidance_manifest.csv").exists():
            raise FileNotFoundError("Offline guidance cache unavailable")
        status["guidance"] = build_corpus(data_dir, offline=offline)
        merge_guidance_manifest(data_dir)
        status["integrity"] = verify_manifest(data_dir)
    except Exception as exc:
        status["guidance"] = {"status":"BLOCKED","error":str(exc)}
        status["errors"].append("guidance: " + str(exc))
        status["ok"] = False
    status["started_at_utc"] = started
    status["finished_at_utc"] = utc_now()
    status["status"] = "completed" if status["ok"] else "failed"
    status["duration_seconds"] = time.perf_counter()-before
    status["rss_mb_at_end"] = psutil.Process().memory_info().rss/1024**2
    old_path = data_dir / "last_success.json"
    if status["ok"]:
        atomic_json(old_path, {"run_id":status["run_id"],"finished_at_utc":status["finished_at_utc"]})
    if old_path.exists():
        status["last_success_utc"] = json.loads(old_path.read_text())["finished_at_utc"]
    atomic_json(data_dir / "status.json", status)
    with (data_dir / "runs.jsonl").open("a",encoding="utf-8") as handle:
        handle.write(json.dumps(status) + "\n")
    return status


def main():
    parser=argparse.ArgumentParser(description="SaayaShift local pipeline")
    parser.add_argument("command", choices=["data","evaluate","verify"])
    parser.add_argument("--data-dir",type=Path,default=Path("data"))
    parser.add_argument("--evidence-dir",type=Path,default=Path("evidence"))
    parser.add_argument("--offline",action="store_true")
    parser.add_argument("--cached",action="store_true")
    args=parser.parse_args()
    if args.command == "data":
        result=rebuild(args.data_dir,args.offline,not args.cached)
        print(json.dumps(result,indent=2))
        raise SystemExit(0 if result["ok"] else 1)
    elif args.command == "evaluate":
        from .model import evaluate
        print(json.dumps(evaluate(args.data_dir,args.evidence_dir),indent=2))
    else:
        print(json.dumps(verify_manifest(args.data_dir),indent=2))


if __name__ == "__main__":
    main()
