"""Resolve one or more machine IDs for test-edge instances."""

from __future__ import annotations


def parse_id_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.replace(" ", ",").split(",") if part.strip()]


def resolve_machine_ids(
    *,
    ids: str | None = None,
    count: int | None = None,
    prefix: str = "test",
    machine_id: str | None = None,
) -> list[str]:
    """
    Prefer an explicit ID list, then a counted fleet, then a single ID.

    IDs are lowercase hyphenated names used as NATS machine_id values.
    """
    explicit = parse_id_list(ids)
    if explicit:
        return explicit
    if count is not None and count > 0:
        if count == 1 and machine_id:
            return [machine_id]
        return [f"{prefix}-{i}" for i in range(1, count + 1)]
    if machine_id:
        return [machine_id]
    return [f"{prefix}-1"]
