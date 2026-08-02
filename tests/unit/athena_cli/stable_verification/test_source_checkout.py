"""Stable verificationのsource checkout asset resolver契約を検証するmodule."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from athena_cli.stable_verification.source_checkout import source_checkout_path

if TYPE_CHECKING:
    import pytest


_SERVER_WORKSPACE_MEMBER = "apps/athena_server"
_CRYPTO_WORKSPACE_MEMBER = "packages/athena_crypto"
_UNAVAILABLE_ASSET_DIRECTORY = ".athena-source-checkout-assets-unavailable"
_ASSET_PARTS = ("tests", "fixtures", "stable_compatibility", "getscores", "response.json")


def test_source_checkout_path_resolves_asset_from_valid_workspace_anchor(
    tmp_path: Path,
) -> None:
    """有効なsource anchorがrepository root基準のasset pathを返すことを検証する.

    Args:
        tmp_path (Path): synthetic workspace rootを作成するtemporary directory.

    Returns:
        None: validated workspace rootからasset pathを解決して完了する.
    """
    workspace_root = tmp_path / "workspace"
    _write_workspace_manifest(
        workspace_root,
        (_SERVER_WORKSPACE_MEMBER, _CRYPTO_WORKSPACE_MEMBER),
    )
    anchor_path = _source_anchor(workspace_root)

    result = source_checkout_path(anchor_path, *_ASSET_PARTS)

    assert result == workspace_root.joinpath(*_ASSET_PARTS)


def test_source_checkout_path_for_installed_anchor_does_not_fallback_to_cwd(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Installed wheel anchorがCWDのsource checkout fixtureを利用しないことを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): consumer processのcurrent working directoryを隔離する
            fixture.
        tmp_path (Path): installed consumerとunrelated source checkoutを作成するtemporary
            directory.

    Returns:
        None: installed anchor向けunavailable pathを返して完了する.
    """
    installed_root = tmp_path / "consumer" / "site-packages"
    anchor_path = _installed_anchor(installed_root)
    cwd_workspace_root = tmp_path / "cwd-workspace"
    _write_workspace_manifest(
        cwd_workspace_root,
        (_SERVER_WORKSPACE_MEMBER, _CRYPTO_WORKSPACE_MEMBER),
    )
    cwd_asset = cwd_workspace_root.joinpath(*_ASSET_PARTS)
    monkeypatch.chdir(cwd_workspace_root)

    result = source_checkout_path(anchor_path, *_ASSET_PARTS)

    assert result == _unavailable_asset_path(anchor_path)
    assert result != cwd_asset
    assert not result.is_relative_to(cwd_workspace_root)


def test_source_checkout_path_rejects_malformed_workspace_without_cwd_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Malformed workspace manifestをsource checkoutとして受理しないことを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): unrelated valid checkoutをCWDに設定するfixture.
        tmp_path (Path): malformed candidate rootとCWD fixture rootを作成するtemporary directory.

    Returns:
        None: malformed candidateからunavailable pathを返して完了する.
    """
    malformed_root = tmp_path / "malformed-workspace"
    anchor_path = _source_anchor(malformed_root)
    _ = (malformed_root / "pyproject.toml").write_text("[tool.uv\n", encoding="utf-8")
    cwd_workspace_root = tmp_path / "cwd-workspace"
    _write_workspace_manifest(
        cwd_workspace_root,
        (_SERVER_WORKSPACE_MEMBER, _CRYPTO_WORKSPACE_MEMBER),
    )
    monkeypatch.chdir(cwd_workspace_root)

    result = source_checkout_path(anchor_path, *_ASSET_PARTS)

    assert result == _unavailable_asset_path(anchor_path)
    assert not result.is_relative_to(cwd_workspace_root)


def test_source_checkout_path_rejects_non_workspace_manifest_without_cwd_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Required memberが欠けるmanifestをsource checkoutとして受理しないことを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): unrelated valid checkoutをCWDに設定するfixture.
        tmp_path (Path): incomplete candidate rootとCWD fixture rootを作成するtemporary directory.

    Returns:
        None: incomplete candidateからunavailable pathを返して完了する.
    """
    incomplete_root = tmp_path / "incomplete-workspace"
    anchor_path = _source_anchor(incomplete_root)
    _write_workspace_manifest(incomplete_root, (_SERVER_WORKSPACE_MEMBER,))
    cwd_workspace_root = tmp_path / "cwd-workspace"
    _write_workspace_manifest(
        cwd_workspace_root,
        (_SERVER_WORKSPACE_MEMBER, _CRYPTO_WORKSPACE_MEMBER),
    )
    monkeypatch.chdir(cwd_workspace_root)

    result = source_checkout_path(anchor_path, *_ASSET_PARTS)

    assert result == _unavailable_asset_path(anchor_path)
    assert not result.is_relative_to(cwd_workspace_root)


def _source_anchor(workspace_root: Path) -> Path:
    """Synthetic Athena CLI source moduleのanchor pathを作成して返す.

    Args:
        workspace_root (Path): source checkoutまたはinstalled consumerとして扱うroot directory.

    Returns:
        Path: `athena_cli` stable verification moduleを表すanchor path.
    """
    anchor_path = (
        workspace_root
        / "apps"
        / "athena_server"
        / "src"
        / "athena_cli"
        / "stable_verification"
        / "source_checkout.py"
    )
    anchor_path.parent.mkdir(parents=True)
    anchor_path.touch()
    return anchor_path


def _installed_anchor(site_packages_root: Path) -> Path:
    """Installed wheel内のAthena CLI moduleを表すanchor pathを作成して返す.

    Args:
        site_packages_root (Path): isolated consumerのsite-packages directory.

    Returns:
        Path: workspace source layoutを含まないinstalled module anchor path.
    """
    anchor_path = site_packages_root / "athena_cli" / "stable_verification" / "source_checkout.py"
    anchor_path.parent.mkdir(parents=True)
    anchor_path.touch()
    return anchor_path


def _unavailable_asset_path(anchor_path: Path) -> Path:
    """Installedまたはinvalid workspace anchor向けのsentinel pathを返す.

    Args:
        anchor_path (Path): source checkoutとして検証に失敗するmodule path.

    Returns:
        Path: resolverがfixture fallbackを拒否するときの非存在asset path.
    """
    return anchor_path.parent / _UNAVAILABLE_ASSET_DIRECTORY / Path(*_ASSET_PARTS)


def _write_workspace_manifest(workspace_root: Path, members: tuple[str, ...]) -> None:
    """指定memberを持つminimal uv workspace manifestを作成する.

    Args:
        workspace_root (Path): pyproject.tomlを配置するcandidate workspace root.
        members (tuple[str, ...]): workspaceに属するmember path群.

    Returns:
        None: resolverが検証するminimal manifestを作成して完了する.
    """
    workspace_root.mkdir(parents=True, exist_ok=True)
    rendered_members = ", ".join(f'"{member}"' for member in members)
    _ = (workspace_root / "pyproject.toml").write_text(
        f"[tool.uv.workspace]\nmembers = [{rendered_members}]\n",
        encoding="utf-8",
    )
