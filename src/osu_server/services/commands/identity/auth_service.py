"""登録とログインのidentity workflowをオーケストレーションするserviceを提供する."""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from osu_server.domain.identity.authentication import (
    LoginResponse,
    LoginResult,
    RegistrationForm,
    RegistrationResult,
)
from osu_server.domain.identity.passwords import (
    PASSWORD_COMPROMISED_MESSAGE,
    validate_plain_password,
)
from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.identity.users import User

if TYPE_CHECKING:
    from osu_server.domain.identity.authentication import LoginRequest
    from osu_server.repositories.interfaces.queries.roles import RoleQueryRepository
    from osu_server.repositories.interfaces.queries.users import UserQueryRepository
    from osu_server.repositories.interfaces.session_store import LoginSessionWriter
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
    from osu_server.services.queries.identity.password_service import PasswordService
    from osu_server.services.queries.identity.permission_service import PermissionService

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]

# ── Validation constants ─────────────────────────────────────────────

_USERNAME_MIN = 2
_USERNAME_MAX = 15
_USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_ -]+$")

_EMAIL_PATTERN = re.compile(r"^[^@\s]{1,200}@[^@\s.]{1,30}\.[^@.\s]{1,24}$")

_MSG_USERNAME_CHARS = (
    "Username may only contain alphanumeric characters, spaces, underscores, and hyphens."
)


class AuthService:
    """登録とログインのidentity workflowをオーケストレーションする.

    Attributes:
        _uow_factory (UnitOfWorkFactory): durable mutationを行うUnit of Workのfactory.
        _user_query_repo (UserQueryRepository): usernameとemailでユーザーを検索するrepository.
        _role_query_repo (RoleQueryRepository): default roleを読むrepository.
        _password_service (PasswordService): password検証、hash化、照合を提供するservice.
        _permission_service (PermissionService): login時のsession authorizationを計算するservice.
        _session_store (LoginSessionWriter): login成功時のactive sessionを作成するstore.
        _system_user_id (int): loginを拒否するsystem userのID.

    Notes:
        register()は検証、重複確認、password検査の後にユーザー作成とdefault role付与を
        atomicに実行する.
    """

    _uow_factory: UnitOfWorkFactory
    _user_query_repo: UserQueryRepository
    _role_query_repo: RoleQueryRepository
    _password_service: PasswordService
    _permission_service: PermissionService
    _session_store: LoginSessionWriter
    _system_user_id: int

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        user_query_repo: UserQueryRepository,
        role_query_repo: RoleQueryRepository,
        password_service: PasswordService,
        permission_service: PermissionService,
        session_store: LoginSessionWriter,
        *,
        system_user_id: int = 1,
    ) -> None:
        """登録とログインに必要な依存を初期化する.

        Args:
            uow_factory (UnitOfWorkFactory): durable mutationを行うUnit of Workのfactory.
            user_query_repo (UserQueryRepository): usernameとemailでユーザーを検索するrepository.
            role_query_repo (RoleQueryRepository): default roleを読むrepository.
            password_service (PasswordService): password検証、hash化、照合を提供するservice.
            permission_service (PermissionService): session authorizationを計算するservice.
            session_store (LoginSessionWriter): login成功時のactive sessionを作成するstore.
            system_user_id (int): loginを拒否するsystem userのID.

        """
        self._uow_factory = uow_factory
        self._user_query_repo = user_query_repo
        self._role_query_repo = role_query_repo
        self._password_service = password_service
        self._permission_service = permission_service
        self._session_store = session_store
        self._system_user_id = system_user_id

    # ── Public API ───────────────────────────────────────────────────

    async def register(
        self,
        form_data: RegistrationForm,
        check_only: bool = False,
    ) -> RegistrationResult:
        """アカウント登録を検証し、要求時はユーザーとdefault roleを作成する.

        Args:
            form_data (RegistrationForm): username、email、平文passwordを含む登録フォーム.
            check_only (bool): 永続化せず検証だけを行う場合はTrue.

        Returns:
            RegistrationResult: 登録成功またはfield別validation errorを表す結果.

        Notes:
            check_onlyではidempotent retryを成功扱いにせず、credential valueはlogへ出力しない.
        """
        errors: dict[str, list[str]] = {}

        # Phase 1: Format validation (synchronous, no I/O)
        self._validate_username_format(form_data.username, errors)
        self._validate_password_format(form_data.password, errors)
        self._validate_email_format(form_data.email, errors)

        # Phase 2: Uniqueness / disallowed checks (read-only, outside UoW)
        safe_username = User.normalize_username(form_data.username)
        await self._check_username_availability(safe_username, errors)
        await self._check_email_availability(form_data.email, errors)

        # Phase 3: Password security (HIBP + custom banned list, external I/O)
        await self._check_password_banned(form_data.password, errors)

        # Return early if any errors
        if errors:
            if not check_only and await self._is_idempotent_registration_retry(
                form_data,
                safe_username=safe_username,
                errors=errors,
            ):
                return RegistrationResult(success=True)

            failed_fields = sorted(errors)
            logger.warning(
                "registration_failed",
                username=form_data.username,
                reason="validation_errors",
                failed_fields=failed_fields,
                check_only=check_only,
            )
            return RegistrationResult(success=False, errors=errors)

        # check_only mode: validation passed, no account creation
        if check_only:
            return RegistrationResult(success=True)

        # Phase 4: Prepare password hash (expensive CPU work, outside UoW)
        password_hash = await self._password_service.prepare_password(form_data.password)
        now = datetime.now(UTC)

        user = User(
            id=0,  # auto-generated by repository
            username=form_data.username,
            safe_username=safe_username,
            email=form_data.email.lower(),
            password_hash=password_hash,
            country="XX",
            created_at=now,
            updated_at=now,
        )

        # Phase 5: Atomic user creation + role assignment inside UoW
        try:
            async with self._uow_factory() as uow:
                # Validate default role exists (consistency check inside UoW)
                default_role = await uow.roles.get_default_role()

                # Create user
                created_user = await uow.users.create(user)

                # Assign default role
                await uow.roles.assign_role(created_user.id, default_role.id)

                # Atomic commit: both user and role assignment succeed or neither
                await uow.commit()

            logger.info(
                "registration_success",
                username=form_data.username,
                user_id=created_user.id,
            )
            return RegistrationResult(success=True)

        except ValueError as exc:
            # DB unique constraint caught a concurrent duplicate registration
            msg = str(exc)
            reason = "persistence_error"
            if "safe_username" in msg:
                errors.setdefault("username", []).append("Username is already taken.")
                reason = "persistence_conflict"
            elif "email" in msg:
                errors.setdefault("email", []).append("Email address is already in use.")
                reason = "persistence_conflict"
            else:
                errors.setdefault("username", []).append("Registration failed. Please try again.")
            if reason == "persistence_conflict" and await self._is_idempotent_registration_retry(
                form_data,
                safe_username=safe_username,
                errors=errors,
            ):
                return RegistrationResult(success=True)
            logger.warning(
                "registration_failed",
                username=form_data.username,
                reason=reason,
                failed_fields=sorted(errors),
                check_only=check_only,
            )
            return RegistrationResult(success=False, errors=errors)

    async def _is_idempotent_registration_retry(
        self,
        form_data: RegistrationForm,
        *,
        safe_username: str,
        errors: dict[str, list[str]],
    ) -> bool:
        """登録再送が成功済みの同一credentialかを判定する.

        Args:
            form_data (RegistrationForm): 再送された登録フォーム.
            safe_username (str): 正規化済みusername.
            errors (dict[str, list[str]]): 直前のvalidationまたは重複検査で収集したerror.

        Returns:
            bool: 同一username、email、passwordを持つ既存ユーザーの場合はTrue.

        Notes:
            usernameまたはemailだけの重複errorがある場合にだけ既存password hashを照合する.
        """
        failed_fields = set(errors)
        if not failed_fields or failed_fields - {"email", "username"}:
            return False

        existing_user = await self._user_query_repo.get_by_safe_username(safe_username)
        if existing_user is None:
            return False

        if existing_user.email != form_data.email.lower():
            return False

        password_md5 = self._password_service.legacy_plaintext_md5(form_data.password)
        if not await self._password_service.verify(existing_user.password_hash, password_md5):
            return False

        logger.info(
            "registration_retry_confirmed",
            username=form_data.username,
            user_id=existing_user.id,
        )
        return True

    async def login(
        self,
        login_request: LoginRequest,
        *,
        country: str,
    ) -> LoginResponse | LoginResult:
        """ログインを認証し、成功時はsession情報を返す.

        Args:
            login_request (LoginRequest): パース済みのログインrequest.
            country (str): transport boundaryで解決した国コード.

        Returns:
            LoginResponse | LoginResult: 成功時のsession情報または認証失敗理由.

        Notes:
            ユーザー不在とpassword不一致は同じAUTHENTICATION_FAILEDへ正規化し、想定外の例外はSERVER_ERRORへ変換する.
        """
        try:
            return await self._do_login(login_request, country=country)
        except Exception:
            logger.error(
                "login_error",
                username=login_request.username,
                exc_info=True,
            )
            return LoginResult.SERVER_ERROR

    async def _do_login(
        self,
        login_request: LoginRequest,
        *,
        country: str,
    ) -> LoginResponse | LoginResult:
        """ログイン認証、session作成、必要時のcountry更新を実行する.

        Args:
            login_request (LoginRequest): パース済みのログインrequest.
            country (str): transport boundaryで解決した国コード.

        Returns:
            LoginResponse | LoginResult: 成功時のsession情報または認証失敗理由.

        Notes:
            collaboratorからの想定外の例外はpublic login()がSERVER_ERRORへ変換する.
        """
        # 1. ユーザー検索 (read-only, outside UoW)
        safe_username = User.normalize_username(login_request.username)
        user = await self._user_query_repo.get_by_safe_username(safe_username)
        if user is None:
            logger.warning(
                "login_failed",
                username=login_request.username,
                reason="authentication_failed",
            )
            return LoginResult.AUTHENTICATION_FAILED

        # 1.5. System user login guard
        if user.id == self._system_user_id:
            logger.warning(
                "login_failed",
                username=login_request.username,
                reason="system_user_auth_denied",
            )
            return LoginResult.AUTHENTICATION_FAILED

        # 2. パスワード照合 (argon2id hash vs MD5 hex, CPU-intensive outside UoW)
        password_ok = await self._password_service.verify(
            user.password_hash,
            login_request.password_md5,
        )
        if not password_ok:
            logger.warning(
                "login_failed",
                username=login_request.username,
                reason="authentication_failed",
            )
            return LoginResult.AUTHENTICATION_FAILED

        # 3. 権限計算 (login と refresh で共有の snapshot, read-only outside UoW)
        auth_snapshot = await self._permission_service.compute_session_authorization(user.id)
        privileges = auth_snapshot.privileges
        role_ids = auth_snapshot.role_ids

        # 4. Country 更新 (mutation inside UoW if needed)
        if country not in ("XX", user.country):
            async with self._uow_factory() as uow:
                await uow.users.update_country(user.id, country)
                await uow.commit()

        # 5. トークン生成
        token = secrets.token_urlsafe(32)

        # 6. SessionData 構築
        client = login_request.client_info
        session_data = SessionData(
            user_id=user.id,
            username=user.username,
            privileges=int(privileges),
            country=country,
            osu_version=client.osu_version,
            utc_offset=client.utc_offset,
            display_city=client.display_city,
            client_hashes=client.client_hashes,
            pm_private=client.pm_private,
            role_ids=role_ids,
        )

        # 7. セッション作成(既存セッションは SessionStore.create() が自動置換)
        await self._session_store.create(user.id, token, session_data)

        logger.info(
            "login_success",
            username=user.username,
            user_id=user.id,
        )

        # 8. LoginResponse 返却
        return LoginResponse(
            token=token,
            user=user,
            privileges=privileges,
            role_ids=role_ids,
            country=country,
            session_data=session_data,
        )

    # ── Private validation helpers ───────────────────────────────────

    @staticmethod
    def _validate_username_format(
        username: str,
        errors: dict[str, list[str]],
    ) -> None:
        """usernameの長さと文字種を検証し、errorを収集する.

        Args:
            username (str): 検証する入力username.
            errors (dict[str, list[str]]): validation errorを書き込むmutable mapping.

        Returns:
            None: 不正なusernameのerrorを必要に応じて追加し、呼び出し側へ値を返さずに完了する.
        """
        msgs: list[str] = []

        if len(username) < _USERNAME_MIN or len(username) > _USERNAME_MAX:
            msgs.append(
                f"Username must be between {_USERNAME_MIN} and {_USERNAME_MAX} characters."
            )

        if username and not _USERNAME_PATTERN.match(username):
            msgs.append(_MSG_USERNAME_CHARS)

        if " " in username and "_" in username:
            msgs.append("Username cannot contain both spaces and underscores.")

        if msgs:
            errors["username"] = msgs

    @staticmethod
    def _validate_password_format(
        password: str,
        errors: dict[str, list[str]],
    ) -> None:
        """平文passwordのpolicyを検証し、errorを収集する.

        Args:
            password (str): 検証する平文password.
            errors (dict[str, list[str]]): validation errorを書き込むmutable mapping.

        Returns:
            None: policy errorを必要に応じて追加し、呼び出し側へ値を返さずに完了する.
        """
        msgs = list(validate_plain_password(password))
        if msgs:
            errors["password"] = msgs

    @staticmethod
    def _validate_email_format(
        email: str,
        errors: dict[str, list[str]],
    ) -> None:
        """emailの形式を検証し、errorを収集する.

        Args:
            email (str): 検証する入力email.
            errors (dict[str, list[str]]): validation errorを書き込むmutable mapping.

        Returns:
            None: 不正なemailのerrorを必要に応じて追加し、呼び出し側へ値を返さずに完了する.
        """
        if not _EMAIL_PATTERN.match(email):
            errors["email"] = ["Invalid email address format."]

    async def _check_username_availability(
        self,
        safe_username: str,
        errors: dict[str, list[str]],
    ) -> None:
        """usernameの重複と禁止状態を確認し、errorを収集する.

        Args:
            safe_username (str): repository検索用に正規化したusername.
            errors (dict[str, list[str]]): availability errorを書き込むmutable mapping.

        Returns:
            None: 重複または禁止のerrorを必要に応じて追加し、呼び出し側へ値を返さずに完了する.
        """
        existing = await self._user_query_repo.get_by_safe_username(safe_username)
        if existing is not None:
            errors.setdefault("username", []).append("Username is already taken.")
            return

        if await self._user_query_repo.is_username_disallowed(safe_username):
            errors.setdefault("username", []).append("This username is not allowed.")

    async def _check_email_availability(
        self,
        email: str,
        errors: dict[str, list[str]],
    ) -> None:
        """emailの重複を確認し、errorを収集する.

        Args:
            email (str): repository検索に使用する入力email.
            errors (dict[str, list[str]]): duplicate errorを書き込むmutable mapping.

        Returns:
            None: 重複errorを必要に応じて追加し、呼び出し側へ値を返さずに完了する.
        """
        existing = await self._user_query_repo.get_by_email(email)
        if existing is not None:
            errors.setdefault("email", []).append("Email address is already in use.")

    async def _check_password_banned(
        self,
        password: str,
        errors: dict[str, list[str]],
    ) -> None:
        """漏えいまたは禁止されたpasswordを確認し、errorを収集する.

        Args:
            password (str): security serviceへ渡す平文password.
            errors (dict[str, list[str]]): compromise errorを書き込むmutable mapping.

        Returns:
            None: 禁止passwordのerrorを必要に応じて追加し、呼び出し側へ値を返さずに完了する.
        """
        if await self._password_service.is_password_banned(password):
            errors.setdefault("password", []).append(PASSWORD_COMPROMISED_MESSAGE)
