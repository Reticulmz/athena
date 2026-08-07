"""GitHub Actionsがcanonical root task contractを使うことを検証する."""

from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CI_WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"


def _job_blocks(workflow_source: str) -> dict[str, str]:
    """Workflow sourceからtop-level jobごとのsource blockを抽出する.

    Args:
        workflow_source (str): `.github/workflows/ci.yml`の全文.

    Returns:
        dict[str, str]: Job IDをkey、headerを含むjob sourceをvalueとするmapping.
    """
    lines = workflow_source.splitlines()
    jobs_started = False
    current_job: str | None = None
    job_lines: dict[str, list[str]] = {}

    for line in lines:
        if line == "jobs:":
            jobs_started = True
            continue
        if not jobs_started:
            continue
        header = re.fullmatch(r"  ([a-z][a-z0-9_-]*):", line)
        if header is not None:
            job_id = header.group(1)
            current_job = job_id
            job_lines[job_id] = [line]
            continue
        if current_job is not None:
            job_lines[current_job].append(line)

    return {job_id: "\n".join(source_lines) for job_id, source_lines in job_lines.items()}


def test_ci_reports_each_validation_boundary_as_a_distinct_job() -> None:
    """Quality、test、build、migration、Nix、auditを独立statusとして公開する契約を検証する.

    Returns:
        None: Required job IDまたは表示名が欠落する場合にassertionで失敗する.
    """
    jobs = _job_blocks(CI_WORKFLOW_PATH.read_text(encoding="utf-8"))
    required_jobs = {
        "quality": "Quality",
        "test": "Test",
        "build": "Build",
        "migration": "Migration",
        "nix": "Nix",
        "audit": "Audit",
    }

    assert required_jobs.keys() <= jobs.keys()
    for job_id, display_name in required_jobs.items():
        assert f"name: {display_name}" in jobs[job_id]


def test_ci_validation_jobs_invoke_canonical_root_recipes() -> None:
    """Native CI jobがlegacy scriptやecosystem commandへvalidation意味を複製しないことを検証する.

    Returns:
        None: Required Just recipeが欠落するかlegacy/direct validation commandが残る場合に失敗する.
    """
    workflow_source = CI_WORKFLOW_PATH.read_text(encoding="utf-8")
    jobs = _job_blocks(workflow_source)
    expected_recipes = {
        "quality": "just quality",
        "build": "just build",
        "migration": "just migration-check",
        "audit": "just audit-monorepo",
    }

    for job_id, command in expected_recipes.items():
        assert f"run: {command}" in jobs[job_id]
    assert "run: just db-migrate" in jobs["test"]
    assert "run: just test" in jobs["test"]
    assert "run: nix flake check" in jobs["nix"]
    assert "scripts/ci.sh" not in workflow_source
    assert "scripts/dev-tasks.sh" not in workflow_source
    assert "uv run pytest" not in workflow_source
    assert "alembic upgrade head" not in workflow_source


def test_test_job_applies_migration_before_the_full_root_test_gate() -> None:
    """Database-backed test jobがmigration head適用後に全workspace testを実行する契約を検証する.

    Returns:
        None: Migrationとtestの順序またはservice containerが不正な場合にassertionで失敗する.
    """
    test_job = _job_blocks(CI_WORKFLOW_PATH.read_text(encoding="utf-8"))["test"]

    assert test_job.index("run: just db-migrate") < test_job.index("run: just test")
    assert "image: postgres:16" in test_job
    assert "image: redis:7" in test_job
    assert "fetch-depth: 0" in test_job


def test_native_jobs_share_locked_setup_without_local_development_mutations() -> None:
    """Native jobがlocked environmentを復元しlocal setup副作用を要求しない契約を検証する.

    Returns:
        None: Just/native dependency setupが欠落するかlocal-only commandが混入した場合に失敗する.
    """
    workflow_source = CI_WORKFLOW_PATH.read_text(encoding="utf-8")
    jobs = _job_blocks(workflow_source)
    for job_id in ("quality", "test", "build", "migration", "audit"):
        job_source = jobs[job_id]
        assert "needs: setup" in job_source
        assert "uses: extractions/setup-just@v3" in job_source
        assert "uv sync --locked --reinstall-package athena-crypto" in job_source

    assert "image: postgres:16" in jobs["migration"]
    for forbidden_command in (
        "just setup",
        "just tunnel-setup",
        "just dev",
        "just dev-tunnel",
        "just process-lifecycle-check",
        "mkcert",
        "process-compose",
        "cloudflared",
        "prek install",
    ):
        assert forbidden_command not in workflow_source


def test_nix_job_uses_the_verified_install_action_and_flake_gate() -> None:
    """Nix jobがnative jobsと独立してreproducible Flake contractを検証する.

    Returns:
        None: Nix installer、flake check、またはjob独立性が欠落する場合にassertionで失敗する.
    """
    nix_job = _job_blocks(CI_WORKFLOW_PATH.read_text(encoding="utf-8"))["nix"]

    assert "uses: cachix/install-nix-action@v31" in nix_job
    assert "run: nix flake check" in nix_job
    assert "needs: setup" not in nix_job
