---
name: puda-deployment
description: Install, commission, transfer, and troubleshoot PUDA edge deployments using readiness gates. Use for host, NATS, controller, labware, and deployment-log work.
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

All deployment code and configuration lives in one deployment monorepo. Before adding any edge, service, or skill, read [references/deployment-monorepo.md](references/deployment-monorepo.md): copy templates in as plain folders, never `git clone` them into the repository or leave a nested `.git`.

Do not use deployment as permission to move hardware. Motion, homing, gripping, or process commands require separate authorization and a clear workspace.

## Progressive gate sequence

Read only the reference for the current gate or symptom; load later gates when earlier ones pass.

1. **System model:** Read [references/system-and-gates.md](references/system-and-gates.md). Record site, host, tool, machine ID, controller transport, and owners in copies of [site-profile.yaml](templates/site-profile.yaml) and [machine-profile.yaml](templates/machine-profile.yaml).
2. **Host:** Run [scripts/preflight.sh](scripts/preflight.sh). Verify required commands, Docker access, clock, disk, and permissions.
3. **Network/NATS:** Read [references/network-and-nats.md](references/network-and-nats.md), run the read-only inspectors [inspect-network.sh](scripts/inspect-network.sh) and [inspect-nats.sh](scripts/inspect-nats.sh), and prove host-to-controller and client-to-broker routes separately. `puda healthcheck` must report `ok`; on failure use network-and-nats.md.
4. **PUDA:** Read [references/puda-cli-project.md](references/puda-cli-project.md). Verify CLI version, identity, skills, project root, and that `puda healthcheck` reports `ok` for the configured NATS endpoints.
5. **Source/package:** Read [references/deployment-monorepo.md](references/deployment-monorepo.md) and [references/edge-packaging.md](references/edge-packaging.md). Verify the deployment monorepo has no nested `.git`, then repository access, clean Git state, Python/uv workspace packaging, Docker context, and environment loading.
6. **Edge readiness:** Start/recreate only after configuration review; inspect with [inspect-edge.sh](scripts/inspect-edge.sh). Require driver initialized → NATS connected → command consumers ready → acceptable queue state → fresh discovery/state.
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

Copy [templates/deployment-record.md](templates/deployment-record.md) before starting. Append actions and actual outputs as work proceeds. Use [templates/incident-record.md](templates/incident-record.md) when a command times out, is interrupted, or produces uncertain physical state. Redact secrets and never rewrite history to hide failed attempts.

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
8. A template cloned into the deployment monorepo creates a nested `.git`; the parent repository then tracks nothing inside it. Copy templates as plain folders.
