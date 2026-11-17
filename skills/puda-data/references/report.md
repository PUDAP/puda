# PUDA experiment reports

## Reporting workflow

1. Resolve the intended project and run/experiment IDs from project records. Extract the related data with the bundled extractor (see [Extraction](extraction.md)) or `puda db exec` SQL; `puda project hash --id <project_id>` returns a SHA-256 hash of the project-linked data.
2. Inspect `puda db schema` before selecting report data; do not assume table or column names.
3. For custom analysis and plotting, select the analysis reference linked from `SKILL.md`. Keep custom scripts and generated artifacts in the project's `analysis/` directory.
4. Use the bundled extraction, SHA-256 hashing, plotting, and Markdown report helpers as needed. Select their references from `SKILL.md` without loading unrelated guides.
5. Include source IDs, extraction scope, hashes, findings, and requested plots so conclusions can be traced to the recorded data.

## Usage

`generate_report` adds run metadata, integrity hashes, a data summary, and a plot; `ExperimentReport` builds the same sections selectively plus custom plots, tables, and Markdown. `command_name` defaults to `"CV"`; pass it explicitly for other measurement types.

### Simple Report

```python
from report import generate_report

generate_report(
    run_id,
    output_dir="/path/to/reports/",
    command_name="CV",
)
```

### Report with Custom Plot

```python
from report import ExperimentReport
from plotter import plot_cv

# Create report
report = ExperimentReport(run_id, command_name="CV")

# Add run metadata
report.add_metadata()

# Add custom visualization
report.add_plot(
    title="CV Curve",
    plot_function=plot_cv,
    plot_kwargs={"run_id": run_id, "output_path": "plot.png"}
)

# Save
report.save("/path/to/report.md")
```

### Custom Visualization Function

```python
def my_custom_plot(run_id, output_path):
    # Your plotting code here
    df = extract_measurement_data(run_id, "CV")
    # ... create plot ...
    plt.savefig(output_path)
    return output_path

# Use it in report
report.add_plot("My Plot", my_custom_plot, {"run_id": run_id, "output_path": "my_plot.png"})
```

## Class: ExperimentReport

### Methods

| Method | Description |
|--------|-------------|
| `add_metadata()` | Add run info, protocol, timestamps |
| `add_hashes()` | Add measurement_hash, run_hash, checksum |
| `add_plot(title, func, kwargs)` | Add custom visualization |
| `add_table(title, data)` | Add data table |
| `add_markdown(content)` | Add raw markdown |
| `save(path)` | Save report to file |

### Attributes

| Attribute | Description |
|-----------|-------------|
| `run_id` | Current run ID |
| `sections` | List of report sections |
| `plots` | List of added plots |

## Default Paths

- Database: `<project-root>/puda.db`
- Default reports: `<project-root>/reports/`
- Plots subdir: `reports/plots/`
