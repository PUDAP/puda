# Error handling

Run-id mismatch, unknown command (ends the run), second START, malformed input, missing run_id, kwargs precedence.

Captured from Python SDK 0.0.23 (`test-edge`, 2 s simulated command delay) and CLI 0.1.6-rc2
against nats-server 2.15.3 provisioned with `infra/nats/jetstream/setup_streams.sh`.
Heartbeat/health/position telemetry, JetStream advisories, the CLI's ephemeral response consumers, pull-request polling (`CONSUMER.MSG.NEXT`
and its `408` timeouts) and the CLI's own catalog reads are omitted. Times are seconds since capture start.
`→ ack:` lines are the reply subject a delivered message carries.

## `run2_wrong_run`

```text
 103.59  _INBOX.… [Nats-Stream: KV_MACHINE_COMMANDS, Nats-Subject: $KV.MACHINE_COMMANDS.proto-test, Nats-Sequence: 1]
         {"commands": "cancel(self) -> 'dict'\n    Acknowledge cancel. Run teardown is handled by the edge client.\n\necho(self, message: 'str' = '') -> 'dict'\n    Echo
 103.60  puda.proto-test.cmd.queue (reply → _INBOX)
         command `echo` run_id='99999999-2222-4333-8444-555555555555' step=1 params={"message": "x"}
 103.60  puda.proto-test.cmd.queue → ack: $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         command `echo` run_id='99999999-2222-4333-8444-555555555555' step=1 params={"message": "x"}
 103.60  $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         (empty body = +ACK)
 103.60  puda.proto-test.cmd.response.queue (reply → _INBOX)
         response `echo` run_id='99999999-2222-4333-8444-555555555555' step=1 params={"message": "x"} → **error** code=RUN_ID_MISMATCH message='Run ID mismatch: expected active run, got 99999999-2222-4333-8444-555555555555'
 103.60  puda.proto-test.cmd.response.queue → ack: $JS.ACK.RESPONSE_QUEUE.24OZaOQs (delivery #1)
         response `echo` run_id='99999999-2222-4333-8444-555555555555' step=1 params={"message": "x"} → **error** code=RUN_ID_MISMATCH message='Run ID mismatch: expected active run, got 99999999-2222-4333-8444-555555555555'
 103.60  $JS.ACK.RESPONSE_QUEUE.24OZaOQs (delivery #1)
         "+ACK"
```

## `run2_unknown`

```text
 104.77  _INBOX.… [Nats-Stream: KV_MACHINE_COMMANDS, Nats-Subject: $KV.MACHINE_COMMANDS.proto-test, Nats-Sequence: 1]
         {"commands": "cancel(self) -> 'dict'\n    Acknowledge cancel. Run teardown is handled by the edge client.\n\necho(self, message: 'str' = '') -> 'dict'\n    Echo
 104.77  puda.proto-test.cmd.queue (reply → _INBOX)
         command `not_a_command` run_id='22222222-2222-4333-8444-555555555555' step=1
 104.77  puda.proto-test.cmd.queue → ack: $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         command `not_a_command` run_id='22222222-2222-4333-8444-555555555555' step=1
 104.78  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='busy' run_id='22222222-2222-4333-8444-555555555555'
 104.78  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='error' run_id='22222222-2222-4333-8444-555555555555'
 104.78  $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         "+TERM"
 104.78  puda.proto-test.cmd.response.queue (reply → _INBOX)
         response `not_a_command` run_id='22222222-2222-4333-8444-555555555555' step=1 → **error** code=UNKNOWN_COMMAND message='Unknown or restricted command: not_a_command'
 104.78  puda.proto-test.cmd.response.queue → ack: $JS.ACK.RESPONSE_QUEUE.JnJg6d62 (delivery #1)
         response `not_a_command` run_id='22222222-2222-4333-8444-555555555555' step=1 → **error** code=UNKNOWN_COMMAND message='Unknown or restricted command: not_a_command'
 104.78  $JS.ACK.RESPONSE_QUEUE.JnJg6d62 (delivery #1)
         "+ACK"
```

## `run2_fail`

```text
 105.95  _INBOX.… [Nats-Stream: KV_MACHINE_COMMANDS, Nats-Subject: $KV.MACHINE_COMMANDS.proto-test, Nats-Sequence: 1]
         {"commands": "cancel(self) -> 'dict'\n    Acknowledge cancel. Run teardown is handled by the edge client.\n\necho(self, message: 'str' = '') -> 'dict'\n    Echo
 105.95  puda.proto-test.cmd.queue (reply → _INBOX)
         command `fail` run_id='22222222-2222-4333-8444-555555555555' step=1 params={"message": "boom"}
 105.95  puda.proto-test.cmd.queue → ack: $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         command `fail` run_id='22222222-2222-4333-8444-555555555555' step=1 params={"message": "boom"}
 105.96  $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         (empty body = +ACK)
 105.96  puda.proto-test.cmd.response.queue (reply → _INBOX)
         response `fail` run_id='22222222-2222-4333-8444-555555555555' step=1 params={"message": "boom"} → **error** code=RUN_ID_MISMATCH message='Send START command to start a run before sending commands'
 105.96  puda.proto-test.cmd.response.queue → ack: $JS.ACK.RESPONSE_QUEUE.aJTM3LEd (delivery #1)
         response `fail` run_id='22222222-2222-4333-8444-555555555555' step=1 params={"message": "boom"} → **error** code=RUN_ID_MISMATCH message='Send START command to start a run before sending commands'
 105.96  $JS.ACK.RESPONSE_QUEUE.aJTM3LEd (delivery #1)
         "+ACK"
```

## `run3_double_start`

```text
 117.39  puda.proto-test.cmd.ping (reply → _INBOX)
         "ping"
 117.39  _INBOX.…
         pong {"status": "pong", "machine_id": "proto-test", "timestamp": "2026-11-23T13:26:15Z", "sdk_version": "0.0.23", "uptime_seconds": 117.393, "run_status": 
 117.40  puda.proto-test.cmd.immediate (reply → _INBOX)
         command `start` run_id='44444444-2222-4333-8444-555555555555' step=0
 117.40  puda.proto-test.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         command `start` run_id='44444444-2222-4333-8444-555555555555' step=0
 117.40  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         (empty body = +ACK)
 117.40  puda.proto-test.cmd.response.immediate (reply → _INBOX)
         response `start` run_id='44444444-2222-4333-8444-555555555555' step=0 → **error** code=RUN_ID_MISMATCH message='cannot start, 33333333-2222-4333-8444-555555555555 is currently running'
 117.40  puda.proto-test.cmd.response.immediate → ack: $JS.ACK.RESPONSE_IMMEDIATE.tfb0LZLV (delivery #1)
         response `start` run_id='44444444-2222-4333-8444-555555555555' step=0 → **error** code=RUN_ID_MISMATCH message='cannot start, 33333333-2222-4333-8444-555555555555 is currently running'
 117.40  $JS.ACK.RESPONSE_IMMEDIATE.tfb0LZLV (delivery #1)
         "+ACK"
```

## `raw_ping`

```text
 138.50  puda.proto-test.cmd.ping (reply → _INBOX)
         "ping"
 138.50  _INBOX.…
         pong {"status": "pong", "machine_id": "proto-test", "timestamp": "2026-11-23T13:26:36Z", "sdk_version": "0.0.23", "uptime_seconds": 138.499, "run_status": 
 138.50  puda.proto-test.cmd.ping (reply → _INBOX)
         "hello"
 138.50  _INBOX.…
         error {"status": "error", "machine_id": "proto-test", "timestamp": "2026-11-23T13:26:36Z", "message": "expected ping"}
```

## `imm_start_no_run`

```text
 139.61  puda.proto-test.cmd.immediate (reply → _INBOX)
         command `start` run_id=None step=0
 139.61  puda.proto-test.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         command `start` run_id=None step=0
 139.61  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         (empty body = +ACK)
 139.61  puda.proto-test.cmd.response.immediate (reply → _INBOX)
         response `start` run_id=None step=0 → **error** code=MISSING_RUN_ID message='START command requires RUN_ID'
 141.86  puda.proto-test.cmd.queue → ack: $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #2)
         command `echo` run_id='33333333-2222-4333-8444-555555555555' step=1 params={"message": "while paused"}
 141.86  $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #2)
         (empty body = +ACK)
 141.86  puda.proto-test.cmd.response.queue (reply → _INBOX)
         response `echo` run_id='33333333-2222-4333-8444-555555555555' step=1 params={"message": "while paused"} → **error** code=RUN_ID_MISMATCH message='Send START command to start a run before sending commands'
```

## `imm_unknown`

```text
 142.72  puda.proto-test.cmd.immediate (reply → _INBOX)
         command `frobnicate` run_id=None step=0
 142.72  puda.proto-test.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         command `frobnicate` run_id=None step=0
 142.72  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         (empty body = +ACK)
 142.72  puda.proto-test.cmd.response.immediate (reply → _INBOX)
         response `frobnicate` run_id=None step=0 → **error** code=UNKNOWN_COMMAND message='Unknown immediate command: frobnicate'
```

## `imm_complete_no_run`

```text
 145.82  puda.proto-test.cmd.immediate (reply → _INBOX)
         command `complete` run_id=None step=0
 145.82  puda.proto-test.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         command `complete` run_id=None step=0
 145.82  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         (empty body = +ACK)
 145.82  puda.proto-test.cmd.response.immediate (reply → _INBOX)
         response `complete` run_id=None step=0 → **error** code=MISSING_RUN_ID message='COMPLETE command requires RUN_ID'
```

## `malformed`

```text
 152.04  puda.proto-test.cmd.queue (reply → _INBOX)
         "{not json"
 152.04  puda.proto-test.cmd.queue → ack: $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         "{not json"
 152.04  $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         "+TERM"
 153.04  puda.proto-test.cmd.immediate (reply → _INBOX)
         "{not json"
 153.04  puda.proto-test.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         "{not json"
 153.05  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='error' run_id=None
 153.05  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         (empty body = +ACK)
```

## `queue_null_run`

```text
 155.15  puda.proto-test.cmd.queue (reply → _INBOX)
         command `echo` run_id=None step=1 params={"message": "x"}
 155.15  puda.proto-test.cmd.queue → ack: $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         command `echo` run_id=None step=1 params={"message": "x"}
 155.15  $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         (empty body = +ACK)
 155.15  puda.proto-test.cmd.response.queue (reply → _INBOX)
         response `echo` run_id=None step=1 params={"message": "x"} → **error** code=EXECUTION_ERROR message='Command requires run_id'
```

## `kwargs_merge`

```text
 183.52  puda.proto-test.cmd.immediate (reply → _INBOX)
         command `start` run_id='77777777-2222-4333-8444-555555555555' step=0
 183.52  puda.proto-test.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         command `start` run_id='77777777-2222-4333-8444-555555555555' step=0
 183.52  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         (empty body = +ACK)
 183.52  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='idle' run_id='77777777-2222-4333-8444-555555555555'
 183.53  puda.proto-test.cmd.response.immediate (reply → _INBOX)
         response `start` run_id='77777777-2222-4333-8444-555555555555' step=0 → **success**
 184.53  puda.proto-test.cmd.queue (reply → _INBOX)
         command `echo` run_id='77777777-2222-4333-8444-555555555555' step=1 params={"message": "p"} kwargs={"message": "k"}
 184.53  puda.proto-test.cmd.queue → ack: $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         command `echo` run_id='77777777-2222-4333-8444-555555555555' step=1 params={"message": "p"} kwargs={"message": "k"}
 184.53  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='busy' run_id='77777777-2222-4333-8444-555555555555'
 186.53  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='idle' run_id='77777777-2222-4333-8444-555555555555'
 186.53  puda.proto-test.evt.log
         {"timestamp": "2026-11-23T13:27:24Z", "log_level": "INFO", "msg": "Command echo completed"}
 186.53  $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         (empty body = +ACK)
 186.53  puda.proto-test.cmd.response.queue (reply → _INBOX)
         response `echo` run_id='77777777-2222-4333-8444-555555555555' step=1 params={"message": "p"} kwargs={"message": "k"} → **success** data={"message": "k"}
 188.53  puda.proto-test.cmd.immediate (reply → _INBOX)
         command `complete` run_id='77777777-2222-4333-8444-555555555555' step=0
 188.53  puda.proto-test.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         command `complete` run_id='77777777-2222-4333-8444-555555555555' step=0
 188.53  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         (empty body = +ACK)
 188.53  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='idle' run_id=None
 188.54  puda.proto-test.cmd.response.immediate (reply → _INBOX)
         response `complete` run_id='77777777-2222-4333-8444-555555555555' step=0 → **success**
```
