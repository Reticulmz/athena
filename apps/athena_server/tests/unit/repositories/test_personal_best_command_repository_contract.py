"""PersonalBest command repositoryのupsert契約を検証するtests."""

from datetime import UTC, datetime

import pytest

from osu_server.domain.beatmaps import BeatmapRankStatus
from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.personal_best import (
    LeaderboardCategory,
    PersonalBestScope,
)
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.repositories.interfaces.commands.personal_bests import UpsertPersonalBest
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory


@pytest.mark.asyncio
async def test_personal_best_upsert_keeps_existing_score_on_tie_or_lower_value() -> None:
    """同値または低いranking valueが既存PersonalBestを置換しないことを検証する.

    同じscopeへ同順位の別scoreをupsertし,
    最初に保存したscore IDがcurrent entryのまま残ることを確認する.

    Returns:
        None: tie時の既存entry保持を検証して完了し, 呼び出し側へ値を返さない.
    """
    factory = InMemoryUnitOfWorkFactory()

    async with factory() as uow:
        first = await uow.scores.create(_score(online_checksum="first", score=1000))
        second = await uow.scores.create(_score(online_checksum="second", score=1000))
        assert first.id is not None
        assert second.id is not None

        scope = _scope()
        created = await uow.personal_bests.upsert_if_better(
            UpsertPersonalBest(scope=scope, score_id=first.id, ranking_value=1000)
        )
        tied = await uow.personal_bests.upsert_if_better(
            UpsertPersonalBest(scope=scope, score_id=second.id, ranking_value=1000)
        )
        await uow.commit()

    assert created.score_id == first.id
    assert tied.score_id == first.id


@pytest.mark.asyncio
async def test_personal_best_upsert_replaces_existing_score_on_higher_value() -> None:
    """より高いranking valueが同じscopeのPersonalBestを置換することを検証する.

    初期entryの後に高得点scoreをupsertし,
    返却entryが新しいscore IDとranking valueを持つことを確認する.

    Returns:
        None: 高い値の置換結果を検証して完了し, 呼び出し側へ値を返さない.
    """
    factory = InMemoryUnitOfWorkFactory()

    async with factory() as uow:
        first = await uow.scores.create(_score(online_checksum="first", score=1000))
        second = await uow.scores.create(_score(online_checksum="second", score=1200))
        assert first.id is not None
        assert second.id is not None

        scope = _scope()
        _ = await uow.personal_bests.upsert_if_better(
            UpsertPersonalBest(scope=scope, score_id=first.id, ranking_value=1000)
        )
        replaced = await uow.personal_bests.upsert_if_better(
            UpsertPersonalBest(scope=scope, score_id=second.id, ranking_value=1200)
        )
        await uow.commit()

    assert replaced.score_id == second.id
    assert replaced.ranking_value == 1200


def _scope() -> PersonalBestScope:
    """fixture用のglobal PersonalBest scopeを構築する.

    Returns:
        PersonalBestScope: user, beatmap, ruleset, playstyle, categoryを固定した比較scope.
    """
    return PersonalBestScope(
        user_id=1000,
        beatmap_id=1,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        category=LeaderboardCategory.GLOBAL,
    )


def _score(*, online_checksum: str, score: int) -> Score:
    """PersonalBest比較用の保存前Score fixtureを構築する.

    Args:
        online_checksum (str): scoreを一意に識別するonline checksum.
        score (int): PersonalBestのranking valueに対応する得点.

    Returns:
        Score: 指定したchecksumと得点を持つ保存前のscore.
    """
    return Score(
        id=None,
        user_id=1000,
        beatmap_id=1,
        beatmap_checksum="abc123",
        online_checksum=online_checksum,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        mods=ModCombination.none(),
        n300=100,
        n100=10,
        n50=5,
        geki=0,
        katu=0,
        miss=2,
        score=score,
        max_combo=99,
        accuracy=0.95,
        grade=Grade.A,
        passed=True,
        perfect=False,
        client_version="20240101",
        submitted_at=datetime.now(UTC),
        beatmap_status_at_submission=BeatmapRankStatus.RANKED,
    )
