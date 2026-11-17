---
name: puda-deployment
description: Install, commission, transfer, and troubleshoot PUDA edge deployments using readiness gates. Use for host, NATS, controller, labware, and deployment-log work.
license: MIT
metadata:
  version: "1.0.0"
  author: PUDAP
  hermes.tags: "puda, deployment, edge-driver, nats, commissioning, troubleshooting"
  hermes.related_skills: "puda, puda-edge, puda-protocol, puda-data"
---

# PUDA Deployment

## Overview

Use this skill to install a new PUDA-connected tool or diagnose an incomplete installation. Work from high-level infrastructure down to physical labware. Stop at the first failed gate; do not skip to motion to compensate for a software or connection failure.

## When to use

- Installing PUDA, NATS, a driver repository, or an edge service.
- Moving a working installation to another site or host.
- Diagnosing missing/stale machine discovery, dependency/build failures, controller errors, or alignment problems.
- Creating an installation log, incident record, or reusable SOP for a new tool.
- Exporting deployment logs and learnings as a zip for the user.

Do not use deployment as permission to move hardware. Motion, homing, gripping, or process commands require separate authorization and a clear workspace.

## Progressive gate sequence

Read only the reference for the current gate or symptom; load later gates when earlier ones pass.

1. **System model:** Read [references/system-and-gates.md](references/system-and-gates.md). Record site, host, tool, machine ID, controller transport, and owners.
2. **Host:** Run `scripts/preflight.sh`. Verify required commands, Docker access, clock, disk, and permissions.
3. **Network/NATS:** Read [references/network-and-nats.md](references/network-and-nats.md), run the read-only inspectors, and prove host-to-controller and client-to-broker routes separately. From the CLI host, run `puda healthcheck` against the active profile: it prints one JSON report with `status` `ok`/`degraded`/`unhealthy` and exits nonzero unless `ok`. Read transport causes (including TLS) in `servers[].error` and JetStream results in `jetstream.status`/`reason`. Use `--timeout <duration>` for slow links and `--human` for text.
4. **PUDA:** Read [references/puda-cli-project.md](references/puda-cli-project.md). Verify CLI version, identity (`puda config list`), skills, project root, and that `puda healthcheck` passes for the configured NATS endpoints. Its `compatibility` object (`status` `supported`/`unsupported`/`unknown`/`not_checked`; `reason` such as `nats_unreachable`, `no_responders`, `discovery_error`, or `discovery_incomplete`) is advisory only and never changes health status or exit code; it covers only edges that replied.
5. **Source/package:** Read [references/edge-packaging.md](references/edge-packaging.md). Verify repository access, clean Git state, Python/uv workspace packaging, Docker context, and environment loading.
6. **Edge readiness:** Start/recreate only after configuration review. Require driver initialized → NATS connected → command consumers ready → acceptable queue state → fresh discovery/state.
7. **Controller:** Read [references/hardware-commissioning.md](references/hardware-commissioning.md). Use one session owner, read-only communication first, then a separately authorized low-risk command.
8. **Labware:** Read [references/labware-alignment.md](references/labware-alignment.md). Calibrate approach, intermediate, and process poses with provenance and tolerances.
9. **Operations/recovery:** Read [references/operations-recovery.md](references/operations-recovery.md). Validate live command exposure, protocol schema, stop boundaries, and incident recovery.
10. **Failure lookup:** Use [references/error-catalog.md](references/error-catalog.md) by symptom; append new proven errors after resolution.

## Mandatory evidence model

Report each layer independently:

| Layer | Minimum evidence |
|---|---|
| Host | command/version/permission checks |
| Broker | listener plus `puda healthcheck` report with `status: "ok"` (exit 0) |
| PUDA | configured endpoint, project, identity, CLI output |
| Edge | logs showing driver initialization, NATS connection, subscriptions, queue state |
| Controller | valid read-only response through the owning edge session |
| Machine | authorized command result plus independent measurement when physical |
| Labware | dated alignment record, frame, tolerance, and verifier |

A heartbeat or `idle` state is not proof of controller readiness. A returned motion target is not proof of measured final pose. A digital-output acknowledgment is not proof of jaw state.

## Installation logging

Copy `templates/deployment-record.md` before starting. Append actions and actual outputs as work proceeds. Use `templates/incident-record.md` when a command times out, is interrupted, or produces uncertain physical state. Redact secrets and never rewrite history to hide failed attempts.

## Export logs and learnings

When asked for a deployment archive, read [export procedure](references/export-logs.md).

## Completion criteria

A deployment is complete only when:

- Every applicable gate is checked with fresh evidence.
- The expected machine appears with a fresh timestamp and live command registry.
- Controller communication succeeds through the edge-owned path.
- Any authorized physical commissioning result is independently verified.
- Labware coordinates have provenance and tolerance records.
- Environment templates contain placeholders, not credentials.
- Installation and unresolved risks are recorded.

## Common pitfalls

1. `localhost` in a container points to the container unless host networking is deliberate.
2. A shallow Docker healthcheck can stay green during driver retry loops.
3. PUDA login does not grant private GitHub repository access.
4. `puda protocol validate` does not prove a command is exposed by the live edge.
5. Restarting/rebuilding can change controller session or queue behavior; inspect before retrying.
6. A second controller diagnostic session may disrupt the edge-owned session.
7. Site-specific IPs, coordinates, and active-low outputs are not portable defaults.
