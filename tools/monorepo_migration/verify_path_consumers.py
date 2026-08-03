"""移設済みartifactのcurrent path consumerを監査するentrypoint."""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

type JsonObject = dict[str, object]


class PathConsumerAuditError(RuntimeError):
    """Path consumer監査policyまたは対象repositoryが不正であることを表すexception."""


@dataclass(frozen=True, slots=True)
class AuditRule:
    """旧path consumerを検出する一つの正規表現ruleを表す.

    Attributes:
        identifier (str): allowlistから参照する安定したrule ID.
        pattern (re.Pattern[str]): 旧path表記を検出するcompiled regular expression.
        replacement (str): consumerが参照すべき新pathの説明.
    """

    identifier: str
    pattern: re.Pattern[str]
    replacement: str


@dataclass(frozen=True, slots=True)
class AuditException:
    """監査対象から除外するpathまたはfinding例外を表す.

    Attributes:
        glob (str): repository rootからの相対path glob.
        reason (str): 例外がcurrent consumerでない理由.
        rule (str | None): 一部ruleだけを許可する場合のrule ID. Noneはpath全体を除外する.
    """

    glob: str
    reason: str
    rule: str | None = None


@dataclass(frozen=True, slots=True)
class AuditPolicy:
    """Path consumer監査の対象、rule、例外を保持するpolicy.

    Attributes:
        scan_paths (tuple[str, ...]): 監査するcurrent fileまたはdirectoryのpath.
        excluded_paths (tuple[AuditException, ...]): 監査対象外とするhistorical path.
        rules (tuple[AuditRule, ...]): stale pathを検出するrule.
        allowed_references (tuple[AuditException, ...]): current file内の理由付き例外.
    """

    scan_paths: tuple[str, ...]
    excluded_paths: tuple[AuditException, ...]
    rules: tuple[AuditRule, ...]
    allowed_references: tuple[AuditException, ...]


@dataclass(frozen=True, slots=True)
class AuditFinding:
    """旧path consumerの一行分の監査findingを表す.

    Attributes:
        path (str): repository rootからの相対path.
        line_number (int): stale referenceが現れた1-based line number.
        rule (AuditRule): findingを検出したrule.
        line (str): 検出された行のtrim済み表示.
    """

    path: str
    line_number: int
    rule: AuditRule
    line: str


def _object(value: object, label: str) -> JsonObject:
    """JSON valueがobjectであることを検証する.

    Args:
        value (object): JSON parserから返された未検証value.
        label (str): error messageへ表示するfield名.

    Returns:
        JsonObject: 検証済みJSON object.

    Raises:
        PathConsumerAuditError: valueがobjectではない場合.
    """
    if not isinstance(value, dict):
        raise PathConsumerAuditError(f"{label} must be a JSON object")
    return cast("JsonObject", value)


def _string(value: object, label: str) -> str:
    """JSON valueがstringであることを検証する.

    Args:
        value (object): JSON parserから返された未検証value.
        label (str): error messageへ表示するfield名.

    Returns:
        str: 検証済みstring.

    Raises:
        PathConsumerAuditError: valueがstringではない場合.
    """
    if not isinstance(value, str):
        raise PathConsumerAuditError(f"{label} must be a string")
    return value


def _string_list(value: object, label: str) -> tuple[str, ...]:
    """JSON valueがstring listであることを検証する.

    Args:
        value (object): JSON parserから返された未検証value.
        label (str): error messageへ表示するfield名.

    Returns:
        tuple[str, ...]: 検証済みstring tuple.

    Raises:
        PathConsumerAuditError: valueがstring listではない場合.
    """
    if not isinstance(value, list):
        raise PathConsumerAuditError(f"{label} must be a string list")
    items = cast("list[object]", value)
    if not all(isinstance(item, str) for item in items):
        raise PathConsumerAuditError(f"{label} must be a string list")
    return tuple(cast("list[str]", items))


def _exceptions(value: object, label: str) -> tuple[AuditException, ...]:
    """JSON exception listをtyped audit exceptionへ変換する.

    Args:
        value (object): JSON parserから返された未検証exception list.
        label (str): error messageへ表示するfield名.

    Returns:
        tuple[AuditException, ...]: 検証済みpath exception tuple.

    Raises:
        PathConsumerAuditError: exception shapeまたはfield typeが不正な場合.
    """
    if not isinstance(value, list):
        raise PathConsumerAuditError(f"{label} must be a JSON list")
    exceptions: list[AuditException] = []
    raw_exceptions = cast("list[object]", value)
    for index, raw_exception in enumerate(raw_exceptions):
        exception = _object(raw_exception, f"{label}[{index}]")
        glob = _string(exception.get("glob"), f"{label}[{index}].glob")
        reason = _string(exception.get("reason"), f"{label}[{index}].reason")
        raw_rule = exception.get("rule")
        rule = None if raw_rule is None else _string(raw_rule, f"{label}[{index}].rule")
        exceptions.append(AuditException(glob=glob, reason=reason, rule=rule))
    return tuple(exceptions)


def load_policy(policy_path: Path) -> AuditPolicy:
    """JSON policyを読み込み、監査に利用できる型へ変換する.

    Args:
        policy_path (Path): path consumer audit policy JSON path.

    Returns:
        AuditPolicy: 検証済みaudit policy.

    Raises:
        PathConsumerAuditError: policy fileが読めないかschemaが不正な場合.
    """
    try:
        raw_policy = cast("object", json.loads(policy_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as error:
        message = f"Could not read audit policy {policy_path}: {error}"
        raise PathConsumerAuditError(message) from error
    policy = _object(raw_policy, "policy")
    schema_version = policy.get("schema_version")
    if schema_version != 1:
        message = f"Unsupported audit policy schema_version: {schema_version!r}"
        raise PathConsumerAuditError(message)

    raw_rules = policy.get("rules")
    if not isinstance(raw_rules, list):
        raise PathConsumerAuditError("rules must be a JSON list")
    rules: list[AuditRule] = []
    identifiers: set[str] = set()
    raw_rule_items = cast("list[object]", raw_rules)
    for index, raw_rule in enumerate(raw_rule_items):
        rule = _object(raw_rule, f"rules[{index}]")
        identifier = _string(rule.get("id"), f"rules[{index}].id")
        if identifier in identifiers:
            raise PathConsumerAuditError(f"Duplicate audit rule id: {identifier}")
        identifiers.add(identifier)
        pattern_text = _string(rule.get("regex"), f"rules[{index}].regex")
        try:
            pattern = re.compile(pattern_text)
        except re.error as error:
            message = f"Invalid regex for rule {identifier}: {error}"
            raise PathConsumerAuditError(message) from error
        replacement = _string(rule.get("replacement"), f"rules[{index}].replacement")
        rules.append(AuditRule(identifier, pattern, replacement))

    allowed_references = _exceptions(policy.get("allow", []), "allow")
    return AuditPolicy(
        scan_paths=_string_list(policy.get("scan_paths"), "scan_paths"),
        excluded_paths=_exceptions(policy.get("excluded_paths", []), "excluded_paths"),
        rules=tuple(rules),
        allowed_references=allowed_references,
    )


def _matches(path: str, glob: str) -> bool:
    """repository-relative pathがpolicy globへ一致するか判定する.

    Args:
        path (str): repository rootからのPOSIX relative path.
        glob (str): policyが指定したPOSIX glob.

    Returns:
        bool: pathがglobへ一致する場合True.
    """
    return fnmatch.fnmatchcase(path, glob)


def _is_excluded(path: str, exceptions: Iterable[AuditException]) -> bool:
    """path全体を監査から除外するexceptionがあるか判定する.

    Args:
        path (str): repository rootからのPOSIX relative path.
        exceptions (Iterable[AuditException]): path exclusion definitions.

    Returns:
        bool: path全体を除外するexceptionがある場合True.
    """
    return any(
        exception.rule is None and _matches(path, exception.glob) for exception in exceptions
    )


def _is_allowed(path: str, rule: AuditRule, exceptions: Iterable[AuditException]) -> bool:
    """指定pathとruleの組み合わせがallowlistにあるか判定する.

    Args:
        path (str): repository rootからのPOSIX relative path.
        rule (AuditRule): findingを検出したrule.
        exceptions (Iterable[AuditException]): finding allowlist definitions.

    Returns:
        bool: path全体またはruleがallowされている場合True.
    """
    return any(
        _matches(path, exception.glob) and exception.rule in (None, "*", rule.identifier)
        for exception in exceptions
    )


def _iter_scan_files(repository_root: Path, scan_paths: Iterable[str]) -> tuple[Path, ...]:
    """policyのscan pathを重複なしのfile tupleへ展開する.

    Args:
        repository_root (Path): scan pathを解決するrepository root.
        scan_paths (Iterable[str]): fileまたはdirectoryのrepository-relative path.

    Returns:
        tuple[Path, ...]: repository内に存在するscan対象file.

    Raises:
        PathConsumerAuditError: scan pathがrepository外のabsolute pathまたは存在しない場合.
    """
    files: set[Path] = set()
    for raw_path in scan_paths:
        relative_path = Path(raw_path)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise PathConsumerAuditError(f"Scan path must be repository-relative: {raw_path}")
        path = repository_root / relative_path
        if not path.exists():
            raise PathConsumerAuditError(f"Scan path is missing: {raw_path}")
        if path.is_file():
            files.add(path)
        else:
            for candidate in path.rglob("*"):
                if not candidate.is_file() or candidate.suffix in {".pyc", ".pyo"}:
                    continue
                if any(
                    directory_name in {".git", "__pycache__", ".pytest_cache", ".ruff_cache"}
                    for directory_name in candidate.relative_to(path).parts
                ):
                    continue
                files.add(candidate)
    return tuple(sorted(files, key=lambda path: path.relative_to(repository_root).as_posix()))


def audit_repository(repository_root: Path, policy: AuditPolicy) -> tuple[AuditFinding, ...]:
    """Current consumer pathをpolicyに従って監査する.

    Args:
        repository_root (Path): 監査対象repositoryのroot path.
        policy (AuditPolicy): scan path、rule、historical exceptionを含むaudit policy.

    Returns:
        tuple[AuditFinding, ...]: allowされていないstale path findingをpath順に返す.

    Raises:
        PathConsumerAuditError: scan対象fileがUTF-8 textとして読めない場合.
    """
    findings: list[AuditFinding] = []
    for path in _iter_scan_files(repository_root, policy.scan_paths):
        relative_path = path.relative_to(repository_root).as_posix()
        if _is_excluded(relative_path, policy.excluded_paths):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError as error:
            message = f"Could not decode audit file {relative_path}: {error}"
            raise PathConsumerAuditError(message) from error
        for line_number, line in enumerate(lines, start=1):
            findings.extend(
                AuditFinding(
                    path=relative_path,
                    line_number=line_number,
                    rule=rule,
                    line=line.strip(),
                )
                for rule in policy.rules
                if rule.pattern.search(line)
                and not _is_allowed(
                    relative_path,
                    rule,
                    policy.allowed_references,
                )
            )
    return tuple(findings)


def _parser() -> argparse.ArgumentParser:
    """Path consumer audit CLIのargument parserを作る.

    Returns:
        argparse.ArgumentParser: repository rootとpolicy pathを受け付けるparser.
    """
    parser = argparse.ArgumentParser(
        description="Audit current consumers for moved repository paths."
    )
    _ = parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="監査対象repositoryのroot path.",
    )
    _ = parser.add_argument(
        "--policy",
        type=Path,
        default=Path(__file__).with_name("path_consumer_audit.json"),
        help="Path consumer audit policy JSON path.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Path consumerを監査し、findingをstderrへ報告する.

    Args:
        argv (Sequence[str] | None): parse対象のCLI argument. Noneの場合はprocess argumentを使う.

    Returns:
        int: stale findingがなく監査を完了した場合0、それ以外は1.
    """
    arguments = _parser().parse_args(argv)
    repository_root = cast("Path", arguments.repository_root).resolve()
    policy_path = cast("Path", arguments.policy).resolve()
    try:
        policy = load_policy(policy_path)
        findings = audit_repository(repository_root, policy)
    except PathConsumerAuditError as error:
        print(f"Path consumer audit failed: {error}", file=sys.stderr)
        return 1

    if findings:
        for finding in findings:
            location = f"{finding.path}:{finding.line_number}"
            message = " ".join(
                (
                    f"{location}: {finding.rule.identifier}: stale path reference;",
                    f"use {finding.rule.replacement}; {finding.line}",
                )
            )
            print(message, file=sys.stderr)
        return 1
    print("path consumer audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
