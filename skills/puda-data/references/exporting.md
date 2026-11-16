# Export data and experiments

### Exporter

```python
from exporter import (
    export_to_csv,           # Export DataFrame to CSV
    export_to_json,           # Export with metadata + hashes
    export_protocol,          # Export protocol definition
    export_full_experiment,   # Export everything at once
)

# Examples
csv_path = export_to_csv(run_id)
json_path = export_to_json(run_id)
prot_path = export_protocol(run_id)
results = export_full_experiment(run_id)
```
