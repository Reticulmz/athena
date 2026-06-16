"""Identity command use-case package."""

from osu_server.services.commands.identity.change_password import (
    ChangeUserPasswordCommand,
    ChangeUserPasswordCommandInput,
    ChangeUserPasswordCommandResult,
    ChangeUserPasswordCommandUseCase,
    ChangeUserPasswordStatus,
)
from osu_server.services.commands.identity.change_role import (
    ChangeUserRoleCommand,
    ChangeUserRoleCommandInput,
    ChangeUserRoleCommandResult,
    ChangeUserRoleCommandUseCase,
    ChangeUserRoleStatus,
)
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
from osu_server.services.commands.identity.session_authorization_service import (
    SessionAuthorizationService,
)

__all__ = [
    "ChangeUserPasswordCommand",
    "ChangeUserPasswordCommandInput",
    "ChangeUserPasswordCommandResult",
    "ChangeUserPasswordCommandUseCase",
    "ChangeUserPasswordStatus",
    "ChangeUserRoleCommand",
    "ChangeUserRoleCommandInput",
    "ChangeUserRoleCommandResult",
    "ChangeUserRoleCommandUseCase",
    "ChangeUserRoleStatus",
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
    "SessionAuthorizationService",
]
