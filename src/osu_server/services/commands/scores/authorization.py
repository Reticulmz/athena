"""スコア submission の認可状態を判定する service を提供する module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from osu_server.domain.identity.users import User

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.queries.users import UserQueryRepository
    from osu_server.repositories.interfaces.session_store import UserSessionLookup
    from osu_server.services.queries.identity.password_service import PasswordService


@dataclass(frozen=True, slots=True)
class AuthorizationContext:
    """スコア submission の認可判定結果を表す.

    Attributes:
        user_id (int): 認証対象として解決した user ID.user未検出時は0.
        username (str): 認証対象として解決したユーザー名.user未検出時はpayloadの値.
        session_valid (bool): 有効な bancho session が存在するか.
        password_valid (bool): password-md5 credential が登録済みpasswordと一致するか.
        payload_identity_match (bool): payloadのusernameとuser IDが認証対象と一致するか.
    """

    user_id: int
    username: str
    session_valid: bool
    password_valid: bool
    payload_identity_match: bool

    @property
    def authorized(self) -> bool:
        """すべての認可条件を満たすかを返す.

        Returns:
            bool: 有効session,password,payload identityがすべて一致する場合はTrue.
        """
        return self.session_valid and self.password_valid and self.payload_identity_match


class ScoreAuthorizationService:
    """スコア submission のcredential,session,identityを照合する service.

    Attributes:
        _user_repo (UserQueryRepository): payload usernameからuserを検索するquery repository.
        _password_service (PasswordService): password-md5 credentialを検証するservice.
        _session_store (UserSessionLookup): userの有効bancho sessionを検索するstore.
        _NO_PAYLOAD_USER_ID (int): stable payloadがuser IDを送らないことを表すsentinel.

    Notes:
        raw credentialは記録せず,test credentialはcomposition boundaryのtest doubleから与える.
    """

    _user_repo: UserQueryRepository
    _password_service: PasswordService
    _session_store: UserSessionLookup

    _NO_PAYLOAD_USER_ID: int = 0

    def __init__(
        self,
        *,
        user_repo: UserQueryRepository,
        password_service: PasswordService,
        session_store: UserSessionLookup,
    ) -> None:
        """認可判定に必要なrepositoryとserviceを設定する.

        Args:
            user_repo (UserQueryRepository): usernameからuserを検索するrepository.
            password_service (PasswordService): password-md5を検証するservice.
            session_store (UserSessionLookup): user単位のsessionを検索するstore.
        """
        self._user_repo = user_repo
        self._password_service = password_service
        self._session_store = session_store

    async def authorize_submission(
        self,
        password_md5: str,
        payload_username: str,
        payload_user_id: int,
    ) -> AuthorizationContext:
        """スコア submissionのcredential,session,payload identityを照合する.

        Args:
            password_md5 (str): stable clientから受け取ったpasswordのMD5 hex値.記録しない.
            payload_username (str): 復号済みpayloadに含まれるユーザー名.
            payload_user_id (int): 復号済みpayloadに含まれるuser ID.未送信時は0.

        Returns:
            AuthorizationContext: 個別の照合結果と総合認可状態を含むcontext.

        Notes:
            password-md5は有効なMD5 hex値であることを呼び出し側が保証する.
        """
        return await self._authorize_with_repositories(
            password_md5,
            payload_username,
            payload_user_id,
        )

    async def _authorize_with_repositories(
        self,
        password_md5: str,
        payload_username: str,
        payload_user_id: int,
    ) -> AuthorizationContext:
        """保存層のrepositoryを用いて認可情報を解決する.

        Args:
            password_md5 (str): 検証対象のpassword MD5 hex値.記録しない.
            payload_username (str): stable payloadのユーザー名.前後空白を除去して正規化する.
            payload_user_id (int): stable payloadのuser ID.0は未送信を表す.

        Returns:
            AuthorizationContext: user,password,session,identityの照合結果.

        Notes:
            userを解決できない場合も例外にはせず,すべての認可条件をFalseにしたcontextを返す.
        """
        safe_username = User.normalize_username(payload_username.strip())
        user = await self._user_repo.get_by_safe_username(safe_username)
        if user is None:
            return AuthorizationContext(
                user_id=0,
                username=payload_username,
                session_valid=False,
                password_valid=False,
                payload_identity_match=False,
            )

        password_valid = await self._password_service.verify(user.password_hash, password_md5)
        session = await self._session_store.get_by_user(user.id)
        session_valid = session is not None
        payload_user_id_matches = payload_user_id in (self._NO_PAYLOAD_USER_ID, user.id)
        payload_identity_match = safe_username == user.safe_username and payload_user_id_matches

        return AuthorizationContext(
            user_id=user.id,
            username=user.username,
            session_valid=session_valid,
            password_valid=password_valid,
            payload_identity_match=payload_identity_match,
        )
