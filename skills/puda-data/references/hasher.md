# Data hashing

Hash and validate experimental data for provenance with SHA-256. Functions that take `command_name` default to `"CV"`; pass it explicitly for other measurement types.

## Hash types

| Hash | What it hashes |
|------|----------------|
| `measurement_hash` | The measurement data (DataFrame) |
| `run_hash` | All commands in the run |
| `checksum` | Root verification hash |

## Hashing functions

### hash_measurement(df)

Compute SHA-256 hash of measurement data.

```python
from hasher import hash_measurement
import pandas as pd

# Hash a DataFrame
df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
hash = hash_measurement(df)
# Returns: "sha256:abc123..."
```

### hash_run(run_id)

Aggregate hash of all commands in a run.

```python
from hasher import hash_run

run_hash = hash_run(run_id)
```

### generate_fingerprint(run_id, command_name)

Generate full metadata with all hashes.

```python
from hasher import generate_fingerprint

fingerprint = generate_fingerprint(run_id, command_name="CV")
# Returns: {run_id, command_name, measurement_hash, run_hash, checksum, data_points, protocol_id, created_at, x/y ranges}
```

### verify_integrity(run_id, expected_hash, command_name)

Verify data hasn't been modified.

```python
from hasher import verify_integrity

is_valid = verify_integrity(run_id, expected_hash, command_name="CV")
# Returns: True/False
```

## Integrity demo

```python
from hasher import demonstrate_integrity

result = demonstrate_integrity(run_id, command_name="CV")
# Returns original and modified hashes after a 1% change to one value
```
