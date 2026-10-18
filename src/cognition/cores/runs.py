"""Errors for core agent runs. Stop terminates a run; it is not a budget."""

import asyncio


class RunStopped(asyncio.CancelledError):
    """The operator pressed Stop. Recorded as interrupted, then re-raised."""


class CoreBusy(ValueError):
    """A core allows one active run per plant."""
