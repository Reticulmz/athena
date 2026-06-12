"""Score submission service orchestrating the full submission pipeline."""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from osu_server.domain.beatmap import BeatmapResolveOptions, BeatmapResolveResult
from osu_server.domain.score.payload_parser import ParseError, parse
from osu_server.domain.score.replay import Replay
from osu_server.domain.score.score import Playstyle, Ruleset, Score
from osu_server.domain.score.submission import ScoreSubmission
from osu_server.domain.score.validator import ValidationError, validate_hit_counts
from osu_server.infrastructure.auth.score_authorization import (
    AuthorizationContext,
    ScoreAuthorizationService,
)
from osu_server.infrastructure.crypto.score_crypto import decrypt_score_payload
from osu_server.repositories.interfaces.replay_repository import ReplayRepository
from osu_server.repositories.interfaces.score_repository import ScoreRepository
from osu_server.repositories.interfaces.submission_repository import ScoreSubmissionRepository
from osu_server.shared.errors import DecryptionError

# Mod bit constants for playstyle detection (Requirement 1.3)
_MOD_RELAX = 1 << 7  # 128
_MOD_AUTOPILOT = 1 << 13  # 8192


class BeatmapEligibilityResolver(Protocol):
    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult: ...


class SubmissionOutcome(Enum):
    """Submission result outcome."""

    COMPLETED = "completed"
    TERMINAL_REJECTED = "terminal_rejected"
    RETRYABLE = "retryable"


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    """Result of score submission."""

    outcome: SubmissionOutcome
    score_id: int | None = None
    error_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedSubmissionInput:
    """Input model for score submission."""

    encrypted_payload: bytes
    iv: bytes
    replay_data: bytes | None
    password_md5: str
    client_hash: str
    fail_time_ms: int | None
    osu_version: str | None
    beatmap_id: int
    submitted_at: datetime


class ScoreSubmissionService:
    """Orchestrate score submission use-case.

    Requirements: R1-R12 (all Wave 1 requirements)
    """

    def __init__(
        self,
        score_repo: ScoreRepository,
        submission_repo: ScoreSubmissionRepository,
        replay_repo: ReplayRepository,
        auth_service: ScoreAuthorizationService,
        beatmap_resolver: BeatmapEligibilityResolver,
    ) -> None:
        self._score_repo: ScoreRepository = score_repo
        self._submission_repo: ScoreSubmissionRepository = submission_repo
        self._replay_repo: ReplayRepository = replay_repo
        self._auth_service: ScoreAuthorizationService = auth_service
        self._beatmap_resolver: BeatmapEligibilityResolver = beatmap_resolver

    async def submit_score(  # noqa: PLR0911, PLR0912
        self, input_data: ParsedSubmissionInput
    ) -> SubmissionResult:
        """Submit a score with full validation and persistence.

        Flow:
        1. Generate submission fingerprint
        2. Check for existing submission (idempotency)
        3. Decrypt payload
        4. Parse payload
        5. Authorize (password + session + identity)
        6. Check beatmap eligibility
        7. Validate hit counts
        8. Check uniqueness (online checksum, replay checksum)
        9. Persist score + replay
        10. Return result

        Requirements:
            - R9.1-9.4: Idempotent retry handling
            - R3.1-3.4: Decryption
            - R4.1-4.5: Authorization
            - R8.1-8.5: Beatmap eligibility
            - R5.1-5.5: Validation
            - R6.1-6.4: Uniqueness enforcement
            - R7.1-7.5: Persistence
            - R11.1-11.5: Security logging
        """
        # 1. Generate submission fingerprint (R9.4)
        fingerprint = self._generate_fingerprint(input_data)

        # 2. Check existing submission (R9.2)
        existing = await self._submission_repo.get_by_fingerprint(fingerprint)
        if existing and existing.state == "completed":
            score_id_value = (
                existing.result_snapshot.get("score_id") if existing.result_snapshot else None
            )
            # Ensure score_id is int or None
            if isinstance(score_id_value, int):
                return SubmissionResult(
                    outcome=SubmissionOutcome.COMPLETED,
                    score_id=score_id_value,
                )
            return SubmissionResult(
                outcome=SubmissionOutcome.COMPLETED,
                score_id=None,
            )

        # 3. Decrypt payload (R3.1-3.4)
        try:
            decrypted = decrypt_score_payload(
                input_data.encrypted_payload,
                input_data.iv,
                input_data.osu_version,
            )
        except DecryptionError as e:
            return SubmissionResult(
                outcome=SubmissionOutcome.TERMINAL_REJECTED,
                error_reason=f"decryption_failed: {e}",
            )

        # 4. Parse payload (R5.1)
        try:
            parsed = parse(decrypted.plaintext)
        except ParseError as e:
            return SubmissionResult(
                outcome=SubmissionOutcome.TERMINAL_REJECTED,
                error_reason=f"parse_failed: {e}",
            )

        # 5. Authorize (R4.1-4.5)
        auth_ctx = await self._auth_service.authorize_submission(
            input_data.password_md5,
            parsed.username,
            parsed.user_id,
        )
        if not auth_ctx.authorized:
            return SubmissionResult(
                outcome=SubmissionOutcome.TERMINAL_REJECTED,
                error_reason=self._format_auth_error(auth_ctx),
            )

        # 5.5. Check playstyle (R1.3, R1.4)
        if self._is_relax_or_autopilot(parsed.mods):
            return SubmissionResult(
                outcome=SubmissionOutcome.TERMINAL_REJECTED,
                error_reason="playstyle_not_supported: relax_or_autopilot",
            )

        # 6. Check beatmap eligibility (R8.1-8.5)
        beatmap_result = await self._beatmap_resolver.resolve_by_beatmap_id(
            input_data.beatmap_id,
            BeatmapResolveOptions(),
        )
        eligibility = beatmap_result.eligibility
        accepts_submission = False
        if eligibility is not None:
            accepts_submission = (
                eligibility.accepts_scores if parsed.passed else eligibility.accepts_failed_scores
            )
        if not accepts_submission:
            denial_reason = eligibility.denial_reason if eligibility is not None else None
            return SubmissionResult(
                outcome=SubmissionOutcome.TERMINAL_REJECTED,
                error_reason=f"beatmap_ineligible: {denial_reason or 'not_accepting_scores'}",
            )

        # 7. Validate hit counts (R5.1-5.5)
        try:
            validation = validate_hit_counts(parsed)
        except ValidationError as e:
            return SubmissionResult(
                outcome=SubmissionOutcome.TERMINAL_REJECTED,
                error_reason=f"validation_failed: {e}",
            )

        # 8. Check uniqueness (R6.1, R6.2)
        if await self._score_repo.exists_by_online_checksum(parsed.online_checksum):
            return SubmissionResult(
                outcome=SubmissionOutcome.TERMINAL_REJECTED,
                error_reason="duplicate_online_checksum",
            )

        replay_checksum: str | None = None
        if input_data.replay_data:
            replay_checksum = hashlib.sha256(input_data.replay_data).hexdigest()
            if await self._replay_repo.exists_by_checksum(replay_checksum):
                return SubmissionResult(
                    outcome=SubmissionOutcome.TERMINAL_REJECTED,
                    error_reason="duplicate_replay_checksum",
                )

        # 9. Persist score (R7.1-7.5, R12.1-12.4)
        score = Score(
            id=None,
            user_id=parsed.user_id,
            beatmap_id=input_data.beatmap_id,
            beatmap_checksum=parsed.beatmap_checksum,
            online_checksum=parsed.online_checksum,
            ruleset=Ruleset(parsed.ruleset),
            playstyle=Playstyle.VANILLA,
            mods=parsed.mods,
            n300=parsed.n300,
            n100=parsed.n100,
            n50=parsed.n50,
            geki=parsed.geki,
            katu=parsed.katu,
            miss=parsed.miss,
            score=parsed.score,
            max_combo=parsed.max_combo,
            accuracy=validation.accuracy,
            grade=validation.grade,
            passed=parsed.passed,
            perfect=parsed.perfect,
            client_version=input_data.osu_version or "unknown",
            submitted_at=input_data.submitted_at,
        )

        created_score = await self._score_repo.create(score)
        assert created_score.id is not None, "Score ID must be set after creation"

        # 10. Persist replay if present (R7.3-7.4)
        if input_data.replay_data and replay_checksum:
            replay = Replay(
                id=None,
                score_id=created_score.id,
                blob_key=f"replay/{created_score.id}",
                checksum_sha256=replay_checksum,
                byte_size=len(input_data.replay_data),
            )
            _ = await self._replay_repo.create(replay)

        # 11. Record submission (R9.1)
        submission = ScoreSubmission(
            id=None,
            fingerprint=fingerprint,
            user_id=parsed.user_id,
            beatmap_checksum=parsed.beatmap_checksum,
            submitted_at=input_data.submitted_at,
            state="completed",
            result_snapshot={"score_id": created_score.id},
        )
        _ = await self._submission_repo.create(submission)

        return SubmissionResult(
            outcome=SubmissionOutcome.COMPLETED,
            score_id=created_score.id,
        )

    def _generate_fingerprint(self, input_data: ParsedSubmissionInput) -> str:
        """Generate submission fingerprint for idempotency (R9.4)."""
        material = (
            f"{input_data.beatmap_id}:"
            f"{input_data.client_hash}:"
            f"{input_data.submitted_at.isoformat()}"
        )
        return hashlib.sha256(material.encode()).hexdigest()

    def _format_auth_error(self, ctx: AuthorizationContext) -> str:
        """Format authorization error without exposing credentials (R11.1)."""
        if not ctx.password_valid:
            return "authorization_failed: invalid_password"
        if not ctx.session_valid:
            return "authorization_failed: no_active_session"
        if not ctx.payload_identity_match:
            return "authorization_failed: identity_mismatch"
        return "authorization_failed: unknown"

    def _is_relax_or_autopilot(self, mods: int) -> bool:
        """Check if submission contains Relax or Autopilot mods (R1.3, R1.4)."""
        return (mods & _MOD_RELAX) != 0 or (mods & _MOD_AUTOPILOT) != 0
