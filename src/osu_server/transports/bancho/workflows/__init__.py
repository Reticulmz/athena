"""Bancho workflow contract exports."""

from osu_server.transports.bancho.workflows.login import (
    LoginWorkflowInput,
    LoginWorkflowResult,
)
from osu_server.transports.bancho.workflows.polling import (
    PollingWorkflowInput,
    PollingWorkflowResult,
)

__all__ = [
    "LoginWorkflowInput",
    "LoginWorkflowResult",
    "PollingWorkflowInput",
    "PollingWorkflowResult",
]
