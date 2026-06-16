"""Tests for SQLAlchemy score performance command repository."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from osu_server.domain.scores.performance import FormulaProfile, PerformanceCalculationState
from osu_server.repositories.interfaces.commands.score_performance import (
    ClaimScorePerformanceCalculation,
    CompleteScorePerformanceCalculation,
    CreateScorePerformanceCalculation,
)
from osu_server.repositories.sqlalchemy.commands.score_performance import (
    SQLAlchemyScorePerformanceCommandRepository,
)
from osu_server.repositories.sqlalchemy.models.score_performance import (
    ScorePerformanceCalculationModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.base import Executable

_NOW = datetime(2026, 6, 16, 0, 0, 0, tzinfo=UTC)


class FakeResult:
    """Minimal SQLAlchemy scalar result double."""

    def __init__(self, value: object | None) -> None:
        self._value: object | None = value

    def scalar_one_or_none(self) -> object | None:
        return self._value


class FakeSession:
    """AsyncSession-shaped fake for command repository mutation tests."""

    def __init__(
        self,
        *,
        execute_results: list[object | None] | None = None,
        get_results: dict[tuple[type[object], object], object] | None = None,
    ) -> None:
        self.execute_results: list[object | None] = execute_results or []
        self.get_results: dict[tuple[type[object], object], object] = get_results or {}
        self.added: list[object] = []
        self.flush_calls: int = 0
        self.refresh_calls: int = 0
        self.commit_calls: int = 0
        self.rollback_calls: int = 0
        self._next_performance_id: int = 100

    async def execute(self, statement: Executable) -> FakeResult:
        _ = statement
        value = self.execute_results.pop(0) if self.execute_results else None
        return FakeResult(value)

    async def get(self, model_type: type[object], identity: object) -> object | None:
        return self.get_results.get((model_type, identity))

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        self.flush_calls += 1
        for instance in self.added:
            if (
                isinstance(instance, ScorePerformanceCalculationModel)
                and getattr(instance, "id", None) is None
            ):
                instance.id = self._next_performance_id
                self._next_performance_id += 1
                instance.created_at = _NOW
                instance.updated_at = _NOW

    async def refresh(self, instance: object) -> None:
        _ = instance
        self.refresh_calls += 1

    async def commit(self) -> None:
        self.commit_calls += 1

    async def rollback(self) -> None:
        self.rollback_calls += 1


async def test_sqlalchemy_repository_creates_current_calculation_without_commit() -> None:
    session = FakeSession(execute_results=[None])
    repo = _repo(session)

    result = await repo.create_or_reuse_calculation(_request(score_id=10))

    assert result.created is True
    assert result.is_replacement is False
    assert result.calculation.id == 100
    assert result.calculation.is_current is True
    assert result.calculation.state is PerformanceCalculationState.QUEUED
    assert len(session.added) == 1
    assert session.flush_calls == 1
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_sqlalchemy_repository_returns_claim_conflict_without_mutation() -> None:
    model = _model(
        calculation_id=20,
        score_id=10,
        state=PerformanceCalculationState.QUEUED,
        is_current=True,
    )
    model.claim_owner = "worker-a"
    model.claim_expires_at = _NOW + timedelta(minutes=5)
    session = FakeSession(execute_results=[model])
    repo = _repo(session)

    result = await repo.claim_pending_calculation(
        ClaimScorePerformanceCalculation(
            calculation_id=20,
            owner="worker-b",
            claimed_at=_NOW,
            claim_expires_at=_NOW + timedelta(minutes=10),
        )
    )

    assert result is None
    assert model.claim_owner == "worker-a"
    assert session.flush_calls == 0
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_sqlalchemy_replacement_completion_supersedes_old_current_atomically() -> None:
    old_current = _model(
        calculation_id=1,
        score_id=10,
        state=PerformanceCalculationState.COMPLETED,
        is_current=True,
    )
    replacement = _model(
        calculation_id=2,
        score_id=10,
        state=PerformanceCalculationState.QUEUED,
        is_current=False,
        calculator_version="4.1.0",
    )
    session = FakeSession(
        execute_results=[old_current],
        get_results={(ScorePerformanceCalculationModel, 2): replacement},
    )
    repo = _repo(session)

    completed = await repo.mark_completed(
        CompleteScorePerformanceCalculation(
            calculation_id=2,
            pp=Decimal("222.222222"),
            star_rating=Decimal("6.54321"),
            calculator_name="rosu-pp-py",
            calculator_version="4.1.0",
            formula_profile=FormulaProfile.VANILLA_RANKED,
            beatmap_file_attachment_id=55,
            beatmap_file_checksum_md5="a" * 32,
            calculated_at=_NOW,
        )
    )

    assert completed is not None
    assert completed.id == 2
    assert completed.is_current is True
    assert completed.state is PerformanceCalculationState.COMPLETED
    assert old_current.is_current is False
    assert old_current.state == PerformanceCalculationState.SUPERSEDED.value
    assert replacement.is_current is True
    assert replacement.pp == Decimal("222.222222")
    assert session.flush_calls == 2
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


def _repo(session: FakeSession) -> SQLAlchemyScorePerformanceCommandRepository:
    return SQLAlchemyScorePerformanceCommandRepository(
        cast("AsyncSession", cast("object", session))
    )


def _request(
    *,
    score_id: int,
    calculator_version: str = "4.0.2",
) -> CreateScorePerformanceCalculation:
    return CreateScorePerformanceCalculation(
        score_id=score_id,
        calculator_name="rosu-pp-py",
        calculator_version=calculator_version,
        formula_profile=FormulaProfile.VANILLA_RANKED,
        requested_at=_NOW,
    )


def _model(
    *,
    calculation_id: int,
    score_id: int,
    state: PerformanceCalculationState,
    is_current: bool,
    calculator_version: str = "4.0.2",
) -> ScorePerformanceCalculationModel:
    model = ScorePerformanceCalculationModel(
        id=calculation_id,
        score_id=score_id,
        state=state.value,
        is_current=is_current,
        pp=Decimal("123.456789") if state is PerformanceCalculationState.COMPLETED else None,
        star_rating=Decimal("5.43210") if state is PerformanceCalculationState.COMPLETED else None,
        calculator_name="rosu-pp-py",
        calculator_version=calculator_version,
        formula_profile=FormulaProfile.VANILLA_RANKED.value,
        beatmap_file_attachment_id=55 if state is PerformanceCalculationState.COMPLETED else None,
        beatmap_file_checksum_md5="a" * 32
        if state is PerformanceCalculationState.COMPLETED
        else None,
        unavailable_reason="osu_file_unusable"
        if state is PerformanceCalculationState.UNAVAILABLE
        else None,
        claim_owner=None,
        claim_expires_at=None,
        attempt_count=0,
        calculated_at=_NOW if state.is_terminal else None,
    )
    model.created_at = _NOW
    model.updated_at = _NOW
    return model
