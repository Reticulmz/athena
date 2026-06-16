"""Tests for SQLAlchemy score performance command repository."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from osu_server.domain.scores.performance import FormulaProfile, PerformanceCalculationState
from osu_server.repositories.interfaces.commands.score_performance import (
    ClaimScorePerformanceCalculation,
    ClaimScorePerformanceRecalculationWork,
    CompleteScorePerformanceCalculation,
    CompleteScorePerformanceRecalculationWork,
    CreateScorePerformanceCalculation,
    CreateScorePerformanceRecalculationBatch,
    CreateScorePerformanceRecalculationWorkItem,
    MarkScorePerformanceRecalculationWorkFailed,
)
from osu_server.repositories.sqlalchemy.commands.score_performance import (
    SQLAlchemyScorePerformanceCommandRepository,
)
from osu_server.repositories.sqlalchemy.models.score_performance import (
    PerformanceRecalculationBatchModel,
    PerformanceRecalculationWorkItemModel,
    ScorePerformanceCalculationModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.base import Executable

_NOW = datetime(2026, 6, 16, 0, 0, 0, tzinfo=UTC)


class FakeResult:
    """Minimal SQLAlchemy scalar result double."""

    def __init__(self, value: object | None, values: list[object] | None = None) -> None:
        self._value: object | None = value
        self._values: list[object] = values or []

    def scalar_one_or_none(self) -> object | None:
        return self._value

    def scalars(self) -> FakeResult:
        return self

    def all(self) -> list[object]:
        return self._values


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
        self._next_recalculation_batch_id: int = 200
        self._next_recalculation_work_item_id: int = 300

    async def execute(self, statement: Executable) -> FakeResult:
        _ = statement
        value = self.execute_results.pop(0) if self.execute_results else None
        if isinstance(value, list):
            return FakeResult(None, cast("list[object]", value))
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
            elif (
                isinstance(instance, PerformanceRecalculationBatchModel)
                and getattr(instance, "id", None) is None
            ):
                instance.id = self._next_recalculation_batch_id
                self._next_recalculation_batch_id += 1
                instance.created_at = _NOW
                instance.updated_at = _NOW
            elif (
                isinstance(instance, PerformanceRecalculationWorkItemModel)
                and getattr(instance, "id", None) is None
            ):
                instance.id = self._next_recalculation_work_item_id
                self._next_recalculation_work_item_id += 1
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
    assert result.requires_commit is True
    assert result.calculation.id == 100
    assert result.calculation.is_current is True
    assert result.calculation.state is PerformanceCalculationState.QUEUED
    assert len(session.added) == 1
    assert session.flush_calls == 1
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_sqlalchemy_request_supersedes_mismatched_pending_replacement() -> None:
    current = _model(
        calculation_id=1,
        score_id=10,
        state=PerformanceCalculationState.COMPLETED,
        is_current=True,
    )
    stale_replacement = _model(
        calculation_id=2,
        score_id=10,
        state=PerformanceCalculationState.QUEUED,
        is_current=False,
        calculator_version="4.1.0",
    )
    stale_replacement.claim_owner = "worker-a"
    stale_replacement.claim_expires_at = _NOW + timedelta(minutes=5)
    session = FakeSession(
        execute_results=[current, [stale_replacement]],
        get_results={(ScorePerformanceCalculationModel, 2): stale_replacement},
    )
    repo = _repo(session)

    result = await repo.create_or_reuse_calculation(
        _request(score_id=10, calculator_version="4.2.0")
    )
    stale_finalize = await repo.mark_completed(
        CompleteScorePerformanceCalculation(
            calculation_id=2,
            pp=Decimal("111.111111"),
            star_rating=Decimal("4.32100"),
            calculator_name="rosu-pp-py",
            calculator_version="4.1.0",
            formula_profile=FormulaProfile.VANILLA_RANKED,
            beatmap_file_attachment_id=55,
            beatmap_file_checksum_md5="a" * 32,
            calculated_at=_NOW,
        )
    )

    assert result.created is True
    assert result.is_replacement is True
    assert result.requires_commit is True
    assert result.calculation.id == 100
    assert result.calculation.state is PerformanceCalculationState.QUEUED
    assert result.calculation.is_current is False
    assert stale_replacement.state == PerformanceCalculationState.SUPERSEDED.value
    assert stale_replacement.is_current is False
    assert stale_replacement.claim_owner is None
    assert stale_replacement.claim_expires_at is None
    assert stale_finalize is None
    assert current.state == PerformanceCalculationState.COMPLETED.value
    assert current.is_current is True
    assert len(session.added) == 1
    assert session.flush_calls == 2
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_sqlalchemy_request_commits_supersede_before_reusing_matching_replacement() -> None:
    current = _model(
        calculation_id=1,
        score_id=10,
        state=PerformanceCalculationState.COMPLETED,
        is_current=True,
    )
    matching_replacement = _model(
        calculation_id=2,
        score_id=10,
        state=PerformanceCalculationState.QUEUED,
        is_current=False,
        calculator_version="4.2.0",
    )
    stale_replacement = _model(
        calculation_id=3,
        score_id=10,
        state=PerformanceCalculationState.QUEUED,
        is_current=False,
        calculator_version="4.1.0",
    )
    stale_replacement.claim_owner = "worker-a"
    stale_replacement.claim_expires_at = _NOW + timedelta(minutes=5)
    session = FakeSession(execute_results=[current, [matching_replacement, stale_replacement]])
    repo = _repo(session)

    result = await repo.create_or_reuse_calculation(
        _request(score_id=10, calculator_version="4.2.0")
    )

    assert result.created is False
    assert result.is_replacement is True
    assert result.requires_commit is True
    assert result.calculation.id == matching_replacement.id
    assert result.calculation.state is PerformanceCalculationState.QUEUED
    assert stale_replacement.state == PerformanceCalculationState.SUPERSEDED.value
    assert stale_replacement.is_current is False
    assert stale_replacement.claim_owner is None
    assert stale_replacement.claim_expires_at is None
    assert len(session.added) == 0
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


async def test_sqlalchemy_repository_creates_recalculation_batch_without_commit() -> None:
    session = FakeSession()
    repo = _repo(session)

    batch = await repo.create_recalculation_batch(
        CreateScorePerformanceRecalculationBatch(
            filters={"all": True},
            reason_counts={"uncalculated": 1, "stale": 1},
            target_calculator_version="4.1.0",
            target_formula_profile=FormulaProfile.VANILLA_RANKED,
            work_items=(
                CreateScorePerformanceRecalculationWorkItem(
                    score_id=101,
                    reason="uncalculated",
                ),
                CreateScorePerformanceRecalculationWorkItem(
                    score_id=102,
                    reason="stale",
                ),
            ),
            created_at=_NOW,
        )
    )

    added_batches = [
        item for item in session.added if isinstance(item, PerformanceRecalculationBatchModel)
    ]
    added_work = [
        item for item in session.added if isinstance(item, PerformanceRecalculationWorkItemModel)
    ]
    assert batch.id == 200
    assert batch.candidate_count == 2
    assert batch.completed_count == 0
    assert batch.unavailable_count == 0
    assert len(added_batches) == 1
    assert len(added_work) == 2
    assert {item.batch_id for item in added_work} == {200}
    assert session.flush_calls == 2
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_sqlalchemy_repository_claims_recalculation_work_without_commit() -> None:
    batch = _batch_model(batch_id=200, candidate_count=2)
    first = _work_model(work_item_id=300, batch_id=200, score_id=101)
    second = _work_model(work_item_id=301, batch_id=200, score_id=102)
    session = FakeSession(
        execute_results=[[first, second]],
        get_results={(PerformanceRecalculationBatchModel, 200): batch},
    )
    repo = _repo(session)

    claimed = await repo.claim_recalculation_work(
        ClaimScorePerformanceRecalculationWork(
            batch_id=200,
            owner="worker-a",
            claimed_at=_NOW,
            claim_expires_at=_NOW + timedelta(minutes=5),
            limit=2,
        )
    )

    assert [item.id for item in claimed] == [300, 301]
    assert {item.claim_owner for item in claimed} == {"worker-a"}
    assert [item.attempt_count for item in claimed] == [1, 1]
    assert batch.status == "running"
    assert first.state == "claimed"
    assert first.claim_owner == "worker-a"
    assert second.state == "claimed"
    assert session.flush_calls == 1
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_sqlalchemy_repository_marks_recalculation_work_completed_without_commit() -> None:
    batch = _batch_model(batch_id=200, candidate_count=1)
    work = _work_model(work_item_id=300, batch_id=200, score_id=101)
    work.state = "claimed"
    work.claim_owner = "worker-a"
    work.claim_expires_at = _NOW + timedelta(minutes=5)
    work.attempt_count = 1
    session = FakeSession(
        execute_results=[work, batch, [work]],
        get_results={
            (PerformanceRecalculationBatchModel, 200): batch,
        },
    )
    repo = _repo(session)

    completed = await repo.mark_recalculation_work_completed(
        CompleteScorePerformanceRecalculationWork(
            work_item_id=300,
            owner="worker-a",
            calculation_id=500,
            completed_at=_NOW + timedelta(minutes=1),
        )
    )

    assert completed is not None
    assert completed.id == 300
    assert completed.calculation_id == 500
    assert completed.state.value == "completed"
    assert work.claim_owner is None
    assert batch.completed_count == 1
    assert batch.unavailable_count == 0
    assert batch.status == "completed"
    assert session.flush_calls == 2
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_sqlalchemy_repository_recalculates_batch_progress_from_work_items() -> None:
    batch = _batch_model(batch_id=200, candidate_count=2)
    current = _work_model(work_item_id=300, batch_id=200, score_id=101)
    current.state = "claimed"
    current.claim_owner = "worker-a"
    current.claim_expires_at = _NOW + timedelta(minutes=5)
    current.attempt_count = 1
    prior_completed = _work_model(work_item_id=301, batch_id=200, score_id=102)
    prior_completed.state = "completed"
    prior_completed.calculation_id = 499
    session = FakeSession(
        execute_results=[current, batch, [current, prior_completed]],
    )
    repo = _repo(session)

    completed = await repo.mark_recalculation_work_completed(
        CompleteScorePerformanceRecalculationWork(
            work_item_id=300,
            owner="worker-a",
            calculation_id=500,
            completed_at=_NOW + timedelta(minutes=1),
        )
    )

    assert completed is not None
    assert batch.completed_count == 2
    assert batch.unavailable_count == 0
    assert batch.status == "completed"
    assert session.flush_calls == 2
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_sqlalchemy_repository_records_failure_without_releasing_claim() -> None:
    batch = _batch_model(batch_id=200, candidate_count=1)
    work = _work_model(work_item_id=300, batch_id=200, score_id=101)
    work.state = "claimed"
    work.claim_owner = "worker-a"
    work.claim_expires_at = _NOW + timedelta(minutes=5)
    work.attempt_count = 1
    session = FakeSession(
        execute_results=[work],
        get_results={(PerformanceRecalculationBatchModel, 200): batch},
    )
    repo = _repo(session)

    failed = await repo.mark_recalculation_work_failed(
        MarkScorePerformanceRecalculationWorkFailed(
            work_item_id=300,
            owner="worker-a",
            error="replacement_calculation_pending",
            failed_at=_NOW + timedelta(minutes=1),
        )
    )

    assert failed is not None
    assert failed.state.value == "claimed"
    assert work.state == "claimed"
    assert work.claim_owner == "worker-a"
    assert work.claim_expires_at == _NOW + timedelta(minutes=5)
    assert work.last_error == "replacement_calculation_pending"
    assert batch.status == "running"
    assert session.flush_calls == 1
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_sqlalchemy_repository_rejects_stale_work_completion_owner() -> None:
    work = _work_model(work_item_id=300, batch_id=200, score_id=101)
    work.state = "claimed"
    work.claim_owner = "worker-b"
    work.claim_expires_at = _NOW + timedelta(minutes=10)
    work.attempt_count = 2
    session = FakeSession(
        execute_results=[None],
        get_results={(PerformanceRecalculationWorkItemModel, 300): work},
    )
    repo = _repo(session)

    completed = await repo.mark_recalculation_work_completed(
        CompleteScorePerformanceRecalculationWork(
            work_item_id=300,
            owner="worker-a",
            calculation_id=500,
            completed_at=_NOW + timedelta(minutes=6),
        )
    )

    assert completed is None
    assert work.state == "claimed"
    assert work.claim_owner == "worker-b"
    assert work.calculation_id is None
    assert session.flush_calls == 0
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_sqlalchemy_repository_rejects_stale_work_failure_owner() -> None:
    work = _work_model(work_item_id=300, batch_id=200, score_id=101)
    work.state = "claimed"
    work.claim_owner = "worker-b"
    work.claim_expires_at = _NOW + timedelta(minutes=10)
    work.attempt_count = 2
    session = FakeSession(
        execute_results=[None],
        get_results={(PerformanceRecalculationWorkItemModel, 300): work},
    )
    repo = _repo(session)

    failed = await repo.mark_recalculation_work_failed(
        MarkScorePerformanceRecalculationWorkFailed(
            work_item_id=300,
            owner="worker-a",
            error="old worker timeout",
            failed_at=_NOW + timedelta(minutes=6),
        )
    )

    assert failed is None
    assert work.state == "claimed"
    assert work.claim_owner == "worker-b"
    assert work.last_error is None
    assert session.flush_calls == 0
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


def _batch_model(
    *,
    batch_id: int,
    candidate_count: int,
) -> PerformanceRecalculationBatchModel:
    model = PerformanceRecalculationBatchModel(
        id=batch_id,
        status="pending",
        filters={"all": True},
        reason_counts={"uncalculated": candidate_count},
        target_calculator_version="4.1.0",
        target_formula_profile=FormulaProfile.VANILLA_RANKED.value,
        candidate_count=candidate_count,
        completed_count=0,
        unavailable_count=0,
    )
    model.created_at = _NOW
    model.updated_at = _NOW
    return model


def _work_model(
    *,
    work_item_id: int,
    batch_id: int,
    score_id: int,
) -> PerformanceRecalculationWorkItemModel:
    model = PerformanceRecalculationWorkItemModel(
        id=work_item_id,
        batch_id=batch_id,
        score_id=score_id,
        reason="uncalculated",
        state="pending",
        calculation_id=None,
        claim_owner=None,
        claim_expires_at=None,
        attempt_count=0,
        last_error=None,
    )
    model.created_at = _NOW
    model.updated_at = _NOW
    return model
