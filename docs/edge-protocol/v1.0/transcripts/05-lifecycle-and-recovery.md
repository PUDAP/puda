# Update, shutdown, restart and offline backlog

Update request answered with an error (no restart), graceful shutdown (`offline`), restart with an existing durable, commands sent while the edge was offline (D-5).

Captured from Python SDK 0.0.23 (`test-edge`, 2 s simulated command delay) and CLI 0.1.6-rc2
against nats-server 2.15.3 provisioned with `infra/nats/jetstream/setup_streams.sh`.
Heartbeat/health/position telemetry, JetStream advisories, the CLI's ephemeral response consumers, pull-request polling (`CONSUMER.MSG.NEXT`
and its `408` timeouts) and the CLI's own catalog reads are omitted. Times are seconds since capture start.
`→ ack:` lines are the reply subject a delivered message carries.

## `update_bad`

```text
  50.88  puda.proto-test.update
         command `update` run_id='f469f611-d913-4dfe-a883-579448dc3b7a' step=0 params={"ref": "invalid.invalid/none:0", "source_type": "docker"}
  50.92  puda.proto-test.update.response
         response `update` run_id='f469f611-d913-4dfe-a883-579448dc3b7a' step=0 params={"ref": "invalid.invalid/none:0", "source_type": "docker"} → **error** code=EXECUTION_ERROR message='docker pull failed: permission denied while trying to connect to the docker API at unix://'
  50.92  puda.proto-test.evt.log
         {"timestamp": "2026-11-23T13:25:08Z", "log_level": "ERROR", "msg": "Update error: docker pull failed: permission denied while trying to connect to the docker AP
```

## `shutdown_sigint`

```text
 509.53  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='offline' run_id=None
```

## `restart_edge`

```text
 518.21  $JS.API.STREAM.CREATE.KV_MACHINE_STATE (reply → _INBOX)
         {"name": "KV_MACHINE_STATE", "subjects": ["$KV.MACHINE_STATE.>"], "max_consumers": -1, "max_msgs": -1, "discard": "new", "discard_new_per_subject": false, "max_
 518.21  _INBOX.…
         stream_create_response ERROR 10058 stream name already in use with a different configuration
 518.21  $JS.API.STREAM.CREATE.KV_MACHINE_COMMANDS (reply → _INBOX)
         {"name": "KV_MACHINE_COMMANDS", "subjects": ["$KV.MACHINE_COMMANDS.>"], "max_consumers": -1, "max_msgs": -1, "discard": "new", "discard_new_per_subject": false,
 518.21  _INBOX.…
         stream_create_response ERROR 10058 stream name already in use with a different configuration
 518.21  $JS.API.CONSUMER.INFO.COMMAND_QUEUE.cmd_queue_proto-test (reply → _INBOX)
         ""
 518.21  _INBOX.…
         consumer_info_response
 518.21  $JS.API.CONSUMER.INFO.COMMAND_QUEUE.cmd_queue_proto-test (reply → _INBOX)
         ""
 518.21  _INBOX.…
         consumer_info_response
 518.21  $JS.API.CONSUMER.INFO.COMMAND_QUEUE.cmd_queue_proto-test (reply → _INBOX)
         ""
 518.21  _INBOX.…
         consumer_info_response
 518.22  $JS.API.CONSUMER.DELETE.COMMAND_IMMEDIATE.cmd_immed_proto-test (reply → _INBOX)
         ""
 518.22  _INBOX.…
         consumer_delete_response
 518.22  $JS.API.CONSUMER.INFO.COMMAND_IMMEDIATE.cmd_immed_proto-test (reply → _INBOX)
         ""
 518.22  _INBOX.…
         consumer_info_response ERROR 10014 consumer not found
 518.22  $JS.API.CONSUMER.DURABLE.CREATE.COMMAND_IMMEDIATE.cmd_immed_proto-test (reply → _INBOX)
         config={"durable_name": "cmd_immed_proto-test", "deliver_policy": "all", "ack_policy": "explicit", "filter_subject": "puda.proto-test.cmd.immediate", "replay_policy": "instant", "flow_control": false, "deliver_subject": "_INBOX
 518.22  _INBOX.…
         consumer_create_response
 518.22  $KV.MACHINE_COMMANDS.proto-test (reply → _INBOX)
         {"commands": "cancel(self) -> 'dict'\n    Acknowledge cancel. Run teardown is handled by the edge client.\n\necho(self, message: 'str' = '') -> 'dict'\n    Echo
 518.22  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='idle' run_id=None
```

## `offline_backlog`

```text
 563.64  puda.proto-test.cmd.immediate (reply → _INBOX)
         command `start` run_id='88888888-2222-4333-8444-555555555555' step=0
 563.64  puda.proto-test.cmd.queue (reply → _INBOX)
         command `echo` run_id='88888888-2222-4333-8444-555555555555' step=1 params={"message": "queued while offline"}
 568.74  $JS.API.STREAM.CREATE.KV_MACHINE_STATE (reply → _INBOX)
         {"name": "KV_MACHINE_STATE", "subjects": ["$KV.MACHINE_STATE.>"], "max_consumers": -1, "max_msgs": -1, "discard": "new", "discard_new_per_subject": false, "max_
 568.74  _INBOX.…
         stream_create_response ERROR 10058 stream name already in use with a different configuration
 568.74  $JS.API.STREAM.CREATE.KV_MACHINE_COMMANDS (reply → _INBOX)
         {"name": "KV_MACHINE_COMMANDS", "subjects": ["$KV.MACHINE_COMMANDS.>"], "max_consumers": -1, "max_msgs": -1, "discard": "new", "discard_new_per_subject": false,
 568.74  _INBOX.…
         stream_create_response ERROR 10058 stream name already in use with a different configuration
 568.74  $JS.API.CONSUMER.INFO.COMMAND_QUEUE.cmd_queue_proto-test (reply → _INBOX)
         ""
 568.74  _INBOX.…
         consumer_info_response
 568.74  $JS.API.CONSUMER.INFO.COMMAND_QUEUE.cmd_queue_proto-test (reply → _INBOX)
         ""
 568.74  _INBOX.…
         consumer_info_response
 568.74  $JS.API.CONSUMER.INFO.COMMAND_QUEUE.cmd_queue_proto-test (reply → _INBOX)
         ""
 568.74  _INBOX.…
         consumer_info_response
 568.74  puda.proto-test.cmd.queue → ack: $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         command `echo` run_id='88888888-2222-4333-8444-555555555555' step=1 params={"message": "queued while offline"}
 568.74  $JS.ACK.COMMAND_QUEUE.cmd_queue_proto-test (delivery #1)
         (empty body = +ACK)
 568.75  puda.proto-test.cmd.response.queue (reply → _INBOX)
         response `echo` run_id='88888888-2222-4333-8444-555555555555' step=1 params={"message": "queued while offline"} → **error** code=RUN_ID_MISMATCH message='Send START command to start a run before sending commands'
 568.75  $JS.API.CONSUMER.DELETE.COMMAND_IMMEDIATE.cmd_immed_proto-test (reply → _INBOX)
         ""
 568.75  _INBOX.…
         consumer_delete_response
 568.75  $JS.API.CONSUMER.INFO.COMMAND_IMMEDIATE.cmd_immed_proto-test (reply → _INBOX)
         ""
 568.75  _INBOX.…
         consumer_info_response ERROR 10014 consumer not found
 568.75  $JS.API.CONSUMER.DURABLE.CREATE.COMMAND_IMMEDIATE.cmd_immed_proto-test (reply → _INBOX)
         config={"durable_name": "cmd_immed_proto-test", "deliver_policy": "all", "ack_policy": "explicit", "filter_subject": "puda.proto-test.cmd.immediate", "replay_policy": "instant", "flow_control": false, "deliver_subject": "_INBOX
 568.75  _INBOX.…
         consumer_create_response
 568.75  $KV.MACHINE_COMMANDS.proto-test (reply → _INBOX)
         {"commands": "cancel(self) -> 'dict'\n    Acknowledge cancel. Run teardown is handled by the edge client.\n\necho(self, message: 'str' = '') -> 'dict'\n    Echo
 568.75  puda.proto-test.cmd.immediate → ack: $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         command `start` run_id='88888888-2222-4333-8444-555555555555' step=0
 568.75  $JS.ACK.COMMAND_IMMEDIATE.cmd_immed_proto-test (delivery #1)
         (empty body = +ACK)
 568.75  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='idle' run_id='88888888-2222-4333-8444-555555555555'
 568.75  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='idle' run_id=None
 568.75  puda.proto-test.cmd.response.immediate (reply → _INBOX)
         response `start` run_id='88888888-2222-4333-8444-555555555555' step=0 → **success**
```
