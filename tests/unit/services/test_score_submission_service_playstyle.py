"""Unit tests for ProcessScoreSubmissionUseCase playstyle validation (Task 17.1)."""

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapEligibility,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapRankStatus,
    BeatmapResolveOptions,
    BeatmapResolveResult,
    BeatmapSourceVerification,
)
from osu_server.domain.scores.decryption import DecryptedPayload
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.scores import (
    ParsedSubmissionInput,
    ProcessScoreSubmissionUseCase,
    SubmissionOutcome,
)
from tests.support.credentials import fixed_test_password_md5
from tests.support.fakes import (
    StubBlobStorageService,
    StubScorePayloadDecryptor,
    StubScorePayloadParser,
    make_score_authorization_service,
    make_submit_score_use_case,
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
        mode="osu",
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
def score_decryptor() -> StubScorePayloadDecryptor:
    return StubScorePayloadDecryptor()


@pytest.fixture
def service(
    uow_factory: InMemoryUnitOfWorkFactory,
    beatmap_resolver: FakeBeatmapResolver,
    score_decryptor: StubScorePayloadDecryptor,
) -> ProcessScoreSubmissionUseCase:
    """Create service with in-memory repositories."""
    auth_service = make_score_authorization_service()
    return ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        StubBlobStorageService(),
        score_decryptor,
        StubScorePayloadParser(),
        auth_service,
        beatmap_resolver,
    )


@pytest.fixture
def valid_input() -> ParsedSubmissionInput:
    """Valid submission input."""
    return ParsedSubmissionInput(
        encrypted_payload=b"encrypted_data",
        iv=b"0" * 32,
        replay_data=b"replay_binary_data",
        password_md5=fixed_test_password_md5(),
        client_hash="test_hash",
        fail_time_ms=None,
        osu_version="20240101",
        beatmap_id=1,
        submitted_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_relax_mod_terminal_reject(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
    score_decryptor: StubScorePayloadDecryptor,
) -> None:
    """Requirement 1.3: Relax mod submissions are rejected."""

    def mock_decrypt(
        _encrypted: bytes,
        _iv: bytes,
        _osu_version: str | None,
    ) -> DecryptedPayload:
        # mods field = RELAX (128)
        payload = f"1000:test_user:abc123:online_rx:0:{RELAX}:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    result = await service.execute(valid_input)

    assert result.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result.error_reason is not None
    assert "relax" in result.error_reason.lower() or "playstyle" in result.error_reason.lower()


@pytest.mark.asyncio
async def test_autopilot_mod_terminal_reject(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
    score_decryptor: StubScorePayloadDecryptor,
) -> None:
    """Requirement 1.3: Autopilot mod submissions are rejected."""

    def mock_decrypt(
        _encrypted: bytes,
        _iv: bytes,
        _osu_version: str | None,
    ) -> DecryptedPayload:
        # mods field = AUTOPILOT (8192)
        payload = f"1000:test_user:abc123:online_ap:0:{AUTOPILOT}:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    result = await service.execute(valid_input)

    assert result.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result.error_reason is not None
    assert "autopilot" in result.error_reason.lower() or "playstyle" in result.error_reason.lower()


@pytest.mark.asyncio
async def test_relax_and_autopilot_combined_terminal_reject(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
    score_decryptor: StubScorePayloadDecryptor,
) -> None:
    """Requirement 1.3: Combined Relax + Autopilot is rejected."""

    def mock_decrypt(
        _encrypted: bytes,
        _iv: bytes,
        _osu_version: str | None,
    ) -> DecryptedPayload:
        # mods field = RELAX | AUTOPILOT (128 | 8192 = 8320)
        combined_mods = RELAX | AUTOPILOT
        payload = (
            f"1000:test_user:abc123:online_both:0:{combined_mods}:100:10:5:0:0:2:500000:99:1:1"
        )
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    result = await service.execute(valid_input)

    assert result.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result.error_reason is not None
    assert "playstyle" in result.error_reason.lower()


@pytest.mark.asyncio
async def test_vanilla_mod_accepted(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
    score_decryptor: StubScorePayloadDecryptor,
) -> None:
    """Requirement 1.2: Vanilla gameplay is accepted."""

    def mock_decrypt(
        _encrypted: bytes,
        _iv: bytes,
        _osu_version: str | None,
    ) -> DecryptedPayload:
        # mods field = 0 (no mods, vanilla)
        payload = "1000:test_user:abc123:online_vanilla:0:0:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    result = await service.execute(valid_input)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.score_id is not None
    assert result.error_reason is None


@pytest.mark.asyncio
async def test_other_mods_accepted(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
    score_decryptor: StubScorePayloadDecryptor,
) -> None:
    """Requirement 1.2: Other mods (HD, HR, DT, etc.) are accepted."""

    def mock_decrypt(
        _encrypted: bytes,
        _iv: bytes,
        _osu_version: str | None,
    ) -> DecryptedPayload:
        # mods field = Hidden (8) | HardRock (16) | DoubleTime (64) = 88
        # No Relax or Autopilot
        other_mods = 8 | 16 | 64
        payload = f"1000:test_user:abc123:online_other:0:{other_mods}:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    result = await service.execute(valid_input)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.score_id is not None
    assert result.error_reason is None
