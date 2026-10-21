# Local hourly pipeline

The root `app.py` and `requirements.txt` are the deployed Gradio app. They remain unchanged.

Use a separate Windows Python 3.12 environment for the local pipeline. From this repository folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-pipeline.txt
.\scripts\start-local-scheduler.ps1
```

The startup script starts the local Prefect server and hourly runner. Keep the machine powered and online. It does not install Windows auto-start. Do not expose the local Prefect API publicly.

Export the required evidence window while the local Prefect server is running:

```powershell
.\.venv\Scripts\python.exe scripts/export_runs.py
```

The existing `evidence/prefect_runs.csv` and matching `.raw.json` are preserved original exports, containing 24 completed runs for the required window. Re-running the export reads the local server's history, so a fresh installation needs its own server history; the supplied CSV does not populate the Prefect database.

Optional evidence sync to the existing Space uses `scripts/space_sync.py`. Install `huggingface-hub` in the pipeline environment if needed and supply `HF_TOKEN` through the environment, never in the repository. The `once` and `loop` commands upload data only; `init` uploads the full app and must be used deliberately. The `space/` source copies are retained because this helper expects those paths. No sync was started during packaging.

```powershell
.\.venv\Scripts\python.exe -m pip install huggingface-hub
.\.venv\Scripts\python.exe scripts/space_sync.py once --space ssswq12/saayashift
```

The raw source files referenced by the included manifest are supplied so integrity verification can succeed. New pipeline runs still need internet access to refresh forecasts. Local `.venv/`, `.prefect/`, generated logs, databases and `work/` should remain outside Git; the supplied manifest, raw provenance and exported evidence should remain included.
