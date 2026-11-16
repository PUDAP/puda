# Edge command safety metadata

## `@safety`

Attach `@safety` to a `@command` method to publish advisory context in the command catalog. It does not block edge dispatch. `@safety` without `@command` is ignored.

All five fields are keyword-only. Do not add others.

| Field | Required | Role |
|---|---|---|
| `summary` | yes | Headline of the risk |
| `hazards` | no | Short tags such as `collision`, `thermal` |
| `requires` | no | Preconditions; agents insert earlier steps or ask first |
| `forbidden_when` | no | Situations where the command must not be used |
| `confirm` | no | Operator `yes` gate. Defaults to `false`. Set `true` to opt in |

Do not repeat the same sentence across fields. `summary` names the risk; `requires` is the precondition; `forbidden_when` is the veto; `confirm=True` is the prompt. Do not put "confirm…" in `summary`.

```python
@command
@safety(
    summary="Collision risk from unhomed motion or an occupied workspace.",
    hazards=["collision"],
    requires="Machine must just have been homed.",
    forbidden_when="Do not move if the workspace is occupied or human movement is detected.",
    confirm=True,
)
def move_to(self, x: float, y: float, z: float) -> dict:
    ...
```

Omit `@safety` on read-only or harmless commands (`get_position`, `echo`). Use `confirm=True` for motion, chemical mixing, heat, pressure, or other irreversible hardware actions.
