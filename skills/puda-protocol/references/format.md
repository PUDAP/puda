# Protocol format

## Protocol Structure

A single protocol can contain commands for **multiple machines**. Each command specifies its own `machine_id`. Step numbers are sequential execution groups across all commands. If commands are meant to be executed in parallel, use the same `step_number`; however, `machine_id` cannot be repeated within the same parallel command group.

Top-level fields:
- `project_id`: UUID from **project.md** in the project root
- `protocol_id`: New UUID per protocol (e.g. `python -c "import uuid; print(uuid.uuid4())"`)
- `description`: Short description of what the protocol does
- `timestamp`: ISO 8601 UTC (e.g. `datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`)
- `commands`: Array of command objects (see below)

Each command:
- `step_number`: Sequential integer from 1; commands with the same value execute in parallel
- `name`: Valid command name for the specified machine, or a special command (`wait`)
- `machine_id`: Target machine id. For `wait`, omit to pause the whole protocol, or set it to pause only that machine while other machines in the same step run
- `params`: Required and optional parameters for the command
- `safety`: Required when the live command catalog advertises safety metadata; copy the structured metadata into the command unchanged. Omit for special commands

## Special commands

Special commands are handled by the CLI during `puda protocol run`. They are not sent to a machine and do not require a live command catalog or `safety`.

### `wait`

CLI-only delay. `params.seconds` is required (`>= 0`, fractional OK; `0.5` = 500ms). Never send `wait` to a machine.

```json
{"step_number": 2, "name": "wait", "machine_id": "first", "params": {"seconds": 5}}
```

Omit `machine_id` and use its own step to pause every machine. Set `machine_id` (one wait per paused machine, same `step_number` as machines that keep working) to pause only those machines. Do not also command a waiting machine in that step.

## Output Format (JSON)

```json
{
  "project_id": "<project_id>",
  "protocol_id": "<protocol_id>",
  "description": "description for this protocol",
  "timestamp": "<ISO 8601>",
  "commands": []
}
```

Each command: `step_number`, `name`, `machine_id`, `params`, plus `safety` whenever the live command catalog advertises it. For the special command `wait`, set `params.seconds`. Omit `machine_id` to pause every machine; set `machine_id` to pause only that machine while other machines at the same step run.
