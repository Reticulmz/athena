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
    assert {entry.evidence_type for entry in evidence} == {EvidenceType.GOLDEN_FIXTURE}
    assert all(entry.scope is EvidenceScope.MANDATORY for entry in evidence)
    assert all((PROJECT_ROOT / entry.reference).exists() for entry in evidence)
    assert all(gap.status is VerificationStatus.KNOWN_GAP for gap in gaps)
