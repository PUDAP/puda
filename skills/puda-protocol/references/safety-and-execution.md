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
- For agent-driven execution, start `puda protocol run` with `terminal(background=true, pty=true, watch_patterns=["Type yes to continue step"])`. When the prompt appears, inspect the process output, show the complete command and safety context to the operator, and wait. After explicit approval, continue with `process(action="submit", data="yes")`. If permission is denied, submit any value other than `yes` or terminate the process. Parallel commands at the same step are displayed together and use one confirmation covering every safety-tagged command and machine in that step.

## Troubleshooting

- **RUN_ID_MISMATCH** when sending a protocol file: run `puda machine reset <machine_id>` to reset the machine, then send the protocol again.
