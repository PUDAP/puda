# System model and gate record

## Layers

```text
operator/agent -> PUDA CLI/project -> NATS -> edge service -> driver -> controller -> mechanism -> labware
```

Diagnose left to right. Never use evidence from one layer to assert another layer is healthy.

## Intake

Record: site, host, operator, tool, model, machine ID, driver repository/ref, controller transport/address, NATS owner/endpoints, physical hazards, and rollback owner.

## Gate states

Use `NOT_STARTED`, `PASS`, `FAIL`, `BLOCKED`, or `NOT_APPLICABLE`. A gate passes only with timestamped evidence. If evidence is stale, re-run discovery.
