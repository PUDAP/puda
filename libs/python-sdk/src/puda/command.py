"""Mark driver methods that may be advertised and invoked as remote commands.

``EdgeRunner`` only exposes methods decorated with ``@command``. Inherited
serial APIs and other undecorated public methods are neither advertised nor
callable over NATS. Drivers with no ``@command`` methods fail with
``SDK_UPDATE_ERROR``.

Command failure is exception-based. A handler that does not succeed must
raise; returning ``False`` is still a successful PUDA response whose payload
is ``{"result": false}``.
"""
from __future__ import annotations

import inspect
from typing import Any, TypeVar

_COMMAND_ATTR = "__puda_command__"

MIN_COMMAND_SDK_VERSION = "0.0.17"
SDK_UPDATE_ERROR = f"Update SDK to {MIN_COMMAND_SDK_VERSION}"

F = TypeVar("F")


def command(func: F) -> F:
    """Mark a driver method as a remotely callable PUDA command.

    The method must raise an exception to indicate failure. Returning
    ``False`` is treated as success and serialized as ``{"result": false}``.
    """
    setattr(func, _COMMAND_ATTR, True)
    return func


def is_command(func: Any) -> bool:
    """Return True if *func* was decorated with :func:`command`."""
    return bool(getattr(inspect.unwrap(func), _COMMAND_ATTR, False))


def iter_command_methods(driver: Any) -> list[tuple[str, Any]]:
    """Return ``(name, function)`` pairs for ``@command`` methods on *driver*."""
    cls = type(driver)
    return [
        (name, func)
        for name, func in inspect.getmembers(cls, predicate=inspect.isfunction)
        if not name.startswith("_") and is_command(func)
    ]


def resolve_command_names(driver: Any) -> frozenset[str]:
    """Return the names of ``@command`` methods on *driver*."""
    return frozenset(name for name, _ in iter_command_methods(driver))


def require_command_names(driver: Any) -> frozenset[str]:
    """Return ``@command`` names, or raise if the driver has none."""
    names = resolve_command_names(driver)
    if not names:
        raise RuntimeError(SDK_UPDATE_ERROR)
    return names
