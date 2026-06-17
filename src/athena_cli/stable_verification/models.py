from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


def _empty_credential_fields() -> dict[str, str]:
    return {}


class StableSurface(StrEnum):
    REGISTRATION = "registration"
    BANCHO_LOGIN = "bancho_login"
    POLLING = "polling"
    CHAT = "chat"
    GETSCORES = "getscores"
    SCORE_SUBMIT = "score_submit"


class EvidenceType(StrEnum):
    AUTOMATED_TEST = "automated_test"
    GOLDEN_FIXTURE = "golden_fixture"
    HEADLESS_PROBE = "headless_probe"


class EvidenceScope(StrEnum):
    MANDATORY = "mandatory"
    OPTIONAL = "optional"


class SurfaceScope(StrEnum):
    IN_SCOPE = "in_scope"
    OUT_OF_SCOPE = "out_of_scope"


class VerificationStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    KNOWN_GAP = "known_gap"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class StableTarget:
    base_url: str
    host_identity: str
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class GetscoresProbeCase:
    name: str
    checksum: str
    filename: str
    beatmapset_id: int | None
    mode: int
    mods: int
    leaderboard_type: str
    request_version: int


@dataclass(frozen=True, slots=True)
class SurfaceInventoryEntry:
    surface: StableSurface
    implemented: bool
    scope: SurfaceScope
    description: str


@dataclass(frozen=True, slots=True)
class EvidenceEntry:
    surface: StableSurface
    evidence_type: EvidenceType
    scope: EvidenceScope
    reference: str
    purpose: str


@dataclass(frozen=True, slots=True)
class EvidenceGap:
    surface: StableSurface
    status: VerificationStatus
    summary: str
    owner: str


@dataclass(frozen=True, slots=True)
class DiagnosticSummary:
    message: str
    method: str | None = None
    path: str | None = None
    status_code: int | None = None
    response_byte_size: int | None = None
    sanitized_error: str | None = None


@dataclass(frozen=True, slots=True)
class SecretProbeInput:
    password: str | None = field(default=None, repr=False)
    password_hash: str | None = field(default=None, repr=False)
    session_token: str | None = field(default=None, repr=False)
    raw_replay: bytes | None = field(default=None, repr=False)
    credential_fields: Mapping[str, str] = field(
        default_factory=_empty_credential_fields,
        repr=False,
    )


@dataclass(frozen=True, slots=True)
class SurfaceResult:
    surface: StableSurface
    status: VerificationStatus
    evidence_type: EvidenceType
    scope: EvidenceScope
    diagnostic_summary: DiagnosticSummary
    reference: str | None = None

    @property
    def fails_run(self) -> bool:
        if self.status is VerificationStatus.FAIL:
            return True

        return (
            self.scope is EvidenceScope.MANDATORY and self.status is VerificationStatus.UNAVAILABLE
        )


@dataclass(frozen=True, slots=True)
class VerificationRunResult:
    target: StableTarget | None
    results: tuple[SurfaceResult, ...]

    @property
    def failed(self) -> bool:
        return any(result.fails_run for result in self.results)


__all__ = [
    "DiagnosticSummary",
    "EvidenceEntry",
    "EvidenceGap",
    "EvidenceScope",
    "EvidenceType",
    "GetscoresProbeCase",
    "SecretProbeInput",
    "StableSurface",
    "StableTarget",
    "SurfaceInventoryEntry",
    "SurfaceResult",
    "SurfaceScope",
    "VerificationRunResult",
    "VerificationStatus",
]
