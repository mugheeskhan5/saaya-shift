"""Rebuild layers in a fresh directory using only verified original raw files."""
from pathlib import Path
import hashlib,json,shutil,time
from saayashift.cli import rebuild

def main():
    original=Path("data")
    destination=Path("work") / ("rebuild-"+str(time.time_ns()))
    destination.mkdir(parents=True)
    shutil.copytree(original/"raw",destination/"raw")
    for name in ["manifest.csv","guidance_manifest.csv"]:
        shutil.copy2(original/name,destination/name)
    status=rebuild(destination,offline=True)
    results={}
    for layer in ["cleaned","processed"]:
        for table in ["weather","forecast","osm"]:
            relative=f"{layer}/{table}.csv"
            expected=hashlib.sha256((original/relative).read_bytes()).hexdigest()
            actual=hashlib.sha256((destination/relative).read_bytes()).hexdigest()
            results[relative]={"expected":expected,"actual":actual,"identical":expected==actual}
    report={"status":"PASS" if status["ok"] and all(x["identical"] for x in results.values()) else "FAIL",
            "method":"fresh layers; verified raw cache only; no network", "directory":str(destination),
            "duration_seconds":status["duration_seconds"],"rss_mb_at_end":status["rss_mb_at_end"],
            "api_calls":status["acquisition"]["http_calls"],"tables":results}
    Path("evidence/rebuild_report.json").write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
    raise SystemExit(0 if report["status"]=="PASS" else 1)
if __name__=="__main__":main()
