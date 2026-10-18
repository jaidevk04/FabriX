"""Bounded public-text streaming with redaction across SDK token boundaries."""

import os
import re
from collections.abc import Callable


class PublicTextStream:
    def __init__(self, emit: Callable[[str], None]) -> None:
        self.emit = emit
        self.secrets = [
            value
            for name, value in os.environ.items()
            if len(value) >= 4
            and any(word in name.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
        ]
        self.hold = max([64] + [len(value) for value in self.secrets])
        self.pending = ""
        self.total = 0

    def push(self, text: str, *, final: bool = False) -> None:
        self.total += len(text)
        if self.total > 50000:
            raise RuntimeError("Public response exceeded stream budget")
        self.pending += text
        for secret in self.secrets:
            self.pending = self.pending.replace(secret, "[REDACTED]")
        self.pending = re.sub(r"AIza[\w-]{35}", "[REDACTED]", self.pending)
        cut = len(self.pending) if final else max(0, len(self.pending) - self.hold)
        if cut:
            self.emit(self.pending[:cut])
            self.pending = self.pending[cut:]
