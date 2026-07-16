from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from tests.support.getscores_contract import (
    build_getscores_contract_query,
    read_getscores_expected_body,
)

from athena_cli.stable_verification.getscores_evidence import (
    GetscoresCompletionEvidence,
    GetscoresIdentityProfile,
    GetscoresMutationProfile,
    GetscoresRequestSelector,
    GetscoresSeedProfile,
    GetscoresWireShapeFixture,
    GetscoresWireShapeId,
    load_getscores_completion_evidence,
)
from osu_server.domain.scores.mods import Mod

_FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures"
_MANIFEST_ROOT = _FIXTURE_ROOT / "stable_compatibility" / "getscores"
_BODY_ROOT = _FIXTURE_ROOT / "web_legacy" / "getscores" / "completion"
_BASE_CHECKSUM = "1" * 32
_BASE_PASSWORD_MD5 = "b" * 32
_CANONICAL_CASE_IDS = frozenset(
    {
        "global-with-rows",
        "local-maps-global",
        "selected-mods-supported",
        "selected-mods-unsupported",
        "friends-outbound-only",
        "country-match",
        "country-missing",
        "country-xx",
        "song-select-header-only",
        "unsupported-leaderboard-header-only",
        "unsupported-playstyle-header-only",
        "unavailable-beatmap",
        "update-candidate",
        "missing-beatmap-identity",
        "invalid-checksum",
        "malformed-mode",
        "malformed-mods",
        "malformed-leaderboard-type",
        "malformed-leaderboard-version",
        "malformed-song-select-flag",
        "malformed-anti-cheat-signal",
        "malformed-beatmapset-hint",
        "malformed-multiple-optional-fields",
        "auth-missing",
        "auth-invalid",
        "global-no-scores",
        "valid-anti-cheat-signal-invariant",
        "request-version-variant-invariant",
    }
)


def test_global_domain_and_local_build_the_stable_local_runtime_selector(
    tmp_path: Path,
) -> None:
    """Global domainとStable Localがv=1へ決定的に変換されることを確認する。

    Args:
        tmp_path (Path): Typed evidence用の一時manifest directoryを作るroot。

    Returns:
        None: 両profileが同じruntime selectorを持つ新規queryを返す。

    Raises:
        AssertionError: Selector変換またはbase queryのcopy境界が異なる場合。
    """
    evidence = _load_branch_evidence(tmp_path)
    cases = {
        case.request_selector: case
        for case in evidence.branch_cases
        if case.case_id in {"global-with-rows", "local-maps-global"}
    }
    base_query = _base_query()
    original = dict(base_query)

    global_query = build_getscores_contract_query(
        cases[GetscoresRequestSelector.GLOBAL_DOMAIN],
        base_query,
    )
    local_query = build_getscores_contract_query(
        cases[GetscoresRequestSelector.LOCAL],
        base_query,
    )

    assert global_query == local_query
    assert global_query is not base_query
    assert global_query["v"] == "1"
    assert global_query["s"] == "0"
    assert global_query["mods"] == "0"
    assert base_query == original


@pytest.mark.parametrize(
    ("case_id", "expected_fields"),
    [
        ("selected-mods-supported", {"v": "2", "mods": str(int(Mod.MIRROR))}),
        ("selected-mods-unsupported", {"v": "2", "mods": str(1 << 31)}),
        ("friends-outbound-only", {"v": "3"}),
        ("country-match", {"v": "4"}),
        ("song-select-header-only", {"v": "1", "s": "1"}),
        ("unsupported-leaderboard-header-only", {"v": "99"}),
        ("unsupported-playstyle-header-only", {"v": "1", "mods": str(int(Mod.RELAX))}),
    ],
)
def test_request_selector_profiles_build_verified_stable_fields(
    tmp_path: Path,
    case_id: str,
    expected_fields: dict[str, str],
) -> None:
    """Closed selector profileをselection-changing stable fieldへ変換する。

    Args:
        tmp_path (Path): Typed evidence用の一時manifest directoryを作るroot。
        case_id (str): Canonical branch case ID。
        expected_fields (dict[str, str]): Selectorが生成するfield subset。

    Returns:
        None: Runtime selector fieldが期待値と一致する。

    Raises:
        AssertionError: Selectorが別categoryへfallbackした場合。
    """
    evidence = _load_branch_evidence(tmp_path)
    case = next(case for case in evidence.branch_cases if case.case_id == case_id)

    query = build_getscores_contract_query(case, _base_query())

    assert {field: query[field] for field in expected_fields} == expected_fields


@pytest.mark.parametrize(
    ("case_id", "expected_fields", "absent_fields"),
    [
        (
            "auth-missing",
            {"c": _BASE_CHECKSUM},
            ("us", "ha"),
        ),
        (
            "auth-invalid",
            {"us": "SyntheticViewer", "ha": "0" * 32},
            (),
        ),
        (
            "global-with-rows",
            {"c": _BASE_CHECKSUM},
            (),
        ),
        ("missing-beatmap-identity", {}, ("c", "f", "i")),
        (
            "invalid-checksum",
            {"c": "not-a-valid-md5"},
            ("f", "i"),
        ),
        (
            "unavailable-beatmap",
            {"c": "f" * 32},
            ("f", "i"),
        ),
        (
            "update-candidate",
            {
                "c": "a" * 32,
                "f": "Camellia - Exit (Realazy) [Insane].osu",
                "i": "1",
            },
            (),
        ),
    ],
)
def test_identity_profiles_build_synthetic_auth_and_beatmap_shapes(
    tmp_path: Path,
    case_id: str,
    expected_fields: dict[str, str],
    absent_fields: tuple[str, ...],
) -> None:
    """Closed identity profileをsynthetic auth/beatmap queryへ変換する。

    Args:
        tmp_path (Path): Typed evidence用の一時manifest directoryを作るroot。
        case_id (str): Canonical branch case ID。
        expected_fields (dict[str, str]): Identity profileが生成するfield subset。
        absent_fields (tuple[str, ...]): Queryから除去されるfield名。

    Returns:
        None: Identity query shapeが期待値と一致する。

    Raises:
        AssertionError: Identity不足、invalid auth、update fallbackの形が異なる場合。
    """
    evidence = _load_branch_evidence(tmp_path)
    case = next(case for case in evidence.branch_cases if case.case_id == case_id)

    query = build_getscores_contract_query(case, _base_query())

    assert {field: query[field] for field in expected_fields} == expected_fields
    assert all(field not in query for field in absent_fields)


@pytest.mark.parametrize(
    "caller_identity",
    [
        {
            "c": "2" * 32,
            "f": "Synthetic Caller Map One.osu",
            "i": "101",
            "us": "CallerViewerOne",
            "ha": "3" * 32,
        },
        {
            "c": "4" * 32,
            "f": "Synthetic Caller Map Two.osu",
            "i": "202",
            "us": "CallerViewerTwo",
            "ha": "5" * 32,
        },
    ],
)
def test_known_beatmap_preserves_each_caller_owned_identity_field(
    tmp_path: Path,
    caller_identity: dict[str, str],
) -> None:
    """Known beatmap profileがcaller-owned identityを一切上書きしないことを確認する。

    Args:
        tmp_path (Path): Typed evidence用の一時manifest directoryを作るroot。
        caller_identity (dict[str, str]): Callerが所有する`c/f/i/us/ha`値。

    Returns:
        None: 5つのidentity fieldがexactに保持される。

    Raises:
        AssertionError: Validation後に固定値へ上書きされたfieldがある場合。
    """
    evidence = _load_branch_evidence(tmp_path)
    case = next(case for case in evidence.branch_cases if case.case_id == "global-with-rows")
    base_query = _base_query()
    base_query.update(caller_identity)

    query = build_getscores_contract_query(case, base_query)

    assert {field: query[field] for field in caller_identity} == caller_identity


def test_auth_invalid_hash_always_differs_from_caller_value(tmp_path: Path) -> None:
    """Auth invalid profileがcallerのhashと異なるsynthetic値を必ず生成する。

    Args:
        tmp_path (Path): Typed evidence用の一時manifest directoryを作るroot。

    Returns:
        None: Base hashがpreferred invalid値でも別値が選択される。

    Raises:
        AssertionError: Invalid hashがcaller値と同一になった場合。
    """
    evidence = _load_branch_evidence(tmp_path)
    case = next(case for case in evidence.branch_cases if case.case_id == "auth-invalid")
    base_query = _base_query()
    base_query["ha"] = "0" * 32

    query = build_getscores_contract_query(case, base_query)

    assert query["ha"] != base_query["ha"]


@pytest.mark.parametrize(
    ("case_id", "expected_fields"),
    [
        ("malformed-mode", {"m": "invalid-mode"}),
        ("malformed-mods", {"mods": "invalid-mods"}),
        ("malformed-leaderboard-type", {"v": "invalid-leaderboard-type"}),
        (
            "malformed-leaderboard-version",
            {"vv": "invalid-leaderboard-version"},
        ),
        ("malformed-song-select-flag", {"s": "invalid-song-select-flag"}),
        (
            "malformed-anti-cheat-signal",
            {"a": "invalid-anti-cheat-signal"},
        ),
        (
            "malformed-beatmapset-hint",
            {"i": "invalid-beatmapset-id-hint"},
        ),
        ("valid-anti-cheat-signal-invariant", {"a": "1"}),
        ("request-version-variant-invariant", {"vv": "5"}),
    ],
)
def test_mutation_profiles_apply_after_identity_and_selector(
    tmp_path: Path,
    case_id: str,
    expected_fields: dict[str, str],
) -> None:
    """Diagnostic/request-version mutationを最後に決定的に適用する。

    Args:
        tmp_path (Path): Typed evidence用の一時manifest directoryを作るroot。
        case_id (str): Canonical branch case ID。
        expected_fields (dict[str, str]): Mutationが最終的に生成するfield subset。

    Returns:
        None: Mutation値がidentity/selector適用後のqueryへ残る。

    Raises:
        AssertionError: Mutationがselector値で上書きされた場合。
    """
    evidence = _load_branch_evidence(tmp_path)
    case = next(case for case in evidence.branch_cases if case.case_id == case_id)

    query = build_getscores_contract_query(case, _base_query())

    assert {field: query[field] for field in expected_fields} == expected_fields


def test_all_28_canonical_cases_build_deterministically_without_mutating_base(
    tmp_path: Path,
) -> None:
    """Canonical 28 caseを同じinputから再現可能なqueryへ変換する。

    Args:
        tmp_path (Path): Typed evidence用の一時manifest directoryを作るroot。

    Returns:
        None: 全caseがdeterministicかつcaller queryを変更しない。

    Raises:
        AssertionError: Catalog件数、query、identity保持、base copy境界が異なる場合。
    """
    evidence = _load_branch_evidence(tmp_path)

    assert len(evidence.branch_cases) == 28
    assert {case.case_id for case in evidence.branch_cases} == _CANONICAL_CASE_IDS
    for case in evidence.branch_cases:
        base_query = _base_query()
        original = dict(base_query)

        first = build_getscores_contract_query(case, base_query)
        second = build_getscores_contract_query(case, base_query)

        assert first == second
        assert first is not base_query
        assert first["caller-owned"] == "preserved"
        assert base_query == original
        if case.identity_profile in {
            GetscoresIdentityProfile.AUTH_MISSING,
            GetscoresIdentityProfile.AUTH_INVALID,
            GetscoresIdentityProfile.KNOWN_BEATMAP,
        }:
            assert first["c"] == _BASE_CHECKSUM

    malformed_mode = next(
        case for case in evidence.branch_cases if case.case_id == "malformed-mode"
    )
    assert malformed_mode.expected_shape_id is GetscoresWireShapeId.HEADER_ONLY


@pytest.mark.parametrize(
    ("case_id", "missing_field"),
    [
        ("global-with-rows", "c"),
        ("auth-invalid", "us"),
        ("auth-invalid", "ha"),
        ("update-candidate", "f"),
        ("update-candidate", "i"),
    ],
)
def test_required_caller_owned_identity_fields_fail_closed_without_values(
    tmp_path: Path,
    case_id: str,
    missing_field: str,
) -> None:
    """Seed-owned identity field不足をsafe identifierだけで拒否する。

    Args:
        tmp_path (Path): Typed evidence用の一時manifest directoryを作るroot。
        case_id (str): Required fieldを持つcanonical branch case ID。
        missing_field (str): Base queryから除去するfield名。

    Returns:
        None: Missing fieldがvalue-redacted errorになる。

    Raises:
        AssertionError: Error codeが異なるかcaller値がmessageへ漏れた場合。
    """
    evidence = _load_branch_evidence(tmp_path)
    case = next(case for case in evidence.branch_cases if case.case_id == case_id)
    base_query = _base_query()
    _ = base_query.pop(missing_field)
    base_query["caller-owned"] = "raw-secret-caller-value"

    expected_error = f"getscores_contract:base_query:{missing_field}:missing_field"
    with pytest.raises(ValueError, match=expected_error) as raised:
        _ = build_getscores_contract_query(case, base_query)

    message = str(raised.value)
    assert message == expected_error
    assert "raw-secret-caller-value" not in message


@pytest.mark.parametrize(
    ("profile_kind", "expected_error"),
    [
        ("identity", "getscores_contract:identity_profile:unknown_profile"),
        ("request_selector", "getscores_contract:request_selector:unknown_profile"),
        ("seed", "getscores_contract:seed_profile:unknown_profile"),
        ("mutation", "getscores_contract:mutation_profile:unknown_profile"),
    ],
)
def test_corrupted_runtime_profiles_fail_closed_without_echoing_values(
    tmp_path: Path,
    profile_kind: str,
    expected_error: str,
) -> None:
    """Typed loaderを迂回したunknown runtime profileを固定errorで拒否する。

    Args:
        tmp_path (Path): Typed evidence用の一時manifest directoryを作るroot。
        profile_kind (str): Corruptするclosed profile fieldの識別子。
        expected_error (str): 期待するvalue-redacted error code。

    Returns:
        None: Unknown profileがfallbackされず拒否される。

    Raises:
        AssertionError: Error codeが異なるかprofile/query値がmessageへ漏れた場合。
    """
    evidence = _load_branch_evidence(tmp_path)
    case = next(case for case in evidence.branch_cases if case.case_id == "global-with-rows")
    raw_profile = "raw-secret-profile-value"
    match profile_kind:
        case "identity":
            case = replace(
                case,
                identity_profile=cast(
                    "GetscoresIdentityProfile",
                    cast("object", raw_profile),
                ),
            )
        case "request_selector":
            case = replace(
                case,
                request_selector=cast(
                    "GetscoresRequestSelector",
                    cast("object", raw_profile),
                ),
            )
        case "seed":
            case = replace(
                case,
                seed_profile=cast(
                    "GetscoresSeedProfile",
                    cast("object", raw_profile),
                ),
            )
        case "mutation":
            case = replace(
                case,
                mutation_profiles=(cast("GetscoresMutationProfile", cast("object", raw_profile)),),
            )
        case _:
            raise AssertionError("unknown test profile kind")
    base_query = _base_query()
    base_query["caller-owned"] = "raw-secret-query-value"

    with pytest.raises(ValueError, match=expected_error) as raised:
        _ = build_getscores_contract_query(case, base_query)

    message = str(raised.value)
    assert message == expected_error
    assert raw_profile not in message
    assert "raw-secret-query-value" not in message


def test_selected_mods_rejects_incoherent_known_seed_profile(tmp_path: Path) -> None:
    """Selected Modsと不整合なknown seedもfallbackせず拒否する。

    Args:
        tmp_path (Path): Typed evidence用の一時manifest directoryを作るroot。

    Returns:
        None: Invalid selector/seed combinationが固定errorになる。

    Raises:
        AssertionError: Incoherent seedが暗黙のmod bitmaskへ変換された場合。
    """
    evidence = _load_branch_evidence(tmp_path)
    case = next(
        case for case in evidence.branch_cases if case.case_id == "selected-mods-supported"
    )
    case = replace(case, seed_profile=GetscoresSeedProfile.RANKED_WITH_ROWS)

    expected_error = "getscores_contract:seed_profile:invalid_selector_profile"
    with pytest.raises(ValueError, match=expected_error) as raised:
        _ = build_getscores_contract_query(case, _base_query())

    assert str(raised.value) == expected_error


@pytest.mark.parametrize("shape_id", tuple(GetscoresWireShapeId))
def test_expected_body_resolver_returns_publicly_decoded_fixture_bytes(
    tmp_path: Path,
    shape_id: GetscoresWireShapeId,
) -> None:
    """Known shapeをpublic fixture boundary経由のdecoded bytesへ解決する。

    Args:
        tmp_path (Path): Typed evidence用の一時manifest directoryを作るroot。
        shape_id (GetscoresWireShapeId): 解決するcanonical wire shape ID。

    Returns:
        None: Resolverとfixture objectが同じexact bytesを返す。

    Raises:
        AssertionError: Shape lookupまたはBase64 decode boundaryが異なる場合。
    """
    evidence = _load_branch_evidence(tmp_path)
    shape = next(shape for shape in evidence.response_shapes if shape.shape_id is shape_id)

    body = read_getscores_expected_body(evidence, shape_id)

    assert body == shape.read_body_bytes()


def test_expected_body_resolver_calls_public_boundary_with_resolved_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolverがstrict resolved pathでpublic fixture boundaryを一度だけ呼ぶ。

    Args:
        tmp_path (Path): Typed evidence用の一時manifest directoryを作るroot。
        monkeypatch (pytest.MonkeyPatch): Typed spy functionをmethodへ一時設定するfixture。

    Returns:
        None: Sentinel bytesとexact call pathが確認できた状態。

    Raises:
        AssertionError: Direct decode、boundary bypass、複数呼び出し、未解決pathの場合。
    """
    evidence = _load_branch_evidence(tmp_path)
    shape_id = GetscoresWireShapeId.HEADER_ONLY
    selected_shape = next(
        shape for shape in evidence.response_shapes if shape.shape_id is shape_id
    )
    expected_path = selected_shape.body_file.resolve(strict=True)
    calls: list[Path] = []
    sentinel = b"getscores-public-boundary-sentinel"

    def spy(self: GetscoresWireShapeFixture) -> bytes:
        calls.append(self.body_file)
        return sentinel

    monkeypatch.setattr(GetscoresWireShapeFixture, "read_body_bytes", spy)

    body = read_getscores_expected_body(evidence, shape_id)

    assert body == sentinel
    assert calls == [expected_path]


def test_expected_body_resolver_rejects_unknown_shape_without_echoing_value(
    tmp_path: Path,
) -> None:
    """Unknown runtime shape IDをraw valueなしで即時拒否する。

    Args:
        tmp_path (Path): Typed evidence用の一時manifest directoryを作るroot。

    Returns:
        None: Unknown shapeがsafe error codeになる。

    Raises:
        AssertionError: Error codeが異なるかunknown valueがmessageへ漏れた場合。
    """
    evidence = _load_branch_evidence(tmp_path)
    unknown = cast("GetscoresWireShapeId", cast("object", "raw-secret-shape"))

    expected_error = "getscores_contract:shape_id:unknown_shape"
    with pytest.raises(ValueError, match=expected_error) as raised:
        _ = read_getscores_expected_body(evidence, unknown)

    message = str(raised.value)
    assert message == expected_error
    assert "raw-secret-shape" not in message


def test_expected_body_resolver_rejects_missing_known_shape(tmp_path: Path) -> None:
    """Known shapeがbundleに存在しない場合をfallbackせず拒否する。

    Args:
        tmp_path (Path): Typed evidence用の一時manifest directoryを作るroot。

    Returns:
        None: Missing shapeがsafe error codeになる。

    Raises:
        AssertionError: Resolverが別shapeへfallbackするかerror codeが異なる場合。
    """
    evidence = _load_branch_evidence(tmp_path)
    evidence = replace(
        evidence,
        response_shapes=tuple(
            shape
            for shape in evidence.response_shapes
            if shape.shape_id is not GetscoresWireShapeId.HEADER_ONLY
        ),
    )

    expected_error = "getscores_contract:shape_id:missing_shape"
    with pytest.raises(ValueError, match=expected_error) as raised:
        _ = read_getscores_expected_body(evidence, GetscoresWireShapeId.HEADER_ONLY)

    assert str(raised.value) == expected_error


def test_expected_body_resolver_rejects_duplicate_known_shape(tmp_path: Path) -> None:
    """Known shapeが複数存在するambiguous bundleを拒否する。

    Args:
        tmp_path (Path): Typed evidence用の一時manifest directoryを作るroot。

    Returns:
        None: Duplicate shapeがsafe error codeになる。

    Raises:
        AssertionError: Resolverが最初のshapeを暗黙選択するかerror codeが異なる場合。
    """
    evidence = _load_branch_evidence(tmp_path)
    duplicate = next(
        shape
        for shape in evidence.response_shapes
        if shape.shape_id is GetscoresWireShapeId.HEADER_ONLY
    )
    evidence = replace(
        evidence,
        response_shapes=(*evidence.response_shapes, duplicate),
    )

    expected_error = "getscores_contract:shape_id:duplicate_shape"
    with pytest.raises(ValueError, match=expected_error) as raised:
        _ = read_getscores_expected_body(evidence, GetscoresWireShapeId.HEADER_ONLY)

    assert str(raised.value) == expected_error


def test_expected_body_resolver_rejects_all_shapes_outside_canonical_root(
    tmp_path: Path,
) -> None:
    """全shapeが同じmalicious parentへ移されてもcanonical root外を拒否する。

    Args:
        tmp_path (Path): Canonical root外のbody filesを置く一時directory。

    Returns:
        None: Shared malicious parentをtrusted rootとして推論しない。

    Raises:
        AssertionError: Outside bodyが読まれるかpath/valueがmessageへ漏れた場合。
    """
    evidence = _load_branch_evidence(tmp_path)
    outside_root = tmp_path / "raw-secret-outside-root"
    outside_root.mkdir()
    outside_shapes: list[GetscoresWireShapeFixture] = []
    for shape in evidence.response_shapes:
        outside = outside_root / shape.body_file.name
        _ = outside.write_bytes(shape.body_file.read_bytes())
        outside_shapes.append(replace(shape, body_file=outside))
    evidence = replace(evidence, response_shapes=tuple(outside_shapes))

    expected_error = "getscores_contract:body_file:unsafe_body_root"
    with pytest.raises(ValueError, match=expected_error) as raised:
        _ = read_getscores_expected_body(evidence, GetscoresWireShapeId.HEADER_ONLY)

    message = str(raised.value)
    assert message == expected_error
    assert "raw-secret-outside-root" not in message
    assert str(tmp_path) not in message


def _load_branch_evidence(tmp_path: Path) -> GetscoresCompletionEvidence:
    manifest_root = tmp_path / "manifests"
    manifest_root.mkdir()
    for filename in ("response_shapes.json", "branch_cases.json"):
        source = _MANIFEST_ROOT / filename
        _ = (manifest_root / filename).write_bytes(source.read_bytes())
    crosswalk_schema = "athena.stable_compatibility.getscores.beatmap_status_crosswalk.v1"
    empty_crosswalk = f'{{"schema":"{crosswalk_schema}","entries":[]}}\n'
    _ = (manifest_root / "beatmap_status_crosswalk.json").write_text(
        empty_crosswalk,
        encoding="utf-8",
    )
    return load_getscores_completion_evidence(manifest_root, _BODY_ROOT)


def _base_query() -> dict[str, str]:
    return {
        "c": _BASE_CHECKSUM,
        "f": "Camellia - Exit (Realazy) [Insane].osu",
        "i": "1",
        "us": "SyntheticViewer",
        "ha": _BASE_PASSWORD_MD5,
        "s": "1",
        "vv": "5",
        "v": "4",
        "m": "3",
        "mods": "64",
        "caller-owned": "preserved",
    }
