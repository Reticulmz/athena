"""Replay download accounting command policy tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

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

_OLD_ACTIVITY = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
_NOW = datetime(2026, 7, 8, 12, 0, 0, tzinfo=UTC)
_LATER = datetime(2026, 7, 8, 12, 1, 0, tzinfo=UTC)


@dataclass(slots=True)
class _ReplayViewClaim:
    viewer_user_id: int
    score_id: int
    ttl_seconds: int


@dataclass(slots=True)
class _LatestActivityClaim:
    viewer_user_id: int
    ttl_seconds: int


@dataclass(slots=True)
class _RecordingAccountingGate:
    replay_view_result: bool = True
    latest_activity_result: bool = True
    claims: list[_ReplayViewClaim] = field(default_factory=list)
    activity_claims: list[_LatestActivityClaim] = field(default_factory=list)

    async def claim_replay_view(
        self,
        viewer_user_id: int,
        score_id: int,
        ttl_seconds: int,
    ) -> bool:
        self.claims.append(
            _ReplayViewClaim(
                viewer_user_id=viewer_user_id,
                score_id=score_id,
                ttl_seconds=ttl_seconds,
            )
        )
        return self.replay_view_result

    async def claim_latest_activity(self, viewer_user_id: int, ttl_seconds: int) -> bool:
        self.activity_claims.append(
            _LatestActivityClaim(
                viewer_user_id=viewer_user_id,
                ttl_seconds=ttl_seconds,
            )
        )
        return self.latest_activity_result


class _FailingReplayViewGate:
    async def claim_replay_view(
        self,
        viewer_user_id: int,
        score_id: int,
        ttl_seconds: int,
    ) -> bool:
        del viewer_user_id, score_id, ttl_seconds
        raise RuntimeError("temporary gate unavailable")

    async def claim_latest_activity(self, viewer_user_id: int, ttl_seconds: int) -> bool:
        del viewer_user_id, ttl_seconds
        return True


class _FailingLatestActivityGate:
    async def claim_replay_view(
        self,
        viewer_user_id: int,
        score_id: int,
        ttl_seconds: int,
    ) -> bool:
        del viewer_user_id, score_id, ttl_seconds
        return True

    async def claim_latest_activity(self, viewer_user_id: int, ttl_seconds: int) -> bool:
        del viewer_user_id, ttl_seconds
        raise RuntimeError("activity gate unavailable")


@dataclass(slots=True)
class _Clock:
    now: float = 1_000.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.asyncio
async def test_non_owner_download_with_open_cooldown_increments_once() -> None:
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
async def test_duplicate_cooldown_gate_failure_is_treated_as_open() -> None:
    factory = InMemoryUnitOfWorkFactory()
    owner = await _create_user(factory, username="Owner")
    viewer = await _create_user(factory, username="Viewer")
    score = await _create_score(factory, owner_user_id=owner.id)
    score_id = _require_score_id(score)
    use_case = ReplayDownloadAccountingUseCase(
        unit_of_work_factory=factory,
        accounting_gate=_FailingReplayViewGate(),
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


@pytest.mark.asyncio
async def test_latest_activity_gate_failure_is_treated_as_open() -> None:
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


async def _create_user(
    factory: InMemoryUnitOfWorkFactory,
    *,
    username: str,
) -> User:
    async with factory() as uow:
        user = await uow.users.create(_user(username=username))
        await uow.commit()
        return user


async def _create_score(
    factory: InMemoryUnitOfWorkFactory,
    *,
    owner_user_id: int,
) -> Score:
    async with factory() as uow:
        score = await uow.scores.create(_score(owner_user_id=owner_user_id))
        await uow.commit()
        return score


async def _replay_view_count(factory: InMemoryUnitOfWorkFactory, score_id: int) -> int:
    async with factory() as uow:
        score = await uow.scores.get_by_id(score_id)
    if score is None:
        msg = f"score not found: {score_id}"
        raise AssertionError(msg)
    return score.replay_view_count


async def _latest_activity_at(factory: InMemoryUnitOfWorkFactory, user_id: int) -> datetime:
    user = factory.snapshot().users_by_id.get(user_id)
    if user is None:
        msg = f"user not found: {user_id}"
        raise AssertionError(msg)
    return user.latest_activity_at


def _user(*, username: str) -> User:
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


def _score(*, owner_user_id: int) -> Score:
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
        beatmap_status_at_submission="ranked",
        leaderboard_eligible_at_submission=True,
    )


def _require_score_id(score: Score) -> int:
    if score.id is None:
        raise AssertionError("score id was not assigned")
    return score.id
