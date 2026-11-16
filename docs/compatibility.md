# CLI / Python SDK compatibility

The repository-root `compatibility.json` is one array of CLI/Python SDK range
rules, with no duplicated per-release lists or named groups. **Every `min` and
`max` is inclusive**, for both CLI and SDK:

```json
{
  "compatibility": [
    {
      "cli": {"min": "0.0.0", "max": "0.0.36"},
      "python_sdk": {"min": "0.0.15", "max": "0.0.16"}
    },
    {
      "cli": {"min": "0.1.0", "max": "0.1.6"},
      "python_sdk": {"min": "0.0.17", "max": "0.0.22"}
    }
  ]
}
```

The legacy rule is **user-declared compatibility, not runtime-tested legacy
qualification**. The user identifies CLI 0.0.36 / SDK 0.0.16 as the last compatible
legacy boundary before CLI 0.1.0 / SDK 0.0.17. Lower bounds scope this declaration
to published history: the retained registry inventory in
`compatibility-history.json` starts at CLI v0.0.0 and SDK 0.0.15. We do not invent
an SDK 0.0.0 start or promise compatibility before the inventoried artifacts.

The modern rule declares CLI 0.1.0 through pending 0.1.6 with SDK 0.0.17 through
0.0.22. This is **declared compatibility within bounds, not exhaustive per-version
qualification**. Historical software-only checks observed SDK 0.0.17, 0.0.18,
0.0.19, 0.0.21 and locally built pending 0.0.22. SDK 0.0.20 was not published or
tested; the range nevertheless implies support for a stable 0.0.20 report.
It does not create a published artifact or qualification result. The modern SDK
maximum remains 0.0.22, not the illustrative future 0.1.0 boundary.

Only stable three-component numeric versions are evaluated. Prerelease/dev/local
CLI or SDK reports remain unknown, including prerelease tags numerically between
stable endpoints. No matching CLI rule means **unknown**. For a matching CLI,
the supported SDK set is the **union** of its matching rules; stable SDKs outside
that union are **unsupported** (advisory, not proof of runtime failure). Gaps
between SDK ranges are not filled. Both bounds are required: missing, null,
malformed or inverted CLI/SDK bounds invalidate the policy and yield unknown,
never unbounded or partially approved. A singleton range supports one version.

[Historical qualification evidence](compatibility-history.md) is unchanged;
its old policy snapshot and measured outcomes are historical facts, not the
current declaration. SDK 0.0.17 requires a driver-provided reset method. Evidence
covers bounded **plaintext command/discovery and single-machine protocol** scope,
not universal deployment compatibility. Encryption/TLS, key rotation,
cross-gateway operation, telemetry consumers and physical hardware remain
unqualified. Old binaries do not acquire advisories or this policy retroactively.

## Advisory behavior

- `puda machine list`, `puda machine info`, and `puda healthcheck` check each
  successful pong's existing `sdk_version`. The installed local Python package
  is irrelevant; neither `pip` nor a Python interpreter is invoked by the CLI.
- A stable version inside the inclusive range is silent. A well-formed stable
  version below `min` or above `max` emits **outside the supported range** on
  stderr, with actionable guidance to choose a version within those bounds.
  This is an advisory, not a claim of proven incompatibility.
- Missing, malformed, prerelease, local, or development SDK version strings
  emit **compatibility unknown**. Development CLI builds and unmatched CLI policy
  ranges also report unknown. Stable versions must have three decimal
  components with no leading zeroes. Comparison is numeric by major, minor,
  then patch (not lexical ordering of version strings), without integer overflow. Only the CLI release tag may have a single
  `v` prefix; SDK reports are not trimmed, normalized, or coerced.
- Offline/non-pong results and an empty discovery result generate no compatibility
  warning. A mixed info result can warn for its responding edges while retaining
  its original nonzero exit status for nonresponders.
- JSON and human-readable stdout are unchanged. Advisory writes cannot fail a
  command, even if stderr is unavailable. Existing discovery/output errors are
  retained. These inspection commands add no execution gates, machine operations,
  SDK wire fields, policy-network requests, or automatic updates. Only the update
  preflight below fetches target-release compatibility metadata.
- Healthcheck remains the existing top-level NATS server/cluster/gateway and
  JetStream check. After writing its unchanged report, it broadcasts the existing
  fleet ping through the active profile and checks all unique valid pongs during
  the `--timeout` window (default 2s). It never uses stored machine states.
  Offline edges are not evaluated. Empty discovery and discovery errors produce
  a stderr-only **not checked** diagnostic, not a claim of compatibility; neither
  changes the NATS report or exit status. This is not an exhaustive inventory.
- The `machine ping` alias has been removed; use `machine info`. The protocol
  ping transport is unchanged.
- Other paths (`machine commands`, `machine run`, protocol execution, watch,
  etc.) do not emit these advisories. A warning never changes the
  existing safety confirmation or SDK run-state requirements.

## Update preflight

`puda update [version]` resolves the target through the existing GitHub release
lookup, then checks SDK compatibility **before the existing confirmation and
before binary download/replacement**. The `--version` form behaves identically.
Already-on-release returns without fetching compatibility metadata or discovering
edges. The background update notifier remains check-only: it does not ping edges
or fetch policy. There is no new `--check` flag.

The target policy is **not** inferred from the installed CLI's embedded map:

1. Use the exact `tag_name` returned by release lookup in the fixed updater
   repository, `PUDAP/puda`; reject malformed tags rather than normalize them.
2. Read GitHub's `/git/ref/tags/<tag>` and peel annotated tag objects to a commit
   (at most five tag objects). Lightweight tags resolve directly to a commit.
3. Fetch repository-root `compatibility.json` via `/contents/compatibility.json`
   with `ref=<40-character commit SHA>`. Metadata requests have a shared 10-second
   deadline, a 1 MiB response limit, and refuse redirects. No `main`, latest-tag,
   local-file, or bundled-policy fallback is allowed.

The current GoReleaser configuration publishes platform archives and checksums,
not a dedicated compatibility asset. Source-at-commit therefore supplies the
policy without changing release packaging. Trust is the existing updater's
fixed GitHub repository over HTTPS. Pinning makes the content immutable after
tag resolution, but tags can be moved before resolution; this is **not** a
cryptographic attestation that the published binary was built from that commit.
The existing archive checksum verification and replacement flow are unchanged.
A release whose tagged source lacks this file cannot be certified by this check.

The active profile supplies the NATS connection (including existing TLS/E2EE
setup). A fresh fleet ping collects unique pongs for two seconds; connection
attempts also have a two-second timeout per configured server and no reconnect.
Only responders are evaluated, never stored machine state. Offline, late, or
interrupted discovery is not evidence that all connected machines are compatible.

Stderr identifies each affected machine ID, its reported installed Python SDK,
the target CLI, and the target's inclusive supported range to **upgrade/change**
to. A version supported by the installed CLI but outside the target range is labeled
**newly unsupported by target**; an existing out-of-range pair is labeled separately.
An unknown current policy cannot establish whether the update introduced a
mismatch. Out of range means undeclared support, not proven runtime failure.
Unknown/dev SDK reports remain unknown even when the target declares bounds.
Unknown bounds provide no invented upgrade recommendation. Older exact-list
metadata has no bounds and therefore remains unknown; it is not reinterpreted
or used as a fallback range.

Missing/invalid target rules, metadata failure, absent configuration, failed
NATS discovery, and zero responders produce explicit unknown/not-checked warnings.
Metadata failure still permits discovery and per-responder unknown diagnostics.
Warnings do not gate the update: existing confirmations, refusal/EOF behavior,
downgrade prompts and `--yes` behavior remain intact. `--yes` skips prompts, not
preflight. There is no hidden override and no SDK installation or machine control.
Stdout retains the updater's existing text contract; list/info JSON and healthcheck
schema/status remain unchanged.

Implementation: root `compatibility.Policy.Evaluate` is the shared pure evaluator;
`Result.Warning` formats guidance. CLI `writeCompatibilityWarnings` handles live
pong selection/deduplication and optional current-vs-target classification;
`writeFleetCompatibility` shares discovery between healthcheck and update.
`internal/update/compatibility.go` owns the bounded target-source fetch, while the
updater invokes the CLI preflight callback only after resolving a different release.

## Single source and builds

The small root Go module embeds `compatibility.json` from the same directory.
`apps/cli/go.mod` references it through `replace github.com/PUDAP/puda => ../..`.
There is no generated or copied map, runtime file lookup, or `go:embed ../...`.
Build from the repository checkout (including its root), not a detached copy of
`apps/cli`. A built/released binary is standalone and needs no JSON alongside it.
The local replacement means version-suffixed `go install ...@version` is not a
supported source-install route; use released binaries or build the full checkout.

Run all three module suites, since nested Go modules are independent:

```sh
go test ./... && go vet ./...
(cd apps/cli && go test ./... && go vet ./...)
(cd apps/loadgen && go test ./... && go vet ./...)
```

## Reproducible isolated contract checks

`apps/cli/tests/test_python_sdk_contract.py` uses the **installed** SDK in the
selected Python interpreter, the real compiled CLI, and a fresh loopback-only
JetStream broker. It creates disposable configuration and storage under `TMPDIR`,
disables the CLI update notifier, and uses only a software driver. It never uses
an installed PUDA profile or connects to physical hardware.

```sh
# Use a scratch directory and isolated environments; do not sync the workspace.
export TMPDIR=/path/to/scratch
uv venv "$TMPDIR/puda-sdk-021"
uv pip install --python "$TMPDIR/puda-sdk-021/bin/python" 'puda==0.0.21' pytest
uv venv "$TMPDIR/puda-sdk-022"
uv pip install --python "$TMPDIR/puda-sdk-022/bin/python" ./libs/python-sdk pytest
(cd apps/cli && go build \
  -ldflags '-X github.com/PUDAP/puda/apps/cli/internal/cli.Version=0.1.6' \
  -o "$TMPDIR/puda-compat-cli" ./cmd/puda)
export PUDA_TEST_CLI="$TMPDIR/puda-compat-cli"
export PUDA_TEST_NATS_SERVER=/absolute/path/to/nats-server
for v in 021 022; do
  "$TMPDIR/puda-sdk-$v/bin/python" -m unittest discover \
    -s apps/cli/tests -p test_python_sdk_contract.py -v
done
```

Earlier isolated qualification evidence (before removal of the alias):

- SDK 0.0.21 installed from the package index: **2 loopback contract tests passed**;
  **27 command allowlist/processor, ping, and execution-state tests passed**.
- SDK 0.0.22 built from the pending local SDK source: **2 loopback contract tests
  passed**; **93 SDK tests passed**.
- Each earlier loopback run exercised actual list/info discovery (and the
  since-removed ping alias), version reporting,
  unknown-version warnings, no-pong and partial-response exit behavior, command
  catalog retrieval, immediate START, safety-confirmation refusal, queued typed
  parameters plus kwargs, successful driver dispatch and CLI response correlation,
  intentional driver-failure propagation, and immediate RESET.
- The loopback harness initially exposed the existing requirement to send START
  before queued commands; the final test follows that lifecycle rather than
  weakening it. This is not a compatibility regression or an execution bypass.

The root policy test verifies declared rule endpoints, legacy/modern boundaries and range union semantics.
Independent unit cases retain separate fixture policies to prove supported
silence, out-of-range warnings, and unknown-version handling. Update regression
fixtures deliberately use an out-of-range synthetic SDK, rather than treating
0.0.21/0.0.22 as inherently mismatched. The Python contract harness reads the
checked-in map and tested binary's `--version`. Build from the same checkout
so its embedded policy matches the harness input. With CLI 0.1.6, both 0.0.21
and 0.0.22 are within the declared range; both real-SDK suites were rerun after this change.
See the historical report for artifact hashes, broader contract coverage, and
remaining gaps; earlier checks below predate that qualification.

After the consistency fix, the rebuilt CLI 0.1.6 passed both current loopback
contract tests with each existing isolated SDK environment (0.0.21 and locally
built 0.0.22). Root, CLI, and loadgen module tests and vet passed, as did the
focused healthcheck/machine-info race tests with an explicit private-broker
binary. This rerun did not test hardware, live services, protocol orchestration,
or encrypted deployment interoperability and does not extend the support map.

## Update preflight regression checks

The update tests use loopback HTTP fixtures and disposable NATS brokers only.
They resolve a target whose fixture support differs from the installed map,
exercise annotated/lightweight tag pinning, missing/invalid/oversized metadata,
HTTP errors and a deadline, and verify unknown policies never approve an edge.
Command-path tests reach the existing missing-asset check after warning (no binary
is downloaded or replaced); separate cases verify preflight ordering, decline,
downgrade, `--yes`, already-latest, and background notification-only lookup.
Mixed versions, duplicate pongs, absent/dev versions, no responders and connection
timeouts cover the shared advisory layer. Existing list/info and healthcheck
output/status tests run against the same implementation.

Verification for this change used Go 1.26.2: uncached tests, vet and builds passed
in the root, CLI and loadgen modules. Focused update/healthcheck/discovery race
tests passed with an explicit private `nats-server`. The rebuilt CLI 0.1.6 also
passed both existing real-SDK loopback contract tests in each existing isolated
SDK 0.0.21 and locally built 0.0.22 environment. The intentionally failing software
driver logs an expected traceback while the failure-propagation test passes.
These checks neither use physical edges nor update the installed CLI, qualify
published release binaries, or add support declarations.

```sh
export PUDA_TEST_NATS_SERVER=/absolute/path/to/nats-server
(cd apps/cli && go test -race -count=1 ./internal/update ./internal/cli \
  -run 'TestTargetCompatibility|TestUpdate|TestReleaseNotification|TestHealthcheck|TestMachineInfoCommandMetadata|TestMachineDiscovery')
```

## Range-rule migration verification

The rule-array migration passed uncached root, CLI and loadgen Go tests, vet and
builds, plus focused update/healthcheck/discovery race tests with an explicit
private broker. The rebuilt CLI 0.1.6 passed both contract tests in each retained
isolated SDK environment (0.0.21 and local 0.0.22). Intentional software-driver
failure logs are expected in the passing failure-propagation test. Unit tests
cover both legacy and modern endpoints, the 0.0.36/0.1.0 and 0.0.16/0.0.17
cross-boundaries, numeric ordering and large components, union gaps, invalid
rules and prerelease exclusion. The schema changes were first reproduced by
failing evaluator/bundled-policy tests before implementation.

No packages were installed, no CLI was replaced, and no live hardware or services
were used. The deleted historical scratch matrix was not recreated. These checks
do not runtime-qualify the user-declared legacy rule or alter historical measured
evidence; no legacy SDK environment was rerun.

## Healthcheck regression checks

```sh
# Explicit test binary; all broker data and CLI config are disposable.
export PUDA_TEST_NATS_SERVER=/absolute/path/to/nats-server
(cd apps/cli && go test ./... && go vet ./...)
(cd apps/cli && go test -race ./internal/cli -run 'TestHealthcheck|TestMachineInfoCommandMetadata')
```

These checks exercise fresh multi-responder fleet discovery, duplicate pongs,
stale stored state exclusion, mixed stable/missing/development SDK versions,
no subscribers, silent subscribers, offline handshake timeout, disconnection
during discovery, JSON and human output, failing stderr/stdout, and unchanged
healthy/degraded/unhealthy local and gateway status/exit behavior. The removed
alias and retained `machine info` command are also checked. Broker-dependent
Go cases skip unless the binary is available explicitly or on PATH; the checks
for this change were run with the explicit binary and did not skip. This does
not qualify physical hardware, encrypted deployments, or cross-gateway routing.
