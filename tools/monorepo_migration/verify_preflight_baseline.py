"""monorepo移行前の互換contractとcleanup inventoryを再検証する."""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import NoReturn, cast

type JsonMapping = Mapping[str, object]
type AlembicCurrentRunner = Callable[[Path], subprocess.CompletedProcess[str]]
ALEMBIC_CURRENT_REVISION_LINE = re.compile(r"(?P<revision>[^\s()]+)\s+\([^)]*\)")
MINIMUM_HISTORICAL_KIRO_SPEC_COUNT = 2


class VerificationMode(StrEnum):
    """Physical layoutに応じたbaseline検証範囲を表す.

    Attributes:
        PRE_CUTOVER (str): 旧root pathとcleanup inventoryが存在する移行前treeを検証するmode.
        POST_CUTOVER (str): owner workspaceへ移設済みの意味的互換contractだけを検証するmode.
    """

    PRE_CUTOVER = "pre-cutover"
    POST_CUTOVER = "post-cutover"


@dataclass(frozen=True, slots=True)
class ParsedArguments:
    """baseline checkerへ渡されたCLI引数を表す.

    Attributes:
        baseline (Path): 比較対象のchecked-in baseline JSON file.
        alembic_current (bool): 到達可能database上のAlembic currentも照合するか.
        mode (VerificationMode): 旧path inventoryまたは移設後semantic contractを検証するmode.
    """

    baseline: Path
    alembic_current: bool
    mode: VerificationMode


@dataclass(frozen=True, slots=True)
class Baseline:
    """schema versionを確認済みのpreflight snapshotを表す.

    Attributes:
        document (Mapping[str, object]): string keyを持つJSON objectとして検証済みのsnapshot.
    """

    document: JsonMapping

    def field(self, key: str) -> object:
        """baselineの必須fieldを取得する.

        Args:
            key (str): 取得するtop-level field名.

        Returns:
            object: JSON schemaに従って後続のcheckerがnarrowingするfield値.

        Raises:
            ValueError: fieldがbaselineに存在しない場合.
        """
        return _field(self.document, key, "baseline")


def main() -> None:
    """CLI引数を解析して移行前baselineとの差分を検証する.

    Returns:
        None: 差分がない場合は成功終了し、差分または実行不能なruntime check時はnon-zeroで終了する.
    """
    arguments = _parse_arguments()
    repository_root = Path.cwd()

    try:
        baseline = _load_baseline(arguments.baseline)
        differences = _collect_differences(repository_root, baseline, mode=arguments.mode)
        if arguments.alembic_current:
            differences.extend(
                collect_alembic_current_difference(
                    repository_root,
                    baseline,
                    mode=arguments.mode,
                )
            )
    except (OSError, SyntaxError, TypeError, ValueError) as error:
        _fail(f"Baseline verification could not complete: {error}")

    if differences:
        _report_differences(differences)
        raise SystemExit(1)

    print("Preflight baseline matches the current repository contract.")
    if not arguments.alembic_current:
        message = "Alembic current was not checked. Re-run with --alembic-current against a "
        print(f"{message}reachable database.")


def _parse_arguments() -> ParsedArguments:
    """Baseline checkerのcommand line引数を解析する.

    Returns:
        ParsedArguments: pathとoptionalなAlembic current検証を型付きで表した引数.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Verify Athena's pre-monorepo migration baseline without mutating repository state."
        )
    )
    _ = parser.add_argument(
        "--baseline",
        type=Path,
        required=True,
        help="Path to the checked-in preflight baseline JSON file.",
    )
    _ = parser.add_argument(
        "--alembic-current",
        action="store_true",
        help="Run alembic current against DATABASE_URL and compare it with the recorded head.",
    )
    _ = parser.add_argument(
        "--mode",
        choices=[mode.value for mode in VerificationMode],
        default=VerificationMode.PRE_CUTOVER.value,
        help="Check pre-cutover inventory or post-cutover semantic compatibility.",
    )
    namespace = parser.parse_args()
    parsed_values: object = vars(namespace)
    values = _mapping(parsed_values, "CLI arguments")
    baseline_path = _field(values, "baseline", "CLI arguments")
    alembic_current = _field(values, "alembic_current", "CLI arguments")
    mode_value = _field(values, "mode", "CLI arguments")
    if not isinstance(baseline_path, Path):
        raise TypeError("CLI argument --baseline must be a path")
    if not isinstance(alembic_current, bool):
        raise TypeError("CLI argument --alembic-current must be a boolean")
    if not isinstance(mode_value, str):
        raise TypeError("CLI argument --mode must be a string")
    return ParsedArguments(
        baseline=baseline_path,
        alembic_current=alembic_current,
        mode=VerificationMode(mode_value),
    )


def _load_baseline(path: Path) -> Baseline:
    """JSONで固定したpreflight baselineを読み込む.

    Args:
        path (Path): 読み込むchecked-in baseline JSONのpath.

    Returns:
        Baseline: schema versionを確認済みのbaseline値.

    Raises:
        ValueError: JSONがobjectでないか、対応していないschema versionの場合.
    """
    decoded = cast("object", json.loads(path.read_text(encoding="utf-8")))
    document = _mapping(decoded, f"baseline {path}")
    schema_version = _field(document, "schema_version", "baseline")
    if schema_version != 1:
        raise ValueError(f"Unsupported baseline schema version: {schema_version!r}")
    return Baseline(document=document)


def _collect_differences(
    repository_root: Path,
    baseline: Baseline,
    *,
    mode: VerificationMode = VerificationMode.PRE_CUTOVER,
) -> list[str]:
    """指定したphysical layoutでbaselineとの差分を収集する.

    Args:
        repository_root (Path): 検証対象repositoryのroot directory.
        baseline (Baseline): 比較するpreflight snapshot.
        mode (VerificationMode): pre-cutover inventoryまたはpost-cutover semantic contractのmode.

    Returns:
        list[str]: 検出した差分の人間が確認できる説明. 差分がない場合は空list.
    """
    if mode is VerificationMode.PRE_CUTOVER:
        differences = _check_verification_contract(baseline)
        required_file_differences = _check_required_files(repository_root, baseline)
        cleanup_differences = _check_cleanup_inventory(repository_root, baseline)
        differences.extend(required_file_differences)
        differences.extend(cleanup_differences)
        if required_file_differences:
            return differences
        differences.extend(
            _collect_semantic_differences(
                repository_root,
                baseline,
                mode=mode,
            )
        )
        return differences

    differences = _check_verification_contract(baseline)
    with tempfile.TemporaryDirectory(prefix="athena-preflight-semantic-") as directory:
        semantic_root = Path(directory)
        differences.extend(
            _populate_post_cutover_semantic_view(repository_root, semantic_root, baseline)
        )
        if differences:
            return differences
        differences.extend(
            _collect_semantic_differences(
                semantic_root,
                baseline,
                mode=mode,
            )
        )
    return differences


def _collect_semantic_differences(
    semantic_root: Path,
    baseline: Baseline,
    *,
    mode: VerificationMode,
) -> list[str]:
    """物理layoutから独立したruntime互換contractの差分を収集する.

    Args:
        semantic_root (Path): baselineのpre-cutover pathを解決できるread-only semantic view.
        baseline (Baseline): 比較するpreflight snapshot.
        mode (VerificationMode): CLI smokeとlegacy validation evidenceの解釈に使うlayout mode.

    Returns:
        list[str]: runtime、CLI、migration、build、validation semantic contractの差分.
    """
    differences: list[str] = []
    differences.extend(_check_runtime_contract(semantic_root, baseline))
    differences.extend(_check_cli_contract(semantic_root, baseline, mode=mode))
    differences.extend(_check_migration_chain(semantic_root, baseline))
    differences.extend(_check_build_contracts(semantic_root, baseline))
    differences.extend(
        _check_validation_contract(
            semantic_root,
            baseline,
            mode=mode,
        )
    )
    return differences


def _populate_post_cutover_semantic_view(
    repository_root: Path,
    semantic_root: Path,
    baseline: Baseline,
) -> list[str]:
    """予定済みowner relocationを旧path非依存のsemantic viewへ解決する.

    Args:
        repository_root (Path): 移設先owner workspaceを含む実際のrepository root.
        semantic_root (Path): 一時的に旧baseline pathを解決するdirectory.
        baseline (Baseline): post-cutover relocation mapを含むsnapshot.

    Returns:
        list[str]: relocation targetが存在しない場合の差分. 成功時は空list.
    """
    compatibility = _post_cutover_compatibility(baseline)
    relocations = _mapping(
        _field(compatibility, "relocations", "post_cutover_compatibility"),
        "post_cutover_compatibility.relocations",
    )
    differences: list[str] = []
    for pre_cutover_path, relocated_path in relocations.items():
        target_path = repository_root / _string(
            relocated_path,
            f"post_cutover_compatibility.relocations[{pre_cutover_path!r}]",
        )
        if not target_path.exists():
            differences.append(f"Post-cutover relocation target is missing: {target_path}")
            continue
        semantic_path = semantic_root / pre_cutover_path
        semantic_path.parent.mkdir(parents=True, exist_ok=True)
        semantic_path.symlink_to(target_path, target_is_directory=target_path.is_dir())
    return differences


def _post_cutover_compatibility(baseline: Baseline) -> JsonMapping:
    """Baselineからpost-cutover semantic compatibility設定を取得する.

    Args:
        baseline (Baseline): post-cutover server ownerとrelocationを記録したsnapshot.

    Returns:
        Mapping[str, object]: server workspaceとrelocationを含む設定.
    """
    return _mapping(
        baseline.field("post_cutover_compatibility"),
        "post_cutover_compatibility",
    )


def _check_required_files(repository_root: Path, baseline: Baseline) -> list[str]:
    """Baselineが参照するsource fileの存在を検証する.

    Args:
        repository_root (Path): 検証対象repositoryのroot directory.
        baseline (Baseline): 必須pathを含むpreflight snapshot.

    Returns:
        list[str]: 存在しない必須pathの差分.
    """
    required_files = _string_list(baseline.field("required_files"), "required_files")
    return [
        f"Required baseline path is missing: {path}"
        for path in required_files
        if not (repository_root / path).exists()
    ]


def _check_verification_contract(baseline: Baseline) -> list[str]:
    """Checker自身を呼び出すrecorded commandを検証する.

    Args:
        baseline (Baseline): verification commandを含むpreflight snapshot.

    Returns:
        list[str]: command argvがcanonical invocationと異なる場合の差分.
    """
    verification = _mapping(baseline.field("verification"), "verification")
    base_command = [
        "nix",
        "develop",
        "--command",
        "uv",
        "run",
        "python",
        "tools/monorepo_migration/verify_preflight_baseline.py",
        "--baseline",
        ".kiro/specs/monorepo-migration/preflight-baseline.json",
    ]
    current_command = _string_list(_field(verification, "command", "verification"), "command")
    current_with_alembic = _string_list(
        _field(verification, "alembic_current_command", "verification"),
        "alembic_current_command",
    )
    post_cutover_command = _string_list(
        _field(verification, "post_cutover_command", "verification"),
        "post_cutover_command",
    )
    differences: list[str] = []
    if current_command != base_command:
        differences.append("Baseline verification command changed")
    if current_with_alembic != [*base_command, "--alembic-current"]:
        differences.append("Baseline Alembic-current command changed")
    if post_cutover_command != [*base_command, "--mode", VerificationMode.POST_CUTOVER.value]:
        differences.append("Baseline post-cutover verification command changed")
    return differences


def _check_runtime_contract(repository_root: Path, baseline: Baseline) -> list[str]:
    """公開Python namespace、app、worker contractを構造的に検証する.

    Args:
        repository_root (Path): 検証対象repositoryのroot directory.
        baseline (Baseline): runtime contractを含むpreflight snapshot.

    Returns:
        list[str]: namespace、app、workerのsourceまたはentrypoint差分.
    """
    runtime = _mapping(baseline.field("runtime"), "runtime")
    namespaces = _mapping(_field(runtime, "python_namespaces", "runtime"), "python_namespaces")
    differences: list[str] = []

    app = _mapping(_field(runtime, "app", "runtime"), "runtime.app")
    app_source = _string(_field(app, "source", "runtime.app"), "runtime.app.source")
    package_name = _package_name_from_main_source(app_source)
    cli = _mapping(_field(runtime, "cli", "runtime"), "runtime.cli")
    cli_namespace = _string(
        _field(cli, "import_namespace", "runtime.cli"), "runtime.cli.import_namespace"
    )
    builds = _mapping(baseline.field("builds"), "builds")
    crypto = _mapping(_field(builds, "crypto", "builds"), "builds.crypto")
    crypto_module = _string(_field(crypto, "module", "builds.crypto"), "builds.crypto.module")
    expected_namespaces = {
        package_name: f"src/{package_name.replace('.', '/')}/__init__.py",
        cli_namespace: f"src/{cli_namespace.replace('.', '/')}/__init__.py",
        crypto_module: "athena-crypto/src/lib.rs",
    }
    if namespaces != expected_namespaces:
        message = "Python namespace contract changed: expected {!r}, got {!r}"
        differences.append(message.format(expected_namespaces, dict(namespaces)))
    for namespace, relative_path in expected_namespaces.items():
        if not (repository_root / relative_path).is_file():
            differences.append(
                f"Python namespace {namespace!r} is not available at {relative_path}"
            )
    expected_invocation = f"python -m {package_name}"
    expected_target = f"{package_name}.app:app"
    app_content = (repository_root / app_source).read_text(encoding="utf-8")
    if (
        _string(_field(app, "invocation", "runtime.app"), "runtime.app.invocation")
        != expected_invocation
    ):
        differences.append(f"App invocation changed: expected {expected_invocation!r}")
    if (
        _string(_field(app, "asgi_target", "runtime.app"), "runtime.app.asgi_target")
        != expected_target
    ):
        differences.append(f"App ASGI target changed: expected {expected_target!r}")
    if 'if __name__ == "__main__":' not in app_content:
        differences.append(f"App module invocation guard is missing: {app_source}")
    if expected_target not in app_content:
        differences.append(f"App ASGI target is not used by {app_source}: {expected_target!r}")

    worker = _mapping(_field(runtime, "worker", "runtime"), "runtime.worker")
    expected_worker_source = str(Path(app_source).with_name("worker.py"))
    expected_jobs_directory = str(Path(app_source).with_name("jobs"))
    expected_worker_entrypoint = f"{package_name}.worker:broker"
    worker_source = _string(_field(worker, "source", "runtime.worker"), "runtime.worker.source")
    jobs_directory = _string(
        _field(worker, "jobs_directory", "runtime.worker"), "runtime.worker.jobs_directory"
    )
    if worker_source != expected_worker_source:
        differences.append(f"Worker source changed: expected {expected_worker_source!r}")
    if jobs_directory != expected_jobs_directory:
        differences.append(f"Worker jobs directory changed: expected {expected_jobs_directory!r}")
    if (
        _string(_field(worker, "entrypoint", "runtime.worker"), "runtime.worker.entrypoint")
        != expected_worker_entrypoint
    ):
        differences.append(f"Worker entrypoint changed: expected {expected_worker_entrypoint!r}")

    worker_content = (repository_root / worker_source).read_text(encoding="utf-8")
    if "register_all_jobs(broker)" not in worker_content:
        differences.append("Worker no longer registers all application jobs on its broker")
    actual_task_names = _registered_task_names(repository_root / jobs_directory)
    expected_task_names = sorted(
        _string_list(_field(worker, "task_names", "runtime.worker"), "runtime.worker.task_names")
    )
    if actual_task_names != expected_task_names:
        differences.append(
            f"Worker task names changed: expected {expected_task_names}, got {actual_task_names}"
        )
    return differences


def _package_name_from_main_source(source_path: str) -> str:
    """`src/<package>/__main__.py` pathから公開package名を導出する.

    Args:
        source_path (str): app moduleのrepository相対source path.

    Returns:
        str: `python -m`とASGI targetに使うpackage名.

    Raises:
        ValueError: pathがsrc packageの`__main__.py`を表さない場合.
    """
    path = Path(source_path)
    minimum_main_module_parts = len(("src", "package", "__main__.py"))
    if (
        path.parts[0:1] != ("src",)
        or path.name != "__main__.py"
        or len(path.parts) < minimum_main_module_parts
    ):
        raise ValueError(f"App source must be a src package __main__.py path: {source_path}")
    return ".".join(path.parts[1:-1])


def _registered_task_names(jobs_directory: Path) -> list[str]:
    """Taskiq decoratorから登録済みtask名を静的に抽出する.

    Args:
        jobs_directory (Path): worker job moduleを含むdirectory.

    Returns:
        list[str]: 重複を除いてsortしたregistered task名.

    Raises:
        ValueError: task_nameがstring literalまたはmodule定数へ解決できない場合.
    """
    task_names: set[str] = set()
    for source_path in sorted(jobs_directory.glob("*.py")):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        constants = _string_constants(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
                continue
            for decorator in node.decorator_list:
                task_name = _task_name_from_decorator(decorator, constants)
                if task_name is not None:
                    task_names.add(task_name)
    return sorted(task_names)


def _string_constants(tree: ast.Module) -> dict[str, str]:
    """Module scopeのstring constantを収集する.

    Args:
        tree (ast.Module): 解析済みPython module AST.

    Returns:
        dict[str, str]: constant名とstring valueの対応.
    """
    constants: dict[str, str] = {}
    for node in tree.body:
        assignment = _named_assignment(node)
        if assignment is None:
            continue
        name, value = assignment
        string_value = _string_literal(value)
        if string_value is not None:
            constants[name] = string_value
    return constants


def _named_assignment(node: ast.stmt) -> tuple[str, ast.expr] | None:
    """単一nameへ値を代入するAST statementを安全に抽出する.

    Args:
        node (ast.stmt): 判定するmodule scope statement.

    Returns:
        tuple[str, ast.expr] | None: 代入先のnameとvalue. 対象外ならNone.
    """
    if isinstance(node, ast.Assign):
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            return None
        return node.targets[0].id, node.value
    if isinstance(node, ast.AnnAssign):
        if not isinstance(node.target, ast.Name) or node.value is None:
            return None
        return node.target.id, node.value
    return None


def _string_literal(expression: ast.expr) -> str | None:
    """AST expressionがstring literalならその値を返す.

    Args:
        expression (ast.expr): 判定するAST expression.

    Returns:
        str | None: string literalの値. それ以外ならNone.
    """
    if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
        return expression.value
    return None


def _task_name_from_decorator(decorator: ast.expr, constants: Mapping[str, str]) -> str | None:
    """jobs.register decoratorからtask_nameを解決する.

    Args:
        decorator (ast.expr): functionに付与されたdecorator expression.
        constants (Mapping[str, str]): 同じmoduleで宣言されたstring constant.

    Returns:
        str | None: jobs.register decoratorのtask名. 対象外ならNone.

    Raises:
        ValueError: task_nameの値を静的に解決できない場合.
    """
    if not (
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr == "register"
        and isinstance(decorator.func.value, ast.Name)
        and decorator.func.value.id == "jobs"
    ):
        return None
    for keyword in decorator.keywords:
        if keyword.arg != "task_name":
            continue
        task_name = _string_literal(keyword.value)
        if task_name is not None:
            return task_name
        if isinstance(keyword.value, ast.Name) and keyword.value.id in constants:
            return constants[keyword.value.id]
        raise ValueError("jobs.register task_name must be a string literal or module constant")
    raise ValueError("jobs.register must declare task_name")


def _check_cli_contract(
    repository_root: Path,
    baseline: Baseline,
    *,
    mode: VerificationMode,
) -> list[str]:
    """Console scriptとTyper command familyのbaselineを検証する.

    Args:
        repository_root (Path): 検証対象repositoryのroot directory.
        baseline (Baseline): CLI contractを含むsnapshot.
        mode (VerificationMode): installed CLI smokeを実行できるphysical layoutを表すmode.

    Returns:
        list[str]: console scriptまたはcommand familyの差分.
    """
    runtime = _mapping(baseline.field("runtime"), "runtime")
    cli = _mapping(_field(runtime, "cli", "runtime"), "runtime.cli")
    manifest_path = _string(_field(cli, "manifest", "runtime.cli"), "runtime.cli.manifest")
    root_manifest = _load_toml(repository_root / manifest_path)
    project = _mapping(_field(root_manifest, "project", "pyproject.toml"), "project")
    scripts = _mapping(_field(project, "scripts", "pyproject.toml.project"), "project.scripts")
    console_command = _string(
        _field(cli, "console_command", "runtime.cli"), "runtime.cli.console_command"
    )
    actual_entrypoint = scripts.get(console_command)
    expected_entrypoint = _string(
        _field(cli, "console_entrypoint", "runtime.cli"), "runtime.cli.console_entrypoint"
    )
    import_namespace = _string(
        _field(cli, "import_namespace", "runtime.cli"), "runtime.cli.import_namespace"
    )
    source_path = _string(_field(cli, "source", "runtime.cli"), "runtime.cli.source")
    command_groups, root_commands = _typer_command_catalog(repository_root / source_path)
    expected_groups = sorted(
        _string_list(_field(cli, "command_groups", "runtime.cli"), "runtime.cli.command_groups")
    )
    expected_root_commands = sorted(
        _string_list(_field(cli, "root_commands", "runtime.cli"), "runtime.cli.root_commands")
    )

    differences: list[str] = []
    expected_source_path = str(Path("src") / Path(*import_namespace.split(".")) / "main.py")
    expected_entrypoint_for_namespace = f"{import_namespace}.main:main"
    if source_path != expected_source_path:
        differences.append(f"CLI source changed: expected {expected_source_path!r}")
    if expected_entrypoint != expected_entrypoint_for_namespace:
        differences.append(
            f"CLI import namespace changed: expected {expected_entrypoint_for_namespace!r}"
        )
    if actual_entrypoint != expected_entrypoint:
        message = "Console command changed: {!r} resolves to {!r}, expected {!r}"
        differences.append(message.format(console_command, actual_entrypoint, expected_entrypoint))
    if command_groups != expected_groups:
        differences.append(
            f"CLI command groups changed: expected {expected_groups}, got {command_groups}"
        )
    if root_commands != expected_root_commands:
        differences.append(
            f"CLI root commands changed: expected {expected_root_commands}, got {root_commands}"
        )
    if mode is VerificationMode.PRE_CUTOVER:
        differences.extend(
            _check_cli_help(console_command, expected_groups, expected_root_commands)
        )
    differences.extend(
        _check_source_contracts(
            repository_root,
            _mapping(
                _field(cli, "confirmation_contract", "runtime.cli"),
                "runtime.cli.confirmation_contract",
            ),
            "CLI confirmation contract evidence is missing",
        )
    )
    differences.extend(
        _check_source_contracts(
            repository_root,
            _mapping(_field(cli, "exit_contract", "runtime.cli"), "runtime.cli.exit_contract"),
            "CLI exit contract evidence is missing",
        )
    )
    return differences


def _typer_command_catalog(source: Path) -> tuple[list[str], list[str]]:
    """Root Typer applicationに登録されたcommand groupとcommandを抽出する.

    Args:
        source (Path): `athena_cli.main`のsource file.

    Returns:
        tuple[list[str], list[str]]: sort済みのcommand group名とroot command名.
    """
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    groups: set[str] = set()
    commands: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_app_method(node.func, "add_typer"):
            groups.add(_required_keyword_string(node, "name"))
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and _is_app_method(decorator.func, "command"):
                    commands.add(_required_keyword_string(decorator, "name"))
    return sorted(groups), sorted(commands)


def _is_app_method(expression: ast.expr, method_name: str) -> bool:
    """AST expressionがroot `app`の指定method呼び出しかを判定する.

    Args:
        expression (ast.expr): 調べるcallable expression.
        method_name (str): 判定するTyper application method名.

    Returns:
        bool: root `app`の指定methodならTrue.
    """
    return (
        isinstance(expression, ast.Attribute)
        and expression.attr == method_name
        and isinstance(expression.value, ast.Name)
        and expression.value.id == "app"
    )


def _required_keyword_string(call: ast.Call, keyword_name: str) -> str:
    """AST callの必須keywordからstring literalを抽出する.

    Args:
        call (ast.Call): keywordを調べるcall expression.
        keyword_name (str): 抽出するkeyword名.

    Returns:
        str: 指定keywordに設定されたstring literal値.

    Raises:
        ValueError: keywordがないかstring literal以外の場合.
    """
    for keyword in call.keywords:
        if keyword.arg != keyword_name:
            continue
        value = _string_literal(keyword.value)
        if value is not None:
            return value
        raise ValueError(f"Typer {keyword_name} must be a string literal")
    raise ValueError(f"Typer call must declare {keyword_name}")


def _check_cli_help(
    console_command: str,
    expected_groups: Sequence[str],
    expected_root_commands: Sequence[str],
) -> list[str]:
    """Installed console commandのhelpがbaseline command familyを公開することを検証する.

    Args:
        console_command (str): baselineが公開するconsole command名.
        expected_groups (Sequence[str]): 公開されるべきTyper command group名.
        expected_root_commands (Sequence[str]): 公開されるべきroot command名.

    Returns:
        list[str]: console commandが見つからないかhelpにcommandがない場合の差分.
    """
    command_path = shutil.which(console_command)
    if command_path is None:
        return [
            f"Installed console command is unavailable for the CLI smoke check: {console_command}"
        ]
    result = subprocess.run(
        [command_path, "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        message = "{} --help failed with exit code {}: {}"
        return [message.format(console_command, result.returncode, result.stderr.strip())]
    return [
        f"{console_command} --help does not list command family {name!r}"
        for name in [*expected_groups, *expected_root_commands]
        if name not in result.stdout
    ]


def _check_source_contracts(
    repository_root: Path, contracts: JsonMapping, error_prefix: str
) -> list[str]:
    """Source pathとfragmentで表したcontract evidenceを検証する.

    Args:
        repository_root (Path): source fileを解決するrepository root.
        contracts (Mapping[str, object]): contract名ごとのsource evidence mapping.
        error_prefix (str): mismatch messageのcategory prefix.

    Returns:
        list[str]: source fileまたはrequired fragmentが不足する場合の差分.
    """
    differences: list[str] = []
    for contract_name, value in contracts.items():
        contract = _mapping(value, f"{error_prefix}[{contract_name!r}]")
        source_path = _string(
            _field(contract, "source", f"{error_prefix}[{contract_name!r}]"),
            f"{error_prefix}[{contract_name!r}].source",
        )
        fragments = _string_list(
            _field(contract, "fragments", f"{error_prefix}[{contract_name!r}]"),
            f"{error_prefix}[{contract_name!r}].fragments",
        )
        path = repository_root / source_path
        if not path.is_file():
            differences.append(
                f"{error_prefix}: source is missing for {contract_name!r}: {source_path}"
            )
            continue
        content = path.read_text(encoding="utf-8")
        differences.extend(
            f"{error_prefix}: {contract_name!r} lacks {fragment!r} in {source_path}"
            for fragment in fragments
            if fragment not in content
        )
    return differences


def _check_migration_chain(repository_root: Path, baseline: Baseline) -> list[str]:
    """Alembic revision chainとhead identifierを検証する.

    Args:
        repository_root (Path): 検証対象repositoryのroot directory.
        baseline (Baseline): migration baselineを含むsnapshot.

    Returns:
        list[str]: revision chainまたはheadの差分.
    """
    migration = _mapping(baseline.field("migrations"), "migrations")
    config_path = _string(_field(migration, "config", "migrations"), "migrations.config")
    versions_directory = _string(
        _field(migration, "versions_directory", "migrations"), "migrations.versions_directory"
    )
    script_location = str(Path(config_path).with_suffix(""))
    expected_versions_directory = str(Path(script_location) / "versions")
    config_source = repository_root / config_path
    differences: list[str] = []
    if versions_directory != expected_versions_directory:
        differences.append(
            f"Alembic versions directory changed: expected {expected_versions_directory!r}"
        )
    if not config_source.is_file():
        differences.append(f"Alembic config is missing: {config_path}")
        return differences
    expected_script_location = f"script_location = %(here)s/{script_location}"
    if expected_script_location not in config_source.read_text(encoding="utf-8"):
        differences.append(
            f"Alembic config no longer declares script location {script_location!r}"
        )
    actual_chain = _alembic_revision_chain(repository_root / versions_directory)
    expected_chain = _string_list(
        _field(migration, "revision_chain", "migrations"), "migrations.revision_chain"
    )
    expected_head = _string(_field(migration, "head", "migrations"), "migrations.head")
    expected_current_at_head = _string(
        _field(migration, "current_at_head", "migrations"), "migrations.current_at_head"
    )
    if actual_chain != expected_chain:
        differences.append(
            f"Alembic revision chain changed: expected {expected_chain}, got {actual_chain}"
        )
    if actual_chain and actual_chain[0] != expected_head:
        differences.append(
            f"Alembic head changed: expected {expected_head!r}, got {actual_chain[0]!r}"
        )
    if expected_current_at_head != expected_head:
        message = "Recorded Alembic current_at_head differs from recorded head: {!r} != {!r}"
        differences.append(message.format(expected_current_at_head, expected_head))
    return differences


def _alembic_revision_chain(versions_directory: Path) -> list[str]:
    """Alembic revision sourceからheadからbaseまでのchainを復元する.

    Args:
        versions_directory (Path): Alembic revision moduleを含むdirectory.

    Returns:
        list[str]: headからbaseまで順序づけたrevision identifier.

    Raises:
        ValueError: revision graphが分岐、循環、または静的に解決不能な場合.
    """
    revisions: dict[str, str | None] = {}
    for source_path in versions_directory.glob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        constants = _string_constants(tree)
        revision = constants.get("revision")
        if revision is None:
            raise ValueError(f"Alembic revision is missing in {source_path}")
        if revision in revisions:
            raise ValueError(f"Alembic revision identifier is duplicated: {revision}")
        revisions[revision] = _down_revision(tree, constants)

    descendants = {value for value in revisions.values() if value is not None}
    heads = sorted(set(revisions) - descendants)
    if len(heads) != 1:
        raise ValueError(f"Alembic revision graph must have one head, got {heads}")

    chain: list[str] = []
    revision: str | None = heads[0]
    while revision is not None:
        if revision in chain:
            raise ValueError(f"Alembic revision cycle detected at {revision}")
        chain.append(revision)
        revision = revisions.get(revision)
        if revision is not None and revision not in revisions:
            raise ValueError(f"Alembic revision parent is missing: {revision}")
    return chain


def _down_revision(tree: ast.Module, constants: Mapping[str, str]) -> str | None:
    """Alembic moduleのdown_revisionを静的に解決する.

    Args:
        tree (ast.Module): 解析済みAlembic revision module AST.
        constants (Mapping[str, str]): 同じmoduleで宣言されたstring constant.

    Returns:
        str | None: 親revision identifier. root revisionならNone.

    Raises:
        ValueError: down_revisionが宣言されていないかunsupportedな形式の場合.
    """
    for node in tree.body:
        assignment = _named_assignment(node)
        if assignment is None:
            continue
        name, value = assignment
        if name != "down_revision":
            continue
        if isinstance(value, ast.Constant):
            literal = value.value
            if isinstance(literal, str) or literal is None:
                return literal
        if isinstance(value, ast.Name) and value.id in constants:
            return constants[value.id]
        raise ValueError(
            "Alembic down_revision must be a string literal, None, or module constant"
        )
    raise ValueError("Alembic revision must declare down_revision")


def _check_build_contracts(repository_root: Path, baseline: Baseline) -> list[str]:
    """serverとcrypto artifactのbuild metadataを検証する.

    Args:
        repository_root (Path): 検証対象repositoryのroot directory.
        baseline (Baseline): build contractを含むsnapshot.

    Returns:
        list[str]: distribution、build backend、module名の差分.
    """
    builds = _mapping(baseline.field("builds"), "builds")
    server = _mapping(_field(builds, "server", "builds"), "builds.server")
    crypto = _mapping(_field(builds, "crypto", "builds"), "builds.crypto")
    server_manifest_path = _string(
        _field(server, "manifest", "builds.server"), "builds.server.manifest"
    )
    crypto_manifest_path = _string(
        _field(crypto, "manifest", "builds.crypto"), "builds.crypto.manifest"
    )
    differences: list[str] = []
    server_manifest = _load_recorded_manifest(
        repository_root,
        server_manifest_path,
        "Build manifest is missing for server",
        differences,
    )
    if server_manifest is not None:
        differences.extend(
            _check_server_build_contract(
                server_manifest,
                server_manifest_path,
                server,
                baseline,
            )
        )
    crypto_manifest = _load_recorded_manifest(
        repository_root,
        crypto_manifest_path,
        "Build manifest is missing for crypto",
        differences,
    )
    if crypto_manifest is not None:
        differences.extend(
            _check_crypto_build_contract(crypto_manifest, crypto_manifest_path, crypto)
        )
    return differences


def _check_server_build_contract(
    server_manifest: JsonMapping,
    manifest_path: str,
    server: JsonMapping,
    baseline: Baseline,
) -> list[str]:
    """Server distributionとwheel artifactのbaseline contractを検証する.

    Args:
        server_manifest (Mapping[str, object]): server Python manifestのTOML mapping.
        manifest_path (str): baselineがrecordしたserver manifestのrelative path.
        server (Mapping[str, object]): server build baseline mapping.
        baseline (Baseline): runtime namespaceを参照するpreflight snapshot.

    Returns:
        list[str]: server manifest、build command、wheel artifactの差分.
    """
    runtime = _mapping(baseline.field("runtime"), "runtime")
    app = _mapping(_field(runtime, "app", "runtime"), "runtime.app")
    cli = _mapping(_field(runtime, "cli", "runtime"), "runtime.cli")
    expected_namespaces = sorted(
        [
            _package_name_from_main_source(
                _string(_field(app, "source", "runtime.app"), "runtime.app.source")
            ),
            _string(
                _field(cli, "import_namespace", "runtime.cli"), "runtime.cli.import_namespace"
            ),
        ]
    )
    console_command = _string(
        _field(cli, "console_command", "runtime.cli"), "runtime.cli.console_command"
    )
    root_project = _mapping(_field(server_manifest, "project", manifest_path), "project")
    root_build_system = _mapping(
        _field(server_manifest, "build-system", manifest_path), "build-system"
    )
    artifact = _mapping(
        _field(server, "artifact_contract", "builds.server"), "builds.server.artifact_contract"
    )
    differences: list[str] = []
    if _string_list(_field(server, "command", "builds.server"), "builds.server.command") != [
        "nix",
        "develop",
        "--command",
        "uv",
        "build",
    ]:
        differences.append("Build command changed for server")
    if _field(root_project, "name", "project") != _field(server, "distribution", "builds.server"):
        differences.append("Server distribution name changed")
    if _field(root_build_system, "build-backend", "build-system") != _field(
        server, "build_backend", "builds.server"
    ):
        differences.append("Server build backend changed")
    wheel = _hatch_wheel_target(server_manifest, manifest_path)
    differences.extend(
        _check_server_artifact_contract(
            artifact,
            wheel,
            expected_namespaces,
            console_command,
        )
    )
    return differences


def _hatch_wheel_target(manifest: JsonMapping, manifest_path: str) -> JsonMapping:
    """Root Hatch設定からwheel target mappingを取得する.

    Args:
        manifest (Mapping[str, object]): server Python manifestのTOML mapping.
        manifest_path (str): manifestのrepository相対path.

    Returns:
        Mapping[str, object]: `tool.hatch.build.targets.wheel`のsetting mapping.
    """
    tool = _mapping(_field(manifest, "tool", manifest_path), "tool")
    hatch = _mapping(_field(tool, "hatch", "tool"), "tool.hatch")
    build = _mapping(_field(hatch, "build", "tool.hatch"), "tool.hatch.build")
    targets = _mapping(_field(build, "targets", "tool.hatch.build"), "tool.hatch.build.targets")
    return _mapping(
        _field(targets, "wheel", "tool.hatch.build.targets"),
        "tool.hatch.build.targets.wheel",
    )


def _check_server_artifact_contract(
    artifact: JsonMapping,
    wheel: JsonMapping,
    expected_namespaces: Sequence[str],
    console_command: str,
) -> list[str]:
    """Server wheelが公開namespaceとconsole commandを保持するか検証する.

    Args:
        artifact (Mapping[str, object]): server artifact baseline mapping.
        wheel (Mapping[str, object]): root Hatch wheel target mapping.
        expected_namespaces (Sequence[str]): appとCLIが公開するnamespace名.
        console_command (str): CLI baselineが公開するconsole command名.

    Returns:
        list[str]: artifact namespace、wheel package、console commandの差分.
    """
    artifact_namespaces = sorted(
        _string_list(
            _field(artifact, "python_namespaces", "builds.server.artifact_contract"),
            "builds.server.artifact_contract.python_namespaces",
        )
    )
    actual_wheel_packages = sorted(
        _string_list(
            _field(wheel, "packages", "tool.hatch.build.targets.wheel"),
            "tool.hatch.build.targets.wheel.packages",
        )
    )
    expected_wheel_packages = sorted(f"src/{namespace}" for namespace in expected_namespaces)
    artifact_console_command = _string(
        _field(artifact, "console_command", "builds.server.artifact_contract"),
        "builds.server.artifact_contract.console_command",
    )
    differences: list[str] = []
    if artifact_namespaces != list(expected_namespaces):
        message = "Server artifact Python namespaces changed: expected {!r}, got {!r}"
        differences.append(message.format(list(expected_namespaces), artifact_namespaces))
    if actual_wheel_packages != expected_wheel_packages:
        message = "Server wheel packages changed: expected {!r}, got {!r}"
        differences.append(message.format(expected_wheel_packages, actual_wheel_packages))
    if artifact_console_command != console_command:
        message = "Server artifact console command changed: expected {!r}, got {!r}"
        differences.append(message.format(console_command, artifact_console_command))
    return differences


def _check_crypto_build_contract(
    crypto_manifest: JsonMapping, manifest_path: str, crypto: JsonMapping
) -> list[str]:
    """Crypto distributionとnative extension artifactのbaseline contractを検証する.

    Args:
        crypto_manifest (Mapping[str, object]): crypto Python manifestのTOML mapping.
        manifest_path (str): baselineがrecordしたcrypto manifestのrelative path.
        crypto (Mapping[str, object]): crypto build baseline mapping.

    Returns:
        list[str]: crypto manifest、build command、native extensionの差分.
    """
    project = _mapping(_field(crypto_manifest, "project", manifest_path), "project")
    tool = _mapping(_field(crypto_manifest, "tool", manifest_path), "tool")
    maturin = _mapping(_field(tool, "maturin", "tool"), "tool.maturin")
    module = _string(_field(crypto, "module", "builds.crypto"), "builds.crypto.module")
    artifact = _mapping(
        _field(crypto, "artifact_contract", "builds.crypto"), "builds.crypto.artifact_contract"
    )
    native_extension_module = _string(
        _field(artifact, "native_extension_module", "builds.crypto.artifact_contract"),
        "builds.crypto.artifact_contract.native_extension_module",
    )
    differences: list[str] = []
    if _string_list(_field(crypto, "command", "builds.crypto"), "builds.crypto.command") != [
        "nix",
        "develop",
        "--command",
        "uv",
        "build",
        "--project",
        "athena-crypto",
    ]:
        differences.append("Build command changed for crypto")
    if _field(project, "name", "project") != _field(crypto, "distribution", "builds.crypto"):
        differences.append("Crypto distribution name changed")
    if _field(maturin, "module-name", "tool.maturin") != module:
        differences.append("Crypto extension module name changed")
    if native_extension_module != module:
        message = "Crypto artifact native extension module changed: expected {!r}, got {!r}"
        differences.append(message.format(module, native_extension_module))
    return differences


def _check_validation_contract(
    semantic_root: Path,
    baseline: Baseline,
    *,
    mode: VerificationMode,
) -> list[str]:
    """現在のquality/test対象とlayoutごとのpublic validation interfaceを検証する.

    Args:
        semantic_root (Path): baselineのpre-cutover pathを解決するread-only semantic view.
        baseline (Baseline): validation policy baselineを含むsnapshot.
        mode (VerificationMode): legacy command evidenceを検証するpre-cutover modeかを表す.

    Returns:
        list[str]: test pathまたはrequired command evidenceの差分.
    """
    validation = _mapping(baseline.field("validation"), "validation")
    manifest_path = _string(_field(validation, "manifest", "validation"), "validation.manifest")
    differences: list[str] = []
    manifest = _load_recorded_manifest(
        semantic_root,
        manifest_path,
        "Validation manifest is missing",
        differences,
    )
    if manifest is None:
        return differences
    tool = _mapping(_field(manifest, "tool", manifest_path), "tool")
    pytest = _mapping(_field(tool, "pytest", f"{manifest_path}.tool"), "tool.pytest")
    ini_options = _mapping(_field(pytest, "ini_options", "tool.pytest"), "tool.pytest.ini_options")
    actual_test_paths = _string_list(
        _field(ini_options, "testpaths", "tool.pytest.ini_options"), "pytest testpaths"
    )
    expected_test_paths = _string_list(
        _field(validation, "pytest_testpaths", "validation"), "validation.pytest_testpaths"
    )
    if actual_test_paths != expected_test_paths:
        differences.append(
            f"Pytest target paths changed: expected {expected_test_paths}, got {actual_test_paths}"
        )
    if mode is VerificationMode.POST_CUTOVER:
        return differences

    runtime = _mapping(baseline.field("runtime"), "runtime")
    cli = _mapping(_field(runtime, "cli", "runtime"), "runtime.cli")
    console_command = _string(
        _field(cli, "console_command", "runtime.cli"), "runtime.cli.console_command"
    )
    console_entrypoint = _string(
        _field(cli, "console_entrypoint", "runtime.cli"), "runtime.cli.console_entrypoint"
    )
    expected_commands = {
        "quality": {
            "argv": ["nix", "develop", "--command", "./scripts/ci.sh", "quality"],
            "source": "scripts/ci.sh",
            "fragments": ["quality)"],
        },
        "test": {
            "argv": ["nix", "develop", "--command", "./scripts/ci.sh", "test"],
            "source": "scripts/ci.sh",
            "fragments": ["test)"],
        },
        "targeted_python_test": {
            "argv": [
                "nix",
                "develop",
                "--command",
                "uv",
                "run",
                "pytest",
                "<path>",
            ],
            "source": "pyproject.toml",
            "fragments": ['testpaths = ["tests"]'],
        },
        "cli_smoke": {
            "argv": [
                "nix",
                "develop",
                "--command",
                "uv",
                "run",
                console_command,
                "--help",
            ],
            "source": "pyproject.toml",
            "fragments": [f'{console_command} = "{console_entrypoint}"'],
        },
    }
    command_records = _mapping(_field(validation, "commands", "validation"), "validation.commands")
    for command_name, expected in expected_commands.items():
        record = _mapping(
            _field(command_records, command_name, "validation.commands"),
            f"validation.commands[{command_name!r}]",
        )
        actual_argv = _string_list(
            _field(record, "argv", f"validation.commands[{command_name!r}]"),
            f"validation.commands[{command_name!r}].argv",
        )
        if actual_argv != expected["argv"]:
            differences.append(f"Validation command changed for {command_name}")
        actual_source = _string(
            _field(record, "source", f"validation.commands[{command_name!r}]"),
            f"validation.commands[{command_name!r}].source",
        )
        if actual_source != expected["source"]:
            message = "Validation command source changed for {}: expected {!r}, got {!r}"
            differences.append(message.format(command_name, expected["source"], actual_source))
        actual_fragments = _string_list(
            _field(record, "fragments", f"validation.commands[{command_name!r}]"),
            f"validation.commands[{command_name!r}].fragments",
        )
        if actual_fragments != expected["fragments"]:
            differences.append(f"Validation command evidence changed for {command_name}")
        differences.extend(
            _check_source_contracts(
                semantic_root,
                {command_name: record},
                "Validation command evidence is missing",
            )
        )
    command_evidence = _mapping(
        _field(validation, "required_command_evidence", "validation"),
        "validation.required_command_evidence",
    )
    for relative_path, fragments in command_evidence.items():
        path = semantic_root / relative_path
        if not path.is_file():
            differences.append(f"Validation command evidence source is missing: {relative_path}")
            continue
        content = path.read_text(encoding="utf-8")
        differences.extend(
            f"Validation command evidence is missing from {relative_path}: {fragment!r}"
            for fragment in _string_list(
                fragments, f"validation.required_command_evidence[{relative_path!r}]"
            )
            if fragment not in content
        )
    return differences


def _check_cleanup_inventory(repository_root: Path, baseline: Baseline) -> list[str]:
    """cleanup対象、template、generated state、authority inventoryの現在値を検証する.

    Args:
        repository_root (Path): 検証対象repositoryのroot directory.
        baseline (Baseline): cleanup inventoryを含むsnapshot.

    Returns:
        list[str]: tracked/untracked分類またはcurrent authority pathの差分.
    """
    inventory = _mapping(baseline.field("cleanup_inventory"), "cleanup_inventory")
    tracked_files = _tracked_files(repository_root)
    differences: list[str] = []

    legacy_capabilities = _mapping(
        _field(inventory, "legacy_task_capabilities", "cleanup_inventory"),
        "cleanup_inventory.legacy_task_capabilities",
    )
    for relative_path, capabilities in legacy_capabilities.items():
        capability_record = _mapping(
            capabilities, f"cleanup_inventory.legacy_task_capabilities[{relative_path!r}]"
        )
        path = repository_root / relative_path
        if not path.is_file():
            differences.append(f"Legacy task capability source is missing: {relative_path}")
            continue
        content = path.read_text(encoding="utf-8")
        if relative_path in {"scripts/ci.sh", "scripts/dev-tasks.sh"}:
            commands = _string_list(
                _field(
                    capability_record,
                    "commands",
                    f"cleanup_inventory.legacy_task_capabilities[{relative_path!r}]",
                ),
                f"cleanup_inventory.legacy_task_capabilities[{relative_path!r}].commands",
            )
            if not commands:
                raise ValueError(f"Legacy task capability inventory is empty for {relative_path}")
            differences.extend(
                f"Legacy task capability is missing: {relative_path} {command!r}"
                for command in commands
                if f"{command})" not in content
            )
            continue
        if relative_path == "scripts/agent-worktree.sh":
            if not _boolean(
                _field(capability_record, "retained", "scripts/agent-worktree.sh"),
                "scripts/agent-worktree.sh.retained",
            ):
                differences.append("Legacy agent worktree helper is no longer retained")
            source_evidence = _string_list(
                _field(capability_record, "source_evidence", "scripts/agent-worktree.sh"),
                "scripts/agent-worktree.sh.source_evidence",
            )
            differences.extend(
                f"Legacy task capability is missing: {relative_path} {fragment!r}"
                for fragment in source_evidence
                if fragment not in content
            )
            continue
        raise ValueError(f"Unsupported legacy task capability source: {relative_path}")

    differences.extend(
        f"Tracked template is missing: {relative_path}"
        for relative_path in _string_list(
            _field(inventory, "tracked_templates", "cleanup_inventory"),
            "cleanup_inventory.tracked_templates",
        )
        if relative_path not in tracked_files
    )
    for relative_path in _string_list(
        _field(inventory, "generated_state", "cleanup_inventory"),
        "cleanup_inventory.generated_state",
    ):
        if _is_tracked_path_or_descendant(relative_path, tracked_files):
            differences.append(f"Generated or machine-specific state is tracked: {relative_path}")
        if not _git_path_is_ignored(repository_root, relative_path):
            differences.append(
                f"Generated or machine-specific state is not ignored: {relative_path}"
            )
    differences.extend(
        f"Normative current path is missing: {relative_path}"
        for relative_path in _string_list(
            _field(inventory, "normative_current_paths", "cleanup_inventory"),
            "cleanup_inventory.normative_current_paths",
        )
        if not (repository_root / relative_path).exists()
    )
    differences.extend(
        f"Pre-cutover cleanup inventory path is missing: {relative_path}"
        for relative_path in _string_list(
            _field(inventory, "pre_cutover_cleanup_paths", "cleanup_inventory"),
            "cleanup_inventory.pre_cutover_cleanup_paths",
        )
        if not (repository_root / relative_path).exists()
    )

    differences.extend(check_kiro_and_todo_inventory(repository_root, inventory))
    differences.extend(_check_scope_exclusions(repository_root, inventory, baseline))
    return differences


def check_kiro_and_todo_inventory(repository_root: Path, inventory: JsonMapping) -> list[str]:
    """Kiroのcurrent/historical区別とTODO snapshotの前提を検証する.

    Args:
        repository_root (Path): 検証対象repositoryのroot directory.
        inventory (Mapping[str, object]): cleanup inventoryのtop-level mapping.

    Returns:
        list[str]: current Kiro path、historical evidence、TODO pathの差分.
    """
    historical = _mapping(
        _field(inventory, "historical_kiro_evidence", "cleanup_inventory"),
        "cleanup_inventory.historical_kiro_evidence",
    )
    current_spec = _string(
        _field(historical, "current_spec", "historical_kiro_evidence"),
        "historical_kiro_evidence.current_spec",
    )
    historical_glob = _string(
        _field(historical, "historical_spec_glob", "historical_kiro_evidence"),
        "historical_kiro_evidence.historical_spec_glob",
    )
    todo_status = _mapping(
        _field(inventory, "kiro_todo_status", "cleanup_inventory"),
        "cleanup_inventory.kiro_todo_status",
    )
    current_spec_is_normative = _boolean(
        _field(historical, "current_spec_is_normative", "historical_kiro_evidence"),
        "historical_kiro_evidence.current_spec_is_normative",
    )
    historical_specs_are_non_normative = _boolean(
        _field(historical, "historical_specs_are_non_normative", "historical_kiro_evidence"),
        "historical_kiro_evidence.historical_specs_are_non_normative",
    )
    task_source = _string(
        _field(todo_status, "task_source", "kiro_todo_status"), "kiro_todo_status.task_source"
    )
    task_identity = _string(
        _field(todo_status, "task_identity", "kiro_todo_status"),
        "kiro_todo_status.task_identity",
    )
    todo_path = _string(_field(todo_status, "todo_path", "kiro_todo_status"), "todo_path")
    todo_minimum_nonempty_lines = _integer(
        _field(todo_status, "todo_minimum_nonempty_lines", "kiro_todo_status"),
        "kiro_todo_status.todo_minimum_nonempty_lines",
    )

    differences: list[str] = []
    if not (repository_root / current_spec).is_dir():
        differences.append(f"Current Kiro spec path is missing: {current_spec}")
    spec_paths = sorted(path for path in repository_root.glob(historical_glob) if path.is_dir())
    if not spec_paths:
        differences.append(f"Historical Kiro evidence glob matched no paths: {historical_glob}")
    elif repository_root / current_spec not in spec_paths:
        differences.append(
            f"Current Kiro spec is outside historical evidence scope: {current_spec}"
        )
    elif len(spec_paths) < MINIMUM_HISTORICAL_KIRO_SPEC_COUNT:
        differences.append("Historical Kiro evidence has no completed-spec candidate")
    if not current_spec_is_normative:
        differences.append("Current Kiro spec is not classified as normative")
    if not historical_specs_are_non_normative:
        differences.append("Historical Kiro specs are not classified as non-normative")
    task_source_path = repository_root / task_source
    if not task_source_path.is_file():
        differences.append(f"Kiro task source is missing: {task_source}")
    elif task_identity not in task_source_path.read_text(encoding="utf-8"):
        differences.append(f"Kiro task identity is missing from {task_source}: {task_identity!r}")
    if not (repository_root / todo_path).is_file():
        differences.append(f"Kiro TODO inventory path is missing: {todo_path}")
    else:
        todo_lines = [
            line
            for line in (repository_root / todo_path).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if len(todo_lines) < todo_minimum_nonempty_lines:
            message = (
                "Kiro TODO has fewer non-empty lines than recorded: expected at least {}, got {}"
            )
            differences.append(message.format(todo_minimum_nonempty_lines, len(todo_lines)))
    return differences


def _check_scope_exclusions(
    repository_root: Path, inventory: JsonMapping, baseline: Baseline
) -> list[str]:
    """Boundary 1で禁止する明示pathが作成されていないことを検証する.

    Args:
        repository_root (Path): 検証対象repositoryのroot directory.
        inventory (Mapping[str, object]): cleanup inventoryのtop-level mapping.
        baseline (Baseline): server manifest pathを参照するpreflight snapshot.

    Returns:
        list[str]: snapshotで明示した禁止pathが存在する場合の差分.
    """
    exclusions = _mapping(
        _field(inventory, "scope_exclusions", "cleanup_inventory"),
        "cleanup_inventory.scope_exclusions",
    )
    forbidden_paths = _string_list(
        _field(exclusions, "forbidden_paths", "scope_exclusions"),
        "scope_exclusions.forbidden_paths",
    )
    forbidden_root_workspace_files = _string_list(
        _field(exclusions, "forbidden_root_workspace_files", "scope_exclusions"),
        "scope_exclusions.forbidden_root_workspace_files",
    )
    forbidden_process_names = _string_list(
        _field(exclusions, "forbidden_process_names", "scope_exclusions"),
        "scope_exclusions.forbidden_process_names",
    )
    expected_dependencies = _string_list(
        _field(exclusions, "root_python_dependencies", "scope_exclusions"),
        "scope_exclusions.root_python_dependencies",
    )
    crypto_cargo_manifest = _string(
        _field(exclusions, "crypto_cargo_manifest", "scope_exclusions"),
        "scope_exclusions.crypto_cargo_manifest",
    )
    crypto_dependencies = sorted(
        _string_list(
            _field(exclusions, "crypto_cargo_dependencies", "scope_exclusions"),
            "scope_exclusions.crypto_cargo_dependencies",
        )
    )
    crypto_library = _mapping(
        _field(exclusions, "crypto_library", "scope_exclusions"),
        "scope_exclusions.crypto_library",
    )

    differences: list[str] = []
    differences.extend(
        f"Scope-excluded path exists before its approved boundary: {relative_path}"
        for relative_path in forbidden_paths
        if (repository_root / relative_path).exists()
    )
    differences.extend(
        f"Scope-excluded root workspace file exists: {relative_path}"
        for relative_path in forbidden_root_workspace_files
        if (repository_root / relative_path).is_file()
    )
    process_names = _process_names(repository_root / "process-compose.yml")
    differences.extend(
        f"Scope-excluded process is configured: {process_name}"
        for process_name in forbidden_process_names
        if process_name in process_names
    )
    builds = _mapping(baseline.field("builds"), "builds")
    server = _mapping(_field(builds, "server", "builds"), "builds.server")
    server_manifest_path = _string(
        _field(server, "manifest", "builds.server"), "builds.server.manifest"
    )
    server_manifest = _load_recorded_manifest(
        repository_root,
        server_manifest_path,
        "Server dependency manifest is missing",
        differences,
    )
    if server_manifest is not None:
        server_project = _mapping(
            _field(server_manifest, "project", server_manifest_path), "project"
        )
        actual_dependencies = _string_list(
            _field(server_project, "dependencies", f"{server_manifest_path}.project"),
            f"{server_manifest_path}.project.dependencies",
        )
        if actual_dependencies != expected_dependencies:
            message = "Frozen root Python dependencies changed: expected {!r}, got {!r}"
            differences.append(message.format(expected_dependencies, actual_dependencies))
    cargo_manifest = _load_recorded_manifest(
        repository_root,
        crypto_cargo_manifest,
        "Crypto Cargo manifest is missing",
        differences,
    )
    if cargo_manifest is not None:
        differences.extend(
            _check_crypto_cargo_contract(
                cargo_manifest,
                crypto_cargo_manifest,
                crypto_dependencies,
                crypto_library,
            )
        )
    return differences


def _check_crypto_cargo_contract(
    cargo_manifest: JsonMapping,
    manifest_path: str,
    crypto_dependencies: Sequence[str],
    crypto_library: JsonMapping,
) -> list[str]:
    """Crypto Cargo manifestのdependencyとlibrary target contractを検証する.

    Args:
        cargo_manifest (Mapping[str, object]): baseline pathから読み込んだCargo manifest.
        manifest_path (str): baselineがrecordしたCargo manifestのrelative path.
        crypto_dependencies (Sequence[str]): 記録済みCargo dependency名.
        crypto_library (Mapping[str, object]): 記録済みnative library target contract.

    Returns:
        list[str]: dependency、library name、crate type、binary targetの差分.
    """
    cargo_dependencies = _mapping(
        _field(cargo_manifest, "dependencies", manifest_path),
        f"{manifest_path}.dependencies",
    )
    actual_crypto_dependencies = sorted(cargo_dependencies)
    cargo_library = _mapping(
        _field(cargo_manifest, "lib", manifest_path),
        f"{manifest_path}.lib",
    )
    expected_library_name = _string(
        _field(crypto_library, "name", "scope_exclusions.crypto_library"),
        "scope_exclusions.crypto_library.name",
    )
    actual_library_name = _string(
        _field(cargo_library, "name", f"{manifest_path}.lib"),
        f"{manifest_path}.lib.name",
    )
    expected_crate_type = _string_list(
        _field(crypto_library, "crate_type", "scope_exclusions.crypto_library"),
        "scope_exclusions.crypto_library.crate_type",
    )
    actual_crate_type = _string_list(
        _field(cargo_library, "crate-type", f"{manifest_path}.lib"),
        f"{manifest_path}.lib.crate-type",
    )
    expected_binary_targets = _string_list(
        _field(crypto_library, "binary_targets", "scope_exclusions.crypto_library"),
        "scope_exclusions.crypto_library.binary_targets",
    )
    actual_binary_targets = _cargo_binary_target_names(cargo_manifest, manifest_path)
    differences: list[str] = []
    if actual_crypto_dependencies != list(crypto_dependencies):
        message = "Frozen crypto Cargo dependencies changed: expected {!r}, got {!r}"
        differences.append(message.format(list(crypto_dependencies), actual_crypto_dependencies))
    if actual_library_name != expected_library_name:
        message = "Crypto library name changed: expected {!r}, got {!r}"
        differences.append(message.format(expected_library_name, actual_library_name))
    if actual_crate_type != expected_crate_type:
        message = "Crypto library crate type changed: expected {!r}, got {!r}"
        differences.append(message.format(expected_crate_type, actual_crate_type))
    if actual_binary_targets != expected_binary_targets:
        message = "Crypto binary targets changed: expected {!r}, got {!r}"
        differences.append(message.format(expected_binary_targets, actual_binary_targets))
    return differences


def _is_tracked_path_or_descendant(relative_path: str, tracked_files: set[str]) -> bool:
    """Git indexがpathまたはそのdirectory配下を追跡しているか判定する.

    Args:
        relative_path (str): repository rootからのfileまたはdirectory path.
        tracked_files (set[str]): Git indexで追跡するrepository相対path集合.

    Returns:
        bool: path自体またはdirectory配下のfileが追跡されていればTrue.
    """
    return relative_path in tracked_files or any(
        tracked_path.startswith(f"{relative_path}/") for tracked_path in tracked_files
    )


def _git_path_is_ignored(repository_root: Path, relative_path: str) -> bool:
    """Git ignore ruleが指定pathをgenerated stateとして除外するか判定する.

    Args:
        repository_root (Path): Git worktree root.
        relative_path (str): repository rootからのgenerated state path.

    Returns:
        bool: `git check-ignore --quiet`がpathをignoreすると判定すればTrue.

    Raises:
        RuntimeError: `git check-ignore`がignore不一致以外のerrorで失敗した場合.
    """
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", "--", relative_path],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise RuntimeError(f"git check-ignore failed for {relative_path}: {result.stderr.strip()}")


def _process_names(process_compose_source: Path) -> set[str]:
    """process-compose sourceからtop-level process名を抽出する.

    Args:
        process_compose_source (Path): process-compose YAML fileのpath.

    Returns:
        set[str]: `processes:`直下に宣言されたprocess名集合.

    Raises:
        ValueError: `processes:` sectionがないかprocess名の構文を解釈できない場合.
    """
    in_processes = False
    process_names: set[str] = set()
    for line in process_compose_source.read_text(encoding="utf-8").splitlines():
        if line == "processes:":
            in_processes = True
            continue
        if not in_processes:
            continue
        if line and not line.startswith((" ", "\t", "#")):
            break
        if not line.startswith("  ") or line.startswith("    "):
            continue
        candidate, separator, remainder = line.strip().partition(":")
        if not separator or not candidate or remainder.strip() != "":
            continue
        process_names.add(candidate)
    if not in_processes:
        raise ValueError(
            f"process-compose source has no processes section: {process_compose_source}"
        )
    return process_names


def _cargo_binary_target_names(cargo_manifest: JsonMapping, manifest_path: str) -> list[str]:
    """Cargo manifestの`[[bin]]` target名を抽出する.

    Args:
        cargo_manifest (Mapping[str, object]): TOMLとして読み込んだCargo manifest.
        manifest_path (str): Cargo manifestのrepository相対path.

    Returns:
        list[str]: declaration順のbinary target名. `[[bin]]`がなければ空list.

    Raises:
        TypeError: `[[bin]]` entryまたはそのnameがCargo TOML object/stringではない場合.
    """
    raw_targets = cargo_manifest.get("bin", [])
    if not isinstance(raw_targets, list):
        raise TypeError(f"{manifest_path}.bin must be a list")
    target_names: list[str] = []
    for index, target in enumerate(cast("list[object]", raw_targets)):
        target_mapping = _mapping(target, f"{manifest_path}.bin[{index}]")
        target_names.append(
            _string(
                _field(target_mapping, "name", f"{manifest_path}.bin[{index}]"),
                f"{manifest_path}.bin[{index}].name",
            )
        )
    return target_names


def _tracked_files(repository_root: Path) -> set[str]:
    """Git indexに追跡されているrepository相対pathを取得する.

    Args:
        repository_root (Path): Git worktree root.

    Returns:
        set[str]: Git indexのtracked path集合.

    Raises:
        RuntimeError: Git indexを読み取れない場合.
    """
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git ls-files failed: {result.stderr.strip()}")
    return set(result.stdout.splitlines())


def collect_alembic_current_difference(
    repository_root: Path,
    baseline: Baseline,
    *,
    mode: VerificationMode = VerificationMode.PRE_CUTOVER,
    run_current: AlembicCurrentRunner | None = None,
) -> list[str]:
    """Reachable database上のAlembic currentをrecorded headと比較する.

    Args:
        repository_root (Path): Alembic commandを実行するrepository root.
        baseline (Baseline): expected current/headを含むmigration snapshot.
        mode (VerificationMode): pre-cutover rootまたはpost-cutover server owner rootを選ぶmode.
        run_current (AlembicCurrentRunner | None): current commandを実行するinjected runner.
            Noneの場合はproduction subprocess runnerを使う.

    Returns:
        list[str]: command失敗、current revisionの曖昧さ、またはrecorded headとの不一致を表す差分.
    """
    migration = _mapping(baseline.field("migrations"), "migrations")
    runner = _run_alembic_current if run_current is None else run_current
    command_root = repository_root
    if mode is VerificationMode.POST_CUTOVER:
        compatibility = _post_cutover_compatibility(baseline)
        server_workspace = _string(
            _field(
                compatibility,
                "server_workspace",
                "post_cutover_compatibility",
            ),
            "post_cutover_compatibility.server_workspace",
        )
        command_root = repository_root / server_workspace
    if not command_root.is_dir():
        return [f"Alembic current command root is missing: {command_root}"]
    try:
        result = runner(command_root)
    except OSError as error:
        error_prefix = "Alembic current check could not run. Provide a reachable DATABASE_URL"
        return [f"{error_prefix} and retry: {error}"]
    if result.returncode != 0:
        error_prefix = "Alembic current check could not run. Provide a reachable DATABASE_URL"
        error_detail = f" and retry: exit code {result.returncode}; {result.stderr.strip()}"
        return [f"{error_prefix}{error_detail}"]
    expected_current = _string(_field(migration, "head", "migrations"), "migrations.head")
    current_revisions = _alembic_current_revisions(result.stdout)
    current_output = result.stdout.strip()
    if len(current_revisions) != 1:
        return [f"Alembic current output must contain exactly one revision: {current_output!r}"]
    actual_current = current_revisions[0]
    if actual_current != expected_current:
        return [
            f"Alembic current differs from recorded head {expected_current!r}: {actual_current!r}"
        ]
    return []


def _alembic_current_revisions(output: str) -> list[str]:
    """Alembic current標準出力から完全なrevision tokenだけを抽出する.

    Args:
        output (str): `alembic current`が標準出力へ書き込んだtext.

    Returns:
        list[str]: revision tokenと括弧内annotationだけから成る行ごとのrevision identifier.

    Notes:
        loggerの補足行やrevision tokenを含む任意textはcurrent revisionとして解釈しない.
    """
    revisions: list[str] = []
    for line in output.splitlines():
        match = ALEMBIC_CURRENT_REVISION_LINE.fullmatch(line.strip())
        if match is not None:
            revisions.append(match["revision"])
    return revisions


def _run_alembic_current(repository_root: Path) -> subprocess.CompletedProcess[str]:
    """Alembic current commandをrepository rootから実行する.

    Args:
        repository_root (Path): Alembic commandを実行するrepository root.

    Returns:
        subprocess.CompletedProcess[str]: stdout、stderr、終了codeを含むcommand実行結果.
    """
    return subprocess.run(
        ["uv", "run", "alembic", "current"],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )


def _load_toml(path: Path) -> JsonMapping:
    """TOML manifestをstring key mappingとして読み込む.

    Args:
        path (Path): 読み込むTOML manifestのpath.

    Returns:
        Mapping[str, object]: string keyを持つTOML top-level mapping.
    """
    with path.open("rb") as file:
        decoded: object = tomllib.load(file)
    return _mapping(decoded, f"TOML manifest {path}")


def _load_recorded_manifest(
    repository_root: Path,
    manifest_path: str,
    missing_message_prefix: str,
    differences: list[str],
) -> JsonMapping | None:
    """Baselineがrecordしたmanifest pathを読み込む.

    Args:
        repository_root (Path): manifest pathを解決するrepository root.
        manifest_path (str): baselineがrecordしたrepository相対manifest path.
        missing_message_prefix (str): manifest不在時のmismatch message接頭辞.
        differences (list[str]): 発見したmissing manifest差分を追加するlist.

    Returns:
        Mapping[str, object] | None: TOML mapping. pathが存在しない場合はNone.
    """
    path = repository_root / manifest_path
    if not path.is_file():
        differences.append(f"{missing_message_prefix}: {manifest_path}")
        return None
    return _load_toml(path)


def _field(mapping: JsonMapping, key: str, context: str) -> object:
    """String key mappingから必須fieldを取得する.

    Args:
        mapping (Mapping[str, object]): 参照するstring key mapping.
        key (str): 必須field名.
        context (str): error messageへ含めるmappingの用途.

    Returns:
        object: schemaに従ってcallerがnarrowingするfield値.

    Raises:
        ValueError: fieldがmappingに存在しない場合.
    """
    try:
        return mapping[key]
    except KeyError as error:
        raise ValueError(f"Missing required field {key!r} in {context}") from error


def _mapping(value: object, context: str) -> JsonMapping:
    """JSON/TOML値がstring key mappingであることを確認する.

    Args:
        value (object): 検証する値.
        context (str): error messageへ含める値の用途.

    Returns:
        Mapping[str, object]: string key mappingとして扱える値.

    Raises:
        TypeError: valueがstring key mappingではない場合.
    """
    if not isinstance(value, Mapping):
        raise TypeError(f"Expected a string-key mapping for {context}, got {value!r}")
    object_mapping = cast("Mapping[object, object]", value)
    mapping: dict[str, object] = {}
    for key, item in object_mapping.items():
        if not isinstance(key, str):
            raise TypeError(f"Expected string keys for {context}, got {key!r}")
        mapping[key] = item
    return mapping


def _string(value: object, context: str) -> str:
    """JSON/TOML値がstringであることを確認する.

    Args:
        value (object): 検証する値.
        context (str): error messageへ含める値の用途.

    Returns:
        str: string value.

    Raises:
        TypeError: valueがstringではない場合.
    """
    if not isinstance(value, str):
        raise TypeError(f"Expected a string for {context}, got {value!r}")
    return value


def _integer(value: object, context: str) -> int:
    """JSON/TOML値がboolではないintegerであることを確認する.

    Args:
        value (object): 検証する値.
        context (str): error messageへ含める値の用途.

    Returns:
        int: JSON/TOMLのinteger value.

    Raises:
        TypeError: valueがboolまたはinteger以外の場合.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"Expected an integer for {context}, got {value!r}")
    return value


def _boolean(value: object, context: str) -> bool:
    """JSON/TOML値がbooleanであることを確認する.

    Args:
        value (object): 検証する値.
        context (str): error messageへ含める値の用途.

    Returns:
        bool: JSON/TOMLのboolean value.

    Raises:
        TypeError: valueがbooleanではない場合.
    """
    if not isinstance(value, bool):
        raise TypeError(f"Expected a boolean for {context}, got {value!r}")
    return value


def _string_list(value: object, context: str) -> list[str]:
    """JSON/TOML値がstringだけからなるlistであることを確認する.

    Args:
        value (object): 検証する値.
        context (str): error messageへ含める値の用途.

    Returns:
        list[str]: string valueのlist.

    Raises:
        TypeError: valueがstringだけからなるlistではない場合.
    """
    if not isinstance(value, list):
        raise TypeError(f"Expected a list for {context}, got {value!r}")
    strings: list[str] = []
    for item in cast("list[object]", value):
        if not isinstance(item, str):
            raise TypeError(f"Expected strings only for {context}, got {item!r}")
        strings.append(item)
    return strings


def _report_differences(differences: Iterable[str]) -> None:
    """baselineとの差分をstderrへ出力する.

    Args:
        differences (Iterable[str]): reportする差分の反復.

    Returns:
        None: 差分をstderrへ出力して完了し、呼び出し側へ値を返さない.
    """
    for difference in differences:
        print(f"BASELINE MISMATCH: {difference}", file=sys.stderr)


def _fail(message: str) -> NoReturn:
    """checker設定errorをstderrへ出力して終了する.

    Args:
        message (str): 利用者へ表示する設定errorの内容.

    Raises:
        SystemExit: checkerを成功扱いせず終了する.
    """
    print(message, file=sys.stderr)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
