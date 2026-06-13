"""Score submission service orchestrating the full submission pipeline."""

import hashlib
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol

import structlog

from osu_server.domain.beatmaps import BeatmapResolveOptions, BeatmapResolveResult
from osu_server.domain.score.decryption import DecryptedPayload
from osu_server.domain.score.payload_parser import ParseError, parse
from osu_server.domain.score.replay import Replay
from osu_server.domain.score.score import Playstyle, Ruleset, Score
from osu_server.domain.score.submission import ScoreSubmission
from osu_server.domain.score.validator import ValidationError, validate_hit_counts
from osu_server.domain.scores.mods import Mod, ModCombination
from osu_server.domain.storage.blobs import BlobStoreResult
from osu_server.repositories.interfaces.replay_repository import ReplayRepository
from osu_server.repositories.interfaces.score_repository import ScoreRepository
from osu_server.repositories.interfaces.submission_repository import ScoreSubmissionRepository
from osu_server.services.score_authorization_service import (
    AuthorizationContext,
    ScoreAuthorizationService,
)
from osu_server.shared.errors import DecryptionError

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]

_REPLAY_CONTENT_TYPE = "application/octet-stream"
_STATE_PROCESSING = "processing"
_STATE_COMPLETED = "completed"
_STATE_TERMINAL_REJECTED = "terminal_rejected"
_STATE_RETRYABLE = "retryable"
_OPAQUE_METADATA_FIELDS = frozenset({"fs", "bmk", "sbk", "c1", "st", "i", "token"})


def _empty_submission_metadata() -> dict[str, str]:
    return {}


class _FingerprintHasher(Protocol):
    def update(self, data: bytes, /) -> None: ...


def _update_fingerprint_bytes(hasher: _FingerprintHasher, label: bytes, value: bytes) -> None:
    hasher.update(label)
    hasher.update(b"\0")
    hasher.update(str(len(value)).encode())
    hasher.update(b"\0")
    hasher.update(value)
    hasher.update(b"\0")


def _update_fingerprint_text(hasher: _FingerprintHasher, label: str, value: str) -> None:
    _update_fingerprint_bytes(hasher, label.encode(), value.encode())


class BeatmapEligibilityResolver(Protocol):
    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult: ...

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult: ...


class ReplayBlobStorage(Protocol):
    async def put_bytes(
        self,
        data: bytes,
        *,
        content_type: str,
    ) -> BlobStoreResult: ...


class ScorePayloadDecryptor(Protocol):
    def decrypt_score_payload(
        self,
        encrypted: bytes,
        iv: bytes,
        osu_version: str | None,
    ) -> DecryptedPayload: ...


class SubmissionOutcome(Enum):
    """Submission result outcome."""

    COMPLETED = "completed"
    TERMINAL_REJECTED = "terminal_rejected"
    RETRYABLE = "retryable"
    ACCEPTED_PENDING = "accepted_pending"


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    """Result of score submission."""

    outcome: SubmissionOutcome
    score_id: int | None = None
    beatmap_id: int | None = None
    beatmapset_id: int | None = None
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
    submitted_at: datetime
    beatmap_id: int | None = None
    submission_metadata: Mapping[str, str] = field(default_factory=_empty_submission_metadata)


def hash_submission_metadata(metadata: Mapping[str, str]) -> dict[str, str]:
    """Return SHA-256 hashes for optional opaque score submission fields."""
    return {
        f"{key}_sha256": hashlib.sha256(value.encode()).hexdigest()
        for key, value in sorted(metadata.items())
        if key in _OPAQUE_METADATA_FIELDS
    }


def _grade_discrepancy(client_grade: str | None, server_grade: str) -> dict[str, str] | None:
    if client_grade is None:
        return None

    normalized_client_grade = client_grade.strip().upper()
    if not normalized_client_grade or normalized_client_grade == server_grade:
        return None

    return {
        "client_grade": client_grade,
        "server_grade": server_grade,
    }


def generate_submission_request_hash(input_data: ParsedSubmissionInput) -> str:
    """Hash request material that is stable across network retries."""
    hasher = hashlib.sha256()
    _update_fingerprint_bytes(hasher, b"encrypted_payload", input_data.encrypted_payload)
    _update_fingerprint_bytes(hasher, b"iv", input_data.iv)
    _update_fingerprint_text(
        hasher,
        "password_md5_hash",
        hashlib.sha256(input_data.password_md5.encode()).hexdigest(),
    )
    replay_marker = b"" if input_data.replay_data is None else input_data.replay_data
    _update_fingerprint_bytes(hasher, b"replay", replay_marker)
    _update_fingerprint_text(hasher, "replay_present", str(input_data.replay_data is not None))
    _update_fingerprint_text(hasher, "client_hash", input_data.client_hash)
    _update_fingerprint_text(hasher, "fail_time_ms", str(input_data.fail_time_ms))
    _update_fingerprint_text(hasher, "osu_version", str(input_data.osu_version))
    _update_fingerprint_text(hasher, "beatmap_id", str(input_data.beatmap_id or ""))
    for key, digest in hash_submission_metadata(input_data.submission_metadata).items():
        _update_fingerprint_text(hasher, f"metadata:{key}", digest)
    return hasher.hexdigest()


def generate_submission_fingerprint(
    *,
    user_id: int,
    beatmap_checksum: str,
    submitted_timestamp: str | None,
    request_hash: str,
) -> str:
    """Generate a submission fingerprint per Requirement 6.4."""
    hasher = hashlib.sha256()
    _update_fingerprint_text(hasher, "user_id", str(user_id))
    _update_fingerprint_text(hasher, "beatmap_checksum", beatmap_checksum)
    _update_fingerprint_text(hasher, "submitted_timestamp", submitted_timestamp or "")
    _update_fingerprint_text(hasher, "request_hash", request_hash)
    return hasher.hexdigest()


class ScoreSubmissionService:
    """Orchestrate score submission use-case.

    Requirements: R1-R12 (all Wave 1 requirements)
    """

    def __init__(
        self,
        score_repo: ScoreRepository,
        submission_repo: ScoreSubmissionRepository,
        replay_repo: ReplayRepository,
        replay_blob_storage: ReplayBlobStorage,
        payload_decryptor: ScorePayloadDecryptor,
        auth_service: ScoreAuthorizationService,
        beatmap_resolver: BeatmapEligibilityResolver,
    ) -> None:
        self._score_repo: ScoreRepository = score_repo
        self._submission_repo: ScoreSubmissionRepository = submission_repo
        self._replay_repo: ReplayRepository = replay_repo
        self._replay_blob_storage: ReplayBlobStorage = replay_blob_storage
        self._payload_decryptor: ScorePayloadDecryptor = payload_decryptor
        self._auth_service: ScoreAuthorizationService = auth_service
        self._beatmap_resolver: BeatmapEligibilityResolver = beatmap_resolver

    async def submit_score(  # noqa: PLR0911, PLR0912, PLR0915
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
        start_time = time.perf_counter()

        request_hash = generate_submission_request_hash(input_data)
        opaque_field_hashes = hash_submission_metadata(input_data.submission_metadata)

        # 3. Decrypt payload (R3.1-3.4)
        decrypt_start = time.perf_counter()
        try:
            decrypted = self._payload_decryptor.decrypt_score_payload(
                input_data.encrypted_payload,
                input_data.iv,
                input_data.osu_version,
            )
            decrypt_latency_ms = (time.perf_counter() - decrypt_start) * 1000
        except DecryptionError as e:
            logger.warning(
                "score_submission_failed",
                reason="decryption_failed",
                request_hash=request_hash,
                opaque_fields=opaque_field_hashes or None,
                error=str(e),
            )
            return SubmissionResult(
                outcome=SubmissionOutcome.TERMINAL_REJECTED,
                error_reason=f"decryption_failed: {e}",
            )
        if not decrypted.checksum_valid:
            logger.warning(
                "score_submission_failed",
                reason="crypto_checksum_invalid",
                request_hash=request_hash,
                opaque_fields=opaque_field_hashes or None,
            )
            return SubmissionResult(
                outcome=SubmissionOutcome.TERMINAL_REJECTED,
                error_reason="crypto_checksum_invalid",
            )

        # 4. Parse payload (R5.1)
        try:
            parsed = parse(decrypted.plaintext)
        except ParseError as e:
            logger.warning(
                "score_submission_failed",
                reason="parse_failed",
                request_hash=request_hash,
                opaque_fields=opaque_field_hashes or None,
                error=str(e),
            )
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

        fingerprint = generate_submission_fingerprint(
            user_id=auth_ctx.user_id,
            beatmap_checksum=parsed.beatmap_checksum,
            submitted_timestamp=parsed.client_submitted_at,
            request_hash=request_hash,
        )
        existing = await self._submission_repo.get_by_fingerprint(fingerprint)
        if existing is not None:
            return self._result_from_existing_submission(existing)

        submission = ScoreSubmission(
            id=None,
            fingerprint=fingerprint,
            user_id=auth_ctx.user_id,
            beatmap_checksum=parsed.beatmap_checksum,
            submitted_at=input_data.submitted_at,
            state=_STATE_PROCESSING,
            result_snapshot=None,
        )
        try:
            active_submission = await self._submission_repo.create(submission)
        except ValueError:
            raced_submission = await self._submission_repo.get_by_fingerprint(fingerprint)
            if raced_submission is not None:
                return self._result_from_existing_submission(raced_submission)
            raise
        assert active_submission.id is not None, "Submission ID must be set after creation"

        if not auth_ctx.authorized:
            password_hash = hashlib.sha256(input_data.password_md5.encode()).hexdigest()
            logger.warning(
                "score_submission_failed",
                reason="authorization_failed",
                fingerprint=fingerprint,
                password_hash=password_hash,
                username=parsed.username,
                user_id=auth_ctx.user_id,
                password_valid=auth_ctx.password_valid,
                session_valid=auth_ctx.session_valid,
                identity_match=auth_ctx.payload_identity_match,
            )
            return await self._record_terminal_reject(
                active_submission,
                self._format_auth_error(auth_ctx),
                opaque_field_hashes,
            )

        # 5.5. Check playstyle (R1.3, R1.4)
        if self._is_relax_or_autopilot(parsed.mods):
            error_reason = "playstyle_not_supported: relax_or_autopilot"
            logger.warning(
                "score_submission_failed",
                reason="playstyle_not_supported",
                fingerprint=fingerprint,
                mods=parsed.mods.to_persistence_bitmask(),
                user_id=auth_ctx.user_id,
            )
            return await self._record_terminal_reject(
                active_submission,
                error_reason,
                opaque_field_hashes,
            )

        # 6. Check beatmap eligibility (R8.1-8.5)
        beatmap_start = time.perf_counter()
        beatmap_result = await self._beatmap_resolver.resolve_by_checksum(
            parsed.beatmap_checksum,
            BeatmapResolveOptions(wait_timeout_seconds=5),
        )
        beatmap_latency_ms = (time.perf_counter() - beatmap_start) * 1000

        # 6.1. Handle beatmap not found (fetch in progress)
        if beatmap_result.beatmap is None:
            error_reason = "beatmap_fetch_in_progress"
            logger.info(
                "score_submission_retryable",
                reason=error_reason,
                fingerprint=fingerprint,
                beatmap_checksum=parsed.beatmap_checksum,
                opaque_fields=opaque_field_hashes or None,
            )
            return await self._record_retryable(
                active_submission,
                error_reason,
                opaque_field_hashes,
            )

        # 6.2. Check eligibility
        eligibility = beatmap_result.eligibility
        accepts_submission = False
        if eligibility is not None:
            accepts_submission = (
                eligibility.accepts_scores if parsed.passed else eligibility.accepts_failed_scores
            )
        if not accepts_submission:
            denial_reason = eligibility.denial_reason if eligibility is not None else None
            error_reason = f"beatmap_ineligible: {denial_reason or 'not_accepting_scores'}"
            logger.warning(
                "score_submission_failed",
                reason="beatmap_ineligible",
                fingerprint=fingerprint,
                beatmap_id=input_data.beatmap_id,
                beatmap_checksum=parsed.beatmap_checksum,
                denial_reason=denial_reason,
                passed=parsed.passed,
            )
            return await self._record_terminal_reject(
                active_submission,
                error_reason,
                opaque_field_hashes,
            )

        replay_byte_size = (
            len(input_data.replay_data) if input_data.replay_data is not None else None
        )
        if input_data.replay_data == b"":
            error_reason = "empty_replay_data"
            logger.warning(
                "score_submission_failed",
                reason="empty_replay_data",
                fingerprint=fingerprint,
                passed=parsed.passed,
                fail_time_ms=input_data.fail_time_ms,
            )
            return await self._record_terminal_reject(
                active_submission,
                error_reason,
                opaque_field_hashes,
            )
        # 7. Validate hit counts (R5.1-5.5)
        try:
            validation = validate_hit_counts(parsed)
        except ValidationError as e:
            error_reason = f"validation_failed: {e}"
            logger.warning(
                "score_submission_failed",
                reason="validation_failed",
                fingerprint=fingerprint,
                error=str(e),
            )
            return await self._record_terminal_reject(
                active_submission,
                error_reason,
                opaque_field_hashes,
            )

        grade_discrepancy = _grade_discrepancy(parsed.client_grade, validation.grade.value)
        if grade_discrepancy is not None:
            logger.info(
                "score_grade_discrepancy",
                fingerprint=fingerprint,
                user_id=auth_ctx.user_id,
                beatmap_checksum=parsed.beatmap_checksum,
                client_grade=grade_discrepancy["client_grade"],
                server_grade=grade_discrepancy["server_grade"],
            )

        # 8. Check uniqueness (R6.1, R6.2)
        existing_score = await self._score_repo.get_by_online_checksum(parsed.online_checksum)
        if existing_score is not None:
            error_reason = "duplicate_online_checksum"
            logger.warning(
                "score_submission_failed",
                reason="duplicate_online_checksum",
                fingerprint=fingerprint,
                online_checksum=parsed.online_checksum,
                user_id=auth_ctx.user_id,
                score_id=existing_score.id,
                beatmap_id=existing_score.beatmap_id,
                beatmap_checksum=parsed.beatmap_checksum,
            )
            return await self._record_terminal_reject(
                active_submission,
                error_reason,
                opaque_field_hashes,
            )

        replay_data = input_data.replay_data
        replay_checksum: str | None = None
        if replay_data is not None:
            replay_checksum = hashlib.sha256(replay_data).hexdigest()
            if await self._replay_repo.exists_by_checksum(replay_checksum):
                error_reason = "duplicate_replay_checksum"
                logger.warning(
                    "score_submission_failed",
                    reason="duplicate_replay_checksum",
                    fingerprint=fingerprint,
                    replay_checksum=replay_checksum,
                    user_id=auth_ctx.user_id,
                    beatmap_checksum=parsed.beatmap_checksum,
                )
                return await self._record_terminal_reject(
                    active_submission,
                    error_reason,
                    opaque_field_hashes,
                )

        replay_blob_result: BlobStoreResult | None = None
        if replay_data is not None:
            try:
                replay_blob_result = await self._replay_blob_storage.put_bytes(
                    replay_data,
                    content_type=_REPLAY_CONTENT_TYPE,
                )
            except Exception as exc:
                logger.warning(
                    "score_submission_retryable",
                    reason="replay_blob_store_failed",
                    fingerprint=fingerprint,
                    error=type(exc).__name__,
                )
                return await self._record_retryable(
                    active_submission,
                    "replay_blob_store_failed",
                    opaque_field_hashes,
                )

        resolved_beatmap_id = input_data.beatmap_id or beatmap_result.beatmap.id
        resolved_beatmapset_id = (
            beatmap_result.beatmapset.id if beatmap_result.beatmapset is not None else 0
        )
        beatmap_status_at_submission = beatmap_result.beatmap.effective_status.value

        # 9. Persist score (R7.1-7.5, R12.1-12.4)
        score = Score(
            id=None,
            user_id=auth_ctx.user_id,
            beatmap_id=resolved_beatmap_id,
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
            beatmap_status_at_submission=beatmap_status_at_submission,
        )

        db_start = time.perf_counter()
        created_score = await self._score_repo.create(score)
        db_latency_ms = (time.perf_counter() - db_start) * 1000
        assert created_score.id is not None, "Score ID must be set after creation"

        # 10. Persist replay if present (R7.3-7.4)
        if replay_data is not None and replay_checksum:
            assert replay_blob_result is not None, "Replay blob must be stored before attachment"
            replay = Replay(
                id=None,
                score_id=created_score.id,
                blob_id=replay_blob_result.blob.id,
                checksum_sha256=replay_checksum,
                byte_size=len(replay_data),
            )
            created_replay = await self._replay_repo.create(replay)
        else:
            created_replay = None

        # 11. Record submission (R9.1)
        completion_snapshot: dict[str, object] = {
            "score_id": created_score.id,
            "beatmap_id": resolved_beatmap_id,
            "beatmapset_id": resolved_beatmapset_id,
            "beatmap_status_at_submission": beatmap_status_at_submission,
        }
        if grade_discrepancy is not None:
            completion_snapshot["grade_discrepancy"] = grade_discrepancy
        if opaque_field_hashes:
            completion_snapshot["opaque_fields"] = opaque_field_hashes
        if created_replay is not None:
            completion_snapshot["replay_attachment_id"] = created_replay.id
            completion_snapshot["replay_blob_id"] = created_replay.blob_id

        await self._submission_repo.update_state(
            active_submission.id,
            _STATE_COMPLETED,
            completion_snapshot,
        )

        total_duration_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            "score_submission_completed",
            duration_ms=total_duration_ms,
            decrypt_latency_ms=decrypt_latency_ms,
            beatmap_latency_ms=beatmap_latency_ms,
            db_latency_ms=db_latency_ms,
            fingerprint=fingerprint,
            user_id=auth_ctx.user_id,
            beatmap_id=resolved_beatmap_id,
            score_id=created_score.id,
            replay_attachment_id=created_replay.id if created_replay is not None else None,
            replay_present=replay_data is not None,
            replay_byte_size=replay_byte_size,
            passed=parsed.passed,
            fail_time_ms=input_data.fail_time_ms,
            beatmap_status_at_submission=beatmap_status_at_submission,
            opaque_fields=opaque_field_hashes or None,
        )

        return SubmissionResult(
            outcome=SubmissionOutcome.COMPLETED,
            score_id=created_score.id,
            beatmap_id=resolved_beatmap_id,
            beatmapset_id=resolved_beatmapset_id,
        )

    def _result_from_existing_submission(self, submission: ScoreSubmission) -> SubmissionResult:
        """Return the client-safe response for an existing submission fingerprint."""
        if submission.state in {_STATE_PROCESSING, "received"}:
            logger.info(
                "score_submission_idempotency_pending",
                fingerprint=submission.fingerprint,
                submission_id=submission.id,
            )
            return SubmissionResult(
                outcome=SubmissionOutcome.ACCEPTED_PENDING,
                error_reason="accepted_pending",
            )

        snapshot = submission.result_snapshot or {}
        if submission.state == _STATE_COMPLETED:
            score_id_value = snapshot.get("score_id")
            beatmap_id_value = snapshot.get("beatmap_id")
            beatmapset_id_value = snapshot.get("beatmapset_id")
            if isinstance(score_id_value, int):
                logger.info(
                    "score_submission_idempotency_hit",
                    fingerprint=submission.fingerprint,
                    score_id=score_id_value,
                    beatmap_id=beatmap_id_value if isinstance(beatmap_id_value, int) else None,
                    beatmapset_id=beatmapset_id_value
                    if isinstance(beatmapset_id_value, int)
                    else None,
                )
                return SubmissionResult(
                    outcome=SubmissionOutcome.COMPLETED,
                    score_id=score_id_value,
                    beatmap_id=beatmap_id_value if isinstance(beatmap_id_value, int) else None,
                    beatmapset_id=beatmapset_id_value
                    if isinstance(beatmapset_id_value, int)
                    else None,
                )

        error_reason = snapshot.get("error_reason")
        if submission.state == _STATE_RETRYABLE:
            return SubmissionResult(
                outcome=SubmissionOutcome.RETRYABLE,
                error_reason=error_reason if isinstance(error_reason, str) else "retryable",
            )

        return SubmissionResult(
            outcome=SubmissionOutcome.TERMINAL_REJECTED,
            error_reason=error_reason if isinstance(error_reason, str) else "terminal_rejected",
        )

    async def _record_terminal_reject(
        self,
        submission: ScoreSubmission,
        error_reason: str,
        opaque_field_hashes: Mapping[str, str] | None = None,
    ) -> SubmissionResult:
        assert submission.id is not None, "Submission ID must be set before state update"
        result_snapshot: dict[str, object] = {"error_reason": error_reason}
        if opaque_field_hashes:
            result_snapshot["opaque_fields"] = dict(opaque_field_hashes)
        await self._submission_repo.update_state(
            submission.id,
            _STATE_TERMINAL_REJECTED,
            result_snapshot,
        )
        return SubmissionResult(
            outcome=SubmissionOutcome.TERMINAL_REJECTED,
            error_reason=error_reason,
        )

    async def _record_retryable(
        self,
        submission: ScoreSubmission,
        error_reason: str,
        opaque_field_hashes: Mapping[str, str] | None = None,
    ) -> SubmissionResult:
        assert submission.id is not None, "Submission ID must be set before state update"
        result_snapshot: dict[str, object] = {"error_reason": error_reason}
        if opaque_field_hashes:
            result_snapshot["opaque_fields"] = dict(opaque_field_hashes)
        await self._submission_repo.update_state(
            submission.id,
            _STATE_RETRYABLE,
            result_snapshot,
        )
        return SubmissionResult(
            outcome=SubmissionOutcome.RETRYABLE,
            error_reason=error_reason,
        )

    def _format_auth_error(self, ctx: AuthorizationContext) -> str:
        """Format authorization error without exposing credentials (R11.1)."""
        if not ctx.password_valid:
            return "authorization_failed: invalid_password"
        if not ctx.session_valid:
            return "authorization_failed: no_active_session"
        if not ctx.payload_identity_match:
            return "authorization_failed: identity_mismatch"
        return "authorization_failed: unknown"

    def _is_relax_or_autopilot(self, mods: ModCombination) -> bool:
        """Check if submission contains Relax or Autopilot mods (R1.3, R1.4)."""
        return mods.has(Mod.RELAX) or mods.has(Mod.AUTOPILOT)
