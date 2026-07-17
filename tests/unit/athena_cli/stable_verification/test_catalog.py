from __future__ import annotations

from pathlib import Path

from athena_cli.stable_verification.catalog import (
    list_evidence,
    list_gaps,
    list_surface_inventory,
    list_surfaces,
)
from athena_cli.stable_verification.models import (
    EvidenceScope,
    EvidenceType,
    StableSurface,
    SurfaceScope,
    VerificationStatus,
)

PROJECT_ROOT = Path(__file__).resolve().parents[4]
_GETSCORES_COMPLETION_MANIFEST_REFERENCES = frozenset(
    (
        "tests/fixtures/stable_compatibility/getscores/response_shapes.json",
        "tests/fixtures/stable_compatibility/getscores/branch_cases.json",
        "tests/fixtures/stable_compatibility/getscores/beatmap_status_crosswalk.json",
    )
)


def test_catalog_lists_all_required_stable_surfaces() -> None:
    assert set(list_surfaces()) == {
        StableSurface.REGISTRATION,
        StableSurface.BANCHO_LOGIN,
        StableSurface.POLLING,
        StableSurface.CHAT,
        StableSurface.GETSCORES,
        StableSurface.SCORE_SUBMIT,
        StableSurface.REPLAY_DOWNLOAD,
    }


def test_inventory_distinguishes_implemented_surface_scope() -> None:
    inventory = {entry.surface: entry for entry in list_surface_inventory()}

    assert set(inventory) == set(list_surfaces())
    assert all(
        entry.implemented
        for surface, entry in inventory.items()
        if surface is not StableSurface.REPLAY_DOWNLOAD
    )
    assert inventory[StableSurface.REPLAY_DOWNLOAD].implemented is False
    assert all(entry.scope is SurfaceScope.IN_SCOPE for entry in inventory.values())


def test_catalog_references_existing_stable_evidence_without_replacing_it() -> None:
    evidence = list_evidence()

    assert evidence
    assert {entry.surface for entry in evidence} == set(list_surfaces())
    existing_evidence = [
        entry for entry in evidence if entry.evidence_type is not EvidenceType.HEADLESS_PROBE
    ]

    assert all((PROJECT_ROOT / entry.reference).exists() for entry in existing_evidence)
    assert EvidenceScope.MANDATORY in {entry.scope for entry in evidence}
    assert EvidenceScope.OPTIONAL in {entry.scope for entry in evidence}
    assert EvidenceType.AUTOMATED_TEST in {entry.evidence_type for entry in evidence}
    assert EvidenceType.GOLDEN_FIXTURE in {entry.evidence_type for entry in evidence}
    assert EvidenceType.HEADLESS_PROBE in {entry.evidence_type for entry in evidence}


def test_catalog_keeps_distinct_purposes_for_repeated_surface_evidence() -> None:
    getscores_evidence = list_evidence(StableSurface.GETSCORES)

    assert len(getscores_evidence) >= 2
    assert len({entry.purpose for entry in getscores_evidence}) == len(getscores_evidence)


def test_getscores_catalog_separates_completion_evidence_from_optional_probe() -> None:
    """Getscoresの実装完了証跡と任意probeを別々に投影することを検証する.

    Args:
        なし.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: 実装状態, completion manifest, または任意probeの分類が異なる場合.
    """

    inventory = {entry.surface: entry for entry in list_surface_inventory()}
    getscores_evidence = list_evidence(StableSurface.GETSCORES)
    completion_evidence = tuple(
        entry
        for entry in getscores_evidence
        if entry.reference in _GETSCORES_COMPLETION_MANIFEST_REFERENCES
    )
    optional_probe = tuple(
        entry
        for entry in getscores_evidence
        if entry.reference == "optional:osu.py getscores probe"
    )

    assert inventory[StableSurface.GETSCORES].implemented is True
    assert inventory[StableSurface.GETSCORES].scope is SurfaceScope.IN_SCOPE
    assert {entry.reference for entry in completion_evidence} == (
        _GETSCORES_COMPLETION_MANIFEST_REFERENCES
    )
    assert all(
        entry.evidence_type is EvidenceType.GOLDEN_FIXTURE
        and entry.scope is EvidenceScope.MANDATORY
        for entry in completion_evidence
    )
    assert len({entry.purpose for entry in completion_evidence}) == len(completion_evidence)
    assert len(optional_probe) == 1
    assert optional_probe[0].evidence_type is EvidenceType.HEADLESS_PROBE
    assert optional_probe[0].scope is EvidenceScope.OPTIONAL


def test_getscores_catalog_reports_required_target_traffic_handoff() -> None:
    """Getscoresの残存gapをtarget traffic未確認だけとして投影することを検証する.

    Args:
        なし.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: stale implementation gap, route分類, またはIssue handoffが異なる場合.
    """

    gaps = list_gaps(StableSurface.GETSCORES)

    assert len(gaps) == 1
    gap = gaps[0]
    assert gap.status is VerificationStatus.KNOWN_GAP
    assert gap.summary == (
        "required modern getscores route is implementation-complete but lacks "
        "Target Stable Client traffic confirmation; hand off to Issue #27 / #28"
    )
    assert gap.owner == "Issue #27 / #28 Target Stable Client traffic verification"
    assert "leaderboard score rows depend on beatmap-leaderboards" not in gap.summary
    assert "beatmap-leaderboards" not in gap.owner


def test_catalog_keeps_unrelated_known_gaps_unchanged() -> None:
    """Score submitとreplay downloadの既存known gapを維持することを検証する.

    Args:
        なし.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: Getscoresのcatalog更新が隣接surfaceのgapを変更した場合.
    """

    score_submit_gaps = list_gaps(StableSurface.SCORE_SUBMIT)
    replay_download_gaps = list_gaps(StableSurface.REPLAY_DOWNLOAD)

    assert [(gap.status, gap.summary, gap.owner) for gap in score_submit_gaps] == [
        (
            VerificationStatus.KNOWN_GAP,
            "rank and user stat fields depend on user-stats and leaderboard projections",
            "user-stats, beatmap-leaderboards",
        )
    ]
    assert [(gap.status, gap.summary, gap.owner) for gap in replay_download_gaps] == [
        (
            VerificationStatus.KNOWN_GAP,
            (
                "endpoint implementation, unresolved malformed branches, local target-body "
                "validation artifact, and success body implementation remain pending"
            ),
            "replay-download-contract",
        )
    ]


def test_catalog_reports_known_compatibility_gaps() -> None:
    gaps = list_gaps()

    assert gaps
    assert all(gap.status is VerificationStatus.KNOWN_GAP for gap in gaps)
    assert {gap.surface for gap in gaps} >= {
        StableSurface.GETSCORES,
        StableSurface.SCORE_SUBMIT,
        StableSurface.REPLAY_DOWNLOAD,
    }


def test_replay_download_catalog_entries_are_known_gap_evidence_surface() -> None:
    evidence = list_evidence(StableSurface.REPLAY_DOWNLOAD)
    gaps = list_gaps(StableSurface.REPLAY_DOWNLOAD)

    assert evidence
    assert gaps
    assert {entry.evidence_type for entry in evidence} == {
        EvidenceType.AUTOMATED_TEST,
        EvidenceType.GOLDEN_FIXTURE,
    }
    assert all(entry.scope is EvidenceScope.MANDATORY for entry in evidence)
    assert all((PROJECT_ROOT / entry.reference).exists() for entry in evidence)
    assert all(gap.status is VerificationStatus.KNOWN_GAP for gap in gaps)
