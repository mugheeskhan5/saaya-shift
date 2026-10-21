"""Export every server-returned Prefect run in the required window, without inventing entries."""
import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
import requests

START="2026-10-20T11:00:00Z"
END="2026-10-21T11:00:00Z"

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--api-url",default="http://127.0.0.1:4200/api")
    parser.add_argument("--output",type=Path,default=Path("evidence/prefect_runs.csv"))
    args=parser.parse_args()
    if datetime.now(timezone.utc) < datetime.fromisoformat(END.replace("Z","+00:00")):
        raise SystemExit("Evidence window is not complete. No final run-history export created.")
    runs=[]; offset=0
    while True:
        response=requests.post(args.api_url+"/flow_runs/filter",json={
            "flows":{"name":{"any_":["saayashift-hourly"]}},
            "flow_runs":{"expected_start_time":{"after_":START,"before_":END}},
            "sort":"EXPECTED_START_TIME_ASC","offset":offset,"limit":200},timeout=30)
        response.raise_for_status(); batch=response.json(); runs.extend(batch)
        if len(batch)<200: break
        offset += len(batch)
    if not runs:
        raise SystemExit("No real server runs found; do not submit a fabricated history.")
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.with_suffix(".raw.json").write_text(json.dumps(runs,indent=2),encoding="utf-8")
    fields=sorted({key for row in runs for key in row})
    with args.output.open("w",newline="",encoding="utf-8") as handle:
        writer=csv.DictWriter(handle,fieldnames=fields); writer.writeheader()
        for row in runs:
            writer.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()})
    print(f"Exported {len(runs)} server-returned rows, including failures and incomplete runs. Inspect coverage separately; raw response retained.")
if __name__=="__main__": main()
