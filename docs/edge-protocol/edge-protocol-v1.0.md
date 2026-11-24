# PUDA Edge Protocol 1.0

| | |
|---|---|
| Status | Draft for review |
| Protocol version | `1.0`, carried as `header.version` in every command and response. E2E frames are format `0x01`. |
| Reference implementations | Python SDK `0.0.23` (`libs/python-sdk`). CLI `0.1.x` (`apps/cli`, commit `ac7fb56`). Broker `nats-server 2.15.3` provisioned by `infra/nats/jetstream/setup_streams.sh`. |
| Evidence | Wire captures in [`v1.0/transcripts/`](v1.0/transcripts/). Payload examples in [`v1.0/examples/`](v1.0/examples/). Schemas in [`v1.0/schemas/`](v1.0/schemas/). E2E vectors in [`v1.0/vectors/`](v1.0/vectors/). Run [`v1.0/check.py`](v1.0/check.py) to validate them. |

This document specifies what a PUDA **edge** must do on the wire to be driven by the PUDA CLI, agents and loggers. An edge is the process that owns one machine. The spec is written so a second implementation, such as a C SDK on an ESP32, can interoperate without reading the Python source.

The key words MUST, MUST NOT, SHOULD, SHOULD NOT and MAY are used as in RFC 2119.

Behaviour is described in two ways:

- **Normative text** is the contract. A conforming edge MUST follow it.
- **Observed** notes record what the Python reference does today, including defects. These are listed in §16 and are not requirements. Where the reference deviates from the normative text, the normative text wins.

---

## 1. Roles

| Role | Description | Reference |
|---|---|---|
| Edge | Owns one machine (`machine_id`). Consumes commands, publishes responses, state, catalog and telemetry. | `EdgeRunner` + `EdgeNatsClient` |
| Client | Sends commands and waits for responses. Examples: the CLI, agents, `CommandService`. | `apps/cli`, `puda.command_service` |
| Observer | Subscribes without sending. Examples: loggers, `puda machine watch`. | `puda-logger` |
| Provisioner | Creates streams and KV buckets. | `infra/nats/jetstream/setup_streams.sh` |
| Broker | NATS with JetStream. | `nats:2.15.3` |

An edge serves exactly one `machine_id`. Several edges MAY share a host and a NATS connection pool, but each machine has its own subjects, consumers and KV keys.

## 2. Versioning

- `header.version` MUST be `"1.0"` in messages produced under this spec. `command.version` defaults to `"1.0"`.
- Receivers MUST ignore unknown JSON fields. Both reference implementations already do this: pydantic ignores extras and Go `encoding/json` drops them. Additive fields are therefore backward compatible within `1.x`.
- Changing a subject, consumer name, required field, ack rule or the E2E frame layout requires a new major version.
- An edge does not currently advertise a protocol version. §18 proposes adding `protocol_version` to the pong.

## 3. Machine identity

- `machine_id` MUST match `^[A-Za-z0-9_-]+$`. It SHOULD be lowercase and hyphenated, for example `opentron`, `esp32-pump-1`.
- `machine_id` is used verbatim as a subject token, a KV key and part of a durable consumer name. The Python edge and the CLI ping path replace `.` with `-` in subjects. The CLI command path and KV keys do not. An ID containing `.` therefore resolves to different subjects on different paths, which is why `.` is forbidden.
- The machine description advertised in the pong is a single line, typically the first paragraph of the driver class docstring.

## 4. Transport

### 4.1 NATS connection

- An edge MUST speak the NATS client protocol with **headers** (`HPUB`/`HMSG`). Headers carry JetStream status codes (`408`, `404`, `409`), `KV-Operation` markers and `Nats-Subject` on KV reads.
- Server URLs are either all `nats://` or all `tls://`. Mixing them is a configuration error.
- With `tls://`, the edge MUST verify the server certificate against an explicitly configured CA file (`PUDA_NATS_CA` / `ca_file`). Reference deployments use server-only TLS; client certificates are not required.
- Authentication: reference deployments run without broker authentication; access is controlled at the network layer. Edges SHOULD support token or user/password authentication for deployments that add it. NKEY and JWT support is OPTIONAL in 1.0.
- Reconnect: the edge MUST reconnect forever. The reference waits 2 s between attempts and uses a 10 s connect timeout. After a reconnect the edge MUST restore every subscription and consumer binding (§7) and republish its state (§10).

### 4.2 Message size

The broker allows 64 MB payloads. An edge MUST accept command messages of at least 16 KiB and MAY reject larger ones with `EXECUTION_ERROR`. The test edge's catalog value (§11) is about 13 KB, so an edge MUST also be able to publish its own catalog in one message.

### 4.3 Time

Every timestamp in this protocol is UTC ISO 8601. The reference format is `YYYY-MM-DDTHH:MM:SSZ` at second precision; receivers MUST also accept fractional seconds.

An edge MUST have a synchronised wall clock (for example SNTP on an ESP32) before it publishes state or responses. Until then it MAY publish only heartbeats.

## 5. Provisioning

Provisioning is the operator's job, not the edge's. `setup_streams.sh` creates the following:

| Name | Kind | Subjects / key | Retention and settings |
|---|---|---|---|
| `COMMAND_QUEUE` | Stream | `puda.*.cmd.queue` | `workqueue`, file storage, `discard: new`, `max_msgs_per_subject: 100` |
| `COMMAND_IMMEDIATE` | Stream | `puda.*.cmd.immediate` | `workqueue`, file storage, `discard: new`, `max_msgs_per_subject: 100` |
| `RESPONSE_QUEUE` | Stream | `puda.*.cmd.response.queue` | `interest`, `max_age` 24 h |
| `RESPONSE_IMMEDIATE` | Stream | `puda.*.cmd.response.immediate` | `interest`, `max_age` 24 h |
| `MACHINE_STATE` | KV | key `<machine_id>` | history 1 |
| `MACHINE_COMMANDS` | KV | key `<machine_id>` | history 1 |
| `E2E_KEYRING` | KV | key `current` | history 1 |
| `E2E_KEYFILES` | KV | `cli/<id>` | history 1; written by the CLI only |
| `LIVESTREAMS` | KV | — | history 1; not used by edges |

Rules:

- An edge MUST work against these pre-provisioned objects without creating or modifying any of them.
- An edge SHOULD NOT create or update streams. A Core edge (§15) MUST NOT update them, because an update can overwrite provisioned settings such as replicas or `max_msgs_per_subject`.
- An edge MAY call `STREAM.INFO` to check that a stream exists. If one is missing it SHOULD log the problem and retry, not create it.
- Writing a KV value needs no API call. Publishing to `$KV.<bucket>.<key>` through JetStream is enough (Appendix A).

> **Observed.** On every connect the Python edge calls `STREAM.INFO` on all four streams. It would call `STREAM.UPDATE` if subjects or retention differed. It also attempts `STREAM.CREATE` for each KV bucket and falls back to `STREAM.INFO` after error `10058`. This is harmless against correctly provisioned streams but conflicts with the rule above (§16, D-7).

## 6. Subject map

`<id>` is the `machine_id`. Payloads are JSON (UTF-8). When E2E is enabled every payload is sealed, including the literal `ping` (§13).

| Subject | Transport | Direction | Payload | Required (Core) |
|---|---|---|---|---|
| `puda.<id>.cmd.queue` | JetStream `COMMAND_QUEUE` | client → edge | [NATSMessage](v1.0/schemas/nats-message.schema.json) command | MUST |
| `puda.<id>.cmd.immediate` | JetStream `COMMAND_IMMEDIATE` | client → edge | NATSMessage command | MUST |
| `puda.<id>.cmd.response.queue` | JetStream `RESPONSE_QUEUE` | edge → clients | NATSMessage response | MUST |
| `puda.<id>.cmd.response.immediate` | JetStream `RESPONSE_IMMEDIATE` | edge → clients | NATSMessage response | MUST |
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
3. Bind the immediate consumer (§8.3), **then** the queue consumer (§8.2), so stale immediate commands are discarded (§9.7) before queued work is pulled.
4. Subscribe to `puda.<id>.update` if it supports updates.
5. Put the catalog to `MACHINE_COMMANDS/<id>`.
6. Put state `idle` with the active `run_id` (normally `null` after a restart) to `MACHINE_STATE/<id>`, or `estopped` if the estop latch is set (§9.6).
7. Start heartbeats (§12).

> **Observed.** After a broker restart Python ends up with two NATS connections and answers ping twice (D-4). See [transcript 01](v1.0/transcripts/01-startup-and-discovery.md) and [transcript 05](v1.0/transcripts/05-lifecycle-and-recovery.md).

## 8. Commands

### 8.1 Envelope

Commands and responses share one envelope ([schema](v1.0/schemas/nats-message.schema.json), [example](v1.0/examples/command-queue.json)):

```json
{
  "header": {
    "version": "1.0",
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
    "version": "1.0",
    "machine_id": "proto-test"
  }
}
```

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
- Acknowledgements go to the delivered message's reply subject `$JS.ACK.COMMAND_QUEUE.cmd_queue_<id>.…`. An empty body and `+ACK` are equivalent. The reference sends an empty body for ack and `+TERM` for terminate. `+NAK` is not used.

### 8.3 Immediate consumer

| Item | Value |
|---|---|
| Stream | `COMMAND_IMMEDIATE` |
| Durable name | `cmd_immed_<id>` |
| Kind | Push with a `deliver_subject` (reference) or pull. Both conform. |
| Config | `{"durable_name":"cmd_immed_<id>","filter_subject":"puda.<id>.cmd.immediate","ack_policy":"explicit","deliver_policy":"all"}` |

- On each connect the edge MUST delete and recreate `cmd_immed_<id>`, so a durable left behind by an earlier implementation with a different kind cannot block binding.
- Immediate commands MUST be processed **concurrently** with a running queued command. `pause`, `complete` with `abort`, and `estop` exist to act while a queued command is running.
- The edge MUST ack an immediate command on receipt, before executing it. A malformed immediate MUST still be acked or terminated so it is not redelivered.

### 8.4 Responses

For every command it acts on, the edge MUST publish exactly one response through JetStream and wait for the PubAck. Queue commands go to `puda.<id>.cmd.response.queue`; immediate commands go to `puda.<id>.cmd.response.immediate`.

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
- For queue commands, the reference acks or terminates first and then publishes the response.

> **Observed.** A queue or immediate message that is not valid JSON or fails envelope validation gets no response. The queue message is terminated; the immediate message is acked and state becomes `error`. The client waits until its timeout (D-6). Edges SHOULD publish an `EXECUTION_ERROR` or `JSON_DECODE_ERROR` response when `header.run_id`, `machine_id` and `step_number` can still be recovered.

### 8.5 Driver command dispatch

- Only commands listed in the catalog (§11) are dispatchable. Names starting with `_` MUST be rejected.
- An unknown name gets `UNKNOWN_COMMAND` with the message `Unknown or restricted command: <name>`.
- Handler failure MUST produce `status: error`, `code: EXECUTION_ERROR`, and a `message` that describes the failure (targets, hardware response). Never report failure with a "successful" `false`.
- `estop` sent through the queue MUST be rejected with `EXECUTION_ERROR` and the message `estop is an immediate command; use puda machine estop <machine_id>`.
- A second queued command arriving while one runs cannot happen given the serial rule in §8.2. If an implementation allows it anyway, it MUST reply `EXECUTION_LOCKED`.

### 8.6 Response codes

| Code | Meaning |
|---|---|
| `UNKNOWN_COMMAND` | Name not in the catalog, or an unknown immediate verb. |
| `EXECUTION_ERROR` | Handler raised; envelope problem (missing `run_id` on queue, missing command); estop via queue. |
| `EXECUTION_LOCKED` | Another queued command holds the execution lock, or `complete` without `abort` while a command of the run is running (§9.3). |
| `COMMAND_CANCELLED` | The running queued command was stopped by `estop` or `complete` with `abort`. |
| `RUN_ID_MISMATCH` | No active run, a different active run, `complete` for an inactive run, or `start` while another run is active. |
| `MISSING_RUN_ID` | `start` or `complete` without a `run_id`. |
| `MACHINE_PAUSED` | Reserved. A paused edge holds queued commands instead (§9.4). |
| `MACHINE_ESTOPPED` | Queued command, `start` or `resume` while the estop latch is set. |
| `ESTOP_NOT_SUPPORTED` | `estop` on a machine without a hardware stop. The latch is still set. |
| `JSON_DECODE_ERROR` | Undecodable payload. Defined, not observed. |
| `PAUSE_ERROR`, `RESUME_ERROR`, `CANCEL_ERROR`, `NO_EXECUTION` | Reserved. Not emitted by the reference. |

## 9. Run model and command semantics

### 9.1 Runs

- An edge holds at most one active `run_id`. It lives in memory only; after an edge restart there is no active run.
- Queued commands MUST carry the active `run_id`. `start` sets it, and `complete`, `reset` and `estop` clear it.
- **Any error response to a queued command ends the active run.** The edge clears the run and terminates the message. Clients must send a new `start` to continue ([transcript 03, `run2_unknown` → `run2_fail`](v1.0/transcripts/03-errors.md)).

### 9.2 Queued command decision table

The edge MUST evaluate these checks in this order:

| # | Condition | Ack | Response | Run | State |
|---|---|---|---|---|---|
| 1 | Payload unreadable (bad frame, bad JSON) | `+TERM` | none (see D-6) | — | — |
| 2 | Estop latch set | `+TERM` | `MACHINE_ESTOPPED` "Machine emergency stopped; send reset before queuing commands" | — | — |
| 3 | Paused | held, keep-alive `+WPI` | none until resume, then rows 4–11 | — | — |
| 4 | `run_id` is `null` | `+ACK` | `EXECUTION_ERROR` "Command requires run_id" | — | — |
| 5 | No active run | `+ACK` | `RUN_ID_MISMATCH` "Send START command to start a run before sending commands" | — | — |
| 6 | `run_id` ≠ active run | `+ACK` | `RUN_ID_MISMATCH` "Run ID mismatch: expected active run, got <run_id>" | — | — |
| 7 | Command is `estop` | `+TERM` | `EXECUTION_ERROR` | cleared | — |
| 8 | Name not dispatchable | `+TERM` | `UNKNOWN_COMMAND` | cleared | `busy` → `error` |
| 9 | Handler raises | `+TERM` | `EXECUTION_ERROR` | cleared | `busy` → `error` |
| 10 | Stopped by `estop` or `complete` with `abort` | `+TERM` | `COMMAND_CANCELLED` (`data` is the handler's result, if it returned) | cleared | `estopped`, or `idle` + `null` after abort |
| 11 | Success | `+ACK` | `success`, `data` | kept | `busy` → `idle` |

Row 3 only applies to a message delivered at the instant the edge paused; otherwise a paused edge does not pull (§9.4). Rows 2 and 3 are re-evaluated when the hold ends, so an estop while held terminates the message with `MACHINE_ESTOPPED`.

### 9.3 Immediate commands

Immediate verbs are matched case-insensitively. Any other name is dispatched to the driver like a queued command (§8.5), without run checks.

| Verb | Precondition | Effect | Response | State |
|---|---|---|---|---|
| `start` | `run_id` set; no estop latch; no active run | Run becomes active | `success` / `MISSING_RUN_ID` / `MACHINE_ESTOPPED` / `RUN_ID_MISMATCH` "cannot start, <active> is currently running" | `idle` + `run_id` |
| `complete` | `run_id` = active run, and no command of the run running unless `params.abort` | Run cleared; see §9.8 | `success` / `EXECUTION_LOCKED` / `MISSING_RUN_ID` / `RUN_ID_MISMATCH` "Run <id> not active" | `idle`, `run_id: null` |
| `pause` | — | Pause latch set; driver `pause` called if it is in the catalog | Driver result, or `success` if absent | `paused` + active run |
| `resume` | No estop latch | Pause latch cleared; driver `resume` called if present | Driver result, or `success` if absent / `MACHINE_ESTOPPED` | `idle` + active run, or `busy` if a command is running |
| `reset` | — | Run cleared; driver `reset` called if present. On success the estop latch is cleared. | Driver result, or `success` if absent | `idle` on success, `error` on failure |
| `estop` | — | §9.6 | — | `estopped` |

Notes:

- "Driver result, or `success` if absent" is the normative rule. A machine without a `pause` method still pauses.
- There is no `cancel` verb. It is answered `UNKNOWN_COMMAND` "Unknown immediate command: cancel" like any other unknown verb ([example](v1.0/examples/response-immediate-cancel-unknown.json)). A driver method named `cancel` is dispatched only through the queue.
- `pause` and `resume` do not change the run. The `run_id` they put in state is the **active** run (or `null`), never `header.run_id`.

### 9.4 Pause

Pause **holds the queue**; resume continues it in order.

- A queued command that is already running continues and is answered normally.
- While paused the edge MUST NOT pull from `COMMAND_QUEUE`. Commands published meanwhile stay in the stream, unanswered.
- A message already delivered when the pause took effect MUST be held in memory with `+WPI` at an interval shorter than `ack_wait`, so it is not redelivered, and MUST run first on resume.
- `resume` restarts pulling. Held and backlogged commands then go through §9.2 in delivery order; commands of a run that ended meanwhile get `RUN_ID_MISMATCH`.
- `estop` while paused releases the hold: the held message and the backlog are terminated with `MACHINE_ESTOPPED` (§9.6). A later `reset` leaves the pause latch set.
- Pause does not affect immediate commands.
- Clients wait for queued responses without a timeout, so a paused command answered later is not an error for them.

### 9.5 Busy status

`run_status` in the pong is `busy` while a queued command executes and `idle` otherwise. It is not persisted.

### 9.6 Emergency stop

On `estop` the edge MUST, in this order:

1. Set the **estop latch** before anything else, so no queued command can start.
2. Issue the hardware stop without waiting behind the running queued command. The reference uses a dedicated thread.
3. Cancel the running queued command. Its response is `COMMAND_CANCELLED` and its message is terminated.
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

### 9.7 Backlog and staleness

`COMMAND_QUEUE` and `COMMAND_IMMEDIATE` are work-queue streams, so messages published while an edge is offline wait for it.

Immediate commands act on the machine *now*, so a backlog of them must not replay. Recreating the immediate durable with `deliver_policy: all` delivers every immediate command published while the edge was offline, including `start`, `estop` and `reset`.

- The edge MUST discard an immediate command whose **stored time** is more than `immediate_max_age` before its receipt. The default is 10 s; it MAY be configurable, and disabling it is not conforming.
- The stored time is the JetStream server timestamp of the message: the `timestamp` field of the delivery metadata, which is the 8th token (nanoseconds since the Unix epoch) of the reply subject `$JS.ACK.COMMAND_IMMEDIATE.cmd_immed_<id>.<delivered>.<stream_seq>.<consumer_seq>.<timestamp>.<pending>`. `header.timestamp` MUST NOT be used: it is the client's clock and second-precision. The comparison uses the edge's synchronised clock (§4.3); if the stored time cannot be read the command is processed.
- A discarded command MUST be acked, MUST NOT act, and MUST be answered `EXECUTION_ERROR` "Stale immediate command discarded: stored <age>s ago (max <max>s); the edge was offline when it was sent", so a client that is still waiting learns why ([example](v1.0/examples/response-immediate-stale.json)). It does not change state.
- Queued commands published while the edge was offline remain in `COMMAND_QUEUE` and are evaluated normally; after a restart there is no active run, so they get `RUN_ID_MISMATCH`.

`deliver_policy: new` was rejected as an alternative: undelivered messages would stay in the stream and count against `max_msgs_per_subject` (100).

### 9.8 Completing and aborting a run

`complete` is designed for clients, such as agents, that may act on a stale view of the machine: by default it never stops work, it explains a refusal, and repeating it is safe.

1. **Already ended.** If `run_id` is not active but was active recently on this edge (completed, cleared by an error, `reset` or `estop`), respond `success` with `data: {"already_completed": true}` and change nothing ([example](v1.0/examples/response-immediate-complete-repeat.json)). The edge MUST remember at least the last ended run and SHOULD remember more; the reference keeps the last 64 since it started. Otherwise respond `RUN_ID_MISMATCH`.
2. **Refusal.** If a queued command of the run is running and `params.abort` is not `true`, respond `EXECUTION_LOCKED` with `data.running` = `{"name", "step_number", "elapsed_s"}` and `data.queued` = the number of queued commands not yet answered behind it (`null` if unknown). The run stays active ([example](v1.0/examples/response-immediate-complete-locked.json)).
3. **Abort.** With `params.abort: true` the edge MUST:
   1. Count `queued` before stopping anything.
   2. Call the driver's `abort` if the catalog has it, on a thread or task that does not wait behind the running command (like §9.6 step 2).
   3. Wait up to 5 s for the running command to return. If it does not, stop waiting for it.
   4. Answer the running command `COMMAND_CANCELLED` (§9.2 row 10, [example](v1.0/examples/response-queue-aborted.json)) and terminate its message.
   5. Clear the run, put `idle` + `null`, publish `evt.log` at level `WARNING`, and respond `success` with `data` = `{"aborted": {name, step_number, elapsed_s} | null, "driver_abort": bool, "finished": bool, "queued": int | null}` ([example](v1.0/examples/response-immediate-complete-abort.json)). `finished: false` means the hardware call may still be running. A driver `abort` that raises adds `driver_error`.
4. **Plain completion.** Otherwise clear the run, put `idle` + `null` and respond `success`. `data` is `null`, or the abort object of step 3 when `abort` was set and nothing was running.

Commands queued behind the run are not removed. They are evaluated when pulled and get `RUN_ID_MISMATCH`.

`abort` is a soft stop for ending a run early. It is not a safety function and does not latch; hazards use `estop` (§9.6). A client interrupted while it waits for queued responses (the CLI on SIGINT or SIGTERM) SHOULD send `complete` with `abort` to every machine it started, because nothing else will observe the commands still running.

## 10. Machine state (`MACHINE_STATE`)

The value is published to KV `MACHINE_STATE`, key `<id>` ([schema](v1.0/schemas/machine-state.schema.json), [example](v1.0/examples/machine-state.json)):

```json
{"timestamp": "2026-11-23T13:25:24Z", "state": "busy", "run_id": "22222222-…", "homed": false}
```

- `state` is one of `idle`, `busy`, `paused`, `error`, `estopped`, `offline`.
- Machine-specific fields MAY be merged at the top level, as `homed` is above. They MUST NOT reuse `timestamp`, `state` or `run_id`.
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
  - malformed immediate: `error`;
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
  ]
}
```

- `commands` is human-readable text. Agents read it through `puda machine commands`.
- Each `catalog` entry MUST contain `name`, `signature`, `doc` and `safety`. `doc` and `safety` MAY be `null` but MUST be present; the CLI rejects entries missing them.
- A non-null `safety` MUST contain all five fields. `summary` is a non-empty string, `hazards` is an array, and `confirm` is a boolean.
- `confirm: true` makes the CLI ask the operator before sending the command. It is advisory metadata and does not change edge dispatch.
- The catalog SHOULD list the lifecycle commands the driver actually implements: `home`, `reset`, `pause`, `resume`, `abort`, `estop`, `shutdown`.

### 11.2 Signature grammar

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

Telemetry samples use the `{timestamp, data}` wrapper. Consumers SHOULD accept both wrapped and flat shapes for compatibility with older edges.

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
| Reply to a request (pong) | the request's **reply** subject, i.e. the inbox |
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
| §8.3 immediate consumer, concurrent | MUST | MUST |
| §8.4–8.6 responses and codes | MUST | MUST |
| §9 run model, pause, estop latch | MUST | MUST |
| §10 state KV | MUST | MUST |
| §11 catalog KV | MUST, static and generated at build time | MUST, from code |
| §12 heartbeat | MUST | MUST |
| §12 health, streams, events | MAY | SHOULD |
| §13 E2E incl. rotation | MUST if the deployment uses E2E | MUST |
| §14 update | SHOULD (OTA or `UNKNOWN_COMMAND`) | MUST |
| Pong `local_ip`, `tailscale_ip`, `magicdns`, `uptime_seconds`, `description` | MAY | SHOULD |

## 16. Known deviations in the Python reference (SDK 0.0.23)

Each was reproduced against the live stack with SDK 0.0.23. Transcript names refer to `v1.0/transcripts/`, which were captured from 0.0.23. The last column names the release that conforms; integration tests for each fix live in `libs/python-sdk/tests/integration/`.

| ID | Behaviour | Impact | Evidence | Fixed |
|---|---|---|---|---|
| D-1 | A queued command received while paused is not acked. It is redelivered after `ack_wait` (30 s) and evaluated again. | A command the client was told failed can execute later. | 04 `run3_paused_cmd`, `imm_start_no_run` (delivery #2) | 0.0.24: pause holds the queue (§9.4) |
| D-2 | `cancel` does not interrupt the running queued command. State says `idle`/`null` while it runs. | The operator believes the work stopped. Queued work stays blocked. | 04 `cancel_flow` | 0.0.24: `cancel` removed; `complete` with `abort` (§9.8) |
| D-3 | `pause` writes `run_id` from the header (`""` from the CLI). `resume` writes `null` while a run is still active. | State KV misreports the run. | 04 `run3_pause`, `run3_resume` | 0.0.24: active run in state (§9.3) |
| D-4 | After a broker restart the edge holds two connections and answers ping twice. | Duplicate pongs, duplicate subscriptions. | `connz` showed 2 edge connections; `nats req --replies=0` got 2 pongs | open |
| D-5 | Stale immediate commands replay on startup; the queue binds before immediate; a hidden active run blocks `start`. | Stale `start`/`estop`/`reset` act minutes or days later. | 05 `offline_backlog` | 0.0.24: stale immediates discarded, immediate binds first (§7, §9.7) |
| D-6 | Malformed queue or immediate messages produce no response. | Client waits for its full timeout. | 03 `malformed` | open |
| D-7 | Edge issues `STREAM.CREATE` for KV buckets and would `STREAM.UPDATE` command streams whose config differs. | May override provisioned settings. | 01 `startup` | open |
| D-8 | `pause`, `resume` and `cancel` return `UNKNOWN_COMMAND` when the driver lacks the method, after applying the effect. | The CLI reports failure for an action that happened. | 04 `min_driver` | 0.0.24: missing hooks succeed (§9.3) |

## 17. Discrepancies with the public docs

The Communication page (`apps/docs/docs/overview/communication.mdx`) does not match this spec in several places:

- **Heartbeat rate.** The page says every second; edges publish every 5 s.
- **`tlm.status`.** The page lists `puda.<id>.tlm.status`, which does not exist. State lives in KV `MACHINE_STATE`.
- **Response stream retention.** The page says "Limits"; provisioning uses `interest` with a 24 h max age.
- **Events transport.** The page says events use JetStream; they are core NATS.
- **Queue delivery guarantee.** "Exactly-once" for commands is not accurate. Delivery is at-least-once with redelivery after `ack_wait`, so exactly-once execution relies on the edge acking or terminating every message it acts on (§8.2, D-1).

## 18. Open issues for 1.1

1. Advertise `protocol_version` and `sdk_name` in the pong. Today the CLI compatibility check keys on `sdk_version` against Python SDK ranges, so a C edge always shows "compatibility unknown".
2. Fix D-1, D-2, D-3 and D-8 in the Python SDK and then remove the "Observed" notes.
3. Decide whether malformed commands that can still be correlated get a response (D-6).
4. Define broker authentication (NKEY/JWT) for edges outside a trusted network.
5. Consider an MQTT binding. The broker already exposes MQTT, and ESP-IDF has a native MQTT client. Work-queue consumption and ack semantics would need to be specified first.

---

## Appendix A. JetStream wire operations for clients without a JetStream library

Every request below is a core-NATS request with a fresh reply inbox. Responses are JSON. An `"error"` object means failure.

| Operation | Publish to | Body |
|---|---|---|
| Stream exists? | `$JS.API.STREAM.INFO.<stream>` | empty |
| Queue consumer info | `$JS.API.CONSUMER.INFO.COMMAND_QUEUE.cmd_queue_<id>` | empty; error `10014` means not found |
| Create queue consumer | `$JS.API.CONSUMER.CREATE.COMMAND_QUEUE.cmd_queue_<id>.puda.<id>.cmd.queue` | `{"stream_name":"COMMAND_QUEUE","config":{"name":"cmd_queue_<id>","durable_name":"cmd_queue_<id>","deliver_policy":"all","ack_policy":"explicit","filter_subject":"puda.<id>.cmd.queue"}}` |
| Delete consumer | `$JS.API.CONSUMER.DELETE.<stream>.<durable>` | empty |
| Create immediate consumer, push | `$JS.API.CONSUMER.DURABLE.CREATE.COMMAND_IMMEDIATE.cmd_immed_<id>` | `{"stream_name":"COMMAND_IMMEDIATE","config":{"durable_name":"cmd_immed_<id>","deliver_policy":"all","ack_policy":"explicit","filter_subject":"puda.<id>.cmd.immediate","deliver_subject":"<your inbox>"}}` |
| Pull next message | `$JS.API.CONSUMER.MSG.NEXT.COMMAND_QUEUE.cmd_queue_<id>` | `{"batch":1,"expires":<ns>}`. Reply is either a message or an empty status (`408` timeout, `404`/`409`). |
| Ack / terminate / in-progress | the delivered message's reply `$JS.ACK.<stream>.<consumer>.<delivered>.<sseq>.<cseq>.<ts>.<pending>` | empty or `+ACK` / `+TERM` / `+WPI` |
| JetStream publish | the subject itself, with a reply inbox | payload. The reply is a PubAck `{"stream":"…","seq":n}` or an error. |
| KV put | `$KV.<bucket>.<key>`, as a JetStream publish | value |
| KV get | `$JS.API.DIRECT.GET.KV_<bucket>.$KV.<bucket>.<key>` | empty. The reply carries headers `Nats-Subject`, `Nats-Sequence`; status `404` means missing. |
| KV watch, one key | `$JS.API.CONSUMER.CREATE.KV_<bucket>` | ordered consumer, as sent by the reference: `{"stream_name":"KV_<bucket>","config":{"deliver_policy":"last_per_subject","ack_policy":"none","max_deliver":1,"filter_subject":"$KV.<bucket>.<key>","replay_policy":"instant","flow_control":true,"idle_heartbeat":5000000000,"headers_only":false,"deliver_subject":"<inbox>","mem_storage":true,"num_replicas":1}}`. Deletes arrive with header `KV-Operation: DEL`. Embedded edges may poll `DIRECT.GET` instead (§13.5). |

A JetStream-delivered message arrives on the subscription's inbox with its MSG subject set to the **original** subject (`puda.<id>.cmd.queue`). Use that subject as the E2E AAD.

## Appendix B. Embedded implementation notes (non-normative)

- **Memory.** A TLS session plus JSON parse buffers plus a 16 KiB command buffer fits comfortably on an ESP32-S3 with PSRAM. Allocate the catalog value in flash.
- **Tasks.** Run the NATS reader, queue executor and immediate handler as separate tasks. The estop path MUST NOT wait on the queue executor's mutex. Keep the motion loop on its own core, and keep hardware interlocks independent of the network.
- **Catalog.** Generate `commands`, `catalog` and the C dispatch table from one command spec (YAML/JSON) at build time. Emit `parameters` schemas (§11.2) so `puda protocol validate` does not depend on parsing Python-looking signatures.
- **Time.** Gate startup on SNTP sync (§4.3).
- **Keys.** Keep the ring in NVS (encrypted NVS if available). Use the hardware AES-GCM through mbedTLS.
- **Updates.** Map `update` with `source_type: "ota"` to ESP-IDF OTA. Publish the response, then reboot. Heartbeats resume after boot.
- **Conformance.** Run `check.py` against your crypto implementation using the vectors. Compare your edge's wire behaviour against the transcripts.

## Appendix C. How the evidence was produced

- **Stack.** An isolated `nats-server 2.15.3` (plaintext and `tls://` instances), provisioned with `setup_streams.sh`.
- **Edges.** The repository's `test-edge` driver on Python SDK 0.0.23: plaintext `proto-test`; E2E `proto-e2e` with a live CLI rotation, switch and retire; and a minimal driver `proto-min`.
- **Clients.** CLI `0.1.6-rc2`, plus raw nats-py publishes for cases the CLI cannot produce: estop, cancel, malformed input, offline backlog.
- **Capture.** A `>` subscriber recorded every message. All 1,689 PUDA payloads in the captures (252 command/response envelopes, 69 state values, 7 catalogs, 33 pongs, 1,300 telemetry samples, 12 events and 16 keyring records) validate against the schemas in `v1.0/schemas/`. All 581 sealed frames in the E2E capture open under the AAD rules in §13.3, across both keys, with no plaintext seen on `puda.*`. The Go CLI opened the Python edge's frames, and the reverse, throughout, including across the rotation.
- **Redaction.** IP addresses, host names and user IDs in the examples and transcripts are replaced with documentation values. Lab keys from the capture are not included; the vectors use fixed test keys.
