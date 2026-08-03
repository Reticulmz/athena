"""Stable verification surfaceとevidence catalogを提供する."""

from __future__ import annotations

from athena_cli.stable_verification.models import (
    EvidenceEntry,
    EvidenceGap,
    EvidenceScope,
    EvidenceType,
    StableSurface,
    SurfaceInventoryEntry,
    SurfaceScope,
    VerificationStatus,
)

_SURFACE_INVENTORY: tuple[SurfaceInventoryEntry, ...] = (
    SurfaceInventoryEntry(
        surface=StableSurface.REGISTRATION,
        implemented=True,
        scope=SurfaceScope.IN_SCOPE,
        description="Stable account registration via legacy web endpoint.",
    ),
    SurfaceInventoryEntry(
        surface=StableSurface.BANCHO_LOGIN,
        implemented=True,
        scope=SurfaceScope.IN_SCOPE,
        description="Stable bancho login request and packet-stream response.",
    ),
    SurfaceInventoryEntry(
        surface=StableSurface.POLLING,
        implemented=True,
        scope=SurfaceScope.IN_SCOPE,
        description="Token-authenticated stable bancho packet polling.",
    ),
    SurfaceInventoryEntry(
        surface=StableSurface.CHAT,
        implemented=True,
        scope=SurfaceScope.IN_SCOPE,
        description="Stable bancho channel and private chat packet flows.",
    ),
    SurfaceInventoryEntry(
        surface=StableSurface.GETSCORES,
        implemented=True,
        scope=SurfaceScope.IN_SCOPE,
        description="Stable web legacy getscores endpoint and text response bodies.",
    ),
    SurfaceInventoryEntry(
        surface=StableSurface.SCORE_SUBMIT,
        implemented=True,
        scope=SurfaceScope.IN_SCOPE,
        description="Stable modular score submission endpoint and chart response.",
    ),
    SurfaceInventoryEntry(
        surface=StableSurface.REPLAY_DOWNLOAD,
        implemented=False,
        scope=SurfaceScope.IN_SCOPE,
        description="Stable replay download endpoint contract and evidence fixtures.",
    ),
)

_EVIDENCE: tuple[EvidenceEntry, ...] = (
    EvidenceEntry(
        surface=StableSurface.REGISTRATION,
        evidence_type=EvidenceType.AUTOMATED_TEST,
        scope=EvidenceScope.MANDATORY,
        reference="apps/athena_server/tests/integration/test_registration_flow.py",
        purpose="registration request parsing, validation, and stable response behavior",
    ),
    EvidenceEntry(
        surface=StableSurface.BANCHO_LOGIN,
        evidence_type=EvidenceType.AUTOMATED_TEST,
        scope=EvidenceScope.MANDATORY,
        reference="apps/athena_server/tests/integration/test_login_flow.py",
        purpose="stable bancho login routing, credentials, and packet stream",
    ),
    EvidenceEntry(
        surface=StableSurface.POLLING,
        evidence_type=EvidenceType.AUTOMATED_TEST,
        scope=EvidenceScope.MANDATORY,
        reference="apps/athena_server/tests/integration/test_polling_e2e.py",
        purpose="stable token polling and queued packet delivery",
    ),
    EvidenceEntry(
        surface=StableSurface.CHAT,
        evidence_type=EvidenceType.AUTOMATED_TEST,
        scope=EvidenceScope.MANDATORY,
        reference="apps/athena_server/tests/integration/test_chat_e2e.py",
        purpose="stable chat packet handling and delivery contract",
    ),
    EvidenceEntry(
        surface=StableSurface.GETSCORES,
        evidence_type=EvidenceType.GOLDEN_FIXTURE,
        scope=EvidenceScope.MANDATORY,
        reference="apps/athena_server/tests/unit/transports/web_legacy/test_getscores_fixtures.py",
        purpose="decoded getscores stable response fixture compatibility",
    ),
    EvidenceEntry(
        surface=StableSurface.GETSCORES,
        evidence_type=EvidenceType.AUTOMATED_TEST,
        scope=EvidenceScope.MANDATORY,
        reference="apps/athena_server/tests/integration/test_getscores_endpoint.py",
        purpose="getscores host routing and endpoint response contract",
    ),
    EvidenceEntry(
        surface=StableSurface.GETSCORES,
        evidence_type=EvidenceType.GOLDEN_FIXTURE,
        scope=EvidenceScope.MANDATORY,
        reference=(
            "apps/athena_server/tests/fixtures/stable_compatibility/getscores/response_shapes.json"
        ),
        purpose="getscores completion response shape contract",
    ),
    EvidenceEntry(
        surface=StableSurface.GETSCORES,
        evidence_type=EvidenceType.GOLDEN_FIXTURE,
        scope=EvidenceScope.MANDATORY,
        reference="apps/athena_server/tests/fixtures/stable_compatibility/getscores/branch_cases.json",
        purpose="getscores completion branch selection catalog",
    ),
    EvidenceEntry(
        surface=StableSurface.GETSCORES,
        evidence_type=EvidenceType.GOLDEN_FIXTURE,
        scope=EvidenceScope.MANDATORY,
        reference=(
            "apps/athena_server/tests/fixtures/stable_compatibility/getscores/beatmap_status_crosswalk.json"
        ),
        purpose="getscores completion beatmap status crosswalk",
    ),
    EvidenceEntry(
        surface=StableSurface.GETSCORES,
        evidence_type=EvidenceType.HEADLESS_PROBE,
        scope=EvidenceScope.OPTIONAL,
        reference="optional:osu.py getscores probe",
        purpose="optional client-like getscores probe against local Athena",
    ),
    EvidenceEntry(
        surface=StableSurface.SCORE_SUBMIT,
        evidence_type=EvidenceType.AUTOMATED_TEST,
        scope=EvidenceScope.MANDATORY,
        reference="apps/athena_server/tests/unit/transports/web_legacy/test_score_submit_mapper.py",
        purpose="score submit mapper request metadata and chart response contract",
    ),
    EvidenceEntry(
        surface=StableSurface.SCORE_SUBMIT,
        evidence_type=EvidenceType.AUTOMATED_TEST,
        scope=EvidenceScope.MANDATORY,
        reference="apps/athena_server/tests/integration/transports/web_legacy/test_score_submit_e2e.py",
        purpose="score submit endpoint workflow and response compatibility",
    ),
    EvidenceEntry(
        surface=StableSurface.REPLAY_DOWNLOAD,
        evidence_type=EvidenceType.GOLDEN_FIXTURE,
        scope=EvidenceScope.MANDATORY,
        reference=(
            "apps/athena_server/tests/fixtures/stable_compatibility/replay_download/"
            "target_client_request_metadata.json"
        ),
        purpose="target stable client replay download route and auth metadata",
    ),
    EvidenceEntry(
        surface=StableSurface.REPLAY_DOWNLOAD,
        evidence_type=EvidenceType.GOLDEN_FIXTURE,
        scope=EvidenceScope.MANDATORY,
        reference=(
            "apps/athena_server/tests/fixtures/stable_compatibility/replay_download/"
            "target_client_response_metadata.json"
        ),
        purpose="target stable client replay download response metadata",
    ),
    EvidenceEntry(
        surface=StableSurface.REPLAY_DOWNLOAD,
        evidence_type=EvidenceType.GOLDEN_FIXTURE,
        scope=EvidenceScope.MANDATORY,
        reference=(
            "apps/athena_server/tests/fixtures/stable_compatibility/replay_download/reference_responses.json"
        ),
        purpose="replay download reference implementation response audit",
    ),
    EvidenceEntry(
        surface=StableSurface.REPLAY_DOWNLOAD,
        evidence_type=EvidenceType.GOLDEN_FIXTURE,
        scope=EvidenceScope.MANDATORY,
        reference=(
            "apps/athena_server/tests/fixtures/stable_compatibility/replay_download/response_contract.json"
        ),
        purpose="replay download branch readiness response contract",
    ),
    EvidenceEntry(
        surface=StableSurface.REPLAY_DOWNLOAD,
        evidence_type=EvidenceType.GOLDEN_FIXTURE,
        scope=EvidenceScope.MANDATORY,
        reference=(
            "apps/athena_server/tests/fixtures/stable_compatibility/replay_download/body_assembly_decision.json"
        ),
        purpose="replay download body assembly decision metadata",
    ),
    EvidenceEntry(
        surface=StableSurface.REPLAY_DOWNLOAD,
        evidence_type=EvidenceType.AUTOMATED_TEST,
        scope=EvidenceScope.MANDATORY,
        reference="apps/athena_server/tests/unit/athena_cli/stable_verification/test_replay_download.py",
        purpose="replay blob diagnostic classification and redaction contract",
    ),
)

_GAPS: tuple[EvidenceGap, ...] = (
    EvidenceGap(
        surface=StableSurface.GETSCORES,
        status=VerificationStatus.KNOWN_GAP,
        summary=(
            "required modern getscores route is implementation-complete but lacks "
            "Target Stable Client traffic confirmation; hand off to Issue #27 / #28"
        ),
        owner="Issue #27 / #28 Target Stable Client traffic verification",
    ),
    EvidenceGap(
        surface=StableSurface.SCORE_SUBMIT,
        status=VerificationStatus.KNOWN_GAP,
        summary="rank and user stat fields depend on user-stats and leaderboard projections",
        owner="user-stats, beatmap-leaderboards",
    ),
    EvidenceGap(
        surface=StableSurface.REPLAY_DOWNLOAD,
        status=VerificationStatus.KNOWN_GAP,
        summary=(
            "endpoint implementation, unresolved malformed branches, local target-body "
            "validation artifact, and success body implementation remain pending"
        ),
        owner="replay-download-contract",
    ),
)


def list_surface_inventory() -> tuple[SurfaceInventoryEntry, ...]:
    """Stable verification対象surfaceの不変inventoryを返す.

    Returns:
        tuple[SurfaceInventoryEntry, ...]: 実装状態と対象scopeを含む定義順のinventory.

    Notes:
        返すtupleはmodule内のcatalogを共有する.呼出側はentryを変更せず参照専用で扱う.
    """
    return _SURFACE_INVENTORY


def list_surfaces() -> tuple[StableSurface, ...]:
    """Stable verification対象のsurfaceをinventory順で返す.

    Returns:
        tuple[StableSurface, ...]: 実装状態によらずcatalogへ登録されたsurface.

    Notes:
        runnerはこの順序を,明示的なsurface指定がない場合の実行候補に利用する.
    """
    return tuple(entry.surface for entry in _SURFACE_INVENTORY)


def list_evidence(surface: StableSurface | None = None) -> tuple[EvidenceEntry, ...]:
    """指定surfaceのverification evidenceを返す.

    Args:
        surface (StableSurface | None): 絞り込むsurface.Noneの場合は全surfaceのevidenceを返す.

    Returns:
        tuple[EvidenceEntry, ...]: catalog順のevidence.該当surfaceがない場合は空tuple.

    Notes:
        Headless probeを含むoptional evidenceも,mandatory evidenceと同じcatalogから返す.
    """
    if surface is None:
        return _EVIDENCE

    return tuple(entry for entry in _EVIDENCE if entry.surface is surface)


def list_gaps(surface: StableSurface | None = None) -> tuple[EvidenceGap, ...]:
    """指定surfaceの既知verification gapを返す.

    Args:
        surface (StableSurface | None): 絞り込むsurface.Noneの場合は全既知gapを返す.

    Returns:
        tuple[EvidenceGap, ...]: catalog順のknown gap.該当surfaceがない場合は空tuple.

    Notes:
        返すgapは実装状態を変更せず,未確認contractの引継ぎ先を表す.
    """
    if surface is None:
        return _GAPS

    return tuple(gap for gap in _GAPS if gap.surface is surface)


__all__ = [
    "list_evidence",
    "list_gaps",
    "list_surface_inventory",
    "list_surfaces",
]
