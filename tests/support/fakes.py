"""testが外部I/Oなしでseamを検証するtyped fake群を提供する."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, final, override

from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.identity.users import User
from osu_server.domain.scores.decryption import DecryptedPayload
from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.payload_parser import ParsedScore, ParseError
from osu_server.domain.storage.blobs import Blob, BlobStorageBackendKind, BlobStored
from osu_server.services.commands.scores import ParsedSubmissionInput, SubmitScoreUseCase
from osu_server.services.commands.scores.authorization import ScoreAuthorizationService
from osu_server.services.queries.identity.password_service import PasswordService
from osu_server.transports.stable.web_legacy.mappers.score_submit import (
    StableScorePayloadDecryptor,
    StableScorePayloadParser,
    StableScoreSubmitDecoder,
)
from tests.support.credentials import FIXED_TEST_PASSWORD_MD5

if TYPE_CHECKING:
    from osu_server.domain.identity.sessions import SessionAuthorization
    from osu_server.domain.identity.system_users import SystemUserIdentity
    from osu_server.domain.scores.replay import Replay
    from osu_server.domain.scores.score import Score
    from osu_server.domain.scores.submission import ScoreSubmission, ScoreSubmissionState
    from osu_server.infrastructure.security.hibp import HIBPClient
    from osu_server.repositories.interfaces.queries.users import UserQueryRepository
    from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory


class FakeHIBPClient:
    """HIBPClientの漏洩照会結果を固定するtyped fakeを提供する.

    Attributes:
        compromised_passwords (set[str]): 漏洩済みとして返すplain password集合.
        calls (list[str]): 照会順に記録したplain password列.

    Notes:
        本物のnetwork通信を行わず, 指定された漏洩状態だけをsimulatorする.
    """

    def __init__(self, compromised_passwords: set[str] | None = None) -> None:
        """漏洩済みpassword集合を持つfakeを初期化する.

        Args:
            compromised_passwords (set[str] | None): 漏洩済みとして扱うplain password集合.
                Noneの場合は空集合から開始する.
        """
        self.compromised_passwords: set[str] = compromised_passwords or set()
        self.calls: list[str] = []

    async def is_password_compromised(self, password: str) -> bool:
        """指定passwordを漏洩済みとして扱うかを返す.

        Args:
            password (str): 漏洩状態を照会するplain password.

        Returns:
            bool: passwordがcompromised_passwordsに含まれる場合はTrue.

        Notes:
            照会したpasswordをcallsへ必ず追記する.
        """
        self.calls.append(password)
        return password in self.compromised_passwords


# Ensure FakeHIBPClient implements the HIBPClient protocol
_: HIBPClient = FakeHIBPClient()


@final
class ErrorRaisingUserRepository:
    """armed状態でget_by_safe_usernameだけが例外を送出するrepository fakeを提供する.

    Attributes:
        _inner (UserQueryRepository): 通常操作を委譲するrepository.
        _error (Exception): armed時のsafe username照会で送出する例外.
        _armed (bool): failure injectionを有効にしたか.

    Notes:
        AsyncMockのmonkey-patchを使わず, DB failureを再現する.
    """

    def __init__(self, inner: UserQueryRepository, error: Exception) -> None:
        """委譲先repositoryとinjectionする例外を初期化する.

        Args:
            inner (UserQueryRepository): 通常操作を委譲するrepository.
            error (Exception): arm後のsafe username照会で送出する例外.
        """
        self._inner = inner
        self._error = error
        self._armed = False

    def arm(self) -> None:
        """以降のsafe username照会で例外を送出する状態にする.

        Returns:
            None: failure injectionを有効化し, 呼び出し側へ値を返さずに完了する.
        """
        self._armed = True

    async def get_by_id(self, user_id: int) -> User | None:
        """User ID照会をinner repositoryへ委譲する.

        Args:
            user_id (int): 取得するuserの識別子.

        Returns:
            User | None: inner repositoryが返すuser. 未登録の場合はNone.
        """
        return await self._inner.get_by_id(user_id)

    async def get_by_safe_username(self, safe_username: str) -> User | None:
        """Safe username照会を委譲するか, armed時の例外を送出する.

        Args:
            safe_username (str): 取得するuserの正規化済みusername.

        Returns:
            User | None: armedでない場合にinner repositoryが返すuser. 未登録の場合はNone.
        """
        if self._armed:
            raise self._error
        return await self._inner.get_by_safe_username(safe_username)

    async def get_by_email(self, email: str) -> User | None:
        """email照会をinner repositoryへ委譲する.

        Args:
            email (str): 取得するuserのemail address.

        Returns:
            User | None: inner repositoryが返すuser. 未登録の場合はNone.
        """
        return await self._inner.get_by_email(email)

    async def is_username_disallowed(self, safe_username: str) -> bool:
        """username禁止照会をinner repositoryへ委譲する.

        Args:
            safe_username (str): 照会する正規化済みusername.

        Returns:
            bool: inner repositoryが返す禁止判定.
        """
        return await self._inner.is_username_disallowed(safe_username)


@final
class StaticScoreUserRepository:
    """score authorization test用の単一user repositoryを提供する.

    Attributes:
        _user (User): createまたは初期化で保持する唯一のuser.

    Notes:
        username禁止集合とsystem user同期は保持せず, command contractだけを満たす.
    """

    def __init__(self, user: User) -> None:
        """唯一の読み書き対象userを初期化する.

        Args:
            user (User): repositoryが最初に保持するuser.
        """
        self._user = user

    async def create(self, user: User) -> User:
        """保持userを置き換えて作成結果として返す.

        Args:
            user (User): 既存の保持userを置き換えるuser.

        Returns:
            User: 保存済みとして返す引数のuser.
        """
        self._user = user
        return user

    async def get_by_id(self, user_id: int) -> User | None:
        """保持userをIDで照会する.

        Args:
            user_id (int): 照会するuserの識別子.

        Returns:
            User | None: IDが一致する保持user. 不一致の場合はNone.
        """
        return self._user if self._user.id == user_id else None

    async def get_by_safe_username(self, safe_username: str) -> User | None:
        """保持userをsafe usernameで照会する.

        Args:
            safe_username (str): 照会する正規化済みusername.

        Returns:
            User | None: safe usernameが一致する保持user. 不一致の場合はNone.
        """
        return self._user if self._user.safe_username == safe_username else None

    async def get_by_email(self, email: str) -> User | None:
        """保持userをemail addressで照会する.

        Args:
            email (str): 照会するemail address.

        Returns:
            User | None: emailが一致する保持user. 不一致の場合はNone.
        """
        return self._user if self._user.email == email else None

    async def is_username_disallowed(self, safe_username: str) -> bool:
        """username禁止照会へ常にFalseを返す.

        Args:
            safe_username (str): 照会する正規化済みusername.

        Returns:
            bool: 常にFalse.

        Notes:
            fakeは禁止username集合を保持しない.
        """
        _ = safe_username
        return False

    async def add_disallowed_username(self, safe_username: str) -> None:
        """username禁止登録要求を副作用なしで受け入れる.

        Args:
            safe_username (str): 登録を要求する正規化済みusername.

        Returns:
            None: 値を保持せず, 呼び出し側へ値を返さずに完了する.
        """
        _ = safe_username

    async def update_country(self, user_id: int, country: str) -> None:
        """IDが一致する保持userのcountryだけを更新する.

        Args:
            user_id (int): countryを更新するuserの識別子.
            country (str): 保存するcountry code.

        Returns:
            None: 一致時にcountryを更新し, 呼び出し側へ値を返さずに完了する.
        """
        if self._user.id == user_id:
            self._user.country = country

    async def sync_system_user(self, identity: SystemUserIdentity) -> None:
        """System user同期要求を副作用なしで受け入れる.

        Args:
            identity (SystemUserIdentity): 同期を要求するsystem user identity.

        Returns:
            None: system userを保持せず, 呼び出し側へ値を返さずに完了する.
        """
        _ = identity


@final
class StaticPasswordService(PasswordService):
    """1つのpassword-md5だけを受理するPasswordService fakeを提供する.

    Attributes:
        _accepted_password_md5 (str): verifyで受理するpassword-md5 value.
    """

    def __init__(self, accepted_password_md5: str) -> None:
        """受理するpassword-md5 valueを持つfakeを初期化する.

        Args:
            accepted_password_md5 (str): verifyでTrueを返すpassword-md5 value.

        Notes:
            parent serviceへnetwork clientなし, banned passwordなしの設定を渡す.
        """
        super().__init__(hibp_client=None, banned_passwords=[])
        self._accepted_password_md5 = accepted_password_md5

    @override
    async def verify(self, hashed: str, password: str) -> bool:
        """入力passwordが固定の受理値と一致するかを返す.

        Args:
            hashed (str): interface互換のため受け取るhash値. 判定には使わない.
            password (str): 受理値と比較するpassword-md5 value.

        Returns:
            bool: passwordが初期化時の受理値に一致する場合はTrue.
        """
        _ = hashed
        return password == self._accepted_password_md5


@final
class StaticSessionStore:
    """任意のactive sessionを1つ保持するSessionStore fakeを提供する.

    Attributes:
        _session (SessionData | None): 現在保持する唯一のactive session.
        _token (str): 現在のsessionを取得するtoken.

    Notes:
        複数sessionやexpirationをmodel化せず, session store contractの最小状態だけを保持する.
    """

    def __init__(self, session: SessionData | None) -> None:
        """任意の初期active sessionからstoreを初期化する.

        Args:
            session (SessionData | None): 初期状態で保持するsession. Noneは空storeを表す.
        """
        self._session = session
        self._token = f"token-{session.user_id}" if session is not None else ""

    async def create(self, user_id: int, token: str, data: SessionData) -> None:
        """保持sessionとlookup tokenを新しい値へ置き換える.

        Args:
            user_id (int): interface互換のため受け取るowner ID. dataの値を使う.
            token (str): 以降のgetで照合するsession token.
            data (SessionData): 新しく保持するsession data.

        Returns:
            None: sessionを置き換え, 呼び出し側へ値を返さずに完了する.
        """
        _ = user_id
        self._token = token
        self._session = data

    async def get(self, token: str) -> SessionData | None:
        """tokenが一致する場合に保持sessionを返す.

        Args:
            token (str): 照会するsession token.

        Returns:
            SessionData | None: token一致時の保持session. 不一致または空storeではNone.
        """
        return self._session if self._session is not None and token == self._token else None

    async def get_by_user(self, user_id: int) -> SessionData | None:
        """User IDが一致する場合に保持sessionを返す.

        Args:
            user_id (int): 照会するsession ownerのuser ID.

        Returns:
            SessionData | None: user ID一致時の保持session. 不一致または空storeではNone.
        """
        return (
            self._session
            if self._session is not None and self._session.user_id == user_id
            else None
        )

    async def delete(self, token: str) -> None:
        """tokenが一致する場合に保持sessionを削除する.

        Args:
            token (str): 削除するsessionのtoken.

        Returns:
            None: 一致時にsessionを削除し, 呼び出し側へ値を返さずに完了する.
        """
        if token == self._token:
            self._session = None

    async def exists(self, token: str) -> bool:
        """tokenに対応する保持sessionが存在するかを返す.

        Args:
            token (str): 存在を照会するsession token.

        Returns:
            bool: 空storeでなくtokenが一致する場合はTrue.
        """
        return self._session is not None and token == self._token

    async def refresh(self, token: str) -> bool:
        """tokenが現在のsessionを参照するかだけを確認する.

        Args:
            token (str): refreshを試行するsession token.

        Returns:
            bool: tokenが現在のsessionを参照する場合はTrue.

        Notes:
            fakeはexpirationを保持しないため, session dataを変更しない.
        """
        return await self.exists(token)

    async def delete_by_user(self, user_id: int) -> None:
        """User IDが一致する場合に保持sessionを削除する.

        Args:
            user_id (int): 削除するsession ownerのuser ID.

        Returns:
            None: 一致時にsessionを削除し, 呼び出し側へ値を返さずに完了する.
        """
        if self._session is not None and self._session.user_id == user_id:
            self._session = None

    async def update_authorization(
        self,
        user_id: int,
        authorization: SessionAuthorization,
    ) -> bool:
        """一致するsessionのauthorization snapshotを更新する.

        Args:
            user_id (int): 更新するsession ownerのuser ID.
            authorization (SessionAuthorization): 保存するprivilegeとrole ID snapshot.

        Returns:
            bool: 一致するsessionを更新できた場合はTrue. 空storeまたはID不一致ではFalse.
        """
        if self._session is None or self._session.user_id != user_id:
            return False
        self._session.privileges = int(authorization.privileges)
        self._session.role_ids = authorization.role_ids
        return True

    async def update_pm_private(self, user_id: int, enabled: bool) -> bool:
        """一致するsessionのprivate message設定を更新する.

        Args:
            user_id (int): 更新するsession ownerのuser ID.
            enabled (bool): 保存するprivate message拒否設定.

        Returns:
            bool: 一致するsessionを更新できた場合はTrue. 空storeまたはID不一致ではFalse.
        """
        if self._session is None or self._session.user_id != user_id:
            return False
        self._session.pm_private = enabled
        return True

    async def list_active_sessions(self) -> list[SessionData]:
        """保持中のactive sessionを最大1件のlistで返す.

        Returns:
            list[SessionData]: 空storeでは空list. それ以外は保持sessionだけを含むlist.
        """
        return [] if self._session is None else [self._session]


def make_score_authorization_service(
    *,
    user_id: int = 1000,
    username: str = "test_user",
    password_md5: str = FIXED_TEST_PASSWORD_MD5,
    create_session: bool = True,
) -> ScoreAuthorizationService:
    """明示的なfakeでrepository-backed score authorization serviceを作る.

    Args:
        user_id (int): 静的userとsessionに設定する識別子.
        username (str): 静的userとsessionに設定するusername.
        password_md5 (str): StaticPasswordServiceが受理するpassword-md5 value.
        create_session (bool): active sessionを初期化するか.

    Returns:
        ScoreAuthorizationService: static repository, password service, session storeを持つservice.

    Notes:
        userはJP countryと固定のtest metadataを持ち, create_sessionがFalseならstoreは空である.
    """
    now = datetime.now(UTC)
    user = User(
        id=user_id,
        username=username,
        safe_username=User.normalize_username(username),
        email=f"{username}@example.com",
        password_hash="!static-test-hash",
        country="JP",
        created_at=now,
        updated_at=now,
    )
    session = (
        SessionData(
            user_id=user_id,
            username=username,
            privileges=1,
            country="JP",
            osu_version="20240101",
            utc_offset=9,
            display_city=False,
            client_hashes="",
            pm_private=False,
        )
        if create_session
        else None
    )
    return ScoreAuthorizationService(
        user_repo=StaticScoreUserRepository(user),
        password_service=StaticPasswordService(password_md5),
        session_store=StaticSessionStore(session),
    )


class UowScoreRepositoryView:
    """testからUnit of Work配下のscore command stateを読むviewを提供する.

    Attributes:
        _unit_of_work_factory (InMemoryUnitOfWorkFactory): score command stateを開くfactory.
    """

    def __init__(self, unit_of_work_factory: InMemoryUnitOfWorkFactory) -> None:
        """Score command stateを開くfactoryを初期化する.

        Args:
            unit_of_work_factory (InMemoryUnitOfWorkFactory): 共有in-memory stateを開くfactory.
        """
        self._unit_of_work_factory: InMemoryUnitOfWorkFactory = unit_of_work_factory

    async def create(self, score: Score) -> Score:
        """scoreをcommand repositoryへ保存してcommitする.

        Args:
            score (Score): 保存するscore.

        Returns:
            Score: repositoryが作成してcommitしたscore.
        """
        async with self._unit_of_work_factory() as uow:
            created = await uow.scores.create(score)
            await uow.commit()
            return created

    async def exists_by_online_checksum(self, checksum: str) -> bool:
        """Online checksumが保存済みscoreに存在するかを返す.

        Args:
            checksum (str): 照会するonline checksum.

        Returns:
            bool: checksumを持つscoreが存在する場合はTrue.
        """
        async with self._unit_of_work_factory() as uow:
            return await uow.scores.exists_by_online_checksum(checksum)

    async def get_by_online_checksum(self, checksum: str) -> Score | None:
        """Online checksumに対応するscoreを取得する.

        Args:
            checksum (str): 照会するonline checksum.

        Returns:
            Score | None: checksumが一致するscore. 未登録の場合はNone.
        """
        async with self._unit_of_work_factory() as uow:
            return await uow.scores.get_by_online_checksum(checksum)

    async def get_by_id(self, score_id: int) -> Score | None:
        """Score IDに対応するscoreを取得する.

        Args:
            score_id (int): 照会するscoreの識別子.

        Returns:
            Score | None: IDが一致するscore. 未登録の場合はNone.
        """
        async with self._unit_of_work_factory() as uow:
            return await uow.scores.get_by_id(score_id)


class UowScoreSubmissionRepositoryView:
    """testからUnit of Work配下のsubmission command stateを読むviewを提供する.

    Attributes:
        _unit_of_work_factory (InMemoryUnitOfWorkFactory): submission command stateを開くfactory.
    """

    def __init__(self, unit_of_work_factory: InMemoryUnitOfWorkFactory) -> None:
        """Submission command stateを開くfactoryを初期化する.

        Args:
            unit_of_work_factory (InMemoryUnitOfWorkFactory): 共有in-memory stateを開くfactory.
        """
        self._unit_of_work_factory: InMemoryUnitOfWorkFactory = unit_of_work_factory

    async def create(self, submission: ScoreSubmission) -> ScoreSubmission:
        """submissionをcommand repositoryへ保存してcommitする.

        Args:
            submission (ScoreSubmission): 保存するscore submission.

        Returns:
            ScoreSubmission: repositoryが作成してcommitしたsubmission.
        """
        async with self._unit_of_work_factory() as uow:
            created = await uow.submissions.create(submission)
            await uow.commit()
            return created

    async def get_by_fingerprint(self, fingerprint: str) -> ScoreSubmission | None:
        """Idempotency fingerprintに対応するsubmissionを取得する.

        Args:
            fingerprint (str): 照会するsubmission fingerprint.

        Returns:
            ScoreSubmission | None: fingerprintが一致するsubmission. 未登録の場合はNone.
        """
        async with self._unit_of_work_factory() as uow:
            return await uow.submissions.get_by_fingerprint(fingerprint)

    async def update_state(
        self,
        submission_id: int,
        state: ScoreSubmissionState,
        result_snapshot: dict[str, object] | None = None,
    ) -> None:
        """Submission stateと任意のresult snapshotを更新してcommitする.

        Args:
            submission_id (int): 更新するsubmissionの識別子.
            state (ScoreSubmissionState): 保存するsubmission lifecycle state.
            result_snapshot (dict[str, object] | None): 任意で保存するresult snapshot.

        Returns:
            None: stateをcommitし, 呼び出し側へ値を返さずに完了する.
        """
        async with self._unit_of_work_factory() as uow:
            await uow.submissions.update_state(submission_id, state, result_snapshot)
            await uow.commit()


class UowReplayRepositoryView:
    """testからUnit of Work配下のreplay command stateを読むviewを提供する.

    Attributes:
        _unit_of_work_factory (InMemoryUnitOfWorkFactory): replay command stateを開くfactory.
    """

    def __init__(self, unit_of_work_factory: InMemoryUnitOfWorkFactory) -> None:
        """Replay command stateを開くfactoryを初期化する.

        Args:
            unit_of_work_factory (InMemoryUnitOfWorkFactory): 共有in-memory stateを開くfactory.
        """
        self._unit_of_work_factory: InMemoryUnitOfWorkFactory = unit_of_work_factory

    async def create(self, replay: Replay) -> Replay:
        """replayをcommand repositoryへ保存してcommitする.

        Args:
            replay (Replay): 保存するreplay.

        Returns:
            Replay: repositoryが作成してcommitしたreplay.
        """
        async with self._unit_of_work_factory() as uow:
            created = await uow.replays.create(replay)
            await uow.commit()
            return created

    async def exists_by_checksum(self, checksum: str) -> bool:
        """checksumが保存済みreplayに存在するかを返す.

        Args:
            checksum (str): 照会するreplay checksum.

        Returns:
            bool: checksumを持つreplayが存在する場合はTrue.
        """
        async with self._unit_of_work_factory() as uow:
            return await uow.replays.exists_by_checksum(checksum)


type ScoreRepositoryViews = tuple[
    UowScoreRepositoryView,
    UowScoreSubmissionRepositoryView,
    UowReplayRepositoryView,
]


def make_score_repository_views(
    unit_of_work_factory: InMemoryUnitOfWorkFactory,
) -> ScoreRepositoryViews:
    """Score submission test用のrepository view集合を作成する.

    Args:
        unit_of_work_factory (InMemoryUnitOfWorkFactory): 全viewで共有するin-memory state factory.

    Returns:
        ScoreRepositoryViews: score, submission, replay command stateを読む3つのview.
    """
    return (
        UowScoreRepositoryView(unit_of_work_factory),
        UowScoreSubmissionRepositoryView(unit_of_work_factory),
        UowReplayRepositoryView(unit_of_work_factory),
    )


def make_submit_score_use_case(
    unit_of_work_factory: InMemoryUnitOfWorkFactory,
) -> SubmitScoreUseCase:
    """in-memory Unit of Workを持つscore submission use caseを作成する.

    Args:
        unit_of_work_factory (InMemoryUnitOfWorkFactory): use caseへ注入するin-memory state
            factory.

    Returns:
        SubmitScoreUseCase: 指定factoryを使ってcommandを実行するuse case.
    """
    return SubmitScoreUseCase(unit_of_work_factory=unit_of_work_factory)


class StubBlobStorageService:
    """blob write検証が必要なtest用のtyped fakeを提供する.

    Attributes:
        fail_writes (bool): Trueの場合に全put_bytes呼び出しを失敗させるか.
        stored (list[Blob]): 書込み成功順に保持する生成済みblob metadata.
        writes (list[bytes]): 書込み成功順に保持するraw byte列.
    """

    def __init__(self, *, fail_writes: bool = False) -> None:
        """任意のwrite failure modeを持つblob storage fakeを初期化する.

        Args:
            fail_writes (bool): 全writeをRuntimeErrorで失敗させるか.
        """
        self.fail_writes: bool = fail_writes
        self.stored: list[Blob] = []
        self.writes: list[bytes] = []

    async def put_bytes(self, data: bytes, *, content_type: str) -> BlobStored:
        """byte列をin-memory blobとして保存するか, failure modeなら失敗させる.

        Args:
            data (bytes): 保存するraw blob content.
            content_type (str): 生成するblob metadataへ記録するMIME type.

        Returns:
            BlobStored: SHA-256 metadataとともに保存したblob.

        Raises:
            RuntimeError: fail_writesがTrueでblob write failureを再現する場合.
        """
        if self.fail_writes:
            raise RuntimeError("blob write failed")

        digest = hashlib.sha256(data).hexdigest()
        blob = Blob(
            id=len(self.stored) + 1,
            sha256=digest,
            byte_size=len(data),
            content_type=content_type,
            storage_backend=BlobStorageBackendKind.LOCAL,
            storage_key=f"sha256/{digest[:2]}/{digest[2:4]}/{digest}",
            created_at=datetime.now(UTC),
        )
        self.stored.append(blob)
        self.writes.append(data)
        return BlobStored(blob=blob)


type ScorePayloadDecryptFactory = Callable[[bytes, bytes, str | None], DecryptedPayload]
type ScorePayloadParseFactory = Callable[[str], ParsedScore]

_TEST_BEATMAP_CHECKSUM = "0123456789abcdef0123456789abcdef"
_DEFAULT_TEST_SCORE_PAYLOAD = (
    f"1000:test_user:{_TEST_BEATMAP_CHECKSUM}:online_checksum_1:0:0:100:10:5:0:0:2:500000:99:1:1"
)


def make_test_parsed_score(payload: str = _DEFAULT_TEST_SCORE_PAYLOAD) -> ParsedScore:
    """test用stable score payloadをParsedScoreに変換する.

    Args:
        payload (str): legacy/stable score payload text. 省略時はosu! rulesetの成功例を使う.

    Returns:
        ParsedScore: command use caseに渡せるparsed score.

    Raises:
        ParseError: payloadのfield countまたはvalueがtest parserの受理条件に合わない場合.

    Notes:
        production parserの依存を避け, unit test用のdeterministic parserだけを使う.
    """
    return _parse_test_score_payload(payload)


def make_test_submission_input(
    *,
    payload: str = _DEFAULT_TEST_SCORE_PAYLOAD,
    parsed_score: ParsedScore | None = None,
    request_hash: str = "test_request_hash",
    replay_data: bytes | None = b"replay_binary_data",
    password_md5: str = FIXED_TEST_PASSWORD_MD5,
    fail_time_ms: int | None = None,
    osu_version: str | None = "20240101",
    beatmap_id: int | None = 1,
    submitted_at: datetime | None = None,
    submit_exit_classification: str | None = None,
    opaque_field_hashes: dict[str, str] | None = None,
    decrypt_latency_ms: float = 0.0,
) -> ParsedSubmissionInput:
    """Score submission command test用inputを作る.

    Args:
        payload (str): parsed_scoreがNoneのときにparseするstable payload.
        parsed_score (ParsedScore | None): 直接使うparsed score. 指定時はpayloadをparseしない.
        request_hash (str): idempotency検証用のrequest hash.
        replay_data (bytes | None): replay binary. replayなしの経路ではNoneを渡す.
        password_md5 (str): authorization fakeへ渡すpassword-md5 credential.
        fail_time_ms (int | None): stable clientのfail time. 未送信を表す場合はNone.
        osu_version (str | None): stable client version. 未送信を表す場合はNone.
        beatmap_id (int | None): request field由来のbeatmap ID. 未送信を表す場合はNone.
        submitted_at (datetime | None): server受信時刻. Noneの場合は現在時刻を使う.
        submit_exit_classification (str | None): client終了種別のdiagnostic value.
        opaque_field_hashes (dict[str, str] | None): tokenなどopaque fieldのhash値.
        decrypt_latency_ms (float): 復号処理時間として記録する値.

    Returns:
        ParsedSubmissionInput: score submission use caseに渡せる正規化済みinput.

    Raises:
        ParseError: parsed_scoreがNoneでpayloadがtest parserの受理条件に合わない場合.

    Notes:
        encrypted payloadやIVを含めず, command boundaryの正規化済みinputだけを生成する.
    """
    return ParsedSubmissionInput(
        parsed_score=parsed_score or make_test_parsed_score(payload),
        request_hash=request_hash,
        opaque_field_hashes=opaque_field_hashes or {},
        decrypt_latency_ms=decrypt_latency_ms,
        replay_data=replay_data,
        password_md5=password_md5,
        fail_time_ms=fail_time_ms,
        osu_version=osu_version,
        submitted_at=submitted_at or datetime.now(UTC),
        beatmap_id=beatmap_id,
        submit_exit_classification=submit_exit_classification,
    )


def make_stable_score_submit_decoder(
    payload: str = (
        f"1000:test_user:{_TEST_BEATMAP_CHECKSUM}:online_checksum:0:0:100:10:5:0:0:2:500000:99:1:1"
    ),
    *,
    checksum_valid: bool = True,
    payload_decryptor: StableScorePayloadDecryptor | None = None,
) -> StableScoreSubmitDecoder:
    """Stable score submit test用decoderを作る.

    Args:
        payload (str): 復号結果として返すplaintext score payload.
        checksum_valid (bool): 復号結果のchecksum_valid. checksum異常経路ではFalseを渡す.
        payload_decryptor (StableScorePayloadDecryptor | None): test固有の復号fake.
            Noneの場合はpayloadから生成する.

    Returns:
        StableScoreSubmitDecoder: 指定payloadを復号結果として返すdecoder.

    Notes:
        transport testのdecoder構築を一箇所に集約し, payloadとchecksumの差分だけをcall siteに残す.
        payloadのparse失敗はdecoder生成時ではなく実行時に発生する.
    """
    decryptor = payload_decryptor or StubScorePayloadDecryptor(
        DecryptedPayload(plaintext=payload, checksum_valid=checksum_valid)
    )
    return StableScoreSubmitDecoder(
        payload_decryptor=decryptor,
        payload_parser=StableScorePayloadParser(),
    )


class StubScorePayloadDecryptor:
    """score submission test用payload decryptorのtyped fakeを提供する.

    Attributes:
        _result (DecryptedPayload | None): factory未設定時に返す固定復号結果.
        _factory (ScorePayloadDecryptFactory | None): 入力ごとに復号結果を作るoptional factory.
        calls (list[tuple[bytes, bytes, str | None]]): 復号要求順に記録するencrypted input列.
    """

    def __init__(
        self,
        result: DecryptedPayload | None = None,
        *,
        factory: ScorePayloadDecryptFactory | None = None,
    ) -> None:
        """固定結果またはfactoryを持つdecryptor fakeを初期化する.

        Args:
            result (DecryptedPayload | None): factory未設定時に返す固定復号結果.
            factory (ScorePayloadDecryptFactory | None): encrypted inputごとに結果を作るfactory.

        Notes:
            resultとfactoryがともにNoneの場合, decrypt_score_payloadはAssertionErrorを送出する.
        """
        self._result: DecryptedPayload | None = result
        self._factory: ScorePayloadDecryptFactory | None = factory
        self.calls: list[tuple[bytes, bytes, str | None]] = []

    def set_result(self, result: DecryptedPayload) -> None:
        """以降の復号で返す固定結果を設定する.

        Args:
            result (DecryptedPayload): factoryを置き換えて返す復号結果.

        Returns:
            None: 固定結果を設定し, factoryを解除して完了する.
        """
        self._result = result
        self._factory = None

    def set_factory(self, factory: ScorePayloadDecryptFactory) -> None:
        """Encrypted inputから復号結果を作るfactoryを設定する.

        Args:
            factory (ScorePayloadDecryptFactory): decrypt要求ごとに呼び出すfactory.

        Returns:
            None: factoryを設定し, 呼び出し側へ値を返さずに完了する.
        """
        self._factory = factory

    def decrypt_score_payload(
        self,
        encrypted: bytes,
        iv: bytes,
        osu_version: str | None,
    ) -> DecryptedPayload:
        """復号要求を記録し, factoryまたは固定結果を返す.

        Args:
            encrypted (bytes): 復号を要求するencrypted payload.
            iv (bytes): encrypted payloadに対応するinitialization vector.
            osu_version (str | None): payloadを送信したclient version.

        Returns:
            DecryptedPayload: factoryまたは固定設定から得た復号結果.

        Raises:
            AssertionError: factoryも固定結果も設定されていない場合.
        """
        self.calls.append((encrypted, iv, osu_version))
        if self._factory is not None:
            return self._factory(encrypted, iv, osu_version)
        if self._result is None:
            raise AssertionError("StubScorePayloadDecryptor result was not configured")
        return self._result


class StubScorePayloadParser:
    """ParsedScoreを必要とするcommand test用parser fakeを提供する.

    Attributes:
        _result (ParsedScore | None): factory未設定時に返す固定parse結果.
        _factory (ScorePayloadParseFactory | None): payloadごとにparse結果を作るoptional factory.
        calls (list[str]): parse要求順に記録するpayload列.
    """

    def __init__(
        self,
        result: ParsedScore | None = None,
        *,
        factory: ScorePayloadParseFactory | None = None,
    ) -> None:
        """固定結果またはfactoryを持つparser fakeを初期化する.

        Args:
            result (ParsedScore | None): factory未設定時に返す固定parse結果.
            factory (ScorePayloadParseFactory | None): payloadごとに結果を作るfactory.
        """
        self._result: ParsedScore | None = result
        self._factory: ScorePayloadParseFactory | None = factory
        self.calls: list[str] = []

    def set_result(self, result: ParsedScore) -> None:
        """以降のparseで返す固定結果を設定する.

        Args:
            result (ParsedScore): factoryを置き換えて返すparse結果.

        Returns:
            None: 固定結果を設定し, factoryを解除して完了する.
        """
        self._result = result
        self._factory = None

    def set_factory(self, factory: ScorePayloadParseFactory) -> None:
        """payloadからparse結果を作るfactoryを設定する.

        Args:
            factory (ScorePayloadParseFactory): parse要求ごとに呼び出すfactory.

        Returns:
            None: factoryを設定し, 呼び出し側へ値を返さずに完了する.
        """
        self._factory = factory

    def parse(self, payload: str) -> ParsedScore:
        """parse要求を記録し, factory, 固定結果, test parserの順で結果を返す.

        Args:
            payload (str): ParsedScoreへ変換するscore payload text.

        Returns:
            ParsedScore: factory, 固定結果, またはtest parserが返すparsed score.

        Raises:
            ParseError: 未設定時のtest parserがpayloadを受理できない場合.
        """
        self.calls.append(payload)
        if self._factory is not None:
            return self._factory(payload)
        if self._result is not None:
            return self._result
        return _parse_test_score_payload(payload)


def _parse_test_score_payload(payload: str) -> ParsedScore:
    """test用legacyまたはstable score payloadをParsedScoreへ変換する.

    Args:
        payload (str): colon区切りのlegacyまたはstable score payload text.

    Returns:
        ParsedScore: field layoutに対応するparsed score.

    Raises:
        ParseError: field数がlegacy/stable test layoutに一致しない場合.
    """
    fields = payload.split(":")
    if len(fields) == 16 and _is_int(fields[0]):
        return _parse_test_legacy_score_payload(fields)
    if 16 <= len(fields) <= 19:
        return _parse_test_stable_score_payload(fields)
    raise ParseError(f"Unsupported test score payload field count: {len(fields)}")


def _parse_test_legacy_score_payload(fields: list[str]) -> ParsedScore:
    """16 fieldのlegacy score payloadをParsedScoreへ変換する.

    Args:
        fields (list[str]): user IDからpassed flagまでを持つ16 fieldのlegacy layout.

    Returns:
        ParsedScore: legacy fieldを型変換したparsed score.

    Raises:
        ParseError: integer, mod, またはboolean fieldを変換できない場合.
    """
    try:
        return ParsedScore(
            user_id=int(fields[0]),
            username=fields[1],
            beatmap_checksum=fields[2],
            online_checksum=fields[3],
            ruleset=int(fields[4]),
            mods=ModCombination.from_bitmask(int(fields[5])),
            n300=int(fields[6]),
            n100=int(fields[7]),
            n50=int(fields[8]),
            geki=int(fields[9]),
            katu=int(fields[10]),
            miss=int(fields[11]),
            score=int(fields[12]),
            max_combo=int(fields[13]),
            perfect=_parse_test_bool(fields[14]),
            passed=_parse_test_bool(fields[15]),
        )
    except ValueError as exc:
        raise ParseError(f"Failed to parse test score payload: {exc}") from exc


def _parse_test_stable_score_payload(fields: list[str]) -> ParsedScore:
    """16から19 fieldのstable score payloadをParsedScoreへ変換する.

    Args:
        fields (list[str]): beatmap checksumからoptional client metadataまでを持つstable layout.

    Returns:
        ParsedScore: stable fieldを型変換したparsed score.

    Raises:
        ParseError: integer, mod, またはboolean fieldを変換できない場合.
    """
    try:
        return ParsedScore(
            user_id=0,
            username=fields[1],
            beatmap_checksum=fields[0],
            online_checksum=fields[2],
            n300=int(fields[3]),
            n100=int(fields[4]),
            n50=int(fields[5]),
            geki=int(fields[6]),
            katu=int(fields[7]),
            miss=int(fields[8]),
            score=int(fields[9]),
            max_combo=int(fields[10]),
            perfect=_parse_test_bool(fields[11]),
            client_grade=fields[12],
            mods=ModCombination.from_bitmask(int(fields[13])),
            passed=_parse_test_bool(fields[14]),
            ruleset=int(fields[15]),
            client_submitted_at=fields[16] if len(fields) > 16 else None,
            client_version=fields[17] if len(fields) > 17 else None,
            client_checksum=fields[18] if len(fields) > 18 else None,
        )
    except ValueError as exc:
        raise ParseError(f"Failed to parse test score payload: {exc}") from exc


def _is_int(value: str) -> bool:
    """文字列をintへ変換できるかを返す.

    Args:
        value (str): integer表現として判定する文字列.

    Returns:
        bool: int conversionが成功する場合はTrue.
    """
    try:
        _ = int(value)
    except ValueError:
        return False
    return True


def _parse_test_bool(value: str) -> bool:
    """Test payloadのboolean fieldをboolへ変換する.

    Args:
        value (str): 1/0または大文字小文字を許容するTrue/False表現.

    Returns:
        bool: valueが表すboolean値.

    Raises:
        ValueError: valueがtest payloadで受理するboolean表現でない場合.
    """
    match value:
        case "1" | "True" | "true":
            return True
        case "0" | "False" | "false":
            return False
        case _:
            raise ValueError(f"invalid boolean value: {value}")
