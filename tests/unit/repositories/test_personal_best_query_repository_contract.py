from datetime import UTC, datetime

import pytest

from osu_server.domain.identity.users import User
from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.personal_best import (
    LeaderboardCategory,
    PersonalBestScope,
)
from osu_server.domain.scores.replay import Replay
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.repositories.interfaces.commands.personal_bests import UpsertPersonalBest
from osu_server.repositories.memory.queries.personal_bests import (
    InMemoryPersonalBestQueryRepository,
)
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory

_NOW = datetime(2026, 6, 17, tzinfo=UTC)


@pytest.mark.asyncio
async def test_personal_best_query_returns_current_score_listing() -> None:
    factory = InMemoryUnitOfWorkFactory()

    async with factory() as uow:
        user = await uow.users.create(_user())
        score = await uow.scores.create(_score(user_id=user.id))
        assert score.id is not None
        _ = await uow.personal_bests.upsert_if_better(
            UpsertPersonalBest(
                scope=_scope(user_id=user.id, beatmap_id=score.beatmap_id),
                score_id=score.id,
                ranking_value=score.score,
            )
        )
        _ = await uow.replays.create(_replay(score_id=score.id))
        await uow.commit()

    repository = InMemoryPersonalBestQueryRepository(factory)

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
    assert personal_best.n300 == score.n300
    assert personal_best.mods == score.mods.to_persistence_bitmask()
    assert personal_best.submitted_at == _NOW
    assert personal_best.rank == 1
    assert personal_best.has_replay is True


@pytest.mark.asyncio
async def test_personal_best_query_ranks_against_same_scope_personal_bests() -> None:
    factory = InMemoryUnitOfWorkFactory()

    async with factory() as uow:
        target_user = await uow.users.create(_user(username="PlayerOne"))
        higher_user = await uow.users.create(_user(username="HigherRank"))
        target_score = await uow.scores.create(
            _score(
                user_id=target_user.id,
                score=900_000,
                online_checksum="target-online-checksum",
            )
        )
        higher_score = await uow.scores.create(
            _score(
                user_id=higher_user.id,
                score=950_000,
                online_checksum="higher-online-checksum",
            )
        )
        assert target_score.id is not None
        assert higher_score.id is not None
        _ = await uow.personal_bests.upsert_if_better(
            UpsertPersonalBest(
                scope=_scope(user_id=target_user.id, beatmap_id=target_score.beatmap_id),
                score_id=target_score.id,
                ranking_value=target_score.score,
            )
        )
        _ = await uow.personal_bests.upsert_if_better(
            UpsertPersonalBest(
                scope=_scope(user_id=higher_user.id, beatmap_id=higher_score.beatmap_id),
                score_id=higher_score.id,
                ranking_value=higher_score.score,
            )
        )
        await uow.commit()

    repository = InMemoryPersonalBestQueryRepository(factory)

    personal_best = await repository.get_personal_best(
        user_id=target_user.id,
        beatmap_id=target_score.beatmap_id,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        category=LeaderboardCategory.GLOBAL,
    )

    assert personal_best is not None
    assert personal_best.score_id == target_score.id
    assert personal_best.rank == 2


@pytest.mark.asyncio
async def test_personal_best_query_returns_none_when_projection_is_missing() -> None:
    factory = InMemoryUnitOfWorkFactory()
    repository = InMemoryPersonalBestQueryRepository(factory)

    personal_best = await repository.get_personal_best(
        user_id=1,
        beatmap_id=2,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        category=LeaderboardCategory.GLOBAL,
    )

    assert personal_best is None


def _user(*, username: str = "PlayerOne") -> User:
    safe_username = username.lower()
    return User(
        id=0,
        username=username,
        safe_username=safe_username,
        email=f"{safe_username}@example.com",
        password_hash="hash",
        country="JP",
        created_at=_NOW,
        updated_at=_NOW,
    )


def _scope(*, user_id: int, beatmap_id: int) -> PersonalBestScope:
    return PersonalBestScope(
        user_id=user_id,
        beatmap_id=beatmap_id,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        category=LeaderboardCategory.GLOBAL,
    )


def _score(
    *,
    user_id: int,
    score: int = 987_654,
    online_checksum: str = "online-checksum",
) -> Score:
    return Score(
        id=None,
        user_id=user_id,
        beatmap_id=75,
        beatmap_checksum="abc123",
        online_checksum=online_checksum,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        mods=ModCombination.from_bitmask(24),
        n300=300,
        n100=2,
        n50=1,
        geki=5,
        katu=4,
        miss=3,
        score=score,
        max_combo=1_234,
        accuracy=98.76,
        grade=Grade.S,
        passed=True,
        perfect=True,
        client_version="b20260617",
        submitted_at=_NOW,
        beatmap_status_at_submission="ranked",
    )


def _replay(*, score_id: int) -> Replay:
    return Replay(
        id=None,
        score_id=score_id,
        blob_id=1,
        checksum_sha256="d" * 64,
        byte_size=256,
    )
