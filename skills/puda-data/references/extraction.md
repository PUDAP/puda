# Data extraction and project paths

## Path discovery (config.py)

Automatically finds project root via:
1. `PUDA_PROJECT_ROOT` env var
2. `puda.db` in parent directories
3. `puda.config` in parent directories
4. `project.md` in parent directories
5. `protocols/` in parent directories
6. `cwd()` fallback

```python
from config import get_project_root, get_db_path, get_report_dir

print(get_project_root())  # /path/to/workspace
print(get_db_path())       # /path/to/workspace/puda.db
```

## Extractor

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

`get_run_info()` and each `list_all_runs()` item include `steps` and `notes` as stored TEXT. `None` means SQL `NULL` or a column absent from an older database (read without migration). `steps=NULL` in the current schema means the full protocol was requested; an absent column means the historical selection is unknown. Neither proves execution completed. Read relevant `project.md` history before analysis, and never treat historical equipment state as current.

Inspect tables and columns with `puda db schema`.

## Environment Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| `PUDA_PROJECT_ROOT` | Override project root discovery | `/home/user/puda-project` |
