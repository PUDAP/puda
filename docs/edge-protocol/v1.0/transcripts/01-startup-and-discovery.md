# Startup, discovery and state

Edge connect sequence (streams pre-provisioned), broadcast and direct ping, state read.

Captured from Python SDK 0.0.23 (`test-edge`, 2 s simulated command delay) and CLI 0.1.6-rc2
against nats-server 2.15.3 provisioned with `infra/nats/jetstream/setup_streams.sh`.
Heartbeat/health/position telemetry, JetStream advisories, the CLI's ephemeral response consumers, pull-request polling (`CONSUMER.MSG.NEXT`
and its `408` timeouts) and the CLI's own catalog reads are omitted. Times are seconds since capture start.
`→ ack:` lines are the reply subject a delivered message carries.

## `startup`

```text
   0.00  $JS.API.STREAM.CREATE.KV_MACHINE_STATE (reply → _INBOX)
         {"name": "KV_MACHINE_STATE", "subjects": ["$KV.MACHINE_STATE.>"], "max_consumers": -1, "max_msgs": -1, "discard": "new", "discard_new_per_subject": false, "max_
   0.00  _INBOX.…
         stream_create_response ERROR 10058 stream name already in use with a different configuration
   0.00  $JS.API.STREAM.CREATE.KV_MACHINE_COMMANDS (reply → _INBOX)
         {"name": "KV_MACHINE_COMMANDS", "subjects": ["$KV.MACHINE_COMMANDS.>"], "max_consumers": -1, "max_msgs": -1, "discard": "new", "discard_new_per_subject": false,
   0.00  _INBOX.…
         stream_create_response ERROR 10058 stream name already in use with a different configuration
   0.01  $JS.API.CONSUMER.INFO.COMMAND_QUEUE.cmd_queue_proto-test (reply → _INBOX)
         ""
   0.01  _INBOX.…
         consumer_info_response ERROR 10014 consumer not found
   0.01  $JS.API.CONSUMER.INFO.COMMAND_QUEUE.cmd_queue_proto-test (reply → _INBOX)
         ""
   0.01  _INBOX.…
         consumer_info_response ERROR 10014 consumer not found
   0.01  $JS.API.CONSUMER.CREATE.COMMAND_QUEUE.cmd_queue_proto-test.puda.proto-test.cmd.queue (reply → _INBOX)
         config={"name": "cmd_queue_proto-test", "durable_name": "cmd_queue_proto-test", "deliver_policy": "all", "ack_policy": "explicit", "filter_subject": "puda.proto-test.cmd.queue", "replay_policy": "instant", "ack_wait": 0, "idle_
   0.01  _INBOX.…
         consumer_create_response
   0.01  $JS.API.CONSUMER.INFO.COMMAND_QUEUE.cmd_queue_proto-test (reply → _INBOX)
         ""
   0.01  _INBOX.…
         consumer_info_response
   0.01  $JS.API.CONSUMER.DELETE.COMMAND_IMMEDIATE.cmd_immed_proto-test (reply → _INBOX)
         ""
   0.01  _INBOX.…
         consumer_delete_response ERROR 10014 consumer not found
   0.01  $JS.API.CONSUMER.INFO.COMMAND_IMMEDIATE.cmd_immed_proto-test (reply → _INBOX)
         ""
   0.01  _INBOX.…
         consumer_info_response ERROR 10014 consumer not found
   0.01  $JS.API.CONSUMER.DURABLE.CREATE.COMMAND_IMMEDIATE.cmd_immed_proto-test (reply → _INBOX)
         config={"durable_name": "cmd_immed_proto-test", "deliver_policy": "all", "ack_policy": "explicit", "filter_subject": "puda.proto-test.cmd.immediate", "replay_policy": "instant", "flow_control": false, "deliver_subject": "_INBOX
   0.01  _INBOX.…
         consumer_create_response
   0.02  $KV.MACHINE_COMMANDS.proto-test (reply → _INBOX)
         {"commands": "cancel(self) -> 'dict'\n    Acknowledge cancel. Run teardown is handled by the edge client.\n\necho(self, message: 'str' = '') -> 'dict'\n    Echo
   0.02  $KV.MACHINE_STATE.proto-test (reply → _INBOX)
         state='idle' run_id=None
```

## `list`

```text
  26.58  puda.cmd.ping (reply → _INBOX)
         "ping"
  26.58  _INBOX.…
         pong {"status": "pong", "machine_id": "proto-test", "timestamp": "2026-11-23T13:24:44Z", "sdk_version": "0.0.23", "uptime_seconds": 26.582, "run_status": "
  27.59  _INBOX.…
         consumer_create_response
```

## `info`

```text
  28.75  puda.proto-test.cmd.ping (reply → _INBOX)
         "ping"
  28.75  _INBOX.…
         pong {"status": "pong", "machine_id": "proto-test", "timestamp": "2026-11-23T13:24:46Z", "sdk_version": "0.0.23", "uptime_seconds": 28.755, "run_status": "
  28.76  _INBOX.…
         consumer_create_response
```

## `state`

```text
  31.12  $JS.API.DIRECT.GET.KV_MACHINE_STATE.$KV.MACHINE_STATE.proto-test (reply → _INBOX)
         ""
  31.12  _INBOX.… [Nats-Stream: KV_MACHINE_STATE, Nats-Subject: $KV.MACHINE_STATE.proto-test, Nats-Sequence: 1]
         state='idle' run_id=None
```
