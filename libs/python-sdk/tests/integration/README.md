# Edge protocol integration tests

Each test class starts a private `nats-server` on free loopback ports,
provisions it from `infra/nats/jetstream/streams/*.json` (as
`setup_streams.sh` does), runs `edge_driver.py` as a real edge subprocess and
drives it with raw protocol envelopes. They cover the behaviour specified in
`docs/edge-protocol/` (pause hold, stale immediates, complete/abort, malformed
commands, reconnect, provisioning).

```bash
cd libs/python-sdk
PUDA_NATS_SERVER=/path/to/nats-server uv run pytest tests/integration
```

Without `PUDA_NATS_SERVER` the binary is looked up on `PATH`; if none is found
the tests are skipped. Nothing outside the temporary broker directory is
touched, and no CLI profile or key is read.

- `nats_harness.py`: `Broker`, `Edge`, `Wire` (raw client that records every
  response) and `EdgeTestCase` (one broker per class, a fresh machine and edge
  per test).
- `edge_driver.py`: the edge process. `full` implements every lifecycle hook
  (`pause`, `resume`, `reset`, `estop`, `abort`); `minimal` has none. Its slow
  command is `hold`, because `wait` is a CLI built-in in protocols.
