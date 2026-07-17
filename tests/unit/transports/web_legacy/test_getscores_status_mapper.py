"""GetscoresStatusMapperとtyped status crosswalkのruntime contractを検証する."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import osu_server.transports.stable.web_legacy.mappers.getscores as getscores_mappers
from athena_cli.stable_verification.getscores_evidence import (
    EndpointEvidenceState,
    StableBeatmapStatusCrosswalkEntry,
    StatusRepresentation,
    load_getscores_completion_evidence,
)
from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSourceVerification,
    LocalBeatmapStatus,
)
from osu_server.transports.stable.web_legacy.mappers import (
    GetscoresStatusMapper,
)

_NOW = datetime(2026, 6, 7, tzinfo=UTC)
_NEXT_REFRESH = _NOW + timedelta(days=30)
_CHECKSUM = "0123456789abcdef0123456789abcdef"
_FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures"
_MANIFEST_ROOT = _FIXTURE_ROOT / "stable_compatibility" / "getscores"
_BODY_ROOT = _FIXTURE_ROOT / "web_legacy" / "getscores" / "completion"
_GETSCORES_EVIDENCE = load_getscores_completion_evidence(_MANIFEST_ROOT, _BODY_ROOT)
_STATUS_CROSSWALK = _GETSCORES_EVIDENCE.status_crosswalk
_STATUS_CROSSWALK_IDS = tuple(entry.canonical_status.value for entry in _STATUS_CROSSWALK)


def _make_beatmap(*, official_status: BeatmapRankStatus) -> Beatmap:
    return Beatmap(
        id=2_000,
        beatmapset_id=1_000,
        checksum_md5=_CHECKSUM,
        mode=BeatmapMode.OSU,
        version="Insane",
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
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        local_status_override=None,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=BeatmapFileState.MISSING,
        file_attachment=None,
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
    )


# ---------------------------------------------------------------------------
# Status wire values (requirements 4.2, 4.3)
# ---------------------------------------------------------------------------


def test_not_submitted_maps_to_none() -> None:
    """NotSubmitted returns None (no header, mapped to -1 by caller)."""
    mapper = GetscoresStatusMapper()
    beatmap = _make_beatmap(official_status=BeatmapRankStatus.NOT_SUBMITTED)
    assert mapper.map_header_status(beatmap) is None


def test_unknown_maps_to_none() -> None:
    """Unknown returns None."""
    mapper = GetscoresStatusMapper()
    beatmap = _make_beatmap(official_status=BeatmapRankStatus.UNKNOWN)
    assert mapper.map_header_status(beatmap) is None


@pytest.mark.parametrize(
    "entry",
    _STATUS_CROSSWALK,
    ids=_STATUS_CROSSWALK_IDS,
)
def test_crosswalk_entry_matches_runtime_mapper(
    entry: StableBeatmapStatusCrosswalkEntry,
) -> None:
    """Crosswalkの各canonical statusをruntime mapperへ一度ずつ照合する.

    Args:
        entry (StableBeatmapStatusCrosswalkEntry): Typed evidenceから得たstatus entry.

    Returns:
        None: Getscores representationとruntime mapperの結果が一致したことを示す.

    Raises:
        AssertionError: Crosswalkとruntime mapperのcontractが異なる場合.
    """
    beatmap = _make_beatmap(official_status=entry.canonical_status)

    actual_wire_status = GetscoresStatusMapper().map_header_status(beatmap)

    if entry.getscores.representation is StatusRepresentation.WIRE:
        assert entry.getscores.wire_status is not None
    else:
        assert entry.getscores.representation is StatusRepresentation.UNAVAILABLE
        assert entry.getscores.wire_status is None
    assert actual_wire_status == entry.getscores.wire_status


def test_crosswalk_runtime_inputs_cover_each_canonical_status_once() -> None:
    """Runtime comparisonのinputがcanonical status集合と一対一であることを検証する.

    Returns:
        None: 全BeatmapRankStatusが重複なくcrosswalkへ存在することを示す.

    Raises:
        AssertionError: Statusの欠落, 重複, 余分なentryが存在する場合.
    """
    crosswalk_statuses = tuple(entry.canonical_status for entry in _STATUS_CROSSWALK)

    assert len(crosswalk_statuses) == len(BeatmapRankStatus)
    assert len(set(crosswalk_statuses)) == len(crosswalk_statuses)
    assert set(crosswalk_statuses) == set(BeatmapRankStatus)


def test_beatmap_info_unconfirmed_statuses_have_no_numeric_guess() -> None:
    """Beatmap infoの未確認statusがnumeric valueを保持しないことを検証する.

    Returns:
        None: Ranked以外がunconfirmedかつwire statusなしであることを示す.

    Raises:
        AssertionError: 未確認statusへnumeric valueまたは確定stateが設定された場合.
    """
    entries_by_status = {entry.canonical_status: entry for entry in _STATUS_CROSSWALK}
    ranked_evidence = entries_by_status[BeatmapRankStatus.RANKED].beatmap_info
    unconfirmed_statuses = set(BeatmapRankStatus) - {BeatmapRankStatus.RANKED}

    assert ranked_evidence.representation is StatusRepresentation.WIRE
    assert ranked_evidence.wire_status == 1
    assert ranked_evidence.evidence_status is EndpointEvidenceState.OFFICIAL_FIXTURE
    for status in unconfirmed_statuses:
        evidence = entries_by_status[status].beatmap_info
        assert evidence.representation is StatusRepresentation.UNCONFIRMED
        assert evidence.wire_status is None
        assert evidence.evidence_status is EndpointEvidenceState.UNCONFIRMED


def _assert_status_mapper_ownership(source: str) -> None:
    """Mapper sourceのmodule-local status lookup構造を検証する.

    Args:
        source (str): Getscores mapper moduleのPython source.

    Returns:
        None: Module-local mappingとdirect lookupが存在することを示す.

    Raises:
        SyntaxError: SourceをPython ASTへparseできない場合.
        AssertionError: Mappingがmodule-localでない場合, またはmethodがshared
            mapperへdelegateする場合.

    Notes:
        `_STATUS_TO_WIRE`のdict literalとmethodからのdirect `.get(...)`だけを許可し,
        別runtime moduleが所有するnumeric mapperへの委譲を拒否する.
    """
    syntax_tree = ast.parse(source)
    status_mapping_value: ast.expr | None = None
    mapper_class: ast.ClassDef | None = None
    for statement in syntax_tree.body:
        if isinstance(statement, (ast.AnnAssign, ast.Assign)):
            if isinstance(statement, ast.AnnAssign):
                is_status_mapping = (
                    isinstance(statement.target, ast.Name)
                    and statement.target.id == "_STATUS_TO_WIRE"
                )
            else:
                is_status_mapping = any(
                    isinstance(target, ast.Name) and target.id == "_STATUS_TO_WIRE"
                    for target in statement.targets
                )
            if is_status_mapping:
                status_mapping_value = statement.value
        elif isinstance(statement, ast.ClassDef) and statement.name == "GetscoresStatusMapper":
            mapper_class = statement

    assert isinstance(status_mapping_value, ast.Dict)
    assert mapper_class is not None
    mapper_method = next(
        (
            statement
            for statement in mapper_class.body
            if isinstance(statement, ast.FunctionDef) and statement.name == "map_header_status"
        ),
        None,
    )
    assert mapper_method is not None
    method_body = (
        mapper_method.body[1:]
        if ast.get_docstring(mapper_method, clean=False) is not None
        else mapper_method.body
    )
    assert len(method_body) == 1
    return_statement = method_body[0]
    assert isinstance(return_statement, ast.Return)
    return_value = return_statement.value
    assert isinstance(return_value, ast.Call)
    assert isinstance(return_value.func, ast.Attribute)
    assert return_value.func.attr == "get"
    assert isinstance(return_value.func.value, ast.Name)
    assert return_value.func.value.id == "_STATUS_TO_WIRE"
    assert len(return_value.args) == 1
    assert not return_value.keywords
    status_argument = return_value.args[0]
    assert isinstance(status_argument, ast.Attribute)
    assert status_argument.attr == "effective_status"
    assert isinstance(status_argument.value, ast.Name)
    assert status_argument.value.id == "beatmap"


def test_status_mapper_ownership_remains_endpoint_local() -> None:
    """Runtime mapperがmodule-local mappingをdirect lookupすることを検証する.

    Returns:
        None: Mapper所有pathとlookup構造がendpoint-localであることを示す.

    Raises:
        AssertionError: Mapperがshared numeric mapperへdelegateする場合.
    """
    assert GetscoresStatusMapper.__module__ == getscores_mappers.__name__
    source_file = getscores_mappers.__file__
    assert source_file is not None

    _assert_status_mapper_ownership(Path(source_file).read_text(encoding="utf-8"))


def test_pending_maps_to_0() -> None:
    mapper = GetscoresStatusMapper()
    beatmap = _make_beatmap(official_status=BeatmapRankStatus.PENDING)
    assert mapper.map_header_status(beatmap) == 0


def test_wip_maps_to_0() -> None:
    mapper = GetscoresStatusMapper()
    beatmap = _make_beatmap(official_status=BeatmapRankStatus.WIP)
    assert mapper.map_header_status(beatmap) == 0


def test_graveyard_maps_to_0() -> None:
    mapper = GetscoresStatusMapper()
    beatmap = _make_beatmap(official_status=BeatmapRankStatus.GRAVEYARD)
    assert mapper.map_header_status(beatmap) == 0


def test_ranked_maps_to_2() -> None:
    mapper = GetscoresStatusMapper()
    beatmap = _make_beatmap(official_status=BeatmapRankStatus.RANKED)
    assert mapper.map_header_status(beatmap) == 2


def test_approved_maps_to_3() -> None:
    mapper = GetscoresStatusMapper()
    beatmap = _make_beatmap(official_status=BeatmapRankStatus.APPROVED)
    assert mapper.map_header_status(beatmap) == 3


def test_qualified_maps_to_4() -> None:
    mapper = GetscoresStatusMapper()
    beatmap = _make_beatmap(official_status=BeatmapRankStatus.QUALIFIED)
    assert mapper.map_header_status(beatmap) == 4


def test_loved_maps_to_5() -> None:
    mapper = GetscoresStatusMapper()
    beatmap = _make_beatmap(official_status=BeatmapRankStatus.LOVED)
    assert mapper.map_header_status(beatmap) == 5


def test_all_mapped_statuses_are_unique() -> None:
    """Each visible status maps to a distinct wire value (requirement 9.8)."""
    mapper = GetscoresStatusMapper()
    visible_statuses = [
        BeatmapRankStatus.PENDING,
        BeatmapRankStatus.WIP,
        BeatmapRankStatus.GRAVEYARD,
        BeatmapRankStatus.RANKED,
        BeatmapRankStatus.APPROVED,
        BeatmapRankStatus.QUALIFIED,
        BeatmapRankStatus.LOVED,
    ]
    values = [mapper.map_header_status(_make_beatmap(official_status=s)) for s in visible_statuses]
    # Pending/WIP/Graveyard all map to 0 (same value is intentional)
    # Ranked=2, Approved=3, Qualified=4, Loved=5 are all distinct
    distinct_above_zero = [v for v in values if v is not None and v > 0]
    assert len(distinct_above_zero) == len(set(distinct_above_zero))


# ---------------------------------------------------------------------------
# Local status override (effective_status)
# ---------------------------------------------------------------------------


def test_local_override_takes_precedence() -> None:
    """local_status_override changes effective_status which maps to wire value."""
    mapper = GetscoresStatusMapper()
    beatmap = _make_beatmap(
        official_status=BeatmapRankStatus.PENDING,
    )
    # Use object.__setattr__ to bypass frozen dataclass
    object.__setattr__(beatmap, "local_status_override", LocalBeatmapStatus.RANKED)

    assert beatmap.effective_status == BeatmapRankStatus.RANKED
    assert mapper.map_header_status(beatmap) == 2


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_mapper_has_expected_interface() -> None:
    mapper = GetscoresStatusMapper()
    assert hasattr(mapper, "map_header_status")
    assert callable(mapper.map_header_status)
