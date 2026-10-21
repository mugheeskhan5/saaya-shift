---
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

# SaayaShift

**Plan outdoor work around the heat.**

SaayaShift helps supervisors in Karachi compare complete shift windows using forecast feels-like temperatures. It shows the data behind each comparison, original-source guidance, and the latest pipeline status.

**[Open the live app →](https://huggingface.co/spaces/ssswq12/saayashift)**

## Use the app

1. Check **forecast freshness**, **data quality**, and the **last successful run**.
2. In **Compare shifts**, choose a working date, duration, earliest start, and latest finish.
3. Compare the ranked windows. Select a window to see its start, finish, mean temperature, and peak temperature.
4. Open **Ask the evidence** for supported scheduling and recovery questions, with NIOSH citations.
5. Use **Model evaluation** and **Pipeline evidence** to inspect the recorded results and source records.

All displayed times are Pakistan Standard Time (PKT, UTC+5). If today's working hours have already passed, choose a future date. If there are no complete windows, adjust the date, duration, or operating hours.

## How it works

```text
Open-Meteo weather + OpenStreetMap context + NIOSH guidance
                           ↓
                Local acquisition and quality checks
                           ↓
                  Saved data and evidence files
                           ↓
                  Upload copies to Hugging Face
                           ↓
                  Gradio planning dashboard
```

The planner orders complete windows by **lowest mean feels-like temperature**, then **lowest peak**, then **earliest start**. Numbers come from saved forecast rows. Guidance answers use verified NIOSH excerpts; an embedding model reorders eligible passages. No language model generates the answer text. This describes the implemented capability; it does not claim a multilingual Chroma/FAISS store or language-model wording generation.

The archived-series model experiment is separate: **it does not generate the live forecasts or shift rankings**.

## What is in this repository?

| File or folder | Purpose |
|---|---|
| `app.py` | Gradio app used by the deployed Space |
| `requirements.txt` | Hugging Face app dependencies |
| `requirements-pipeline.txt` | Separate local pipeline dependencies |
| `saayashift/` | Existing planning, guidance, data, quality, model, API, and flow modules |
| `config/cities.json` | Karachi configuration |
| `scripts/start-local-scheduler.ps1` | Starts the local Prefect server and hourly runner |
| `scripts/export_runs.py` | Exports the required Prefect evidence window |
| `scripts/space_sync.py` | Copies evidence from the local host to the Space |
| `space/` | App source copies expected by the sync/bundle helper |
| `data/` | Complete local data-folder snapshot: raw, cleaned, processed, manifests, logs, and warehouse |
| `evidence/` | Every local evidence file, including model outputs, original Prefect exports, verification logs, and the explicitly labeled summary draft |
| `AI_Use_Log.md` | Material AI-use disclosure and verification limits |
| `ATTRIBUTION.md` | Data, guidance, and model credits |
| `DATASET_DECLARATION.md` | Dataset declaration |
| `PIPELINE_SETUP.md` | Additional operational notes |

This is the hosted app plus its local pipeline support. It does not include the separate React frontend or the development project's test suite.

## Submission files

- [Summary.pdf](Summary.pdf): current one-page project summary, prepared for Mughees Khan Abdullah.
- [Business model](docs/BUSINESS_MODEL.md) and [optimization notes](docs/OPTIMIZATION.md).
- [Prefect screenshots](evidence/screenshots/README.md): five unchanged captures supplied by the user.
- [Original run CSV](evidence/prefect_runs.csv) and [record explanation](evidence/READ_FIRST_RUN_RECORDS.md).

The demo video will be attached separately by the user. A GitHub release/tag has not been created by this assistant.

## Run the local pipeline

You need **Windows, Python 3.12, and internet access**. Open PowerShell in this repository folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-pipeline.txt
.\make.cmd data
.\scripts\start-local-scheduler.ps1
```

`make data` is supplied by the Windows dispatcher (`.\make.cmd data` in PowerShell). Linux/GNU Make users can activate a separate Python 3.12 pipeline environment and run `make data`. Both call the original `saayashift.cli data` implementation. `make evaluate` and `make verify` are also available. A cached, no-network rebuild can be invoked as `.\make.cmd data --offline` or `make data ARGS=--offline`; cached forecasts may correctly be flagged stale.

Original dispatcher copies are retained in `docs/original-build-commands/` for provenance. The root wrappers omit the old Streamlit-dashboard and development-test targets because this package's root app is Gradio and its development tests are not included.

The data command refreshes source data. The startup script starts the Prefect server and the hourly runner. Open the local dashboard at **http://127.0.0.1:4200** to inspect runs. Scheduled runs start at **five minutes past each hour**.

Keep the Windows host powered and online. The runner requests protection from idle sleep while it is alive, but shutdowns, restarts, and lid settings can still interrupt it. **It does not automatically restart after a PC reboot**; run the startup script again. Avoid starting duplicate runners.

Use `requirements-pipeline.txt` for the local pipeline and keep the root `requirements.txt` for the Gradio Space. They describe separate environments.

To verify the included raw files without downloading new data:

```powershell
.\.venv\Scripts\python.exe -m saayashift.cli verify
```

## Update the Space's data

The pipeline and the upload process are separate. Running the pipeline updates local files; the Space updates when those files are uploaded.

For the sync helper, install its upload dependency in the pipeline environment:

```powershell
.\.venv\Scripts\python.exe -m pip install huggingface-hub
```

Configure an appropriate `HF_TOKEN` environment variable outside the repository. Never put the token in source files, documents, or commits.

Upload the latest evidence once:

```powershell
.\.venv\Scripts\python.exe scripts/space_sync.py once --space ssswq12/saayashift
```

For automatic uploads after new pipeline runs:

```powershell
.\.venv\Scripts\python.exe scripts/space_sync.py loop --space ssswq12/saayashift
```

Stop the sync loop with **Ctrl+C**. This stops uploads; it does not necessarily stop Prefect. If uploads stop, the hosted data ages and the freshness display can become stale.

The `once` and `loop` commands upload data only. They do not publish UI changes. For the existing deployment, upload the corrected root `app.py` manually when changing the UI. Keep its `space/app.py` source copy aligned for any later full-bundle upload.

## Prefect evidence

> **IMPORTANT: THE PIPELINE RAN AS A PREFECT FLOW. ITS INTERNAL STEPS WERE NOT REGISTERED AS PREFECT TASKS, SO THERE ARE NO TASK-LEVEL RECORDS FOR THOSE STEPS.** The 24 actual flow runs are present in Prefect's flow history and the original export.

For an easier-to-read copy with a repeated warning, open `evidence/pipeline_runs_view.csv`. It is a derived view; the unedited export is `prefect_runs.csv`, alongside the unchanged raw JSON. See [the record explanation](evidence/READ_FIRST_RUN_RECORDS.md).

The repository includes:

- `evidence/prefect_runs.csv` — unchanged original server export, using the required filename.
- `evidence/prefect_runs_annotated.csv` — supporting copy with a short task-registration warning.
- `evidence/prefect_runs_original.csv` — unchanged original run-history export for submission requirements asking for unedited evidence.
- `evidence/prefect_runs.raw.json` — matching raw server response.

The export records **24 completed runs** in the required window: **20 October 2026, 4 PM to 21 October 2026, 4 PM PKT**. Expected starts run from 4:05 PM Tuesday to 3:05 PM Wednesday. These are run records, not detailed console logs.

To export that window from your running local Prefect server:

```powershell
.\.venv\Scripts\python.exe scripts/export_runs.py
```

The command writes the original CSV and raw JSON under `evidence/`; running it again replaces those files with the local server response. A fresh clone does not contain the original Prefect database: the supplied exports preserve its evidence but do not restore its server history. Keep the original exports unchanged when preparing submission evidence.

## Limits to understand

- Lower forecast heat **does not certify safe working conditions**. The app does not assess individual health, workload, clothing, acclimatization, or on-site shade. For an emergency, contact official local emergency medical services.
- The prototype uses one Karachi weather grid. It does not provide worksite microclimate predictions.
- Forecasts are modeled values, not measured worker exposure. Unsupported guidance questions receive an abstention.
- The saved forecast is a snapshot. A working pipeline and upload process are needed to keep the hosted data current.
- Full multilingual, language-model-generated RAG is not implemented.

## Complete data and evidence

This package includes every file found in the source project's `data/` and `evidence/` folders when it was assembled. The files are preserved byte for byte; generated raw/cleaned/processed tables, the DuckDB warehouse, provenance manifests, quality/run logs, frozen model artifacts, predictions, group results, and original console reports are included. `Summary-draft.pdf` is a draft and must not be mistaken for an approved final summary.

The data snapshot is newer than the original Space snapshot. The app source and its processing logic are unchanged. Live acquisition and sync remain separate operations.

## Verification

Before packaging, the development project's **24 backend tests**, React type check, and React production build passed. The corrected Gradio app was checked on desktop/mobile and in light/dark modes. All original application logic functions and event connections were preserved; the added UI handlers format existing outputs only.

The startup font error was reproduced and corrected, and the theme comparison passed against all nine Gradio 6.30.0 built-in themes. The user confirmed the deployment works. GPU inference was not rerun locally during the UI checks.

The packaged pipeline also rebuilt successfully from its raw cache with **zero network calls**. A stale cached forecast correctly produced a timeliness warning; refreshing live data is a separate step.

## License and credits

Original code is released under the [MIT License](LICENSE). Source datasets, guidance, and external models retain their own terms; see [ATTRIBUTION.md](ATTRIBUTION.md) and [DATASET_DECLARATION.md](DATASET_DECLARATION.md).

Material assistant contributions are disclosed in [AI_Use_Log.md](AI_Use_Log.md). Named contact/reviewer: **Mughees Khan Abdullah**. Each team member must still be able to explain their retained work; a full roster and understanding checks are not invented here.
