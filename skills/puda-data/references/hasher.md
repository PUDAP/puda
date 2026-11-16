# puda-data Phase 2: Data Hasher

## Overview

Hash and validate experimental data for provenance. Uses SHA-256 to ensure data integrity.

## Hash System

### Why Hash?

- **Detect tampering**: If any data is modified, the hash changes completely
- **Verify integrity**: Store the hash alongside data to verify nothing changed
- **SHA-256**: Even a 1% change produces a completely different hash

### Hash Types

| Hash | What it hashes |
|------|----------------|
| `measurement_hash` | The measurement data (DataFrame) |
| `run_hash` | All commands in the run |
| `checksum` | Root verification hash |

## Hashing Functions

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

run_hash = hash_run("f3677d75-1e5e-4ff6-9b04-4e9d55670a58")
```

### generate_fingerprint(run_id)

Generate full metadata with all hashes.

```python
from hasher import generate_fingerprint

fingerprint = generate_fingerprint("f3677d75-1e5e-4ff6-9b04-4e9d55670a58")
# Returns: {run_id, measurement_hash, run_hash, checksum, metadata...}
```

### verify_integrity(run_id, expected_hash)

Verify data hasn't been modified.

```python
from hasher import verify_integrity

is_valid = verify_integrity("f3677d75...", "sha256:abc123...")
# Returns: True/False
```

## Integrity Demo

```python
from hasher import demonstrate_integrity

demonstrate_integrity(run_id)
# Shows how even a 1% change produces a completely different hash!
```

## Output Format

```json
{
  "run_id": "f3677d75-1e5e-4ff6-9b04-4e9d55670a58",
  "measurement_hash": "sha256:f2583e1df5b97ce7f542940a8655336539163873e53d89c1e93a618a3e6171ee",
  "run_hash": "sha256:ac066dae1f031595e4de40e78292cc202233141b40aa69d60874f8575b1f6c58",
  "checksum": "sha256:...",
  "data_points": 504,
  "potential_range": [-0.051, 5.206],
  "current_range": [-1.0e-5, 1.7e-5],
  "created_at": "2026-03-13T15:41:20+08:00"
}
```
