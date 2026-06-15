# score-pp-calculation Gap Analysis

## Summary

- Requirements は `requirements-generated` で未承認だが、brownfield gap analysis として実装差分の把握を先行した。
- 現状の score-ingestion は Score / Score Submission / Replay attachment の保存と stable completed response までを実装済みで、PP 計算、Performance Calculation、再計算 batch は未実装。
- beatmap-mirror と blob-storage は `.osu` file attachment の取得、blob id の保持、blob body 読み取りに使える既存資産を持つ。
- 実装方針は Hybrid が妥当。score submit boundary は最小拡張し、Performance Calculation / Recalculation は score とは別の domain、repository、worker use-case として新設する。
- 主なリスクは、重複 submit / 重複 job 実行時の current PP 一意性、bounded wait の signal 設計、大規模再計算の durable work 設計、`rosu-pp-py` の version / typing / Python 3.14 compatibility 確認。

## Context Loaded

- Spec: `.kiro/specs/score-pp-calculation/spec.json`, `.kiro/specs/score-pp-calculation/requirements.md`
- Steering: `.kiro/steering/tech.md`, `.kiro/steering/scaling.md`, `.kiro/steering/roadmap.md`
- Project glossary: `CONTEXT.md`
- Rules: `.claude/rules/architecture.md`, `.claude/rules/development.md`, `.claude/rules/operations.md`
- Existing code: score domain/use-cases/repositories/transports, beatmap mirror, blob storage, taskiq jobs, worker startup, CLI, Alembic migrations

Note: `.kiro/steering/product.md` and `.kiro/steering/structure.md` are not present. Current worktree also contains unrelated/unowned composition provider modularization changes; this analysis treats them as context and does not revert them.

## Current State Investigation

### Score Submission Assets

- `src/osu_server/domain/scores/score.py`
  - `Score` stores user, beatmap, checksum, ruleset, playstyle, mods, hit counts, score, max combo, accuracy, grade, passed, perfect, client version, submitted timestamp, and beatmap status at submission.
  - There is no PP, star rating, calculator version, formula profile, or performance state on `Score`.
- `src/osu_server/domain/scores/payload_parser.py`
  - `ParsedScore` exposes hit counts, mods, score, combo, pass/fail, client grade and client metadata.
  - These fields are enough to derive a `rosu-pp-py` score state without replay parsing.
- `src/osu_server/services/commands/scores/process_submission.py`
  - Full Wave 1 flow is implemented: decrypt, parse, authorize, beatmap eligibility, hit count validation, replay blob storage, score persistence.
  - It resolves beatmap metadata with `BeatmapResolveOptions(wait_timeout_seconds=5)`.
  - It currently returns `SubmissionResult` with score and beatmap identifiers only.
  - It does not enqueue PP calculation, wait for PP completion, or read current performance.
- `src/osu_server/services/commands/scores/submit_score.py`
  - `SubmitScoreUseCase` owns durable idempotency by submission fingerprint.
  - Existing fingerprint retry returns the existing submission outcome.
  - Different fingerprint with duplicate online checksum becomes terminal reject `duplicate_online_checksum`.
  - Duplicate replay checksum becomes terminal reject `duplicate_replay_checksum`.
  - `score_submissions.result_snapshot` stores score/beatmap/replay ids and diagnostics, but no PP.
- `src/osu_server/transports/stable/web_legacy/mappers/score_submit.py`
  - Completed response currently formats `pp:0`.
  - Retryable response is `error: yes`, terminal response is `error: no`.
  - Mapper can be extended to accept an already rounded stable PP value without owning calculation logic.

### Persistence Assets

- `src/osu_server/repositories/sqlalchemy/models/score.py`
  - Existing tables: `scores`, `score_submissions`, `replay_file_attachments`.
  - No `score_performance_calculations`, formula profile, recalculation batch, or recalculation work item tables.
- `src/osu_server/repositories/interfaces/unit_of_work.py`
  - UoW currently exposes users, roles, channels, chat, scores, submissions, replays, blobs, beatmaps.
  - Performance command repositories would need to be added to this contract.
- `src/osu_server/repositories/interfaces/queries/scores.py`
  - Query side currently supports `get_by_id` and `get_by_online_checksum`.
  - It does not expose current performance read methods.
- `src/osu_server/repositories/memory/commands/state.py`
  - In-memory UoW state mirrors command persistence for tests.
  - Performance and recalculation state must be added here if command repositories are added.
- `alembic/versions`
  - Score and beatmap file attachment migrations exist.
  - No performance or recalculation migrations exist.

### Beatmap And Blob Assets

- `src/osu_server/domain/beatmaps/models.py`
  - `BeatmapEligibility` already distinguishes `awards_ranked_pp`, `awards_loved_pp`, and `requires_osu_file_for_pp`.
  - For Wave 2, performance eligibility should use only passed scores with `awards_ranked_pp=True`; Loved / Qualified / failed scores remain outside Performance Calculation scope.
  - `BeatmapFileAttachment` stores `beatmap_id`, `blob_id`, checksum, source, filename, fetched/verified timestamps.
- `src/osu_server/services/queries/beatmaps/mirror/resolution_service.py`
  - `BeatmapResolveOptions(require_osu_file=True)` can enqueue `.osu` file fetch when missing.
  - Current wait is repository polling for beatmap metadata, not Performance Completion Signal.
- `src/osu_server/services/commands/storage/blob_storage.py`
  - `BlobStorageService.read_bytes(blob_id)` can read small blob bodies, which is suitable for loading `.osu` file bytes for calculator input.

### Job And Worker Assets

- `src/osu_server/infrastructure/jobs/registry.py`
  - Jobs are registered by stable task names and attached to taskiq broker.
- `src/osu_server/jobs/beatmap_fetch.py`
  - Job adapters validate primitive payloads, resolve use-cases from taskiq state, and fail observably if runtime state is missing.
  - This is the pattern to copy for PP calculation and recalculation processing.
- `src/osu_server/worker.py`
  - Worker startup resolves use-cases from Dishka and stores them on taskiq state.
  - PP job use-cases must be added to worker container and state.
- `src/osu_server/composition/providers/beatmaps_app.py`
  - App-side enqueue pattern uses `broker.find_task(task_name)` and `task.kiq(...)`.
  - PP calculation can reuse this wake-up pattern, but durable recalculation work cannot rely on taskiq queue as source of truth.

### CLI Assets

- `src/athena_cli/main.py`
  - Typer root command exposes `env`, `db`, `config`, and `test`.
  - No PP or recalculation command group exists.
- `src/athena_cli/commands/db.py`
  - Existing commands resolve environment, load config, and call app infrastructure or subprocess runners.
  - PP recalculation CLI should follow this shape but call a use-case that creates durable work; it must not calculate PP inside the CLI process.

### External Dependency Status

- `pyproject.toml` and `uv.lock` do not include `rosu-pp-py`.
- Context7 did not have an exact `rosu-pp-py` library entry. PyPI lists `rosu-pp-py` with latest observed version `4.0.2` and exposes the expected package for Python bindings.
- Dependency addition requires explicit user approval before `uv add`.
- Design phase must verify current API, Python 3.14 wheel availability, type information, and whether local stubs are needed.

Reference: https://pypi.org/project/rosu-pp-py/

## Requirement-to-Asset Map

| Requirement | Existing support | Gap / constraint |
| --- | --- | --- |
| 1. PP Eligibility | Score has `passed`; beatmap eligibility exposes `awards_ranked_pp` and `awards_loved_pp`; beatmap status is captured at submission. | Missing dedicated performance eligibility policy. Constraint: Wave 2 must ignore Loved / Qualified / failed even though beatmap eligibility has Loved PP language. |
| 2. Calculation Inputs | Score stores validated hit counts, mods, combo, ruleset, playstyle; beatmap file attachment stores blob id; blob storage can read bytes. | Missing `.osu` fetch-to-calculate orchestration, calculator input mapper, and unavailable reason policy. |
| 3. Stable Submit Response | Submit response mapper already returns completed / retryable / terminal stable bodies. | Missing PP request enqueue, bounded wait, current performance read, PP-aware `SubmissionResult`, and rounded `pp` formatting. |
| 4. Performance Calculation State | No current asset. | Missing state enum/value object, state transitions, worker claim model, unavailable reason, superseded historical handling. |
| 5. Current Performance Value and Provenance | Score is cleanly separate from PP; result snapshot is opaque JSON and currently has no PP. | Missing performance table with current/historical distinction, provenance fields, decimal PP/star storage, current selection query. |
| 6. Completion Waiting | Beatmap resolver has bounded wait polling; scaling steering calls out Valkey and distributed concerns. | Missing Performance Completion Signal abstraction and implementation. Constraint: signal cannot be source of truth; response must re-read DB. |
| 7. Submission Retry and Duplicate Score Handling | Fingerprint idempotency, duplicate online checksum reject, duplicate replay checksum reject already exist. | Need retry response to compose from existing score + current performance instead of snapshot-only result. Must not alter terminal duplicate behavior. |
| 8. Duplicate Calculation Requests | taskiq job pattern exists, UoW can enforce DB consistency. | Missing idempotent calculation request/claim repository methods and DB constraints for one current result per score/provenance. |
| 9. PP Recalculation Selection | Score query repository can read basic score data; beatmap/provenance not modeled. | Missing candidate selector for uncalculated/stale/version mismatch/profile mismatch/include-unavailable and eligibility filters. |
| 10. Recalculation CLI Entry Point | Typer CLI structure exists. | Missing PP command group, dry-run output, execute mode, filters, `--all`, `--include-unavailable`, optional `--limit`, and app composition entrypoint for use-case invocation. |
| 11. Durable Recalculation Batch | taskiq queue exists; database and UoW patterns exist. | Missing batch/work item domain, tables, repositories, chunk claiming, stale claim retry, progress reporting. Constraint: queue signal is not durable source of truth. |
| 12. Formula Profile Consistency | Playstyle exists on Score; Relax/AP are rejected in Wave 1 but schema supports axis. | Missing Formula Profile policy per playstyle, active profile provider/config/source, migration behavior, and no user-subset split enforcement. |
| 13. PP Representation and Stable Formatting | Stable submit response has `pp:0` placeholder. | Missing decimal persistence type decision, stable integer rounding rule implementation, and mapper tests for completed/unavailable/out-of-scope PP. |
| 14. Calculator Adoption and Isolation | Tech steering names `rosu-pp-py`; project has adapter-independent service rules. | Missing dependency, adapter wrapper, version recording, calculator error mapping, and type stub strategy if needed. |
| 15. Future Scope Boundaries | score-ingestion explicitly leaves leaderboard/stats/PP to later waves; getscores is header-only MVP. | Need design to keep Wave 2 from updating leaderboard/stats projections and avoid replay parsing. |

## Implementation Approach Options

### Option A: Extend Existing Score Submission Components

**Shape**

- Add performance fields and workflow directly around `ProcessScoreSubmissionUseCase`, `SubmitScoreUseCase`, score repositories, and stable mapper.
- Store current PP close to score or submission snapshot.

**Pros**

- Lowest initial file count.
- Reuses existing idempotency and stable response flow directly.
- Minimal new composition surface.

**Cons**

- Blurs Score source-of-truth and Performance Calculation source-of-truth.
- Risks making the already complex `ProcessScoreSubmissionUseCase.execute` larger.
- Hard to support historical calculations, superseded rows, and durable recalculation batches.
- Conflicts with requirement that PP must not be canonical in `score_submissions.result_snapshot`.

**Assessment**

- Effort: M
- Risk: High
- Not recommended except for a temporary spike, because it makes future leaderboard/stats work inherit the wrong boundary.

### Option B: Create A Fully Independent Performance Subsystem

**Shape**

- Add new domain package under scores/performance or a sibling score performance module.
- Add performance command/query repositories, SQLAlchemy/memory implementations, worker jobs, completion signals, recalculation batch model, and CLI command.
- Existing score submission only emits a request or score id; all PP response behavior goes through performance query service.

**Pros**

- Cleanest ownership boundary for Performance Calculation, provenance, and recalculation.
- Easy to test calculation and recalculation independently.
- Fits roadmap separation: score-ingestion Wave 1, score-pp-calculation Wave 2, leaderboard/stats later.

**Cons**

- Requires multiple new files and repository contracts.
- Needs careful integration with existing submit retry semantics.
- If implemented too separately, stable response can become awkward or require extra orchestration.

**Assessment**

- Effort: L
- Risk: Medium
- Good architectural direction, but submit response requirements still need a small existing boundary extension.

### Option C: Hybrid: Minimal Submit Extension + New Performance Subsystem

**Shape**

- Keep score submission responsible for accepting/rejecting/storing score and preserving existing duplicate behavior.
- Add a new performance subsystem for eligibility, request/claim, calculation, current/historical persistence, completion signal, and recalculation batch/work.
- Extend `ProcessScoreSubmissionUseCase` result path to request PP, wait up to bounded window, re-read current performance, and return PP-aware result for stable mapper.
- Keep `score_submissions.result_snapshot` free of canonical PP.

**Pros**

- Preserves existing score-ingestion behavior and tests.
- Keeps PP state and provenance separate from Score.
- Allows stable submit response to satisfy bounded wait/retry requirements.
- Provides a durable base for later beatmap leaderboard and user stats projections.

**Cons**

- More orchestration than Option A.
- Requires precise transaction and idempotency design around current row replacement and duplicate worker claims.
- Requires new completion signal infrastructure or adapter.

**Assessment**

- Effort: L
- Risk: Medium
- Recommended design direction for the next phase.

## Missing Components By Boundary

### Domain

- `PerformanceCalculation` model with id, score id, state, current/historical marker, PP, star rating, calculator version, formula profile, beatmap file attachment identity, unavailable reason, timestamps.
- `PerformanceCalculationState` values: `queued`, `fetching_file`, `calculating`, `completed`, `unavailable`, `superseded`.
- `FormulaProfile` value/policy scoped by playstyle.
- `PerformanceEligibilityPolicy` for Wave 2 ranked-only eligibility.
- `PerformanceProvenance` value object for calculator version, formula profile, beatmap file attachment id/checksum.
- `PerformanceRecalculationBatch` and `PerformanceRecalculationWorkItem` domain models.

### Command Use-Cases

- Request current performance calculation for one score.
- Claim and execute one calculation request in worker.
- Mark calculation `fetching_file`, `calculating`, `completed`, `unavailable`, or `superseded`.
- Create recalculation batch/work items from filters and candidate reasons.
- Process recalculation work in bounded chunks and release stale claims.

### Query Use-Cases

- Read current performance for stable submit response.
- Wait for Performance Completion Signal, then re-read current performance.
- Select recalculation candidates and dry-run reason breakdown.
- Report batch progress for CLI output.

### Repositories

- Command repository for performance rows and atomic claim/current replacement.
- Query repository for current performance and candidate selection.
- Command/query repositories for recalculation batches and work items.
- In-memory implementations for unit tests.
- SQLAlchemy implementations and mapping helpers.

### Infrastructure

- Completion signal interface and production implementation.
  - Candidate: Valkey pub/sub or lightweight key notification abstraction.
  - Constraint: lost signal must not corrupt semantics because DB re-read is source of truth.
- Calculator adapter wrapping `rosu-pp-py`.
  - It should expose Athena-owned input/result dataclasses so `rosu-pp-py` objects do not leak into domain or transports.
- Optional calculator safety checks for suspicious/heavy beatmaps.

### Transport

- Stable submit mapper must format PP as nearest integer when current performance is completed.
- It must leave `pp:0` for unavailable or out-of-scope.
- It must not expose unavailable reasons or calculator diagnostics to stable clients.

### Composition

- App provider wiring for PP request, bounded wait/read service, completion signal, and stable submit integration.
- Worker provider wiring for calculator adapter, blob read service, beatmap file access, and performance job use-cases.
- Test provider overrides/in-memory graph updates.

### CLI

- New Typer command group for PP recalculation.
- Dry-run mode for candidate counts and reason breakdown.
- Execute mode that creates durable work and wakes worker processing.
- Filters: score id, beatmap id, user id, ruleset, limit.
- Explicit full-scope flag for all-candidate/profile migration runs.
- Explicit include-unavailable option.

### Database / Migration

- `score_performance_calculations` table.
  - Needs score foreign key, state, current marker or current pointer strategy, PP decimal, star rating decimal, calculator version, formula profile, beatmap file attachment reference, unavailable reason, timestamps.
  - Needs constraint/index for at most one current calculation per score.
  - Needs indexes for score id, state, current, provenance, candidate selection.
- `performance_recalculation_batches` table.
  - Stores filters, reason breakdown/profile/calculator target, status/progress, timestamps.
- `performance_recalculation_work_items` table.
  - Stores batch id, score id, reason, state, claim owner/deadline/attempts, timestamps.

## Complexity And Risk

- Effort: L (1-2 weeks)
  - Multiple layers are touched: domain, repositories, Alembic, command/query use-cases, taskiq jobs, composition, stable mapper, CLI, tests.
- Risk: Medium
  - Existing architecture provides strong patterns, but duplicate worker execution, current-row replacement, completion signal loss, and large recalculation batch recovery require careful design.
- External dependency risk: Medium
  - `rosu-pp-py` is the selected calculator direction, but API, binary wheels for Python 3.14, and typing quality must be verified before implementation.
- Operational risk: Medium
  - Large profile migration needs durable work and bounded chunk processing; queue-only execution is not sufficient.

## Research Needed For Design Phase

1. `rosu-pp-py` current API and version policy
   - Confirm install name, latest stable version, Python 3.14 wheel availability, and `Beatmap` / `Performance` / `ScoreState` API.
   - Confirm whether the package is typed; if not, decide local `typings/` stub strategy before strict basedpyright work.
2. Calculator input mapping
   - Confirm exact mapping from Athena `Ruleset`, `ModCombination`, hit counts, combo, passed/perfect, and accuracy to `rosu-pp-py`.
   - Confirm mania/taiko/catch score state details and what fields are required.
3. Beatmap file handling
   - Decide whether worker requests `.osu` file through beatmap resolver, beatmap command repository, or query repository + explicit file fetch wake-up.
   - Define unavailable vs still pending when file fetch fails or file body is missing.
4. Current-row strategy
   - Choose between partial unique index on `is_current`, separate current pointer table, or score-level current performance id.
   - Need atomic replacement so old current remains available until replacement is finalized.
5. Completion signal
   - Decide production abstraction and implementation, likely Valkey-based.
   - Define timeout behavior, lost-signal fallback, and test double.
6. Recalculation batch claiming
   - Define claim timeout, attempt limit, stale claim recovery, chunk size, and progress states.
   - Ensure multiple workers can process without duplicate current writes.
7. CLI composition
   - Decide whether CLI creates an app/worker-like Dishka container or calls a smaller operator composition entrypoint.
   - Ensure CLI does not calculate PP and does not bypass repository/use-case boundaries.
8. Configuration
   - Decide how active calculator version, bounded wait seconds, formula profiles by playstyle, recalculation chunk size, and signal timeout are configured.
   - Any `AppConfig` / project config changes require explicit approval.

## Recommendations For Design Phase

1. Use Option C as the primary design:
   - Minimal score submit extension for request/wait/read response.
   - New performance subsystem for calculation, persistence, provenance, and recalculation.
2. Keep Score and Performance Calculation separate:
   - Do not add `scores.pp`.
   - Do not store canonical PP in `score_submissions.result_snapshot`.
3. Model eligibility explicitly:
   - Wave 2 eligibility: `score.passed=True`, playstyle vanilla, and beatmap status at submission/current policy awards ranked PP.
   - Loved / Qualified / failed scores remain stored scores without performance rows.
4. Make durable persistence the source of truth:
   - DB current performance row is source of truth for PP.
   - DB batch/work items are source of truth for recalculation progress.
   - Completion signal and taskiq queue are wake/wait optimizations only.
5. Preserve retry semantics:
   - Same fingerprint retry binds to existing submission/score and reads current performance.
   - Pending performance returns stable retryable `error: yes`.
   - Completed performance returns stable completed response with rounded PP.
   - Unavailable performance returns completed accepted response with `pp:0`.
6. Add tests at the same boundaries as existing Wave 1:
   - Domain policy tests for eligibility/provenance/state transitions.
   - In-memory repository tests for current/superseded behavior.
   - SQLAlchemy model/migration tests for constraints and indexes.
   - Use-case tests for duplicate request, pending/completed/unavailable response paths.
   - Job adapter tests matching beatmap fetch patterns.
   - CLI dry-run/execute tests with typed fakes.

---

## Design Discovery Update 2026-06-16

### Summary

- **Feature**: `score-pp-calculation`
- **Discovery Scope**: Complex Integration
- **Key Findings**:
  - `rosu-pp-py` 4.0.2 is the selected calculator package and its upstream repository includes `rosu_pp_py.pyi`, so the design can use a typed adapter boundary instead of leaking untyped objects into services.
  - Existing score submission already owns retry idempotency and duplicate online/replay checksum rejection; PP logic must compose responses from existing score plus current Performance Calculation without changing those rejection rules.
  - Durable recalculation must be DB-backed because taskiq wake-up signals and completion signals are optimizations, not sources of truth.

### Research Log

#### rosu-pp-py API and type boundary

- **Context**: The design needs a concrete calculator dependency while preserving Athena's domain and transport independence.
- **Sources Consulted**:
  - `https://github.com/MaxOhn/rosu-pp-py/blob/main/pyproject.toml`
  - `https://github.com/MaxOhn/rosu-pp-py/blob/main/rosu_pp_py.pyi`
  - `https://pypi.org/project/rosu-pp-py/`
- **Findings**:
  - Upstream project metadata declares package name `rosu-pp-py`, version `4.0.2`, and Python `>=3.11`.
  - The stub file exposes `Beatmap`, `Performance`, `ScoreState`, `GameMode`, `PerformanceAttributes`, and `DifficultyAttributes`.
  - `Beatmap` can parse `.osu` content from bytes/content, and `Performance` returns PP plus difficulty attributes including stars.
  - `Beatmap.is_suspicious()` exists and should be surfaced through Athena's adapter as an unavailable reason rather than letting heavy maps exhaust workers.
- **Implications**:
  - Design uses `RosuPerformanceCalculator` as an infrastructure adapter behind an Athena-owned `PerformanceCalculator` Protocol.
  - The dependency is not added by this design document. Implementation still needs explicit approval before editing `pyproject.toml` and `uv.lock`.

#### Current code integration points

- **Context**: The design must fit existing score submission, worker, repository, and CLI boundaries.
- **Sources Consulted**:
  - `src/osu_server/services/commands/scores/process_submission.py`
  - `src/osu_server/services/commands/scores/submit_score.py`
  - `src/osu_server/transports/stable/web_legacy/mappers/score_submit.py`
  - `src/osu_server/repositories/interfaces/unit_of_work.py`
  - `src/osu_server/jobs/beatmap_fetch.py`
  - `src/athena_cli/main.py`
- **Findings**:
  - `ProcessScoreSubmissionUseCase` is already broad and must not absorb calculator execution.
  - `SubmitScoreUseCase` creates the accepted Score inside a UoW and is the correct durable seam for existing duplicate behavior.
  - Job adapters already resolve use-cases from taskiq state and fail observably if runtime state is missing.
  - CLI is Typer-based and currently exposes management command groups only; PP recalculation can be added as a new command group.
- **Implications**:
  - Design chooses a hybrid boundary: minimal score submit extension plus a new performance subsystem.
  - Score submission requests calculation and waits/read current performance; worker owns actual calculation.
  - CLI creates recalculation batch/work only and never imports calculator adapters.

### Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
| --- | --- | --- | --- | --- |
| Extend score submission only | Add PP behavior directly to existing score submit flow | Small initial surface | Bloats submit use-case and weakens PP provenance ownership | Rejected |
| Independent performance subsystem only | Keep PP entirely separate from submit | Clean boundary | Stable bounded wait response becomes awkward without submit integration | Partially accepted |
| Hybrid subsystem | Submit requests/waits/reads; performance subsystem calculates and persists | Preserves retry semantics and clean PP ownership | Requires explicit orchestration contracts | Selected |

### Design Decisions

#### Decision: Performance Calculation is a separate score-owned subsystem

- **Context**: Requirements require current/historical PP, provenance, stale detection, and future leaderboard/stats reuse.
- **Alternatives Considered**:
  1. Add `pp` and `stars` to `scores`.
  2. Store PP in `score_submissions.result_snapshot`.
  3. Store PP in `score_performance_calculations` with a current marker and history.
- **Selected Approach**: Use `score_performance_calculations` as canonical PP storage; Score remains gameplay source of truth.
- **Rationale**: This matches the glossary and keeps retry response, recalculation, leaderboard, and stats aligned on one source.
- **Trade-offs**: Requires additional table, repository, and UoW work.
- **Follow-up**: Implementation must enforce at most one current calculation per score.

#### Decision: Durable recalculation batches own large backfills

- **Context**: Profile changes may require all eligible scores to converge to a new Formula Profile.
- **Alternatives Considered**:
  1. CLI loops over scores and calculates inline.
  2. CLI enqueues one task per score without durable batch state.
  3. CLI creates DB batch/work items and wakes worker processing.
- **Selected Approach**: DB batch/work items are source of truth; taskiq only wakes processors.
- **Rationale**: This survives lost queue messages and worker crashes and supports progress reporting.
- **Trade-offs**: Adds batch/work schema and stale claim handling.
- **Follow-up**: Tasks should define claim timeout and chunk size as configuration.

#### Decision: Completion signal is an optimization

- **Context**: Stable submit needs a 5-10 second bounded wait but must scale with multiple app/worker processes.
- **Alternatives Considered**:
  1. Poll the database until timeout.
  2. Treat task result as source of truth.
  3. Wait on a completion signal and always re-read DB before response.
- **Selected Approach**: Use `PerformanceCompletionSignal` for wait optimization; DB current row remains source of truth.
- **Rationale**: Lost signals only cause retryable timeout, not incorrect PP.
- **Trade-offs**: Needs signal abstraction and a test double.
- **Follow-up**: Implement Valkey-backed signal only after confirming the exact `valkey-glide` pub/sub shape.

### Risks & Mitigations

- `rosu-pp-py` wheel or type behavior differs from design assumptions — isolate through adapter and add an implementation spike before broad integration.
- Current-row race can create conflicting current PP — enforce DB uniqueness and perform current replacement in one command transaction.
- Bounded wait can hide worker starvation — expose structured logs and CLI batch progress; return retryable response on timeout.
- Large profile migrations can overwhelm workers — process recalculation work in bounded chunks with stale claim recovery.

### References

- [rosu-pp-py project metadata](https://github.com/MaxOhn/rosu-pp-py/blob/main/pyproject.toml)
- [rosu-pp-py type stubs](https://github.com/MaxOhn/rosu-pp-py/blob/main/rosu_pp_py.pyi)
- [rosu-pp-py PyPI](https://pypi.org/project/rosu-pp-py/)
