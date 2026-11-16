# Protocol operations and recovery

- Query live command names before authoring; examples can be stale.
- Validate schema, then separately review physical order, station occupancy, and collision clearance.
- A client interruption is not guaranteed physical cancellation.
- Reconstruct the last confirmed command from edge responses and motion logs, including late replies.
- Do not automatically replay pick/place/cap/decap operations with uncertain sample state.
- Resume only a reviewed uncompleted suffix after pose, gripper/clamp, queue, controller alarm, and station occupancy checks.
- Use only machine-supported reset/recovery commands.
- Keep commanded target, measured result, run ID, and evidence classification separate.
