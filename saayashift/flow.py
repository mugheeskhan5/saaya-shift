"""Real Prefect flow and opt-in local hourly deployment."""
from __future__ import annotations
import os
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("PREFECT_HOME", str(ROOT / ".prefect"))
os.environ.setdefault("PREFECT_SERVER_ANALYTICS_ENABLED", "false")
os.environ.setdefault("PREFECT_API_URL", "http://127.0.0.1:4200/api")
from prefect import flow
from prefect.runtime import flow_run
from .cli import rebuild


@flow(name="saayashift-hourly", retries=2, retry_delay_seconds=60, log_prints=True)
def hourly_pipeline():
    result=rebuild(ROOT / "data",refresh_live=True)
    print({"prefect_run_id":str(flow_run.id),"data_run_id":result["run_id"],
           "ok":result["ok"],"errors":result["errors"]})
    if not result["ok"]:
        raise RuntimeError("Pipeline failed; preserved previous data. See data/status.json")
    return result


if __name__ == "__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--serve",action="store_true")
    args=parser.parse_args()
    if args.serve:
        # Every hour at minute 5 UTC is also every hour at minute 5 PKT (UTC+5).
        # Scoped to this runner thread: allow display sleep, prevent idle system sleep.
        import ctypes
        kernel = ctypes.windll.kernel32 if os.name == "nt" else None
        if kernel is not None and not kernel.SetThreadExecutionState(0x80000001):
            raise OSError("Unable to request system-awake state for the scheduler")
        try:
            print("Hourly runner active; Windows idle sleep inhibited while this process runs.", flush=True)
            hourly_pipeline.serve(name="karachi-hourly",cron="5 * * * *",
                                  pause_on_shutdown=False,limit=1)
        finally:
            if kernel is not None:
                kernel.SetThreadExecutionState(0x80000000)
    else:
        hourly_pipeline()
