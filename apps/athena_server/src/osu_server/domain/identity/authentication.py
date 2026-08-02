"""Identity context の authentication と registration 用 value object を定義する module."""

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
    """Stable login response で client に返す結果 code を表す enum.

    Attributes:
        AUTHENTICATION_FAILED (LoginResult): credential を認証できないことを表す code.
        OLD_CLIENT (LoginResult): client version が古く login を継続できないことを表す code.
        BANNED (LoginResult): account が ban 状態であることを表す code.
        BANNED_ALT (LoginResult): 代替の ban response として扱う code.
        SERVER_ERROR (LoginResult): server 側の処理失敗を表す code.
        SUPPORTER_ONLY (LoginResult): supporter 専用の操作であることを表す code.
        PASSWORD_RESET (LoginResult): password reset が必要なことを表す code.

    Notes:
        数値は stable client と互換な wire result であり変更してはならない.
    """

    AUTHENTICATION_FAILED = -1
    OLD_CLIENT = -2
    BANNED = -3
    BANNED_ALT = -4
    SERVER_ERROR = -5
    SUPPORTER_ONLY = -6
    PASSWORD_RESET = -7


class LegacyWebAuthFailure(Enum):
    """Legacy web authentication が user を返せない理由を表す enum.

    Attributes:
        INVALID_CREDENTIALS (LegacyWebAuthFailure): credential が user と一致しない状態.
        NO_SESSION (LegacyWebAuthFailure): 有効な session を取得できない状態.
    """

    INVALID_CREDENTIALS = "invalid_credentials"
    NO_SESSION = "no_session"


@dataclass(slots=True)
class ClientInfo:
    """Login 時に stable client から受け取る実行環境情報を表す value object.

    Attributes:
        osu_version (str): client が申告した osu! version.
        utc_offset (int): client が申告した UTC offset.
        display_city (bool): city 表示を許可する client setting.
        client_hashes (str): client が送る fingerprint/hash 群の文字列表現.
        pm_private (bool): private message の受信設定.
    """

    osu_version: str
    utc_offset: int
    display_city: bool
    client_hashes: str
    pm_private: bool


@dataclass(slots=True)
class LoginRequest:
    """Authentication use case へ渡す login request を表す value object.

    Attributes:
        username (str): login を試みる表示 user name.
        password_md5 (str): stable client が送る legacy MD5 credential.
        client_info (ClientInfo): session 作成に必要な client 情報.
    """

    username: str
    password_md5: str
    client_info: ClientInfo


@dataclass(slots=True)
class LoginResponse:
    """成功した login で session と user 情報を返す value object.

    Attributes:
        token (str): 作成済み session を識別する token.
        user (User): 認証済み user の domain model.
        privileges (Privileges): login 時点で計算した server-side privilege 集合.
        role_ids (tuple[int, ...]): privileges の計算元になった role ID 群.
        country (str): user の country code.
        session_data (SessionData): volatile session store へ保存する session value.
    """

    token: str
    user: User
    privileges: Privileges
    role_ids: tuple[int, ...]
    country: str
    session_data: SessionData


@dataclass(slots=True, frozen=True)
class LegacyWebAuthResult:
    """Legacy web endpoint の authentication 解決結果を表す immutable value object.

    Attributes:
        user_id (int | None): 成功時に解決した user ID. 失敗時はNone.
        username (str | None): 成功時に解決した user name. 失敗時はNone.
        failure (LegacyWebAuthFailure | None): 失敗理由. 成功時はNone.
    """

    user_id: int | None = None
    username: str | None = None
    failure: LegacyWebAuthFailure | None = None


@dataclass(slots=True)
class RegistrationForm:
    """Registration use case が検証する入力値を表す value object.

    Attributes:
        username (str): 登録を希望する表示 user name.
        email (str): 登録を希望する email address.
        password (str): policy 検証前の plaintext password.
    """

    username: str
    email: str
    password: str


@dataclass(slots=True)
class RegistrationResult:
    """Registration の成功可否と field-level validation error を表す value object.

    Attributes:
        success (bool): registration が完了した場合はTrue.
        errors (dict[str, list[str]]): field name ごとの validation message 群.
            成功時は空の mapping.
    """

    success: bool
    errors: dict[str, list[str]] = field(default_factory=dict)


class AuthenticationError(AppError):
    """Login authentication failure を stable result code と共に伝える exception.

    Attributes:
        result (LoginResult): client response に変換する authentication failure code.
    """

    result: LoginResult

    def __init__(self, result: LoginResult) -> None:
        """Authentication failure code を保持して AppError を初期化する.

        Args:
            result (LoginResult): client response に使用する failure code.
        """
        self.result = result
        super().__init__(str(result))


class RegistrationError(AppError):
    """Registration validation の field-level message を伝える exception.

    Attributes:
        errors (dict[str, list[str]]): field name ごとの validation message 群.
    """

    errors: dict[str, list[str]]

    def __init__(self, errors: dict[str, list[str]]) -> None:
        """Validation message を保持して AppError を初期化する.

        Args:
            errors (dict[str, list[str]]): field name ごとの validation message 群.
        """
        self.errors = errors
        super().__init__(str(errors))
