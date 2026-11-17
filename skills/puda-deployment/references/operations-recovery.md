# Protocol operations and recovery

- Query live command names before authoring; examples can be stale.
- Validate schema, then separately review physical order, station occupancy, and collision clearance.
- A client interruption is not guaranteed physical cancellation.
- Reconstruct the last confirmed command from edge responses and motion logs, including late replies.
- After a failed step or RUN_ID_MISMATCH, check pose, gripper/clamp, queue, controller alarms, and station occupancy, then run `puda machine reset <machine_id>` and rerun the protocol from the failed step with `puda protocol run -f <file> --steps <N>-`.
- Use only machine-supported reset/recovery commands.
- Keep commanded target, measured result, run ID, and evidence classification separate.
