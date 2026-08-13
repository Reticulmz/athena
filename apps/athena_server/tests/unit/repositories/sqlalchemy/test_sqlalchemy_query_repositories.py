"""SQLAlchemy query repository adapterのread-only契約を検証するtest."""

from __future__ import annotations

import ast
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, cast, override

from osu_server.domain.beatmaps import (
    BeatmapFetchState,
    BeatmapFetchTarget,
    BeatmapFetchTargetKind,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSourceVerification,
)
from osu_server.domain.chat.channels import ChannelType
from osu_server.domain.scores.performance import (
    FormulaProfile,
    PerformanceCalculationState,
    RecalculationCandidateReason,
)
from osu_server.domain.scores.personal_best import LeaderboardCategory
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset
from osu_server.repositories.interfaces.queries.score_performance import (
    ScorePerformanceCandidateSelection,
    ScorePerformanceQueryRepository,
)
from osu_server.repositories.sqlalchemy.models.beatmap import (
    BeatmapFetchStateModel,
    BeatmapFileAttachmentModel,
    BeatmapModel,
    BeatmapSetModel,
)
from osu_server.repositories.sqlalchemy.models.blob import BlobModel
from osu_server.repositories.sqlalchemy.models.channel import (
    ChannelMessageModel,
    ChannelModel,
    ChannelRoleOverrideModel,
    PrivateMessageModel,
)
from osu_server.repositories.sqlalchemy.models.role import RoleModel
from osu_server.repositories.sqlalchemy.models.score import ReplayModel, ScoreModel
from osu_server.repositories.sqlalchemy.models.score_performance import (
    ScorePerformanceCalculationModel,
)
from osu_server.repositories.sqlalchemy.models.user import UserModel
from osu_server.repositories.sqlalchemy.queries import (
    SQLAlchemyBeatmapQueryRepository,
    SQLAlchemyBeatmapScoreListingQueryRepository,
    SQLAlchemyBlobQueryRepository,
    SQLAlchemyChannelQueryRepository,
    SQLAlchemyChatHistoryQueryRepository,
    SQLAlchemyFriendRelationshipQueryRepository,
    SQLAlchemyPersonalBestQueryRepository,
    SQLAlchemyRoleQueryRepository,
    SQLAlchemyScorePerformanceQueryRepository,
    SQLAlchemyScoreQueryRepository,
    SQLAlchemyUserQueryRepository,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from types import TracebackType

    from sqlalchemy.sql.base import Executable

    from osu_server.repositories.interfaces.queries import (
        BeatmapQueryRepository,
        BeatmapScoreListingQueryRepository,
        BlobQueryRepository,
        ChannelQueryRepository,
        ChatHistoryQueryRepository,
        FriendRelationshipQueryRepository,
        PersonalBestQueryRepository,
        RoleQueryRepository,
        ScoreQueryRepository,
        UserQueryRepository,
    )
    from osu_server.repositories.sqlalchemy.queries._shared import SQLAlchemyQuerySessionFactory

PROJECT_ROOT = Path(__file__).parents[4]
QUERY_ROOT = PROJECT_ROOT / "src" / "osu_server" / "repositories" / "sqlalchemy" / "queries"
_NOW = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)
_LATEST_ACTIVITY_AT = datetime(2026, 7, 7, 1, 2, 3, tzinfo=UTC)


class FakeResult:
    """SQLAlchemy query結果を再現するread-only fakeを提供する.

    Attributes:
        _value (object | None): scalar_one_or_none()が返す単一値.
        _values (list[object]): scalars().all()が返す順序付き値.
    """

    _value: object | None
    _values: list[object]

    def __init__(self, value: object | None = None, values: Iterable[object] = ()) -> None:
        """query結果doubleを初期化する.

        Args:
            value (object | None): 単一値を読むqueryに返す値.
            values (Iterable[object]): 複数値を読むqueryに返す順序付き値.
        """
        self._value = value
        self._values = list(values)

    def scalar_one_or_none(self) -> object | None:
        """設定済みの単一値を返す.

        Returns:
            object | None: queryが一致させた値. 値がない場合はNone.
        """
        return self._value

    def scalars(self) -> FakeResult:
        """複数値を読むための結果viewを返す.

        Returns:
            FakeResult: all()で設定済みの複数値を返す同じresult instance.
        """
        return self

    def all(self) -> list[object]:
        """設定済みの複数値を順序を保って返す.

        Returns:
            list[object]: queryが一致させた複数値.
        """
        return self._values


class FakeQuerySession(AbstractAsyncContextManager["FakeQuerySession"]):
    """query repositoryのread-only session契約を再現するfakeを提供する.

    Attributes:
        closed (bool): close()が呼ばれたかを示す状態.
        executed (int): execute()で受け取ったstatement数.
        _get_handler (Callable[[type[object], object], object | None]):
            model取得結果を決めるhandler.
        _execute_handler (Callable[[Executable], FakeResult]): statement実行結果を決めるhandler.

    Notes:
        mutation APIはAssertionErrorを送出してquery adapterのwriteをtestで可視化する.
    """

    closed: bool
    executed: int
    _get_handler: Callable[[type[object], object], object | None]
    _execute_handler: Callable[[Executable], FakeResult]

    def __init__(
        self,
        *,
        get_handler: Callable[[type[object], object], object | None] | None = None,
        execute_handler: Callable[[Executable], FakeResult] | None = None,
    ) -> None:
        """read-only query session fakeを初期化する.

        Args:
            get_handler (Callable[[type[object], object], object | None] | None):
                modelとidentityから取得結果を返すhandler. Noneの場合は常にNoneを返す.
            execute_handler (Callable[[Executable], FakeResult] | None):
                SQL statementから結果doubleを返すhandler. Noneの場合は空結果を返す.
        """
        self.closed = False
        self.executed = 0
        self._get_handler = get_handler or _missing_get
        self._execute_handler = execute_handler or _empty_execute

    @override
    async def __aenter__(self) -> FakeQuerySession:
        """context内で利用する同じsession fakeを返す.

        Returns:
            FakeQuerySession: query実行状態を記録するこのsession.
        """
        return self

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """context終了時にsessionを閉じる.

        Args:
            exc_type (type[BaseException] | None): 終了exception型. Noneなら正常終了.
            exc (BaseException | None): 終了exception instance. Noneなら正常終了.
            traceback (TracebackType | None): context内のexception traceback. 例外がない場合はNone.

        Returns:
            None: sessionをclosed状態にして呼び出し側へ値を返さずに完了する.
        """
        _ = exc_type
        _ = exc
        _ = traceback
        await self.close()

    async def get(self, model_type: type[object], identity: object) -> object | None:
        """model型とidentityに対応するread結果を返す.

        Args:
            model_type (type[object]): 取得対象のSQLAlchemy model型.
            identity (object): modelを特定するprimary key値.

        Returns:
            object | None: get handlerが返したmodel. 一致しない場合はNone.
        """
        return self._get_handler(model_type, identity)

    async def execute(self, statement: Executable) -> FakeResult:
        """Read statementの結果を返し実行回数を記録する.

        Args:
            statement (Executable): query repositoryが発行したSQLAlchemy statement.

        Returns:
            FakeResult: execute handlerがstatementに対応させた結果double.
        """
        self.executed += 1
        return self._execute_handler(statement)

    def add(self, instance: object) -> None:
        """Query sessionでの追加操作を失敗させる.

        Args:
            instance (object): 追加しようとしたpersistence model.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.

        Raises:
            AssertionError: query repositoryがmutation APIを呼び出した場合.
        """
        _ = instance
        raise AssertionError("query repository must not add instances")

    async def delete(self, instance: object) -> None:
        """Query sessionでの削除操作を失敗させる.

        Args:
            instance (object): 削除しようとしたpersistence model.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.

        Raises:
            AssertionError: query repositoryがmutation APIを呼び出した場合.
        """
        _ = instance
        raise AssertionError("query repository must not delete instances")

    async def merge(self, instance: object) -> object:
        """Query sessionでのmerge操作を失敗させる.

        Args:
            instance (object): mergeしようとしたpersistence model.

        Raises:
            AssertionError: query repositoryがmutation APIを呼び出した場合.
        """
        _ = instance
        raise AssertionError("query repository must not merge instances")

    async def flush(self) -> None:
        """Query sessionでのflush操作を失敗させる.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.

        Raises:
            AssertionError: query repositoryがmutation APIを呼び出した場合.
        """
        raise AssertionError("query repository must not flush")

    async def commit(self) -> None:
        """Query sessionでのcommit操作を失敗させる.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.

        Raises:
            AssertionError: query repositoryがmutation APIを呼び出した場合.
        """
        raise AssertionError("query repository must not commit")

    async def rollback(self) -> None:
        """Query sessionでのrollback操作を失敗させる.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.

        Raises:
            AssertionError: query repositoryがmutation APIを呼び出した場合.
        """
        raise AssertionError("query repository must not rollback")

    async def refresh(self, instance: object) -> None:
        """Query sessionでのrefresh操作を失敗させる.

        Args:
            instance (object): refreshしようとしたpersistence model.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.

        Raises:
            AssertionError: query repositoryがmutation APIを呼び出した場合.
        """
        _ = instance
        raise AssertionError("query repository must not refresh")

    async def close(self) -> None:
        """sessionをclosed状態へ遷移させる.

        Returns:
            None: closedをTrueにして呼び出し側へ値を返さずに完了する.
        """
        self.closed = True


class FakeSessionFactory:
    """同じquery sessionを返し生成回数を記録するfactory fakeを提供する.

    Attributes:
        session (FakeQuerySession): factoryが各呼び出しで返すsession fake.
        calls (int): factoryが呼び出された回数.
    """

    session: FakeQuerySession
    calls: int

    def __init__(self, session: FakeQuerySession) -> None:
        """再利用するquery session fakeを設定する.

        Args:
            session (FakeQuerySession): 各factory呼び出しで返すsession.
        """
        self.session = session
        self.calls = 0

    def __call__(self) -> FakeQuerySession:
        """設定済みsessionを返し呼び出し回数を加算する.

        Returns:
            FakeQuerySession: query repositoryへ渡す同じsession fake.
        """
        self.calls += 1
        return self.session


@dataclass(frozen=True, slots=True)
class ScoreBlobBeatmapQueryFixture:
    """score/blob/beatmap query testで共有するpersistence model群を表す.

    Attributes:
        score (ScoreModel): query対象のscore model.
        blob (BlobModel): scoreまたはattachmentが参照するblob model.
        beatmapset (BeatmapSetModel): query対象beatmapを含むbeatmapset model.
        beatmap (BeatmapModel): query対象のbeatmap model.
        attachment (BeatmapFileAttachmentModel): beatmapの現在file attachment model.
        fetch_state (BeatmapFetchStateModel): beatmap metadata取得状態model.
        session (FakeQuerySession): read結果を返すsession fake.
        factory (FakeSessionFactory): sessionを返すfactory fake.
    """

    score: ScoreModel
    blob: BlobModel
    beatmapset: BeatmapSetModel
    beatmap: BeatmapModel
    attachment: BeatmapFileAttachmentModel
    fetch_state: BeatmapFetchStateModel
    session: FakeQuerySession
    factory: FakeSessionFactory


async def test_identity_and_channel_query_repositories_use_short_read_sessions() -> None:
    """identity/channel query adapterが短命read sessionだけを使う契約を検証する.

    user/role/channelとrole overrideが存在する条件で各read APIを呼び出す.
    取得値がmappingされ13個のsession生成後にsessionが閉じることを確認する.

    Returns:
        None: read modelとsession lifecycleを検証して呼び出し側へ値を返さずに完了する.
    """
    user_model = _user_model()
    role_model = _role_model()
    channel_model = _channel_model()
    override_model = ChannelRoleOverrideModel(
        channel_id=channel_model.id,
        role_id=role_model.id,
        can_read=True,
        can_write=False,
    )
    session = FakeQuerySession(
        get_handler=_identity_get_handler(user_model=user_model, role_model=role_model),
        execute_handler=_identity_channel_execute_handler(
            user_model=user_model,
            role_model=role_model,
            channel_model=channel_model,
            override_model=override_model,
        ),
    )
    factory = FakeSessionFactory(session)
    session_factory = cast("SQLAlchemyQuerySessionFactory", cast("object", factory))

    users: UserQueryRepository = SQLAlchemyUserQueryRepository(session_factory)
    roles: RoleQueryRepository = SQLAlchemyRoleQueryRepository(session_factory)
    channels: ChannelQueryRepository = SQLAlchemyChannelQueryRepository(session_factory)

    user_by_id = await users.get_by_id(user_model.id)
    user_by_name = await users.get_by_safe_username("QUERYUSER")
    user_by_email = await users.get_by_email("QUERY@EXAMPLE.COM")
    role_by_id = await roles.get_by_id(role_model.id)
    role_by_name = await roles.get_by_name("Default")
    assert user_by_id is not None
    assert user_by_name is not None
    assert user_by_email is not None
    assert role_by_id is not None
    assert role_by_name is not None

    assert user_by_id.username == "QueryUser"
    assert user_by_name.id == user_model.id
    assert user_by_email.email == "query@example.com"
    assert user_by_id.latest_activity_at == _LATEST_ACTIVITY_AT
    assert role_by_id.name == "Default"
    assert role_by_name.id == role_model.id
    assert [role.id for role in await roles.get_roles_for_user(user_model.id)] == [role_model.id]
    assert (await roles.get_default_role()).name == "Default"
    assert await roles.get_user_ids_for_role(role_model.id) == [user_model.id]
    channel_by_name = await channels.get_by_name("#osu")
    assert channel_by_name is not None
    assert channel_by_name.name == "#osu"
    assert [channel.id for channel in await channels.get_all()] == [channel_model.id]
    assert [channel.id for channel in await channels.get_auto_join()] == [channel_model.id]
    overrides = await channels.get_overrides_for_channel(channel_model.id)
    assert [override.role_id for override in overrides] == [role_model.id]
    assert await channels.get_overrides_for_channels([channel_model.id]) == {
        channel_model.id: [overrides[0]]
    }
    assert factory.calls == 13
    assert session.closed is True


async def test_friend_relationship_query_repository_uses_short_read_sessions() -> None:
    """Friend relationship query adapterがread sessionを短命に保つ契約を検証する.

    ownerとtargetのrelationshipを返すSQL結果を用意して一覧と存在確認を行う.
    tupleのfriend IDと真のrelationship判定を返し2回のsession生成後に閉じることを確認する.

    Returns:
        None: relationship read結果とsession lifecycleを検証して呼び出し側へ値を返さずに完了する.
    """
    session = FakeQuerySession(
        execute_handler=lambda statement: _execute_from_text(
            statement,
            {
                "FROM user_friend_relationships": FakeResult(value=20, values=[10, 20]),
            },
        )
    )
    factory = FakeSessionFactory(session)
    session_factory = cast("SQLAlchemyQuerySessionFactory", cast("object", factory))
    repository: FriendRelationshipQueryRepository = SQLAlchemyFriendRelationshipQueryRepository(
        session_factory
    )

    friend_ids = await repository.list_friend_ids(owner_user_id=1)
    has_relationship = await repository.has_relationship(owner_user_id=1, target_user_id=20)

    assert friend_ids == (10, 20)
    assert has_relationship is True
    assert factory.calls == 2
    assert session.closed is True


async def test_score_and_blob_query_repositories_are_read_only() -> None:
    """score/blob query adapterがread modelを返しwriteを行わない契約を検証する.

    scoreとblobがprimary keyおよびchecksumで見つかる条件を用意して各read APIを呼び出す.
    期待するmodel fieldを保持した結果を返しsessionを閉じることを確認する.

    Returns:
        None: score/blob read結果とread-only lifecycleを検証して呼び出し側へ値を返さずに完了する.
    """
    fixture = _score_blob_beatmap_fixture()
    session_factory = cast("SQLAlchemyQuerySessionFactory", cast("object", fixture.factory))
    scores: ScoreQueryRepository = SQLAlchemyScoreQueryRepository(session_factory)
    blobs: BlobQueryRepository = SQLAlchemyBlobQueryRepository(session_factory)

    score_by_id = await scores.get_by_id(fixture.score.id)
    score_by_checksum = await scores.get_by_online_checksum("online")
    blob_by_id = await blobs.get_by_id(fixture.blob.id)
    blob_by_sha256 = await blobs.get_by_sha256("a" * 64)

    assert score_by_id is not None
    assert score_by_checksum is not None
    assert blob_by_id is not None
    assert blob_by_sha256 is not None
    assert score_by_id.online_checksum == "online"
    assert score_by_checksum.id == fixture.score.id
    assert score_by_id.replay_view_count == 0
    assert score_by_checksum.replay_view_count == 0
    assert blob_by_id.sha256 == "a" * 64
    assert blob_by_sha256.id == fixture.blob.id
    assert fixture.session.closed is True


async def test_personal_best_query_repository_returns_score_listing_read_model() -> None:
    """Personal best query adapterがlisting read modelを組み立てる契約を検証する.

    score/user/replayを結合するpersonal best結果を用意してglobal categoryのreadを行う.
    score値とrankおよびreplay有無を保持したread modelを1回のsessionで返すことを確認する.

    Returns:
        None: personal best listingのmappingとsession lifecycleを検証して完了する.
    """
    user = _user_model()
    score = _score_model(score_id=501, user_id=user.id, beatmap_id=7)
    replay = _replay_model(score_id=score.id)
    session = FakeQuerySession(
        execute_handler=lambda statement: _execute_from_text(
            statement,
            {
                "FROM scores JOIN personal_bests": FakeResult(
                    values=[(score, user.username, replay.score_id == score.id, 1)]
                ),
            },
        )
    )
    factory = FakeSessionFactory(session)
    session_factory = cast("SQLAlchemyQuerySessionFactory", cast("object", factory))
    repository: PersonalBestQueryRepository = SQLAlchemyPersonalBestQueryRepository(
        session_factory
    )

    personal_best = await repository.get_personal_best(
        user_id=user.id,
        beatmap_id=score.beatmap_id,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        category=LeaderboardCategory.GLOBAL,
    )

    assert personal_best is not None
    assert personal_best.score_id == score.id
    assert personal_best.user_id == user.id
    assert personal_best.username == user.username
    assert personal_best.score == score.score
    assert personal_best.max_combo == score.max_combo
    assert personal_best.n300 == score.n300
    assert personal_best.rank == 1
    assert personal_best.has_replay is True
    assert factory.calls == 1
    assert session.closed is True


async def test_score_performance_query_repository_reads_current_and_candidates() -> None:
    """Score performance query adapterがcurrent値と再計算候補理由を返す契約を検証する.

    未計算とcalculator/formula/file差分を持つscoreを用意してtarget profileで候補を選択する.
    current calculationと4種類のcandidate reasonを2回のread sessionで返すことを確認する.

    Returns:
        None: performance read結果とcandidate reason集計を検証して呼び出し側へ値を返さずに完了する.
    """
    score_without_performance = _score_model(score_id=301, user_id=10, beatmap_id=7)
    score_with_mismatch = _score_model(score_id=302, user_id=10, beatmap_id=7)
    score_with_profile_mismatch = _score_model(score_id=303, user_id=10, beatmap_id=7)
    score_with_stale_file = _score_model(score_id=304, user_id=10, beatmap_id=7)
    attachment = _attachment_model(attachment_id=8, beatmap_id=7, checksum_md5="b" * 32)
    current = _performance_model(
        calculation_id=401,
        score_id=302,
        state=PerformanceCalculationState.COMPLETED,
        calculator_version="3.9.0",
    )
    profile_mismatch = _performance_model(
        calculation_id=402,
        score_id=303,
        state=PerformanceCalculationState.COMPLETED,
        calculator_version="4.0.2",
        formula_profile=FormulaProfile.LEGACY_VANILLA_RANKED,
    )
    stale_file = _performance_model(
        calculation_id=403,
        score_id=304,
        state=PerformanceCalculationState.COMPLETED,
        calculator_version="4.0.2",
        beatmap_file_attachment_id=8,
        beatmap_file_checksum_md5="c" * 32,
    )
    session = FakeQuerySession(
        execute_handler=lambda statement: _execute_from_text(
            statement,
            {
                "FROM score_performance_calculations": FakeResult(current),
                "LEFT OUTER JOIN score_performance_calculations": FakeResult(
                    values=[
                        (score_without_performance, None, attachment),
                        (score_with_mismatch, current, attachment),
                        (score_with_profile_mismatch, profile_mismatch, attachment),
                        (score_with_stale_file, stale_file, attachment),
                    ]
                ),
            },
        )
    )
    factory = FakeSessionFactory(session)
    session_factory = cast("SQLAlchemyQuerySessionFactory", cast("object", factory))
    repository: ScorePerformanceQueryRepository = SQLAlchemyScorePerformanceQueryRepository(
        session_factory
    )

    current_read = await repository.get_current_for_score(score_with_mismatch.id)
    candidates = await repository.select_recalculation_candidates(
        ScorePerformanceCandidateSelection(
            target_calculator_name="rosu-pp-py",
            target_calculator_version="4.0.2",
            target_formula_profile=FormulaProfile.VANILLA_RANKED,
            score_id=None,
            beatmap_id=7,
            user_id=10,
            ruleset=Ruleset.OSU,
            limit=None,
            include_unavailable=False,
        )
    )

    assert current_read is not None
    assert current_read.id == current.id
    assert [candidate.score_id for candidate in candidates.candidates] == [301, 302, 303, 304]
    assert candidates.reason_counts == {
        RecalculationCandidateReason.UNCALCULATED: 1,
        RecalculationCandidateReason.CALCULATOR_VERSION_MISMATCH: 1,
        RecalculationCandidateReason.FORMULA_PROFILE_MISMATCH: 1,
        RecalculationCandidateReason.STALE: 1,
    }
    assert factory.calls == 2
    assert session.closed is True


async def test_score_performance_query_repository_marks_explicit_target_mismatch_stale() -> None:
    """Explicit target checksumとの差分をstale候補にする契約を検証する.

    完了済みcalculationと異なるtarget beatmap file checksumを指定して候補を選択する.
    対象scoreだけがSTALE reasonで返されsessionが閉じることを確認する.

    Returns:
        None: explicit target mismatchのstale判定を検証して呼び出し側へ値を返さずに完了する.
    """
    score = _score_model(score_id=305, user_id=10, beatmap_id=7)
    attachment = _attachment_model(attachment_id=8, beatmap_id=7, checksum_md5="b" * 32)
    current = _performance_model(
        calculation_id=404,
        score_id=305,
        state=PerformanceCalculationState.COMPLETED,
        calculator_version="4.0.2",
        beatmap_file_attachment_id=8,
        beatmap_file_checksum_md5="b" * 32,
    )
    session = FakeQuerySession(
        execute_handler=lambda statement: _execute_from_text(
            statement,
            {
                "LEFT OUTER JOIN score_performance_calculations": FakeResult(
                    values=[(score, current, attachment)]
                ),
            },
        )
    )
    factory = FakeSessionFactory(session)
    session_factory = cast("SQLAlchemyQuerySessionFactory", cast("object", factory))
    repository: ScorePerformanceQueryRepository = SQLAlchemyScorePerformanceQueryRepository(
        session_factory
    )

    candidates = await repository.select_recalculation_candidates(
        ScorePerformanceCandidateSelection(
            target_calculator_name="rosu-pp-py",
            target_calculator_version="4.0.2",
            target_formula_profile=FormulaProfile.VANILLA_RANKED,
            score_id=score.id,
            beatmap_id=7,
            user_id=10,
            ruleset=Ruleset.OSU,
            limit=None,
            include_unavailable=False,
            target_beatmap_file_checksum_md5="d" * 32,
        )
    )

    assert [candidate.score_id for candidate in candidates.candidates] == [305]
    assert candidates.reason_counts == {RecalculationCandidateReason.STALE: 1}
    assert session.closed is True


async def test_score_performance_query_repository_marks_explicit_attachment_stale() -> None:
    """Explicit attachment IDとの差分をstale候補にする契約を検証する.

    完了済みcalculationと異なるtarget beatmap file attachment IDを指定して候補を選択する.
    対象scoreだけがSTALE reasonで返されsessionが閉じることを確認する.

    Returns:
        None: explicit attachment mismatchのstale判定を検証して呼び出し側へ値を返さずに完了する.
    """
    score = _score_model(score_id=306, user_id=10, beatmap_id=7)
    attachment = _attachment_model(attachment_id=8, beatmap_id=7, checksum_md5="b" * 32)
    current = _performance_model(
        calculation_id=405,
        score_id=306,
        state=PerformanceCalculationState.COMPLETED,
        calculator_version="4.0.2",
        beatmap_file_attachment_id=8,
        beatmap_file_checksum_md5="b" * 32,
    )
    session = FakeQuerySession(
        execute_handler=lambda statement: _execute_from_text(
            statement,
            {
                "LEFT OUTER JOIN score_performance_calculations": FakeResult(
                    values=[(score, current, attachment)]
                ),
            },
        )
    )
    factory = FakeSessionFactory(session)
    session_factory = cast("SQLAlchemyQuerySessionFactory", cast("object", factory))
    repository: ScorePerformanceQueryRepository = SQLAlchemyScorePerformanceQueryRepository(
        session_factory
    )

    candidates = await repository.select_recalculation_candidates(
        ScorePerformanceCandidateSelection(
            target_calculator_name="rosu-pp-py",
            target_calculator_version="4.0.2",
            target_formula_profile=FormulaProfile.VANILLA_RANKED,
            score_id=score.id,
            beatmap_id=7,
            user_id=10,
            ruleset=Ruleset.OSU,
            limit=None,
            include_unavailable=False,
            target_beatmap_file_attachment_id=9,
        )
    )

    assert [candidate.score_id for candidate in candidates.candidates] == [306]
    assert candidates.reason_counts == {RecalculationCandidateReason.STALE: 1}
    assert session.closed is True


async def test_beatmap_and_legacy_getscores_queries_are_read_only() -> None:
    """beatmap/getscores query adapterがread-only lookupを提供する契約を検証する.

    beatmapset/beatmap/file attachment/fetch stateが存在する条件でcurrentとlegacy APIを呼び出す.
    ID/checksum/filename lookupが同じmodel情報を返しsessionを閉じることを確認する.

    Returns:
        None: beatmap read結果とread-only session lifecycleを検証して完了する.
    """
    fixture = _score_blob_beatmap_fixture()
    session_factory = cast("SQLAlchemyQuerySessionFactory", cast("object", fixture.factory))
    beatmaps: BeatmapQueryRepository = SQLAlchemyBeatmapQueryRepository(session_factory)
    legacy_getscores: BeatmapScoreListingQueryRepository = (
        SQLAlchemyBeatmapScoreListingQueryRepository(session_factory)
    )

    beatmap_by_id = await beatmaps.get_beatmap(fixture.beatmap.id)
    beatmapset = await beatmaps.get_beatmapset(fixture.beatmapset.id)
    beatmap_by_checksum = await beatmaps.get_beatmap_by_checksum("b" * 32)
    beatmap_by_filename = await beatmaps.get_beatmap_by_filename_in_beatmapset(
        fixture.beatmapset.id,
        "artist - title.osu",
    )
    file_attachment = await beatmaps.get_current_file_attachment(fixture.beatmap.id)
    fetch_state = await beatmaps.get_fetch_state(
        BeatmapFetchTarget(
            target_type=BeatmapFetchTargetKind.METADATA_BY_BEATMAP_ID, target_key="7"
        )
    )
    legacy_by_checksum = await legacy_getscores.find_by_checksum("b" * 32)
    legacy_by_filename = await legacy_getscores.find_by_filename_in_beatmapset(
        fixture.beatmapset.id,
        "artist - title.osu",
    )
    legacy_beatmapset = await legacy_getscores.get_beatmapset(fixture.beatmapset.id)
    legacy_fetch_state = await legacy_getscores.get_fetch_state(
        BeatmapFetchTarget(
            target_type=BeatmapFetchTargetKind.METADATA_BY_BEATMAP_ID, target_key="7"
        )
    )

    assert beatmap_by_id is not None
    assert beatmapset is not None
    assert beatmap_by_checksum is not None
    assert beatmap_by_filename is not None
    assert file_attachment is not None
    assert fetch_state is not None
    assert legacy_by_checksum is not None
    assert legacy_by_filename is not None
    assert legacy_beatmapset is not None
    assert beatmap_by_id.checksum_md5 == "b" * 32
    assert beatmapset.beatmaps[0].id == fixture.beatmap.id
    assert beatmap_by_checksum.id == fixture.beatmap.id
    assert beatmap_by_filename.id == fixture.beatmap.id
    assert file_attachment.id == fixture.attachment.id
    assert file_attachment.blob_id == fixture.blob.id
    assert fetch_state.status is BeatmapFetchState.FRESH
    assert legacy_by_checksum.id == fixture.beatmap.id
    assert legacy_by_filename.id == fixture.beatmap.id
    assert legacy_beatmapset.id == fixture.beatmapset.id
    assert legacy_fetch_state is not None
    assert legacy_fetch_state.status is BeatmapFetchState.FRESH
    assert fixture.session.closed is True


async def test_chat_history_query_repository_returns_display_read_models() -> None:
    """Chat history query adapterが表示用read modelを返す契約を検証する.

    channel/private messageが各SQL結果に1件ずつ存在する条件で履歴read APIを呼び出す.
    message IDとcontentを保持したread modelを返し2回のsession生成後に閉じることを確認する.

    Returns:
        None: chat history mappingとsession lifecycleを検証して呼び出し側へ値を返さずに完了する.
    """
    channel_message = ChannelMessageModel(
        id=101,
        sender_id=1,
        channel_id=10,
        content="hello channel",
        created_at=_NOW,
    )
    private_message = PrivateMessageModel(
        id=202,
        sender_id=1,
        target_user_id=2,
        content="hello pm",
        created_at=_NOW,
    )
    session = FakeQuerySession(
        execute_handler=lambda statement: _execute_from_text(
            statement,
            {
                "channel_messages": FakeResult(values=[channel_message]),
                "private_messages": FakeResult(values=[private_message]),
            },
        )
    )
    factory = FakeSessionFactory(session)
    session_factory = cast("SQLAlchemyQuerySessionFactory", cast("object", factory))
    repository: ChatHistoryQueryRepository = SQLAlchemyChatHistoryQueryRepository(session_factory)

    channel_messages = await repository.list_channel_messages("#osu", limit=20)
    private_messages = await repository.list_private_messages(1, 2, limit=20)

    assert channel_messages[0].id == 101
    assert channel_messages[0].content == "hello channel"
    assert private_messages[0].id == 202
    assert private_messages[0].content == "hello pm"
    assert factory.calls == 2
    assert session.closed is True


def test_sqlalchemy_query_repository_modules_do_not_call_mutation_methods() -> None:
    """SQLAlchemy query moduleがmutation APIを呼ばない境界契約を検証する.

    query package内の全Python moduleをASTとして読み取りsession mutation名へのcallを探索する.
    add/commit/delete/flush/merge/refresh/rollback呼び出しが0件であることを確認する.

    Returns:
        None: read-only boundaryの静的検査を完了して呼び出し側へ値を返さない.
    """
    violations: list[str] = []
    for path in sorted(QUERY_ROOT.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr in {
                "add",
                "commit",
                "delete",
                "flush",
                "merge",
                "refresh",
                "rollback",
            }:
                violations.append(f"{path.relative_to(PROJECT_ROOT)} calls {node.func.attr}()")

    assert violations == []


def test_sqlalchemy_query_repository_modules_do_not_depend_on_command_boundaries() -> None:
    """SQLAlchemy query moduleがcommand boundaryへ依存しない契約を検証する.

    query package内の全Python moduleからabsolute importを抽出してforbidden rootと照合する.
    command interface/implementation/Unit of Workへのimportが0件であることを確認する.

    Returns:
        None: query layer dependency boundaryの静的検査を完了して呼び出し側へ値を返さない.
    """
    forbidden_roots = (
        "osu_server.repositories.interfaces.commands",
        "osu_server.repositories.interfaces.unit_of_work",
        "osu_server.repositories.sqlalchemy.commands",
        "osu_server.repositories.sqlalchemy.unit_of_work",
    )
    violations = [
        f"{path.relative_to(PROJECT_ROOT)} imports {module}"
        for path in sorted(QUERY_ROOT.glob("*.py"))
        for module in _absolute_imports(path)
        for forbidden_root in forbidden_roots
        if module == forbidden_root or module.startswith(f"{forbidden_root}.")
    ]

    assert violations == []


def _missing_get(model_type: type[object], identity: object) -> object | None:
    """未登録model lookupの空結果を返す既定get handlerを提供する.

    Args:
        model_type (type[object]): lookup対象として渡されたmodel型.
        identity (object): lookup対象として渡されたidentity値.

    Returns:
        object | None: 常にNone. fake sessionにfixture handlerがない場合だけ利用する.
    """
    _ = model_type
    _ = identity
    return None


def _empty_execute(statement: Executable) -> FakeResult:
    """未登録statementの空結果を返す既定execute handlerを提供する.

    Args:
        statement (Executable): fake sessionが受け取ったSQLAlchemy statement.

    Returns:
        FakeResult: 値を持たないresult double. fixture handlerがない場合だけ利用する.
    """
    _ = statement
    return FakeResult()


def _identity_get_handler(
    *, user_model: UserModel, role_model: RoleModel
) -> Callable[[type[object], object], object | None]:
    """user/role modelのprimary key lookupを返すhandlerを構築する.

    Args:
        user_model (UserModel): UserModel lookupに一致させるfixture.
        role_model (RoleModel): RoleModel lookupに一致させるfixture.

    Returns:
        Callable[[type[object], object], object | None]: 一致したuserまたはroleを返すget handler.
    """

    def get(model_type: type[object], identity: object) -> object | None:
        """Fixture model型とprimary keyに一致する値を返す.

        Args:
            model_type (type[object]): session getへ渡されたmodel型.
            identity (object): session getへ渡されたprimary key.

        Returns:
            object | None: 一致するuserまたはrole model. 一致しない場合はNone.
        """
        if model_type is UserModel and identity == user_model.id:
            return user_model
        if model_type is RoleModel and identity == role_model.id:
            return role_model
        return None

    return get


def _score_blob_beatmap_get_handler(
    *,
    score_model: ScoreModel,
    blob_model: BlobModel,
    beatmap_model: BeatmapModel,
    beatmapset_model: BeatmapSetModel,
) -> Callable[[type[object], object], object | None]:
    """score/blob/beatmap/beatmapsetのprimary key lookup handlerを構築する.

    Args:
        score_model (ScoreModel): ScoreModel lookupに一致させるfixture.
        blob_model (BlobModel): BlobModel lookupに一致させるfixture.
        beatmap_model (BeatmapModel): BeatmapModel lookupに一致させるfixture.
        beatmapset_model (BeatmapSetModel): BeatmapSetModel lookupに一致させるfixture.

    Returns:
        Callable[[type[object], object], object | None]: 一致したfixture modelを返すget handler.
    """

    def get(model_type: type[object], identity: object) -> object | None:
        """Fixture model型とprimary keyに一致する値を返す.

        Args:
            model_type (type[object]): session getへ渡されたmodel型.
            identity (object): session getへ渡されたprimary key.

        Returns:
            object | None: 一致するscore/blob/beatmap/beatmapset model. 一致しない場合はNone.
        """
        if model_type is ScoreModel and identity == score_model.id:
            return score_model
        if model_type is BlobModel and identity == blob_model.id:
            return blob_model
        if model_type is BeatmapModel and identity == beatmap_model.id:
            return beatmap_model
        if model_type is BeatmapSetModel and identity == beatmapset_model.id:
            return beatmapset_model
        return None

    return get


def _score_blob_beatmap_fixture() -> ScoreBlobBeatmapQueryFixture:
    """score/blob/beatmap query test用の相互参照fixtureを構築する.

    Returns:
        ScoreBlobBeatmapQueryFixture: read handlerと一致するpersistence model群を持つfixture.
    """
    score_model = _score_model()
    blob_model = _blob_model()
    beatmapset_model = _beatmapset_model()
    beatmap_model = _beatmap_model()
    attachment_model = _attachment_model()
    fetch_state_model = _fetch_state_model()
    session = FakeQuerySession(
        get_handler=_score_blob_beatmap_get_handler(
            score_model=score_model,
            blob_model=blob_model,
            beatmap_model=beatmap_model,
            beatmapset_model=beatmapset_model,
        ),
        execute_handler=_score_blob_beatmap_execute_handler(
            score_model=score_model,
            blob_model=blob_model,
            beatmap_model=beatmap_model,
            attachment_model=attachment_model,
            fetch_state_model=fetch_state_model,
        ),
    )
    return ScoreBlobBeatmapQueryFixture(
        score=score_model,
        blob=blob_model,
        beatmapset=beatmapset_model,
        beatmap=beatmap_model,
        attachment=attachment_model,
        fetch_state=fetch_state_model,
        session=session,
        factory=FakeSessionFactory(session),
    )


def _sql_text(statement: Executable) -> str:
    """SQLAlchemy statementをmarker照合用の空白正規化文字列へ変換する.

    Args:
        statement (Executable): fixture handlerが判別するSQLAlchemy statement.

    Returns:
        str: 連続空白を単一spaceへ正規化したSQL text.
    """
    return " ".join(str(statement).split())


def _identity_channel_execute_handler(
    *,
    user_model: UserModel,
    role_model: RoleModel,
    channel_model: ChannelModel,
    override_model: ChannelRoleOverrideModel,
) -> Callable[[Executable], FakeResult]:
    """identity/channel queryごとのfixture結果を返すexecute handlerを構築する.

    Args:
        user_model (UserModel): user queryに返すfixture.
        role_model (RoleModel): role queryに返すfixture.
        channel_model (ChannelModel): channel queryに返すfixture.
        override_model (ChannelRoleOverrideModel): channel role override queryに返すfixture.

    Returns:
        Callable[[Executable], FakeResult]: SQL markerに対応するresult doubleを返すhandler.
    """

    def execute(statement: Executable) -> FakeResult:
        """statementのSQL markerに一致するidentity/channel結果を返す.

        Args:
            statement (Executable): query repositoryが発行したSQLAlchemy statement.

        Returns:
            FakeResult: 一致するfixture result. markerがない場合は空result.
        """
        text = _sql_text(statement)
        fixtures: tuple[tuple[str, FakeResult], ...] = (
            ("FROM user_roles", FakeResult(values=[(user_model.id,)])),
            ("JOIN user_roles", FakeResult(values=[role_model])),
            ("FROM users WHERE users.safe_username", FakeResult(user_model)),
            ("FROM users WHERE users.email", FakeResult(user_model)),
            ("FROM roles WHERE roles.name", FakeResult(role_model)),
            ("FROM channels WHERE channels.name", FakeResult(channel_model)),
            ("FROM channels WHERE channels.channel_type", FakeResult(values=[channel_model])),
            ("FROM channels WHERE channels.auto_join", FakeResult(values=[channel_model])),
            ("FROM channel_role_overrides", FakeResult(values=[override_model])),
        )
        for marker, result in fixtures:
            if marker in text:
                return result
        return FakeResult()

    return execute


def _score_blob_beatmap_execute_handler(
    *,
    score_model: ScoreModel,
    blob_model: BlobModel,
    beatmap_model: BeatmapModel,
    attachment_model: BeatmapFileAttachmentModel,
    fetch_state_model: BeatmapFetchStateModel,
) -> Callable[[Executable], FakeResult]:
    """score/blob/beatmap queryごとのfixture結果を返すexecute handlerを構築する.

    Args:
        score_model (ScoreModel): score checksum queryに返すfixture.
        blob_model (BlobModel): blob SHA-256 queryに返すfixture.
        beatmap_model (BeatmapModel): beatmap lookup queryに返すfixture.
        attachment_model (BeatmapFileAttachmentModel): file attachment queryに返すfixture.
        fetch_state_model (BeatmapFetchStateModel): fetch state queryに返すfixture.

    Returns:
        Callable[[Executable], FakeResult]: SQL markerに対応するresult doubleを返すhandler.
    """

    def execute(statement: Executable) -> FakeResult:
        """statementのSQL markerに一致するscore/blob/beatmap結果を返す.

        Args:
            statement (Executable): query repositoryが発行したSQLAlchemy statement.

        Returns:
            FakeResult: 一致するfixture result. markerがない場合は空result.
        """
        text = _sql_text(statement)
        fixtures: tuple[tuple[str, FakeResult], ...] = (
            ("FROM scores WHERE scores.online_checksum", FakeResult(score_model)),
            ("FROM blobs WHERE blobs.sha256", FakeResult(blob_model)),
            ("JOIN beatmap_file_attachments", FakeResult(beatmap_model)),
            ("FROM beatmaps WHERE beatmaps.beatmapset_id", FakeResult(values=[beatmap_model])),
            ("FROM beatmaps WHERE beatmaps.checksum_md5", FakeResult(beatmap_model)),
            ("FROM beatmap_file_attachments", FakeResult(attachment_model)),
            ("FROM beatmap_fetch_states", FakeResult(fetch_state_model)),
        )
        for marker, result in fixtures:
            if marker in text:
                return result
        return FakeResult()

    return execute


def _execute_from_text(statement: Executable, fixtures: dict[str, FakeResult]) -> FakeResult:
    """SQL text内のmarkerに対応するfixture resultを返す.

    Args:
        statement (Executable): marker照合対象のSQLAlchemy statement.
        fixtures (dict[str, FakeResult]): SQL markerからresult doubleへの対応表.

    Returns:
        FakeResult: 最初に一致したresult. 一致しない場合は空result.
    """
    text = str(statement)
    for marker, result in fixtures.items():
        if marker in text:
            return result
    return FakeResult()


def _absolute_imports(path: Path) -> set[str]:
    """Python moduleからabsolute import名を抽出する.

    Args:
        path (Path): AST解析するquery repository moduleのpath.

    Returns:
        set[str]: __future__を除くabsolute importとfrom importの完全名.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    modules.discard("__future__")
    return modules


def _user_model() -> UserModel:
    """Identity query testで使う固定user persistence modelを構築する.

    Returns:
        UserModel: username/email/activity timestampを持つQueryUser fixture.
    """
    return UserModel(
        id=1,
        username="QueryUser",
        safe_username="queryuser",
        email="query@example.com",
        password_hash="hash",
        country="JP",
        created_at=_NOW,
        updated_at=_NOW,
        latest_activity_at=_LATEST_ACTIVITY_AT,
    )


def _role_model() -> RoleModel:
    """Role query testで使うdefault role persistence modelを構築する.

    Returns:
        RoleModel: 読み取り対象のDefault role fixture.
    """
    return RoleModel(id=2, name="Default", permissions=1, position=1)


def _channel_model() -> ChannelModel:
    """Channel query testで使うauto join public channel modelを構築する.

    Returns:
        ChannelModel: #osu名とpublic channel種別を持つfixture.
    """
    return ChannelModel(
        id=10,
        name="#osu",
        topic="General",
        channel_type=ChannelType.PUBLIC.value,
        auto_join=True,
        rate_limit_messages=None,
        rate_limit_window=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _score_model(
    *,
    score_id: int = 300,
    user_id: int = 1,
    beatmap_id: int = 7,
) -> ScoreModel:
    """Score query testで使う指定identityのscore persistence modelを構築する.

    Args:
        score_id (int): 構築するscoreのprimary key.
        user_id (int): scoreを所有するuserのprimary key.
        beatmap_id (int): scoreが記録されたbeatmapのprimary key.

    Returns:
        ScoreModel: osu vanilla score値とonline checksumを持つfixture.
    """
    return ScoreModel(
        id=score_id,
        user_id=user_id,
        beatmap_id=beatmap_id,
        beatmap_checksum="b" * 32,
        online_checksum="online",
        ruleset=Ruleset.OSU.value,
        playstyle=Playstyle.VANILLA.value,
        mods=0,
        n300=300,
        n100=10,
        n50=1,
        geki=0,
        katu=0,
        miss=0,
        score=123456,
        max_combo=321,
        accuracy=98.5,
        grade=Grade.A.value,
        passed=True,
        perfect=False,
        client_version="b20260614",
        submitted_at=_NOW,
        beatmap_status_at_submission="ranked",
        replay_view_count=0,
    )


def _replay_model(*, score_id: int) -> ReplayModel:
    """Personal best query testで使うscore連結replay modelを構築する.

    Args:
        score_id (int): replayを関連付けるscoreのprimary key.

    Returns:
        ReplayModel: 指定score IDと固定blob metadataを持つfixture.
    """
    return ReplayModel(
        id=601,
        score_id=score_id,
        blob_id=400,
        checksum_sha256="c" * 64,
        byte_size=256,
        created_at=_NOW,
    )


def _performance_model(
    *,
    calculation_id: int,
    score_id: int,
    state: PerformanceCalculationState,
    calculator_version: str,
    formula_profile: FormulaProfile = FormulaProfile.VANILLA_RANKED,
    beatmap_file_attachment_id: int = 8,
    beatmap_file_checksum_md5: str = "b" * 32,
) -> ScorePerformanceCalculationModel:
    """Performance query testで使うcalculation persistence modelを構築する.

    Args:
        calculation_id (int): calculationのprimary key.
        score_id (int): calculationが対象にするscoreのprimary key.
        state (PerformanceCalculationState): calculationのlifecycle状態.
        calculator_version (str): calculationを生成したcalculator version.
        formula_profile (FormulaProfile): calculationに適用したformula profile.
        beatmap_file_attachment_id (int): calculation時に使ったbeatmap file attachment ID.
        beatmap_file_checksum_md5 (str): calculation時に使ったbeatmap file MD5 checksum.

    Returns:
        ScorePerformanceCalculationModel: 指定stateに応じたcurrent calculation fixture.
    """
    return ScorePerformanceCalculationModel(
        id=calculation_id,
        score_id=score_id,
        state=state.value,
        is_current=True,
        pp=Decimal("123.456789") if state is PerformanceCalculationState.COMPLETED else None,
        star_rating=Decimal("5.43210") if state is PerformanceCalculationState.COMPLETED else None,
        calculator_name="rosu-pp-py",
        calculator_version=calculator_version,
        formula_profile=formula_profile.value,
        beatmap_file_attachment_id=(
            beatmap_file_attachment_id if state is PerformanceCalculationState.COMPLETED else None
        ),
        beatmap_file_checksum_md5=(
            beatmap_file_checksum_md5 if state is PerformanceCalculationState.COMPLETED else None
        ),
        unavailable_reason=None,
        claim_owner=None,
        claim_expires_at=None,
        attempt_count=0,
        calculated_at=_NOW if state.is_terminal else None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _blob_model() -> BlobModel:
    """Blob query testで使う固定content-addressed blob modelを構築する.

    Returns:
        BlobModel: SHA-256とlocal storage metadataを持つfixture.
    """
    return BlobModel(
        id=400,
        sha256="a" * 64,
        byte_size=128,
        content_type="application/octet-stream",
        storage_backend="local",
        storage_key="objects/a",
        created_at=_NOW,
    )


def _beatmapset_model() -> BeatmapSetModel:
    """Beatmap query testで使うranked beatmapset modelを構築する.

    Returns:
        BeatmapSetModel: official metadataがverified済みのfixture.
    """
    return BeatmapSetModel(
        id=6,
        artist="artist",
        title="title",
        creator="mapper",
        artist_unicode="artist",
        title_unicode="title",
        source_text="",
        tags="",
        direct_search_text="artist title mapper diff",
        official_status=BeatmapRankStatus.RANKED.value,
        official_status_source=BeatmapMetadataSource.OFFICIAL.value,
        official_status_verified=True,
        last_fetched_at=_NOW,
        next_refresh_at=None,
        search_document_version=1,
        search_document_updated_at=_NOW,
    )


def _beatmap_model() -> BeatmapModel:
    """Beatmap query testで使うranked osu beatmap modelを構築する.

    Returns:
        BeatmapModel: beatmapset ID/checksum/verified statusを持つfixture.
    """
    return BeatmapModel(
        id=7,
        beatmapset_id=6,
        checksum_md5="b" * 32,
        mode=BeatmapMode.OSU.value,
        version="Insane",
        total_length=120,
        hit_length=110,
        max_combo=500,
        bpm=None,
        cs=None,
        od=None,
        ar=None,
        hp=None,
        difficulty_rating=None,
        official_status=BeatmapRankStatus.RANKED.value,
        official_status_source=BeatmapMetadataSource.OFFICIAL.value,
        official_status_verified=BeatmapSourceVerification.VERIFIED
        is BeatmapSourceVerification.VERIFIED,
        local_status_override=None,
        last_fetched_at=_NOW,
        next_refresh_at=None,
    )


def _attachment_model(
    *,
    attachment_id: int = 8,
    beatmap_id: int = 7,
    checksum_md5: str = "b" * 32,
) -> BeatmapFileAttachmentModel:
    """Beatmap file lookup testで使うattachment modelを構築する.

    Args:
        attachment_id (int): attachmentのprimary key.
        beatmap_id (int): attachmentが属するbeatmapのprimary key.
        checksum_md5 (str): attachmentとverified fileのMD5 checksum.

    Returns:
        BeatmapFileAttachmentModel: 指定identityと固定blob metadataを持つfixture.
    """
    return BeatmapFileAttachmentModel(
        id=attachment_id,
        beatmap_id=beatmap_id,
        blob_id=400,
        checksum_md5=checksum_md5,
        verified_md5=checksum_md5,
        source="osu_current",
        original_filename="artist - title.osu",
        fetched_at=_NOW,
        verified_at=_NOW,
    )


def _fetch_state_model() -> BeatmapFetchStateModel:
    """Beatmap metadata lookup testで使うfresh fetch state modelを構築する.

    Returns:
        BeatmapFetchStateModel: beatmap ID metadata targetがFRESHのfixture.
    """
    return BeatmapFetchStateModel(
        target_type=BeatmapFetchTargetKind.METADATA_BY_BEATMAP_ID.value,
        target_key="7",
        status=BeatmapFetchState.FRESH.value,
        attempt_count=1,
        last_error=None,
        pending_since=None,
        last_attempted_at=_NOW,
    )
