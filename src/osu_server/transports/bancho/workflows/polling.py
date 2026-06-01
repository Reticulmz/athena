"""Polling workflow contracts."""

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class PollingWorkflowInput:
    """Input for the Starlette-independent polling workflow."""

    token: str
    body: bytes


@dataclass(slots=True, frozen=True)
class PollingWorkflowResult:
    """Result returned by the Starlette-independent polling workflow."""

    content: bytes


__all__ = [
    "PollingWorkflowInput",
    "PollingWorkflowResult",
]
