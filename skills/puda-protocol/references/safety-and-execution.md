# Command safety and execution

## Command Safety

After `puda machine commands <machine_id>`, treat any `safety:` block as required planning and execution context. When a command advertises safety metadata, copy it into that command in `protocol.json`. Do not invent, summarize, weaken, or omit any safety field. The live catalog remains the source of truth; refresh the copied metadata whenever the protocol is updated.

Canonical command shape:

```json
{
  "step_number": 1,
  "machine_id": "machine-001",
  "name": "move_to",
  "params": {
    "x": 1,
    "y": 1,
    "z": 1
  },
  "safety": {
    "summary": "Confirm the workspace is clear before moving.",
    "hazards": [
      "collision"
    ],
    "requires": "Machine must just have been homed and the workspace clear.",
    "forbidden_when": "Do not move if the workspace is occupied, human movement is detected",
    "confirm": true
  }
}
```

Safety field types are fixed:

- `summary`: string
- `hazards`: array of strings
- `requires`: string
- `forbidden_when`: string
- `confirm`: boolean

- Follow `requires` in the `safety:` block as prose: insert earlier steps or ask the user before using the command.
- Follow `forbidden_when` as prose: do not use the command when that situation applies.
- If `confirm` is `true`, `puda protocol run` prints the complete command and safety object for the current step, then blocks until `yes` is entered. The AI agent must present that exact output to the operator and wait for explicit approval. Do not submit `yes` first and ask later.
- Only prompt when the catalog explicitly shows `confirm: true`. `@safety` defaults `confirm` to `false`.
- For agent-driven execution, run `puda protocol run` in a background or interactive terminal that accepts input. When it prints `Type yes to continue step <N>:`, show the operator the step's complete command and safety output, and wait. Send `yes` only after explicit approval. If permission is denied, send any other value or terminate the process. Parallel commands at the same step are displayed together and use one confirmation covering every safety-tagged command and machine in that step.

## Troubleshooting

- **RUN_ID_MISMATCH or a failed step:** inspect the machine's state (`puda machine state <machine_id>`) and the physical workspace, then run `puda machine reset <machine_id>` and rerun the protocol from the failed step with `puda protocol run -f <file> --steps <N>-` (`--steps` takes comma-separated steps or inclusive ranges, e.g. `3`, `2-5`, `4-`). Record both run IDs in the run note.
