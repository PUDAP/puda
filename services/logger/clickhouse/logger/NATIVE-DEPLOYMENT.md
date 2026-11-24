# Split native control and server: staged deployment design

**NOT DEPLOYED. DO NOT CUT OVER. Native hostname verification fails.**

## Verified blocker and how to unblock

Official ClickHouse **26.10.2.103** + NATS **2.15.2** were exercised on isolated
loopback ports with generated CA/leaf certificates and random E2EE keys. Python
rejects wrong CA and wrong hostname. The native engine rejects wrong CA but
accepts a same-CA leaf for `wrong.invalid` when connecting to `127.0.0.1`. The
explicit `--runxfail` regression persisted **25 messages** from that wrong-name
peer. This is actual ingestion, not merely successful CREATE TABLE.

`native_control.py install --server tls://...` now fails before connecting,
provisioning consumers, uploading keys, or issuing DDL. There is no override.
The SQL builder remains usable for isolated engine research/tests only.

The pinned upstream `src/Storages/NATS/NATSConnection.cpp` calls SetSecure and
LoadCATrustedCertificates but does not set an expected endpoint name. Its
`contrib/nats-io-cmake/CMakeLists.txt` defines NATS_HAS_TLS but not
NATS_FORCE_HOST_VERIFICATION. Review the exact pinned upstream sources:

```text
https://raw.githubusercontent.com/ClickHouse/ClickHouse/v26.10.2.103-stable/src/Storages/NATS/NATSConnection.cpp
https://raw.githubusercontent.com/ClickHouse/ClickHouse/v26.10.2.103-stable/contrib/nats-io-cmake/CMakeLists.txt
```

A fixed, built and independently verified native binary must reject wrong CA,
wrong DNS name AND wrong IP SAN, including reconnects/discovered peers. Only then
remove the explicit CLI gate and strict xfail. Do not assume defining one build
macro fixes IP verification. A preflight Python TLS connection cannot enforce
identity on a later independent native-engine connection. Neither accepting any
CA-signed name, switching off verification, nor exposing plaintext is a fix.
A native TLS proxy would be a separate topology decision, not silently added here.

## Intended topology and security boundary

- **pudadev:** controller/bootstrap/KV key polling, local private archive, SSH
  client and loopback DB HTTP tunnel. No Python data subscription/decryption.
- **pudadev1:** ClickHouse native NATS engines/MVs/dictionary, mounted CA and
  dictionary directory, plus a **one-shot stdlib-only Python SSH forced-command
  helper**, not a daemon or per-message worker. No project venv needed remotely.
- Existing first publisher and broker configuration remain unchanged. Development
  broker is `tls://100.126.78.55:4222`, CA-required, no broker user/password/client
  cert required according to the supplied deployment context. This task did not
  touch or probe live broker/remote hosts.
- No raw landing table. Historical replay keys remain private, not SQL literals.

## Preparation steps for the deployment owner (not executed)

These paths/UIDs reflect the supplied deployment context; verify host identities,
actual container UID and published DB loopback port before applying anything.
Perform these only after the native hostname gate is fixed and authorization to
deploy is renewed. Preserve existing services, files, consumers and publisher.

1. On pudadev1, install the reviewed `native_key_install.py` as a root-owned,
   non-writable executable at `/usr/local/libexec/puda-native-key-install`:

   ```sh
   sudo install -o root -g root -m 0755 native_key_install.py /usr/local/libexec/puda-native-key-install
   install -d -m 0700 /home/puda/.config/puda/clickhouse-logger-e2ee/dictionary
   ```

   Run the helper as **puda UID 1000**, never root. The dictionary directory must
   be owned by that UID and mode 0700. Its target path is fixed in the helper;
   no command-line destination or arbitrary code is accepted. Configure a
   dedicated SSH key with this authorized_keys restriction (insert only its
   public key, never a private key):

   ```text
   restrict,command="/usr/local/libexec/puda-native-key-install" ssh-ed25519 PUBLIC_KEY native-key-sync
   ```

   On pudadev create a `pudadev1-key-sync` SSH alias with the verified host,
   `User puda`, dedicated `IdentityFile`, `IdentitiesOnly yes`,
   `StrictHostKeyChecking yes`, and a pre-verified known-hosts entry. Do not
   disable host verification. Keep the ordinary admin/tunnel identity separate.
   Forced-command access conveys key replacement authority; protect it like
   the key archive. Server administrators remain trusted.

2. Mount the **directory**, not a single file, read-only into ClickHouse:

   ```yaml
   # additions to the remote ClickHouse service, not an applied override
   volumes:
     - /home/puda/.config/puda/clickhouse-logger-e2ee/dictionary:/var/lib/clickhouse/user_files/native:ro
     - /home/puda/.config/puda/clickhouse-logger-e2ee/ca.pem:/etc/clickhouse-server/native-ca/ca.pem:ro
     - /home/puda/.config/puda/clickhouse-logger-e2ee/native-nats.xml:/etc/clickhouse-server/config.d/native-nats.xml:ro
   environment:
     CLICKHOUSE_NATS_TLS_SECURE: "1"
   ```

   ClickHouse must read mode-0600 dictionary files as UID 1000; do not relax
   permissions to make a mismatched container UID work. Directory mounting is
   necessary because atomic replace changes the file inode. Do not mount the
   original SDK `e2e.key` into the DB container. Existing CA/SDK source files are
   preserved. Confirm no runtime environment sets CLICKHOUSE_NATS_TLS_SECURE=0.

3. Prepare this literal `native-nats.xml` privately, owned/readable by the
   ClickHouse UID, and keep an owner-only identical copy on pudadev:

   ```xml
   <clickhouse>
     <named_collections>
       <puda_native_nats>
         <nats_url overridable="false">tls://100.126.78.55:4222</nats_url>
         <nats_secure overridable="false">true</nats_secure>
         <nats_ca_file overridable="false">/etc/clickhouse-server/native-ca/ca.pem</nats_ca_file>
       </puda_native_nats>
     </named_collections>
   </clickhouse>
   ```

   The controller reads the same XML but `--local-ca` selects its locally
   provisioned, verified copy of the CA. The XML must be literal: no environment
   expansion, XML entities, unknown flags, or credential URLs. Optional auth
   parsing exists but authenticated broker modes are NOT integration-certified.
   Grant the installer `NAMED COLLECTION ON puda_native_nats` in addition to
   the required schema/DDL rights; the integration fixture needed explicit named
   collection privileges. Do not grant that collection or the secret database
   to analytics readers. Production least-privilege MV execution remains a gate.

4. On pudadev, use the existing locked project environment and bootstrap a
   separate local archive from the matching source; never print it:

   ```sh
   cd /home/puda/workspace/pudap/puda-logger/clickhouse/logger
   install -d -m 0700 /home/puda/.config/puda/native-control
   .venv/bin/python native_control.py bootstrap \
     --source /home/puda/workspace/pudap/puda-development-nats/secrets/diagnostic-client/e2e.key \
     --keys /home/puda/.config/puda/native-control/puda-keys.tsv
   ```

   Install the local XML, trusted CA and ClickHouse password out of band under
   that private directory. No password values are CLI arguments or environment
   requirements of this controller.

5. Keep HTTP private using a verified SSH tunnel from pudadev to the remote
   loopback DB. This is specifically for control SQL/password protection, not a
   data-message proxy. Example assumes remote DB loopback port 8123 and unused
   local port 18123; verify both first:

   ```sh
   ssh -NT -o BatchMode=yes -o StrictHostKeyChecking=yes \
     -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
     -L 127.0.0.1:18123:127.0.0.1:8123 pudadev1
   ```

   Supervise the tunnel separately. The forced-command upload key must not have
   forwarding permission. Direct remote cleartext HTTP is refused by the CLI.

6. **BLOCKED COMMAND: do not bypass the CLI gate.** After a verified fixed
   engine and code gate removal, the intended install invocation is:

   ```sh
   .venv/bin/python native_control.py install \
     --server tls://100.126.78.55:4222 --url http://127.0.0.1:18123 \
     --user native_admin --password-file /home/puda/.config/puda/native-control/clickhouse.password \
     --transport /home/puda/.config/puda/native-control/native-nats.xml \
     --local-ca /home/puda/.config/puda/native-control/ca.pem \
     --keys /home/puda/.config/puda/native-control/puda-keys.tsv \
     --remote-target pudadev1-key-sync \
     --remote-key-path /var/lib/clickhouse/user_files/native/puda-keys.tsv
   ```

   Installation uploads/reads back the dictionary, provisions only compatible
   additive logger pull durables, then creates native objects. It is not
   transactional/idempotent; inspect a partial failure, never blindly drop the
   native durables. Existing split-schema tables must already exist.

7. For rotation, run the same command with **`sync` instead of `install`** as an
   agent-local systemd `Type=oneshot` service with `UMask=0077`, bounded timeout
   and a non-overlapping timer (for example OnUnitActiveSec=5s). Alert on nonzero
   exit and stale last-success. Never run competing timers/bootstrap writers.
   Systemd does not restart an already-running oneshot when its timer fires.
   Polling limits rotation detection latency; Core messages in that gap can be
   lost, while durable responses remain pending on missing keys.

## Transfer and failure contract

The controller authenticates encrypted KV using existing trusted replay keys,
merges old/new keys into its private local archive, sends TSV **via SSH stdin**,
then reloads the remote dictionary through the protected HTTP tunnel. The helper
validates key lengths/IDs/duplicates, uses a 0600 temporary file and fsync+atomic
replace in its fixed private directory, reads the installed target back and
returns only a SHA256 digest. The controller verifies that digest before reload.
No key bytes are in argv, SQL, normal stdout/stderr or transport config.

Transfer failure prevents reload. The local archive may already include new
keys, but retains every old key and is safe to retry. A disconnect after atomic
replace is ambiguous until retry/readback; the previously loaded dictionary
remains active until reload. Reload/count failure is fatal and requires retry;
cardinality is a health check, not cryptographic proof of the loaded set. Only
one trusted writer is supported; this is not distributed transactional rotation.

## Reproduction and verified limits

```sh
cd /home/puda/workspace/pudap/puda-logger/clickhouse/logger
export RUN_NATIVE_INTEGRATION=1
export CLICKHOUSE_TEST_BINARY=/home/puda/.hermes/cache/scratch/nats-engine-binaries/clickhouse-common-static-26.10.2.103/usr/bin/clickhouse
export NATS_TEST_BINARY=/home/puda/.hermes/cache/scratch/nats-engine-binaries/nats-server-v2.15.2-linux-amd64/nats-server
.venv/bin/python -m pytest tests/ -q -rx
# This MUST currently fail; do not call an xfailed security gate a pass:
.venv/bin/python -m pytest tests/test_native_tls.py -k bad-name --runxfail -q
```

Full suite observed: **80 passed, 1 strict xfailed** (hostname security gate),
plus upstream nats-py Python-3.14 deprecation warnings. TLS tests exercise real
native ingestion, Limits/Interest independent ACK retention during actual target
constraint failures, recovery, encrypted KV rotation and remote-path dictionary
reload. The SSH command's private-stdin/strict-host-key/readback behavior is unit
tested; integration runs the real helper with separate local/server files while
substituting the SSH hop. **No real SSH deployment, forced-key restriction,
container mounts, live CA, production ACL, reconnect-name verification or live
publisher cutover was tested here.** Preserve these as explicit acceptance gates.
