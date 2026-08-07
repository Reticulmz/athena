"""Stable verification用のsource checkout asset pathを解決する."""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

_SERVER_WORKSPACE_MEMBER = "apps/athena_server"
_CRYPTO_WORKSPACE_MEMBER = "packages/athena_crypto"
_UNAVAILABLE_ASSET_DIRECTORY = ".athena-source-checkout-assets-unavailable"


def source_checkout_path(anchor_path: Path, *relative_parts: str) -> Path:
    """検証済みsource checkoutからstable verification asset pathを解決する.

    Args:
        anchor_path (Path): `athena_cli` source moduleのfile path.
        *relative_parts (str): repository rootから解決するasset pathの構成要素.

    Returns:
        Path: source checkoutではrepository root基準のasset path. installed wheelではCWDに
            依存しない存在しないpath.

    Notes:
        Root候補はnon-package uv workspace manifestと`apps/athena_server/src`配下にanchorが
        あることの両方で検証する. wheelはrepository fixtureを含まないため、呼び出し側は返された
        pathのread失敗を既存のUNAVAILABLE結果へ変換する.
    """
    resolved_anchor = anchor_path.resolve()
    for candidate_root in resolved_anchor.parent.parents:
        if _is_source_checkout_root(candidate_root, resolved_anchor):
            return candidate_root.joinpath(*relative_parts)

    return resolved_anchor.parent.joinpath(_UNAVAILABLE_ASSET_DIRECTORY, *relative_parts)


def _is_source_checkout_root(candidate_root: Path, anchor_path: Path) -> bool:
    """Candidate directoryがこのsource moduleを含むAthena workspace rootか判定する.

    Args:
        candidate_root (Path): upward search中のroot候補directory.
        anchor_path (Path): 解決対象のstable verification module path.

    Returns:
        bool: root manifestとsource mountがAthena workspace contractを満たす場合はTrue.
    """
    expected_source_root = candidate_root / _SERVER_WORKSPACE_MEMBER / "src"
    if not anchor_path.is_relative_to(expected_source_root):
        return False

    manifest = _load_manifest_mapping(candidate_root / "pyproject.toml")
    workspace_config = (
        _nested_mapping_value(manifest, "tool", "uv", "workspace")
        if manifest is not None
        else None
    )
    workspace_members = (
        _string_list_value(workspace_config.get("members"))
        if workspace_config is not None
        else None
    )

    return {
        _SERVER_WORKSPACE_MEMBER,
        _CRYPTO_WORKSPACE_MEMBER,
    }.issubset(workspace_members or ())


def _load_manifest_mapping(manifest_path: Path) -> Mapping[str, object] | None:
    """TOML manifestをstring key mappingとして読み込む.

    Args:
        manifest_path (Path): candidate workspace rootにあるpyproject.toml path.

    Returns:
        Mapping[str, object] | None: 構文とmapping条件を満たすTOML document.
            読み込めない場合はNone.
    """
    try:
        document = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError, tomllib.TOMLDecodeError:
        return None
    return _mapping_value(document)


def _nested_mapping_value(
    root_mapping: Mapping[str, object],
    *keys: str,
) -> Mapping[str, object] | None:
    """Nested TOML tableをstring key mappingとして安全に返す.

    Args:
        root_mapping (Mapping[str, object]): traversalを開始するTOML mapping.
        *keys (str): rootから順に探索するtable key群.

    Returns:
        Mapping[str, object] | None: 全keyを辿れたnested mapping. 型またはkeyが不正な場合はNone.
    """
    current_value: object = root_mapping
    for key in keys:
        current_mapping = _mapping_value(current_value)
        if current_mapping is None:
            return None
        current_value = current_mapping.get(key)
    return _mapping_value(current_value)


def _mapping_value(value: object) -> Mapping[str, object] | None:
    """Object valueをstring keyのmappingとして安全に扱える場合だけ返す.

    Args:
        value (object): TOML documentから取り出した検証対象value.

    Returns:
        Mapping[str, object] | None: string key mapping. mappingでない場合はNone.
    """
    if not isinstance(value, dict):
        return None
    raw_mapping = cast("Mapping[object, object]", value)
    if not all(isinstance(key, str) for key in raw_mapping):
        return None
    return cast("Mapping[str, object]", raw_mapping)


def _string_list_value(value: object) -> tuple[str, ...] | None:
    """Object valueを文字列だけで構成するtupleへ変換する.

    Args:
        value (object): TOML documentから取り出したworkspace member value.

    Returns:
        tuple[str, ...] | None: 文字列だけのmember sequence. 条件を満たさない場合はNone.
    """
    if not isinstance(value, list):
        return None
    raw_members = cast("list[object]", value)
    if not all(isinstance(member, str) for member in raw_members):
        return None
    return tuple(cast("str", member) for member in raw_members)
