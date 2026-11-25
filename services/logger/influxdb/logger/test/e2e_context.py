"""Test-only E2EE contexts holding an explicit ring (no key file, no globals)."""
from puda import e2e


def ring_context(ring=None):
    context = e2e.Context()
    context._ring = ring
    return context
