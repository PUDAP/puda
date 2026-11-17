---
name: puda-data
description: Extract, analyze, hash, export, and report on PUDA experimental data. Use for run data, plots, experiment reports, result interpretation, SHA-256 provenance, or device adapter extensions.
---

# PUDA experimental data

Use the bundled Python modules to extract measurements, analyze results, hash provenance, export data, plot results, and generate experiment reports. Built-in device adapters cover First and Biologic; other devices use the generic adapter. Measurement types include CV, OCV, CA, PEIS, and a GEIS fallback.

## Start with the requested operation

Resolve this skill's installed directory and add its `scripts/` directory to Python's import path; do not hard-code a user or agent installation path. Run from the intended project root or set `PUDA_PROJECT_ROOT` **before importing modules**, since paths are discovered at import time. Install `pandas` and `matplotlib` if missing.

Inspect the live schema with `puda db schema` before writing custom queries; use the bundled scripts as the source of truth for function signatures.

| Task | Read when needed | Python entrypoints |
|---|---|---|
| Find runs, load measurements, or resolve paths | [Extraction](references/extraction.md) | `extractor`, `config` |
| Hash, verify, or demonstrate tamper detection | [Hashing](references/hasher.md) | `hasher` |
| Export CSV, JSON, or an experiment | [Exporting](references/exporting.md) | `exporter` |
| Plot measurements or compute summaries | [Plotting](references/plotting.md) | `plotter` |
| Analyze or interpret experiment results | [Analysis workflow](references/analysis.md) | `sqlite3`, `pandas`, `matplotlib` |
| Generate an experiment report | [Reporting workflow and builder](references/report.md) | `report` |
| Add device schemas, adapters, or plotters | [Extension contracts](references/extending.md) | `registry`, `adapters`, `plotter` |

Read only the references and script implementations needed for the selected operation. Keep run IDs, metadata, and SHA-256 provenance with exported/report data so results can be traced back to their source.

For run context, `extractor.get_run_info()` and `extractor.list_all_runs()` include stored `steps` and `notes`; see [Extraction](references/extraction.md). After analysis, append conclusions with `puda protocol note`, following the run-note rules in **puda-protocol**.
