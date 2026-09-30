"""Mark driver methods that are polled and published as telemetry streams.

``EdgeRunner`` calls each ``@tlm_stream`` method every ``interval`` seconds
and publishes the returned dict to ``puda.{machine_id}.tlm.stream.{name}``.
Returning ``None`` skips that sample. Streams are advertised in the ping
reply as ``tlm_streams`` so ``puda machine info`` can list them.

A method may be both a ``@command`` and a ``@tlm_stream``.
"""
from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

_TLM_STREAM_ATTR = "__puda_tlm_stream__"
_NAME_PATTERN = re.compile(r"[A-Za-z0-9_-]+")

F = TypeVar("F")


@dataclass(frozen=True)
class TlmStreamSpec:
    interval: float
    name: str | None = None


def validate_tlm_stream_name(name: str) -> str:
    """Return *name* if it is a single NATS subject token, else raise ``ValueError``."""
    if not isinstance(name, str) or not _NAME_PATTERN.fullmatch(name):
        raise ValueError(
            f"Invalid tlm stream name {name!r}: use letters, digits, '_' or '-'"
        )
    return name


def tlm_stream(interval: float, *, name: str | None = None) -> Callable[[F], F]:
    """Publish the decorated method's return value every *interval* seconds.

    Args:
        interval: Seconds between samples. Must be positive.
        name: Stream name. Defaults to the method name.
    """
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or interval <= 0:
        raise ValueError("@tlm_stream interval must be a positive number of seconds")
    if name is not None:
        validate_tlm_stream_name(name)
    spec = TlmStreamSpec(interval=float(interval), name=name)

    def decorator(func: F) -> F:
        setattr(func, _TLM_STREAM_ATTR, spec)
        return func

    return decorator


def get_tlm_stream_spec(func: Any) -> TlmStreamSpec | None:
    """Return ``@tlm_stream`` metadata, or ``None`` if the method has none."""
    value = getattr(inspect.unwrap(func), _TLM_STREAM_ATTR, None)
    return value if isinstance(value, TlmStreamSpec) else None


def iter_tlm_stream_methods(driver: Any) -> list[tuple[str, Any, TlmStreamSpec]]:
    """Return ``(stream_name, function, spec)`` for ``@tlm_stream`` methods on *driver*."""
    streams: list[tuple[str, Any, TlmStreamSpec]] = []
    seen: dict[str, str] = {}
    for attr, func in inspect.getmembers(type(driver), predicate=inspect.isfunction):
        if attr.startswith("_"):
            continue
        spec = get_tlm_stream_spec(func)
        if spec is None:
            continue
        stream_name = validate_tlm_stream_name(spec.name or attr)
        if stream_name in seen:
            raise ValueError(
                f"Duplicate tlm stream name {stream_name!r} on {seen[stream_name]} and {attr}"
            )
        seen[stream_name] = attr
        streams.append((stream_name, func, spec))
    return streams


def tlm_stream_description(func: Any) -> str | None:
    """Return the first docstring paragraph collapsed to one line."""
    doc = inspect.getdoc(func)
    if not doc:
        return None
    first_paragraph, _, _ = doc.strip().partition("\n\n")
    return " ".join(first_paragraph.split()) or None
