# Pause, cancel and emergency stop

Includes the unacknowledged paused command being redelivered after `ack_wait` (see §13 D-1) , cancel not interrupting the running command (D-2), and a driver without pause/resume/cancel methods (`proto-min`, D-8).

Captured from Python SDK 0.0.23 (`test-edge`, 2 s simulated command delay) and CLI 0.1.6-rc2
against nats-server 2.15.3 provisioned with `infra/nats/jetstream/setup_streams.sh`.
Heartbeat/health/position telemetry, JetStream advisories, the CLI's ephemeral response consumers, pull-request polling (`CONSUMER.MSG.NEXT`
and its `408` timeouts) and the CLI's own catalog reads are omitted. Times are seconds since capture start.
`→ ack:` lines are the reply subject a delivered message carries.

## `run3_start`

```text
 109.48  puda.proto-test.cmd.ping (reply → _INBOX)
         "ping"
 109.48  _INBOX.…
         pong {"status": "pong", "machine_id": "proto-test", "timestamp": "2026-11-23T13:26:07Z", "sdk_version": "0.0.23", "uptime_seconds": 109.486, "run_status": 
 109.49  puda.proto-test.cmd.immediate (reply → _INBOX)
         command `start` run_id='33333333-2222-4333-8444-555555555555' step=0
 109.49  puda.proto-test.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         command `start` run_id='33333333-2222-4333-8444-555555555555' step=0
 109.49  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         (empty body = +ACK)
 109.49  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='idle' run_id='33333333-2222-4333-8444-555555555555'
 109.49  puda.proto-test.cmd.response.immediate (reply → _INBOX)
         response `start` run_id='33333333-2222-4333-8444-555555555555' step=0 → **success**
 109.49  puda.proto-test.cmd.response.immediate → ack: $JS.ACK.RESPONSE_IMMEDIATE.XhdDhx3z (delivery #1)
         response `start` run_id='33333333-2222-4333-8444-555555555555' step=0 → **success**
 109.49  $JS.ACK.RESPONSE_IMMEDIATE.XhdDhx3z (delivery #1)
         "+ACK"
```

## `run3_pause`

```text
 110.66  puda.proto-test.cmd.ping (reply → _INBOX)
         "ping"
 110.66  _INBOX.…
         pong {"status": "pong", "machine_id": "proto-test", "timestamp": "2026-11-23T13:26:08Z", "sdk_version": "0.0.23", "uptime_seconds": 110.666, "run_status": 
 110.67  puda.proto-test.cmd.immediate (reply → _INBOX)
         command `pause` run_id='' step=0
 110.67  puda.proto-test.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         command `pause` run_id='' step=0
 110.67  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         (empty body = +ACK)
 110.67  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='paused' run_id=''
 110.67  puda.proto-test.cmd.response.immediate (reply → _INBOX)
         response `pause` run_id='' step=0 → **success** data={"paused": true}
 110.67  puda.proto-test.cmd.response.immediate → ack: $JS.ACK.RESPONSE_IMMEDIATE.aG9Bg6jm (delivery #1)
         response `pause` run_id='' step=0 → **success** data={"paused": true}
 110.67  $JS.ACK.RESPONSE_IMMEDIATE.aG9Bg6jm (delivery #1)
         "+ACK"
```

## `run3_paused_cmd`

```text
 111.85  _INBOX.… [Nats-Stream: KV_MACHINE_COMMANDS, Nats-Subject: $KV.MACHINE_COMMANDS.proto-test, Nats-Sequence: 1]
         {"commands": "cancel(self) -> 'dict'\n    Acknowledge cancel. Run teardown is handled by the edge client.\n\necho(self, message: 'str' = '') -> 'dict'\n    Echo
 111.86  puda.proto-test.cmd.queue (reply → _INBOX)
         command `echo` run_id='33333333-2222-4333-8444-555555555555' step=1 params={"message": "while paused"}
 111.86  puda.proto-test.cmd.queue → ack: $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         command `echo` run_id='33333333-2222-4333-8444-555555555555' step=1 params={"message": "while paused"}
 111.86  puda.proto-test.cmd.response.queue (reply → _INBOX)
         response `echo` run_id='33333333-2222-4333-8444-555555555555' step=1 params={"message": "while paused"} → **error** code=MACHINE_PAUSED message='Machine paused'
 111.86  puda.proto-test.cmd.response.queue → ack: $JS.ACK.RESPONSE_QUEUE.02wccBrZ (delivery #1)
         response `echo` run_id='33333333-2222-4333-8444-555555555555' step=1 params={"message": "while paused"} → **error** code=MACHINE_PAUSED message='Machine paused'
 111.86  $JS.ACK.RESPONSE_QUEUE.02wccBrZ (delivery #1)
         "+ACK"
```

## `run3_resume`

```text
 113.02  puda.proto-test.cmd.ping (reply → _INBOX)
         "ping"
 113.02  _INBOX.…
         pong {"status": "pong", "machine_id": "proto-test", "timestamp": "2026-11-23T13:26:10Z", "sdk_version": "0.0.23", "uptime_seconds": 113.026, "run_status": 
 113.03  puda.proto-test.cmd.immediate (reply → _INBOX)
         command `resume` run_id='' step=0
 113.03  puda.proto-test.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         command `resume` run_id='' step=0
 113.03  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         (empty body = +ACK)
 113.03  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='idle' run_id=None
 113.03  puda.proto-test.cmd.response.immediate (reply → _INBOX)
         response `resume` run_id='' step=0 → **success** data={"paused": false}
 113.03  puda.proto-test.cmd.response.immediate → ack: $JS.ACK.RESPONSE_IMMEDIATE.tHKJXt2o (delivery #1)
         response `resume` run_id='' step=0 → **success** data={"paused": false}
 113.03  $JS.ACK.RESPONSE_IMMEDIATE.tHKJXt2o (delivery #1)
         "+ACK"
```

## `run3_after`

```text
 114.21  _INBOX.… [Nats-Stream: KV_MACHINE_COMMANDS, Nats-Subject: $KV.MACHINE_COMMANDS.proto-test, Nats-Sequence: 1]
         {"commands": "cancel(self) -> 'dict'\n    Acknowledge cancel. Run teardown is handled by the edge client.\n\necho(self, message: 'str' = '') -> 'dict'\n    Echo
 114.21  puda.proto-test.cmd.queue (reply → _INBOX)
         command `echo` run_id='33333333-2222-4333-8444-555555555555' step=1 params={"message": "after resume"}
 114.21  puda.proto-test.cmd.queue → ack: $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         command `echo` run_id='33333333-2222-4333-8444-555555555555' step=1 params={"message": "after resume"}
 114.21  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='busy' run_id='33333333-2222-4333-8444-555555555555'
 116.22  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='idle' run_id='33333333-2222-4333-8444-555555555555'
 116.22  puda.proto-test.evt.log
         {"timestamp": "2026-11-23T13:26:14Z", "log_level": "INFO", "msg": "Command echo completed"}
 116.22  $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         (empty body = +ACK)
 116.22  puda.proto-test.cmd.response.queue (reply → _INBOX)
         response `echo` run_id='33333333-2222-4333-8444-555555555555' step=1 params={"message": "after resume"} → **success** data={"message": "after resume"}
 116.22  puda.proto-test.cmd.response.queue → ack: $JS.ACK.RESPONSE_QUEUE.q0RktcU4 (delivery #1)
         response `echo` run_id='33333333-2222-4333-8444-555555555555' step=1 params={"message": "after resume"} → **success** data={"message": "after resume"}
 116.22  $JS.ACK.RESPONSE_QUEUE.q0RktcU4 (delivery #1)
         "+ACK"
```

## `run3_complete`

```text
 118.57  puda.proto-test.cmd.ping (reply → _INBOX)
         "ping"
 118.57  _INBOX.…
         pong {"status": "pong", "machine_id": "proto-test", "timestamp": "2026-11-23T13:26:16Z", "sdk_version": "0.0.23", "uptime_seconds": 118.57, "run_status": "
 118.57  puda.proto-test.cmd.immediate (reply → _INBOX)
         command `complete` run_id='33333333-2222-4333-8444-555555555555' step=0
 118.57  puda.proto-test.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         command `complete` run_id='33333333-2222-4333-8444-555555555555' step=0
 118.57  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         (empty body = +ACK)
 118.58  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='idle' run_id=None
 118.58  puda.proto-test.cmd.response.immediate (reply → _INBOX)
         response `complete` run_id='33333333-2222-4333-8444-555555555555' step=0 → **success**
 118.58  puda.proto-test.cmd.response.immediate → ack: $JS.ACK.RESPONSE_IMMEDIATE.0RmCUaWo (delivery #1)
         response `complete` run_id='33333333-2222-4333-8444-555555555555' step=0 → **success**
 118.58  $JS.ACK.RESPONSE_IMMEDIATE.0RmCUaWo (delivery #1)
         "+ACK"
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

## `cancel_flow`

```text
 157.26  puda.proto-test.cmd.immediate (reply → _INBOX)
         command `start` run_id='55555555-2222-4333-8444-555555555555' step=0
 157.26  puda.proto-test.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         command `start` run_id='55555555-2222-4333-8444-555555555555' step=0
 157.26  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         (empty body = +ACK)
 157.26  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='idle' run_id='55555555-2222-4333-8444-555555555555'
 157.26  puda.proto-test.cmd.response.immediate (reply → _INBOX)
         response `start` run_id='55555555-2222-4333-8444-555555555555' step=0 → **success**
 158.26  puda.proto-test.cmd.queue (reply → _INBOX)
         command `wait` run_id='55555555-2222-4333-8444-555555555555' step=1 params={"seconds": 10}
 158.26  puda.proto-test.cmd.queue → ack: $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         command `wait` run_id='55555555-2222-4333-8444-555555555555' step=1 params={"seconds": 10}
 158.26  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='busy' run_id='55555555-2222-4333-8444-555555555555'
 159.76  puda.proto-test.cmd.immediate (reply → _INBOX)
         command `cancel` run_id='55555555-2222-4333-8444-555555555555' step=0
 159.77  puda.proto-test.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         command `cancel` run_id='55555555-2222-4333-8444-555555555555' step=0
 159.77  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         (empty body = +ACK)
 159.77  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='idle' run_id=None
 159.77  puda.proto-test.cmd.response.immediate (reply → _INBOX)
         response `cancel` run_id='55555555-2222-4333-8444-555555555555' step=0 → **success** data={"cancelled": true}
 162.77  puda.proto-test.cmd.queue (reply → _INBOX)
         command `echo` run_id='55555555-2222-4333-8444-555555555555' step=2 params={"message": "after cancel"}
```

## `estop_flow`

```text
 165.38  puda.proto-test.cmd.immediate (reply → _INBOX)
         command `start` run_id='66666666-2222-4333-8444-555555555555' step=0
 165.38  puda.proto-test.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         command `start` run_id='66666666-2222-4333-8444-555555555555' step=0
 165.38  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         (empty body = +ACK)
 165.38  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='idle' run_id='66666666-2222-4333-8444-555555555555'
 165.38  puda.proto-test.cmd.response.immediate (reply → _INBOX)
         response `start` run_id='66666666-2222-4333-8444-555555555555' step=0 → **success**
 166.38  puda.proto-test.cmd.queue (reply → _INBOX)
         command `wait` run_id='66666666-2222-4333-8444-555555555555' step=1 params={"seconds": 10}
 167.89  puda.proto-test.cmd.immediate (reply → _INBOX)
         command `estop` run_id='66666666-2222-4333-8444-555555555555' step=0
 167.89  puda.proto-test.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         command `estop` run_id='66666666-2222-4333-8444-555555555555' step=0
 167.89  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         (empty body = +ACK)
 167.89  puda.proto-test.evt.log
         {"timestamp": "2026-11-23T13:27:05Z", "log_level": "CRITICAL", "msg": "Emergency stop received"}
 167.89  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='estopped' run_id=None
 167.89  $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         "+TERM"
 167.89  puda.proto-test.cmd.response.queue (reply → _INBOX)
         response `wait` run_id='55555555-2222-4333-8444-555555555555' step=1 params={"seconds": 10} → **error** code=COMMAND_CANCELLED message='Command was cancelled'
 167.89  puda.proto-test.cmd.response.immediate (reply → _INBOX)
         response `estop` run_id='66666666-2222-4333-8444-555555555555' step=0 → **error** code=ESTOP_NOT_SUPPORTED message='Driver has no estop command: queue halted and running command cancelled, but no hardware s'
 167.89  puda.proto-test.cmd.queue → ack: $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         command `echo` run_id='55555555-2222-4333-8444-555555555555' step=2 params={"message": "after cancel"}
 167.89  $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         "+TERM"
 167.89  puda.proto-test.cmd.response.queue (reply → _INBOX)
         response `echo` run_id='55555555-2222-4333-8444-555555555555' step=2 params={"message": "after cancel"} → **error** code=MACHINE_ESTOPPED message='Machine emergency stopped; send reset before queuing commands'
 167.89  puda.proto-test.cmd.queue → ack: $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         command `wait` run_id='66666666-2222-4333-8444-555555555555' step=1 params={"seconds": 10}
 167.89  $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         "+TERM"
 167.89  puda.proto-test.cmd.response.queue (reply → _INBOX)
         response `wait` run_id='66666666-2222-4333-8444-555555555555' step=1 params={"seconds": 10} → **error** code=MACHINE_ESTOPPED message='Machine emergency stopped; send reset before queuing commands'
 170.89  puda.proto-test.cmd.immediate (reply → _INBOX)
         command `start` run_id='66666666-2222-4333-8444-555555555555' step=0
 170.89  puda.proto-test.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         command `start` run_id='66666666-2222-4333-8444-555555555555' step=0
 170.89  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         (empty body = +ACK)
 170.89  puda.proto-test.cmd.response.immediate (reply → _INBOX)
         response `start` run_id='66666666-2222-4333-8444-555555555555' step=0 → **error** code=MACHINE_ESTOPPED message='Machine emergency stopped; send reset before start'
 171.89  puda.proto-test.cmd.queue (reply → _INBOX)
         command `echo` run_id='66666666-2222-4333-8444-555555555555' step=2 params={"message": "latched"}
 171.89  puda.proto-test.cmd.queue → ack: $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         command `echo` run_id='66666666-2222-4333-8444-555555555555' step=2 params={"message": "latched"}
 171.90  $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         "+TERM"
 171.90  puda.proto-test.cmd.response.queue (reply → _INBOX)
         response `echo` run_id='66666666-2222-4333-8444-555555555555' step=2 params={"message": "latched"} → **error** code=MACHINE_ESTOPPED message='Machine emergency stopped; send reset before queuing commands'
 173.40  puda.proto-test.cmd.immediate (reply → _INBOX)
         command `resume` run_id=None step=0
 173.40  puda.proto-test.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         command `resume` run_id=None step=0
 173.40  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         (empty body = +ACK)
 173.40  puda.proto-test.cmd.response.immediate (reply → _INBOX)
         response `resume` run_id=None step=0 → **error** code=MACHINE_ESTOPPED message='Machine emergency stopped; send reset before resume'
 174.40  puda.proto-test.cmd.immediate (reply → _INBOX)
         command `reset` run_id=None step=0
 174.40  puda.proto-test.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         command `reset` run_id=None step=0
 174.40  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         (empty body = +ACK)
 176.40  puda.proto-test.cmd.immediate (reply → _INBOX)
         command `start` run_id='66666666-2222-4333-8444-555555555555' step=0
 176.40  puda.proto-test.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         command `start` run_id='66666666-2222-4333-8444-555555555555' step=0
 176.41  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='idle' run_id=None
 176.41  puda.proto-test.cmd.response.immediate (reply → _INBOX)
         response `reset` run_id=None step=0 → **success** data={"reset": true, "position": {"x": 0.0, "y": 0.0, "z": 0.0}}
 176.41  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         (empty body = +ACK)
 176.41  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='idle' run_id='66666666-2222-4333-8444-555555555555'
 176.41  puda.proto-test.cmd.response.immediate (reply → _INBOX)
         response `start` run_id='66666666-2222-4333-8444-555555555555' step=0 → **success**
 177.41  puda.proto-test.cmd.queue (reply → _INBOX)
         command `echo` run_id='66666666-2222-4333-8444-555555555555' step=3 params={"message": "after reset"}
 177.41  puda.proto-test.cmd.queue → ack: $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         command `echo` run_id='66666666-2222-4333-8444-555555555555' step=3 params={"message": "after reset"}
 177.41  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='busy' run_id='66666666-2222-4333-8444-555555555555'
 179.41  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='idle' run_id='66666666-2222-4333-8444-555555555555'
 179.41  puda.proto-test.evt.log
         {"timestamp": "2026-11-23T13:27:17Z", "log_level": "INFO", "msg": "Command echo completed"}
 179.42  $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         (empty body = +ACK)
 179.42  puda.proto-test.cmd.response.queue (reply → _INBOX)
         response `echo` run_id='66666666-2222-4333-8444-555555555555' step=3 params={"message": "after reset"} → **success** data={"message": "after reset"}
 181.41  puda.proto-test.cmd.immediate (reply → _INBOX)
         command `complete` run_id='66666666-2222-4333-8444-555555555555' step=0
 181.42  puda.proto-test.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         command `complete` run_id='66666666-2222-4333-8444-555555555555' step=0
 181.42  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         (empty body = +ACK)
 181.42  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='idle' run_id=None
 181.42  puda.proto-test.cmd.response.immediate (reply → _INBOX)
         response `complete` run_id='66666666-2222-4333-8444-555555555555' step=0 → **success**
```

## `min_driver`

```text
 885.89  puda.proto-min.cmd.ping (reply → _INBOX)
         "ping"
 885.89  _INBOX.…
         pong {"status": "pong", "machine_id": "proto-min", "timestamp": "2026-11-23T13:39:03Z", "sdk_version": "0.0.23", "uptime_seconds": 9.251, "run_status": "id
 885.90  puda.proto-min.cmd.immediate (reply → _INBOX)
         command `start` run_id='cccccccc-2222-4333-8444-555555555555' step=0
 885.90  puda.proto-min.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-min (delivery #1)
         command `start` run_id='cccccccc-2222-4333-8444-555555555555' step=0
 885.90  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-min (delivery #1)
         (empty body = +ACK)
 885.90  $KV.MACHINE_STATE.proto-min (reply → _INBOX)
         state='idle' run_id='cccccccc-2222-4333-8444-555555555555'
 885.90  puda.proto-min.cmd.response.immediate (reply → _INBOX)
         response `start` run_id='cccccccc-2222-4333-8444-555555555555' step=0 → **success**
 885.90  puda.proto-min.cmd.response.immediate → ack: $JS.ACK.RESPONSE_IMMEDIATE.1bPRJIT4 (delivery #1)
         response `start` run_id='cccccccc-2222-4333-8444-555555555555' step=0 → **success**
 885.90  $JS.ACK.RESPONSE_IMMEDIATE.1bPRJIT4 (delivery #1)
         "+ACK"
 885.91  puda.proto-min.cmd.ping (reply → _INBOX)
         "ping"
 885.91  _INBOX.…
         pong {"status": "pong", "machine_id": "proto-min", "timestamp": "2026-11-23T13:39:03Z", "sdk_version": "0.0.23", "uptime_seconds": 9.269, "run_status": "id
 885.91  puda.proto-min.cmd.immediate (reply → _INBOX)
         command `pause` run_id='' step=0
 885.91  puda.proto-min.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-min (delivery #1)
         command `pause` run_id='' step=0
 885.91  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-min (delivery #1)
         (empty body = +ACK)
 885.91  $KV.MACHINE_STATE.proto-min (reply → _INBOX)
         state='paused' run_id=''
 885.91  puda.proto-min.cmd.response.immediate (reply → _INBOX)
         response `pause` run_id='' step=0 → **error** code=UNKNOWN_COMMAND message='Unknown or restricted command: pause'
 885.91  puda.proto-min.cmd.response.immediate → ack: $JS.ACK.RESPONSE_IMMEDIATE.lECepwsJ (delivery #1)
         response `pause` run_id='' step=0 → **error** code=UNKNOWN_COMMAND message='Unknown or restricted command: pause'
 885.91  $JS.ACK.RESPONSE_IMMEDIATE.lECepwsJ (delivery #1)
         "+ACK"
 885.92  puda.proto-min.cmd.ping (reply → _INBOX)
         "ping"
 885.92  _INBOX.…
         pong {"status": "pong", "machine_id": "proto-min", "timestamp": "2026-11-23T13:39:03Z", "sdk_version": "0.0.23", "uptime_seconds": 9.282, "run_status": "id
 885.92  puda.proto-min.cmd.immediate (reply → _INBOX)
         command `resume` run_id='' step=0
 885.92  puda.proto-min.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-min (delivery #1)
         command `resume` run_id='' step=0
 885.93  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-min (delivery #1)
         (empty body = +ACK)
 885.93  $KV.MACHINE_STATE.proto-min (reply → _INBOX)
         state='idle' run_id=None
 885.93  puda.proto-min.cmd.response.immediate (reply → _INBOX)
         response `resume` run_id='' step=0 → **error** code=UNKNOWN_COMMAND message='Unknown or restricted command: resume'
 885.93  puda.proto-min.cmd.response.immediate → ack: $JS.ACK.RESPONSE_IMMEDIATE.EyTsUYmf (delivery #1)
         response `resume` run_id='' step=0 → **error** code=UNKNOWN_COMMAND message='Unknown or restricted command: resume'
 885.93  $JS.ACK.RESPONSE_IMMEDIATE.EyTsUYmf (delivery #1)
         "+ACK"
 885.93  puda.proto-min.cmd.ping (reply → _INBOX)
         "ping"
 885.93  _INBOX.…
         pong {"status": "pong", "machine_id": "proto-min", "timestamp": "2026-11-23T13:39:03Z", "sdk_version": "0.0.23", "uptime_seconds": 9.295, "run_status": "id
 885.94  puda.proto-min.cmd.immediate (reply → _INBOX)
         command `reset` run_id='' step=0
 885.94  puda.proto-min.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-min (delivery #1)
         command `reset` run_id='' step=0
 885.94  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-min (delivery #1)
         (empty body = +ACK)
 885.94  $KV.MACHINE_STATE.proto-min (reply → _INBOX)
         state='idle' run_id=None
 885.94  puda.proto-min.cmd.response.immediate (reply → _INBOX)
         response `reset` run_id='' step=0 → **success**
 885.94  puda.proto-min.cmd.response.immediate → ack: $JS.ACK.RESPONSE_IMMEDIATE.poU16DcL (delivery #1)
         response `reset` run_id='' step=0 → **success**
 885.94  $JS.ACK.RESPONSE_IMMEDIATE.poU16DcL (delivery #1)
         "+ACK"
 886.06  puda.proto-min.cmd.immediate (reply → _INBOX)
         command `start` run_id='dddddddd-2222-4333-8444-555555555555' step=0
 886.06  puda.proto-min.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-min (delivery #1)
         command `start` run_id='dddddddd-2222-4333-8444-555555555555' step=0
 886.06  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-min (delivery #1)
         (empty body = +ACK)
 886.06  $KV.MACHINE_STATE.proto-min (reply → _INBOX)
         state='idle' run_id='dddddddd-2222-4333-8444-555555555555'
 886.06  puda.proto-min.cmd.response.immediate (reply → _INBOX)
         response `start` run_id='dddddddd-2222-4333-8444-555555555555' step=0 → **success**
 887.06  puda.proto-min.cmd.immediate (reply → _INBOX)
         command `cancel` run_id='dddddddd-2222-4333-8444-555555555555' step=0
 887.06  puda.proto-min.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-min (delivery #1)
         command `cancel` run_id='dddddddd-2222-4333-8444-555555555555' step=0
 887.06  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-min (delivery #1)
         (empty body = +ACK)
 887.06  $KV.MACHINE_STATE.proto-min (reply → _INBOX)
         state='idle' run_id=None
 887.06  puda.proto-min.cmd.response.immediate (reply → _INBOX)
         response `cancel` run_id='dddddddd-2222-4333-8444-555555555555' step=0 → **error** code=UNKNOWN_COMMAND message='Unknown or restricted command: cancel'
 888.06  puda.proto-min.cmd.immediate (reply → _INBOX)
         command `estop` run_id=None step=0
 888.06  puda.proto-min.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-min (delivery #1)
         command `estop` run_id=None step=0
 888.06  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-min (delivery #1)
         (empty body = +ACK)
 888.06  puda.proto-min.evt.log
         {"timestamp": "2026-11-23T13:39:05Z", "log_level": "CRITICAL", "msg": "Emergency stop received"}
 888.06  $KV.MACHINE_STATE.proto-min (reply → _INBOX)
         state='estopped' run_id=None
 888.07  puda.proto-min.cmd.response.immediate (reply → _INBOX)
         response `estop` run_id=None step=0 → **error** code=ESTOP_NOT_SUPPORTED message='Driver has no estop command: queue halted, but no hardware stop was sent'
 889.07  puda.proto-min.cmd.immediate (reply → _INBOX)
         command `reset` run_id=None step=0
 889.07  puda.proto-min.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-min (delivery #1)
         command `reset` run_id=None step=0
 889.07  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-min (delivery #1)
         (empty body = +ACK)
 889.07  $KV.MACHINE_STATE.proto-min (reply → _INBOX)
         state='idle' run_id=None
 889.07  puda.proto-min.cmd.response.immediate (reply → _INBOX)
         response `reset` run_id=None step=0 → **success**
```
