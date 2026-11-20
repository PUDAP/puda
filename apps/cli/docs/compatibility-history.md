# Historical CLI / Python SDK qualification

This is a **partial, evidence-backed map**, not exhaustive release certification.
All published CLI tags are inventoried; unknown pairs remain unlisted. No support
was inferred from version ordering or copied across source-hash groups.

## Registry reconciliation

Authoritative sources: GitHub `PUDAP/puda` releases and tags APIs (all pages),
and PyPI `puda` JSON release registry. The exact responses and downloaded artifact
hashes are preserved in the scratch evidence directory below. GitHub tags were
matched to locally peeled commit SHAs. Every discovered tag has CLI release
assets: none was classified as an SDK tag merely because its number matches an
SDK. In particular, CLI v0.0.22 is **not** evidence that SDK 0.0.22 was published.
The PyPI inventory contains no 0.0.20 or 0.0.22; absent versions were not invented.
CLI 0.1.6 and SDK 0.0.22 are pending working-tree artifacts.

Reconciled counts: **published_cli: 48**, **stable_cli: 43**, **prerelease_cli: 5**, **published_sdk: 7**, **policy_entries: 49**, **matrix_cells: 392**, **qualified_pairs: 35**, **contract_tests_passed: 105**, **unqualified_cells: 357**.

## Acceptance scope and limits

Each listed pair passed three real software-only tests: private loopback NATS
JetStream, disposable HOME/config/database, software driver, bounded subprocess
and broker lifetimes. Tests cover list and info (historical ping where named),
reported package version, catalog retrieval, START, safety refusal without driver
dispatch, typed parameters plus kwargs, successful response correlation, deliberate
driver failure with nonzero CLI status, RESET, and single-machine protocol
execution with automatic START/COMPLETE. No physical device or configured lab
profile was used. Released Linux x86_64 archives were checked against their
release checksum asset; PyPI wheels against registry SHA256. Other platforms
and dependency-version permutations were not tested.

**Not qualified:** TLS/E2EE, rotation, cross-gateway operation, multi-machine
protocols, telemetry consumers, physical safety, older CLI execution interfaces.
Support entries mean the bounded plaintext scope above, not these untested paths.
SDK 0.0.22's installed source was byte-compared with the pending repository source;
requalification against the immutable wheel is required after publication.

The initial protocol fixture incorrectly included explicit START/COMPLETE catalog
commands, then lacked a project configuration. Both were harness errors, corrected
without changing product code. SDK 0.0.17 rejected RESET when the driver omitted
it: this is its historical requirement, not wire incompatibility. A decorated
software reset method fixed the fixture; every pair was rerun successfully.
SDK 0.0.17 also requires a telemetry callback and lacks HostAddresses; the scratch
adapter accounts for those constructor/module differences, without mocking wire
transport. Earlier failures do not establish incompatible pairs.

## Wire evolution audit

PyPI 0.0.15 and 0.0.16 publish only the textual `commands` member from public driver
methods; 0.0.17 publishes `commands` plus a structured `catalog` from decorated
methods. CommandRequest retains name, params, kwargs, step_number, version and
machine_id across the downloaded versions: the catalog boundary alone is not a
proof that every older command pair is incompatible. 0.0.18 adds driver telemetry,
host metadata, and optional-reset behavior; 0.0.19 adds E2EE; 0.0.21 uses explicit
per-client encryption configuration. Pending 0.0.22 changes telemetry envelopes,
so command compatibility must not be represented as telemetry-reader compatibility.

The CLI source audit hashes selected machine/protocol/config/NATS Go files for all
48 tags. It identifies some identical subsets (for example v0.0.20–v0.0.23), but
that is not a complete transitive program equivalence proof. **No support entries
were extrapolated from those hashes.** CLI v0.0.0 has no `machine` command;
v0.0.20 lacks the modern run/start interface; v0.0.36 has a historical human-oriented
surface without modern safety/JSON flags. Help probes used checksum-verified
artifacts. These are missing-feature/harness-adaptation findings, not declarations
that their historical protocol paths cannot interoperate.

## Every discovered CLI release

`Q` means each exact SDK in `0.0.17, 0.0.18, 0.0.19, 0.0.21, 0.0.22` passed the
three-test plaintext suite. `U` means no pair qualified in the bounded review;
all eight inventoried/pending SDK versions remain unlisted. `RC` means additionally
the unchanged evaluator rejects prerelease CLI versions, even with an entry.

| CLI | Status | supported_versions |
|---|---|---|
| 0.1.5 | Q | 0.0.17, 0.0.18, 0.0.19, 0.0.21, 0.0.22 |
| 0.1.4 | Q | 0.0.17, 0.0.18, 0.0.19, 0.0.21, 0.0.22 |
| 0.1.3 | Q | 0.0.17, 0.0.18, 0.0.19, 0.0.21, 0.0.22 |
| 0.1.3-rc1 | RC | [] |
| 0.1.2 | Q | 0.0.17, 0.0.18, 0.0.19, 0.0.21, 0.0.22 |
| 0.1.1 | Q | 0.0.17, 0.0.18, 0.0.19, 0.0.21, 0.0.22 |
| 0.1.0 | Q | 0.0.17, 0.0.18, 0.0.19, 0.0.21, 0.0.22 |
| 0.1.0-rc4 | RC | [] |
| 0.1.0-rc3 | RC | [] |
| 0.1.0-rc2 | RC | [] |
| 0.1.0-rc1 | RC | [] |
| 0.0.36 | U | [] |
| 0.0.35 | U | [] |
| 0.0.34 | U | [] |
| 0.0.33 | U | [] |
| 0.0.32 | U | [] |
| 0.0.31 | U | [] |
| 0.0.30 | U | [] |
| 0.0.29 | U | [] |
| 0.0.28 | U | [] |
| 0.0.27 | U | [] |
| 0.0.26 | U | [] |
| 0.0.25 | U | [] |
| 0.0.24 | U | [] |
| 0.0.23 | U | [] |
| 0.0.22 | U | [] |
| 0.0.21 | U | [] |
| 0.0.20 | U | [] |
| 0.0.19 | U | [] |
| 0.0.18 | U | [] |
| 0.0.17 | U | [] |
| 0.0.16 | U | [] |
| 0.0.15 | U | [] |
| 0.0.14 | U | [] |
| 0.0.13 | U | [] |
| 0.0.12 | U | [] |
| 0.0.11 | U | [] |
| 0.0.10 | U | [] |
| 0.0.9 | U | [] |
| 0.0.8 | U | [] |
| 0.0.7 | U | [] |
| 0.0.6 | U | [] |
| 0.0.5 | U | [] |
| 0.0.4 | U | [] |
| 0.0.3 | U | [] |
| 0.0.2 | U | [] |
| 0.0.1 | U | [] |
| 0.0.0 | U | [] |
| 0.1.6 (pending) | Q | 0.0.17, 0.0.18, 0.0.19, 0.0.21, 0.0.22 |

## Every SDK version

| SDK | Classification |
|---|---|
| 0.0.15 | Published; downloaded/hash-verified/source-audited; legacy catalog, runtime pairs unqualified. |
| 0.0.16 | Published; downloaded/hash-verified/source-audited; legacy catalog, runtime pairs unqualified. |
| 0.0.17 | Published; qualified with CLI 0.1.0–0.1.6; driver reset required; plaintext only. |
| 0.0.18 | Published; qualified with CLI 0.1.0–0.1.6; plaintext only. |
| 0.0.19rc1 | Published prerelease; downloaded/hash-verified/source-audited; unqualified, evaluator reports unknown. |
| 0.0.19 | Published; qualified with CLI 0.1.0–0.1.6; plaintext only, E2EE not exercised. |
| 0.0.21 | Published; qualified with CLI 0.1.0–0.1.6; plaintext only, E2EE not exercised. |
| 0.0.22 | Pending local build, not PyPI; qualified with CLI 0.1.0–0.1.6 within scope; recheck published artifact. |

Every other combination is explicitly classified in the machine-readable matrix.
Empty lists are unfinished qualification, not proven incompatibility. The five
CLI prereleases are retained for complete inventory, without changing evaluator
semantics or falsely advertising prerelease support.

## Evidence and reproduction

Scratch evidence directory: `/home/puda/.hermes/cache/scratch/puda-historical-compat/`.
The durable summary/complete per-cell matrix is `apps/cli/docs/compatibility-history.json`.
Scratch files include raw `releases.json`, `tags.json`, `pypi.json`,
`source-audit.json`, `sdk-source-audit.json`, `cli-artifacts.json`,
`sdk-artifacts.json`, `all-contract-results.json`, and individual `contract-*.log`.
`prepare.py` downloads exact artifacts; `historical_contract.py` reuses the current
contract harness via `adapted_base.py` with documented historical API adjustments;
`run_matrix.py` exercises the six stable historical 0.1.x binaries, and
`verify.py` runs all three Go modules and the two current advisory contracts.
The stored exact hashes are the identity evidence, not the scratch directory name.
Scratch is ephemeral; retain needed artifacts before cache pruning.

The current two-test advisory suite also passes with both SDK 0.0.21 and pending
0.0.22 after rebuilding CLI 0.1.6 with the expanded map. Root policy regression was
observed failing on the old two-entry map before metadata expansion. Update tests
that assumed 0.0.21/0.0.22 were inherently unlisted were changed to independent
target-policy fixtures; product evaluator behavior and JSON schema are unchanged.

Final verification: uncached `go test -count=1 ./...` and `go vet ./...` passed
in the root, CLI and loadgen modules, with `PUDA_TEST_NATS_SERVER` explicitly set
for private-broker cases. All 35 historical/current pair runs passed three tests
(105 test executions), and the original current advisory suite passed two tests
in each of SDK 0.0.21 and local 0.0.22 (four additional executions).
The final pending CLI binary SHA256 is
`ca376ce3d8ed53f441d44c72df55c6cec13cce7cafe1eec6485bc98231fc413e`.
Installed SDK 0.0.21 Python source bytes were also compared with the downloaded,
checksum-verified wheel. `git diff --check` passed. No live installation, commit,
tag, push, publication, hardware operation, or external write was performed.
