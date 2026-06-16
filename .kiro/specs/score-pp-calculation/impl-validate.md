# score-pp-calculation 実装検証ログ

## 2026-06-17T00:32:08+09:00 - Task 7.4 検証

### 対象

- Spec: `.kiro/specs/score-pp-calculation/requirements.md`, `design.md`, `tasks.md`
- Task: 7.4 Quality gates と architecture boundaries を確認する
- 範囲: performance domain、repositories、worker、stable submit、CLI、architecture boundary
- RED phase: N/A。7.4 は非機能の検証・記録タスクであり、追加の runtime behavior を導入しない。

### 機械検証

#### Quality gate: PASS

Command:

```bash
./scripts/ci.sh quality
```

Result:

```text
Ruff format check: 636 files already formatted
Ruff lint check: All checks passed!
Basedpyright type check: 0 errors, 0 warnings, 0 notes
Import linter: 13 kept, 0 broken
Analyzed 433 files, 2026 dependencies
Exit code: 0
```

Import-linter contracts:

- Layered architecture: KEPT
- Services don't depend on transports: KEPT
- Services stay adapter independent: KEPT
- Server runtime doesn't depend on CLI: KEPT
- Jobs only depend on approved layers: KEPT
- Jobs stay persistence-adapter independent: KEPT
- Transports don't depend on jobs: KEPT
- Transports stay persistence-adapter independent: KEPT
- Transport family packages stay independent: KEPT
- Domain has no I/O dependencies: KEPT
- Repository interfaces stay pure: KEPT
- Shared has no business logic dependencies: KEPT
- Repositories only use approved database libraries: KEPT

#### Project test gate: PASS

Command:

```bash
./scripts/ci.sh test
```

Result:

```text
2466 passed in 70.43s (0:01:10)
Exit code: 0
```

### Coverage map

| Boundary | Evidence |
| --- | --- |
| Domain policy and state | `tests/unit/domain/scores/test_performance.py`, `tests/unit/services/commands/scores/performance/test_future_scope_boundaries.py` |
| Calculator isolation | `tests/unit/infrastructure/performance/test_rosu_calculator.py`, `tests/unit/infrastructure/performance/test_calculator_identity.py` |
| Completion signal | `tests/unit/infrastructure/state/test_performance_completion_signal.py` |
| Command persistence | `tests/unit/repositories/test_score_performance_command_repository_contract.py`, `tests/unit/repositories/sqlalchemy/test_score_performance_command_repository.py`, `tests/unit/repositories/memory/test_performance_state.py` |
| Query persistence and candidate selection | `tests/unit/repositories/test_score_performance_query_repository_contract.py`, `tests/unit/repositories/test_score_performance_migration.py` |
| Request / execute calculation workflows | `tests/unit/services/commands/scores/performance/test_request_calculation.py`, `tests/unit/services/commands/scores/performance/test_execute_calculation.py`, `tests/unit/services/commands/scores/performance/test_beatmap_file_provider.py` |
| Stable submit response | `tests/unit/services/queries/scores/test_performance_response.py`, `tests/unit/transports/web_legacy/test_score_submit_mapper.py`, `tests/integration/transports/web_legacy/test_score_submit_performance_e2e.py` |
| Recalculation operations | `tests/unit/services/commands/scores/performance/test_create_recalculation_batch.py`, `tests/unit/services/commands/scores/performance/test_process_recalculation_batch.py`, `tests/integration/services/commands/scores/performance/test_recalculation_recovery.py` |
| Worker adapters and runtime state | `tests/unit/jobs/test_score_performance_tasks.py`, `tests/unit/test_worker.py`, `tests/unit/test_worker_jobs.py` |
| CLI and composition | `tests/unit/athena_cli/test_pp.py`, `tests/unit/composition/test_performance_cli_composition.py`, `tests/unit/composition/test_performance_composition.py`, `tests/integration/athena_cli/test_cli_help.py` |
| Architecture guardrails | `tests/unit/test_architecture_boundary_contract.py`, `./scripts/ci.sh quality` import-linter contracts |

### Architecture boundary review

- Domain performance code remains transport- and infrastructure-independent. The quality gate confirms `Domain has no I/O dependencies` and `Repository interfaces stay pure`.
- `rosu-pp-py` stays behind the infrastructure calculator adapter. CLI and stable transports do not import the calculator.
- Stable submit integration reads PP through use-case/query boundaries and emits only stable-safe `pp` values or existing retry/error shapes.
- Worker jobs keep primitive payloads and resolve use-cases from runtime state; job boundary contracts keep SQLAlchemy, Valkey, calculator construction, and repository construction out of job adapters.
- Recalculation work is durable DB state; taskiq wake-ups and completion signals remain optimizations rather than sources of truth.
- Loved / Qualified / failed / Relax / Autopilot scope remains excluded from Wave 2 PP calculation, and leaderboard / stats projections are not updated by this feature.

### Stable client and worker behavior review

- Existing stable terminal duplicate behavior is covered by score submission service tests and stable submit E2E tests.
- Pending performance still returns retryable stable response instead of rejecting accepted scores.
- Unavailable or out-of-scope performance returns accepted completed response with `pp:0`.
- Worker duplicate execution and stale recalculation claim recovery converge through command use-cases and durable repository state.

### Decision

- Task-local decision: GO
- Remaining unverified items for 7.4: none
