# pyright: reportUnknownParameterType=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnusedParameter=false, reportOperatorIssue=false, reportMissingParameterType=false
"""Unit tests for ScoreSubmissionService playstyle validation (Task 17.1)."""

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from osu_server.domain.beatmap import (
    BeatmapEligibility,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapResolveOptions,
    BeatmapResolveResult,
)
from osu_server.infrastructure.auth.score_authorization import (
    ScoreAuthorizationService,
)
from osu_server.infrastructure.crypto.score_crypto import DecryptedPayload
from osu_server.repositories.memory.replay_repository import InMemoryReplayRepository
from osu_server.repositories.memory.score_repository import InMemoryScoreRepository
from osu_server.repositories.memory.submission_repository import (
    InMemoryScoreSubmissionRepository,
)
from osu_server.services.score_submission_service import (
    ParsedSubmissionInput,
    ScoreSubmissionService,
    SubmissionOutcome,
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


@dataclass(slots=True)
class FakeBeatmapResolver:
    eligibility: BeatmapEligibility | None = None

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,  # noqa: ARG002
        options: BeatmapResolveOptions | None = None,  # noqa: ARG002
    ) -> BeatmapResolveResult:
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


@pytest.fixture
def repos() -> tuple[
    InMemoryScoreRepository, InMemoryScoreSubmissionRepository, InMemoryReplayRepository
]:
    """Create in-memory repositories."""
    return (
        InMemoryScoreRepository(),
        InMemoryScoreSubmissionRepository(),
        InMemoryReplayRepository(),
    )


@pytest.fixture
def beatmap_resolver() -> FakeBeatmapResolver:
    return FakeBeatmapResolver(_eligible_beatmap())


@pytest.fixture
def service(repos, beatmap_resolver: FakeBeatmapResolver) -> ScoreSubmissionService:
    """Create service with in-memory repositories."""
    score_repo, submission_repo, replay_repo = repos
    auth_service = ScoreAuthorizationService()
    return ScoreSubmissionService(
        score_repo, submission_repo, replay_repo, auth_service, beatmap_resolver
    )


@pytest.fixture
def valid_input() -> ParsedSubmissionInput:
    """Valid submission input."""
    return ParsedSubmissionInput(
        encrypted_payload=b"encrypted_data",
        iv=b"0" * 32,
        replay_data=b"replay_binary_data",
        password_md5="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",  # "password"
        client_hash="test_hash",
        fail_time_ms=None,
        osu_version="20240101",
        beatmap_id=1,
        submitted_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_relax_mod_terminal_reject(
    service: ScoreSubmissionService,
    valid_input: ParsedSubmissionInput,
    monkeypatch,
) -> None:
    """Requirement 1.3: Relax mod submissions are rejected."""

    def mock_decrypt(
        encrypted: bytes,  # noqa: ARG001
        iv: bytes,  # noqa: ARG001
        osu_version: str | None,  # noqa: ARG001
    ) -> DecryptedPayload:
        # mods field = RELAX (128)
        payload = f"1000:test_user:abc123:online_rx:0:{RELAX}:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    monkeypatch.setattr(
        "osu_server.services.score_submission_service.decrypt_score_payload",
        mock_decrypt,
    )

    result = await service.submit_score(valid_input)

    assert result.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result.error_reason is not None
    assert "relax" in result.error_reason.lower() or "playstyle" in result.error_reason.lower()


@pytest.mark.asyncio
async def test_autopilot_mod_terminal_reject(
    service: ScoreSubmissionService,
    valid_input: ParsedSubmissionInput,
    monkeypatch,
) -> None:
    """Requirement 1.3: Autopilot mod submissions are rejected."""

    def mock_decrypt(
        encrypted: bytes,  # noqa: ARG001
        iv: bytes,  # noqa: ARG001
        osu_version: str | None,  # noqa: ARG001
    ) -> DecryptedPayload:
        # mods field = AUTOPILOT (8192)
        payload = f"1000:test_user:abc123:online_ap:0:{AUTOPILOT}:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    monkeypatch.setattr(
        "osu_server.services.score_submission_service.decrypt_score_payload",
        mock_decrypt,
    )

    result = await service.submit_score(valid_input)

    assert result.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result.error_reason is not None
    assert "autopilot" in result.error_reason.lower() or "playstyle" in result.error_reason.lower()


@pytest.mark.asyncio
async def test_relax_and_autopilot_combined_terminal_reject(
    service: ScoreSubmissionService,
    valid_input: ParsedSubmissionInput,
    monkeypatch,
) -> None:
    """Requirement 1.3: Combined Relax + Autopilot is rejected."""

    def mock_decrypt(
        encrypted: bytes,  # noqa: ARG001
        iv: bytes,  # noqa: ARG001
        osu_version: str | None,  # noqa: ARG001
    ) -> DecryptedPayload:
        # mods field = RELAX | AUTOPILOT (128 | 8192 = 8320)
        combined_mods = RELAX | AUTOPILOT
        payload = (
            f"1000:test_user:abc123:online_both:0:{combined_mods}:100:10:5:0:0:2:500000:99:1:1"
        )
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    monkeypatch.setattr(
        "osu_server.services.score_submission_service.decrypt_score_payload",
        mock_decrypt,
    )

    result = await service.submit_score(valid_input)

    assert result.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result.error_reason is not None
    assert "playstyle" in result.error_reason.lower()


@pytest.mark.asyncio
async def test_vanilla_mod_accepted(
    service: ScoreSubmissionService,
    valid_input: ParsedSubmissionInput,
    monkeypatch,
) -> None:
    """Requirement 1.2: Vanilla gameplay is accepted."""

    def mock_decrypt(
        encrypted: bytes,  # noqa: ARG001
        iv: bytes,  # noqa: ARG001
        osu_version: str | None,  # noqa: ARG001
    ) -> DecryptedPayload:
        # mods field = 0 (no mods, vanilla)
        payload = "1000:test_user:abc123:online_vanilla:0:0:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    monkeypatch.setattr(
        "osu_server.services.score_submission_service.decrypt_score_payload",
        mock_decrypt,
    )

    result = await service.submit_score(valid_input)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.score_id is not None
    assert result.error_reason is None


@pytest.mark.asyncio
async def test_other_mods_accepted(
    service: ScoreSubmissionService,
    valid_input: ParsedSubmissionInput,
    monkeypatch,
) -> None:
    """Requirement 1.2: Other mods (HD, HR, DT, etc.) are accepted."""

    def mock_decrypt(
        encrypted: bytes,  # noqa: ARG001
        iv: bytes,  # noqa: ARG001
        osu_version: str | None,  # noqa: ARG001
    ) -> DecryptedPayload:
        # mods field = Hidden (8) | HardRock (16) | DoubleTime (64) = 88
        # No Relax or Autopilot
        other_mods = 8 | 16 | 64
        payload = f"1000:test_user:abc123:online_other:0:{other_mods}:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    monkeypatch.setattr(
        "osu_server.services.score_submission_service.decrypt_score_payload",
        mock_decrypt,
    )

    result = await service.submit_score(valid_input)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.score_id is not None
    assert result.error_reason is None
