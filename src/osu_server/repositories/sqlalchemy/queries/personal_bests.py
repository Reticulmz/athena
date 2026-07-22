"""SQLAlchemyでstable getscores用personal bestをread-onlyで取得するquery repositoryを提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from osu_server.domain.compatibility.stable.getscores import GetscoresPersonalBest
from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.repositories.sqlalchemy.models.personal_best import PersonalBestModel
from osu_server.repositories.sqlalchemy.models.score import ReplayModel, ScoreModel
from osu_server.repositories.sqlalchemy.models.user import UserModel

if TYPE_CHECKING:
    from sqlalchemy.sql.base import Executable

    from osu_server.domain.scores.personal_best import LeaderboardCategory
    from osu_server.repositories.sqlalchemy.queries._shared import SQLAlchemyQuerySessionFactory

_ROW_TUPLE_LENGTH = 4


class SQLAlchemyPersonalBestQueryRepository:
    """短命なSQLAlchemy read sessionでpersonal best projectionを取得する.

    Attributes:
        _session_factory (SQLAlchemyQuerySessionFactory): queryごとに閉じるread sessionのfactory.
    """

    _session_factory: SQLAlchemyQuerySessionFactory

    def __init__(self, session_factory: SQLAlchemyQuerySessionFactory) -> None:
        """読み取り用session factoryを保持してrepositoryを初期化する.

        Args:
            session_factory (SQLAlchemyQuerySessionFactory): query用の非同期read session factory.

        Returns:
            None: 読み取り用session factoryを保持したrepository instanceを初期化する.

        Notes:
            初期化時にはsessionを生成せず、personal best projectionを変更しない.
        """
        self._session_factory = session_factory

    async def get_personal_best(
        self,
        *,
        user_id: int,
        beatmap_id: int,
        ruleset: Ruleset,
        playstyle: Playstyle,
        category: LeaderboardCategory,
    ) -> GetscoresPersonalBest | None:
        """UserのBeatmap別personal bestをstable getscores read modelとして取得する.

        Args:
            user_id (int): personal bestを検索するUserの永続ID.
            beatmap_id (int): personal bestを検索するBeatmapの永続ID.
            ruleset (Ruleset): Scoreを絞り込むruleset.
            playstyle (Playstyle): Scoreを絞り込むplaystyle.
            category (LeaderboardCategory): personal best projectionを絞り込むleaderboard category.

        Returns:
            GetscoresPersonalBest | None: rankとreplay有無を含むstable getscores用read model.
            対象projectionがない場合はNone.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.
            ValueError: result Score modelのrulesetまたはplaystyleをdomain enumへ変換できない場合.

        Notes:
            queryは最大1rowを返し、projectionとScoreの永続stateを変更しない.
        """
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    _personal_best_statement(
                        user_id=user_id,
                        beatmap_id=beatmap_id,
                        ruleset=ruleset,
                        playstyle=playstyle,
                        category=category,
                    )
                )
            ).all()

        for score_model, username, has_replay, rank in _iter_personal_best_rows(rows):
            return _score_listing_from_models(
                score_model=score_model,
                username=username,
                has_replay=has_replay,
                rank=rank,
            )

        return None


def _personal_best_statement(
    *,
    user_id: int,
    beatmap_id: int,
    ruleset: Ruleset,
    playstyle: Playstyle,
    category: LeaderboardCategory,
) -> Executable:
    """Personal best Score、表示User名、replay有無、rankを取得するstatementを構築する.

    Args:
        user_id (int): personal bestを検索するUserの永続ID.
        beatmap_id (int): personal bestを検索するBeatmapの永続ID.
        ruleset (Ruleset): Scoreを絞り込むruleset.
        playstyle (Playstyle): Scoreを絞り込むplaystyle.
        category (LeaderboardCategory): personal best projectionを絞り込むleaderboard category.

    Returns:
        Executable: 最大1rowのScore、username、has_replay、rankを返すSELECT statement.

    Notes:
        rankは同一Beatmap、ruleset、playstyle、category内でranking valueが大きいrowの数に1を加える.
    """
    better_personal_best = aliased(PersonalBestModel)
    replay_exists = (
        select(ReplayModel.id).where(ReplayModel.score_id == ScoreModel.id).limit(1).exists()
    )
    rank = (
        select(func.count(better_personal_best.id) + 1)
        .where(
            better_personal_best.beatmap_id == PersonalBestModel.beatmap_id,
            better_personal_best.ruleset == PersonalBestModel.ruleset,
            better_personal_best.playstyle == PersonalBestModel.playstyle,
            better_personal_best.category == PersonalBestModel.category,
            better_personal_best.ranking_value > PersonalBestModel.ranking_value,
        )
        .scalar_subquery()
    )
    return (
        select(
            ScoreModel,
            UserModel.username,
            replay_exists.label("has_replay"),
            rank.label("rank"),
        )
        .join(PersonalBestModel, PersonalBestModel.score_id == ScoreModel.id)
        .join(UserModel, UserModel.id == ScoreModel.user_id)
        .where(
            PersonalBestModel.user_id == user_id,
            PersonalBestModel.beatmap_id == beatmap_id,
            PersonalBestModel.ruleset == ruleset.value,
            PersonalBestModel.playstyle == playstyle.value,
            PersonalBestModel.category == category.value,
        )
        .limit(1)
    )


def _iter_personal_best_rows(
    rows: object,
) -> list[tuple[ScoreModel, str, bool, int]]:
    """SQLAlchemy result rowを型検証済みpersonal best tupleへ正規化する.

    Args:
        rows (object): tuple形式またはattribute形式のSQLAlchemy result row list.

    Returns:
        list[tuple[ScoreModel, str, bool, int]]: Score、username、replay有無、rankの順のtuple.
        必須fieldの型が一致しないrowは含めない.

    Notes:
        has_replayはtruthinessでboolへ変換し、tuple形式とnamed row形式の両方を受け入れる.
    """
    result: list[tuple[ScoreModel, str, bool, int]] = []
    for row in cast("list[object]", rows):
        if isinstance(row, tuple):
            values = cast("tuple[object, ...]", row)
            if (
                len(values) == _ROW_TUPLE_LENGTH
                and isinstance(values[0], ScoreModel)
                and isinstance(values[1], str)
                and isinstance(values[3], int)
            ):
                result.append((values[0], values[1], bool(values[2]), values[3]))
            continue

        score_model = getattr(row, "ScoreModel", None)
        username = getattr(row, "username", None)
        has_replay = getattr(row, "has_replay", None)
        rank = getattr(row, "rank", None)
        if (
            isinstance(score_model, ScoreModel)
            and isinstance(username, str)
            and isinstance(rank, int)
        ):
            result.append((score_model, username, bool(has_replay), rank))

    return result


def _score_listing_from_models(
    *,
    score_model: ScoreModel,
    username: str,
    has_replay: bool,
    rank: int,
) -> GetscoresPersonalBest:
    """Score modelとprojection fieldをstable getscores用personal bestへ変換する.

    Args:
        score_model (ScoreModel): personal bestに対応する永続Score model.
        username (str): Score ownerの表示名.
        has_replay (bool): replay attachmentが存在するかを示すflag.
        rank (int): category内で計算済みの順位.

    Returns:
        GetscoresPersonalBest: stable getscores responseが必要とするScore listing read model.

    Raises:
        ValueError: score_modelのrulesetまたはplaystyleをdomain enumへ変換できない場合.

    Notes:
        Score fieldは変換せずに転記し、rulesetとplaystyleだけをdomain enumへ変換する.
    """
    return GetscoresPersonalBest(
        score_id=score_model.id,
        user_id=score_model.user_id,
        username=username,
        beatmap_id=score_model.beatmap_id,
        ruleset=Ruleset(score_model.ruleset),
        playstyle=Playstyle(score_model.playstyle),
        score=score_model.score,
        max_combo=score_model.max_combo,
        n50=score_model.n50,
        n100=score_model.n100,
        n300=score_model.n300,
        miss=score_model.miss,
        katu=score_model.katu,
        geki=score_model.geki,
        perfect=score_model.perfect,
        mods=score_model.mods,
        rank=rank,
        submitted_at=score_model.submitted_at,
        has_replay=has_replay,
    )
