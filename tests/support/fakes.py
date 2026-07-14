"""テストが外部 I/O を使わず seam を検証するための typed fake 群。"""

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
    """HIBPClient の typed fake。

    本物のネットワーク通信を行わず、指定されたパスワードの漏洩状態をシミュレートする。
    """

    def __init__(self, compromised_passwords: set[str] | None = None) -> None:
        self.compromised_passwords: set[str] = compromised_passwords or set()
        self.calls: list[str] = []

    async def is_password_compromised(self, password: str) -> bool:
        """指定パスワードを漏洩済みとして扱うか返す。"""
        self.calls.append(password)
        return password in self.compromised_passwords


# Ensure FakeHIBPClient implements the HIBPClient protocol
_: HIBPClient = FakeHIBPClient()


@final
class ErrorRaisingUserRepository:
    """armed 状態のとき get_by_safe_username で例外を投げる repository fake。

    それ以外の操作は inner UserQueryRepository に委譲する。AsyncMock の
    monkey-patch を使わずに DB failure を再現する。
    """

    def __init__(self, inner: UserQueryRepository, error: Exception) -> None:
        self._inner = inner
        self._error = error
        self._armed = False

    def arm(self) -> None:
        """次回以降の get_by_safe_username で例外を投げる状態にする。"""
        self._armed = True

    async def get_by_id(self, user_id: int) -> User | None:
        return await self._inner.get_by_id(user_id)

    async def get_by_safe_username(self, safe_username: str) -> User | None:
        if self._armed:
            raise self._error
        return await self._inner.get_by_safe_username(safe_username)

    async def get_by_email(self, email: str) -> User | None:
        return await self._inner.get_by_email(email)

    async def is_username_disallowed(self, safe_username: str) -> bool:
        return await self._inner.is_username_disallowed(safe_username)


@final
class StaticScoreUserRepository:
    """score authorization test 用の単一 user repository。"""

    def __init__(self, user: User) -> None:
        self._user = user

    async def create(self, user: User) -> User:
        self._user = user
        return user

    async def get_by_id(self, user_id: int) -> User | None:
        return self._user if self._user.id == user_id else None

    async def get_by_safe_username(self, safe_username: str) -> User | None:
        return self._user if self._user.safe_username == safe_username else None

    async def get_by_email(self, email: str) -> User | None:
        return self._user if self._user.email == email else None

    async def is_username_disallowed(self, safe_username: str) -> bool:
        _ = safe_username
        return False

    async def add_disallowed_username(self, safe_username: str) -> None:
        _ = safe_username

    async def update_country(self, user_id: int, country: str) -> None:
        if self._user.id == user_id:
            self._user.country = country

    async def sync_system_user(self, identity: SystemUserIdentity) -> None:
        _ = identity


@final
class StaticPasswordService(PasswordService):
    """1 つの password-md5 だけを受理する PasswordService fake。"""

    def __init__(self, accepted_password_md5: str) -> None:
        super().__init__(hibp_client=None, banned_passwords=[])
        self._accepted_password_md5 = accepted_password_md5

    @override
    async def verify(self, hashed: str, password: str) -> bool:
        _ = hashed
        return password == self._accepted_password_md5


@final
class StaticSessionStore:
    """任意の active session を 1 つ保持する SessionStore fake。"""

    def __init__(self, session: SessionData | None) -> None:
        self._session = session
        self._token = f"token-{session.user_id}" if session is not None else ""

    async def create(self, user_id: int, token: str, data: SessionData) -> None:
        _ = user_id
        self._token = token
        self._session = data

    async def get(self, token: str) -> SessionData | None:
        return self._session if self._session is not None and token == self._token else None

    async def get_by_user(self, user_id: int) -> SessionData | None:
        return (
            self._session
            if self._session is not None and self._session.user_id == user_id
            else None
        )

    async def delete(self, token: str) -> None:
        if token == self._token:
            self._session = None

    async def exists(self, token: str) -> bool:
        return self._session is not None and token == self._token

    async def refresh(self, token: str) -> bool:
        return await self.exists(token)

    async def delete_by_user(self, user_id: int) -> None:
        if self._session is not None and self._session.user_id == user_id:
            self._session = None

    async def update_authorization(
        self,
        user_id: int,
        authorization: SessionAuthorization,
    ) -> bool:
        if self._session is None or self._session.user_id != user_id:
            return False
        self._session.privileges = int(authorization.privileges)
        self._session.role_ids = authorization.role_ids
        return True

    async def update_pm_private(self, user_id: int, enabled: bool) -> bool:
        if self._session is None or self._session.user_id != user_id:
            return False
        self._session.pm_private = enabled
        return True

    async def list_active_sessions(self) -> list[SessionData]:
        return [] if self._session is None else [self._session]


def make_score_authorization_service(
    *,
    user_id: int = 1000,
    username: str = "test_user",
    password_md5: str = FIXED_TEST_PASSWORD_MD5,
    create_session: bool = True,
) -> ScoreAuthorizationService:
    """明示的な fake で repository-backed score auth を作る。"""
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
    """test から Unit of Work 配下の score command state を読む view。"""

    def __init__(self, unit_of_work_factory: InMemoryUnitOfWorkFactory) -> None:
        self._unit_of_work_factory: InMemoryUnitOfWorkFactory = unit_of_work_factory

    async def create(self, score: Score) -> Score:
        async with self._unit_of_work_factory() as uow:
            created = await uow.scores.create(score)
            await uow.commit()
            return created

    async def exists_by_online_checksum(self, checksum: str) -> bool:
        async with self._unit_of_work_factory() as uow:
            return await uow.scores.exists_by_online_checksum(checksum)

    async def get_by_online_checksum(self, checksum: str) -> Score | None:
        async with self._unit_of_work_factory() as uow:
            return await uow.scores.get_by_online_checksum(checksum)

    async def get_by_id(self, score_id: int) -> Score | None:
        async with self._unit_of_work_factory() as uow:
            return await uow.scores.get_by_id(score_id)


class UowScoreSubmissionRepositoryView:
    """test から Unit of Work 配下の submission command state を読む view。"""

    def __init__(self, unit_of_work_factory: InMemoryUnitOfWorkFactory) -> None:
        self._unit_of_work_factory: InMemoryUnitOfWorkFactory = unit_of_work_factory

    async def create(self, submission: ScoreSubmission) -> ScoreSubmission:
        async with self._unit_of_work_factory() as uow:
            created = await uow.submissions.create(submission)
            await uow.commit()
            return created

    async def get_by_fingerprint(self, fingerprint: str) -> ScoreSubmission | None:
        async with self._unit_of_work_factory() as uow:
            return await uow.submissions.get_by_fingerprint(fingerprint)

    async def update_state(
        self,
        submission_id: int,
        state: ScoreSubmissionState,
        result_snapshot: dict[str, object] | None = None,
    ) -> None:
        async with self._unit_of_work_factory() as uow:
            await uow.submissions.update_state(submission_id, state, result_snapshot)
            await uow.commit()


class UowReplayRepositoryView:
    """test から Unit of Work 配下の replay command state を読む view。"""

    def __init__(self, unit_of_work_factory: InMemoryUnitOfWorkFactory) -> None:
        self._unit_of_work_factory: InMemoryUnitOfWorkFactory = unit_of_work_factory

    async def create(self, replay: Replay) -> Replay:
        async with self._unit_of_work_factory() as uow:
            created = await uow.replays.create(replay)
            await uow.commit()
            return created

    async def exists_by_checksum(self, checksum: str) -> bool:
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
    return (
        UowScoreRepositoryView(unit_of_work_factory),
        UowScoreSubmissionRepositoryView(unit_of_work_factory),
        UowReplayRepositoryView(unit_of_work_factory),
    )


def make_submit_score_use_case(
    unit_of_work_factory: InMemoryUnitOfWorkFactory,
) -> SubmitScoreUseCase:
    return SubmitScoreUseCase(unit_of_work_factory=unit_of_work_factory)


class StubBlobStorageService:
    """blob write 検証が必要な test 用の typed fake。"""

    def __init__(self, *, fail_writes: bool = False) -> None:
        self.fail_writes: bool = fail_writes
        self.stored: list[Blob] = []
        self.writes: list[bytes] = []

    async def put_bytes(self, data: bytes, *, content_type: str) -> BlobStored:
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
    """テスト用 stable score payload を ParsedScore に変換する。

    Args:
        payload: legacy/stable score payload text。省略時は osu! ruleset の成功例を使う。

    Returns:
        command use-case に渡せる ParsedScore。

    Raises:
        ParseError: payload の field count や値が test parser の受理条件に合わない場合。

    Constraints:
        Production parser の依存を避け、unit test 用の deterministic な parser だけを使う。
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
    """スコア送信 command test 用 input を作る。

    Args:
        payload: parsed_score が None のときに parse する stable payload。
        parsed_score: 直接使う ParsedScore。指定時は payload を parse しない。
        request_hash: idempotency 検証用の request hash。
        replay_data: replay binary。replay なしの経路では None を渡す。
        password_md5: authorization fake に渡す password-md5 credential。
        fail_time_ms: stable client の fail time。未送信を表す場合は None。
        osu_version: stable client version。未送信を表す場合は None。
        beatmap_id: request field 由来の beatmap id。未送信を表す場合は None。
        submitted_at: server 受信時刻。None の場合は現在時刻を使う。
        submit_exit_classification: client 終了種別の診断値。
        opaque_field_hashes: token など opaque field の hash 値。
        decrypt_latency_ms: 復号処理時間として記録する値。

    Returns:
        ProcessScoreSubmissionUseCase に渡せる ParsedSubmissionInput。

    Raises:
        ParseError: parsed_score が None で payload が test parser の受理条件に合わない場合。

    Constraints:
        encrypted payload や IV は含めず、command 境界の正規化済み入力だけを生成する。
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
    """安定版 score submit test 用 decoder を作る。

    Args:
        payload: 復号結果として返す plaintext score payload。
        checksum_valid: 復号結果の checksum_valid。checksum 異常経路では False を渡す。
        payload_decryptor: test 固有の復号 fake。None の場合は payload から生成する。

    Returns:
        StableScoreSubmitDecoder。

    Raises:
        生成時に独自例外は送出しない。payload の parse 失敗は decoder 実行時に発生する。

    Constraints:
        Transport test の decoder 構築を一箇所に集約し、payload と checksum の差分だけを
        call site に残す。
    """
    decryptor = payload_decryptor or StubScorePayloadDecryptor(
        DecryptedPayload(plaintext=payload, checksum_valid=checksum_valid)
    )
    return StableScoreSubmitDecoder(
        payload_decryptor=decryptor,
        payload_parser=StableScorePayloadParser(),
    )


class StubScorePayloadDecryptor:
    """score submission test 用 payload decryptor の typed fake。"""

    def __init__(
        self,
        result: DecryptedPayload | None = None,
        *,
        factory: ScorePayloadDecryptFactory | None = None,
    ) -> None:
        self._result: DecryptedPayload | None = result
        self._factory: ScorePayloadDecryptFactory | None = factory
        self.calls: list[tuple[bytes, bytes, str | None]] = []

    def set_result(self, result: DecryptedPayload) -> None:
        self._result = result
        self._factory = None

    def set_factory(self, factory: ScorePayloadDecryptFactory) -> None:
        self._factory = factory

    def decrypt_score_payload(
        self,
        encrypted: bytes,
        iv: bytes,
        osu_version: str | None,
    ) -> DecryptedPayload:
        self.calls.append((encrypted, iv, osu_version))
        if self._factory is not None:
            return self._factory(encrypted, iv, osu_version)
        if self._result is None:
            raise AssertionError("StubScorePayloadDecryptor result was not configured")
        return self._result


class StubScorePayloadParser:
    """ParsedScore を必要とする command test 用 parser fake。"""

    def __init__(
        self,
        result: ParsedScore | None = None,
        *,
        factory: ScorePayloadParseFactory | None = None,
    ) -> None:
        self._result: ParsedScore | None = result
        self._factory: ScorePayloadParseFactory | None = factory
        self.calls: list[str] = []

    def set_result(self, result: ParsedScore) -> None:
        self._result = result
        self._factory = None

    def set_factory(self, factory: ScorePayloadParseFactory) -> None:
        self._factory = factory

    def parse(self, payload: str) -> ParsedScore:
        self.calls.append(payload)
        if self._factory is not None:
            return self._factory(payload)
        if self._result is not None:
            return self._result
        return _parse_test_score_payload(payload)


def _parse_test_score_payload(payload: str) -> ParsedScore:
    fields = payload.split(":")
    if len(fields) == 16 and _is_int(fields[0]):
        return _parse_test_legacy_score_payload(fields)
    if 16 <= len(fields) <= 19:
        return _parse_test_stable_score_payload(fields)
    raise ParseError(f"Unsupported test score payload field count: {len(fields)}")


def _parse_test_legacy_score_payload(fields: list[str]) -> ParsedScore:
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
    try:
        _ = int(value)
    except ValueError:
        return False
    return True


def _parse_test_bool(value: str) -> bool:
    match value:
        case "1" | "True" | "true":
            return True
        case "0" | "False" | "false":
            return False
        case _:
            raise ValueError(f"invalid boolean value: {value}")
