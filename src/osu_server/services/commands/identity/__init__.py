"""Identity command use-case package."""

from osu_server.services.commands.identity.login import (
    LoginCommand,
    LoginCommandInput,
    LoginCommandResult,
    LoginCommandUseCase,
)
from osu_server.services.commands.identity.registration import (
    RegisterUserCommand,
    RegisterUserCommandInput,
    RegisterUserCommandResult,
    RegisterUserCommandUseCase,
)
from osu_server.services.commands.identity.session_authorization import (
    RefreshRoleAuthorizationCommand,
    RefreshRoleAuthorizationCommandInput,
    RefreshRoleAuthorizationCommandResult,
    RefreshRoleAuthorizationCommandUseCase,
    RefreshUserAuthorizationCommand,
    RefreshUserAuthorizationCommandInput,
    RefreshUserAuthorizationCommandResult,
    RefreshUserAuthorizationCommandUseCase,
)

__all__ = [
    "LoginCommand",
    "LoginCommandInput",
    "LoginCommandResult",
    "LoginCommandUseCase",
    "RefreshRoleAuthorizationCommand",
    "RefreshRoleAuthorizationCommandInput",
    "RefreshRoleAuthorizationCommandResult",
    "RefreshRoleAuthorizationCommandUseCase",
    "RefreshUserAuthorizationCommand",
    "RefreshUserAuthorizationCommandInput",
    "RefreshUserAuthorizationCommandResult",
    "RefreshUserAuthorizationCommandUseCase",
    "RegisterUserCommand",
    "RegisterUserCommandInput",
    "RegisterUserCommandResult",
    "RegisterUserCommandUseCase",
]
