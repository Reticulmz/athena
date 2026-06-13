"""Authentication and registration value objects for the identity context."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import TYPE_CHECKING

from osu_server.shared.errors import AppError

if TYPE_CHECKING:
    from osu_server.domain.identity.authorization import Privileges
    from osu_server.domain.identity.sessions import SessionData
    from osu_server.domain.identity.users import User


class LoginResult(IntEnum):
    AUTHENTICATION_FAILED = -1
    OLD_CLIENT = -2
    BANNED = -3
    BANNED_ALT = -4
    SERVER_ERROR = -5
    SUPPORTER_ONLY = -6
    PASSWORD_RESET = -7


class LegacyWebAuthFailure(Enum):
    INVALID_CREDENTIALS = "invalid_credentials"
    NO_SESSION = "no_session"


@dataclass(slots=True)
class ClientInfo:
    osu_version: str
    utc_offset: int
    display_city: bool
    client_hashes: str
    pm_private: bool


@dataclass(slots=True)
class LoginRequest:
    username: str
    password_md5: str
    client_info: ClientInfo


@dataclass(slots=True)
class LoginResponse:
    token: str
    user: User
    privileges: Privileges
    role_ids: tuple[int, ...]
    country: str
    session_data: SessionData


@dataclass(slots=True, frozen=True)
class LegacyWebAuthResult:
    user_id: int | None = None
    username: str | None = None
    failure: LegacyWebAuthFailure | None = None


@dataclass(slots=True)
class RegistrationForm:
    username: str
    email: str
    password: str


@dataclass(slots=True)
class RegistrationResult:
    success: bool
    errors: dict[str, list[str]] = field(default_factory=dict)


class AuthenticationError(AppError):
    """Login authentication error with a specific result code."""

    result: LoginResult

    def __init__(self, result: LoginResult) -> None:
        self.result = result
        super().__init__(str(result))


class RegistrationError(AppError):
    """Registration validation error with field-level messages."""

    errors: dict[str, list[str]]

    def __init__(self, errors: dict[str, list[str]]) -> None:
        self.errors = errors
        super().__init__(str(errors))
