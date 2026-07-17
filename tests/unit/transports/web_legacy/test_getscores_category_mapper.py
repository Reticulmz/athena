from __future__ import annotations

from pathlib import Path

import pytest

from athena_cli.stable_verification.getscores_evidence import (
    GetscoresRequestSelector,
    load_getscores_completion_evidence,
)
from osu_server.domain.scores.mods import Mod
from osu_server.transports.stable.web_legacy.mappers import GetscoresQueryParser
from tests.support.getscores_contract import build_getscores_contract_query

_FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures"
_MANIFEST_ROOT = _FIXTURE_ROOT / "stable_compatibility" / "getscores"
_BODY_ROOT = _FIXTURE_ROOT / "web_legacy" / "getscores" / "completion"
_GETSCORES_EVIDENCE = load_getscores_completion_evidence(_MANIFEST_ROOT, _BODY_ROOT)
_GETSCORES_CASES = {case.case_id: case for case in _GETSCORES_EVIDENCE.branch_cases}


@pytest.mark.parametrize(
    ("case_id", "expected_selected_mods", "expected_header_only", "expected_unsupported"),
    [
        ("global-with-rows", None, False, False),
        ("local-maps-global", None, False, False),
        ("selected-mods-supported", int(Mod.MIRROR), False, False),
        ("selected-mods-unsupported", None, True, True),
        ("friends-outbound-only", None, False, False),
        ("country-match", None, False, False),
        ("country-missing", None, False, False),
        ("country-xx", None, False, False),
        ("song-select-header-only", None, True, False),
        ("unsupported-leaderboard-header-only", None, True, True),
        ("unsupported-playstyle-header-only", None, True, False),
        ("global-no-scores", None, False, False),
    ],
)
def test_selection_catalog_query_maps_to_expected_domain_contract(
    case_id: str,
    expected_selected_mods: int | None,
    expected_header_only: bool,
    expected_unsupported: bool,
) -> None:
    """Catalog selectorをparserとcategory mapperの公開interfaceへ通す.

    Args:
        case_id (str): Canonical selection branch case ID.
        expected_selected_mods (int | None): Query scopeへ渡すraw Stable mod bitmask.
        expected_header_only (bool): Mapperがscore rowを抑止する期待値.
        expected_unsupported (bool): Mapperがunsupported selectionと判定する期待値.

    Returns:
        None: Category, mod bitmask, header-only, unsupportedが一致したことを示す.

    Raises:
        KeyError: Canonical caseがtyped evidence bundleに存在しない場合.
        AssertionError: Parserまたはcategory mapperのcontractがcatalogと異なる場合.
    """
    branch_case = _GETSCORES_CASES[case_id]
    query = build_getscores_contract_query(branch_case, _base_query())

    parse_result = GetscoresQueryParser().parse(query)

    assert parse_result.error is None
    assert parse_result.request is not None
    selection = parse_result.request.leaderboard_selection
    assert selection is not None
    assert selection.category is branch_case.expected_domain_category
    assert selection.header_only is expected_header_only
    assert selection.unsupported is expected_unsupported

    if branch_case.request_selector is GetscoresRequestSelector.SELECTED_MODS:
        expected_raw_mods = int(Mod.MIRROR) if case_id == "selected-mods-supported" else 1 << 31
        assert int(query["mods"]) == expected_raw_mods

    if expected_selected_mods is None:
        assert selection.selected_mods is None
    else:
        assert selection.selected_mods is not None
        assert selection.selected_mods.to_persistence_bitmask() == expected_selected_mods


def _base_query() -> dict[str, str]:
    return {
        "c": "0123456789abcdef0123456789abcdef",
        "us": "SyntheticViewer",
        "ha": "b" * 32,
    }
