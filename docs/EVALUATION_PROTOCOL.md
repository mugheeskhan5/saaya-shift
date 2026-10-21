# Frozen evaluation protocol

Recorded before fetching or examining model scores, 19 October 2026 PKT.
The original declaration commit is 4013d44, timestamped 2026-10-19T10:23:30+05:00.
The user's staged declaration specifies the 2023-2024 / 2025 boundary and is preserved unchanged.

- Target: next-hour H apparent temperature (Celsius), Open-Meteo ICON Global historical forecast series, Karachi's returned grid cell.
- Frozen baseline: same local hour previous day, target H minus 24 hours. MAE in Celsius; never redefine this comparator.
- Information cutoff: H minus 1 hour. Predictors: prior apparent temperatures at H-1, H-2, H-3, H-24, H-25, H-48, and known calendar cycles. No target-hour weather covariates.
- This is a retrospective one-hour series-prediction experiment. Historical forecasts are stitched model output, not observations; publication delays and true forecast vintages are unavailable. Scores do NOT establish operational forecast skill or health benefit.
- Fit the candidate scaler and Ridge(alpha=1) on local-year 2023 only; compare validation on Jan-June 2024 to lag-one persistence. Select the lower MAE candidate; ties choose persistence. No hyperparameter search.
- Refit selected candidate on Jan 2023-June 2024. Calibrate a symmetric empirical 90% absolute-residual interval on July-December 2024. Do not claim conditional or formal time-series coverage.
- Freeze candidate, preprocessing and interval before test. Test once on local-year 2025. Prior test targets can supply lag features for later test predictions (rolling one-hour evaluation); no fitting on test.
- Use exact timestamp joins for lags, not row offsets. Exclude missing/range-flagged target or required predictors; publish exclusions and split counts. Estimated targets are excluded.
- Report MAE and paired difference from baseline with a fixed-seed 7-day moving-block bootstrap (500 replicates, 95% interval). Report season and local time-of-day groups and test interval coverage.
- PASS for the event model criterion requires strictly lower held-out MAE; statistical uncertainty remains visible even if the point estimate passes. A failure does not authorize tuning on 2025.
- Local planner uses the provider's current future forecast, NOT this experimental model. Rank complete feasible windows by mean apparent temperature, then peak, then earliest start. The ranking is an exposure proxy, not a safe-work recommendation.

The evaluation command refuses to overwrite an existing held-out report. Reproduction verifies frozen inputs and artifacts without choosing a new model after seeing test scores.
