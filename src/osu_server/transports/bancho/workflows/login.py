"""Login workflow contracts."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class LoginWorkflowInput:
    """Input for the Starlette-independent login workflow."""

    body: bytes
    headers: Mapping[str, str]


@dataclass(slots=True, frozen=True)
class LoginWorkflowResult:
    """Result returned by the Starlette-independent login workflow."""

    content: bytes
    cho_token: str | None


__all__ = [
    "LoginWorkflowInput",
    "LoginWorkflowResult",
]
