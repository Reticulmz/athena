"""Beatmap mirrorの下流境界分離契約を検証する.

score submission. leaderboard. WebUI. Bancho transportからの独立性と.
official status/local overrideの分離を対象にする.
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
    BeatmapFileSource,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
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
    """境界検証に必要な属性を持つbeatmapを生成する.

    Args:
        official_status (BeatmapRankStatus): 外部sourceが示す公式状態.
        local_status_override (LocalBeatmapStatus | None): localで上書きする状態.
        source (BeatmapMetadataSource): metadataを提供したsource.
        source_verification (BeatmapSourceVerification): source metadataの検証状態.
        file_attachment (BeatmapFileAttachment | None): 関連付けるfile metadata.

    Returns:
        Beatmap: freshnessとfile状態を固定した検証用beatmap.
    """
    return Beatmap(
        id=2_000,
        beatmapset_id=1_000,
        checksum_md5=_CHECKSUM,
        mode=BeatmapMode.OSU,
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
    """Module namespace内の禁止package由来objectを収集する.

    Args:
        module_name (str): 検査対象のimport可能なmodule名.
        forbidden_prefixes (tuple[str. ...]): 参照を禁止するpackage prefix群.

    Returns:
        list[str]: 禁止prefixからimportしたobjectを示す違反一覧.
    """
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
    """dataclassに宣言されたfield名を収集する.

    Args:
        cls (type): fieldを検査するdataclass型.

    Returns:
        frozenset[str]: dataclassが直接宣言するfield名の集合.
    """
    return frozenset(f.name for f in fields(cls))


def _public_method_names(cls: type) -> frozenset[str]:
    """型が公開するcallable名を収集する.

    Args:
        cls (type): public APIを検査する型.

    Returns:
        frozenset[str]: underscoreで始まらないcallable属性名の集合.
    """
    return frozenset(
        name
        for name in dir(cls)
        if not name.startswith("_") and callable(getattr(cls, name, None))
    )


# ---------------------------------------------------------------------------
# Import boundary tests (15.1, 15.2, 15.3)
# ---------------------------------------------------------------------------


class TestBeatmapMirrorImportBoundaries:
    """Beatmap mirror moduleが下流packageをimportしない境界を検証する."""

    def test_domain_module_no_transport_imports(self) -> None:
        """Domain moduleがtransport packageをimportしないことを検証する.

        Returns:
            None: forbidden transport importがないことを検証して完了する.
        """
        violations = _module_imports_forbidden(
            "osu_server.domain.beatmaps", _FORBIDDEN_IMPORT_PREFIXES
        )
        assert violations == [], f"domain.beatmaps has forbidden imports: {violations}"

    def test_service_module_no_transport_imports(self) -> None:
        """Service moduleがtransport packageをimportしないことを検証する.

        Returns:
            None: service領域のforbidden importがないことを検証して完了する.
        """
        for module_name in _BEATMAP_MODULES:
            if not module_name.startswith("osu_server.services"):
                continue
            violations = _module_imports_forbidden(module_name, _FORBIDDEN_IMPORT_PREFIXES)
            assert violations == [], f"{module_name} has forbidden imports: {violations}"

    def test_infrastructure_module_no_transport_imports(self) -> None:
        """Infrastructure moduleがtransport packageをimportしないことを検証する.

        Returns:
            None: infrastructure領域のforbidden importがないことを検証して完了する.
        """
        for module_name in _BEATMAP_MODULES:
            if not module_name.startswith("osu_server.infrastructure"):
                continue
            violations = _module_imports_forbidden(module_name, _FORBIDDEN_IMPORT_PREFIXES)
            assert violations == [], f"{module_name} has forbidden imports: {violations}"

    def test_repository_module_no_transport_imports(self) -> None:
        """Repository moduleがtransport packageをimportしないことを検証する.

        Returns:
            None: repository領域のforbidden importがないことを検証して完了する.
        """
        for module_name in _BEATMAP_MODULES:
            if not module_name.startswith("osu_server.repositories"):
                continue
            violations = _module_imports_forbidden(module_name, _FORBIDDEN_IMPORT_PREFIXES)
            assert violations == [], f"{module_name} has forbidden imports: {violations}"

    def test_job_module_no_transport_imports(self) -> None:
        """Beatmap fetch jobがtransport packageをimportしないことを検証する.

        Returns:
            None: job moduleのforbidden importがないことを検証して完了する.
        """
        violations = _module_imports_forbidden(
            "osu_server.jobs.beatmap_fetch", _FORBIDDEN_IMPORT_PREFIXES
        )
        assert violations == [], f"jobs.beatmap_fetch has forbidden imports: {violations}"

    def test_all_beatmap_modules_importable(self) -> None:
        """全Beatmap mirror moduleが例外なくimport可能なことを検証する.

        Returns:
            None: feature boundary内のmodule importを検証して完了する.
        """
        for module_name in _BEATMAP_MODULES:
            try:
                __import__(module_name)
            except Exception as exc:
                pytest.fail(f"Failed to import {module_name}: {exc}")

    def test_removed_provider_modules_not_importable(self) -> None:
        """削除済みprovider module pathを互換facadeとして復活させないことを検証する.

        Returns:
            None: removed pathにmodule specがないことを検証して完了する.
        """
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
    """Beatmap domain型がscore/PP/leaderboard fieldを持たないことを検証する."""

    def test_beatmap_has_no_score_payload_fields(self) -> None:
        """Beatmapがscore payload fieldを持たないことを検証する.

        Returns:
            None: 許可済みfield以外に下流concernがないことを検証して完了する.
        """
        field_names = _domain_field_names(Beatmap)
        for pattern in _FORBIDDEN_DOMAIN_FIELD_PATTERNS:
            for name in field_names:
                if name in _ALLOWED_FIELD_OVERRIDES:
                    continue
                assert pattern not in name.lower(), (
                    f"Beatmap field '{name}' matches forbidden pattern '{pattern}'"
                )

    def test_beatmapset_has_no_score_payload_fields(self) -> None:
        """BeatmapSetがscore payload fieldを持たないことを検証する.

        Returns:
            None: 許可済みfield以外に下流concernがないことを検証して完了する.
        """
        field_names = _domain_field_names(BeatmapSet)
        for pattern in _FORBIDDEN_DOMAIN_FIELD_PATTERNS:
            for name in field_names:
                if name in _ALLOWED_FIELD_OVERRIDES:
                    continue
                assert pattern not in name.lower(), (
                    f"BeatmapSet field '{name}' matches forbidden pattern '{pattern}'"
                )

    def test_beatmap_file_attachment_has_no_score_payload_fields(self) -> None:
        """BeatmapFileAttachmentがscore payload fieldを持たないことを検証する.

        Returns:
            None: attachmentに下流concernがないことを検証して完了する.
        """
        field_names = _domain_field_names(BeatmapFileAttachment)
        for pattern in _FORBIDDEN_DOMAIN_FIELD_PATTERNS:
            for name in field_names:
                if name in _ALLOWED_FIELD_OVERRIDES:
                    continue
                assert pattern not in name.lower(), (
                    f"BeatmapFileAttachment field '{name}' matches forbidden pattern '{pattern}'"
                )

    def test_beatmap_file_attachment_no_body_bytes(self) -> None:
        """BeatmapFileAttachmentがfile bodyではなくblob metadataを参照することを検証する.

        Returns:
            None: body. content. data属性を持たないことを検証して完了する.
        """
        attachment = BeatmapFileAttachment(
            beatmap_id=2_000,
            blob_id=42,
            checksum_md5=_CHECKSUM,
            source=BeatmapFileSource.OSU_CURRENT,
            original_filename="2000.osu",
            fetched_at=_NOW,
            verified_at=_NOW,
        )
        assert not hasattr(attachment, "body")
        assert not hasattr(attachment, "content")
        assert not hasattr(attachment, "data")

    def test_beatmap_evaluation_has_no_pp_or_score_fields(self) -> None:
        """BeatmapEligibilityがPP計算値やscore fieldを持たないことを検証する.

        Returns:
            None: eligibility flagだけを公開することを検証して完了する.
        """
        field_names = _domain_field_names(BeatmapEligibility)
        # Eligibility must not expose actual PP values or score data
        for name in field_names:
            assert "pp_value" not in name.lower()
            assert "score_count" not in name.lower()
        # But should have the documented eligibility flags
        assert "accepts_scores" in field_names
        assert "has_leaderboard" in field_names

    def test_beatmap_evaluation_does_not_return_score_objects(self) -> None:
        """Eligibility serviceがscore objectではなくprojectionを返すことを検証する.

        Returns:
            None: BeatmapEligibility型とscore属性の不在を検証して完了する.
        """
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
    """local status overrideとofficial statusの独立性を検証する."""

    def test_local_override_does_not_change_official_status(self) -> None:
        """Local overrideがofficial statusを変更しないことを検証する.

        Returns:
            None: effective statusだけがlocal overrideになることを検証して完了する.
        """
        beatmap = _make_beatmap(
            official_status=BeatmapRankStatus.GRAVEYARD,
            local_status_override=LocalBeatmapStatus.RANKED,
        )

        assert beatmap.official_status is BeatmapRankStatus.GRAVEYARD
        assert beatmap.local_status_override is LocalBeatmapStatus.RANKED
        assert beatmap.effective_status is BeatmapRankStatus.RANKED

    def test_official_status_unchanged_when_local_override_is_ranked(self) -> None:
        """RANKED local overrideがPENDING official statusを変更しないことを検証する.

        Returns:
            None: officialとeffective statusの分離を検証して完了する.
        """
        beatmap = _make_beatmap(
            official_status=BeatmapRankStatus.PENDING,
            local_status_override=LocalBeatmapStatus.RANKED,
        )

        assert beatmap.official_status is BeatmapRankStatus.PENDING
        assert beatmap.local_status_override is LocalBeatmapStatus.RANKED
        assert beatmap.effective_status is BeatmapRankStatus.RANKED

    def test_official_status_unchanged_when_local_override_is_loved(self) -> None:
        """LOVED local overrideがQUALIFIED official statusを変更しないことを検証する.

        Returns:
            None: officialとeffective statusの分離を検証して完了する.
        """
        beatmap = _make_beatmap(
            official_status=BeatmapRankStatus.QUALIFIED,
            local_status_override=LocalBeatmapStatus.LOVED,
        )

        assert beatmap.official_status is BeatmapRankStatus.QUALIFIED
        assert beatmap.local_status_override is LocalBeatmapStatus.LOVED
        assert beatmap.effective_status is BeatmapRankStatus.LOVED

    def test_official_status_unchanged_when_local_override_is_graveyard(self) -> None:
        """GRAVEYARD local overrideがRANKED official statusを変更しないことを検証する.

        Returns:
            None: officialとeffective statusの分離を検証して完了する.
        """
        beatmap = _make_beatmap(
            official_status=BeatmapRankStatus.RANKED,
            local_status_override=LocalBeatmapStatus.GRAVEYARD,
        )

        assert beatmap.official_status is BeatmapRankStatus.RANKED
        assert beatmap.local_status_override is LocalBeatmapStatus.GRAVEYARD
        assert beatmap.effective_status is BeatmapRankStatus.GRAVEYARD

    def test_effective_status_is_readonly_property(self) -> None:
        """Effective statusが書き込み不可のcomputed propertyであることを検証する.

        Returns:
            None: assignmentがAttributeErrorまたはTypeErrorになることを検証して完了する.
        """
        beatmap = _make_beatmap(official_status=BeatmapRankStatus.APPROVED)

        # effective_status is a computed property; attempting to assign should fail
        with pytest.raises((AttributeError, TypeError)):
            beatmap.effective_status = BeatmapRankStatus.RANKED  # pyright: ignore[reportAttributeAccessIssue]

    def test_no_local_override_means_official_status_is_effective(self) -> None:
        """Local overrideがNoneならofficial statusがeffectiveになることを検証する.

        Returns:
            None: APPROVEDの公式状態をそのまま返すことを検証して完了する.
        """
        beatmap = _make_beatmap(
            official_status=BeatmapRankStatus.APPROVED,
            local_status_override=None,
        )

        assert beatmap.local_status_override is None
        assert beatmap.effective_status is beatmap.official_status
        assert beatmap.effective_status is BeatmapRankStatus.APPROVED

    def test_local_override_present_means_override_takes_effect(self) -> None:
        """Local overrideが設定済みならeffective statusに採用することを検証する.

        Returns:
            None: QUALIFIED overrideを返すことを検証して完了する.
        """
        beatmap = _make_beatmap(
            official_status=BeatmapRankStatus.WIP,
            local_status_override=LocalBeatmapStatus.QUALIFIED,
        )

        assert beatmap.local_status_override is LocalBeatmapStatus.QUALIFIED
        assert beatmap.effective_status is BeatmapRankStatus.QUALIFIED

    def test_approved_preserved_as_official_but_not_allowed_as_local(self) -> None:
        """APPROVEDをofficial statusとして許可しlocal overrideとして拒否することを検証する.

        Requirements 10.1ではAPPROVEDが公式状態に含まれる. Requirements 10.3では
        local overrideからAPPROVEDを除外する.

        Returns:
            None: official statusの保持と不正overrideのValueErrorを検証して完了する.
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
        """Beatmapが生成後にfieldを変更できないfrozen dataclassであることを検証する.

        Returns:
            None: official statusのassignmentがFrozenInstanceErrorになることを検証して完了する.
        """
        beatmap = _make_beatmap(official_status=BeatmapRankStatus.GRAVEYARD)

        with pytest.raises(FrozenInstanceError):
            beatmap.official_status = BeatmapRankStatus.RANKED  # pyright: ignore[reportAttributeAccessIssue]


# ---------------------------------------------------------------------------
# Service API boundary tests (15.4)
# ---------------------------------------------------------------------------


class TestBeatmapMirrorServiceApiBoundary:
    """BeatmapMirrorServiceの公開APIが下流責務を持たないことを検証する."""

    def test_public_methods_are_only_resolve_operations(self) -> None:
        """Service公開APIが解決操作だけを提供する境界契約を検証する.

        BeatmapMirrorServiceのpublic callable名を収集し,4種のresolve操作だけを公開して,
        score処理やqueue操作を公開しないことを確認する.

        Returns:
            None: resolution-onlyのpublic API集合を検証して完了する.
        """
        public_names = _public_method_names(BeatmapMirrorService)
        resolve_methods = {
            "resolve_by_beatmap_id",
            "resolve_by_beatmapset_id",
            "resolve_by_checksum",
            "resolve_known_beatmap",
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
        """BeatmapResolveResultがscore resultではなく解決出力であることを検証する.

        result dataclassのfieldを走査し,許可済みbeatmap属性以外にscore,PP,leaderboard由来の
        field名がないことを確認する.

        Returns:
            None: score payloadを含まない解決結果のfield集合を検証して完了する.
        """
        field_names = _domain_field_names(BeatmapResolveResult)
        for pattern in _FORBIDDEN_DOMAIN_FIELD_PATTERNS:
            for name in field_names:
                if name in _ALLOWED_FIELD_OVERRIDES:
                    continue
                assert pattern not in name.lower(), (
                    f"BeatmapResolveResult field '{name}' matches forbidden pattern '{pattern}'"
                )

    def test_beatmap_set_resolve_result_has_no_score_fields(self) -> None:
        """BeatmapSetResolveResultがscore resultではなくset解決出力であることを検証する.

        result dataclassのfieldを走査し,許可済みbeatmap属性以外にscore,PP,leaderboard由来の
        field名がないことを確認する.

        Returns:
            None: score payloadを含まないset解決結果のfield集合を検証して完了する.
        """
        field_names = _domain_field_names(BeatmapSetResolveResult)
        for pattern in _FORBIDDEN_DOMAIN_FIELD_PATTERNS:
            for name in field_names:
                if name in _ALLOWED_FIELD_OVERRIDES:
                    continue
                assert pattern not in name.lower(), (
                    f"BeatmapSetResolveResult field '{name}' matches forbidden pattern '{pattern}'"
                )

    def test_resolve_options_are_resolution_only(self) -> None:
        """BeatmapResolveOptionsがscore処理ではなく解決条件だけを持つことを検証する.

        file要件,wait上限,強制refreshを持つことと,score,PP,leaderboard,mods用の
        optionを持たないことを確認する.

        Returns:
            None: resolution-onlyのoption field集合を検証して完了する.
        """
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
    """BeatmapStatusResolverがlocal/official statusの分離を保つことを検証する."""

    def test_effective_status_derived_from_beatmap_via_property(self) -> None:
        """StatusResolverがBeatmap.effective_statusをそのまま採用する契約を検証する.

        PENDINGの公式状態とRANKEDのlocal overrideを持つbeatmapを解決し,RANKEDを返しつつ
        official_statusをPENDINGのまま保持することを確認する.

        Returns:
            None: resolverがeffective statusの読み取りでsource状態を変更しないことを
                検証して完了する.
        """
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
        """StatusResolverがAPPROVEDをlocal overrideとして拒否する契約を検証する.

        official status専用のAPPROVEDをvalidate_local_overrideへ渡し,ValueErrorになることを
        確認する.

        Returns:
            None: APPROVEDをlocal overrideに使えない入力制約を検証して完了する.
        """
        resolver = BeatmapStatusResolver()

        with pytest.raises(ValueError, match="Approved cannot be used as a local override"):
            resolver.validate_local_override(BeatmapRankStatus.APPROVED)

    def test_validate_local_override_accepts_none(self) -> None:
        """StatusResolverがoverride未設定を表すNoneを許可する契約を検証する.

        validate_local_overrideへNoneを渡し,例外なく完了することを確認する.

        Returns:
            None: overrideなしの有効な入力を検証して完了する.
        """
        resolver = BeatmapStatusResolver()
        # Should not raise
        resolver.validate_local_override(None)

    def test_validate_local_override_accepts_valid_local_statuses(self) -> None:
        """StatusResolverが全LocalBeatmapStatus値をlocal overrideとして許可する契約を検証する.

        LocalBeatmapStatusの全memberを検証し,いずれも例外なく受け付けることを確認する.

        Returns:
            None: 許可されたlocal override集合を検証して完了する.
        """
        resolver = BeatmapStatusResolver()
        for status in LocalBeatmapStatus:
            # Should not raise
            resolver.validate_local_override(status)


# ---------------------------------------------------------------------------
# Downstream boundary integration tests (15.4, 15.5)
# ---------------------------------------------------------------------------


class TestDownstreamBoundaryIntegration:
    """下流機能がbeatmap mirrorの下流責務を取り込まないことを統合的に検証する.

    local override,file attachment,eligibility projectionを通じて,downstream consumerが
    mirrorの解決結果を使ってもscore,PP,leaderboardの所有権を持ち込まないことを対象にする.
    """

    def test_local_override_does_not_leak_into_official_status_through_service(self) -> None:
        """下流のlocal override利用が公式状態を変更しない統合契約を検証する.

        PENDINGの公式状態とRANKEDのlocal overrideを持つbeatmapをresolverに渡し,effective statusは
        RANKEDでもofficial_statusはPENDING,overrideは明示的なlocal判断のままであることを確認する.

        Returns:
            None: service経由でもofficial/local statusが分離されることを検証して完了する.
        """
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
        """BeatmapFileAttachmentが解析済みosu contentではなくfile metadataを保持する契約を検証する.

        attachmentを生成し,osu file bodyがblob storageに置かれ,timing pointやhit objectなどの
        解析済みcontent fieldをattachmentへ埋め込まないことを確認する.

        Returns:
            None: file provenanceだけを持つattachmentの境界を検証して完了する.
        """
        attachment = BeatmapFileAttachment(
            beatmap_id=75,
            blob_id=1,
            checksum_md5="a" * 32,
            source=BeatmapFileSource.OSU_CURRENT,
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
        """BeatmapEligibilityがPP計算器やleaderboard更新器ではない契約を検証する.

        RANKED beatmapをevaluateし,数値PPやscore countではなくboolean eligibility projectionを
        返し,leaderboard positionのような下流状態を持たないことを確認する.

        Returns:
            None: PP計算やleaderboard更新を含まないeligibility projectionを検証して完了する.
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
