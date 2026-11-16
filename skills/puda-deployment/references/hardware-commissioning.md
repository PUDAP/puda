# Hardware and controller commissioning

1. Confirm physical workspace and emergency-stop access.
2. Identify controller session ownership. Do not open a competing raw session while the edge owns a persistent connection.
3. Verify route and documented TCP/HTTP/serial transport.
4. Start the edge and require an explicit successful driver initialization message.
5. Use a read-only controller/machine query through the edge.
6. Inspect controller mode and alarms through the supported path.
7. Only with separate authorization, run one low-risk command and independently verify its physical result.
8. Record installation-specific output polarity, handedness/kinematic branch, units, frames, and limits.

If the command times out or is interrupted, assume physical outcome is unknown. Inspect logs/state before any retry.
