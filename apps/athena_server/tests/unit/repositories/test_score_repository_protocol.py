"""ScoreCommandRepository Protocolの型契約を検証するtests."""

from datetime import UTC, datetime

import pytest

from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.repositories.interfaces.commands.beatmaps import BeatmapSubmissionCounts
from osu_server.repositories.interfaces.commands.scores import (
    ScoreCommandRepository,
)


class ConcreteScoreRepository:
    """ScoreCommandRepository Protocolを満たす最小のtyped fakeを提供する.

    各methodはrepository interfaceの入出力型だけを固定し, 永続化状態を持たない.
    """

    async def create(self, score: Score) -> Score:
        """受け取ったScoreをcreate結果として返す.

        Args:
            score (Score): interfaceの戻り値型を検証するscore.

        Returns:
            Score: 入力と同じscore.
        """
        return score

    async def exists_by_online_checksum(self, _checksum: str) -> bool:
        """Checksum存在確認のbool戻り値を提供する.

        Args:
            _checksum (str): interfaceに渡されるonline checksum.

        Returns:
            bool: fakeが常に返す不存在結果.
        """
        return False

    async def get_by_online_checksum(self, _checksum: str) -> Score | None:
        """Checksum lookupのoptional Score戻り値を提供する.

        Args:
            _checksum (str): interfaceに渡されるonline checksum.

        Returns:
            Score | None: fakeが常に返す未発見結果.
        """
        return None

    async def get_by_id(self, _score_id: int) -> Score | None:
        """ID lookupのoptional Score戻り値を提供する.

        Args:
            _score_id (int): interfaceに渡されるscore ID.

        Returns:
            Score | None: fakeが常に返す未発見結果.
        """
        return None

    async def increment_replay_view_count(self, _score_id: int) -> bool:
        """Replay view count更新のbool戻り値を提供する.

        Args:
            _score_id (int): interfaceに渡されるscore ID.

        Returns:
            bool: fakeが常に返す更新失敗結果.
        """
        return False

    async def count_submissions_for_beatmap(self, _beatmap_id: int) -> BeatmapSubmissionCounts:
        """beatmap提出数の空集計を提供する.

        Args:
            _beatmap_id (int): interfaceに渡されるbeatmap ID.

        Returns:
            BeatmapSubmissionCounts: play数とpass数が0の集計.
        """
        return BeatmapSubmissionCounts(play_count=0, pass_count=0)

    async def list_current_stats_scores_for_user(
        self,
        user_id: int,
        *,
        ruleset: Ruleset,
        playstyle: Playstyle,
    ) -> tuple[Score, ...]:
        """CurrentUserStats対象scoreの空listingを提供する.

        Args:
            user_id (int): scoreを絞り込むuser ID.
            ruleset (Ruleset): scoreを絞り込むruleset.
            playstyle (Playstyle): scoreを絞り込むplaystyle.

        Returns:
            tuple[Score, ...]: fakeが常に返す空のscore listing.
        """
        _ = user_id
        _ = ruleset
        _ = playstyle
        return ()

    async def list_leaderboard_rebuild_candidates_for_user(
        self,
        user_id: int,
    ) -> tuple[Score, ...]:
        """user単位leaderboard rebuild候補の空listingを提供する.

        Args:
            user_id (int): rebuild候補を絞り込むuser ID.

        Returns:
            tuple[Score, ...]: fakeが常に返す空のcandidate listing.
        """
        _ = user_id
        return ()

    async def list_leaderboard_rebuild_candidates_for_beatmap_ids(
        self,
        beatmap_ids: tuple[int, ...],
    ) -> tuple[Score, ...]:
        """beatmap群単位leaderboard rebuild候補の空listingを提供する.

        Args:
            beatmap_ids (tuple[int, ...]): rebuild候補を絞り込むbeatmap ID群.

        Returns:
            tuple[Score, ...]: fakeが常に返す空のcandidate listing.
        """
        _ = beatmap_ids
        return ()


def test_score_repository_protocol_compliance() -> None:
    """Typed fakeがScoreCommandRepository runtime Protocolに適合することを検証する.

    最小implementationを生成し, runtime_checkable Protocolのisinstance判定が真になることを確認する.

    Returns:
        None: Protocol適合性を検証して完了し, 呼び出し側へ値を返さない.
    """
    repo = ConcreteScoreRepository()
    assert isinstance(repo, ScoreCommandRepository)


@pytest.mark.asyncio
async def test_create_returns_score_with_id() -> None:
    """Create contractがScore型の結果を返すことを検証する.

    保存前Scoreをtyped fakeへ渡し,
    ID生成の有無ではなくinterfaceで約束するScore型が返ることを確認する.

    Returns:
        None: create結果の型を検証して完了し, 呼び出し側へ値を返さない.
    """
    repo = ConcreteScoreRepository()
    score = Score(
        id=None,
        user_id=1,
        beatmap_id=100,
        beatmap_checksum="abc123",
        online_checksum="def456",
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        mods=ModCombination.none(),
        n300=100,
        n100=0,
        n50=0,
        geki=0,
        katu=0,
        miss=0,
        score=1000000,
        max_combo=100,
        accuracy=1.0,
        grade=Grade.X,
        passed=True,
        perfect=True,
        client_version="b20240101",
        submitted_at=datetime.now(UTC),
    )
    result = await repo.create(score)
    assert isinstance(result, Score)


@pytest.mark.asyncio
async def test_exists_by_online_checksum_returns_bool() -> None:
    """checksum存在確認contractがboolを返すことを検証する.

    任意checksumでtyped fakeを呼び出し, 存在状態がbool型として観測できることを確認する.

    Returns:
        None: exists結果の型を検証して完了し, 呼び出し側へ値を返さない.
    """
    repo = ConcreteScoreRepository()
    result = await repo.exists_by_online_checksum("test_checksum")
    assert isinstance(result, bool)


@pytest.mark.asyncio
async def test_get_by_id_returns_optional_score() -> None:
    """ID lookup contractがScoreまたはNoneを返すことを検証する.

    任意IDでtyped fakeを呼び出し, 未発見を表すNoneがoptional Score型の範囲にあることを確認する.

    Returns:
        None: ID lookup結果の型を検証して完了し, 呼び出し側へ値を返さない.
    """
    repo = ConcreteScoreRepository()
    result = await repo.get_by_id(1)
    assert result is None or isinstance(result, Score)


@pytest.mark.asyncio
async def test_get_by_online_checksum_returns_optional_score() -> None:
    """Checksum lookup contractがScoreまたはNoneを返すことを検証する.

    任意checksumでtyped fakeを呼び出し,
    未発見を表すNoneがoptional Score型の範囲にあることを確認する.

    Returns:
        None: checksum lookup結果の型を検証して完了し, 呼び出し側へ値を返さない.
    """
    repo = ConcreteScoreRepository()
    result = await repo.get_by_online_checksum("test_checksum")
    assert result is None or isinstance(result, Score)
