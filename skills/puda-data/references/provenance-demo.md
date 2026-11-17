# Data Provenance Demonstration

This document shows how SHA-256 hashing ensures data integrity for PUDA experimental data.

## How It Works

1. **Extract** measurement data from the database
2. **Hash** the data using SHA-256
3. **Store** the hash alongside your experiment
4. **Verify** later by re-computing the hash

If ANY data is modified, the hash changes completely!

## Example with CV Data

### Original Data

**Run ID:** f3677d75-1e5e-4ff6-9b04-4e9d55670a58

**Hash:** `sha256:7bd7b697d34f6620236dee5ddc7847c043354de8d739cfb815c8cb1787c3f2e1`

**Data Sample (first 5 rows):**

| potential (V) | current (A) | time (s) |
|---------------|-------------|----------|
| 5.2055 | 1.313262e-05 | 0.00 |
| -0.0065 | -1.400851e-06 | 0.25 |
| -0.0045 | 2.425834e-06 | 0.51 |
| 0.0083 | -2.074982e-06 | 0.76 |
| 0.0066 | 4.150816e-06 | 1.02 |

### Modified Data (1% change)

**Modified Value:**
  - Original: 1.313262e-05 A
  - Modified: 1.326395e-05 A
  - Change: +1%

**New Hash:** `sha256:a03a6830770e2906b61e5f0972c7d09d9316d5e274475c44c5751933e583fe9a`

### Comparison

| Metric | Original | Modified |
|--------|----------|----------|
| Hash | `sha256:7bd7b697d34f6620236dee5ddc7847c04...` | `sha256:a03a6830770e2906b61e5f0972c7d09d9...` |
| Data Same | - | ❌ NO |

## Conclusion

Even a **1% change** to a single data point produces a **completely different hash**!

This proves SHA-256 hashing ensures data integrity:
- Store the hash with your experiment metadata
- Later, re-compute the hash to verify data wasn't tampered with
- Any modification (even 0.01%) is detectable

## Full Fingerprint Structure

```json
{
  "run_id": "f3677d75-1e5e-4ff6-9b04-4e9d55670a58",
  "command_name": "CV",
  "measurement_hash": "sha256:7bd7b697d34f6620236dee5ddc7847c043354de8d739cfb815c8cb1787c3f2e1",
  "run_hash": "sha256:139d200e2598c627b5ab13b76a93bc754b0e78da324106bc41035658dbbd55f7",
  "checksum": "sha256:eb26c8b499920a812c0bf5d66941774e7312c89fabc11b26e04ab8e9125515e1",
  "data_points": 504,
  "protocol_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "created_at": "2026-03-13T15:38:39+08:00",
  "potential_range": [-0.051, 5.206],
  "current_range": [-9.88e-06, 1.71e-05]
}
```

## Usage Code

```python
from hasher import generate_fingerprint, verify_integrity  # scripts/ on sys.path (see SKILL.md)

# Get fingerprint with hashes
fp = generate_fingerprint("f3677d75-1e5e-4ff6-9b04-4e9d55670a58")
print(fp['measurement_hash'])

# Verify integrity later
is_valid = verify_integrity(
    "f3677d75-1e5e-4ff6-9b04-4e9d55670a58",
    "sha256:7bd7b697d34f6620236dee5ddc7847c043354de8d739cfb815c8cb1787c3f2e1"
)
print(f"Data intact: {is_valid}")  # True if not tampered
```
