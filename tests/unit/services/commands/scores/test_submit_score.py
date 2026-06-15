"""Tests for score submission command use-case transaction boundaries."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, final

import pytest

from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.scores import (
    SubmitScoreCommand,
    SubmitScoreCommandOutcome,
    SubmitScoreUseCase,
)

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager
    from types import TracebackType

    from osu_server.domain.scores.replay import Replay
    from osu_server.repositories.interfaces.commands.replays import ReplayCommandRepository
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWork


def _score(*, online_checksum: str = "online-checksum") -> Score:
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
        score=500000,
        max_combo=99,
        accuracy=0.95,
        grade=Grade.A,
        passed=True,
        perfect=False,
        client_version="20240101",
        submitted_at=datetime.now(UTC),
        beatmap_status_at_submission="ranked",
    )


@final
class FailingReplayUnitOfWorkFactory:
    """In-memory UoW factory whose replay create fails inside the transaction."""

    def __init__(self) -> None:
        self._factory: InMemoryUnitOfWorkFactory = InMemoryUnitOfWorkFactory()

    def __call__(self) -> AbstractAsyncContextManager[UnitOfWork]:
        context = self._factory()
        return _FailingReplayContext(context)


@final
class _FailingReplayContext:
    def __init__(self, context: AbstractAsyncContextManager[UnitOfWork]) -> None:
        self._context: AbstractAsyncContextManager[UnitOfWork] = context

    async def __aenter__(self) -> UnitOfWork:
        uow = await self._context.__aenter__()
        uow.replays = _FailingReplayRepository(uow.replays)
        return uow

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        _ = await self._context.__aexit__(exc_type, exc, traceback)


@final
class _FailingReplayRepository:
    def __init__(self, wrapped: ReplayCommandRepository) -> None:
        self._wrapped: ReplayCommandRepository = wrapped

    async def create(self, replay: Replay) -> Replay:
        del replay
        raise RuntimeError("replay write failed")

    async def exists_by_checksum(self, checksum: str) -> bool:
        return await self._wrapped.exists_by_checksum(checksum)


@pytest.mark.asyncio
async def test_replay_create_failure_rolls_back_submission_score_and_replay() -> None:
    factory = FailingReplayUnitOfWorkFactory()
    use_case = SubmitScoreUseCase(unit_of_work_factory=factory)

    with pytest.raises(RuntimeError, match="replay write failed"):
        _ = await use_case.execute(
            SubmitScoreCommand(
                fingerprint="fingerprint-1",
                user_id=1000,
                beatmap_checksum="abc123",
                submitted_at=datetime.now(UTC),
                outcome=SubmitScoreCommandOutcome.COMPLETED,
                score=_score(),
                beatmap_id=1,
                beatmapset_id=10,
                replay_blob_id=1,
                replay_checksum_sha256="a" * 64,
                replay_byte_size=128,
            )
        )

    async with factory() as uow:
        assert await uow.submissions.get_by_fingerprint("fingerprint-1") is None
        assert await uow.scores.get_by_online_checksum("online-checksum") is None
        assert not await uow.replays.exists_by_checksum("a" * 64)


@pytest.mark.asyncio
async def test_completed_submission_commits_one_snapshot() -> None:
    factory = InMemoryUnitOfWorkFactory()
    use_case = SubmitScoreUseCase(unit_of_work_factory=factory)

    result = await use_case.execute(
        SubmitScoreCommand(
            fingerprint="fingerprint-2",
            user_id=1000,
            beatmap_checksum="abc123",
            submitted_at=datetime.now(UTC),
            outcome=SubmitScoreCommandOutcome.COMPLETED,
            score=_score(online_checksum="online-2"),
            beatmap_id=1,
            beatmapset_id=10,
            replay_blob_id=2,
            replay_checksum_sha256="b" * 64,
            replay_byte_size=256,
            grade_discrepancy={"client_grade": "D", "server_grade": "A"},
            opaque_field_hashes={"fs_sha256": "c" * 64},
        )
    )

    assert result.outcome == SubmitScoreCommandOutcome.COMPLETED
    assert result.score_id == 1
    async with factory() as uow:
        submission = await uow.submissions.get_by_fingerprint("fingerprint-2")
        assert submission is not None
        assert submission.state == "completed"
        assert submission.result_snapshot == {
            "score_id": 1,
            "beatmap_id": 1,
            "beatmapset_id": 10,
            "beatmap_status_at_submission": "ranked",
            "grade_discrepancy": {"client_grade": "D", "server_grade": "A"},
            "opaque_fields": {"fs_sha256": "c" * 64},
            "replay_attachment_id": 1,
            "replay_blob_id": 2,
        }
