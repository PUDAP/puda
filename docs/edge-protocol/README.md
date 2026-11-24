# PUDA Edge Protocol

The wire contract between a PUDA edge (the process that owns a machine) and the PUDA CLI, agents and loggers. It exists so that edges can be written in languages other than Python, for example a C SDK for ESP32 firmware.

| Version | Spec | Status |
|---|---|---|
| 1.0 | [edge-protocol-v1.0.md](edge-protocol-v1.0.md) | Draft. Reference: Python SDK 0.0.24 / CLI 0.1.7. Transcripts were captured from SDK 0.0.23; payloads added for the 0.0.24 fixes come from the fixed SDK. |

Supporting material for 1.0 lives in [`v1.0/`](v1.0/):

- `schemas/`: JSON Schemas for every payload.
- `examples/`: real payloads, redacted.
- `transcripts/`: per-scenario wire captures from SDK 0.0.23, including the deviations listed in §16 of the spec.
- `vectors/`: E2E frame test vectors and their generator.
- `check.py`: validates the examples against the schemas and the vectors against an independent AES-GCM implementation and `puda.e2e`.

Run the check from the repository root:

```bash
uv run --with jsonschema python docs/edge-protocol/v1.0/check.py
```
