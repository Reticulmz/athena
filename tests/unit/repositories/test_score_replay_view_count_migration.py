from pathlib import Path
from typing import cast

from sqlalchemy import BigInteger, CheckConstraint, Column, Table

from osu_server.repositories.sqlalchemy.models import ScoreModel

MIGRATION_PATH = Path("alembic/versions/20260707_0100_add_score_replay_view_count.py")


def _column(table: Table, name: str) -> Column[object]:
    return cast("Column[object]", table.c[name])


def _check_constraints(table: Table) -> set[str]:
    return {
        str(constraint.name)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }


def test_score_replay_view_count_migration_adds_non_null_default_and_constraint() -> None:
    migration = MIGRATION_PATH.read_text()

    assert 'revision: str = "20260707_0100"' in migration
    assert 'down_revision: str | None = "20260630_0300"' in migration
    assert '"replay_view_count"' in migration
    assert "sa.BigInteger()" in migration
    assert 'server_default=sa.text("0")' in migration
    assert "UPDATE scores" in migration
    assert "replay_view_count = 0" in migration
    assert "ck_scores_replay_view_count_non_negative" in migration
    assert "replay_view_count >= 0" in migration
    assert 'op.drop_column("scores", "replay_view_count")' in migration


def test_score_model_metadata_exposes_non_null_non_negative_replay_view_count() -> None:
    table = cast("Table", ScoreModel.__table__)

    replay_view_count = _column(table, "replay_view_count")
    assert isinstance(replay_view_count.type, BigInteger)
    assert not replay_view_count.nullable
    assert replay_view_count.default is not None
    assert replay_view_count.server_default is not None
    assert "ck_scores_replay_view_count_non_negative" in _check_constraints(table)
