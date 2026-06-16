"""Command repository contract tests for score performance persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from osu_server.domain.scores.performance import (
    FormulaProfile,
    PerformanceCalculation,
    PerformanceCalculationState,
)
from osu_server.repositories.interfaces.commands.score_performance import (
    ClaimScorePerformanceCalculation,
    CompleteScorePerformanceCalculation,
    CreateScorePerformanceCalculation,
    MarkScorePerformanceCalculationUnavailable,
)
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory

_NOW = datetime(2026, 6, 16, 0, 0, 0, tzinfo=UTC)


def _memory_factory() -> UnitOfWorkFactory:
    return InMemoryUnitOfWorkFactory()


async def test_duplicate_requests_reuse_one_current_calculation() -> None:
    factory = _memory_factory()

    async with factory() as uow:
        first = await uow.score_performance.create_or_reuse_calculation(
            _request(score_id=10, calculator_version="4.0.2")
        )
        second = await uow.score_performance.create_or_reuse_calculation(
            _request(score_id=10, calculator_version="4.0.2")
        )
        await uow.commit()

    async with factory() as uow:
        current = await uow.score_performance.get_current_for_score(10)

    assert first.created is True
    assert first.is_replacement is False
    assert second.created is False
    assert second.is_replacement is False
    assert second.calculation.id == first.calculation.id
    assert current == first.calculation


async def test_claim_conflict_is_retryable_without_marking_unavailable() -> None:
    factory = _memory_factory()
    created_id = await _create_current(factory, score_id=11)

    async with factory() as uow:
        first_claim = await uow.score_performance.claim_pending_calculation(
            _claim(calculation_id=created_id, owner="worker-a", claimed_at=_NOW)
        )
        conflict = await uow.score_performance.claim_pending_calculation(
            _claim(calculation_id=created_id, owner="worker-b", claimed_at=_NOW)
        )
        stale_claim = await uow.score_performance.claim_pending_calculation(
            _claim(
                calculation_id=created_id,
                owner="worker-b",
                claimed_at=_NOW + timedelta(minutes=6),
            )
        )
        current = await uow.score_performance.get_current_for_score(11)
        await uow.commit()

    assert first_claim is not None
    assert first_claim.owner == "worker-a"
    assert first_claim.attempt_count == 1
    assert conflict is None
    assert stale_claim is not None
    assert stale_claim.owner == "worker-b"
    assert stale_claim.attempt_count == 2
    assert current is not None
    assert current.state is PerformanceCalculationState.QUEUED


async def test_replacement_preserves_old_current_until_completed_finalization() -> None:
    factory = _memory_factory()
    current_id = await _create_current(factory, score_id=12, calculator_version="4.0.2")
    _ = await _complete(factory, calculation_id=current_id, calculator_version="4.0.2")

    async with factory() as uow:
        replacement = await uow.score_performance.create_or_reuse_calculation(
            _request(score_id=12, calculator_version="4.1.0")
        )
        current_before_finalization = await uow.score_performance.get_current_for_score(12)
        await uow.commit()

    assert replacement.created is True
    assert replacement.is_replacement is True
    assert replacement.calculation.id != current_id
    assert replacement.calculation.is_current is False
    assert current_before_finalization is not None
    assert current_before_finalization.id == current_id
    assert current_before_finalization.is_current is True

    assert replacement.calculation.id is not None
    finalized = await _complete(
        factory,
        calculation_id=replacement.calculation.id,
        calculator_version="4.1.0",
    )

    async with factory() as uow:
        old_current = await uow.score_performance.get_by_id(current_id)
        new_current = await uow.score_performance.get_current_for_score(12)

    assert finalized.is_current is True
    assert old_current is not None
    assert old_current.state is PerformanceCalculationState.SUPERSEDED
    assert old_current.is_current is False
    assert new_current is not None
    assert new_current.id == replacement.calculation.id
    assert new_current.state is PerformanceCalculationState.COMPLETED


async def test_unavailable_replacement_finalization_switches_current_once() -> None:
    factory = _memory_factory()
    current_id = await _create_current(factory, score_id=13, calculator_version="4.0.2")
    _ = await _complete(factory, calculation_id=current_id, calculator_version="4.0.2")

    async with factory() as uow:
        replacement = await uow.score_performance.create_or_reuse_calculation(
            _request(score_id=13, calculator_version="4.1.0")
        )
        await uow.commit()

    assert replacement.calculation.id is not None
    async with factory() as uow:
        unavailable = await uow.score_performance.mark_unavailable(
            MarkScorePerformanceCalculationUnavailable(
                calculation_id=replacement.calculation.id,
                calculator_name="rosu-pp-py",
                calculator_version="4.1.0",
                formula_profile=FormulaProfile.VANILLA_RANKED,
                beatmap_file_attachment_id=None,
                beatmap_file_checksum_md5=None,
                reason="osu_file_unusable",
                calculated_at=_NOW,
            )
        )
        current = await uow.score_performance.get_current_for_score(13)
        old_current = await uow.score_performance.get_by_id(current_id)
        await uow.commit()

    assert unavailable is not None
    assert unavailable.is_current is True
    assert unavailable.state is PerformanceCalculationState.UNAVAILABLE
    assert current == unavailable
    assert old_current is not None
    assert old_current.state is PerformanceCalculationState.SUPERSEDED


async def _create_current(
    factory: UnitOfWorkFactory,
    *,
    score_id: int,
    calculator_version: str = "4.0.2",
) -> int:
    async with factory() as uow:
        result = await uow.score_performance.create_or_reuse_calculation(
            _request(score_id=score_id, calculator_version=calculator_version)
        )
        await uow.commit()
    assert result.calculation.id is not None
    return result.calculation.id


async def _complete(
    factory: UnitOfWorkFactory,
    *,
    calculation_id: int,
    calculator_version: str,
) -> PerformanceCalculation:
    async with factory() as uow:
        completed = await uow.score_performance.mark_completed(
            CompleteScorePerformanceCalculation(
                calculation_id=calculation_id,
                pp=Decimal("123.456789"),
                star_rating=Decimal("5.43210"),
                calculator_name="rosu-pp-py",
                calculator_version=calculator_version,
                formula_profile=FormulaProfile.VANILLA_RANKED,
                beatmap_file_attachment_id=55,
                beatmap_file_checksum_md5="a" * 32,
                calculated_at=_NOW,
            )
        )
        await uow.commit()
    assert completed is not None
    return completed


def _request(
    *,
    score_id: int,
    calculator_version: str,
) -> CreateScorePerformanceCalculation:
    return CreateScorePerformanceCalculation(
        score_id=score_id,
        calculator_name="rosu-pp-py",
        calculator_version=calculator_version,
        formula_profile=FormulaProfile.VANILLA_RANKED,
        requested_at=_NOW,
    )


def _claim(
    *,
    calculation_id: int,
    owner: str,
    claimed_at: datetime,
) -> ClaimScorePerformanceCalculation:
    return ClaimScorePerformanceCalculation(
        calculation_id=calculation_id,
        owner=owner,
        claimed_at=claimed_at,
        claim_expires_at=claimed_at + timedelta(minutes=5),
    )
