"""Integration connection checks.

Each integration module exposes a ``check_connection()`` function that
returns a :class:`CheckResult`. The public helpers here define that
result type and the ``STATUS_*`` constants shared across modules.
"""

from __future__ import annotations

from dataclasses import dataclass

STATUS_OK = "ok"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"


@dataclass
class CheckResult:
    """Structured outcome of a single integration connection check.

    Attributes:
        name: Human-readable integration name.
        status: One of ``ok``, ``failed`` or ``skipped``.
        detail: Short human-readable explanation of the outcome.
    """

    name: str
    status: str
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK

    @property
    def failed(self) -> bool:
        return self.status == STATUS_FAILED

    @property
    def skipped(self) -> bool:
        return self.status == STATUS_SKIPPED


__all__ = [
    "CheckResult",
    "STATUS_OK",
    "STATUS_FAILED",
    "STATUS_SKIPPED",
]
