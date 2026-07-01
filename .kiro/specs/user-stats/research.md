# Research & Design Decisions

## Summary

- **Feature**: `user-stats`
- **Discovery Scope**: Extension
- **Key Findings**:
  - Stable `USER_STATS` builder already exists, but login currently sends placeholder stats.
  - `ft` is parsed and passed through score submission input, but `Score` and `scores` persistence do not retain it.
  - `score-pp-calculation` owns current Performance Calculation and explicitly allows future stats features to read current PP without moving PP onto Score.
  - `beatmap-leaderboards` reserves PP-priority best performance ownership for `user-stats`.

## Research Log

### Stable USER_STATS integration

- **Context**: Login and stats request must emit current stats without changing the stable wire shape.
- **Sources Consulted**:
  - `src/osu_server/transports/stable/bancho/protocol/s2c/login.py`
  - `src/osu_server/transports/stable/bancho/workflows/presence_roster.py`
  - `.kiro/specs/presence-stats-struct-fixtures/requirements.md`
  - `.kiro/specs/presence-stats-struct-fixtures/design.md`
- **Findings**:
  - `user_stats()` already builds packet id `USER_STATS` with `ranked_score`, `accuracy`, `play_count`, `total_score`, `rank`, and `pp`.
  - PP is clamped to `uint16` in the existing builder.
  - Login roster currently sends default zeros for the logged-in user.
  - The struct fixture spec fixes the builder signature and nested `StatusUpdate` wire shape.
- **Implications**:
  - UserStats implementation should feed real values into the existing builder rather than changing packet layout.
  - Compatibility tests should assert byte-level shape remains stable while values change.

### Stats request handler gap

- **Context**: `ClientPacketID.STATS_REQUEST` exists but no handler currently responds to it.
- **Sources Consulted**:
  - `src/osu_server/transports/stable/bancho/protocol/enums.py`
  - `src/osu_server/transports/stable/bancho/dispatch.py`
  - `src/osu_server/transports/stable/bancho/handlers/presence.py`
  - `src/osu_server/transports/stable/bancho/protocol/c2s/presence.py`
- **Findings**:
  - `STATS_REQUEST` is a quiet C2S packet id, so the dispatcher already classifies it as low-noise traffic.
  - No `@handles(ClientPacketID.STATS_REQUEST)` handler is registered.
  - Presence request parsing already has an `IntList` parser pattern and canonical payload validation.
- **Implications**:
  - A new stats handler should follow the `PresenceHandlers` pattern and enqueue `USER_STATS` packets.
  - Implementation must add focused protocol fixture coverage before relying on the assumed stats request payload shape.

### Score timing persistence gap

- **Context**: Play time cannot be reconstructed precisely if submit-time timing is discarded.
- **Sources Consulted**:
  - `.kiro/specs/score-ingestion/requirements.md`
  - `src/osu_server/infrastructure/parsers/multipart_parser.py`
  - `src/osu_server/transports/stable/web_legacy/mappers/score_submit.py`
  - `src/osu_server/services/commands/scores/process_submission.py`
  - `src/osu_server/domain/scores/score.py`
  - `src/osu_server/repositories/sqlalchemy/models/score.py`
  - `src/osu_server/repositories/sqlalchemy/commands/scores.py`
- **Findings**:
  - score-ingestion requirement 12 already requires storing `x` and `ft`.
  - `fail_time_ms` is parsed and included in submission input and fingerprint behavior.
  - The `Score` domain model and `ScoreModel` do not include `fail_time_ms` or `play_time_seconds`.
- **Implications**:
  - Timing persistence is a prerequisite task before reliable UserStats play time.
  - The implementation should extend the existing score command persistence path rather than adding a separate timing record.

### Current PP source and best performance ownership

- **Context**: UserStats needs PP, best performance ordering, and global rank without taking over PP calculation.
- **Sources Consulted**:
  - `.kiro/specs/score-pp-calculation/requirements.md`
  - `.kiro/specs/score-pp-calculation/design.md`
  - `src/osu_server/domain/scores/performance.py`
  - `src/osu_server/repositories/interfaces/queries/score_performance.py`
  - `src/osu_server/repositories/sqlalchemy/models/score_performance.py`
  - `.kiro/specs/beatmap-leaderboards/design.md`
  - `.kiro/specs/beatmap-leaderboards/research.md`
- **Findings**:
  - Performance Calculation is the canonical current PP storage.
  - Existing `ScorePerformanceQueryRepository` reads current PP for individual scores and selects recalculation candidates.
  - beatmap-leaderboards explicitly leaves `beatmap_performance_bests` to user-stats.
- **Implications**:
  - UserStats should own PP-priority best performance projection and current aggregate policy.
  - UserStats must not execute calculator logic or mutate Performance Calculation state.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Live aggregate query only | Compute every value from Score and current Performance Calculation on each stats read | Minimal schema | Login and stats request can become expensive; does not satisfy reserved performance best projection ownership | Rejected as the primary design |
| Current read model projection | Persist PP-priority best performance rows and compute current stats from that read model plus score aggregates | Clear ownership, stable query shape, aligns with roadmap | Requires projection update and rebuild tasks | Selected |
| Full current stats snapshot | Persist fully materialized PP, accuracy, rank, score totals, and play time per user | Fast reads | Rank and score totals can go stale unless every score and performance transition updates it | Deferred until load proves need |

## Design Decisions

### Decision: Persist submit timing on Score

- **Context**: `ft` arrives with score submission and score-ingestion already expects it to be stored.
- **Alternatives Considered**:
  1. Store timing in a separate score metadata table.
  2. Add nullable timing fields directly to Score.
- **Selected Approach**: Add nullable timing fields to Score and the `scores` table.
- **Rationale**: Timing is a property of the accepted score attempt and should travel with command and query score models.
- **Trade-offs**: Existing score factories and repository mappings must be updated.
- **Follow-up**: Implementation should define exact derivation for passed score play time and failed score fail time conversion.

### Decision: UserStats owns PP-priority best performance projection

- **Context**: Weighted PP and accuracy require a user-level best performance set.
- **Alternatives Considered**:
  1. Reuse Beatmap Leaderboard user best rows.
  2. Build `beatmap_performance_bests` for PP-priority bests.
  3. Sort all current Performance Calculations on every read.
- **Selected Approach**: Create `beatmap_performance_bests` owned by user-stats.
- **Rationale**: Beatmap leaderboards are score-priority, while UserStats PP is PP-priority. A separate projection avoids mixed ownership.
- **Trade-offs**: Projection update and rebuild workflows are required.
- **Follow-up**: Recalculation flows must refresh affected best rows without changing performance rows.

### Decision: Initial bonus PP is explicit zero unless verified

- **Context**: Official-like weighting is known, but exact bonus PP compatibility is not yet verified in this repo.
- **Alternatives Considered**:
  1. Guess a bonus formula from memory.
  2. Leave bonus PP implicit.
  3. Use weighted PP only and record bonus policy as zero until verified.
- **Selected Approach**: Initial bonus PP policy is zero and explicitly documented in the domain policy.
- **Rationale**: This avoids hidden compatibility drift and satisfies in-game current stats without guessing external behavior.
- **Trade-offs**: Displayed PP may be lower than official osu! if official bonus would apply.
- **Follow-up**: A future compatibility task can replace the bonus policy after protocol or official behavior evidence is captured.

### Decision: Stable level is derived from total score display, not a new wire field

- **Context**: Stable `USER_STATS` has `total_score` but no separate level field.
- **Alternatives Considered**:
  1. Add a server-only level field to UserStats result.
  2. Let stable client derive Lv from `total_score`.
- **Selected Approach**: Keep stable Lv display driven by `total_score`; do not invent a stable wire level field.
- **Rationale**: Preserves stable packet compatibility and answers the requested Lv display through the existing client behavior.
- **Trade-offs**: First implementation will not expose a separate Web/API level value.
- **Follow-up**: Web profile specs can add server-side level formatting later if needed.

## Risks & Mitigations

- Stats request payload shape may differ from the assumed `IntList` pattern — add focused protocol fixture tests before enabling the handler.
- Global rank query can become expensive as users grow — index the current best projection and keep historical snapshots out of scope until `user-ranking`.
- Performance recalculation can leave best projection stale — include rebuild and refresh workflows as explicit tasks.
- Timing derivation can overstate play time if beatmap metadata is missing or stale — keep `play_time_seconds` nullable and record source policy.

## References

- `.kiro/specs/user-stats/brief.md` — discovery brief and scope.
- `.kiro/specs/score-ingestion/requirements.md` — existing `x` and `ft` storage requirement.
- `.kiro/specs/score-pp-calculation/design.md` — current Performance Calculation ownership.
- `.kiro/specs/beatmap-leaderboards/research.md` — PP-priority performance best boundary reserved for user-stats.
- `src/osu_server/transports/stable/bancho/protocol/s2c/login.py` — stable `USER_STATS` builder.
