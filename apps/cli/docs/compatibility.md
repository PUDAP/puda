# Edge protocol compatibility

The CLI judges an edge by the Edge Protocol it speaks, not by SDK version
numbers. Every pong (`puda.<machine_id>.ping` and the `puda.cmd.ping` broadcast)
carries a `protocol_version` string `"MAJOR.MINOR"`:

```json
{"status": "pong", "machine_id": "oven", "sdk_version": "0.1.0", "protocol_version": "1.0"}
```

- This CLI supports protocol major **1** (`1.x`). Any `1.MINOR` edge is
  supported.
- A minor version only adds fields or verbs, so every `1.x` edge stays
  compatible with this CLI.
- A new major version is a breaking release of both the CLI and the edge SDKs.
- An edge that reports no `protocol_version` predates Edge Protocol 1.0
  (Python SDK before 0.1.0) and is unsupported, as is any other major or a
  malformed value. Fix it by updating the PUDA SDK on that machine.
- `sdk_version` stays in the pong and in CLI output for information only.
- The other direction uses the same version: every command envelope carries
  `header.protocol_version` (this CLI sends `1.0`). An edge refuses a command
  whose `header.protocol_version` is missing or not `1.MINOR` with
  `EXECUTION_ERROR` "Invalid command envelope: header.protocol_version: ..."
  and does not run it.

The CLI and the SDK packages are versioned independently. CLI 0.2.0 and Python
SDK 0.1.0 are the first releases that speak Edge Protocol 1.0. The same contract
applies to any future SDK, such as a C SDK for ESP32 edges.

## Where the CLI checks it

- `puda machine list` and `puda machine info` print one stderr line per
  responding edge that is not supported, for example
  `warning: machine oven speaks edge protocol none; this CLI supports 1.x (update the edge's PUDA SDK)`.
  Stdout and exit status do not change, and nothing is blocked.
- `puda healthcheck` includes the result in its JSON report under
  `compatibility`: `supported_protocol: "1.x"` and, per responding edge,
  `machine_id`, `sdk_version`, `protocol_version` and `status`
  (`supported`/`unsupported`). Each unsupported edge also gets an advisory
  `sdk_unsupported` issue. The result never changes NATS status or the exit
  code. See the [machine contract](../README.md#healthcheck-machine-contract).
- `puda update` only replaces the CLI binary; it does not check edges. Run
  `puda healthcheck` afterwards.

Only edges that answer the fresh ping are checked; offline or late edges are not.

## Contract smoke test

`apps/cli/tests/test_python_sdk_contract.py` runs the real compiled CLI against
the installed Python SDK on a private loopback JetStream broker with a software
driver. It never uses an installed PUDA profile or hardware.

```sh
export TMPDIR=/path/to/scratch
uv venv "$TMPDIR/puda-sdk"
uv pip install --python "$TMPDIR/puda-sdk/bin/python" ./libs/python-sdk
(cd apps/cli && go build -o "$TMPDIR/puda-contract-cli" ./cmd/puda)
PUDA_TEST_CLI="$TMPDIR/puda-contract-cli" PUDA_TEST_NATS_SERVER=/absolute/path/to/nats-server \
  "$TMPDIR/puda-sdk/bin/python" -m unittest discover -s apps/cli/tests -p test_python_sdk_contract.py -v
```
