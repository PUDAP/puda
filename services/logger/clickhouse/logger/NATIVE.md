# Native NATS + PUDA E2EE ingestion (opt-in; TLS deployment blocked)

The executable control plane is `clickhouse/logger/native_control.py`; SQL is
constructed by `native_sql.py`; `native_ingest.py` retains compatibility exports
and handles key files, key sync and consumer provisioning. It creates **six NATS-engine sources and one
materialized view per source**, writing directly to the existing `command_logs`
and `telemetry` MergeTree tables. There is **no persisted raw landing table and
no Python data-message subscriber**. Existing Python logger files, deployment,
and consumers are unchanged; retain them as rollback.

This is a tested local implementation, **not a production cutover**. The required
split topology is control/key-sync on **pudadev**, native engine/MVs/ClickHouse on
**pudadev1**, and the existing publisher unchanged. Python never processes data
messages. Remote key publication uses a short-lived SSH helper, not a DB-host daemon.

**Security blocker discovered in actual ClickHouse 26.10.2.103:** the native NATS
client rejects an untrusted CA, but accepts a trusted-CA leaf with the wrong
endpoint name. An isolated regression persisted 25 probe messages from that peer.
Python's control connection correctly rejects both cases. Consequently TLS
`install` is deliberately blocked before any side effects, with no bypass flag.
A successful encrypted-ingestion test is NOT a secure-transport acceptance pass.
See `NATIVE-DEPLOYMENT.md` for the staged design, exact preparation commands,
blocking regression, and remaining gates. Do not deploy or expose plaintext NATS
as a workaround.

## Data and delivery contract

- `puda.*.cmd.response.queue` and `.immediate` bind existing `RESPONSE_QUEUE` and
  `RESPONSE_IMMEDIATE` streams using new **pull**, explicit-ACK durables
  `puda_native_response_queue` and `puda_native_response_immediate`.
- Stream retention must be Limits or Interest; WorkQueue is refused. Existing
  streams and consumers are never reset or reconfigured. Compatible native
  durables can be reused; incompatible settings cause an error.
- Commands (`cmd.queue`, `cmd.immediate`), health, and `tlm.stream.>` use Core
  subscriptions in the distinct `puda_native_core` group. They do not bind a
  machine's command WorkQueue or compete with the old logger's group.
- Each source has exactly one MV. `RawBLOB` retains binary frame bytes;
  `_subject` is the original AAD. SQL validates `E2 01`, frame length, SHA256
  key ID, AES-256-GCM authentication, UTF-8 and JSON object validity. It then
  validates command fields and RFC3339 timestamps before normalizing. Calendar
  days/leap years and clock/offset ranges are checked before accepting the
  permissive parser's result. Nanoseconds are range-checked without Int64
  overflow; fractional precision and UTC offset normalization are retained.
- Missing/incorrect keys, wrong subjects, tampering and invalid records **throw**;
  there is no `WHERE` filter, skip-broken-message allowance, or raw-persistence
  ACK shortcut. Tested response failures remain unacknowledged and redeliver.
- Responses use singleton blocks, one ACK-pending message, unlimited delivery
  attempts and a two-second ACK wait. These are conservative acceptance settings,
  **not performance-tuned defaults**. A poison response blocks its durable until
  repaired. There is no automatic quarantine or destructive poison-message ACK.
- Storage keeps exact plaintext `raw_json`, subject, SHA256 event ID, nanosecond
  timestamp and receipt timestamp. Health/stream envelope detection matches the
  Python logger's exact two-key rule; legacy objects retain other fields.
  Metadata duplicate object fields use Python's last-member-wins behavior.
  Telemetry `data` is semantically JSON, not guaranteed byte-identical to Python's
  compact serialization: nested whitespace, number spelling and duplicate-member
  spelling can remain from the plaintext. `raw_json` is byte-preserved UTF-8.

**Core delivery is not durable.** There is no broker ACK/replay for those taps.
Messages published before native subscriptions attach, during disconnects,
process crashes or failed inserts may be lost. A CREATE TABLE/MV response is not
proof of Core subscription readiness: acceptance tests observed startup loss
without an attachment delay. Production needs an observed canary/readiness gate,
not a fixed sleep. Durable command logging would require a separate capture stream
and design, never consuming the machine WorkQueue.

## Key custody and rotation

`bootstrap` imports an operator-provisioned SDK key file (`encrypt=BASE64`, optional
`previous=BASE64`). Inputs must be owner-only regular files, owned by the control
process; symlinks are refused. Dictionary updates use mode-0600 same-directory
atomic replacement, not SQL INSERTs or key literals.

The dictionary is `puda_native_secrets.keys`, deliberately outside the `puda`
namespace. Tests prove an existing `SELECT ON puda.*` reader cannot SELECT the
keys or use `dictGet` on them. SQL/config metadata contains only the file path,
not keys. Tests scan actual server/error/query logs and dictionary DDL for the
random test keys. Administrative users, processes with FILE privileges, filesystem
access, memory dumps and backups remain inside the key trust boundary. Do not
issue broad `*.*`, FILE, dictGet, or secret-database grants to analytics users.

`sync` reads **only** encrypted KV `E2E_KEYRING/current`, authenticates with AAD
`kv:E2E_KEYRING:current`, validates the record and key IDs, merges the new/old keys
with the existing dictionary file, explicitly reloads the dictionary and verifies
its cardinality. It never subscribes to data subjects. Run this one-shot command
from a supervised, non-overlapping timer; alert on every nonzero exit. Missing KV,
unknown wrapping keys or bad authentication fail rather than adopting plaintext.

Historical keys are retained across rotations and control-process restarts to
support ciphertext replay. This intentionally does **not** auto-revoke old keys.
Pruning/revocation needs an operator decision based on every pending consumer,
stream retention and backups. A logger that missed enough rotations to lose the
KV wrapping key needs secure re-bootstrap; it cannot invent the missing key.
Only one writer may manage the dictionary file. The control process must run as
the dictionary file owner, and ClickHouse must be able to read the mode-0600 file
(normally the same service UID). File ownership/permissions are not relaxed.

## Explicit local commands

From `clickhouse/logger`, after the existing split schema is installed and the
response streams exist, use private files provisioned out of band. Examples are
commands to adapt for an isolated local instance, not a deployment script:

```sh
.venv/bin/python native_control.py bootstrap \
  --source /private/puda-sdk.keys \
  --keys /var/lib/clickhouse/user_files/puda-keys.tsv

.venv/bin/python native_control.py install \
  --server nats://127.0.0.1:4222 --url http://127.0.0.1:8123 \
  --user native_admin --password-file /private/clickhouse.password \
  --keys /var/lib/clickhouse/user_files/puda-keys.tsv

.venv/bin/python native_control.py sync \
  --server nats://127.0.0.1:4222 --url http://127.0.0.1:8123 \
  --user native_admin --password-file /private/clickhouse.password \
  --keys /var/lib/clickhouse/user_files/puda-keys.tsv
```

No dotenv is loaded. Keys/passwords are never CLI values. The dictionary path
must be an absolute path inside the server's `user_files_path`. In loopback mode
it is accessible at the same path to the control process. In remote mode `--keys`
is the agent-local archive and `--remote-key-path` is the mounted server path;
`--remote-target` selects the dedicated SSH alias. `install` is deliberately not an upsert: existing
objects cause failure rather than silently replacing a possibly different
configuration. Installation is not transactional; inspect partial objects after
a failure. Stop native sources before any deliberate teardown. Do not delete the
native durables during an outage: that can discard Interest-retention ownership.

## Reproduce acceptance

The tests require explicit official native binaries, random loopback ports,
disposable data, and test-only random credentials. They do not read deployment
`.env` files. The verified binaries were ClickHouse **26.10.2.103** and NATS
**2.15.2**, with installed PUDA **0.0.19rc1** producing real encrypted frames.

```sh
cd clickhouse/logger
RUN_NATIVE_INTEGRATION=1 \
CLICKHOUSE_TEST_BINARY=/absolute/path/to/clickhouse \
NATS_TEST_BINARY=/absolute/path/to/nats-server \
.venv/bin/python -m pytest tests/ -q
```

Coverage includes actual NATS→engine→MV→MergeTree delivery, all Core subject
families, nanosecond/offset/raw metadata, both response retention policies,
independent backend ACKs during failure, tamper/wrong key/wrong AAD rejection,
key-ID validation, encrypted KV rotation/retry, actual target constraint failure
and recovery, WorkQueue refusal, private files, CLI install/bootstrap/sync,
query-log key checks, reader isolation and SQL validation edge cases. Timestamp
regressions cover zero month/day, minute/second overflow, leap days, offsets and
Int64 nanosecond boundaries. Encrypted responses with zero month/day or minute
60 remain unacknowledged under both Limits and Interest retention, with no row
persisted even after another backend acknowledges its own copy.

## Remaining deployment gates

- Native TLS chain validation and encrypted ingestion have been exercised, but
  hostname rejection FAILED on 26.10.2.103. TLS installation is blocked. Optional
  NATS authentication/ACLs and production least-privilege background MV execution
  are not certified by these tests. Do not replace the deployed logger yet.
- Keep `materialized_views_ignore_errors=0`; do not enable asynchronous/ignored
  view errors, extra filtering views, direct destructive source reads, or
  skip-broken-message settings. Validate the actual deployment's profiles.
- Delivery is at-least-once, not exactly-once. A crash after insertion but before
  ACK can duplicate rows; the existing event ID is available for query deduping.
  Running both implementations into the same tables also duplicates rows.
- Stream max-age/size and administrative purges can remove unacknowledged data;
  monitor pending/redelivery counts, source errors, last persistence time and
  retention capacity. A durable is not a retention override.
- There is no throughput/load, disk-full, power-loss, replica/failover or native
  container acceptance claim. Tests inject a real target constraint failure,
  not every possible storage failure. Docker was not used.
- Key logging tests cover these configured log levels and tested failure paths,
  not every future ClickHouse version/debug setting. Treat admin logs/backups as
  sensitive; exact plaintext is intentionally stored in the destination tables.
