# IMPORTANT: FLOW RUNS, NOT TASK RUNS

The pipeline executed as Prefect flow runs. Its internal steps were ordinary Python function calls, not registered Prefect tasks. The original export preserves 24 completed flow runs; it does not contain historical task-run executions.

- `prefect_runs.csv`: unchanged original server export, under the filename requested by the guide.
- `prefect_runs.raw.json`: unchanged raw server response.
- `prefect_runs_original.csv`: identical backup of the original export.
- `prefect_runs_annotated.csv`: supporting copy with a short warning column.
- `pipeline_runs_view.csv`: derived viewer table with the detailed warning repeated on every row.
- `screenshots/`: five original user-supplied Prefect screenshots and their context.

Warnings are deliberately kept out of the required unedited `prefect_runs.csv`. The guide asks for hourly run history and does not explicitly require each internal step to be a Prefect task.
