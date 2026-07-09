# Gap Analysis

## Analysis Summary

- `GET /web/osu-getreplay.php` の success response path は既に query-only として実装され、response status、headers、body の regression test も存在する。
- #37 に必要な accounting metadata、score-scoped Replay View Count、viewer latest activity、duplicate cooldown、activity throttle は現状未実装である。
- 既存の `UnitOfWork` は `scores` と `users` repository を公開しているため、command use-case 側の永続化境界は利用できる。
- 既存の `RateLimiter` は INCR/EXPIRE の counter であり、`viewer_user_id + score_id` や `viewer_user_id` の one-shot TTL marker には専用 port か専用 Valkey adapter が必要である。
- 推奨設計は、既存 `ReplayDownloadQuery` を read-only のまま維持し、success metadata を拡張して、Stable transport から別 command use-case を best-effort で呼ぶ hybrid approach である。

## Document Status

- 対象 feature: `replay-download-accounting`
- Spec language: `ja`
- Requirements phase: `requirements-generated`
- Requirements approval: 未承認
- Gap analysis policy: requirements 未承認のため警告付きで進め、design phase の判断材料として整理する
- Steering context: `.kiro/steering/tech.md`、`.kiro/steering/scaling.md`、`.kiro/steering/roadmap.md`
- Missing steering files: `.kiro/steering/product.md` と `.kiro/steering/structure.md` は未配置

## Current State Investigation

### Replay Download Response Path

- `src/osu_server/transports/stable/web_legacy/replay_download.py`
  - `StableReplayDownloadExchange.respond()` が auth、parse、query、response mapping を順に行う。
  - Auth failure は parser/query を呼ばず empty 401 を返す。
  - Success は `ReplayDownloadQueryResult` の body を `Content-Type: zip`、`Content-Disposition: attachment; filename="replay.osr"` 付きで HTTP 200 にする。
  - Accounting hook は存在しない。
- `src/osu_server/services/queries/scores/replay_download.py`
  - `ReplayDownloadQuery` は read-only workflow として設計されている。
  - Storage missing、hidden score、missing replay、body strategy blocked を branch として返す。
  - `ReplayDownloadQueryResult` は `branch` と `response_body` のみで、`score_id` や `score_owner_user_id` を持たない。
- `src/osu_server/repositories/interfaces/queries/replay_download.py`
  - `ReplayDownloadAvailableReplayCandidate` は `blob_id`、`checksum`、`byte_size` のみを持つ。
  - Accounting metadata に必要な `score_id` と `score_owner_user_id` は返していない。
- `src/osu_server/repositories/sqlalchemy/queries/replay_download.py`
  - SQL query は `ScoreModel.id` を select しているが、candidate へ投影していない。
  - `ScoreModel.user_id` は select していない。
- `tests/unit/services/queries/scores/test_replay_download_query.py`
  - query use-case が replay view update と latest activity update を呼ばないことを明示的に検証している。
- `tests/integration/transports/web_legacy/test_replay_download_endpoint.py`
  - success response の bytes、status、headers を検証している。

### Score And User Persistence

- `src/osu_server/repositories/sqlalchemy/models/score.py`
  - `scores` table に Replay View Count 用 column は存在しない。
  - `ScoreModel` に non-negative count constraint も存在しない。
- `src/osu_server/domain/scores/score.py`
  - `Score` dataclass に replay view count は存在しない。
- `src/osu_server/repositories/interfaces/commands/scores.py`
  - `ScoreCommandRepository` に count increment method は存在しない。
- `src/osu_server/repositories/sqlalchemy/commands/scores.py`
  - create/get/list 系のみで、atomic increment は存在しない。
- `src/osu_server/repositories/memory/commands/scores.py`
  - in-memory command repository も count increment を持たない。
- `src/osu_server/repositories/sqlalchemy/models/user.py`
  - `users` table に latest activity 用 column は存在しない。
- `src/osu_server/domain/identity/users.py`
  - `User` dataclass に latest activity は存在しない。
- `src/osu_server/repositories/interfaces/commands/users.py`
  - `UserCommandRepository` に latest activity touch method は存在しない。

### Transaction And Composition Boundaries

- `src/osu_server/repositories/interfaces/unit_of_work.py`
  - command-side `UnitOfWork` は `scores` と `users` を公開済み。
  - #37 の durable side effect は command use-case から既存 UoW に載せられる。
- `src/osu_server/composition/providers/scores.py`
  - `ReplayDownloadQuery` は `ReplayDownloadBodyStrategy.DIRECT_BLOB_BYTES` で組み立てられている。
  - Accounting command provider は存在しない。
- `src/osu_server/composition/providers/stable_web_legacy.py`
  - `ReplayDownloadHandler` provider は auth、parser、query のみを注入する。
  - Accounting dependency の provider wiring は未実装。

### Temporary State

- `src/osu_server/infrastructure/state/interfaces/rate_limiter.py`
  - 既存 `RateLimiter` は user 単位の counter rate limit interface。
- `src/osu_server/infrastructure/state/valkey/rate_limiter.py`
  - Valkey 実装は `INCR` と `EXPIRE`。最初の1回だけ通す `SET NX EX` 相当の marker ではない。
- `src/osu_server/infrastructure/state/valkey/packet_queue.py`
  - `Script` を使った atomic Valkey operation の前例がある。
- `src/osu_server/infrastructure/state/valkey/stable_user_status_store.py`
  - `ExpirySet` / `ExpiryType` を使った TTL set の前例がある。
- Research Needed:
  - `valkey-glide` の conditional `SET NX EX` API shape は design phase で確認する。
  - API が十分に型安全でない場合は既存 `Script` pattern で one-shot marker を実装する。

## Requirement-to-Asset Map

| Requirement | Existing Assets | Gap |
| --- | --- | --- |
| 1. Accounting Trigger and Response Preservation | `StableReplayDownloadExchange.respond()`、`ReplayDownloadQueryResult`、endpoint integration tests | Missing: success known 後の accounting hook。Missing: accounting failure を response に反映しない best-effort wrapper。Missing: sanitized operator log。Constraint: Issue #36 response bytes/status/headers を変更しない。 |
| 2. Score-Scoped Replay View Count | `ScoreModel`、`Score`、`ScoreCommandRepository`、UoW `scores` | Missing: `scores.replay_view_count` integer not null default 0。Missing: Alembic migration/backfill/check constraint。Missing: command repository increment。Missing: query/read exposure policy。Constraint: durable per-download event table は作らない。 |
| 3. Self-View and Duplicate View Policy | Authenticated viewer id、score owner id は DB に存在する | Missing: success result の `score_id` / `score_owner_user_id` metadata。Missing: self-view no-count branch。Missing: viewer+score 24h cooldown marker port。Unknown: exact Valkey Glide conditional set API。Constraint: IP、session token、raw query values を duplicate identity にしない。 |
| 4. Latest Activity Touch | `UserModel`、`User`、`UserCommandRepository`、UoW `users` | Missing: latest activity durable field and repository touch method。Missing: viewer user 5m throttle marker port。Missing: self-view/duplicate hit でも activity eligible にする command logic。Constraint: failed branches では触らない。 |
| 5. Accounting Scope Boundaries | `ReplayDownloadQuery` は read-only、#36 design は #37 mutation を out-of-boundary と明記 | Missing: #37 command use-case の boundary。Missing: design docs で response path と accounting path を分離。Constraint: playback detection、alias route、durable event history、request parsing/auth/lookup/storage/response strategy の変更は scope 外。 |
| 6. Verification and Operator Observability | Unit tests and integration tests for replay download query/handler/endpoint、structlog pattern | Missing: non-owner increment/self-view/duplicate/latest activity/throttle/failure branch/accounting failure tests。Missing: partial failure observability tests。Constraint: logs must not expose raw replay payloads, raw query values, credential values, local artifact paths。 |

## Implementation Approach Options

### Option A: Extend Existing Replay Download Handler Directly

既存 `StableReplayDownloadExchange` に accounting collaborator を追加し、success result の直後に command を呼ぶ。Query repository と result に accounting metadata を追加し、command repository methods を増やす。

Strengths:

- 変更点が endpoint flow に近く、実装経路が短い。
- Response preservation test を既存 handler/endpoint tests に追加しやすい。
- `ReplayDownloadQuery` を read-only のまま維持できる。

Risks / Limitations:

- Handler が auth、parse、query、response、best-effort side effect orchestration を持ち、責務が膨らむ。
- Cooldown/throttle の state port と failure handling を transport 近くに置きすぎると境界が弱くなる。

### Option B: Create Dedicated Replay Download Accounting Command

`services/commands/scores/` に `ReplayDownloadAccountingUseCase` を追加し、input は `score_id`、`score_owner_user_id`、`viewer_user_id`、`occurred_at` のみにする。Command は temporary marker port と UoW repository methods を使い、transport は success metadata から command input を組み立てる。

Strengths:

- Query path と mutation policy を分離できる。
- Self-view、duplicate cooldown、activity throttle、partial failure policy を command tests で独立検証できる。
- Persistence operation ごとの observability を command 側に閉じ込めやすい。

Risks / Limitations:

- 新規 command、state port、Valkey/memory adapters、provider wiring、migration、tests が必要。
- Success response preservation は handler integration test で追加検証が必要。

### Option C: Background Job / Durable Event Based Accounting

Replay download success 後に job または durable event を enqueue し、worker が count/activity を更新する。

Strengths:

- Download response latency から accounting persistence を切り離せる。
- 将来 high traffic で集計を batch 化しやすい。

Risks / Limitations:

- 今回の決定と反する durable per-download event history に近づきやすい。
- Response success と accounting ordering、duplicate cooldown marker、failure observability が複雑になる。
- #37 の "after success body is known, before response construction" という accounting point と合いにくい。

## Effort And Risk

- Effort: M (3-7 days)
  - Schema migration、domain/model/repository updates、new command use-case、Valkey/memory temporary marker adapters、provider wiring、unit/integration tests が必要。
- Risk: Medium
  - Response contract regression、Valkey one-shot marker implementation uncertainty、partial failure observability、dataclass field追加による test update、migration/backfill の影響がある。

## Recommendations For Design Phase

### Preferred Approach

Option B を中心に、transport への hook は Option A 的に薄く追加する hybrid approach がよい。

- `ReplayDownloadQuery` は read-only のまま維持する。
- `ReplayDownloadAvailableReplayCandidate` と `ReplayDownloadQueryResult` に accounting metadata を追加する。
- `StableReplayDownloadExchange` は success result の body が得られた後、response construction の直前に accounting command を best-effort で呼ぶ。
- Accounting command は partial failure を response へ伝播しない。
- Replay View Count increment と latest activity touch は同一 use-case で扱うが、内部 operation と log event は区別する。
- Durable per-download event table は作らない。
- `scores.replay_view_count` は integer/bigint の not null default 0 とし、既存 row は 0 backfill する。
- Cooldown/throttle は Valkey TTL marker と memory adapter で実装し、marker loss 時の over-count/extra write は許容する。

### Research Items To Carry Forward

- `valkey-glide` で `SET key value NX EX seconds` 相当を型安全に呼べるか。難しければ Lua `Script` で実装する。
- `latest_activity` の durable column 名と意味。候補は `users.latest_activity_at`。`updated_at` とは用途が違うため流用しない。
- Replay View Count を `Score` domain dataclass に含めるか、command repository の targeted increment と query read model に限定するか。
- Operator-observable failure の log event 名と fields。`score_id`、`viewer_user_id`、operation、failure_class 程度に留め、raw query/body/credential/path は含めない。
- Count increment と latest activity touch を別 UoW にするか、同一 UoW 内で best-effort operation ごとに rollback/commit を分けるか。
- Response preservation regression tests で accounting success/failure の両方を既存 #36 response bytes/status/headers と比較する方法。

## Next Steps

1. Requirements を確認し、問題なければ approve する。
2. `$kiro-spec-design replay-download-accounting` で technical design を作る。
3. Design phase で Valkey one-shot marker API と latest activity durable field を確定する。

---

# Design Discovery Addendum

## Summary

- **Feature**: `replay-download-accounting`
- **Discovery Scope**: Extension
- **Key Findings**:
  - 既存 replay download response path は query-only として分離済みであり、accounting は別 command use-case として追加するのが最小かつ境界が明確である。
  - Duplicate cooldown と latest activity throttle は同じ one-shot TTL marker 問題であるが、call site へ raw key を渡さない domain-specific gate port にまとめるのがよい。
  - Valkey GLIDE は `Script` と `invoke_script` による Lua script 実行をサポートしており、既存 codebase でも同じ pattern が使われているため、conditional `SET NX EX` は Lua script adapter として設計する。

## Research Log

### Replay download accounting integration point

- **Context**: Success response が確定した後、response bytes/status/headers を変えずに accounting を呼べる位置を確認するため。
- **Sources Consulted**:
  - `src/osu_server/transports/stable/web_legacy/replay_download.py`
  - `src/osu_server/services/queries/scores/replay_download.py`
  - `tests/integration/transports/web_legacy/test_replay_download_endpoint.py`
  - `.kiro/specs/replay-download-response/design.md`
- **Findings**:
  - `StableReplayDownloadExchange.respond()` は auth、parse、query、response mapping を一か所で orchestration している。
  - `ReplayDownloadQuery` は read-only workflow として明示され、mutation dependency を持たない。
  - Success response の body、status、headers は既存 integration test で固定されている。
- **Implications**:
  - Accounting hook は query ではなく transport exchange の success branch 直後に置く。
  - Query result に client-visible ではない accounting metadata を追加し、transport は追加 lookup をしない。
  - Handler は accounting failure を握りつぶして response preservation test で検証する。

### Durable projection and activity persistence

- **Context**: Replay View Count と latest activity の durable storage を既存 persistence pattern に合わせるため。
- **Sources Consulted**:
  - `src/osu_server/repositories/sqlalchemy/models/score.py`
  - `src/osu_server/domain/scores/score.py`
  - `src/osu_server/repositories/interfaces/commands/scores.py`
  - `src/osu_server/repositories/sqlalchemy/models/user.py`
  - `src/osu_server/domain/identity/users.py`
  - `src/osu_server/repositories/interfaces/unit_of_work.py`
- **Findings**:
  - `scores` と `users` は既存 UoW から command repositories として取得できる。
  - Score read/write mapper は domain dataclass を中心にしているため、score-scoped count を domain model に持たせると command/query 両方の read model が一貫する。
  - `updated_at` は row update metadata であり、latest activity の業務値として流用すると意味が混ざる。
- **Implications**:
  - `scores.replay_view_count` は non-null BigInteger default 0 とし、non-negative check を持つ。
  - `users.latest_activity_at` は non-null timestamp とし、既存 user は `created_at` で backfill する。
  - Count increment と latest activity touch は別 durable operation として commit し、片方の failure がもう片方を rollback しない。

### Temporary marker implementation

- **Context**: 24h duplicate cooldown と 5m activity throttle を temporary state として実装するため。
- **Sources Consulted**:
  - `src/osu_server/infrastructure/state/interfaces/rate_limiter.py`
  - `src/osu_server/infrastructure/state/valkey/rate_limiter.py`
  - `src/osu_server/infrastructure/state/valkey/packet_queue.py`
  - `src/osu_server/infrastructure/state/valkey/stable_user_status_store.py`
  - Valkey GLIDE documentation via Context7, `/valkey-io/valkey-glide`
- **Findings**:
  - Existing `RateLimiter` は `INCR` と `EXPIRE` の counter であり、first-writer-wins marker には合わない。
  - Existing `ValkeyPacketQueue` は `Script` と `invoke_script` を使って atomic Valkey operation を実装している。
  - Valkey GLIDE documentation shows Python `Script` with `invoke_script`, including Lua scripts using `SET` with `NX` and `EX`.
- **Implications**:
  - #37 では汎用 RateLimiter を再利用せず、`ReplayDownloadAccountingGate` を追加する。
  - Valkey adapter は `SET key value NX EX ttl` を Lua script で実行し、atomic marker claim を bool として返す。
  - Gate failure は command が gate-open として扱い、count overrun または extra activity write を許容して response success を守る。

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
| --- | --- | --- | --- | --- |
| Query mutation | `ReplayDownloadQuery` 内で count/activity を更新する | 呼び出しは少ない | query boundary を壊し、既存 tests と設計に反する | Rejected |
| Transport direct repository update | Handler が UoW と Valkey を直接扱う | 変更点が一か所に見える | transport が persistence と state ownership を持つ | Rejected |
| Dedicated command with success metadata | Query は metadata を返し、transport が command に渡す | 境界が明確で testable | 新規 command/state adapters が必要 | Selected |
| Background job | Success 後に job enqueue して worker 更新 | latency を切り離せる | accounting point と durable event non-goal に合わない | Deferred |

## Design Decisions

### Decision: Replay download query remains read-only

- **Context**: #36 は replay download response contract を query workflow として固定している。
- **Alternatives Considered**:
  1. Query use-case に mutation collaborator を追加する。
  2. Query result に accounting metadata だけを追加し、mutation は別 command に渡す。
- **Selected Approach**: `ReplayDownloadQuery` は success branch で `ReplayDownloadAccountingMetadata` を返すだけにする。
- **Rationale**: Response compatibility と accounting policy を別々に test でき、command/query separation を維持できる。
- **Trade-offs**: Handler は success branch で command を一つ追加で呼ぶ必要がある。
- **Follow-up**: Handler tests で accounting failure が response を変えないことを固定する。

### Decision: Domain-specific temporary gate over generic marker keys

- **Context**: Cooldown と throttle はどちらも one-shot TTL marker だが、raw key を command に組み立てさせると identity policy が散らばる。
- **Alternatives Considered**:
  1. 汎用 `TemporaryMarkerStore.claim(key, ttl)` を公開する。
  2. `ReplayDownloadAccountingGate` に cooldown/throttle 専用 method を置く。
- **Selected Approach**: `ReplayDownloadAccountingGate` が `claim_view_count_cooldown` と `claim_latest_activity_throttle` を提供する。
- **Rationale**: IP、session token、raw query values を key にしない制約を adapter 境界で守れる。
- **Trade-offs**: 他 feature では直接再利用できないが、現時点の scope には過剰抽象がない。
- **Follow-up**: 将来 similar marker が増えたときに汎用化を検討する。

### Decision: Durable side effects are committed independently

- **Context**: Replay View Count increment と latest activity touch は atomicity を要求しない。
- **Alternatives Considered**:
  1. 一つの UoW で両方を更新する。
  2. Operation ごとに UoW を分け、failure を個別に観測する。
- **Selected Approach**: Count increment と latest activity touch はそれぞれ gate claim 後に別 UoW で commit する。
- **Rationale**: Partial failure を要件どおり許容し、どちらが失敗したかを log と result で区別できる。
- **Trade-offs**: 完全な同時整合性はない。
- **Follow-up**: Operator log fields と tests で partial failure を明示する。

## Risks & Mitigations

- Response contract regression - Existing endpoint tests に accounting success/failure variants を追加し、bytes/status/headers を比較する。
- Valkey unavailable causes over-count - Gate failure を sanitized warning として記録し、response success と durable operation best effort を優先する。
- Schema migration drift - Alembic migration、SQLAlchemy model、domain mapper、memory repository state を同じ task で更新する。
- Sensitive data leakage - Accounting input には raw query、credential、payload、path を含めず、logs は user/score ids と operation label だけにする。

## References

- `.kiro/specs/replay-download-accounting/requirements.md`
- `.kiro/specs/replay-download-accounting/research.md`
- `.kiro/specs/replay-download-response/design.md`
- `src/osu_server/transports/stable/web_legacy/replay_download.py`
- `src/osu_server/services/queries/scores/replay_download.py`
- `src/osu_server/infrastructure/state/valkey/packet_queue.py`
- Valkey GLIDE documentation: https://github.com/valkey-io/valkey-glide/blob/main/docs/markdown/python/async/lua-scripts-guide.md
