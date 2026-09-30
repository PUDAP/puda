"""Mark the driver method whose dict is merged into MACHINE_STATE updates.

``EdgeRunner`` calls the ``@machine_state`` method each time it publishes
machine state (startup, command start and finish, errors, shutdown) and merges
the returned dict into the payload, e.g. homed flags or deck layout. A driver
may have at most one. Passing ``state_handler`` to ``EdgeRunner`` overrides it.

The method is called on the event loop, not in a worker thread, so it must
return quickly from cached values. It is not polled; use ``@tlm_stream`` for
values that change outside commands.
"""
from __future__ import annotations

import inspect
from typing import Any, Callable, TypeVar

_MACHINE_STATE_ATTR = "__puda_machine_state__"

F = TypeVar("F")


def machine_state(func: F) -> F:
    """Merge this method's returned dict into every MACHINE_STATE update."""
    setattr(func, _MACHINE_STATE_ATTR, True)
    return func


def find_machine_state_handler(driver: Any) -> Callable[[], dict] | None:
    """Return the bound ``@machine_state`` method on *driver*, or ``None``."""
    found = [
        (name, func)
        for name, func in inspect.getmembers(type(driver), predicate=inspect.isfunction)
        if getattr(inspect.unwrap(func), _MACHINE_STATE_ATTR, False)
    ]
    if len(found) > 1:
        names = ", ".join(name for name, _ in found)
        raise ValueError(f"Only one @machine_state method is allowed; found {names}")
    if not found:
        return None
    return found[0][1].__get__(driver, type(driver))
