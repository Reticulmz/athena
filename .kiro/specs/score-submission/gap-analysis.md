# Gap Analysis: Score Submission

**Feature**: score-submission
**Analysis Date**: 2026-06-11
**Status**: tasks-generated (実装前のコードベース再確認)

## Executive Summary

score-submission は Athena に対する初の大規模な gameplay data pipeline であり、以下の主要 gap が存在します:

- **Missing Components**: score domain models, repositories, services, worker jobs, transport endpoints が全て未実装
- **Existing Foundation**: domain/repository/service/job パターン、blob storage、beatmap mirror、worker runtime は確立済み
- **Implementation Approach**: 既存パターンに従った新規コンポーネント作成 (Option B) が最適
- **Effort**: L (1-2 weeks) — 複数レイヤーにまたがる統合、PP calculator 導入、projection 設計が必要
- **Risk**: Medium — 既存パターンは明確だが、stable compatibility 検証と worker bounded wait が課題

## 1. Current State Investigation

### 1.1 Existing Athena Architecture

| Component | Status | Location | Pattern |
|-----------|--------|----------|---------|
| Web legacy transport | ✅ Exists | `transports/web_legacy/` | Starlette handler + parser + formatter |
| Domain models | ✅ Exists | `domain/` | `@dataclass(slots=True)` with business logic |
| Repository interfaces | ✅ Exists | `repositories/interfaces/` | Protocol-based contracts |
| SQLAlchemy repositories | ✅ Exists | `repositories/sqlalchemy/` | Async SQLAlchemy 2.0 |
| In-memory test doubles | ✅ Exists | `repositories/memory/` | Protocol-compliant fakes |
| Service layer | ✅ Exists | `services/` | Use-case orchestration |
| Worker runtime | ✅ Exists | `worker.py` | taskiq + ListQueueBroker |
| Job pattern | ✅ Exists | `jobs/` | taskiq job with execute() method |
| Blob storage | ✅ Exists | `services/blob_storage_service.py` | SHA-256 dedup + backend abstraction |
| Beatmap mirror | ✅ Exists | `services/beatmap_mirror_service.py` | Metadata + file fetch orchestration |

### 1.2 Reference Implementation Patterns

主要な osu! server 実装からのパターン比較:

#### 1.2.1 bancho.py (Akatsuki) Patterns

| Pattern | bancho.py | Athena Equivalent |
|---------|-----------|-------------------|
| Score table schema | `scores` with `mode`, `status`, `map_md5`, hit counts, `online_checksum` | 同様の schema に `ruleset`, `playstyle`, `category` axis 追加 |
| Submit endpoint | `/web/osu-submit-modular-selector.php` in `api/domains/osu.py` | `transports/web_legacy/score_submission.py` |
| Multipart parsing | `parse_form_data_score_params()` で duplicate `score` part を分離 | `ScoreSubmissionParser` で同様の処理 |
| Authorization | `authenticate_player_session()` で username + pw_md5 検証 | `LegacyAuthService` + active session check |
| Replay storage | `.data/osr/{score_id}.osr` にファイル保存 | `BlobStorageService` 経由で blob backend に保存 |
| PP calculation | `app.usecases.performance` で rosu-pp 呼び出し | `PerformanceService` (worker) で同様 |
| Score validation | `Score.calc_accuracy()`, `Score.calc_grade()` で server-side 再計算 | `ScoreValidationService` で同様 |
| Best score update | `scores_repo.update()` で status を BEST に更新 | `ScoreBestProjection` table で明示的に管理 |
| Stats update | `stats_repo.update()` で user stats を即座更新 | `UserStatsService` (worker) で projection 更新 |
| Leaderboard | `scores_repo.fetch_many()` で map_md5 + mode + status でクエリ | `BeatmapLeaderboardService` で projection table から取得 |

#### 1.2.2 osuRipple/lets (Cython) Patterns

Research.md より:

| Pattern | lets | Athena Approach |
|---------|------|-----------------|
| Submit handler | `submitModularHandler.pyx` で parsing と validation | `ScoreSubmissionService` で同様の orchestration |
| Score payload decrypt | AES decrypt with `osuver` key selection | `ScoreSubmissionParser` で同様 |
| Duplicate detection | checksum + lock mechanism | `score_submissions.fingerprint` unique constraint |
| Session validation | Active session absence → retryable response | Athena では terminal reject (stricter) |
| Failed play handling | `quit_ or failed` → `failTime // 1000` を playTime に | `ft` milliseconds → seconds 変換、sanity limits 適用 |
| Scoreboard query | `scores` table で `play_mode` と relax flag を条件 | `beatmap_leaderboard_entries` projection で同様 |

#### 1.2.3 osuTitanic/deck (Modern Python) Patterns

Research.md より:

| Pattern | deck | Athena Approach |
|---------|------|-----------------|
| Submit route | `app/routes/web/scoring.py` で FastAPI handler | Starlette handler (Athena の web_legacy 慣習) |
| Form parsing | `form.getlist('score')` で duplicate part 取得 | `ScoreSubmissionParser` で order-aware parsing |
| Score helper | `app/helpers/score.py` で validation と calculation | `ScoreValidationService` で同様 |
| rosu-pp-py usage | `rosu-pp-py==4.0.2` を requirements.txt に | Worker dependency として同様に導入 |
| Beatmap file | `Beatmap.is_suspicious()` で heavy beatmap 検出 | `PerformanceService` で同様の safety check |
| Response format | Chart text with `|` と newline で構成 | `ScoreSubmissionFormatter` で stable-compatible 生成 |

#### 1.2.4 Implementation Pattern Consensus

複数実装で一致しているパターン:

1. **Duplicate `score` multipart**: 全実装が first part を encrypted payload、second part を replay binary として扱う
2. **AES key selection**: `osuver` presence で key を切り替える実装が主流
3. **Score checksum**: `online_checksum` や score checksum による dedupe は広く採用
4. **Failed play storage**: Failed play も score record として保存し、leaderboard/PP から除外
5. **Server-side validation**: Client-reported accuracy/grade を server-side で再計算
6. **rosu-pp**: rosu-pp (または rosu-pp-py) が PP calculator の事実上の標準

### 1.3 Key Architectural Differences

Athena は bancho.py と以下の点で設計が異なる:

| Aspect | bancho.py | Athena |
|--------|-----------|--------|
| プロセス構成 | Single process (FastAPI) | App (transport) + Worker (heavy processing) 分離 |
| Submit 処理 | 同期的に全処理完了 | App は保存 + enqueue、Worker が PP/projection 更新 |
| Best score 管理 | status column で BEST フラグ | 専用 projection table |
| Rank 管理 | stats table + on-demand `COUNT(*)` | `user_rank_projections` snapshot + rebuild job |
| Repository 抽象 | 直接 SQLAlchemy import | Protocol interface + memory/sqlalchemy 実装分離 |
| Test double | Mock or fixture | In-memory repository (protocol-compliant) |
| Blob storage | File system 直接書き込み | `BlobStorageService` + backend abstraction |
| PP calculation | Submit endpoint 内で同期実行 | Worker job で非同期実行 |

## 2. Requirements Feasibility Analysis

### 2.1 Technical Needs from Requirements

| Requirement Area | Technical Components Needed | Existing Support | Gap |
|------------------|----------------------------|------------------|-----|
| Stable submit endpoint (R1) | Transport handler, parser, formatter | ✅ Web legacy pattern | ❌ Score submission specific endpoint |
| Multipart compatibility (R2) | Duplicate field parser, AES decrypt, field redaction | ✅ Starlette form data | ❌ Order-preserving parser, crypto utils |
| Authorization (R3) | Password check, session lookup, payload identity match | ✅ Auth service pattern | ❌ Decrypted payload validation |
| Gameplay persistence (R4) | Score domain, repository, replay attachment | ❌ None | ❌ All new |
| Idempotent retry (R5) | Submission fingerprint, state tracking, result snapshot | ❌ None | ❌ All new |
| Bounded processing (R6) | Worker job, bounded wait, result kinds | ✅ Worker pattern | ❌ Score processing job, wait logic |
| Beatmap eligibility (R7) | Status rules, category mapping, effect policy | ✅ Beatmap status in mirror | ❌ Score effect policy |
| Score validation (R8) | Accuracy/grade calc, hit count validation | ❌ None | ❌ Validation service |
| PP calculation (R9) | rosu-pp-py, provenance, .osu file dependency | ❌ None | ❌ Performance service + dependency |
| Leaderboard rows (R10) | Score projection, row ordering, personal state | ❌ None | ❌ Leaderboard service + projection |
| Best score (R11) | Best tracking, replacement logic | ❌ None | ❌ Best projection |
| User stats (R12) | Stats per ruleset/playstyle/category | ❌ None | ❌ Stats domain + repository |
| Failed play (R13) | Failed storage, playtime from ft, exclusion logic | ❌ None | ❌ Failed play handling in effect policy |
| .osu availability (R14) | Prefetch hooks, bounded wait | ✅ Beatmap mirror + fetch job | ❌ Hooks in getscores/status/submit |
| Security/privacy (R15) | Redaction, diagnostics without secrets | ✅ structlog pattern | ❌ Parser redaction policy |

### 2.2 Missing Capabilities

**Domain Models**:
- Score, ScoreSubmission, PerformanceCalculation, ScoreBestProjection, UserStats, UserRank
- ScoreCategory, Playstyle, ScoreStatus, SubmissionState, ResultKind value objects

**Repositories**:
- ScoreRepository (interface + sqlalchemy + memory)
- UserStatsRepository (interface + sqlalchemy + memory)
- UserRankRepository (interface + sqlalchemy + memory)

**Services**:
- ScoreSubmissionService (authorization, dedupe, replay, enqueue, bounded wait)
- ScoreProcessingService (worker finalization)
- ScoreValidationService (accuracy, grade, hit count validation)
- ScoreEffectPolicy (status → effects mapping)
- PerformanceService (rosu-pp-py wrapper)
- BeatmapLeaderboardService (getscores rows)
- UserStatsService (stats updates)
- UserRankProjectionService (rank rebuild)

**Transport**:
- ScoreSubmissionParser (multipart, AES, redaction)
- ScoreSubmissionFormatter (stable response shapes)
- Score submission endpoint handler

**Jobs**:
- ProcessScoreSubmissionJob (worker entry point)
- RebuildUserRankProjectionsJob (periodic or on-demand)

**Database**:
- Migration: scores, score_submissions, score_replay_attachments, score_performance_calculations, score_best_projections, beatmap_leaderboard_entries, user_stats, user_rank_projections
- Indexes: score descending, user+beatmap best lookup, rank ordering

**External Dependency**:
- rosu-pp-py (PP calculator, Python bindings to Rust library)

### 2.3 Existing Constraints

| Constraint | Impact |
|------------|--------|
| PostgreSQL + asyncpg only | Score schema must be PostgreSQL-compatible; no SQLite unit tests with real DB |
| Protocol-based repositories | All repositories need interface + sqlalchemy + memory implementations |
| No Pydantic in domain | Score domain は `@dataclass` で実装 |
| SQLAlchemy 2.0 async | Async repository methods, `async with session.begin()` |
| Import-linter enforcement | Layer violations are CI failures; services cannot import SQLAlchemy models |
| basedpyright strict | All new code must type-check with strict mode |
| TDD expected | Tests before implementation (per tech steering) |

### 2.4 Complexity Signals

- **Algorithmic**: Accuracy/grade calculation は ruleset-specific だが、既存実装パターンを参考にできる
- **External Integration**: rosu-pp-py dependency + .osu file dependency の coordination
- **Workflows**: Submit → store → enqueue → worker processing → finalization → projection update の multi-step flow
- **Consistency**: Score, best, leaderboard, stats, rank projections の間の整合性維持

## 3. Implementation Approach Options

### Option A: Extend Existing Components ❌ Not Viable

**Rationale**: Score submission は既存コンポーネントとは独立した新しいドメインである。

- Getscores は header-only であり、score row provider を追加する必要があるが、これは score repository に依存する新機能
- Beatmap mirror は metadata/file fetch を所有し、score submission はその **呼び出し側** である
- Worker.py は汎用エントリポイントであり、新しい job を register するだけ

**Trade-offs**:
- ✅ 新規ファイルが少ない
- ❌ 責任境界が不明確になる
- ❌ Score submission の複雑さを既存 service に押し込むことになる

**Verdict**: 不採用。Score submission は独立した feature として実装すべき。

### Option B: Create New Components ✅ Recommended

**Rationale**: Score submission は新しいドメインであり、明確な責任境界を持つ新規コンポーネント群として実装するのが Athena の既存パターンに合致する。

**New Components**:
- `domain/score.py`, `domain/score_submission.py`, `domain/user_stats.py`, `domain/user_rank.py`
- `repositories/interfaces/score_repository.py`, `user_stats_repository.py`, `user_rank_repository.py`
- `repositories/sqlalchemy/score_repository.py`, `user_stats_repository.py`, `user_rank_repository.py`
- `repositories/memory/score_repository.py`, `user_stats_repository.py`, `user_rank_repository.py`
- `services/score_submission_service.py`, `score_processing_service.py`, `score_validation_service.py`, `score_effect_policy.py`, `performance_service.py`, `beatmap_leaderboard_service.py`, `user_stats_service.py`, `user_rank_projection_service.py`
- `transports/web_legacy/score_submission.py`, `score_submission_parser.py`, `score_submission_formatter.py`
- `jobs/score_processing.py`, `user_rank_rebuild.py`
- Migration file

**Integration Points**:
- `transports/web_legacy/getscores.py` を拡張して `BeatmapLeaderboardService` を呼び出す
- `services/legacy_getscores_service.py` に `.osu` prefetch hook を追加
- `transports/bancho/handlers/status.py` に `.osu` prefetch hook を追加
- `worker.py` に新 job を register
- `config.py` に submit limits/timeouts を追加

**Trade-offs**:
- ✅ 明確な責任境界
- ✅ テストしやすい (in-memory repositories で独立テスト可能)
- ✅ 既存コードへの影響が最小限
- ✅ 将来の RX/AP 拡張も同じパターンで追加可能
- ❌ ファイル数が多い (しかし構造は明確)

**Verdict**: 採用。Athena の layered architecture と repository pattern に最も合致する。

### Option C: Hybrid Approach (Phased) 🤔 Alternative

**Rationale**: 初期は最小限の実装で動作確認し、後から projection や rank を追加する。

**Phase 1**: Submit endpoint + score storage + worker skeleton (PP なし、projection なし)
**Phase 2**: PP calculation + performance provenance
**Phase 3**: Best projection + leaderboard
**Phase 4**: User stats + rank projection

**Trade-offs**:
- ✅ 段階的に検証可能
- ✅ 各 phase で動作確認できる
- ❌ Phase 間の境界が不明瞭になりやすい
- ❌ Design では全体を設計済みなので、phased implementation は task 分割で対応すべき

**Verdict**: 保留。Implementation task 分割で対応する方が適切。

## 4. Implementation Complexity & Risk

### 4.1 Effort Estimate

**Size**: L (1-2 weeks)

**Rationale**:
- 新規 domain models: 4 files (score, score_submission, user_stats, user_rank)
- 新規 repositories: 3 interfaces + 3 sqlalchemy + 3 memory = 9 files
- 新規 services: 8 files
- 新規 transport: 3 files (handler, parser, formatter)
- 新規 jobs: 2 files
- Migration: 1 file (8 tables)
- Modified files: 6 files (getscores, legacy_getscores_service, status handler, worker, config, app composition)
- Tests: unit + integration tests for all new components

**Major Work Items**:
1. Schema design + migration (1 day)
2. Domain models + repositories (2 days)
3. Parser + formatter + stable compatibility fixtures (1 day)
4. Services (submission, processing, validation, effect policy) (2 days)
5. Performance service + rosu-pp-py integration (1 day)
6. Projection services (leaderboard, stats, rank) (1.5 days)
7. Worker job + bounded wait (1 day)
8. Integration tests (1 day)
9. Getscores integration + hooks (0.5 day)

### 4.2 Risk Assessment

**Risk Level**: Medium

**High-Risk Areas**:
- **Stable compatibility**: multipart parser と response formatter が実際の stable client と互換性があるか
  - Mitigation: bancho.py/ripple/lets の実装を参考に、captured request fixtures でテスト
- **rosu-pp-py availability**: wheel build や version compatibility
  - Mitigation: worker-only dependency とし、PP failure は score 保存を壊さない設計
- **Bounded wait implementation**: worker completion を app process から観測する実装
  - Mitigation: polling with timeout、処理が pending なら retryable response を返す
- **Projection consistency**: best/leaderboard/stats/rank の間の整合性
  - Mitigation: worker finalization を短い transaction に閉じる、rebuild method を提供

**Medium-Risk Areas**:
- AES decryption と field parsing の正確性
  - Mitigation: bancho.py の実装を参考に、test fixtures で検証
- Score validation logic (accuracy, grade) の ruleset-specific 実装
  - Mitigation: bancho.py の calc_accuracy/calc_grade を参考
- `.osu` file availability の三段構え (getscores, STATUS_CHANGE, submit)
  - Mitigation: 既存 beatmap mirror pattern を使う

**Low-Risk Areas**:
- Repository pattern (既存パターンが明確)
- Service layer orchestration (既存 service pattern を踏襲)
- Worker job pattern (既存 beatmap_fetch job と同様)
- Blob storage (既存 service を再利用)

## 5. Recommendation for Design Phase

### 5.1 Preferred Approach

**Option B: Create New Components** を採用する。

理由:
- Athena の既存 layered architecture に合致
- 責任境界が明確
- テストしやすい
- 既存コードへの影響が最小限
- bancho.py の実装パターンを Athena の構造に適切に翻訳できる

### 5.2 Key Design Decisions to Validate

以下は design.md で既に決定済みだが、実装前に再確認すべき事項:

1. **Duplicate `score` part handling**: parser test fixture で order preservation を検証
2. **Score effect policy**: Loved/Qualified/unranked の projection eligibility を明示
3. **Failed play duration**: `ft` milliseconds → seconds 変換の sanity limit
4. **Rank projection rebuild**: window function による bulk rebuild vs. per-submit cascading update
5. **rosu-pp-py version**: 4.0.2 を採用候補としているが、最新 stable version を確認

### 5.3 Research Items Carried Forward

Design phase で既に調査済みだが、implementation で再確認が必要な項目:

- stable response format の細部 (PP display field の互換性)
- `osuver` による AES key selection (legacy key path の必要性)
- Score checksum uniqueness constraint (compatibility evidence から確認)
- Qualified beatmap の扱い (leaderboard-only か、ranked stats に含めるか)

### 5.4 Implementation Task Structure (Suggestion)

Tasks.md で既に定義済みと思われるが、以下の順序で実装することを推奨:

1. Migration + domain models
2. Repository interfaces + memory implementations
3. SQLAlchemy repositories
4. Parser + formatter (with fixtures)
5. Score effect policy + validation service
6. Submission service (authorization, dedupe, replay, enqueue)
7. Performance service (rosu-pp-py wrapper)
8. Processing service (worker finalization)
9. Projection services (leaderboard, stats, rank)
10. Worker job
11. Transport endpoint
12. Getscores integration
13. Integration tests

## 6. Requirement-to-Asset Map

| Requirement | Existing Assets | Missing Assets | Gap Type |
|-------------|----------------|----------------|----------|
| R1: Stable endpoint scope | Web legacy pattern | Score submit endpoint, parser, formatter | Missing |
| R2: Multipart compatibility | Starlette form data | Order-preserving parser, AES decrypt, redaction | Missing |
| R3: Authorization | Auth service, session store | Decrypted payload validation | Missing |
| R4: Gameplay persistence | Blob storage | Score domain, repository, replay attachment | Missing |
| R5: Idempotent retry | None | Submission fingerprint, state, snapshot | Missing |
| R6: Bounded processing | Worker pattern | Score processing job, bounded wait logic | Missing |
| R7: Beatmap eligibility | Beatmap status | Score effect policy | Missing |
| R8: Score validation | None | Validation service, accuracy/grade calc | Missing |
| R9: PP calculation | None | Performance service, rosu-pp-py | Missing + External |
| R10: Leaderboard rows | Getscores header formatter | Leaderboard service, projection | Missing |
| R11: Best score | None | Best projection, replacement logic | Missing |
| R12: User stats | None | Stats domain, repository, service | Missing |
| R13: Failed play | None | Failed play handling in effect policy | Missing |
| R14: .osu availability | Beatmap mirror, fetch job | Prefetch hooks | Missing |
| R15: Security/privacy | structlog | Parser redaction, credential-safe diagnostics | Missing |

**Gap Summary**:
- Missing: 全ての score submission 固有コンポーネント
- External: rosu-pp-py dependency
- Constraint: PostgreSQL-only, Protocol-based repositories, no Pydantic in domain

## 7. Conclusion

Score submission は Athena の既存 architecture pattern に従って、新規コンポーネント群として実装する (Option B) のが最適です。既存の domain/repository/service/job pattern が確立されているため、これらに従うことで一貫性のある実装が可能です。

bancho.py の実装パターンは参考になりますが、Athena は app/worker プロセス分離、repository abstraction、projection table など、より厳密な構造を持つため、単純な移植ではなく Athena の設計原則に合わせた実装が必要です。

Design.md は既に詳細な設計を提供しており、このギャップ分析は「既存コードベースとの整合性」と「実装時の具体的な作業量」を明確化するものです。
