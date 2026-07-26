"""replay download会計command policyのUnit testを検証する."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import pytest
import structlog.testing

from osu_server.domain.beatmaps import BeatmapRankStatus
from osu_server.domain.identity.users import User
from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.infrastructure.state.memory.replay_download_accounting_gate import (
    InMemoryReplayDownloadAccountingGate,
)
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.scores.replay_download_accounting import (
    LatestActivityAccountingOutcome,
    ReplayDownloadAccountingInput,
    ReplayDownloadAccountingUseCase,
    ReplayViewAccountingOutcome,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from contextlib import AbstractAsyncContextManager
    from typing import Self

    from osu_server.repositories.interfaces.unit_of_work import UnitOfWork

_OLD_ACTIVITY = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
_NOW = datetime(2026, 7, 8, 12, 0, 0, tzinfo=UTC)
_LATER = datetime(2026, 7, 8, 12, 1, 0, tzinfo=UTC)


@dataclass(slots=True)
class _ReplayViewClaim:
    """recording gateへ渡したreplay閲覧claimを表す.

    Attributes:
        viewer_user_id (int): replayを閲覧するuserのID.
        score_id (int): 閲覧対象scoreのID.
        ttl_seconds (int): duplicate抑止に使うclaimの有効秒数.
    """

    viewer_user_id: int
    score_id: int
    ttl_seconds: int


@dataclass(slots=True)
class _LatestActivityClaim:
    """recording gateへ渡したlatest activity claimを表す.

    Attributes:
        viewer_user_id (int): activityを更新するuserのID.
        ttl_seconds (int): activity更新を抑止するclaimの有効秒数.
    """

    viewer_user_id: int
    ttl_seconds: int


@dataclass(slots=True)
class _ReplayViewRelease:
    """operation失敗時にreleaseするreplay閲覧claimを表す.

    Attributes:
        viewer_user_id (int): claimをreleaseする閲覧userのID.
        score_id (int): claimをreleaseするscoreのID.
    """

    viewer_user_id: int
    score_id: int


@dataclass(slots=True)
class _RecordingAccountingGate:
    """claimとrelease呼び出しを記録する成功可能なaccounting gate fakeを提供する.

    Attributes:
        replay_view_result (bool): replay閲覧claimで返す可否.
        latest_activity_result (bool): latest activity claimで返す可否.
        claims (list[_ReplayViewClaim]): 受け取ったreplay閲覧claim列.
        activity_claims (list[_LatestActivityClaim]): 受け取ったactivity claim列.
        releases (list[_ReplayViewRelease]): 受け取ったreplay閲覧release列.
        activity_releases (list[int]): 受け取ったactivity releaseのuser ID列.
    """

    replay_view_result: bool = True
    latest_activity_result: bool = True
    claims: list[_ReplayViewClaim] = field(default_factory=list)
    activity_claims: list[_LatestActivityClaim] = field(default_factory=list)
    releases: list[_ReplayViewRelease] = field(default_factory=list)
    activity_releases: list[int] = field(default_factory=list)

    async def claim_replay_view(
        self,
        viewer_user_id: int,
        score_id: int,
        ttl_seconds: int,
    ) -> bool:
        """replay閲覧claimを記録し、設定済みの可否を返す.

        Args:
            viewer_user_id (int): replayを閲覧するuserのID.
            score_id (int): 閲覧対象scoreのID.
            ttl_seconds (int): duplicate抑止に使う有効秒数.

        Returns:
            bool: replay閲覧countを進められるかを表す設定済みの結果.
        """
        self.claims.append(
            _ReplayViewClaim(
                viewer_user_id=viewer_user_id,
                score_id=score_id,
                ttl_seconds=ttl_seconds,
            )
        )
        return self.replay_view_result

    async def release_replay_view(self, viewer_user_id: int, score_id: int) -> None:
        """replay閲覧claimのreleaseを記録する.

        Args:
            viewer_user_id (int): release対象の閲覧user ID.
            score_id (int): release対象のscore ID.

        Returns:
            None: releaseを記録して、呼び出し側へ値を返さずに完了する.
        """
        self.releases.append(
            _ReplayViewRelease(
                viewer_user_id=viewer_user_id,
                score_id=score_id,
            )
        )

    async def claim_latest_activity(self, viewer_user_id: int, ttl_seconds: int) -> bool:
        """Latest activity claimを記録し、設定済みの可否を返す.

        Args:
            viewer_user_id (int): activityを更新するuserのID.
            ttl_seconds (int): throttleに使う有効秒数.

        Returns:
            bool: latest activityを更新できるかを表す設定済みの結果.
        """
        self.activity_claims.append(
            _LatestActivityClaim(
                viewer_user_id=viewer_user_id,
                ttl_seconds=ttl_seconds,
            )
        )
        return self.latest_activity_result

    async def release_latest_activity(self, viewer_user_id: int) -> None:
        """Latest activity claimのreleaseを記録する.

        Args:
            viewer_user_id (int): release対象のuser ID.

        Returns:
            None: release対象userを記録して、呼び出し側へ値を返さずに完了する.
        """
        self.activity_releases.append(viewer_user_id)


class _FailingReplayViewGate:
    """replay閲覧cooldown claimだけを失敗させるaccounting gate fakeを提供する."""

    async def claim_replay_view(
        self,
        viewer_user_id: int,
        score_id: int,
        ttl_seconds: int,
    ) -> bool:
        """replay閲覧claim時に一時的なgate障害を送出する.

        Args:
            viewer_user_id (int): 未使用の閲覧user ID.
            score_id (int): 未使用のscore ID.
            ttl_seconds (int): 未使用のclaim有効秒数.

        Raises:
            RuntimeError: cooldown gateが利用不能であることを再現する場合.
        """
        del viewer_user_id, score_id, ttl_seconds
        raise RuntimeError("temporary gate unavailable")

    async def release_replay_view(self, viewer_user_id: int, score_id: int) -> None:
        """失敗したreplay閲覧claimのreleaseをno-opで受け入れる.

        Args:
            viewer_user_id (int): 未使用の閲覧user ID.
            score_id (int): 未使用のscore ID.

        Returns:
            None: 引数を破棄して、呼び出し側へ値を返さずに完了する.
        """
        del viewer_user_id, score_id

    async def claim_latest_activity(self, viewer_user_id: int, ttl_seconds: int) -> bool:
        """Latest activity claimは成功として受け入れる.

        Args:
            viewer_user_id (int): 未使用のactivity対象user ID.
            ttl_seconds (int): 未使用のclaim有効秒数.

        Returns:
            bool: latest activity policyを続行させるTrue.
        """
        del viewer_user_id, ttl_seconds
        return True

    async def release_latest_activity(self, viewer_user_id: int) -> None:
        """Latest activity claimのreleaseをno-opで受け入れる.

        Args:
            viewer_user_id (int): 未使用のactivity対象user ID.

        Returns:
            None: 引数を破棄して、呼び出し側へ値を返さずに完了する.
        """
        del viewer_user_id


class _FailingLatestActivityGate:
    """latest activity cooldown claimだけを失敗させるaccounting gate fakeを提供する."""

    async def claim_replay_view(
        self,
        viewer_user_id: int,
        score_id: int,
        ttl_seconds: int,
    ) -> bool:
        """replay閲覧claimは成功として受け入れる.

        Args:
            viewer_user_id (int): 未使用の閲覧user ID.
            score_id (int): 未使用のscore ID.
            ttl_seconds (int): 未使用のclaim有効秒数.

        Returns:
            bool: replay閲覧count policyを続行させるTrue.
        """
        del viewer_user_id, score_id, ttl_seconds
        return True

    async def release_replay_view(self, viewer_user_id: int, score_id: int) -> None:
        """replay閲覧claimのreleaseをno-opで受け入れる.

        Args:
            viewer_user_id (int): 未使用の閲覧user ID.
            score_id (int): 未使用のscore ID.

        Returns:
            None: 引数を破棄して、呼び出し側へ値を返さずに完了する.
        """
        del viewer_user_id, score_id

    async def claim_latest_activity(self, viewer_user_id: int, ttl_seconds: int) -> bool:
        """Latest activity claim時に一時的なgate障害を送出する.

        Args:
            viewer_user_id (int): 未使用のactivity対象user ID.
            ttl_seconds (int): 未使用のclaim有効秒数.

        Raises:
            RuntimeError: activity gateが利用不能であることを再現する場合.
        """
        del viewer_user_id, ttl_seconds
        raise RuntimeError("activity gate unavailable")

    async def release_latest_activity(self, viewer_user_id: int) -> None:
        """Latest activity claimのreleaseをno-opで受け入れる.

        Args:
            viewer_user_id (int): 未使用のactivity対象user ID.

        Returns:
            None: 引数を破棄して、呼び出し側へ値を返さずに完了する.
        """
        del viewer_user_id


@dataclass(slots=True)
class _FailingScoreRepository:
    """replay閲覧count更新を失敗させるscore repository fakeを提供する."""

    async def increment_replay_view_count(self, score_id: int) -> bool:
        """sensitive値を含む内部例外を送出してsanitizationを検証可能にする.

        Args:
            score_id (int): 未使用の更新対象score ID.

        Raises:
            RuntimeError: raw replay pathとtokenを含む永続化障害を再現する場合.
        """
        del score_id
        raise RuntimeError("raw replay bytes: /tmp/replay.osr?score=1&token=secret")


@dataclass(slots=True)
class _FailingUsersRepository:
    """latest activity更新を失敗させるusers repository fakeを提供する."""

    async def touch_latest_activity(self, user_id: int, occurred_at: datetime) -> bool:
        """sensitive値を含む内部例外を送出してsanitizationを検証可能にする.

        Args:
            user_id (int): 未使用の更新対象user ID.
            occurred_at (datetime): 未使用のactivity発生時刻.

        Raises:
            RuntimeError: passwordとreplay pathを含む永続化障害を再現する場合.
        """
        del user_id, occurred_at
        raise RuntimeError("password=secret /var/lib/replays/private.osr")


@dataclass(slots=True)
class _FailingOperationUnitOfWork:
    """replay閲覧とactivity更新を失敗させるUnit of Work fakeを提供する.

    Attributes:
        scores (_FailingScoreRepository): replay閲覧count更新で例外を送出するrepository.
        users (_FailingUsersRepository): latest activity更新で例外を送出するrepository.
        committed (bool): 最後にcommitされた状態かを表すflag.
    """

    scores: _FailingScoreRepository = field(default_factory=_FailingScoreRepository)
    users: _FailingUsersRepository = field(default_factory=_FailingUsersRepository)
    committed: bool = False

    async def __aenter__(self) -> Self:
        """失敗用repositoryを持つUnit of Work contextへ入る.

        Returns:
            Self: 操作を実行する同じUnit of Work fake.
        """
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        """Unit of Work contextから副作用なく退出する.

        Args:
            exc_type (type[BaseException] | None): context内で送出された例外型.
            exc (BaseException | None): context内で送出された例外instance.
            traceback (object): context内例外のtraceback情報.

        Returns:
            None: 例外情報を破棄して、呼び出し側へ値を返さずに完了する.
        """
        del exc_type, exc, traceback

    async def commit(self) -> None:
        """commit呼び出しを状態flagへ記録する.

        Returns:
            None: committedをTrueにして、呼び出し側へ値を返さずに完了する.
        """
        self.committed = True

    async def rollback(self) -> None:
        """rollback呼び出しを状態flagへ記録する.

        Returns:
            None: committedをFalseにして、呼び出し側へ値を返さずに完了する.
        """
        self.committed = False


@dataclass(slots=True)
class _FailingOperationUnitOfWorkFactory:
    """失敗用Unit of Workを呼び出しごとに生成して記録するfactoryを提供する.

    Attributes:
        units (list[_FailingOperationUnitOfWork]): 生成済みUnit of Work fake列.
    """

    units: list[_FailingOperationUnitOfWork] = field(default_factory=list)

    def __call__(self) -> AbstractAsyncContextManager[UnitOfWork]:
        """失敗用repositoryを持つ新しいUnit of Work contextを返す.

        Returns:
            AbstractAsyncContextManager[UnitOfWork]: protocolにcastした新規の失敗用context.
        """
        unit = _FailingOperationUnitOfWork()
        self.units.append(unit)
        return cast("AbstractAsyncContextManager[UnitOfWork]", unit)


@dataclass(slots=True)
class _Clock:
    """固定時刻を返すcooldown gate用clock fakeを提供する.

    Attributes:
        now (float): time functionが返す固定時刻.
    """

    now: float = 1_000.0

    def __call__(self) -> float:
        """設定済みの固定時刻を返す.

        Returns:
            float: cooldown判定に使う現在時刻のfake値.
        """
        return self.now


@pytest.mark.asyncio
async def test_non_owner_download_with_open_cooldown_increments_once() -> None:
    """non-ownerのopen cooldown閲覧がcountとactivityを一度ずつ更新する契約を検証する.

    所有者と別のviewer、claim可能なgateを用意する条件で、replay view countが1になり、viewerの
    latest activityと両cooldown claimが観測できることを確認する.

    Returns:
        None: count、activity、gate呼び出しを検証して、呼び出し側へ値を返さずに完了する.
    """
    factory = InMemoryUnitOfWorkFactory()
    owner = await _create_user(factory, username="Owner")
    viewer = await _create_user(factory, username="Viewer")
    gate = _RecordingAccountingGate()
    score = await _create_score(factory, owner_user_id=owner.id)
    score_id = _require_score_id(score)
    use_case = ReplayDownloadAccountingUseCase(
        unit_of_work_factory=factory,
        accounting_gate=gate,
    )

    result = await use_case.execute(
        ReplayDownloadAccountingInput(
            score_id=score_id,
            score_owner_user_id=owner.id,
            viewer_user_id=viewer.id,
            occurred_at=_NOW,
        )
    )

    assert result.replay_view_outcome is ReplayViewAccountingOutcome.INCREMENTED
    assert result.latest_activity_outcome is LatestActivityAccountingOutcome.TOUCHED
    assert await _replay_view_count(factory, score_id) == 1
    assert await _latest_activity_at(factory, viewer.id) == _NOW
    assert gate.claims == [
        _ReplayViewClaim(
            viewer_user_id=viewer.id,
            score_id=score_id,
            ttl_seconds=86_400,
        )
    ]
    assert gate.activity_claims == [
        _LatestActivityClaim(
            viewer_user_id=viewer.id,
            ttl_seconds=300,
        )
    ]


@pytest.mark.asyncio
async def test_self_view_skips_count_but_touches_latest_activity() -> None:
    """self-viewが閲覧countを増やさずactivityだけを更新する契約を検証する.

    score所有者自身がdownloadする条件で、SKIPPED_SELF_VIEWとTOUCHEDのoutcome、0件のreplay
    claim、更新済みactivityが観測できることを確認する.

    Returns:
        None: self-view分岐のcount非更新とactivity更新を検証して、呼び出し側へ値を返さずに完了する.
    """
    factory = InMemoryUnitOfWorkFactory()
    owner = await _create_user(factory, username="Owner")
    gate = _RecordingAccountingGate()
    score = await _create_score(factory, owner_user_id=owner.id)
    score_id = _require_score_id(score)
    use_case = ReplayDownloadAccountingUseCase(
        unit_of_work_factory=factory,
        accounting_gate=gate,
    )

    result = await use_case.execute(
        ReplayDownloadAccountingInput(
            score_id=score_id,
            score_owner_user_id=owner.id,
            viewer_user_id=owner.id,
            occurred_at=_NOW,
        )
    )

    assert result.replay_view_outcome is ReplayViewAccountingOutcome.SKIPPED_SELF_VIEW
    assert result.latest_activity_outcome is LatestActivityAccountingOutcome.TOUCHED
    assert await _replay_view_count(factory, score_id) == 0
    assert await _latest_activity_at(factory, owner.id) == _NOW
    assert gate.claims == []
    assert gate.activity_claims == [
        _LatestActivityClaim(
            viewer_user_id=owner.id,
            ttl_seconds=300,
        )
    ]


@pytest.mark.asyncio
async def test_duplicate_same_viewer_same_score_within_cooldown_is_suppressed() -> None:
    """同じviewerとscoreのcooldown内再試行を抑止する契約を検証する.

    固定clockのまま同じscoreを二度downloadする条件で、初回だけcountとactivityを更新し、二回目が
    SKIPPED_DUPLICATEとTHROTTLEDになってstateを増やさないことを確認する.

    Returns:
        None: duplicate抑止後のoutcomeとstateを検証して、呼び出し側へ値を返さずに完了する.
    """
    factory = InMemoryUnitOfWorkFactory()
    clock = _Clock()
    gate = InMemoryReplayDownloadAccountingGate(time_func=clock)
    owner = await _create_user(factory, username="Owner")
    viewer = await _create_user(factory, username="Viewer")
    score = await _create_score(factory, owner_user_id=owner.id)
    score_id = _require_score_id(score)
    use_case = ReplayDownloadAccountingUseCase(
        unit_of_work_factory=factory,
        accounting_gate=gate,
    )
    input_data = ReplayDownloadAccountingInput(
        score_id=score_id,
        score_owner_user_id=owner.id,
        viewer_user_id=viewer.id,
        occurred_at=_NOW,
    )
    later_input_data = ReplayDownloadAccountingInput(
        score_id=score_id,
        score_owner_user_id=owner.id,
        viewer_user_id=viewer.id,
        occurred_at=_LATER,
    )

    first_result = await use_case.execute(input_data)
    second_result = await use_case.execute(later_input_data)

    assert first_result.replay_view_outcome is ReplayViewAccountingOutcome.INCREMENTED
    assert first_result.latest_activity_outcome is LatestActivityAccountingOutcome.TOUCHED
    assert second_result.replay_view_outcome is ReplayViewAccountingOutcome.SKIPPED_DUPLICATE
    assert second_result.latest_activity_outcome is LatestActivityAccountingOutcome.THROTTLED
    assert await _replay_view_count(factory, score_id) == 1
    assert await _latest_activity_at(factory, viewer.id) == _NOW


@pytest.mark.asyncio
async def test_duplicate_cooldown_hit_can_still_touch_latest_activity() -> None:
    """replay閲覧duplicateでもactivity claimがopenならactivityを更新する契約を検証する.

    replay view claimだけがFalseを返すgateを使う条件で、閲覧countは0のままSKIPPED_DUPLICATEとなり、
    viewerのlatest activityはTOUCHEDとなることを確認する.

    Returns:
        None: replay countとactivity policyの独立性を検証して、呼び出し側へ値を返さずに完了する.
    """
    factory = InMemoryUnitOfWorkFactory()
    owner = await _create_user(factory, username="Owner")
    viewer = await _create_user(factory, username="Viewer")
    score = await _create_score(factory, owner_user_id=owner.id)
    score_id = _require_score_id(score)
    gate = _RecordingAccountingGate(replay_view_result=False)
    use_case = ReplayDownloadAccountingUseCase(
        unit_of_work_factory=factory,
        accounting_gate=gate,
    )

    result = await use_case.execute(
        ReplayDownloadAccountingInput(
            score_id=score_id,
            score_owner_user_id=owner.id,
            viewer_user_id=viewer.id,
            occurred_at=_NOW,
        )
    )

    assert result.replay_view_outcome is ReplayViewAccountingOutcome.SKIPPED_DUPLICATE
    assert result.latest_activity_outcome is LatestActivityAccountingOutcome.TOUCHED
    assert await _replay_view_count(factory, score_id) == 0
    assert await _latest_activity_at(factory, viewer.id) == _NOW


@pytest.mark.asyncio
async def test_duplicate_cooldown_gate_failure_fails_closed_without_increment() -> None:
    """Replay cooldown gate障害がcountをfail-closedする契約を検証する.

    replay view claimでRuntimeErrorを送出するgateを使う条件で、FAILED outcome、未増加のcount、
    更新済みactivity、およびoperator向けのsanitized logが観測できることを確認する.

    Returns:
        None: gate障害時のfail-closed結果とlogを検証して、呼び出し側へ値を返さずに完了する.
    """
    factory = InMemoryUnitOfWorkFactory()
    owner = await _create_user(factory, username="Owner")
    viewer = await _create_user(factory, username="Viewer")
    score = await _create_score(factory, owner_user_id=owner.id)
    score_id = _require_score_id(score)
    use_case = ReplayDownloadAccountingUseCase(
        unit_of_work_factory=factory,
        accounting_gate=_FailingReplayViewGate(),
    )

    with structlog.testing.capture_logs() as logs:
        result = await use_case.execute(
            ReplayDownloadAccountingInput(
                score_id=score_id,
                score_owner_user_id=owner.id,
                viewer_user_id=viewer.id,
                occurred_at=_NOW,
            )
        )

    assert result.replay_view_outcome is ReplayViewAccountingOutcome.FAILED
    assert result.latest_activity_outcome is LatestActivityAccountingOutcome.TOUCHED
    assert await _replay_view_count(factory, score_id) == 0
    assert await _latest_activity_at(factory, viewer.id) == _NOW
    assert [entry["event"] for entry in logs] == [
        "replay_download_accounting_cooldown_gate_failed"
    ]
    assert logs[0]["operation"] == "cooldown_gate"
    assert logs[0]["outcome"] == "failed_closed"
    assert logs[0]["exception_type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_latest_activity_gate_failure_is_treated_as_open() -> None:
    """Latest activity gate障害がopenとしてactivity更新を続ける契約を検証する.

    activity claimでRuntimeErrorを送出するgateを使う条件で、viewerのlatest activityが更新され、
    TOUCHED outcomeが観測できることを確認する.

    Returns:
        None: activity gate障害時のopen扱いを検証して、呼び出し側へ値を返さずに完了する.
    """
    factory = InMemoryUnitOfWorkFactory()
    owner = await _create_user(factory, username="Owner")
    viewer = await _create_user(factory, username="Viewer")
    score = await _create_score(factory, owner_user_id=owner.id)
    score_id = _require_score_id(score)
    use_case = ReplayDownloadAccountingUseCase(
        unit_of_work_factory=factory,
        accounting_gate=_FailingLatestActivityGate(),
    )

    result = await use_case.execute(
        ReplayDownloadAccountingInput(
            score_id=score_id,
            score_owner_user_id=owner.id,
            viewer_user_id=viewer.id,
            occurred_at=_NOW,
        )
    )

    assert result.latest_activity_outcome is LatestActivityAccountingOutcome.TOUCHED
    assert await _latest_activity_at(factory, viewer.id) == _NOW


@pytest.mark.asyncio
async def test_operation_failures_are_distinguishable_and_sanitized() -> None:
    """repository操作障害が区別可能かつsanitizedなoperator logになる契約を検証する.

    replay countとlatest activityのrepositoryが各々RuntimeErrorを送出する条件で、両outcomeが
    FAILED、operation別log、claim release、
    およびsensitive値を含まないlogが観測できることを確認する.

    Returns:
        None: 操作別のfailure result、release、sanitized logを検証して、呼び出し側へ値を返さずに
            完了する.
    """
    factory = _FailingOperationUnitOfWorkFactory()
    gate = _RecordingAccountingGate()
    use_case = ReplayDownloadAccountingUseCase(
        unit_of_work_factory=factory,
        accounting_gate=gate,
    )

    with structlog.testing.capture_logs() as logs:
        result = await use_case.execute(
            ReplayDownloadAccountingInput(
                score_id=123,
                score_owner_user_id=10,
                viewer_user_id=20,
                occurred_at=_NOW,
            )
        )

    assert result.replay_view_outcome is ReplayViewAccountingOutcome.FAILED
    assert result.latest_activity_outcome is LatestActivityAccountingOutcome.FAILED
    assert [entry["event"] for entry in logs] == [
        "replay_download_accounting_replay_view_failed",
        "replay_download_accounting_latest_activity_failed",
    ]
    assert {entry["operation"] for entry in logs} == {
        "replay_view_count",
        "latest_activity",
    }
    assert {entry["score_id"] for entry in logs} == {123}
    assert {entry["viewer_user_id"] for entry in logs} == {20}
    assert {entry["score_owner_user_id"] for entry in logs} == {10}
    assert {entry["outcome"] for entry in logs} == {"failed"}
    assert {entry["exception_type"] for entry in logs} == {"RuntimeError"}
    assert gate.releases == [_ReplayViewRelease(viewer_user_id=20, score_id=123)]
    assert gate.activity_releases == [20]
    assert _logs_do_not_expose_sensitive_values(logs)


@pytest.mark.asyncio
async def test_gate_failures_are_operator_visible_and_sanitized() -> None:
    """gate障害がoperatorへ見え、sensitive値を漏らさない契約を検証する.

    latest activity gateがRuntimeErrorを送出する条件で、TOUCHED outcomeとactivity_gateのopened
    log、およびsensitive値を含まないlogが観測できることを確認する.

    Returns:
        None: operator向けgate障害logの可視性とsanitizationを検証して、呼び出し側へ値を返さずに
            完了する.
    """
    factory = InMemoryUnitOfWorkFactory()
    owner = await _create_user(factory, username="Owner")
    viewer = await _create_user(factory, username="Viewer")
    score = await _create_score(factory, owner_user_id=owner.id)
    score_id = _require_score_id(score)
    use_case = ReplayDownloadAccountingUseCase(
        unit_of_work_factory=factory,
        accounting_gate=_FailingLatestActivityGate(),
    )

    with structlog.testing.capture_logs() as logs:
        result = await use_case.execute(
            ReplayDownloadAccountingInput(
                score_id=score_id,
                score_owner_user_id=owner.id,
                viewer_user_id=viewer.id,
                occurred_at=_NOW,
            )
        )

    assert result.latest_activity_outcome is LatestActivityAccountingOutcome.TOUCHED
    assert [entry["event"] for entry in logs] == [
        "replay_download_accounting_activity_gate_failed"
    ]
    assert logs[0]["operation"] == "activity_gate"
    assert logs[0]["outcome"] == "opened"
    assert logs[0]["exception_type"] == "RuntimeError"
    assert _logs_do_not_expose_sensitive_values(logs)


async def _create_user(
    factory: InMemoryUnitOfWorkFactory,
    *,
    username: str,
) -> User:
    """Replay accounting test用userを作成してcommitする.

    Args:
        factory (InMemoryUnitOfWorkFactory): userを永続化するmemory Unit of Work factory.
        username (str): 作成するuserの表示名.

    Returns:
        User: repositoryがIDを割り当てた作成済みuser.
    """
    async with factory() as uow:
        user = await uow.users.create(_user(username=username))
        await uow.commit()
        return user


async def _create_score(
    factory: InMemoryUnitOfWorkFactory,
    *,
    owner_user_id: int,
) -> Score:
    """Replay accounting対象のscoreを作成してcommitする.

    Args:
        factory (InMemoryUnitOfWorkFactory): scoreを永続化するmemory Unit of Work factory.
        owner_user_id (int): score所有userのID.

    Returns:
        Score: repositoryがIDを割り当てた作成済みscore.
    """
    async with factory() as uow:
        score = await uow.scores.create(_score(owner_user_id=owner_user_id))
        await uow.commit()
        return score


async def _replay_view_count(factory: InMemoryUnitOfWorkFactory, score_id: int) -> int:
    """永続化済みscoreのreplay view countを取得する.

    Args:
        factory (InMemoryUnitOfWorkFactory): scoreを読み出すmemory Unit of Work factory.
        score_id (int): 取得対象scoreのID.

    Returns:
        int: scoreに記録されたreplay閲覧数.

    Raises:
        AssertionError: 指定scoreがmemory repositoryに存在しない場合.
    """
    async with factory() as uow:
        score = await uow.scores.get_by_id(score_id)
    if score is None:
        msg = f"score not found: {score_id}"
        raise AssertionError(msg)
    return score.replay_view_count


async def _latest_activity_at(factory: InMemoryUnitOfWorkFactory, user_id: int) -> datetime:
    """Memory stateに保存されたuserのlatest activityを取得する.

    Args:
        factory (InMemoryUnitOfWorkFactory): user snapshotを取得するmemory Unit of Work factory.
        user_id (int): 取得対象userのID.

    Returns:
        datetime: userに記録されたlatest activity時刻.

    Raises:
        AssertionError: 指定userがmemory stateに存在しない場合.
    """
    user = factory.snapshot().users_by_id.get(user_id)
    if user is None:
        msg = f"user not found: {user_id}"
        raise AssertionError(msg)
    return user.latest_activity_at


def _user(*, username: str) -> User:
    """Old latest activityを持つtest用userを作成する.

    Args:
        username (str): user名とemail local partに使う表示名.

    Returns:
        User: replay accounting対象として利用できるtest用user.
    """
    return User(
        id=0,
        username=username,
        safe_username=User.normalize_username(username),
        email=f"{User.normalize_username(username)}@example.com",
        password_hash="$argon2id$hash",
        country="JP",
        created_at=_OLD_ACTIVITY,
        updated_at=_OLD_ACTIVITY,
        latest_activity_at=_OLD_ACTIVITY,
    )


def _logs_do_not_expose_sensitive_values(logs: Sequence[Mapping[str, object]]) -> bool:
    """Operator logがsensitiveなreplay値を含まないかを判定する.

    Args:
        logs (Sequence[Mapping[str, object]]): structlog captureから得たlog entry列.

    Returns:
        bool: forbidden path、token、password、raw replay fragmentが一つもない場合はTrue.
    """
    rendered = repr(logs)
    forbidden_fragments = (
        "raw replay bytes",
        "password=",
        "token=",
        "/tmp/",
        "/var/",
        ".osr",
        "secret",
    )
    return all(fragment not in rendered for fragment in forbidden_fragments)


def _score(*, owner_user_id: int) -> Score:
    """Replay accounting対象として利用するtest用scoreを作成する.

    Args:
        owner_user_id (int): scoreの所有user ID.

    Returns:
        Score: ranked、pass済み、leaderboard対象のtest用score.
    """
    return Score(
        id=None,
        user_id=owner_user_id,
        beatmap_id=1,
        beatmap_checksum="beatmap-checksum",
        online_checksum=f"online-{owner_user_id}",
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        mods=ModCombination.none(),
        n300=100,
        n100=10,
        n50=5,
        geki=0,
        katu=0,
        miss=2,
        score=500000,
        max_combo=99,
        accuracy=0.95,
        grade=Grade.A,
        passed=True,
        perfect=False,
        client_version="20240101",
        submitted_at=_NOW,
        beatmap_status_at_submission=BeatmapRankStatus.RANKED,
        leaderboard_eligible_at_submission=True,
    )


def _require_score_id(score: Score) -> int:
    """永続化済みscoreから必須のIDを取り出す.

    Args:
        score (Score): ID割り当て済みであることを期待するscore.

    Returns:
        int: scoreに割り当てられたID.

    Raises:
        AssertionError: score IDがまだ割り当てられていない場合.
    """
    if score.id is None:
        raise AssertionError("score id was not assigned")
    return score.id
