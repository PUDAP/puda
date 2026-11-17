---
name: puda-database
description: Run ad-hoc SQL and schema inspection on a PUDA project's puda.db via `puda db`.
---

# Database Query

Run from the PUDA project root.

1. **Consult the schema first:** `puda db schema` prints tables, columns, and types. Do not assume table or column names.
2. **Execute SQL:** `puda db exec "<SQL>"` runs a single statement and prints JSON. Escape internal quotes for your shell.
3. **Parse output:** read the result to confirm success or use the data in later steps.

```bash
puda db exec "SELECT * FROM command_log WHERE command_name='start'"
```

Command response data is stored in `command_log.payload` at `payload["response"]["data"]`; confirm its shape with `puda machine commands <machine_id> --command <name>`.
