"""Mark driver methods that may be advertised and invoked as remote commands.

``EdgeRunner`` only exposes methods decorated with ``@command``. Inherited
serial APIs and other undecorated public methods are neither advertised nor
callable over NATS. Drivers with no ``@command`` methods fail with
``SDK_UPDATE_ERROR``.

``@safety`` optionally attaches advisory safety context to a ``@command``
method. It is published in the machine command catalog for agents; it does
not change dispatch. ``@safety`` without ``@command`` is ignored.

Command failure is exception-based. A handler that does not succeed must
raise; returning ``False`` is still a successful PUDA response whose payload
is ``{"result": false}``.
"""
from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

_COMMAND_ATTR = "__puda_command__"
_SAFETY_ATTR = "__puda_safety__"

MIN_COMMAND_SDK_VERSION = "0.0.17"
SDK_UPDATE_ERROR = f"Update SDK to {MIN_COMMAND_SDK_VERSION}"

F = TypeVar("F")


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("@safety requires and forbidden_when must be strings")
    stripped = value.strip()
    return stripped or None


@dataclass(frozen=True)
class CommandSafety:
    """Advisory safety metadata published with a ``@command`` method."""

    summary: str
    hazards: tuple[str, ...] = ()
    requires: str | None = None
    forbidden_when: str | None = None
    confirm: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "hazards": list(self.hazards),
            "requires": self.requires,
            "forbidden_when": self.forbidden_when,
            "confirm": self.confirm,
        }

    def format_lines(self) -> list[str]:
        lines = ["    safety:", f"        {self.summary}"]
        if self.hazards:
            lines.append(f"        hazards: {', '.join(self.hazards)}")
        if self.requires:
            lines.append(f"        requires: {self.requires}")
        if self.forbidden_when:
            lines.append(f"        forbidden_when: {self.forbidden_when}")
        lines.append(f"        confirm: {str(self.confirm).lower()}")
        return lines


def command(func: F) -> F:
    """Mark a driver method as a remotely callable PUDA command.

    The method must raise an exception to indicate failure. Returning
    ``False`` is treated as success and serialized as ``{"result": false}``.
    """
    setattr(func, _COMMAND_ATTR, True)
    return func


def safety(
    *,
    summary: str,
    hazards: Sequence[str] | None = None,
    requires: str | None = None,
    forbidden_when: str | None = None,
    confirm: bool = False,
) -> Callable[[F], F]:
    """Attach advisory safety context to a ``@command`` method.

    All five fields are keyword-only. ``confirm`` defaults to ``False``.
    Set ``confirm=True`` so agents must prompt the operator before executing
    the command. This does not block edge dispatch. ``requires`` and
    ``forbidden_when`` are natural-language context.
    """
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("@safety requires a non-empty summary")

    meta = CommandSafety(
        summary=summary.strip(),
        hazards=tuple(hazards or ()),
        requires=_optional_text(requires),
        forbidden_when=_optional_text(forbidden_when),
        confirm=bool(confirm),
    )

    def decorator(func: F) -> F:
        setattr(func, _SAFETY_ATTR, meta)
        return func

    return decorator


def is_command(func: Any) -> bool:
    """Return True if *func* was decorated with :func:`command`."""
    return bool(getattr(inspect.unwrap(func), _COMMAND_ATTR, False))


def get_safety(func: Any) -> CommandSafety | None:
    """Return ``@safety`` metadata, or ``None`` if the method has none."""
    value = getattr(inspect.unwrap(func), _SAFETY_ATTR, None)
    return value if isinstance(value, CommandSafety) else None


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


def _split_doc(doc: str | None) -> tuple[list[str], list[str]]:
    """Split a docstring into the lead description and the remaining body."""
    if not doc:
        return [], []
    lines = doc.split("\n")
    for i, line in enumerate(lines):
        if line.strip() == "":
            return lines[:i], lines[i + 1 :]
    return lines, []


def build_command_catalog(driver: Any) -> tuple[str, list[dict[str, Any]]]:
    """Return advertised command text and a structured catalog for *driver*."""
    methods = iter_command_methods(driver)
    lines: list[str] = []
    catalog: list[dict[str, Any]] = []
    for i, (name, func) in enumerate(methods):
        signature = str(inspect.signature(func))
        doc = inspect.getdoc(func)
        meta = get_safety(func)
        summary, body = _split_doc(doc)
        lines.append(f"{name}{signature}")
        for line in summary:
            lines.append(f"    {line}")
        if meta:
            lines.extend(meta.format_lines())
        if body:
            lines.append("")
            for line in body:
                lines.append(f"    {line}")
        if i < len(methods) - 1:
            lines.append("")
        catalog.append(
            {
                "name": name,
                "signature": signature,
                "doc": doc,
                "safety": meta.to_dict() if meta else None,
            }
        )
    return "\n".join(lines), catalog
