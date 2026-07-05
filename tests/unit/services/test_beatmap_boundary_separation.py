"""Regression tests for beatmap-mirror downstream boundary separation.

Verifies that beatmap-mirror components remain independent from
score-submission, leaderboard, WebUI, BanchoBot rank commands, and
Bancho transports per requirements 15.1-15.5 and 9.1/9.3.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta

import pytest

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapEligibility,
    BeatmapFetchState,
    BeatmapFileAttachment,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapRankStatus,
    BeatmapResolveOptions,
    BeatmapResolveResult,
    BeatmapSet,
    BeatmapSetResolveResult,
    BeatmapSourceVerification,
    LocalBeatmapStatus,
)
from osu_server.services.queries.beatmaps.mirror import (
    BeatmapEligibilityService,
    BeatmapMirrorService,
    BeatmapStatusResolver,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 6, 4, tzinfo=UTC)
_NEXT_REFRESH = _NOW + timedelta(days=30)
_CHECKSUM = "0123456789abcdef0123456789abcdef"

# All modules that belong to the beatmap-mirror feature boundary.
_BEATMAP_MODULES: tuple[str, ...] = (
    "osu_server.domain.beatmaps",
    "osu_server.infrastructure.beatmaps.file_sources",
    "osu_server.infrastructure.beatmaps.metadata_source_adapters",
    "osu_server.infrastructure.beatmaps.mappers",
    "osu_server.infrastructure.beatmaps.metadata_sources",
    "osu_server.repositories.interfaces.commands.beatmaps",
    "osu_server.repositories.interfaces.queries.beatmaps",
    "osu_server.repositories.memory.commands.beatmaps",
    "osu_server.repositories.memory.queries.beatmaps",
    "osu_server.services.queries.beatmaps.mirror.eligibility_service",
    "osu_server.services.queries.beatmaps.mirror.resolution_service",
    "osu_server.jobs.beatmap_fetch",
)

# Deprecated package/module paths that must not become compatibility facades.
_REMOVED_BEATMAP_PROVIDER_MODULES: tuple[str, ...] = (
    "osu_server.repositories.beatmaps",
    "osu_server.repositories.beatmaps.mappers",
    "osu_server.repositories.beatmaps.metadata_providers",
    "osu_server.services.queries.beatmaps.mirror.file_provider_service",
    "osu_server.services.queries.beatmaps.mirror.metadata_provider_service",
)

# Package prefixes that beatmap-mirror modules must NOT import from.
# These represent downstream concerns: transports, score, leaderboard, etc.
_FORBIDDEN_IMPORT_PREFIXES: tuple[str, ...] = (
    "osu_server.transports.bancho",
    "osu_server.transports.api",
    "osu_server.transports.signalr",
    "osu_server.transports.web_legacy",
)

# Score/PP/leaderboard/Bancho-related field name substrings that must NOT
# appear on beatmap domain types. These are checked against each field name
# after stripping known-legitimate prefixes (e.g., "max_" in "max_combo").
_FORBIDDEN_DOMAIN_FIELD_PATTERNS: tuple[str, ...] = (
    "score",
    "pp",
    "accuracy",
    "leaderboard",
    "rank_count",
    "playcount",
    "passcount",
    "combo",
    "mods",
    "grade",
    "replay",
    "bancho",
    "packet",
    "queue",
    "osu_file",
    "osz",
)

# Field names (exact) that are legitimate beatmap properties despite
# containing a forbidden substring. E.g. max_combo is the beatmap's
# maximum possible combo, not a score payload field.
_ALLOWED_FIELD_OVERRIDES: frozenset[str] = frozenset(
    {
        "max_combo",
        "ranked_status",  # historical field on BeatmapSet
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_beatmap(
    *,
    official_status: BeatmapRankStatus = BeatmapRankStatus.RANKED,
    local_status_override: LocalBeatmapStatus | None = None,
    source: BeatmapMetadataSource = BeatmapMetadataSource.OFFICIAL,
    source_verification: BeatmapSourceVerification = BeatmapSourceVerification.VERIFIED,
    file_attachment: BeatmapFileAttachment | None = None,
) -> Beatmap:
    return Beatmap(
        id=2_000,
        beatmapset_id=1_000,
        checksum_md5=_CHECKSUM,
        mode="osu",
        version="Another",
        total_length=240,
        hit_length=220,
        max_combo=1_234,
        bpm=180.0,
        cs=4.0,
        od=8.5,
        ar=9.4,
        hp=6.5,
        difficulty_rating=5.67,
        official_status=official_status,
        official_status_source=source,
        official_status_verified=source_verification,
        local_status_override=local_status_override,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=(
            BeatmapFileState.AVAILABLE if file_attachment is not None else BeatmapFileState.MISSING
        ),
        file_attachment=file_attachment,
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
    )


def _module_imports_forbidden(module_name: str, forbidden_prefixes: tuple[str, ...]) -> list[str]:
    """Return list of forbidden imports found in *module_name*."""
    for prefix in forbidden_prefixes:
        if prefix not in sys.modules:
            continue
    # We cannot rely on sys.modules alone because test runners preload many
    # modules. Instead, check the module's own namespace for objects that
    # originate from forbidden packages.
    violations: list[str] = []
    try:
        mod = sys.modules.get(module_name)
        if mod is None:
            __import__(module_name)
            mod = sys.modules[module_name]
    except Exception:
        return violations  # module not importable; skip

    for name, obj in vars(mod).items():  # pyright: ignore[reportAny]
        if name.startswith("_"):
            continue
        obj_module: str | None = getattr(obj, "__module__", None)  # pyright: ignore[reportAny]
        if obj_module is None:
            continue
        for prefix in forbidden_prefixes:
            if obj_module == prefix or obj_module.startswith(prefix + "."):
                violations.append(f"{module_name} imports {name} from {obj_module}")
                break
    return violations


def _domain_field_names(cls: type) -> frozenset[str]:
    """Return the set of field names declared on a dataclass."""
    return frozenset(f.name for f in fields(cls))


def _public_method_names(cls: type) -> frozenset[str]:
    """Return the set of public method names defined directly on *cls*."""
    return frozenset(
        name
        for name in dir(cls)
        if not name.startswith("_") and callable(getattr(cls, name, None))
    )


# ---------------------------------------------------------------------------
# Import boundary tests (15.1, 15.2, 15.3)
# ---------------------------------------------------------------------------


class TestBeatmapMirrorImportBoundaries:
    """Verify beatmap-mirror modules do not import from downstream packages."""

    def test_domain_module_no_transport_imports(self) -> None:
        """Domain module must not import from any transport package."""
        violations = _module_imports_forbidden(
            "osu_server.domain.beatmaps", _FORBIDDEN_IMPORT_PREFIXES
        )
        assert violations == [], f"domain.beatmaps has forbidden imports: {violations}"

    def test_service_module_no_transport_imports(self) -> None:
        """Service modules must not import from any transport package."""
        for module_name in _BEATMAP_MODULES:
            if not module_name.startswith("osu_server.services"):
                continue
            violations = _module_imports_forbidden(module_name, _FORBIDDEN_IMPORT_PREFIXES)
            assert violations == [], f"{module_name} has forbidden imports: {violations}"

    def test_infrastructure_module_no_transport_imports(self) -> None:
        """Infrastructure modules must not import from any transport package."""
        for module_name in _BEATMAP_MODULES:
            if not module_name.startswith("osu_server.infrastructure"):
                continue
            violations = _module_imports_forbidden(module_name, _FORBIDDEN_IMPORT_PREFIXES)
            assert violations == [], f"{module_name} has forbidden imports: {violations}"

    def test_repository_module_no_transport_imports(self) -> None:
        """Repository modules must not import from any transport package."""
        for module_name in _BEATMAP_MODULES:
            if not module_name.startswith("osu_server.repositories"):
                continue
            violations = _module_imports_forbidden(module_name, _FORBIDDEN_IMPORT_PREFIXES)
            assert violations == [], f"{module_name} has forbidden imports: {violations}"

    def test_job_module_no_transport_imports(self) -> None:
        """Job module must not import from any transport package."""
        violations = _module_imports_forbidden(
            "osu_server.jobs.beatmap_fetch", _FORBIDDEN_IMPORT_PREFIXES
        )
        assert violations == [], f"jobs.beatmap_fetch has forbidden imports: {violations}"

    def test_all_beatmap_modules_importable(self) -> None:
        """All beatmap-mirror modules should be importable without errors."""
        for module_name in _BEATMAP_MODULES:
            try:
                __import__(module_name)
            except Exception as exc:
                pytest.fail(f"Failed to import {module_name}: {exc}")

    def test_removed_provider_modules_not_importable(self) -> None:
        """削除済み provider module path を互換 facade として復活させない。"""
        for module_name in _REMOVED_BEATMAP_PROVIDER_MODULES:
            missing_error = False
            missing_module_name: str | None = None
            spec = None
            try:
                spec = importlib.util.find_spec(module_name)
            except ModuleNotFoundError as exc:
                missing_error = True
                missing_module_name = exc.name

            if missing_error:
                assert missing_module_name is not None
                assert module_name == missing_module_name or module_name.startswith(
                    f"{missing_module_name}."
                )
            assert spec is None


# ---------------------------------------------------------------------------
# Domain model boundary tests (15.1, 15.2)
# ---------------------------------------------------------------------------


class TestBeatmapDomainBoundarySeparation:
    """Verify beatmap domain types do not carry score/PP/leaderboard fields."""

    def test_beatmap_has_no_score_payload_fields(self) -> None:
        """Beatmap must not contain score payload-related fields (15.1)."""
        field_names = _domain_field_names(Beatmap)
        for pattern in _FORBIDDEN_DOMAIN_FIELD_PATTERNS:
            for name in field_names:
                if name in _ALLOWED_FIELD_OVERRIDES:
                    continue
                assert pattern not in name.lower(), (
                    f"Beatmap field '{name}' matches forbidden pattern '{pattern}'"
                )

    def test_beatmapset_has_no_score_payload_fields(self) -> None:
        """BeatmapSet must not contain score payload-related fields (15.1)."""
        field_names = _domain_field_names(BeatmapSet)
        for pattern in _FORBIDDEN_DOMAIN_FIELD_PATTERNS:
            for name in field_names:
                if name in _ALLOWED_FIELD_OVERRIDES:
                    continue
                assert pattern not in name.lower(), (
                    f"BeatmapSet field '{name}' matches forbidden pattern '{pattern}'"
                )

    def test_beatmap_file_attachment_has_no_score_payload_fields(self) -> None:
        """BeatmapFileAttachment must not contain score payload-related fields (15.1)."""
        field_names = _domain_field_names(BeatmapFileAttachment)
        for pattern in _FORBIDDEN_DOMAIN_FIELD_PATTERNS:
            for name in field_names:
                if name in _ALLOWED_FIELD_OVERRIDES:
                    continue
                assert pattern not in name.lower(), (
                    f"BeatmapFileAttachment field '{name}' matches forbidden pattern '{pattern}'"
                )

    def test_beatmap_file_attachment_no_body_bytes(self) -> None:
        """BeatmapFileAttachment references blob storage, does not embed file bytes."""
        attachment = BeatmapFileAttachment(
            beatmap_id=2_000,
            blob_id=42,
            checksum_md5=_CHECKSUM,
            source="osu_current",
            original_filename="2000.osu",
            fetched_at=_NOW,
            verified_at=_NOW,
        )
        assert not hasattr(attachment, "body")
        assert not hasattr(attachment, "content")
        assert not hasattr(attachment, "data")

    def test_beatmap_evaluation_has_no_pp_or_score_fields(self) -> None:
        """BeatmapEligibility is about eligibility projection, not PP calculation (15.2)."""
        field_names = _domain_field_names(BeatmapEligibility)
        # Eligibility must not expose actual PP values or score data
        for name in field_names:
            assert "pp_value" not in name.lower()
            assert "score_count" not in name.lower()
        # But should have the documented eligibility flags
        assert "accepts_scores" in field_names
        assert "has_leaderboard" in field_names

    def test_beatmap_evaluation_does_not_return_score_objects(self) -> None:
        """BeatmapEligibility.evaluate returns BeatmapEligibility, not score objects."""
        # Verify evaluate method exists and returns BeatmapEligibility
        assert hasattr(BeatmapEligibilityService, "evaluate")
        result = BeatmapEligibilityService().evaluate(
            _make_beatmap(official_status=BeatmapRankStatus.RANKED), mirror_trust_enabled=False
        )
        assert isinstance(result, BeatmapEligibility)
        # Verify result has no score-related attributes
        assert not hasattr(result, "score")
        assert not hasattr(result, "pp")


# ---------------------------------------------------------------------------
# Local override separation tests (9.1, 9.3, 15.5)
# ---------------------------------------------------------------------------


class TestLocalOverrideSeparation:
    """Verify local_status_override and official_status remain independent."""

    def test_local_override_does_not_change_official_status(self) -> None:
        """Setting local_status_override does not affect official_status (9.3, 15.5)."""
        beatmap = _make_beatmap(
            official_status=BeatmapRankStatus.GRAVEYARD,
            local_status_override=LocalBeatmapStatus.RANKED,
        )

        assert beatmap.official_status is BeatmapRankStatus.GRAVEYARD
        assert beatmap.local_status_override is LocalBeatmapStatus.RANKED
        assert beatmap.effective_status is BeatmapRankStatus.RANKED

    def test_official_status_unchanged_when_local_override_is_ranked(self) -> None:
        """Ranked local override leaves official Pending unchanged (9.3)."""
        beatmap = _make_beatmap(
            official_status=BeatmapRankStatus.PENDING,
            local_status_override=LocalBeatmapStatus.RANKED,
        )

        assert beatmap.official_status is BeatmapRankStatus.PENDING
        assert beatmap.local_status_override is LocalBeatmapStatus.RANKED
        assert beatmap.effective_status is BeatmapRankStatus.RANKED

    def test_official_status_unchanged_when_local_override_is_loved(self) -> None:
        """Loved local override leaves official Qualified unchanged (9.3)."""
        beatmap = _make_beatmap(
            official_status=BeatmapRankStatus.QUALIFIED,
            local_status_override=LocalBeatmapStatus.LOVED,
        )

        assert beatmap.official_status is BeatmapRankStatus.QUALIFIED
        assert beatmap.local_status_override is LocalBeatmapStatus.LOVED
        assert beatmap.effective_status is BeatmapRankStatus.LOVED

    def test_official_status_unchanged_when_local_override_is_graveyard(self) -> None:
        """Local override to Graveyard does not change official Ranked status (9.3)."""
        beatmap = _make_beatmap(
            official_status=BeatmapRankStatus.RANKED,
            local_status_override=LocalBeatmapStatus.GRAVEYARD,
        )

        assert beatmap.official_status is BeatmapRankStatus.RANKED
        assert beatmap.local_status_override is LocalBeatmapStatus.GRAVEYARD
        assert beatmap.effective_status is BeatmapRankStatus.GRAVEYARD

    def test_effective_status_is_readonly_property(self) -> None:
        """effective_status is a computed property, not writable."""
        beatmap = _make_beatmap(official_status=BeatmapRankStatus.APPROVED)

        # effective_status is a computed property; attempting to assign should fail
        with pytest.raises((AttributeError, TypeError)):
            beatmap.effective_status = BeatmapRankStatus.RANKED  # pyright: ignore[reportAttributeAccessIssue]

    def test_no_local_override_means_official_status_is_effective(self) -> None:
        """When local_status_override is None, effective == official (9.4)."""
        beatmap = _make_beatmap(
            official_status=BeatmapRankStatus.APPROVED,
            local_status_override=None,
        )

        assert beatmap.local_status_override is None
        assert beatmap.effective_status is beatmap.official_status
        assert beatmap.effective_status is BeatmapRankStatus.APPROVED

    def test_local_override_present_means_override_takes_effect(self) -> None:
        """When local_status_override is set, effective uses override (9.5)."""
        beatmap = _make_beatmap(
            official_status=BeatmapRankStatus.WIP,
            local_status_override=LocalBeatmapStatus.QUALIFIED,
        )

        assert beatmap.local_status_override is LocalBeatmapStatus.QUALIFIED
        assert beatmap.effective_status is BeatmapRankStatus.QUALIFIED

    def test_approved_preserved_as_official_but_not_allowed_as_local(self) -> None:
        """Approved is valid as official_status but rejected as local_status_override.

        See requirements 10.1 (official status includes Approved) and 10.3
        (local override excludes Approved).
        """
        # Official Approved is fine
        beatmap = _make_beatmap(
            official_status=BeatmapRankStatus.APPROVED,
            local_status_override=None,
        )
        assert beatmap.official_status is BeatmapRankStatus.APPROVED

        # Local override to Approved must be rejected
        with pytest.raises(ValueError, match="Approved cannot be used as a local override"):
            _ = _make_beatmap(
                local_status_override=BeatmapRankStatus.APPROVED,  # pyright: ignore[reportArgumentType]
            )

    def test_beatmap_is_immutable(self) -> None:
        """Beatmap is a frozen dataclass - fields cannot be mutated after creation."""
        beatmap = _make_beatmap(official_status=BeatmapRankStatus.GRAVEYARD)

        with pytest.raises(FrozenInstanceError):
            beatmap.official_status = BeatmapRankStatus.RANKED  # pyright: ignore[reportAttributeAccessIssue]


# ---------------------------------------------------------------------------
# Service API boundary tests (15.4)
# ---------------------------------------------------------------------------


class TestBeatmapMirrorServiceApiBoundary:
    """Verify BeatmapMirrorService public API does not imply downstream ownership."""

    def test_public_methods_are_only_resolve_operations(self) -> None:
        """Service API is resolution-only; no score or queuing methods (15.4)."""
        public_names = _public_method_names(BeatmapMirrorService)
        resolve_methods = {
            "resolve_by_beatmap_id",
            "resolve_by_beatmapset_id",
            "resolve_by_checksum",
        }
        # Service should not expose methods for score submission, PP, leaderboard
        forbidden = {
            "submit_score",
            "calculate_pp",
            "update_leaderboard",
            "enqueue_packet",
            "format_bancho_response",
            "update_rank",
            "approve_rank",
            "reject_rank",
            "process_score",
        }
        assert resolve_methods <= public_names, (
            f"Missing expected resolve methods: {resolve_methods - public_names}"
        )
        overlap = forbidden & public_names
        assert not overlap, f"Service exposes forbidden downstream methods: {overlap}"

    def test_beatmap_resolve_result_has_no_score_fields(self) -> None:
        """BeatmapResolveResult is a resolution output, not a score result."""
        field_names = _domain_field_names(BeatmapResolveResult)
        for pattern in _FORBIDDEN_DOMAIN_FIELD_PATTERNS:
            for name in field_names:
                if name in _ALLOWED_FIELD_OVERRIDES:
                    continue
                assert pattern not in name.lower(), (
                    f"BeatmapResolveResult field '{name}' matches forbidden pattern '{pattern}'"
                )

    def test_beatmap_set_resolve_result_has_no_score_fields(self) -> None:
        """BeatmapSetResolveResult is a resolution output, not a score result."""
        field_names = _domain_field_names(BeatmapSetResolveResult)
        for pattern in _FORBIDDEN_DOMAIN_FIELD_PATTERNS:
            for name in field_names:
                if name in _ALLOWED_FIELD_OVERRIDES:
                    continue
                assert pattern not in name.lower(), (
                    f"BeatmapSetResolveResult field '{name}' matches forbidden pattern '{pattern}'"
                )

    def test_resolve_options_are_resolution_only(self) -> None:
        """BeatmapResolveOptions controls resolution, not score processing."""
        field_names = _domain_field_names(BeatmapResolveOptions)
        assert "require_osu_file" in field_names
        assert "wait_timeout_seconds" in field_names
        assert "force_refresh" in field_names
        # Must not have score-related options
        for name in field_names:
            assert "score" not in name.lower()
            assert "pp" not in name.lower()
            assert "leaderboard" not in name.lower()
            assert "mods" not in name.lower()


# ---------------------------------------------------------------------------
# StatusResolver boundary tests (9.2, 10.3)
# ---------------------------------------------------------------------------


class TestStatusResolverBoundary:
    """Verify BeatmapStatusResolver preserves local/official separation."""

    def test_effective_status_derived_from_beatmap_via_property(self) -> None:
        """StatusResolver delegates to Beatmap.effective_status property."""
        resolver = BeatmapStatusResolver()
        beatmap = _make_beatmap(
            official_status=BeatmapRankStatus.PENDING,
            local_status_override=LocalBeatmapStatus.RANKED,
        )

        result = resolver.effective_status(beatmap)

        assert result is BeatmapRankStatus.RANKED
        # Official status is not mutated by the call
        assert beatmap.official_status is BeatmapRankStatus.PENDING

    def test_validate_local_override_rejects_approved(self) -> None:
        """StatusResolver rejects Approved as local override (10.3)."""
        resolver = BeatmapStatusResolver()

        with pytest.raises(ValueError, match="Approved cannot be used as a local override"):
            resolver.validate_local_override(BeatmapRankStatus.APPROVED)

    def test_validate_local_override_accepts_none(self) -> None:
        """None is a valid local override (meaning no override)."""
        resolver = BeatmapStatusResolver()
        # Should not raise
        resolver.validate_local_override(None)

    def test_validate_local_override_accepts_valid_local_statuses(self) -> None:
        """All LocalBeatmapStatus values are acceptable local overrides."""
        resolver = BeatmapStatusResolver()
        for status in LocalBeatmapStatus:
            # Should not raise
            resolver.validate_local_override(status)


# ---------------------------------------------------------------------------
# Downstream boundary integration tests (15.4, 15.5)
# ---------------------------------------------------------------------------


class TestDownstreamBoundaryIntegration:
    """Integration-level boundary verification for downstream separation.

    These tests verify that downstream features can consume beatmap-mirror
    results without the mirror owning downstream concerns.
    """

    def test_local_override_does_not_leak_into_official_status_through_service(self) -> None:
        """Downstream rank changes via local override do not mutate official (15.5)."""
        beatmap = _make_beatmap(
            official_status=BeatmapRankStatus.PENDING,
            local_status_override=LocalBeatmapStatus.RANKED,
        )

        # Simulate the downstream consuming effective_status
        resolver = BeatmapStatusResolver()
        effective = resolver.effective_status(beatmap)
        assert effective is BeatmapRankStatus.RANKED

        # Official status still reflects the official source
        assert beatmap.official_status is BeatmapRankStatus.PENDING

        # The override is explicitly a local decision
        assert beatmap.local_status_override is LocalBeatmapStatus.RANKED

    def test_beatmap_file_attachment_does_not_embed_score_osu_parsing(self) -> None:
        """BeatmapFileAttachment keeps file metadata, not parsed beatmap content.

        The .osu file body is stored in blob-storage.  BeatmapFileAttachment
        tracks provenance metadata, not parsed timing points or hit objects.
        """
        attachment = BeatmapFileAttachment(
            beatmap_id=75,
            blob_id=1,
            checksum_md5="a" * 32,
            source="osu_current",
            original_filename="75.osu",
            fetched_at=_NOW,
            verified_at=_NOW,
        )

        # Attachment must not carry parsed osu! file content
        for forbidden in ("hit_objects", "timing_points", "events", "colors", "editor"):
            assert not hasattr(attachment, forbidden), (
                f"BeatmapFileAttachment must not have parsed content field '{forbidden}'"
            )

    def test_eligibility_does_not_calculate_pp_or_update_leaderboard(self) -> None:
        """BeatmapEligibility is a projection, not a PP calculator.

        Requirement 15.2: the mirror does not calculate PP or update
        leaderboards.  BeatmapEligibilityService.evaluate() returns
        boolean projections without computing numeric PP or mutating
        leaderboard state.
        """
        service = BeatmapEligibilityService()
        beatmap = _make_beatmap(official_status=BeatmapRankStatus.RANKED)

        result = service.evaluate(beatmap, mirror_trust_enabled=False)

        # It returns an eligibility projection, not a score result
        assert isinstance(result, BeatmapEligibility)

        # PP is a boolean ("awards_ranked_pp"), not a numeric value
        assert isinstance(result.awards_ranked_pp, bool)
        assert isinstance(result.awards_loved_pp, bool)

        # The evaluation does not carry score counts or PP values
        assert not hasattr(result, "pp_value")
        assert not hasattr(result, "score_count")
        assert not hasattr(result, "leaderboard_position")
