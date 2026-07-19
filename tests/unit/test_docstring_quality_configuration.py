"""Docstring品質toolchainの設定契約を検証する."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"
UV_LOCK_PATH = PROJECT_ROOT / "uv.lock"
FIRST_PARTY_PYTHON_ROOTS = (
    PROJECT_ROOT / "src",
    PROJECT_ROOT / "tests",
    PROJECT_ROOT / "alembic",
    PROJECT_ROOT / "gitlint_rules",
    PROJECT_ROOT / "athena-crypto/tests",
    PROJECT_ROOT / ".agents",
)
DOCSTRING_NOQA_PATTERN = re.compile(
    r"#\s*noqa(?::[^\n]*)?\b(?:D\d{3}|DOC\d{3})\b",
    flags=re.IGNORECASE,
)

type TomlTable = dict[str, object]


def _load_toml(path: Path) -> TomlTable:
    """TOML設定ファイルを型付きtableとして読み込む.

    Args:
        path (Path): UTF-8で保存されたTOML設定ファイルの絶対path.

    Returns:
        TomlTable: 構造を検証する前の最上位table.
    """
    return cast("TomlTable", tomllib.loads(path.read_text(encoding="utf-8")))


def _require_table(value: object) -> TomlTable:
    """TOML値がtableであることを検証して返す.

    Args:
        value (object): TOML parserから取得した未検証の値.

    Returns:
        TomlTable: tableとして扱える値.

    Raises:
        AssertionError: 値がTOML tableではない場合.
    """
    assert isinstance(value, dict)
    return cast("TomlTable", value)


def _require_list(value: object) -> list[object]:
    """TOML値がlistであることを検証して返す.

    Args:
        value (object): TOML parserから取得した未検証の値.

    Returns:
        list[object]: listとして扱える値.

    Raises:
        AssertionError: 値がTOML listではない場合.
    """
    assert isinstance(value, list)
    return cast("list[object]", value)


def _require_string_list(value: object) -> list[str]:
    """TOML listが文字列だけで構成されることを検証する.

    Args:
        value (object): TOML parserから取得した未検証のlist値.

    Returns:
        list[str]: 文字列だけを含むdependencyまたはrule list.

    Raises:
        AssertionError: 値がlistではないか文字列以外を含む場合.
    """
    values = _require_list(value)
    assert all(isinstance(item, str) for item in values)
    return cast("list[str]", values)


def _locked_package_versions() -> dict[str, str]:
    """uv.lockからpackage名と固定versionの対応を取得する.

    Returns:
        dict[str, str]: lockされたpackage名をversionへ対応付けたtable.

    Raises:
        AssertionError: lock内のpackage recordが期待する形ではない場合.
    """
    lock = _load_toml(UV_LOCK_PATH)
    versions: dict[str, str] = {}
    for package in _require_list(lock["package"]):
        package_table = _require_table(package)
        name = package_table.get("name")
        version = package_table.get("version")
        assert isinstance(name, str)
        if isinstance(version, str):
            versions[name] = version
    return versions


def _contains_docstring_rule(rule: str) -> bool:
    """Ruff rule selectorがdocstring rule群を指定するか判定する.

    Args:
        rule (str): Ruff設定に記録されたrule selector.

    Returns:
        bool: `D`または`DOC`のdocstring rule群を指定するときはTrue.
    """
    normalized_rule = rule.upper()
    return (
        normalized_rule == "D"
        or (normalized_rule.startswith("D") and normalized_rule[1:].isdigit())
        or normalized_rule == "DOC"
        or (normalized_rule.startswith("DOC") and normalized_rule[3:].isdigit())
    )


def _docstring_noqa_locations() -> list[str]:
    """first-party Python内のdocstring lint抑制locationを収集する.

    Returns:
        list[str]: `D`または`DOC` ruleを抑制するsource locationのlist.
    """
    locations: list[str] = []
    for root in FIRST_PARTY_PYTHON_ROOTS:
        for source_path in root.rglob("*.py"):
            for line_number, line in enumerate(
                source_path.read_text(encoding="utf-8").splitlines(),
                start=1,
            ):
                if DOCSTRING_NOQA_PATTERN.search(line):
                    locations.append(f"{source_path.relative_to(PROJECT_ROOT)}:{line_number}")
    return locations


def test_declares_locked_docstring_tool_versions() -> None:
    """承認済みtoolがdev dependencyとuv.lockへ同じversionで存在することを検証する.

    これはruntime dependencyへtoolが混入せず再現可能な開発環境で実行できることを保証する.

    Returns:
        None: dependency宣言またはlock versionが異なる場合はassertionで失敗する.
    """
    pyproject = _load_toml(PYPROJECT_PATH)
    dependency_groups = _require_table(pyproject["dependency-groups"])
    dev_dependencies = _require_string_list(dependency_groups["dev"])
    locked_versions = _locked_package_versions()

    assert "interrogate==1.7.0" in dev_dependencies
    assert "pydoclint==0.9.1" in dev_dependencies
    assert locked_versions["interrogate"] == "1.7.0"
    assert locked_versions["pydoclint"] == "0.9.1"


def test_configures_non_blocking_google_docstring_toolchain() -> None:
    """RuffとinterrogateのGoogle Style対応設定を検証する.

    migration step 1ではcorpus整備前のglobal Ruff `D`有効化を禁止しつつ後続gateの
    Google conventionと全definition coverage契約を固定する.

    Returns:
        None: conventionまたはcoverage設定が期待値と異なる場合はassertionで失敗する.
    """
    pyproject = _load_toml(PYPROJECT_PATH)
    tool = _require_table(pyproject["tool"])
    ruff = _require_table(tool["ruff"])
    ruff_lint = _require_table(ruff["lint"])
    pydocstyle = _require_table(ruff_lint["pydocstyle"])
    interrogate = _require_table(tool["interrogate"])

    assert pydocstyle["convention"] == "google"
    assert not any(
        _contains_docstring_rule(rule) for rule in _require_string_list(ruff_lint["select"])
    )
    assert not any(
        _contains_docstring_rule(rule)
        for rule in _require_string_list(ruff_lint.get("extend-select", []))
    )
    assert interrogate["fail-under"] == 100
    assert interrogate["style"] == "sphinx"
    for option in (
        "ignore-init-method",
        "ignore-init-module",
        "ignore-magic",
        "ignore-module",
        "ignore-nested-functions",
        "ignore-nested-classes",
        "ignore-overloaded-functions",
        "ignore-private",
        "ignore-property-decorators",
        "ignore-setters",
        "ignore-semiprivate",
    ):
        assert interrogate[option] is False
    assert "exclude" not in interrogate
    assert "ignore-regex" not in interrogate
    assert "whitelist-regex" not in interrogate


def test_configures_pydoclint_content_checks_and_intentional_boundaries() -> None:
    """pydoclintの内容整合検査と設計上の例外を検証する.

    Raises AST比較とclass attribute比較だけを無効化しながらprivate definitionと
    Args/Returns/Yieldsの型整合を検査する設定を保護する.

    Returns:
        None: 必須検査または意図的な例外が変わった場合はassertionで失敗する.
    """
    pyproject = _load_toml(PYPROJECT_PATH)
    tool = _require_table(pyproject["tool"])
    pydoclint = _require_table(tool["pydoclint"])

    assert pydoclint["style"] == "google"
    for option in (
        "arg-type-hints-in-signature",
        "arg-type-hints-in-docstring",
        "check-arg-order",
        "require-return-section-when-returning-nothing",
        "check-return-types",
        "require-yield-section-when-yielding-nothing",
        "check-yield-types",
        "should-document-star-arguments",
        "check-style-mismatch",
    ):
        assert pydoclint[option] is True
    for option in (
        "skip-checking-short-docstrings",
        "skip-checking-private-functions",
        "ignore-underscore-args",
        "ignore-private-args",
        "omit-stars-when-documenting-varargs",
    ):
        assert pydoclint[option] is False
    assert pydoclint["allow-init-docstring"] is True
    assert pydoclint["skip-checking-raises"] is True
    assert pydoclint["check-class-attributes"] is False
    assert pydoclint["treat-property-methods-as-class-attributes"] is False
    assert pydoclint["auto-regenerate-baseline"] is False


def test_does_not_hide_docstring_debt_with_configuration_or_noqa() -> None:
    """baselineとdocstring lint抑制を使わないことを検証する.

    この検証はper-file ignoreとtool-level broad excludeを拒否し既存負債を可視化したまま
    migrationを進めることを保証する.

    Returns:
        None: 抑制設定またはsource内のdocstring `noqa`が見つかった場合はassertionで失敗する.
    """
    pyproject = _load_toml(PYPROJECT_PATH)
    tool = _require_table(pyproject["tool"])
    ruff = _require_table(tool["ruff"])
    ruff_lint = _require_table(ruff["lint"])
    pydoclint = _require_table(tool["pydoclint"])
    per_file_ignores = _require_table(ruff_lint.get("per-file-ignores", {}))

    assert "baseline" not in pydoclint
    assert "generate-baseline" not in pydoclint
    assert "exclude" not in pydoclint
    assert all(
        not any(_contains_docstring_rule(rule) for rule in _require_string_list(ignored_rules))
        for ignored_rules in per_file_ignores.values()
    )
    assert _docstring_noqa_locations() == []
