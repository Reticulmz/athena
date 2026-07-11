"""Unit tests for ProcessScoreSubmissionUseCase playstyle validation (Task 17.1)."""

from dataclasses import dataclass, replace

import pytest

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapEligibility,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapResolveOptions,
    BeatmapResolveResult,
    BeatmapSourceVerification,
)
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.scores import (
    ParsedSubmissionInput,
    ProcessScoreSubmissionUseCase,
    SubmissionOutcome,
)
from tests.support.credentials import fixed_test_password_md5
from tests.support.fakes import (
    StubBlobStorageService,
    make_score_authorization_service,
    make_submit_score_use_case,
    make_test_parsed_score,
    make_test_submission_input,
)

# Mod bit constants (from osu! stable protocol)
RELAX = 1 << 7  # 128
AUTOPILOT = 1 << 13  # 8192


def _eligible_beatmap() -> BeatmapEligibility:
    return BeatmapEligibility(
        accepts_scores=True,
        has_leaderboard=True,
        awards_ranked_pp=True,
        awards_loved_pp=False,
        requires_osu_file_for_pp=True,
        is_officially_verified=True,
        is_mirror_derived=False,
        accepts_failed_scores=True,
        failed_scores_have_leaderboard=False,
        failed_scores_update_best_score=False,
        failed_scores_award_ranked_pp=False,
        failed_scores_award_loved_pp=False,
        denial_reason=None,
    )


def _resolved_beatmap() -> Beatmap:
    return Beatmap(
        id=1,
        beatmapset_id=10,
        checksum_md5="0123456789abcdef0123456789abcdef",
        mode=BeatmapMode.OSU,
        version="Test",
        total_length=None,
        hit_length=None,
        max_combo=None,
        bpm=None,
        cs=None,
        od=None,
        ar=None,
        hp=None,
        difficulty_rating=None,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        local_status_override=None,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=BeatmapFileState.MISSING,
        file_attachment=None,
        last_fetched_at=None,
        next_refresh_at=None,
    )


@dataclass(slots=True)
class FakeBeatmapResolver:
    eligibility: BeatmapEligibility | None = None

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        del beatmap_id, options
        return BeatmapResolveResult(
            beatmap=None,
            beatmapset=None,
            eligibility=self.eligibility,
            metadata_status=BeatmapFetchState.FRESH,
            file_status=BeatmapFileState.MISSING,
            source=BeatmapMetadataSource.OFFICIAL,
            verified=True,
            last_fetched_at=None,
            next_refresh_at=None,
            reason=None,
        )

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        del checksum_md5, options
        return BeatmapResolveResult(
            beatmap=_resolved_beatmap(),
            beatmapset=None,
            eligibility=self.eligibility,
            metadata_status=BeatmapFetchState.FRESH,
            file_status=BeatmapFileState.MISSING,
            source=BeatmapMetadataSource.OFFICIAL,
            verified=True,
            last_fetched_at=None,
            next_refresh_at=None,
            reason=None,
        )


@pytest.fixture
def uow_factory() -> InMemoryUnitOfWorkFactory:
    return InMemoryUnitOfWorkFactory()


@pytest.fixture
def beatmap_resolver() -> FakeBeatmapResolver:
    return FakeBeatmapResolver(_eligible_beatmap())


@pytest.fixture
def service(
    uow_factory: InMemoryUnitOfWorkFactory,
    beatmap_resolver: FakeBeatmapResolver,
) -> ProcessScoreSubmissionUseCase:
    """Create service with in-memory repositories."""
    auth_service = make_score_authorization_service()
    return ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        StubBlobStorageService(),
        auth_service,
        beatmap_resolver,
    )


@pytest.fixture
def valid_input() -> ParsedSubmissionInput:
    """Valid submission input."""
    return make_test_submission_input(password_md5=fixed_test_password_md5())


@pytest.mark.asyncio
async def test_relax_mod_terminal_reject(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
) -> None:
    """Requirement 1.3: Relax mod submissions are rejected."""

    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            f"1000:test_user:abc123:online_rx:0:{RELAX}:100:10:5:0:0:2:500000:99:1:1"
        ),
    )

    result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result.error_reason is not None
    assert "relax" in result.error_reason.lower() or "playstyle" in result.error_reason.lower()


@pytest.mark.asyncio
async def test_autopilot_mod_terminal_reject(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
) -> None:
    """Requirement 1.3: Autopilot mod submissions are rejected."""

    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            f"1000:test_user:abc123:online_ap:0:{AUTOPILOT}:100:10:5:0:0:2:500000:99:1:1"
        ),
    )

    result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result.error_reason is not None
    assert "autopilot" in result.error_reason.lower() or "playstyle" in result.error_reason.lower()


@pytest.mark.asyncio
async def test_relax_and_autopilot_combined_terminal_reject(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
) -> None:
    """Requirement 1.3: Combined Relax + Autopilot is rejected."""

    combined_mods = RELAX | AUTOPILOT
    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            f"1000:test_user:abc123:online_both:0:{combined_mods}:100:10:5:0:0:2:500000:99:1:1"
        ),
    )

    result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result.error_reason is not None
    assert "playstyle" in result.error_reason.lower()


@pytest.mark.asyncio
async def test_vanilla_mod_accepted(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
) -> None:
    """Requirement 1.2: Vanilla gameplay is accepted."""

    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            "1000:test_user:abc123:online_vanilla:0:0:100:10:5:0:0:2:500000:99:1:1"
        ),
    )

    result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.score_id is not None
    assert result.error_reason is None


@pytest.mark.asyncio
async def test_other_mods_accepted(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
) -> None:
    """Requirement 1.2: Other mods (HD, HR, DT, etc.) are accepted."""

    other_mods = 8 | 16 | 64
    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            f"1000:test_user:abc123:online_other:0:{other_mods}:100:10:5:0:0:2:500000:99:1:1"
        ),
    )

    result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.score_id is not None
    assert result.error_reason is None
