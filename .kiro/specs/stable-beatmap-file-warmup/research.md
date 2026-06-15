# stable-beatmap-file-warmup Gap Analysis

作成日: 2026-06-16

## Analysis Summary

- 既存の beatmap-mirror は `BeatmapResolveOptions(require_osu_file=True)` による `.osu` file fetch enqueue と `fetch_beatmap_file` worker task を既に持っているため、file provider や queue の新規導入は不要です。
- gap は stable の 3 入口 (`osu-osz2-getscores.php`, `STATUS_CHANGE`, `osu-submit-modular-selector.php`) から既存 file fetch capability へ安全に接続する orchestration にあります。
- getscores は現在 read-only query と response compatibility を明示しているため、warmup side effect は `BeatmapScoreListingQuery` へ混ぜず、transport handler か専用 use-case 境界から呼び出す設計が必要です。
- `STATUS_CHANGE` は packet ID と `StatusUpdate` type は存在しますが、現時点で handler が登録されていません。新規 handler と DI 登録が主な追加点です。
- score submit は checksum metadata 解決に bounded wait を使っていますが、file availability は要求していません。fallback warmup は terminal reject / retryable / accepted semantics を変えない位置に差し込む必要があります。

## Context Loaded

- Spec:
  - `.kiro/specs/stable-beatmap-file-warmup/spec.json`
  - `.kiro/specs/stable-beatmap-file-warmup/requirements.md`
- Steering / rules:
  - `.claude/rules/architecture.md`
  - `.claude/rules/development.md`
  - `.claude/rules/operations.md`
  - `.kiro/steering/tech.md`
  - `.kiro/steering/scaling.md`
  - `.kiro/steering/roadmap.md`
- Code areas:
  - `src/osu_server/domain/beatmaps/models.py`
  - `src/osu_server/services/queries/beatmaps/mirror/resolution_service.py`
  - `src/osu_server/services/commands/beatmaps/fetch.py`
  - `src/osu_server/jobs/beatmap_fetch.py`
  - `src/osu_server/transports/stable/web_legacy/getscores.py`
  - `src/osu_server/services/queries/scores/beatmap_score_listing.py`
  - `src/osu_server/services/commands/scores/process_submission.py`
  - `src/osu_server/transports/stable/bancho/protocol/enums.py`
  - `src/osu_server/transports/stable/bancho/protocol/types.py`
  - `src/osu_server/transports/stable/bancho/dispatch.py`
  - `src/osu_server/transports/stable/bancho/workflows/polling.py`
  - `src/osu_server/composition/providers/stable_bancho.py`
  - `src/osu_server/composition/providers/stable_web_legacy.py`

注意: この gap analysis 作成時点では requirements は生成済みかつ未承認でした。design generation では `-y` により requirements を承認済みに更新しています。

## Current State Investigation

### Beatmap File Fetch Assets

既存の beatmap-mirror は Beatmap File Warmup に必要な低レベル capability をほぼ提供しています。

- `BeatmapResolveOptions` は `require_osu_file: bool = False` を持ちます。
- `BeatmapMirrorService.resolve_by_beatmap_id(..., require_osu_file=True)` は未知 beatmap の metadata fetch と file fetch を enqueue できます。
- `BeatmapMirrorService.resolve_by_checksum(..., require_osu_file=True)` は checksum が既知 beatmap に解決できた場合、file state が `AVAILABLE` でなければ `file_by_beatmap_id` を enqueue できます。
- checksum が未知の場合は metadata fetch のみ enqueue され、beatmap id がまだないため file fetch target は作れません。
- `enqueue_beatmap_fetch` は `file:*` target を `fetch_beatmap_file` task に振り分けます。
- `fetch_beatmap_file` taskiq adapter と `FetchBeatmapFileUseCase` が存在し、worker 経由の取得経路があります。

既存 capability を使う場合、new schema は不要に見えます。必要なのは stable entrance から「認証済み activity による file preparation request」を表現する use-case / service boundary です。

### Getscores Assets

`GetscoresHandler` は次の順序で stable response を返しています。

1. `us` / `ha` による session credential 認証
2. `GetscoresQueryParser` による query parse
3. `BeatmapScoreListingQuery.resolve`
4. unavailable / update-available / header response formatting

`BeatmapScoreListingQuery` は docstring で read-only resolution を明示し、background fetch workflow を trigger しない設計です。Requirement 2 の warmup はこの read-only query に直接混ぜると command/query 境界を曖昧にします。

Parser は checksum `c`、filename `f`、beatmapset hint `i` を保持しますが、beatmap id は直接扱いません。getscores warmup は以下のいずれかで beatmap identity を得る必要があります。

- known-header outcome の `Beatmap.id`
- checksum から beatmap-mirror で解決した `Beatmap.id`
- filename + beatmapset hint から query が解決した `Beatmap.id`

checksum-only unknown の場合は、metadata fetch の enqueue は可能でも、file fetch は beatmap id 解決後でなければ enqueue できない点が制約です。

### STATUS_CHANGE Assets

stable bancho protocol には `ClientPacketID.STATUS_CHANGE = 0` と `StatusUpdate` type が存在します。`StatusUpdate` には `beatmap_md5` と `beatmap_id` が含まれます。

一方、現時点で `STATUS_CHANGE` の handler は登録されていません。`stable_bancho.py` の `PacketDispatcher` provider は `LifecycleHandlers` と `ChatHandlers` のみ登録しています。新規 `StatusChangeHandlers` などを追加し、dispatcher provider に登録する必要があります。

`PollingWorkflow` は handler 例外を `c2s_handler_error` として log し、packet handling failure だけでは client disconnect にしません。この既存性質は Requirement 3.5 と相性が良いです。ただし warmup failure は handler 内で握って diagnostics にするか、既存 workflow の error handling に任せるかを design で明確にする必要があります。

### Score Submit Assets

`ProcessScoreSubmissionUseCase` は auth、playstyle、beatmap eligibility、hit count、replay storage、score persistence を順に処理します。beatmap 解決は現在:

- `resolve_by_checksum(parsed.beatmap_checksum, BeatmapResolveOptions(wait_timeout_seconds=5))`

であり、`require_osu_file=True` は指定されていません。したがって score submit は metadata readiness には bounded wait しますが、Beatmap File Warmup は発火していません。

既存 semantics:

- beatmap が未解決なら `beatmap_fetch_in_progress` として retryable を記録します。
- auth / playstyle / eligibility / validation などは terminal reject です。
- accepted score persistence は PP 計算や leaderboard 更新を行いません。

Requirement 4 はこの semantics を維持したまま file warmup fallback を追加する必要があります。特に terminal reject を retryable に変換しないこと、accepted score を file pending だけで reject しないことが constraint です。

### Composition / Worker / Tests

DI は Dishka provider が所有しています。追加候補は以下です。

- warmup service / use-case provider
- getscores handler への warmup dependency injection
- `STATUS_CHANGE` handler provider と dispatcher registration
- score submission use-case への warmup dependency injection、または beatmap resolver option 変更

既存 test assets:

- `tests/unit/services/test_beatmap_mirror_service.py`
- `tests/e2e/test_beatmap_file_resolution.py`
- `tests/integration/test_getscores_endpoint.py`
- `tests/integration/test_getscores_unavailable_paths.py`
- `tests/integration/test_getscores_diagnostics.py`
- `tests/unit/transports/bancho/test_dispatch.py`
- `tests/unit/transports/bancho/test_polling_workflow.py`
- `tests/unit/transports/bancho/protocol/test_types.py`
- `tests/unit/services/test_score_submission_service.py`
- `tests/integration/transports/web_legacy/test_score_submit_e2e.py`

## Requirement-to-Asset Map

| Requirement | Technical need | Existing asset | Gap |
| --- | --- | --- | --- |
| R1 Warmup Scope and Semantics | authenticated stable entrance から idempotent に file preparation を request する | `BeatmapResolveOptions(require_osu_file=True)`, `BeatmapFetchTarget.file_by_beatmap_id`, `fetch_beatmap_file` | **Missing:** entrance-independent warmup orchestration と diagnostics result |
| R2 Getscores Warmup | auth 成功後、parse 成功後、response body を変えずに warmup side effect を発火 | `GetscoresHandler`, `GetscoresQueryParser`, `BeatmapScoreListingQuery` | **Constraint:** query は read-only。**Missing:** handler か専用 use-case からの warmup call |
| R3 STATUS_CHANGE Warmup | packet payload から beatmap id / checksum を取り出し warmup | `ClientPacketID.STATUS_CHANGE`, `StatusUpdate`, `PacketDispatcher`, `PollingWorkflow` | **Missing:** `STATUS_CHANGE` handler と DI 登録。**Unknown:** presence-status との責務分割 |
| R4 Score Submit Fallback | accepted / retryable / terminal semantics を変えずに fallback warmup | `ProcessScoreSubmissionUseCase`, `BeatmapEligibilityResolver` Protocol | **Missing:** `require_osu_file` 指定または専用 fallback call。**Constraint:** terminal reject を retryable に変えない |
| R5 Security and Abuse Resistance | unauthenticated traffic から fetch work を発火しない | getscores auth, polling session lookup, submit auth flow | **Missing:** warmup boundary で入口・user_id・identity validation を統一する policy |
| R6 Operator Observability | entrance, beatmap identity, skipped/failure reason を log / diagnostics に出す | getscores diagnostics logs, fetch use-case logs, polling handler error logs | **Missing:** warmup-specific structured event names / result enum |
| R7 Compatibility Boundaries | stable response body と packet behavior を維持 | response formatters, `PacketDispatcher`, score submission idempotency | **Constraint:** client-visible body へ warmup state を出さない。**Missing:** regression tests |

## Missing Components By Boundary

### Warmup Orchestration

候補として `StableBeatmapFileWarmupUseCase` または `BeatmapFileWarmupService` が必要です。責務は以下に限定するのが自然です。

- entrance (`getscores`, `status_change`, `score_submit_fallback`) を受け取る
- beatmap id または checksum を検証する
- `BeatmapMirrorService` / resolver に `require_osu_file=True` を渡して file fetch を request する
- already available / requested / skipped / failed を operator-visible にする
- stable client response body へ結果を漏らさない

### Getscores Integration

`GetscoresHandler` に warmup dependency を追加し、auth success と parse success の後に呼ぶ統合が必要です。`BeatmapScoreListingQuery` に side effect を入れる案は read-only query contract に反します。

### STATUS_CHANGE Integration

`StatusChangeHandlers` などの新規 `HandlerGroup` が必要です。payload は Caterpillar の `unpack(StatusUpdate, payload)` 相当で decode し、`beatmap_id > 0` を優先、なければ 32 hex checksum を使う流れが候補です。

### Score Submit Fallback Integration

score submission の beatmap 解決に `require_osu_file=True` を付けるだけで一部は満たせますが、Requirement 4.5 の diagnostics と terminal reject との関係を明確にするため、専用 warmup service を呼ぶ方が境界は読みやすくなります。

### Diagnostics / Tests

warmup event 名と payload policy が未定です。credential、raw payload、replay body は出さず、`entrance`, `user_id`, `beatmap_id`, `checksum_present`, `result`, `reason` 程度に絞る必要があります。

## Implementation Approach Options

### Option A: Existing Components に直接追加

各 entrance が `BeatmapMirrorService` を直接呼び、`BeatmapResolveOptions(require_osu_file=True)` を指定します。

Pros:

- 新規ファイルが少ない
- 既存 resolver と worker enqueue をそのまま使える
- getscores と submit の最小差分は小さい

Cons:

- getscores handler、status handler、submit use-case に warmup 判定・logging が重複しやすい
- operator diagnostics の event name / reason が分散する
- query / command / transport 境界の説明が弱くなる
- abuse resistance の policy を一箇所で保証しづらい

### Option B: New Dedicated Warmup Component

stable warmup 専用の use-case / service を作り、3 入口はそこへ typed input を渡します。

Pros:

- idempotency、identity validation、diagnostics、failure handling を一箇所へ集約できる
- stable response compatibility を入口側に閉じ、warmup behavior を test しやすい
- 将来 `presence-status` や PP readiness と責務が混ざりにくい

Cons:

- provider と test double が増える
- `BeatmapMirrorService` が query path に置かれているため、side-effect を含む warmup service から呼ぶ設計説明が必要
- checksum unknown 時の metadata fetch と file fetch の二段階性を service contract に表現する必要がある

### Option C: Hybrid Approach

専用 warmup service を追加しつつ、実際の file fetch は既存 beatmap-mirror / worker queue を再利用します。entrance 側は薄い adapter に留めます。

Pros:

- 既存の fetch infrastructure と test coverage を再利用できる
- 3 entrance の behavior を統一できる
- DB schema や blob storage provider の変更を避けられる
- stable response body を変えない制約を entrance tests で固定しやすい

Cons:

- design で service placement を決める必要がある
- `BeatmapMirrorService` の「query package にあるが enqueue side effect を持つ」現状を明文化する必要がある
- status handler と score submission の依存追加で composition 差分が複数箇所に広がる

## Effort and Risk

- Effort: **M (3-7 days)**。fetch infrastructure は既存ですが、3 entrance、DI、diagnostics、compatibility regression tests が必要です。
- Risk: **Medium**。stable client の hot path に side effect を足すため、response semantics と abuse resistance の regression risk があります。ただし file fetch queue と worker は既存で、未知技術の導入は不要です。

## Recommendations for Design Phase

推奨は **Option C: Hybrid Approach** です。専用 warmup service で identity validation と diagnostics を統一し、file preparation 自体は既存 beatmap-mirror の `require_osu_file=True` と `fetch_beatmap_file` worker task を使うのが最も境界を保ちやすいです。

design で決めるべき事項:

- warmup service の配置: `services/commands/beatmaps`、stable compatibility service、または専用 package のどれにするか
- warmup result enum: `requested`, `already_available`, `skipped_no_identity`, `skipped_unauthenticated`, `failed`, `metadata_pending` など
- checksum-only unknown の扱い: metadata fetch だけを warmup requested と見るか、beatmap id 解決後に file fetch を別途要求するか
- getscores の warmup identity source: parsed request を使うか、resolved outcome header を優先するか
- `STATUS_CHANGE` の payload decode failure と malformed checksum の diagnostics event 名
- repeated `STATUS_CHANGE` に existing fetch pending idempotency 以上の debounce / rate limit が必要か
- score submit fallback を `resolve_by_checksum(..., require_osu_file=True)` に寄せるか、terminal validation 後かつ replay blob storage 前に専用 service call として置くか

Research Needed:

- `BeatmapMirrorService.resolve_by_checksum(require_osu_file=True)` が checksum unknown から wait 後に known beatmap へ到達した場合、file fetch enqueue まで到達することを unit / e2e で明示確認する。
- `fetch_beatmap_file` pending / duplicate enqueue の operator-visible log が warmup diagnostics として十分か、追加 event が必要か確認する。
- future `presence-status` spec と `STATUS_CHANGE` handler の責務が重なる場合、warmup-only handler を先に入れてよいか、presence handler の中に warmup hook を置くかを設計で整理する。

---

# Design Discovery Update

作成日: 2026-06-16

## Summary

- **Feature**: `stable-beatmap-file-warmup`
- **Discovery Scope**: Extension
- **Key Findings**:
  - 新規 dependency や schema migration は不要です。既存 `BeatmapMirrorService` と `fetch_beatmap_file` worker task を再利用できます。
  - 3 入口はすべて「認証済み stable activity から beatmap id / checksum を取り出す」同じ問題に収束するため、入口ごとに resolver を直接呼ばず、`RequestBeatmapFileWarmupUseCase` に集約する設計が適切です。
  - `STATUS_CHANGE` は protocol type と packet id はありますが handler が未登録です。presence-status とは分離し、warmup-only handler として追加するのが今回の最小境界です。

## Research Log

### Existing Beatmap Fetch Capability

- **Context**: Beatmap File Warmup のために新しい queue / worker / DB schema が必要か確認した。
- **Sources Consulted**:
  - `src/osu_server/domain/beatmaps/models.py`
  - `src/osu_server/services/queries/beatmaps/mirror/resolution_service.py`
  - `src/osu_server/composition/providers/beatmaps_app.py`
  - `src/osu_server/jobs/beatmap_fetch.py`
- **Findings**:
  - `BeatmapResolveOptions(require_osu_file=True)` が既に存在する。
  - `resolve_by_beatmap_id` は未知 beatmap id でも metadata と file fetch target を enqueue できる。
  - `resolve_by_checksum` は known beatmap なら file fetch を enqueue できるが、checksum unknown では beatmap id がないため metadata pending に留まる。
- **Implications**:
  - design は file fetch infrastructure を新設しない。
  - checksum-only unknown は `metadata_pending` として diagnostics に表現し、file fetch は beatmap id が判明した後の入口または後続 retry に委ねる。

### Stable Entrance Integration

- **Context**: getscores、`STATUS_CHANGE`、score submit fallback のどこへ warmup を差し込むか確認した。
- **Sources Consulted**:
  - `src/osu_server/transports/stable/web_legacy/getscores.py`
  - `src/osu_server/services/queries/scores/beatmap_score_listing.py`
  - `src/osu_server/transports/stable/bancho/protocol/types.py`
  - `src/osu_server/composition/providers/stable_bancho.py`
  - `src/osu_server/services/commands/scores/process_submission.py`
- **Findings**:
  - getscores read-side query は read-only を明示しており、warmup side effect を混ぜるべきではない。
  - `STATUS_CHANGE` は `StatusUpdate` type はあるが handler 登録がない。
  - score submit は existing metadata bounded wait を持つが file availability は要求していない。
- **Implications**:
  - getscores は handler から warmup use-case を呼ぶ。
  - `STATUS_CHANGE` は新規 `StatusChangeHandlers` で warmup-only を担当する。
  - score submit は terminal validation 後かつ replay blob storage 前に fallback warmup を呼び、retryable / accepted の submission outcome へ影響させない。

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
| --- | --- | --- | --- | --- |
| Direct calls from entrances | 各 handler/use-case が `BeatmapMirrorService` を直接呼ぶ | 差分が小さい | diagnostics と validation が分散しやすい | 採用しない |
| New standalone fetch pipeline | warmup 専用 queue / worker / state を作る | 責務は明確 | 既存 beatmap fetch と重複し、schema と運用が増える | 過剰設計 |
| Central warmup use-case with existing fetch queue | 3 入口は専用 use-case に集約し、file fetch は既存 worker を使う | 境界、diagnostics、idempotency が揃う | use-case と existing mirror の責務説明が必要 | 採用 |

## Design Decisions

### Decision: Warmup orchestration is a beatmap command use-case

- **Context**: Beatmap File Warmup は read-only response ではなく background file preparation を request するため、query use-case に混ぜると command/query 境界が曖昧になる。
- **Alternatives Considered**:
  1. `BeatmapScoreListingQuery` に side effect を追加する。
  2. stable transport handlers で resolver を直接呼ぶ。
  3. `RequestBeatmapFileWarmupUseCase` を追加する。
- **Selected Approach**: `services/commands/beatmaps/file_warmup.py` に typed use-case を追加し、transport と score submission から呼ぶ。
- **Rationale**: Beatmap context の preparation command として扱うことで、stable response formatting、score ingestion、fetch worker の責務を分離できる。
- **Trade-offs**: provider と tests は増えるが、diagnostics と security policy は一箇所に集約できる。
- **Follow-up**: 実装時に import-linter の command/query direction に違反しないよう、resolver は Protocol で受ける。

### Decision: no synchronous file wait in stable request paths

- **Context**: stable response semantics を維持し、song select や polling を file download latency に巻き込まない必要がある。
- **Alternatives Considered**:
  1. getscores / `STATUS_CHANGE` で短い wait を入れる。
  2. score submit fallback で file fetch 完了まで待つ。
  3. すべて queue request だけに留める。
- **Selected Approach**: `BeatmapResolveOptions(require_osu_file=True, wait_timeout_seconds=0)` を warmup use-case で使用する。score submit の metadata bounded wait は既存どおり維持する。
- **Rationale**: warmup は preparation であり readiness source ではない。client-visible response を遅延・変更しないことを優先する。
- **Trade-offs**: checksum-only unknown では即時 file fetch まで到達しない場合がある。
- **Follow-up**: metadata pending の後続 file fetch が必要な運用課題になった場合は、beatmap metadata fetch 完了後の follow-up durable work を別 spec で検討する。

### Decision: score submit fallback runs before replay blob storage

- **Context**: score submit fallback は beatmap が解決できた時点で Beatmap File preparation を最終 request する責務がある。一方、replay blob storage failure は retryable response になり得るため、completed persistence 直前だけに warmup を置くと retryable path を取りこぼす。
- **Alternatives Considered**:
  1. completed score persistence 直前で warmup を呼ぶ。
  2. retryable replay storage failure の return 直前にも追加で warmup を呼ぶ。
  3. auth、beatmap resolution、eligibility、empty replay、hit validation を通過した後、replay blob storage 前に warmup を呼ぶ。
- **Selected Approach**: replay blob storage 前に `RequestBeatmapFileWarmupUseCase` を呼ぶ。
- **Rationale**: terminal reject になる input では warmup を発火せず、accepted と replay storage retryable の両方で fallback preparation を保証できる。
- **Trade-offs**: 後続の replay storage が失敗して score が保存されない場合にも file warmup は発火するが、これは retry 後の同一 score submit を速くする preparation として requirements に合う。
- **Follow-up**: 実装時は warmup result を score submission outcome に混ぜず、diagnostics のみで扱う。

## Risks & Mitigations

- getscores response drift — existing formatter をそのまま使い、byte-for-byte response regression test を追加する。
- unauthenticated fetch abuse — auth gate の後だけ warmup use-case を呼ぶ。malformed identity は resolver に渡さない。
- repeated `STATUS_CHANGE` traffic — existing fetch pending idempotency を利用し、必要なら別 spec で debounce state を設計する。
- presence-status との handler ownership overlap — 今回は warmup-only handler とし、presence-status が `STATUS_CHANGE` を所有する段階で revalidation trigger とする。

## References

- `.kiro/specs/stable-beatmap-file-warmup/requirements.md`
- `.kiro/specs/stable-beatmap-file-warmup/research.md`
- `.claude/rules/architecture.md`
- `.kiro/steering/tech.md`
