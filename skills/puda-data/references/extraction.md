# Data extraction and project paths

### 1. Path Discovery (config.py)

Automatically finds project root via:
1. `PUDA_PROJECT_ROOT` env var
2. `puda.db` in parent directories
3. `puda.config` in parent directories
4. `experiment.md` in parent directories
5. `protocols/` in parent directories
6. `cwd()` fallback

```python
from config import get_project_root, get_db_path, get_report_dir

print(get_project_root())  # /path/to/workspace
print(get_db_path())       # /path/to/workspace/puda.db
```

### Extractor

```python
from extractor import (
    extract_measurement_data,  # Get DataFrame for a run
    get_runs_by_type,          # List runs by command type
    get_latest_measurements,   # Get recent measurement DataFrames
    get_run_info,              # Get run metadata
    get_protocol,              # Get protocol definition
    list_all_runs,             # List all runs
)

# Examples
df = extract_measurement_data(run_id, "CV", device="biologic")
runs = get_runs_by_type("CV", limit=10)
measurements = get_latest_measurements("PEIS", limit=5)
info = get_run_info(run_id)
protocol = get_protocol(protocol_id)
all_runs = list_all_runs(limit=20)
if info:
    print(info["steps"])  # Requested selector text, not completed steps
    print(info["notes"])  # Timestamped, explicitly authored run notes
```

`get_run_info()` and each `list_all_runs()` item include `steps` and `notes`, preserving stored TEXT unchanged. SQL `NULL` becomes Python `None`; the extractor also returns `None` for either column missing from an older database, without altering the database. In the new schema, `steps=NULL` means the full protocol was requested; an absent legacy column means the historical selection is unknown. Neither proves execution completed. `get_run_info()` still returns `{}` for an unknown run and its `commands` remains a list of step/name/device dictionaries; list summaries retain command-name lists. `get_runs_by_type()` retains its three-item `(run_id, step_number, created_at)` tuples.

Append an authored note with `puda protocol note --run <run_id> --text '<note>'` (both flags required). The CLI atomically timestamps and appends supplied text to `run.notes`; it does not generate narrative. Put actual report/plot/log Markdown links relative to the project root inside the note. Retain project-level context and legacy history in `project.md`; no automatic import or new tables.

## Recording analysis context

Work from the intended project root and attach findings only to an actual protocol-associated run. With CLI 0.1.6-rc1 or later, append concise conclusions, caveats, comparison run IDs, and real project-relative Markdown links to reports, plots, logs, or exports. Distinguish measured observations from interpretation. The CLI supplies the recording timestamp, not the experiment time; it does not author the summary.

Verify the returned JSON and retrieve the saved notes with `get_run_info(run_id)`. Report failures rather than claiming success or silently writing a duplicate run entry in `project.md`. Check saved notes before retrying an uncertain append. Preserve `project.md` for goals, durable context, and legacy history; read relevant history before analysis and never treat historical equipment state as current.

## Database Schema

```sql
project(project_id, name, description, created_at)
protocol(protocol_id, project_id, user_id, username, description, commands, created_at)
run(run_id, protocol_id, steps TEXT NULL, notes TEXT NULL, created_at)
sample(sample_id, run_id, data_payload, created_at)
measurement(measurement_id, sample_id, data_payload, created_at)
command_log(command_log_id, run_id, step_number, command_name, payload, machine_id, command_type, created_at)
```

## Environment Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| `PUDA_PROJECT_ROOT` | Override project root discovery | `/home/user/puda-project` |
