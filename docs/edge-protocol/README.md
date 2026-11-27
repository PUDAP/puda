# PUDA Edge Protocol

The wire contract between a PUDA edge (the process that owns a machine) and the PUDA CLI, agents and loggers. It exists so that edges can be written in languages other than Python, for example a C SDK for ESP32 firmware.

| Version | Spec | Status |
|---|---|---|
| 1.0 | [edge-protocol-v1.0.md](edge-protocol-v1.0.md) | Draft. Reference: Python SDK 0.1.0 / CLI 0.2.0 (the first releases speaking 1.0; edges report `protocol_version` in their pong). Transcripts were captured from SDK 0.0.23; payloads added for the 0.1.0 changes come from the fixed SDK. |

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

Both reference implementations test themselves against these files, so either one drifting from the spec fails its own suite:

- CLI: `apps/cli/internal/nats/edge-protocol-spec_test.go` (`go test ./internal/nats -run Spec`)
- Python SDK: `libs/python-sdk/tests/test_edge_protocol_spec.py`

Each checks that the implementation seals every E2E vector byte-for-byte and reaches every negative outcome. It also checks that decoding the examples keeps every spec field, and that the payloads it builds itself (commands, responses, pongs, catalogs, keyring records) validate against the schemas. A new implementation such as a C SDK should add the same checks to its own suite.
