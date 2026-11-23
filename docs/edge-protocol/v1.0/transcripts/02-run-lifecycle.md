# Run lifecycle and queued commands

Queued command without a run, `machine home` (start → queue → complete), success, `False` result, a 30 s command with in-progress keep-alive.

Captured from Python SDK 0.0.23 (`test-edge`, 2 s simulated command delay) and CLI 0.1.6-rc2
against nats-server 2.15.3 provisioned with `infra/nats/jetstream/setup_streams.sh`.
Heartbeat/health/position telemetry, JetStream advisories, the CLI's ephemeral response consumers, pull-request polling (`CONSUMER.MSG.NEXT`
and its `408` timeouts) and the CLI's own catalog reads are omitted. Times are seconds since capture start.
`→ ack:` lines are the reply subject a delivered message carries.

## `run_ok`

```text
  32.29  _INBOX.… [Nats-Stream: KV_MACHINE_COMMANDS, Nats-Subject: $KV.MACHINE_COMMANDS.proto-test, Nats-Sequence: 1]
         {"commands": "cancel(self) -> 'dict'\n    Acknowledge cancel. Run teardown is handled by the edge client.\n\necho(self, message: 'str' = '') -> 'dict'\n    Echo
  32.29  puda.proto-test.cmd.queue (reply → _INBOX)
         command `echo` run_id='f85ebc75-7b8e-4f00-bf48-0a63109ccd38' step=1 params={"message": "hi"}
  32.29  puda.proto-test.cmd.queue → ack: $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         command `echo` run_id='f85ebc75-7b8e-4f00-bf48-0a63109ccd38' step=1 params={"message": "hi"}
  32.29  $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         (empty body = +ACK)
  32.29  puda.proto-test.cmd.response.queue (reply → _INBOX)
         response `echo` run_id='f85ebc75-7b8e-4f00-bf48-0a63109ccd38' step=1 params={"message": "hi"} → **error** code=RUN_ID_MISMATCH message='Send START command to start a run before sending commands'
  32.30  puda.proto-test.cmd.response.queue → ack: $JS.ACK.RESPONSE_QUEUE.mAFZ6Pzh (delivery #1)
         response `echo` run_id='f85ebc75-7b8e-4f00-bf48-0a63109ccd38' step=1 params={"message": "hi"} → **error** code=RUN_ID_MISMATCH message='Send START command to start a run before sending commands'
  32.30  $JS.ACK.RESPONSE_QUEUE.mAFZ6Pzh (delivery #1)
         "+ACK"
```

## `home`

```text
  38.20  puda.proto-test.cmd.immediate (reply → _INBOX)
         command `start` run_id='0237c75c-c1be-43ff-9d2b-672feb96539b' step=0
  38.20  puda.proto-test.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         command `start` run_id='0237c75c-c1be-43ff-9d2b-672feb96539b' step=0
  38.20  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         (empty body = +ACK)
  38.20  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='idle' run_id='0237c75c-c1be-43ff-9d2b-672feb96539b'
  38.20  puda.proto-test.cmd.response.immediate (reply → _INBOX)
         response `start` run_id='0237c75c-c1be-43ff-9d2b-672feb96539b' step=0 → **success**
  38.21  puda.proto-test.cmd.response.immediate → ack: $JS.ACK.RESPONSE_IMMEDIATE.aiSqHZiQ (delivery #1)
         response `start` run_id='0237c75c-c1be-43ff-9d2b-672feb96539b' step=0 → **success**
  38.21  $JS.ACK.RESPONSE_IMMEDIATE.aiSqHZiQ (delivery #1)
         "+ACK"
  38.21  puda.proto-test.cmd.queue (reply → _INBOX)
         command `home` run_id='0237c75c-c1be-43ff-9d2b-672feb96539b' step=1
  38.21  puda.proto-test.cmd.queue → ack: $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         command `home` run_id='0237c75c-c1be-43ff-9d2b-672feb96539b' step=1
  38.21  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='busy' run_id='0237c75c-c1be-43ff-9d2b-672feb96539b'
  40.21  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='idle' run_id='0237c75c-c1be-43ff-9d2b-672feb96539b'
  40.21  puda.proto-test.evt.log
         {"timestamp": "2026-11-23T13:24:58Z", "log_level": "INFO", "msg": "Command home completed"}
  40.21  $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         (empty body = +ACK)
  40.21  puda.proto-test.cmd.response.queue (reply → _INBOX)
         response `home` run_id='0237c75c-c1be-43ff-9d2b-672feb96539b' step=1 → **success** data={"homed": true, "position": {"x": 0.0, "y": 0.0, "z": 0.0}}
  40.21  puda.proto-test.cmd.response.queue → ack: $JS.ACK.RESPONSE_QUEUE.1sX3xYC0 (delivery #1)
         response `home` run_id='0237c75c-c1be-43ff-9d2b-672feb96539b' step=1 → **success** data={"homed": true, "position": {"x": 0.0, "y": 0.0, "z": 0.0}}
  40.22  $JS.ACK.RESPONSE_QUEUE.1sX3xYC0 (delivery #1)
         "+ACK"
  40.22  puda.proto-test.cmd.immediate (reply → _INBOX)
         command `complete` run_id='0237c75c-c1be-43ff-9d2b-672feb96539b' step=2
  40.22  puda.proto-test.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         command `complete` run_id='0237c75c-c1be-43ff-9d2b-672feb96539b' step=2
  40.22  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         (empty body = +ACK)
  40.22  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='idle' run_id=None
  40.22  puda.proto-test.cmd.response.immediate (reply → _INBOX)
         response `complete` run_id='0237c75c-c1be-43ff-9d2b-672feb96539b' step=2 → **success**
  40.22  puda.proto-test.cmd.response.immediate → ack: $JS.ACK.RESPONSE_IMMEDIATE.aiSqHZiQ (delivery #1)
         response `complete` run_id='0237c75c-c1be-43ff-9d2b-672feb96539b' step=2 → **success**
  40.22  $JS.ACK.RESPONSE_IMMEDIATE.aiSqHZiQ (delivery #1)
         "+ACK"
```

## `run2_start`

```text
  65.70  puda.proto-test.cmd.ping (reply → _INBOX)
         "ping"
  65.70  _INBOX.…
         pong {"status": "pong", "machine_id": "proto-test", "timestamp": "2026-11-23T13:25:23Z", "sdk_version": "0.0.23", "uptime_seconds": 65.701, "run_status": "
  65.71  puda.proto-test.cmd.immediate (reply → _INBOX)
         command `start` run_id='22222222-2222-4333-8444-555555555555' step=0
  65.71  puda.proto-test.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         command `start` run_id='22222222-2222-4333-8444-555555555555' step=0
  65.71  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         (empty body = +ACK)
  65.71  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='idle' run_id='22222222-2222-4333-8444-555555555555'
  65.71  puda.proto-test.cmd.response.immediate (reply → _INBOX)
         response `start` run_id='22222222-2222-4333-8444-555555555555' step=0 → **success**
  65.71  puda.proto-test.cmd.response.immediate → ack: $JS.ACK.RESPONSE_IMMEDIATE.eNukOFgO (delivery #1)
         response `start` run_id='22222222-2222-4333-8444-555555555555' step=0 → **success**
  65.71  $JS.ACK.RESPONSE_IMMEDIATE.eNukOFgO (delivery #1)
         "+ACK"
```

## `run2_ok`

```text
  66.87  _INBOX.… [Nats-Stream: KV_MACHINE_COMMANDS, Nats-Subject: $KV.MACHINE_COMMANDS.proto-test, Nats-Sequence: 1]
         {"commands": "cancel(self) -> 'dict'\n    Acknowledge cancel. Run teardown is handled by the edge client.\n\necho(self, message: 'str' = '') -> 'dict'\n    Echo
  66.88  puda.proto-test.cmd.queue (reply → _INBOX)
         command `echo` run_id='22222222-2222-4333-8444-555555555555' step=1 params={"message": "hi"}
  66.88  puda.proto-test.cmd.queue → ack: $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         command `echo` run_id='22222222-2222-4333-8444-555555555555' step=1 params={"message": "hi"}
  66.88  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='busy' run_id='22222222-2222-4333-8444-555555555555'
  68.88  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='idle' run_id='22222222-2222-4333-8444-555555555555'
  68.88  puda.proto-test.evt.log
         {"timestamp": "2026-11-23T13:25:26Z", "log_level": "INFO", "msg": "Command echo completed"}
  68.88  $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         (empty body = +ACK)
  68.88  puda.proto-test.cmd.response.queue (reply → _INBOX)
         response `echo` run_id='22222222-2222-4333-8444-555555555555' step=1 params={"message": "hi"} → **success** data={"message": "hi"}
  68.88  puda.proto-test.cmd.response.queue → ack: $JS.ACK.RESPONSE_QUEUE.Mstl42g0 (delivery #1)
         response `echo` run_id='22222222-2222-4333-8444-555555555555' step=1 params={"message": "hi"} → **success** data={"message": "hi"}
  68.89  $JS.ACK.RESPONSE_QUEUE.Mstl42g0 (delivery #1)
         "+ACK"
```

## `run2_bool_false`

```text
  70.06  _INBOX.… [Nats-Stream: KV_MACHINE_COMMANDS, Nats-Subject: $KV.MACHINE_COMMANDS.proto-test, Nats-Sequence: 1]
         {"commands": "cancel(self) -> 'dict'\n    Acknowledge cancel. Run teardown is handled by the edge client.\n\necho(self, message: 'str' = '') -> 'dict'\n    Echo
  70.06  puda.proto-test.cmd.queue (reply → _INBOX)
         command `echo_bool` run_id='22222222-2222-4333-8444-555555555555' step=1 params={"enabled": false}
  70.06  puda.proto-test.cmd.queue → ack: $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         command `echo_bool` run_id='22222222-2222-4333-8444-555555555555' step=1 params={"enabled": false}
  70.06  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='busy' run_id='22222222-2222-4333-8444-555555555555'
  70.06  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='idle' run_id='22222222-2222-4333-8444-555555555555'
  70.06  puda.proto-test.evt.log
         {"timestamp": "2026-11-23T13:25:27Z", "log_level": "INFO", "msg": "Command echo_bool completed"}
  70.06  $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         (empty body = +ACK)
  70.06  puda.proto-test.cmd.response.queue (reply → _INBOX)
         response `echo_bool` run_id='22222222-2222-4333-8444-555555555555' step=1 params={"enabled": false} → **success** data={"result": false}
  70.06  puda.proto-test.cmd.response.queue → ack: $JS.ACK.RESPONSE_QUEUE.7ud6OB0m (delivery #1)
         response `echo_bool` run_id='22222222-2222-4333-8444-555555555555' step=1 params={"enabled": false} → **success** data={"result": false}
  70.06  $JS.ACK.RESPONSE_QUEUE.7ud6OB0m (delivery #1)
         "+ACK"
```

## `run2_slow`

```text
  72.40  _INBOX.… [Nats-Stream: KV_MACHINE_COMMANDS, Nats-Subject: $KV.MACHINE_COMMANDS.proto-test, Nats-Sequence: 1]
         {"commands": "cancel(self) -> 'dict'\n    Acknowledge cancel. Run teardown is handled by the edge client.\n\necho(self, message: 'str' = '') -> 'dict'\n    Echo
  72.41  puda.proto-test.cmd.queue (reply → _INBOX)
         command `wait` run_id='22222222-2222-4333-8444-555555555555' step=1 params={"seconds": 30}
  72.41  puda.proto-test.cmd.queue → ack: $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         command `wait` run_id='22222222-2222-4333-8444-555555555555' step=1 params={"seconds": 30}
  72.41  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='busy' run_id='22222222-2222-4333-8444-555555555555'
  97.41  $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         "+WPI"
 102.41  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='idle' run_id='22222222-2222-4333-8444-555555555555'
 102.41  puda.proto-test.evt.log
         {"timestamp": "2026-11-23T13:26:00Z", "log_level": "INFO", "msg": "Command wait completed"}
 102.41  $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         (empty body = +ACK)
 102.41  puda.proto-test.cmd.response.queue (reply → _INBOX)
         response `wait` run_id='22222222-2222-4333-8444-555555555555' step=1 params={"seconds": 30} → **success** data={"waited": 30.0}
 102.41  puda.proto-test.cmd.response.queue → ack: $JS.ACK.RESPONSE_QUEUE.FJ02hcbX (delivery #1)
         response `wait` run_id='22222222-2222-4333-8444-555555555555' step=1 params={"seconds": 30} → **success** data={"waited": 30.0}
 102.42  $JS.ACK.RESPONSE_QUEUE.FJ02hcbX (delivery #1)
         "+ACK"
```

## `run2_complete`

```text
 108.31  puda.proto-test.cmd.ping (reply → _INBOX)
         "ping"
 108.31  _INBOX.…
         pong {"status": "pong", "machine_id": "proto-test", "timestamp": "2026-11-23T13:26:06Z", "sdk_version": "0.0.23", "uptime_seconds": 108.31, "run_status": "
 108.31  puda.proto-test.cmd.immediate (reply → _INBOX)
         command `complete` run_id='22222222-2222-4333-8444-555555555555' step=0
 108.32  puda.proto-test.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         command `complete` run_id='22222222-2222-4333-8444-555555555555' step=0
 108.32  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         (empty body = +ACK)
 108.32  puda.proto-test.cmd.response.immediate (reply → _INBOX)
         response `complete` run_id='22222222-2222-4333-8444-555555555555' step=0 → **error** code=RUN_ID_MISMATCH message='Run 22222222-2222-4333-8444-555555555555 not active'
 108.32  puda.proto-test.cmd.response.immediate → ack: $JS.ACK.RESPONSE_IMMEDIATE.O0WdSyUb (delivery #1)
         response `complete` run_id='22222222-2222-4333-8444-555555555555' step=0 → **error** code=RUN_ID_MISMATCH message='Run 22222222-2222-4333-8444-555555555555 not active'
 108.32  $JS.ACK.RESPONSE_IMMEDIATE.O0WdSyUb (delivery #1)
         "+ACK"
```
