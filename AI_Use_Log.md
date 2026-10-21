# Material AI use

Date: 19 October 2026 (updated 21 October 2026). Assistants: OpenAI Codex (19 Oct) and Anthropic Claude (20 Oct, high-level summary in the last table row). Codex details: Assistant: OpenAI Codex, GPT-6 family; exact served model build was not exposed in this chat. Three temporary parallel agents used the same inherited configuration before the session's delegation setting changed.

| Task | Material retained | Checks / changes | Human able to explain |
|---|---|---|---|
| Requirements and deadline review | Status, protocol, traceability | Read guide pages 1–7; inspected original Git declaration timestamp and preserved staged edits | TBD by user |
| Source feasibility | Official-source notes, licensing limits | Primary publisher docs; real robots and guidance permission snapshots; HF ZeroGPU exception added after further check | TBD |
| Data and quality | Acquisition, manifest, Pandera rules, DuckDB | Real source fetch; raw hashes; six byte-identical rebuild tables; synthetic-only corruption/gap tests | TBD |
| Model and planner | Fixed Ridge selection, exact lag joins, intervals, deterministic windows | Pre-score protocol; 2025 used once; chronological/invariance checks; stored row predictions and group report | TBD |
| Insight retrieval | Five exact public-domain NIOSH extracts | Page/offset/hash validation; unsupported/misleading/corruption checks. No runtime LLM generation implemented | TBD |
| UI and operations | Streamlit interface, Prefect flow, export scripts | AppTest and browser checks; scheduler host/continuous evidence pending | TBD |
| Documentation and packaging | README, business assumptions, summary draft | Claims taken from stored evidence; unfinished requirements explicitly labelled | TBD |
| Hosted view and housekeeping (20 Oct) | Anthropic Claude (Sonnet 5.5): dashboard colour restyle, Gradio Hugging Face Space adapted from the earlier Codex version, a script that copies real evidence files to the Space, review of logs and submission documents | No pipeline, model or data code was changed. The user ran every command and checked the Space; files were compared with run logs and docs before edits | TBD |

No AI-generated data was used for model training or evaluation. Synthetic test fixtures are labelled in test files. No person has yet certified understanding or accepted the app. Team members must review and explain every retained part before the viva. No paid AI inference or API credentials are used by the application. The hosted Space uses the small open embedding model all-MiniLM-L6-v2 only to reorder verified NIOSH excerpts; it writes no answer text.


## Update — 21 October 2026

Assistant: OpenAI Codex desktop. Exact served model/build was not recorded for this session. The earlier entries above are historical records; their pending deployment and acceptance notes describe the status at the time they were written.

| Task | Material retained | Verification and limits | Human able to explain |
|---|---|---|---|
| Codebase and operations review | Architecture explanation; distinction between Prefect execution and Space uploads | Inspected source and saved artifacts. No pipeline logic changed. User confirmed the deployed Space works. | TBD by user |
| Gradio presentation refinement | Forest-green theme, status cards, selected-shift summary, responsive layout, expandable evidence | All 15 original non-UI functions, original constants and 10 original event connections preserved. Two display-only handlers format existing outputs. Tested real forecasts, selection/duration changes, empty results, source panels, safety abstention, desktop/mobile and dark/light views. | TBD by user |
| Gradio startup correction | Removed incompatible custom theme font-list override | Reproduced the reported `AttributeError`; tested comparison against all nine Gradio 6.30.0 built-in themes. Initial preview disabled analytics and missed this launch-time branch; corrected before final packaging. User subsequently confirmed deployment works. | TBD by user |
| Pre-commit verification | Read-only audit and verified package | 24 backend tests passed; React type check and build passed in the development project. Manifest and frozen-model provenance verified. Deployed app matched corrected local source. GPU embedding inference was not rerun locally during this session. | TBD by user |
| GitHub package and documentation | Deployed Space snapshot, original Prefect exports/startup scripts, required raw-cache files, setup notes, this disclosure and README | Preserved original scripts and exported evidence bytes. CSV has 24 completed runs and matches raw JSON. Packaged pipeline rebuilt offline with zero network calls; cached-forecast staleness warning was retained honestly. No GitHub commit/push or Space upload was performed by Codex in this session. | TBD by user |

The user performed the Hugging Face uploads. Codebase tests mentioned above were run in the development project; this focused distribution does not include its React frontend or test suite. Team members must fill in the actual human owners and review the retained code before claiming they can explain it. User confirmation that the deployment works does not certify each team member's understanding.


## Named contact and final packaging update — 21 October 2026

**Named contact/reviewer supplied by the user: Mughees Khan Abdullah.** This identifies the contact; it does not certify every team member's understanding or invent a four-person roster.

Codex copied the original build commands, business-model and optimization documents from the development project; adapted only the command launchers to the focused Gradio package; restored the unedited Prefect export under the required filename; included five screenshots unchanged; and prepared the current one-page summary. The demo video and GitHub push remain the user's separate actions. No RAG capability was added or represented as newly implemented: the runtime still uses source-grounded extractive retrieval and semantic reranking.

Final package check: the Windows `make.cmd data --offline` entry point rebuilt all six cleaned/processed tables from raw cache with byte-identical hashes, 53 passing quality checks, zero findings and zero HTTP calls in a scratch copy. This packaging check is stored separately and was not added to the historical Prefect export. All five supplied screenshots are preserved byte for byte.
