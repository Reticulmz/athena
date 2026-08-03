"""ScoreAuthorizationServiceの認可契約を検証する unit test module."""

import hashlib
from datetime import UTC, datetime

import pytest

from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.identity.users import User
from osu_server.repositories.memory.queries.users import InMemoryUserQueryRepository
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.scores.authorization import (
    AuthorizationContext,
    ScoreAuthorizationService,
)
from osu_server.services.queries.identity.password_service import PasswordService
from tests.support.fakes import make_score_authorization_service

_NOW = datetime(2026, 6, 12, tzinfo=UTC)


async def _make_repository_backed_service(
    *,
    username: str = "PlayerOne",
    password: str = "password",
    create_session: bool = True,
) -> tuple[ScoreAuthorizationService, str, int]:
    """実リポジトリと任意のsession状態を使う認可serviceを構成する.

    Args:
        username (str): 作成する認可対象userの表示名.
        password (str): userへ設定し,MD5 hexへ変換する平文password.
        create_session (bool): user用の有効sessionを作成するか.

    Returns:
        tuple[ScoreAuthorizationService, str, int]: 構成済みservice, 検証用password MD5 hex,
            作成済みuser ID.
    """
    uow_factory = InMemoryUnitOfWorkFactory()
    user_repo = InMemoryUserQueryRepository(uow_factory)
    password_service = PasswordService(hibp_client=None, banned_passwords=[])
    session_store = InMemorySessionStore()

    password_md5 = hashlib.md5(password.encode()).hexdigest()
    async with uow_factory() as uow:
        user = await uow.users.create(
            User(
                id=0,
                username=username,
                safe_username=User.normalize_username(username),
                email="player@example.com",
                password_hash=await password_service.hash(password_md5),
                country="JP",
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        await uow.commit()
    if create_session:
        await session_store.create(
            user.id,
            f"token-{user.id}",
            SessionData(
                user_id=user.id,
                username=user.username,
                privileges=1,
                country="JP",
                osu_version="20260412",
                utc_offset=9,
                display_city=False,
                client_hashes="",
                pm_private=False,
            ),
        )

    return (
        ScoreAuthorizationService(
            user_repo=user_repo,
            password_service=password_service,
            session_store=session_store,
        ),
        password_md5,
        user.id,
    )


@pytest.fixture
def service() -> ScoreAuthorizationService:
    """既定の有効sessionを持つ認可serviceを提供する fixture.

    Returns:
        ScoreAuthorizationService: password, session, payload identityがすべて一致する
            test user用service.
    """
    return make_score_authorization_service()


class TestScoreAuthorizationService:
    """ScoreAuthorizationServiceのcredential, session, identity照合を検証する test suite."""

    @pytest.mark.asyncio
    async def test_valid_authorization(self, service: ScoreAuthorizationService) -> None:
        """有効credentialと一致payloadを認可する契約を検証する.

        有効sessionを持つ既定userへ一致するpassword MD5とpayload identityを渡し,
        全照合結果と認可状態がTrueになることを確認する.

        Args:
            service (ScoreAuthorizationService): 有効なtest userを返す認可service.

        Returns:
            None: 認可結果を検証して完了し,呼び出し側へ値を返さない.
        """
        result = await service.authorize_submission(
            password_md5="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            payload_username="test_user",
            payload_user_id=1000,
        )

        assert result.authorized
        assert result.user_id == 1000
        assert result.username == "test_user"
        assert result.session_valid
        assert result.password_valid
        assert result.payload_identity_match

    @pytest.mark.asyncio
    async def test_valid_authorization_without_payload_user_id(
        self, service: ScoreAuthorizationService
    ) -> None:
        """User IDを含まないstable payloadをusernameだけで認可する契約を検証する.

        payload user IDに未送信sentinelの0を渡し,
        既定userのusername照合が認可を成立させることを確認する.

        Args:
            service (ScoreAuthorizationService): 有効なtest userを返す認可service.

        Returns:
            None: user ID未送信時の認可結果を検証して完了し,呼び出し側へ値を返さない.
        """
        result = await service.authorize_submission(
            password_md5="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            payload_username="test_user",
            payload_user_id=0,
        )

        assert result.authorized
        assert result.user_id == 1000
        assert result.payload_identity_match

    @pytest.mark.asyncio
    async def test_repository_backed_authorization(self) -> None:
        """repositoryとsession storeで解決したuserを認可する契約を検証する.

        実際にin-memory repositoryへ保存し有効sessionを作成したuserのcredentialを渡し,
        保存済みidentityで認可されることを確認する.

        Returns:
            None: repository経由の認可結果を検証して完了し,呼び出し側へ値を返さない.
        """
        service, password_md5, user_id = await _make_repository_backed_service()

        result = await service.authorize_submission(
            password_md5=password_md5,
            payload_username="PlayerOne",
            payload_user_id=0,
        )

        assert result.authorized
        assert result.user_id == user_id
        assert result.username == "PlayerOne"
        assert result.password_valid
        assert result.session_valid
        assert result.payload_identity_match

    @pytest.mark.asyncio
    async def test_repository_backed_authorization_accepts_uppercase_password_md5(
        self,
    ) -> None:
        """Password MD5 hexの大文字表現を小文字表現と同じcredentialとして認可する契約を検証する.

        repositoryへ保存したpasswordのMD5 hexを大文字へ変換して渡し,
        case差だけでは認可失敗にならないことを確認する.

        Returns:
            None: 大文字MD5の認可結果を検証して完了し,呼び出し側へ値を返さない.
        """
        service, password_md5, user_id = await _make_repository_backed_service()

        result = await service.authorize_submission(
            password_md5=password_md5.upper(),
            payload_username="PlayerOne",
            payload_user_id=0,
        )

        assert result.authorized
        assert result.user_id == user_id
        assert result.password_valid

    @pytest.mark.asyncio
    async def test_repository_backed_authorization_trims_payload_username(self) -> None:
        """末尾paddingを持つstable payload usernameを正規化して認可する契約を検証する.

        保存済みusernameの末尾へ空白を付与したpayloadを渡し,空白除去後のidentityで認可されることを確認する.

        Returns:
            None: username正規化後の認可結果を検証して完了し,呼び出し側へ値を返さない.
        """
        service, password_md5, user_id = await _make_repository_backed_service()

        result = await service.authorize_submission(
            password_md5=password_md5,
            payload_username="PlayerOne ",
            payload_user_id=0,
        )

        assert result.authorized
        assert result.user_id == user_id
        assert result.username == "PlayerOne"
        assert result.password_valid
        assert result.session_valid
        assert result.payload_identity_match

    @pytest.mark.asyncio
    async def test_invalid_password_rejection(self, service: ScoreAuthorizationService) -> None:
        """無効なpassword MD5をterminalに拒否する認可契約を検証する.

        有効sessionと一致payloadを保ったまま不正credentialを渡し,password照合だけがFalseとなり認可されないことを確認する.

        Args:
            service (ScoreAuthorizationService): 有効なtest userを返す認可service.

        Returns:
            None: credential拒否結果を検証して完了し,呼び出し側へ値を返さない.
        """
        result = await service.authorize_submission(
            password_md5="invalid_hash",
            payload_username="test_user",
            payload_user_id=1000,
        )

        assert not result.authorized
        assert not result.password_valid
        assert result.session_valid

    @pytest.mark.asyncio
    async def test_no_active_session_rejection(self) -> None:
        """有効sessionがないuserを正しいpasswordでも拒否する認可契約を検証する.

        sessionを作成しない既定userへ正しいcredentialと一致payloadを渡し,session照合の失敗で認可されないことを確認する.

        Returns:
            None: session欠落時の拒否結果を検証して完了し,呼び出し側へ値を返さない.
        """
        service_without_session = make_score_authorization_service(create_session=False)
        result = await service_without_session.authorize_submission(
            password_md5="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            payload_username="test_user",
            payload_user_id=1000,
        )

        assert not result.authorized
        assert result.password_valid
        assert not result.session_valid

    @pytest.mark.asyncio
    async def test_payload_identity_mismatch_rejection(
        self, service: ScoreAuthorizationService
    ) -> None:
        """Payload identityが認証対象と異なるsubmissionを拒否する契約を検証する.

        有効credentialを渡しつつusernameとuser IDが既定userに一致しないpayloadを渡し,
        identity照合の失敗で認可されないことを確認する.

        Args:
            service (ScoreAuthorizationService): 有効なtest userを返す認可service.

        Returns:
            None: identity不一致時の拒否結果を検証して完了し,呼び出し側へ値を返さない.
        """
        result = await service.authorize_submission(
            password_md5="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            payload_username="wrong_user",
            payload_user_id=9999,
        )

        assert not result.authorized
        assert not result.payload_identity_match

    @pytest.mark.asyncio
    async def test_no_raw_credentials_logged(
        self, service: ScoreAuthorizationService, caplog: pytest.LogCaptureFixture
    ) -> None:
        """認可処理がraw password MD5をlogへ露出しない契約を検証する.

        既定userを認可し,記録されたすべてのlog messageに渡したcredentialの生値が
        含まれないことを確認する.

        Args:
            service (ScoreAuthorizationService): 認可処理を実行するservice.
            caplog (pytest.LogCaptureFixture): 認可処理中のlog recordを収集するfixture.

        Returns:
            None: credential非露出を検証して完了し,呼び出し側へ値を返さない.
        """
        password_md5 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

        _ = await service.authorize_submission(
            password_md5=password_md5,
            payload_username="test_user",
            payload_user_id=1000,
        )

        # Check no raw password in any log record
        for record in caplog.records:
            assert password_md5 not in record.message


class TestAuthorizationContext:
    """AuthorizationContextの総合認可propertyを検証する test suite."""

    def test_authorized_property_all_valid(self) -> None:
        """3つの照合条件がすべて有効なcontextを認可する契約を検証する.

        session, password, payload identityをすべてTrueにしたcontextを作成し,
        authorized propertyがTrueになることを確認する.

        Returns:
            None: 全条件成立時のproperty値を検証して完了し,呼び出し側へ値を返さない.
        """
        ctx = AuthorizationContext(
            user_id=1000,
            username="test_user",
            session_valid=True,
            password_valid=True,
            payload_identity_match=True,
        )

        assert ctx.authorized

    def test_authorized_property_session_invalid(self) -> None:
        """session照合が無効なcontextを認可しない契約を検証する.

        passwordとpayload identityを有効に保ったままsessionだけをFalseにし,
        authorized propertyがFalseになることを確認する.

        Returns:
            None: session無効時のproperty値を検証して完了し,呼び出し側へ値を返さない.
        """
        ctx = AuthorizationContext(
            user_id=1000,
            username="test_user",
            session_valid=False,
            password_valid=True,
            payload_identity_match=True,
        )

        assert not ctx.authorized

    def test_authorized_property_password_invalid(self) -> None:
        """password照合が無効なcontextを認可しない契約を検証する.

        sessionとpayload identityを有効に保ったままpasswordだけをFalseにし,
        authorized propertyがFalseになることを確認する.

        Returns:
            None: password無効時のproperty値を検証して完了し,呼び出し側へ値を返さない.
        """
        ctx = AuthorizationContext(
            user_id=1000,
            username="test_user",
            session_valid=True,
            password_valid=False,
            payload_identity_match=True,
        )

        assert not ctx.authorized

    def test_authorized_property_identity_mismatch(self) -> None:
        """Payload identityが不一致のcontextを認可しない契約を検証する.

        sessionとpasswordを有効に保ったままidentity照合だけをFalseにし,
        authorized propertyがFalseになることを確認する.

        Returns:
            None: identity不一致時のproperty値を検証して完了し,呼び出し側へ値を返さない.
        """
        ctx = AuthorizationContext(
            user_id=1000,
            username="test_user",
            session_valid=True,
            password_valid=True,
            payload_identity_match=False,
        )

        assert not ctx.authorized
