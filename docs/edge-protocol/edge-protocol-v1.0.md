# PUDA Edge Protocol 1.0

| | |
|---|---|
| Status | Release candidate. Shipped with the reference releases below; normative text changes only with a new protocol version (§2). |
| Protocol version | `1.0`, carried as `header.protocol_version` in every command and response and as `protocol_version` in every pong. E2E frames are format `0x01`. |
| Reference implementations | Python SDK `0.1.0rc1` (`libs/python-sdk`, on PyPI as `puda`; requires nats-py ≥ 2.17). CLI `0.2.0-rc1` (`apps/cli`, GitHub prerelease `v0.2.0-rc1`). Both built from `main` at `53bef76`. Broker `nats-server 2.15.3` (`infra/nats`), provisioned by `infra/nats/jetstream/setup_streams.sh`. |
| Evidence | Wire captures in [`v1.0/transcripts/`](v1.0/transcripts/). Payload examples in [`v1.0/examples/`](v1.0/examples/). Schemas in [`v1.0/schemas/`](v1.0/schemas/). E2E vectors in [`v1.0/vectors/`](v1.0/vectors/). Run [`v1.0/check.py`](v1.0/check.py) to validate them. |

This document specifies what a PUDA **edge** must do on the wire to be driven by the PUDA CLI, agents and loggers. An edge is the process that owns one machine. The spec is written so a second implementation, such as a C SDK on an ESP32, can interoperate without reading the Python source.

The key words MUST, MUST NOT, SHOULD, SHOULD NOT and MAY are used as in RFC 2119.

Behaviour is described in two ways:

- **Normative text** is the contract. A conforming edge MUST follow it.
- **Observed** notes record measurements of the Python reference. They are not requirements. Where an implementation deviates from the normative text, the normative text wins. §16 lists the deviations found in SDK 0.0.23 and the 0.1.0 fix for each.

---

## 1. Roles

| Role | Description | Reference |
|---|---|---|
| Edge | Owns one machine (`machine_id`). Consumes commands, publishes responses, state, catalog and telemetry. | `EdgeRunner` + `EdgeNatsClient` |
| Client | Sends commands and waits for responses. Examples: the CLI, agents, `CommandService`. | `apps/cli`, `puda.command_service` |
| Observer | Subscribes without sending. Examples: loggers, `puda machine watch`. Observers MUST NOT subscribe to `puda.<id>.cmd.immediate` (§8.3). | `services/logger` |
| Provisioner | Creates streams and KV buckets. | `infra/nats/jetstream/setup_streams.sh` |
| Broker | NATS with JetStream. | `nats:2.15.3` |

An edge serves exactly one `machine_id`. Several edges MAY share a host and a NATS connection pool, but each machine has its own subjects, consumers and KV keys.

## 2. Versioning

The protocol version is `MAJOR.MINOR`, and it is the only compatibility signal. Package versions (`sdk_version`, the CLI version) are informational: implementations are versioned independently, and a C SDK and the Python SDK that both speak `1.x` are interchangeable.

- Every command and response carries `header.protocol_version`. Clients MUST send `"1.0"` under this spec. An edge MUST refuse a command whose `header.protocol_version` is missing, is not two dot-separated decimal numbers, or has a major other than its own: it is an invalid envelope (§8.4), answered `EXECUTION_ERROR` "Invalid command envelope: header.protocol_version: …" and never executed ([example](v1.0/examples/response-queue-protocol-mismatch.json)). A response echoes the request's value.
- Every pong carries `protocol_version`, the version the edge speaks. Clients judge an edge by its major: the CLI supports `1.x`, reports any other value (or none) as unsupported in `puda machine list`/`info` and `puda healthcheck`, and does not block on it.
- A minor version only adds: new optional fields, verbs or codes. So that any `1.x` edge works with any `1.x` client:
  - Receivers MUST ignore unknown JSON fields.
  - An edge MUST echo unknown envelope fields unchanged in its response (§8.1).
  - Receivers MUST accept a response `code` they do not know and treat the response as an error with that code (§8.6).
- Changing a subject, consumer name, required field, ack rule, reply rule or the E2E frame layout requires a new major version, which is a breaking release of every client and edge implementation. There is no negotiation and no support for older majors.
- Commands carry no per-command version.

## 3. Machine identity

- `machine_id` MUST match `^[A-Za-z0-9_-]+$`. It SHOULD be lowercase and hyphenated, for example `opentron`, `esp32-pump-1`.
- `machine_id` is used verbatim as a subject token, a KV key and part of a durable consumer name. The Python edge and the CLI ping path replace `.` with `-` in subjects. The CLI command path and KV keys do not. An ID containing `.` therefore resolves to different subjects on different paths, which is why `.` is forbidden.
- The machine description advertised in the pong is a single line, typically the first paragraph of the driver class docstring.

## 4. Transport

### 4.1 NATS connection

- An edge MUST speak the NATS client protocol with **headers** (`HPUB`/`HMSG`). Headers carry JetStream status codes (`408`, `404`, `409`), `KV-Operation` markers and `Nats-Subject` on KV reads.
- Server URLs are either all `nats://` or all `tls://`. Mixing them is a configuration error.
- With `tls://`, the edge MUST verify the server certificate against an explicitly configured CA file. The Python edge takes it as `EdgeNatsClient(ca_file=…)` and the E2E key file (§13.1) as `e2e_key_file=…`; the SDK reads no environment variables for either, so deployments pass their own settings (the loggers and CLI use `PUDA_NATS_CA` and `PUDA_E2E_KEY_FILE`). Reference deployments use server-only TLS; client certificates are not required.
- Authentication: reference deployments run without broker authentication; access is controlled at the network layer. Edges SHOULD support token or user/password authentication for deployments that add it. NKEY and JWT support is OPTIONAL in 1.0.
- Reconnect: the edge MUST reconnect forever. The reference waits 2 s between attempts and uses a 10 s connect timeout. After a reconnect the edge MUST restore every subscription and consumer binding (§7) and republish its state (§10).

### 4.2 Message size

The broker allows 64 MB payloads. An edge MUST accept command messages of at least 16 KiB and MAY reject larger ones with `EXECUTION_ERROR`. The test edge's catalog value (§11) is about 13 KB, so an edge MUST also be able to publish its own catalog in one message.

### 4.3 Time

Every timestamp in this protocol is UTC ISO 8601. The reference format is `YYYY-MM-DDTHH:MM:SSZ` at second precision; receivers MUST also accept fractional seconds.

An edge MUST have a synchronised wall clock (for example SNTP on an ESP32) before it publishes state or responses. Until then it MAY publish only heartbeats.

## 5. Provisioning

Provisioning is the operator's job, not the edge's. `setup_streams.sh` applies the stream configs in `infra/nats/jetstream/streams/*.json` and creates the KV buckets below. It requires `REPLICAS` (1 for a single node, 3 for the three-node cluster) and sets it on every stream and bucket. Re-running it updates existing streams to the files and changes only the replica count of existing buckets.

| Name | Kind | Subjects / key | Retention and settings |
|---|---|---|---|
| `COMMAND_QUEUE` | Stream | `puda.*.cmd.queue` | `workqueue`, file storage, `discard: new`, `max_msgs_per_subject: 10`, `discard_new_per_subject: true` |
| `RESPONSE_QUEUE` | Stream | `puda.*.cmd.response.queue` | `interest`, file storage, `max_age` 24 h |
| `RESPONSE_IMMEDIATE` | Stream | `puda.*.cmd.response.immediate` | `interest`, file storage, `max_age` 24 h |
| `MACHINE_STATE` | KV | key `<machine_id>` | history 1 |
| `MACHINE_COMMANDS` | KV | key `<machine_id>` | history 1 |
| `E2E_KEYRING` | KV | key `current` | history 1 |
| `E2E_KEYFILES` | KV | `cli/<id>` | history 1; written by the CLI only |
| `LIVESTREAMS` | KV | — | history 1; not used by edges |

The broker config (`infra/nats/*/nats.conf`) sets `max_payload: 64MB` and JetStream limits of 4 GB memory and 10 GB file storage per server. No stream or consumer is defined for `puda.<id>.cmd.immediate` (§8.3).

`COMMAND_QUEUE` holds at most **10 commands per machine** (`max_msgs_per_subject: 10`), counting a delivered command not yet acked. With `discard_new_per_subject: true` the broker refuses an 11th publish with `503`, error code `10077`, "maximum messages per subject exceeded", stores nothing and deletes nothing. A client MUST treat this as "queue full" and MUST NOT retry it blindly; the CLI reports it as `queue full` naming the machine. Without `discard_new_per_subject` the broker would instead delete the machine's oldest message, possibly the running command, so provisioning MUST set it. Clients that wait for each response before sending the next command (the CLI and `CommandService` do) keep at most two messages per machine in the stream.

Rules:

- An edge MUST work against these pre-provisioned objects without creating or modifying any of them.
- An edge MUST NOT update or delete a stream or bucket (`STREAM.UPDATE`, `STREAM.DELETE`). An update replaces the whole config, so it can overwrite provisioned settings such as replicas or `max_msgs_per_subject`. If an existing object does not match this table, the edge MUST leave it unchanged and SHOULD log the mismatch.
- An edge MAY call `STREAM.INFO` to check that an object exists, and MAY create one that is **missing** (`STREAM.CREATE`) with the settings in the table, logging a warning that the broker is unprovisioned. This keeps development brokers usable without `setup_streams.sh`. A Core edge (§15) SHOULD instead log the problem and retry.
- Writing a KV value needs no API call. Publishing to `$KV.<bucket>.<key>` through JetStream is enough (Appendix A).

The reference calls `STREAM.INFO` on the three command and response streams and opens the `MACHINE_STATE` and `MACHINE_COMMANDS` buckets on every connect; it creates only what is missing.

## 6. Subject map

`<id>` is the `machine_id`. Payloads are JSON (UTF-8). When E2E is enabled every payload is sealed, including the literal `ping` (§13).

| Subject | Transport | Direction | Payload | Required (Core) |
|---|---|---|---|---|
| `puda.<id>.cmd.queue` | JetStream `COMMAND_QUEUE` | client → edge | [NATSMessage](v1.0/schemas/nats-message.schema.json) command | MUST |
| `puda.<id>.cmd.immediate` | core request/reply | client → edge, reply edge → client | NATSMessage command → NATSMessage response on the inbox | MUST |
| `puda.<id>.cmd.response.queue` | JetStream `RESPONSE_QUEUE` | edge → clients | NATSMessage response | MUST |
| `puda.<id>.cmd.response.immediate` | JetStream `RESPONSE_IMMEDIATE` | edge → observers | copy of each immediate reply, for history | MUST |
| `puda.<id>.cmd.ping` | core request/reply | client → edge | literal `ping` → [pong](v1.0/schemas/pong.schema.json) | MUST |
| `puda.cmd.ping` | core request/reply, fleet broadcast | client → all edges | literal `ping` → pong | MUST |
| `$KV.MACHINE_STATE.<id>` | JetStream KV put | edge → | [state](v1.0/schemas/machine-state.schema.json) | MUST |
| `$KV.MACHINE_COMMANDS.<id>` | JetStream KV put | edge → | [catalog](v1.0/schemas/machine-commands.schema.json) | MUST |
| `puda.<id>.tlm.heartbeat` | core publish | edge → | `{"timestamp"}` | MUST |
| `puda.<id>.tlm.health` | core publish | edge → | `{"timestamp","data":{cpu,mem,temp}}` | MAY |
| `puda.<id>.tlm.stream.<name>` | core publish | edge → | `{"timestamp","data":{…}}` | MAY |
| `puda.<id>.evt.log` | core publish | edge → | `{"timestamp","log_level","msg",…}` | SHOULD |
| `puda.<id>.evt.alert` | core publish | edge → | `{"timestamp","type","severity",…}` | MAY |
| `puda.<id>.evt.media` | core publish | edge → | `{"timestamp","media_url","media_type",…}` | MAY |
| `puda.<id>.update` | core publish | client → edge | NATSMessage command `update` | SHOULD |
| `puda.<id>.update.response` | core publish | edge → client | NATSMessage response | SHOULD, with `update` |
| `$KV.E2E_KEYRING.current` | KV read/watch | → edge | [keyring record](v1.0/schemas/keyring-record.schema.json), sealed | MUST when E2E is on |

## 7. Startup and reconnect sequence

On every successful connect, and after every reconnect, an edge MUST:

1. If E2E is configured, read `E2E_KEYRING/current` and adopt it (§13.5) **before** consuming commands.
2. Subscribe to `puda.<id>.cmd.ping` and `puda.cmd.ping`.
3. Subscribe to `puda.<id>.cmd.immediate` (§8.3) and bind the queue consumer (§8.2).
4. Subscribe to `puda.<id>.update` if it supports updates.
5. Put the catalog to `MACHINE_COMMANDS/<id>`.
6. Put state `idle` with the active `run_id` (normally `null` after a restart) to `MACHINE_STATE/<id>`, or `estopped` if the estop latch is set (§9.6).
7. Start heartbeats (§12).

An edge MUST hold exactly one connection per machine. After a disconnect it MUST either reconnect that connection or close it before opening another, so it never answers a ping or an immediate command twice. The active run survives a broker restart, because it lives in edge memory (§9.1). See [transcript 01](v1.0/transcripts/01-startup-and-discovery.md) and [transcript 05](v1.0/transcripts/05-lifecycle-and-recovery.md).

## 8. Commands

### 8.1 Envelope

Commands and responses share one envelope ([schema](v1.0/schemas/nats-message.schema.json), [example](v1.0/examples/command-queue.json)):

```json
{
  "header": {
    "protocol_version": "1.0",
    "message_type": "command",
    "user_id": "00000000-0000-4000-8000-000000000001",
    "username": "puda",
    "machine_id": "proto-test",
    "run_id": "22222222-2222-4333-8444-555555555555",
    "timestamp": "2026-11-23T13:25:24Z"
  },
  "command": {
    "name": "echo",
    "params": {"message": "hi"},
    "step_number": 1,
    "machine_id": "proto-test"
  }
}
```

- `header.protocol_version` is required (§2).
- `command.kwargs` is optional; the CLI omits it. Before dispatch the edge MUST merge `kwargs` over `params`, with `kwargs` winning on conflict ([transcript 03, `kwargs_merge`](v1.0/transcripts/03-errors.md)).
- `header.run_id` may be a UUID string, `null`, or the empty string. The CLI sends `""` for `pause`, `resume` and `reset` (observed in every capture of those commands).
- `command.params` of an immediate verb carries its options. The only one defined is `complete`'s `abort` (§9.3).
- The edge MUST treat `header`, `command` and `response` as opaque beyond the fields defined here, and MUST echo them back unchanged (§8.4).

### 8.2 Queue consumer

| Item | Value |
|---|---|
| Stream | `COMMAND_QUEUE` |
| Durable name | `cmd_queue_<id>` |
| Kind | Pull |
| Config | `{"durable_name":"cmd_queue_<id>","filter_subject":"puda.<id>.cmd.queue","ack_policy":"explicit","deliver_policy":"all"}`. Server defaults apply: `ack_wait` 30 s, `max_deliver` −1. |

- If the durable exists with a different `filter_subject`, `ack_policy` or `deliver_policy`, the edge MUST delete and recreate it. Otherwise it MUST reuse it, so a backlog survives restarts.
- The edge MUST process queued commands **one at a time**, in delivery order. It MUST NOT request the next message until the current one is acked or terminated, and MUST NOT request one while paused (§9.4). The reference uses `{"batch":1,"expires":999900000}` in a loop. An embedded edge MAY use a longer `expires`, for example 30 s.
- While a queued command runs longer than `ack_wait`, the edge MUST send `+WPI` (in progress) at an interval shorter than `ack_wait`. The reference sends it every 25 s ([transcript 02, `run2_slow`](v1.0/transcripts/02-run-lifecycle.md)).
- Acknowledgements go to the delivered message's reply subject `$JS.ACK.COMMAND_QUEUE.cmd_queue_<id>.…`. An empty body and `+ACK` are equivalent. The reference sends an empty body for ack, `+TERM` for terminate, and `-NAK` (confirmed, §9.4) only for a message delivered at the instant of pausing.

### 8.3 Immediate requests

Immediate commands (`start`, `complete`, `pause`, `resume`, `reset`, `estop`) are **core NATS request/reply**. There is no stream, consumer or ack.

- The client publishes the command to `puda.<id>.cmd.immediate` with a reply subject (an inbox). It MUST publish with headers enabled, so that the broker answers a `503` no-responders status when no edge is subscribed.
- The edge subscribes to `puda.<id>.cmd.immediate` (core, no queue group) and MUST answer every request that has a reply subject **exactly once**, on that reply subject, including malformed ones (§8.4).
- Nothing is stored. A command sent while the edge is offline is never delivered: the client gets no responders at once, and the command cannot act later. This is why immediate commands are not JetStream: a stored `start`, `reset` or `estop` replayed minutes later is a hazard (D-5).
- **Only the edge subscribes to this subject.** Any other subscriber (a logger, a tap, a stream) creates interest, so the broker no longer answers no responders for an offline machine and clients wait for their timeout instead. A JetStream stream bound to the subject also answers every request with a PubAck. Observers record immediate commands from `RESPONSE_IMMEDIATE` (§8.4), which carries the full header and command.
- Immediate commands MUST be processed **concurrently** with a running queued command. `pause`, `complete` with `abort`, and `estop` exist to act while a queued command is running.
- `estop` MUST NOT wait behind another immediate command, such as a slow driver `pause` or `reset` hook. Other verbs SHOULD be applied in arrival order. The reference handles each request in its own task: `estop` runs at once, the rest take turns through a fair lock.
- Client side: a no-responders status means the machine is offline and nothing happened. A timeout without a reply means the outcome is unknown; the command may have run. Every immediate verb is safe to retry (§9.3), so a client MAY resend after a timeout.
- Clients SHOULD NOT buffer publishes while reconnecting (the CLI sets `ReconnectBufSize(-1)`), so a command fails at once instead of being sent late.

### 8.4 Responses

For every command it acts on, the edge MUST produce exactly one response:

- **Queued command:** published through JetStream to `puda.<id>.cmd.response.queue`, and stored (PubAck) **before** the command message is acked or terminated. If the broker is unreachable the edge MUST keep retrying, sending `+WPI` meanwhile, so a result is never lost. It SHOULD set `Nats-Msg-Id: <machine_id>:<stream sequence>` so that re-sending the same result is a duplicate JetStream drops.
- **Immediate command:** sent as the reply on the request's reply subject (sealed with that inbox as AAD, §13.3), then published as a copy to `puda.<id>.cmd.response.immediate` for observers. The reply comes first so that recording never delays it. Clients wait for the reply, not for the copy.

The response is the received message with these changes:

- `header.message_type` set to `"response"`.
- `header.timestamp` set to the response time.
- `response` added:

```json
"response": {
  "status": "success",
  "completed_at": "2026-11-23T13:25:26Z",
  "code": null,
  "message": null,
  "data": {"message": "hi"}
}
```

Rules:

- `header.run_id`, `header.machine_id` and `command.step_number` MUST be byte-identical to the request. The CLI correlates responses on the tuple `(run_id, step_number, machine_id)`, and an empty-string `run_id` is a distinct key.
- On error, `status` is `"error"`, and `code` (§8.6) and `message` are set.
- `data` is a JSON object or `null`. A handler result that is not an object MUST be wrapped as `{"result": <value>}`. A handler returning `false` is a **success** with `{"result": false}` ([example](v1.0/examples/response-queue-bool-false.json)).
- Python adds `"kwargs": {}` to the echoed `command` when it was absent. Edges MAY do the same.
- Storing the result before the ack means an edge that dies in between leaves the message unacked, so JetStream redelivers it. A redelivery MUST NOT run the command again (§9.2 rows 0a and 0b).
- **Graceful shutdown** is the only case where the edge may give up storing a result: it answers a command still running `COMMAND_CANCELLED` (§9.2 row 10b) and stops retrying after a bounded time (the reference waits 5 s). If the result was not stored, the message is still unacked, so after restart it is redelivered and answered under row 0b instead.

**Malformed commands.** A payload that opens (§13.4) but is not a valid envelope:

- MUST NOT act, and MUST NOT be redelivered: a queued message is terminated. An immediate request is not stored, so there is nothing to ack.
- MUST NOT change the run or the machine state.
- MUST be answered `EXECUTION_ERROR` "Invalid command envelope: <field>: <problem>" when it is **correlatable**: a JSON object with a `header` object whose `machine_id` is a string and `run_id` a string or `null`, and a `command` object whose `step_number` is an integer. The response echoes the received object as in the rules above ([example](v1.0/examples/response-queue-malformed.json)).
- Otherwise a queued message is dropped and logged; no client can match a response to it. An immediate request is still answered on its reply subject, because the reply needs no correlation: the body is `{"response": {…EXECUTION_ERROR…}}` without `header` or `command`. It is not recorded on `RESPONSE_IMMEDIATE`. `JSON_DECODE_ERROR` is not emitted.
- A missing or unsupported `header.protocol_version` (§2) is an invalid envelope like any other.

### 8.5 Driver command dispatch

- Only commands listed in the catalog (§11) are dispatchable. Names starting with `_` MUST be rejected.
- An unknown name gets `UNKNOWN_COMMAND` with the message `Unknown or restricted command: <name>`.
- Handler failure MUST produce `status: error`, `code: EXECUTION_ERROR`, and a `message` that describes the failure (targets, hardware response). Never report failure with a "successful" `false`.
- Lifecycle hook names (§11.2) sent through the queue MUST be rejected with `EXECUTION_ERROR`, matched case-insensitively, in place of dispatch (§9.2 row 7, after the run checks). The reference messages are `<verb> is an immediate command; use puda machine <verb> <machine_id>` for `pause`, `resume`, `reset` and `estop`, `abort is a lifecycle hook; use puda machine complete --abort <machine_id>`, and `shutdown is a lifecycle hook and is not remotely callable`. Sent as an immediate command, `abort` and `shutdown` are unknown verbs (`UNKNOWN_COMMAND`).
- A second queued command arriving while one runs cannot happen given the serial rule in §8.2. If an implementation allows it anyway, it MUST reply `EXECUTION_LOCKED`.

### 8.6 Response codes

| Code | Meaning |
|---|---|
| `UNKNOWN_COMMAND` | Name not in the catalog, or an unknown immediate verb. |
| `EXECUTION_ERROR` | Handler raised; envelope problem (missing `run_id` on queue, missing command); estop via queue. |
| `EXECUTION_LOCKED` | Another queued command holds the execution lock, or `complete` without `abort` while a command of the run is running (§9.3). |
| `COMMAND_CANCELLED` | The running queued command was stopped by `estop` or `complete` with `abort`, or the edge shut down while it ran. |
| `RUN_ID_MISMATCH` | No active run, a different active run, `complete` for an inactive run, or `start` while another run is active. |
| `MISSING_RUN_ID` | `start` or `complete` without a `run_id`. |
| `MACHINE_PAUSED` | Reserved. A paused edge holds queued commands instead (§9.4). |
| `MACHINE_ESTOPPED` | Queued command, `start` or `resume` while the estop latch is set. |
| `ESTOP_NOT_SUPPORTED` | `estop` on a machine without a hardware stop. The latch is still set. |
| `JSON_DECODE_ERROR` | Reserved. Undecodable payloads cannot be correlated, so they get no response (§8.4). |
| `PAUSE_ERROR`, `RESUME_ERROR`, `CANCEL_ERROR`, `NO_EXECUTION` | Reserved. Not emitted by the reference. |

A later `1.x` minor may add codes (upper case, digits and `_`). A receiver MUST accept a code it does not know, and treat it as `status: "error"` with that code; it MUST NOT reject the envelope.

## 9. Run model and command semantics

### 9.1 Runs

- An edge holds at most one active `run_id`. It lives in memory only; after an edge restart there is no active run.
- Queued commands MUST carry the active `run_id`. `start` sets it, and `complete`, `reset` and `estop` clear it.
- **An error from running a queued command ends the active run**: rows 0b and 7–10 of §9.2. The edge clears the run and terminates the message, and clients must send a new `start` to continue ([transcript 03, `run2_unknown` → `run2_fail`](v1.0/transcripts/03-errors.md)). Rejections before anything runs (rows 1–6) leave the run unchanged.

### 9.2 Queued command decision table

The edge MUST evaluate these checks in the order of the table: 0a, 1, 0b, 2, 3, … A malformed message (row 1) never ran, so it is rejected before row 0b. Row 0b comes before the estop latch (row 2), so a command that may already have run is reported as outcome unknown rather than as refused. The edge MUST remember the results of at least its last queued command by stream sequence; the reference keeps 64. Rows 0a and 0b make every queued command run at most once even though results are stored before the ack (§8.4): a redelivery that already has a result is answered again, and one without (the edge restarted mid-command, so the hardware may have acted) is reported, not run. Clients take the first response per `(run_id, step_number, machine_id)`.

| # | Condition | Ack | Response | Run | State |
|---|---|---|---|---|---|
| 0a | Redelivered, and this edge has the result of that stream sequence | as before | the same result again (same `Nats-Msg-Id`) | — | — |
| 1 | Payload unreadable or not a valid envelope | `+TERM` | `EXECUTION_ERROR` if correlatable (§8.4), else none | — | — |
| 0b | Redelivered (delivery count > 1: the `<delivered>` token of the reply subject `$JS.ACK.<stream>.<consumer>.<delivered>.…`) with no result on record and not NAKed by this edge on pause | `+TERM` | `EXECUTION_ERROR` "Redelivered without a result: the edge restarted while handling this command. Outcome unknown; it was not run again" | cleared | — |
| 2 | Estop latch set | `+TERM` | `MACHINE_ESTOPPED` "Machine emergency stopped; send reset before queuing commands" | — | — |
| 3 | Paused | `-NAK`, confirmed (§9.4) | none; redelivered after resume | — | — |
| 4 | `run_id` is `null` | `+ACK` | `EXECUTION_ERROR` "Command requires run_id" | — | — |
| 5 | No active run | `+ACK` | `RUN_ID_MISMATCH` "Send START command to start a run before sending commands" | — | — |
| 6 | `run_id` ≠ active run | `+ACK` | `RUN_ID_MISMATCH` "Run ID mismatch: expected active run, got <run_id>" | — | — |
| 7 | Command is a lifecycle hook (§11.2) | `+TERM` | `EXECUTION_ERROR` naming the CLI action (§8.5) | cleared | — |
| 8 | Name not dispatchable | `+TERM` | `UNKNOWN_COMMAND` | cleared | `busy` → `error` |
| 9 | Handler raises | `+TERM` | `EXECUTION_ERROR` | cleared | `busy` → `error` |
| 10 | Stopped by `estop` or `complete` with `abort`, answered when the driver call returns | `+TERM` | `COMMAND_CANCELLED` "Stopped by estop" / "Stopped by complete --abort" (`data` is the handler's result) | cleared | `estopped`, or `idle` + `null` after abort |
| 10b | Edge shut down gracefully while the command ran | `+ACK` | `COMMAND_CANCELLED` "Command cancelled", best effort (§8.4) | cleared | `offline` |
| 11 | Success | `+ACK` | `success`, `data` | kept | `busy` → `idle` |

Row 3 only applies to a message delivered at the instant the edge paused; otherwise a paused edge does not pull (§9.4). When the message is redelivered, rows 2 and 3 apply again, so after an estop it is terminated with `MACHINE_ESTOPPED`.

### 9.3 Immediate commands

Immediate verbs are matched case-insensitively. Any other name is answered `UNKNOWN_COMMAND` "Unknown immediate command: <name>"; driver commands are only reachable through the queue.

Every verb is safe to repeat, so a client that timed out (§8.3) can resend it: `start` of the run that is already active answers `success` with `data: {"already_started": true}` ([example](v1.0/examples/response-immediate-start-repeat.json)); `complete` of a run that already ended answers `already_completed` (§9.8); `pause`, `resume`, `reset` and `estop` are idempotent.

| Verb | Precondition | Effect | Response | State |
|---|---|---|---|---|
| `start` | `run_id` set; no estop latch; no other active run | Run becomes active | `success` (`already_started` if it was) / `MISSING_RUN_ID` / `MACHINE_ESTOPPED` / `RUN_ID_MISMATCH` "cannot start, <active> is currently running" | `idle` + `run_id` |
| `complete` | `run_id` = active run, and no command of the run running unless `params.abort` | Run cleared; see §9.8 | `success` / `EXECUTION_LOCKED` / `MISSING_RUN_ID` / `RUN_ID_MISMATCH` "Run <id> not active" | `idle`, `run_id: null` |
| `pause` | — | Pause latch set; driver `pause` hook called if implemented (§11.2) | Driver result, or `success` if absent | `paused` + active run (`estopped` while latched) |
| `resume` | No estop latch | Pause latch cleared; driver `resume` called if present | Driver result, or `success` if absent / `MACHINE_ESTOPPED` | `idle` + active run, or `busy` if a command is running |
| `reset` | — | Run cleared; driver `reset` called if present. On success the estop latch is cleared. | Driver result, or `success` if absent | `idle` on success; on failure `error`, or `estopped` if the latch is still set |
| `estop` | — | §9.6 | — | `estopped` |

Notes:

- "Driver result, or `success` if absent" is the normative rule. A machine without a `pause` method still pauses.
- There is no `cancel` verb. It is answered `UNKNOWN_COMMAND` "Unknown immediate command: cancel" like any other unknown name ([example](v1.0/examples/response-immediate-cancel-unknown.json)). A driver method named `cancel` is dispatched only through the queue.
- `pause` and `resume` do not change the run. The `run_id` they put in state is the **active** run (or `null`), never `header.run_id`.

### 9.4 Pause

Pause **holds the queue**; resume continues it in order.

- A queued command that is already running continues and is answered normally.
- While paused the edge MUST NOT pull from `COMMAND_QUEUE`. Commands published meanwhile stay in the stream, unanswered.
- A message already delivered when the pause took effect MUST be returned with `-NAK` and not answered. The edge MUST wait for the server to confirm the NAK before its next pull (send `-NAK` as a request to the message's reply subject; the server replies with an empty message), so the message is back at the head of the redelivery queue and runs first on resume. A fire-and-forget NAK can reach the server after the next pull, which then delivers a newer command first.
- `resume` restarts pulling. Held and backlogged commands then go through §9.2 in delivery order; commands of a run that ended meanwhile get `RUN_ID_MISMATCH`.
- `estop` while paused releases the hold: the backlog, including a NAKed message, is pulled and terminated with `MACHINE_ESTOPPED` (§9.6). A later `reset` leaves the pause latch set.
- Pause does not affect immediate commands.
- Clients wait for queued responses without a timeout, so a paused command answered later is not an error for them.

### 9.5 Busy status

`run_status` in the pong is `busy` while a queued command executes and `idle` otherwise. It is not persisted.

### 9.6 Emergency stop

On `estop` the edge MUST, in this order:

1. Set the **estop latch** before anything else, so no queued command can start. The edge MUST check the latch, and whether the running command was marked stopped (step 3, §9.8), immediately before it hands a queued command to the driver, with nothing that can yield in between (no I/O, no `await`). A check made earlier, for example before putting `busy`, misses an estop that arrives in the meantime. A command stopped this way never reaches the driver; it is answered as in step 3, with `data: null`.
2. Issue the hardware stop without waiting behind the running queued command or any other immediate command (§8.3). The reference uses a dedicated thread pool that nothing else uses.
3. Mark the running queued command stopped. It is answered `COMMAND_CANCELLED` and its message terminated **when its driver call returns**; the edge MUST NOT start another queued command before then, so a hardware call is never overlapped. The stop in step 2 is what makes it return.
4. Clear the run, put state `estopped`, and publish `evt.log` at level `CRITICAL`.
5. Respond:
   - `success` with the driver's data, if the stop succeeded.
   - `EXECUTION_ERROR` "Driver estop failed: …", if it raised.
   - `ESTOP_NOT_SUPPORTED`, if the machine has no hardware stop. The latch is still set.

While latched:

- Queued commands → `+TERM`, `MACHINE_ESTOPPED`.
- `start` and `resume` → `MACHINE_ESTOPPED`.
- `pause` and `complete` are processed normally.
- Every state publish reports `estopped`, except `offline` at shutdown.

Only a successful `reset` clears the latch ([transcript 04, `estop_flow`](v1.0/transcripts/04-pause-cancel-estop.md)).

On hardware with a physical e-stop input, the edge SHOULD also enter this latched state locally and publish `estopped`.

### 9.7 Backlog

`COMMAND_QUEUE` is a work-queue stream, so queued commands published while an edge is offline wait for it. After a restart there is no active run, so they are evaluated normally and get `RUN_ID_MISMATCH` (§9.2).

Immediate commands have no backlog: they are request/reply (§8.3), so one sent while the edge is offline fails at once with no responders and never reaches it. An edge therefore never sees a stale `start`, `estop` or `reset`, and needs no age check or binding order.

### 9.8 Completing and aborting a run

`complete` is designed for clients, such as agents, that may act on a stale view of the machine: by default it never stops work, it explains a refusal, and repeating it is safe.

1. **Already ended.** If `run_id` is not active but was active recently on this edge (completed, cleared by an error, `reset` or `estop`), respond `success` with `data: {"already_completed": true}` and change nothing ([example](v1.0/examples/response-immediate-complete-repeat.json)). The edge MUST remember at least the last ended run and SHOULD remember more; the reference keeps the last 64 since it started. Otherwise respond `RUN_ID_MISMATCH`.
2. **Refusal.** If a queued command of the run is running and `params.abort` is not `true`, respond `EXECUTION_LOCKED` with `data.running` = `{"name", "step_number", "elapsed_s"}` and `data.queued` = the number of queued commands not yet answered behind it (`null` if unknown). The run stays active ([example](v1.0/examples/response-immediate-complete-locked.json)).
3. **Abort.** With `params.abort: true` the edge MUST, without waiting for the running command:
   1. Count `queued` before stopping anything.
   2. Mark the running command stopped, and start the driver's `abort` hook if implemented (§11.2) on its own thread, without awaiting it. A hook that raises is logged and published as `evt.log` at level `ERROR`.
   3. Clear the run, put `busy` + `null` while the stopped command is still executing (`idle` + `null` otherwise), publish `evt.log` at level `WARNING`, and respond `success` with `data` = `{"aborted": {name, step_number, elapsed_s} | null, "driver_abort": bool, "queued": int | null}` ([example](v1.0/examples/response-immediate-complete-abort.json)). `driver_abort` means the hook was started.
   4. When the running command's driver call returns, answer it `COMMAND_CANCELLED` (§9.2 row 10, [example](v1.0/examples/response-queue-aborted.json)), terminate its message and put `idle` + `null`. The next queued command MUST NOT start before then. A command that ignores `abort` therefore keeps the machine `busy` until it finishes; `estop` (§9.6) is the stronger stop.
4. **Plain completion.** Otherwise clear the run, put `idle` + `null` and respond `success`. `data` is `null`, or the abort object of step 3 when `abort` was set and nothing was running.

Commands queued behind the run are not removed. They are evaluated when pulled and get `RUN_ID_MISMATCH`.

`abort` is a soft stop for ending a run early. It is not a safety function and does not latch; hazards use `estop` (§9.6). A client interrupted while it waits for queued responses (the CLI on SIGINT or SIGTERM) SHOULD send `complete` with `abort` to every machine it started, because nothing else will observe the commands still running.

## 10. Machine state (`MACHINE_STATE`)

The value is published to KV `MACHINE_STATE`, key `<id>` ([schema](v1.0/schemas/machine-state.schema.json), [example](v1.0/examples/machine-state.json)):

```json
{"timestamp": "2026-11-23T13:25:24Z", "state": "busy", "run_id": "22222222-…", "protocol_version": "1.0", "homed": false}
```

- `state` is one of `idle`, `busy`, `paused`, `error`, `estopped`, `offline`.
- `protocol_version` is the version the writing edge speaks (§2). The value outlives the edge that wrote it, so readers use it to tell which protocol produced it. Edges SHOULD include it; readers MUST NOT require it, because values written before it was added have none.
- Machine-specific fields MAY be merged at the top level, as `homed` is above. They MUST NOT reuse `timestamp`, `state`, `run_id` or `protocol_version`.
- The edge MUST put state at each of these points:
  - startup: `idle`;
  - queued command start: `busy` + run;
  - queued command finish: `idle` + run, or `error` + run;
  - `start`: `idle` + run;
  - `complete`: `idle` + `null`;
  - `pause`: `paused` + active run;
  - `resume`: `idle` + active run, or `busy` + run while a command is running;
  - `reset`: `idle` or `error`;
  - `estop`: `estopped`;
  - graceful shutdown: `offline`.
- The value is overwritten (history 1). Clients read it with `DIRECT.GET`.
- After an E2E key switch the edge MUST re-put its last state, sealed with the new key.
- `offline` is only published on graceful shutdown. A crashed edge leaves its last state behind, so clients MUST treat ping as the liveness signal, not state.

## 11. Command catalog (`MACHINE_COMMANDS`)

### 11.1 Value

The catalog is put once per connect to KV `MACHINE_COMMANDS`, key `<id>` ([schema](v1.0/schemas/machine-commands.schema.json), [example](v1.0/examples/machine-commands.json)):

```json
{
  "commands": "move_to(self, x: 'float', y: 'float', z: 'float') -> 'dict'\n    Move to an absolute simulated position.\n…",
  "catalog": [
    {
      "name": "move_to",
      "signature": "(self, x: 'float', y: 'float', z: 'float') -> 'dict'",
      "doc": "Move to an absolute simulated position.\n\nArgs:\n    x: Target X\n…",
      "safety": {
        "summary": "Collision risk from unhomed motion or an occupied workspace.",
        "hazards": ["collision"],
        "requires": "Machine must just have been homed.",
        "forbidden_when": "Do not move if the workspace is occupied or human movement is detected.",
        "confirm": true
      }
    }
  ],
  "hooks": ["estop", "reset"],
  "protocol_version": "1.0"
}
```

- `commands` is human-readable text. Agents read it through `puda machine commands`.
- Each `catalog` entry MUST contain `name`, `signature`, `doc` and `safety`. `doc` and `safety` MAY be `null` but MUST be present; the CLI rejects entries missing them.
- A non-null `safety` MUST contain all five fields. `summary` is a non-empty string, `hazards` is an array, and `confirm` is a boolean.
- `confirm: true` makes the CLI ask the operator before sending the command. It is advisory metadata and does not change edge dispatch.
- `hooks` MUST list the lifecycle hooks the edge implements (§11.2), sorted, and MAY be empty. Clients treat a missing `hooks` field as unknown; SDK 0.0.23 and older do not send it.
- Lifecycle hooks MUST NOT appear in `catalog` or `commands`. `home` is an ordinary command.
- `protocol_version` follows the same rule as in state (§10): edges SHOULD include it, and readers MUST NOT require it.

### 11.2 Lifecycle hooks

A hook is machine behaviour that the edge runs as part of a protocol action, not a command a client calls directly. The set is fixed:

| Hook | Called by | Without it |
|---|---|---|
| `pause` | `pause`, after the queue is held (§9.4) | `success` |
| `resume` | `resume`, after the queue is released | `success` |
| `reset` | `reset`, after the run is cleared | `success`; the estop latch is still cleared |
| `estop` | `estop`, on its own thread (§9.6) | `ESTOP_NOT_SUPPORTED`; the latch is still set |
| `abort` | `complete` with `abort`, on its own thread, not awaited (§9.8) | `driver_abort: false`; the command runs until it returns |
| `shutdown` | Graceful edge shutdown, before `offline` is put | nothing |

Hooks are advertised only through `hooks`, are never dispatchable as driver commands (§8.5), and are not valid protocol steps; neither are `start` and `complete`, which the protocol runner sends itself. In the Python SDK hooks are plain methods found by name; decorating one with `@command` is a startup error (`LifecycleHookError`).

### 11.3 Signature grammar

`puda protocol validate` parses `signature` to type-check protocol steps, so a non-Python edge MUST emit a Python-style signature:

```text
"(" [ "self" "," ] param { "," param } ")" [ "->" annotation ]
param      = name [ ":" annotation ] [ "=" default ]
annotation = str | string | int | integer | float | number | bool | boolean | bytes
           | dict | Dict | object | list | List | array | Any | any | None | null
           | Optional[annotation] | Union[annotation, …] | annotation "|" annotation
           | dict[str, annotation] | list[annotation]
```

- Annotations may be quoted, for example `'float'`.
- A parameter with a default is optional.
- `**name` accepts extra keyword arguments.
- Positional-only parameters (`/`) are rejected, because dispatch is keyword-only.
- `bytes` travels as a JSON string.

An entry MAY add `"parameters": {"<name>": {"required": bool, "schema": {"kind": "int|float|str|bool|bytes|null|any|dict|list|union", "nullable": bool, "items": …, "values": …, "members": […]}}}`. These schemas take precedence over the signature's annotations. Python does not emit them, but the CLI accepts them, which makes them the natural choice for code-generated catalogs.

## 12. Telemetry and events

All of these use core NATS, fire-and-forget, and are sealed when E2E is enabled. The `timestamp` is added by the edge at publish time.

| Subject | Payload | Rate |
|---|---|---|
| `tlm.heartbeat` | `{"timestamp": "…"}` | MUST be every 5 s, ±1 s. `puda machine update` waits for a heartbeat to confirm a restart. |
| `tlm.health` | `{"timestamp","data":{"cpu":%,"mem":%,"temp":°C or null}}` | MAY; the reference publishes every 5 s. |
| `tlm.stream.<name>` | `{"timestamp","data":{…}}` | Per stream. `<name>` matches `^[A-Za-z0-9_-]+$`. Streams SHOULD be advertised in the pong `tlm_streams`. |
| `evt.log` | `{"timestamp","log_level","msg",…}` | On command completion (`INFO "Command <name> completed"`), estop (`CRITICAL`), update result. |
| `evt.alert` | `{"timestamp","type","severity",…}` | For example `update_restart`. |
| `evt.media` | `{"timestamp","media_url","media_type",…}` | After uploading media. |

Telemetry samples MUST use the `{timestamp, data}` wrapper.

> **Observed.** In the capture, heartbeat and health both had a median interval of 5.04 s, and `pos` (declared at 3 s) had 3.00 s.

## 13. Payload encryption (E2E)

Encryption is configured per deployment. When the edge has a lab key, **every** payload it sends or accepts on `puda.*` subjects and on the PUDA KV buckets MUST be sealed, and unsealed payloads MUST be rejected. Without a key, sealed payloads MUST be rejected.

### 13.1 Key file

The key file is plain text, mode 600:

```text
encrypt=<base64 32-byte AES-256 key>
previous=<base64 32-byte key>   # optional, at most one
```

- The key id is `kid = SHA-256(key)[0:4]`, written as 8 lowercase hex characters.
- An edge MUST persist an adopted ring (§13.5) so it survives restarts. On an ESP32 that means NVS or equivalent.
- If the edge cannot persist the ring, it MUST report `e2e_persist: false` in its pong.

### 13.2 Frame

```text
offset  size  field
0       1     magic 0xE2
1       1     version 0x01
2       4     kid of the sealing key
6       12    nonce (random, unique per key)
18      n+16  AES-256-GCM(ciphertext || 16-byte tag)
```

A payload is a frame if and only if it is at least 34 bytes long and begins `E2 01`.

### 13.3 Additional authenticated data (AAD)

| Payload | AAD |
|---|---|
| Message published on subject S | S, as UTF-8 |
| JetStream delivery of a message | the original publish subject, which is the delivered message's subject |
| Reply to a request (pong, immediate command reply) | the request's **reply** subject, i.e. the inbox |
| Ping request | `puda.<id>.cmd.ping` or `puda.cmd.ping` |
| KV value of bucket B, key K | `kv:B:K`, for example `kv:MACHINE_STATE:esp32-demo` |
| KV value read via `DIRECT.GET` or watch | `kv:B:K`, using the `Nats-Subject: $KV.B.K` header |

### 13.4 Receive rules

| Edge has key | Payload is a frame | Result |
|---|---|---|
| no | no | accept as plaintext |
| no | yes | reject ("peer has encryption enabled") |
| yes | no | reject ("plaintext payload rejected") |
| yes | yes, kid ∈ ring | open with that key; GCM failure → reject |
| yes | yes, kid ∉ ring | reject ("unknown key id") |

The ring holds the `encrypt` key plus at most one other key.

JetStream API requests, acks, PubAcks, KV headers and subjects are **not** encrypted. Subjects, machine IDs, consumer names and message timing remain visible to the broker.

### 13.5 Key rotation

The CLI drives rotation (`puda encryption rotate`). Edges follow the record in KV `E2E_KEYRING`, key `current`. The record's plaintext is `{"new_key","old_key","encrypt_kid"}`, and it is always sealed with the **old** key (AAD `kv:E2E_KEYRING:current`).

| Phase | Record | Edge ring after adopting | Pong `e2e_decrypt_kids` |
|---|---|---|---|
| 0, steady | absent | `{encrypt: K1}` | `[K1]` |
| 1, staged | `encrypt_kid = kid(K1)` | `{encrypt: K1, previous: K2}` | `[K1, K2]` |
| 2, switched | `encrypt_kid = kid(K2)` | `{encrypt: K2, previous: K1}` | `[K2, K1]` |
| 3, retired | key deleted (`KV-Operation: DEL`) | `{encrypt: K2}` | `[K2]` |

The edge MUST:

1. Read the record at connect, and observe later changes within 30 s, either through a KV watch (an ordered consumer, as the reference uses) or by polling `DIRECT.GET`.
2. On a record, open it with its ring, check that `encrypt_kid` equals the kid of `new_key` or `old_key`, and adopt it as shown in the table.
3. On delete or purge, drop `previous`.
4. Persist the ring.
5. Re-put state (§10) after any change.

The CLI judges an edge "ready" from the kids it reports in its pong. This whole sequence was exercised live: [`rotation-pong-progression.json`](v1.0/examples/rotation-pong-progression.json), [`keyring-records.json`](v1.0/examples/keyring-records.json). `E2E_KEYFILES` is written by the CLI only; edges MUST NOT write it.

### 13.6 Vectors

[`v1.0/vectors/e2e-vectors.json`](v1.0/vectors/e2e-vectors.json) has 7 positive cases (command, KV value, ping, pong-on-inbox, both rotation records, new-key command) and 6 negative cases. They use fixed test keys and nonces. An implementation MUST reproduce every positive frame byte-for-byte when given the same key and nonce, and MUST reach the stated outcome for every negative case.

## 14. Remote update

- The request is a NATSMessage with `command.name = "update"` on core subject `puda.<id>.update` ([example](v1.0/examples/update-request.json)). For example `params: {"source_type": "git"|"docker", "ref": …, "checkout": …}`. `header.run_id` is a fresh UUID used only to correlate the reply.
- The edge MUST publish exactly one response on `puda.<id>.update.response`, with the same envelope rules as §8.4, **before** it restarts. Success means the new code is staged; there is no second "restarted" message.
- A malformed request, including one with another major's `header.protocol_version`, is not acted on. It is answered `EXECUTION_ERROR` "Invalid command envelope: …" when it is correlatable (§8.4), and otherwise dropped and logged.
- After restarting, the edge MUST resume heartbeats. The CLI waits for one.
- Python performs `git fetch` / `reset --hard` / `uv sync` or `docker pull`, then re-executes itself. Other implementations MAY interpret `source_type` differently, for example `"ota"` with `ref` as a firmware URL. They MUST answer unknown source types with `UNKNOWN_COMMAND`.
- An edge that does not support updates SHOULD still answer with `UNKNOWN_COMMAND`, so the CLI fails fast instead of timing out.

## 15. Conformance profiles

| Requirement | Core (embedded) | Full |
|---|---|---|
| §3 identity, §4 transport with headers, reconnect | MUST | MUST |
| §4.1 TLS with explicit CA | MUST when the broker is `tls://` | MUST |
| §5 work without provisioning rights | MUST | MUST |
| §6/§8 ping and broadcast ping | MUST | MUST |
| §8.2 queue consumer, serial, `+WPI` | MUST | MUST |
| §8.3 immediate request/reply, concurrent | MUST | MUST |
| §8.4–8.6 responses and codes | MUST | MUST |
| §2 `protocol_version` in pong, `header.protocol_version` check | MUST | MUST |
| §9 run model, pause, estop latch | MUST | MUST |
| §10 state KV | MUST | MUST |
| §11 catalog KV | MUST, static and generated at build time | MUST, from code |
| §12 heartbeat | MUST | MUST |
| §12 health, streams, events | MAY | SHOULD |
| §13 E2E incl. rotation | MUST if the deployment uses E2E | MUST |
| §14 update | SHOULD (OTA or `UNKNOWN_COMMAND`) | MUST |
| Pong `local_ip`, `tailscale_ip`, `magicdns`, `uptime_seconds`, `description` | MAY | SHOULD |

## 16. Known deviations in the Python reference (SDK 0.0.23)

Each was reproduced against the live stack with SDK 0.0.23. Transcript names refer to `v1.0/transcripts/`, which were captured from 0.0.23. The last column names the release that conforms (0.1.0 is the first release speaking this spec); integration tests for each fix live in `libs/python-sdk/tests/integration/`.

| ID | Behaviour | Impact | Evidence | Fixed |
|---|---|---|---|---|
| D-1 | A queued command received while paused is not acked. It is redelivered after `ack_wait` (30 s) and evaluated again. | A command the client was told failed can execute later. | 04 `run3_paused_cmd`, `imm_start_no_run` (delivery #2) | 0.1.0: pause holds the queue (§9.4) |
| D-2 | `cancel` does not interrupt the running queued command. State says `idle`/`null` while it runs. | The operator believes the work stopped. Queued work stays blocked. | 04 `cancel_flow` | 0.1.0: `cancel` removed; `complete` with `abort` (§9.8) |
| D-3 | `pause` writes `run_id` from the header (`""` from the CLI). `resume` writes `null` while a run is still active. | State KV misreports the run. | 04 `run3_pause`, `run3_resume` | 0.1.0: active run in state (§9.3) |
| D-4 | After a broker restart the edge holds two connections and answers ping twice. | Duplicate pongs, duplicate subscriptions. | `connz` showed 2 edge connections; `nats req --replies=0` got 2 pongs | 0.1.0: one connection (§7) |
| D-5 | Stale immediate commands replay on startup; the queue binds before immediate; a hidden active run blocks `start`. | Stale `start`/`estop`/`reset` act minutes or days later. | 05 `offline_backlog` | 0.1.0: immediate commands are core request/reply, so nothing is stored to replay (§8.3, §9.7) |
| D-6 | Malformed queue or immediate messages produce no response. | Client waits for its full timeout. | 03 `malformed` | 0.1.0: correlatable ones answered, state unchanged (§8.4) |
| D-7 | Edge issues `STREAM.CREATE` for KV buckets and would `STREAM.UPDATE` command streams whose config differs. | May override provisioned settings. | 01 `startup` | 0.1.0: create only if missing, never update (§5) |
| D-8 | `pause`, `resume` and `cancel` return `UNKNOWN_COMMAND` when the driver lacks the method, after applying the effect. | The CLI reports failure for an action that happened. | 04 `min_driver` | 0.1.0: missing hooks succeed (§9.3) |

## 17. Discrepancies with the public docs

The Communication page (`apps/docs/docs/overview/communication.mdx`) does not match this spec in several places:

- **Heartbeat rate.** The page says every second; edges publish every 5 s.
- **`tlm.status`.** The page lists `puda.<id>.tlm.status`, which does not exist. State lives in KV `MACHINE_STATE`.
- **Response stream retention.** The page says "Limits"; provisioning uses `interest` with a 24 h max age.
- **Events transport.** The page says events use JetStream; they are core NATS.
- **Queue delivery guarantee.** "Exactly-once" for commands is not accurate. Delivery is at-least-once with redelivery after `ack_wait`, so exactly-once execution relies on the edge acking or terminating every message it acts on (§8.2, D-1).

## 18. Open issues for 1.1

1. Define broker authentication (NKEY/JWT) for edges outside a trusted network.
2. Consider an MQTT binding. The broker already exposes MQTT, and ESP-IDF has a native MQTT client. Work-queue consumption and ack semantics would need to be specified first.
3. Consider `sdk_name` in the pong, so reports can tell implementations apart; compatibility does not need it (§2).

## 19. Errata

These fix contradictions in the 1.0 text, and places where the reference disagreed with it. The protocol version stays `1.0`. "Fixed" names the first Python SDK release that conforms.

| ID | Change | Fixed |
|---|---|---|
| E-1 | §9.3: an unknown immediate name is answered `UNKNOWN_COMMAND`. The text said it was dispatched to the driver; its own `cancel` note and the reference already answered `UNKNOWN_COMMAND`. | text only |
| E-2 | §9.1: only errors from running a command (§9.2 rows 0b and 7–10) end the run. The text said any error did, which contradicted rows 4–6. | text only |
| E-3 | §9.2: the order is 0a, 1, 0b, 2. The reference checked the estop latch before row 0b, so a command that may already have run was answered `MACHINE_ESTOPPED` instead of outcome unknown. | Unreleased |
| E-4 | §9.3, §9.6: while the estop latch is set, `pause` and a failed `reset` put `estopped`. The reference put `paused` and `error`. | Unreleased |
| E-5 | §8.1: the reference dropped unknown `header`, `command` and top-level fields instead of echoing them. | Unreleased |
| E-6 | §2, §8.6: receivers accept unknown response codes. The reference Python client rejected the whole response, so its wait timed out, and the schema allowed only the 1.0 codes. | Unreleased |
| E-7 | §14: a malformed update request is answered when correlatable. The reference dropped it, so the CLI waited for its timeout. | Unreleased |
| E-8 | §9.6 step 1: the latch is checked immediately before the driver call. The reference checked it before putting `busy`, so an estop or `complete --abort` handled during that put did not stop the command from starting. | Unreleased |
| E-9 | §10, §11.1: state and catalog values carry `protocol_version` (SHOULD; readers MUST NOT require it). This only adds an optional field. | Unreleased |

---

## Appendix A. JetStream wire operations for clients without a JetStream library

Every request below is a core-NATS request with a fresh reply inbox. Responses are JSON. An `"error"` object means failure. Immediate commands (§8.3) need none of this: subscribe to `puda.<id>.cmd.immediate` and publish the answer to each message's reply subject.

| Operation | Publish to | Body |
|---|---|---|
| Stream exists? | `$JS.API.STREAM.INFO.<stream>` | empty |
| Queue consumer info | `$JS.API.CONSUMER.INFO.COMMAND_QUEUE.cmd_queue_<id>` | empty; error `10014` means not found |
| Create queue consumer | `$JS.API.CONSUMER.CREATE.COMMAND_QUEUE.cmd_queue_<id>.puda.<id>.cmd.queue` | `{"stream_name":"COMMAND_QUEUE","config":{"name":"cmd_queue_<id>","durable_name":"cmd_queue_<id>","deliver_policy":"all","ack_policy":"explicit","filter_subject":"puda.<id>.cmd.queue"}}` |
| Delete consumer | `$JS.API.CONSUMER.DELETE.<stream>.<durable>` | empty |
| Pull next message | `$JS.API.CONSUMER.MSG.NEXT.COMMAND_QUEUE.cmd_queue_<id>` | `{"batch":1,"expires":<ns>}`. Reply is either a message or an empty status (`408` timeout, `404`/`409`). |
| Ack / terminate / in-progress | the delivered message's reply `$JS.ACK.<stream>.<consumer>.<delivered>.<sseq>.<cseq>.<ts>.<pending>` | empty or `+ACK` / `+TERM` / `+WPI` / `-NAK`. Sent as a request, the server confirms with an empty reply. |
| JetStream publish | the subject itself, with a reply inbox | payload. The reply is a PubAck `{"stream":"…","seq":n}` or an error. |
| KV put | `$KV.<bucket>.<key>`, as a JetStream publish | value |
| KV get | `$JS.API.DIRECT.GET.KV_<bucket>.$KV.<bucket>.<key>` | empty. The reply carries headers `Nats-Subject`, `Nats-Sequence`; status `404` means missing. |
| KV watch, one key | `$JS.API.CONSUMER.CREATE.KV_<bucket>` | ordered consumer, as sent by the reference: `{"stream_name":"KV_<bucket>","config":{"deliver_policy":"last_per_subject","ack_policy":"none","max_deliver":1,"filter_subject":"$KV.<bucket>.<key>","replay_policy":"instant","flow_control":true,"idle_heartbeat":5000000000,"headers_only":false,"deliver_subject":"<inbox>","mem_storage":true,"num_replicas":1}}`. Deletes arrive with header `KV-Operation: DEL`. Embedded edges may poll `DIRECT.GET` instead (§13.5). |

A JetStream-delivered message arrives on the subscription's inbox with its MSG subject set to the **original** subject (`puda.<id>.cmd.queue`). Use that subject as the E2E AAD.

## Appendix B. Embedded implementation notes (non-normative)

- **Memory.** A TLS session plus JSON parse buffers plus a 16 KiB command buffer fits comfortably on an ESP32-S3 with PSRAM. Allocate the catalog value in flash.
- **Tasks.** Run the NATS reader, queue executor and immediate handler as separate tasks. The immediate handler answers on the request's reply subject; it never touches JetStream except to record the copy on `RESPONSE_IMMEDIATE`. The estop path MUST NOT wait on the queue executor's mutex. Keep the motion loop on its own core, and keep hardware interlocks independent of the network.
- **Catalog.** Generate `commands`, `catalog`, `hooks` and the C dispatch table from one command spec (YAML/JSON) at build time. Emit `parameters` schemas (§11.3) so `puda protocol validate` does not depend on parsing Python-looking signatures.
- **Time.** Gate startup on SNTP sync (§4.3).
- **Keys.** Keep the ring in NVS (encrypted NVS if available). Use the hardware AES-GCM through mbedTLS.
- **Updates.** Map `update` with `source_type: "ota"` to ESP-IDF OTA. Publish the response, then reboot. Heartbeats resume after boot.
- **Conformance.** Run `check.py` against your crypto implementation using the vectors, and validate the payloads your edge builds against the schemas, as the reference test suites do (see the [README](README.md)). The transcripts are historical: they were captured from SDK 0.0.23 and show the pre-1.0 wire shape (Appendix C). Where they disagree with the examples or this text, the examples and this text win.

## Appendix C. How the evidence was produced

- **Stack.** An isolated `nats-server 2.15.3` (plaintext and `tls://` instances), provisioned with `setup_streams.sh`.
- **Edges.** The repository's `test-edge` driver on Python SDK 0.0.23: plaintext `proto-test`; E2E `proto-e2e` with a live CLI rotation, switch and retire; and a minimal driver `proto-min`.
- **Clients.** CLI `0.1.6-rc2`, plus raw nats-py publishes for cases the CLI cannot produce: estop, cancel, malformed input, offline backlog.
- **Later shape changes.** The transcripts predate SDK 0.1.0: they show immediate commands on the `COMMAND_IMMEDIATE` stream and `header.version`/`command.version`. The examples were updated to the 0.1.0 envelope (`header.protocol_version`, no `command.version`, `protocol_version` in pongs), and `response-immediate-start-repeat.json`, `response-queue-protocol-mismatch.json`, `response-immediate-complete-abort.json` and `response-queue-aborted.json` were captured from a 0.1.0rc1 edge.
- **Capture.** A `>` subscriber recorded every message. All 1,689 PUDA payloads in the captures (252 command/response envelopes, 69 state values, 7 catalogs, 33 pongs, 1,300 telemetry samples, 12 events and 16 keyring records) validate against the schemas in `v1.0/schemas/`. All 581 sealed frames in the E2E capture open under the AAD rules in §13.3, across both keys, with no plaintext seen on `puda.*`. The Go CLI opened the Python edge's frames, and the reverse, throughout, including across the rotation.
- **Redaction.** IP addresses, host names and user IDs in the examples and transcripts are replaced with documentation values. Lab keys from the capture are not included; the vectors use fixed test keys.
