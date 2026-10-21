# Measured optimization and trade-offs

One change: reuse verified raw bytes instead of making fresh requests. First successful full acquisition took 186.377 s, 12 HTTP requests, RSS at completion 153.020 MiB. A fresh-layer offline rebuild took 11.340 s, 0 HTTP requests, RSS at completion 145.184 MiB. All six cleaned/processed weather/forecast/OSM CSV SHA-256 values matched exactly. See evidence/rebuild_report.json and first successful data/runs.jsonl entry.

This is a single-run operational comparison, not a controlled benchmark or peak-memory measurement. Network time dominates acquisition, and cache behavior/system load differ. Hash identity establishes identical model inputs and group outcomes; no 2025 model retuning was done. Retain caching for frozen history and OSM snapshot, while fetching live forecasts hourly. The trade-off is storage for original responses and potentially stale remote snapshots, shown explicitly in the UI.

Model development compared a fixed Ridge(alpha=1) with lag-one persistence on Jan-Jun 2024. Ridge validation MAE was 0.370856°C; persistence 0.711310°C. This candidate selection is not a multi-step optimization claim. Frozen 2025 testing occurred only afterward. Final 90% intervals undercovered at 85.02%; no test-informed recalibration was performed.

No energy/carbon reduction, peak-memory gain, GPU requirement, population benefit or statistical runtime significance is claimed. Avoid extra model complexity until real operational forecast-vintage validation exists.
