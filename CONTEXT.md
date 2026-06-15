# Athena Domain Glossary

## Identity and Authorization Context

### Role
A named authorization bundle assigned to a user. A role grants server-side privileges and is not itself exposed as a stable client permission.
_Avoid_: Permission group, client role

### Privilege
A server-side authorization capability used by Athena to permit protected operations. Privileges are the source of truth for internal authorization decisions.
_Avoid_: Permission, client permission

### Bancho Client Permission
A stable client-visible compatibility flag derived from a user's privileges for Bancho login and presence packets. It is never the source of truth for server authorization.
_Avoid_: Privilege, internal permission, ClientPermissions

### Session Authorization Snapshot
A point-in-time authorization view for an active session, containing the user's current privileges and role membership. It is refreshed from role state and then used by authorization-sensitive actions.
_Avoid_: Session permissions, cached roles

### ModCombination
A canonical score mod value object. Stable bitmasks, lazer payloads, and first-party API payloads are converted into ModCombination before reaching score use-cases, while persistence may store the canonical bitmask integer.
_Avoid_: Raw mods int at use-case boundary, stable bitmask as domain model

## Event Boundary Context

### Local Event
同一 process 内で完結する一時的な通知。外部 replica や worker が受け取る必要はなく、失われても durable state の source of truth は壊れない。
_Avoid_: EventBus event, distributed event

Production-critical workflow の source of truth にはしない。

### Distributed Event
複数 process や複数 runtime family に届ける必要がある一時的な通知。通知の source of truth ではなく、受信者が現在状態を再取得するきっかけとして扱う。
_Avoid_: durable work, task result

DB-backed event log ではなく、non-durable な通知として扱う。

### Disconnect Notification
User が active session から離れたことを他 runtime に知らせる Distributed Event。Presence や channel membership の source of truth ではなく、miss しても TTL や heartbeat により最終的に回復する。
_Avoid_: presence truth, membership cleanup guarantee

### Durable Work
失われると user-visible state や永続 state が欠落する作業単位。未処理 work の source of truth を持ち、retry や重複実行に耐える前提で扱う。
_Avoid_: pub/sub notification, fire-and-forget event

Queue は実行 signal であり、production-critical work の source of truth ではない。
Production-critical Durable Work は DB-backed work item や state machine を source of truth にする。

### Chat Persistence Work
受け付けた chat message を chat history に反映する Durable Work。Realtime delivery とは別の結果であり、retry や重複実行でも同じ履歴状態へ収束する。
_Avoid_: chat event, pub/sub message, listener side effect

## Score Submission Context

### Score Submission
Client からの score submit request を記録する entity。Network error や processing delay による retry を検出し、idempotent response を保証する。

- **Fingerprint**: Submission の canonical identifier。User ID + beatmap checksum + submitted timestamp + request hash で構成。Global unique constraint。
- **State**: `received` → `processing` → `completed` / `terminal_rejected`
- **Result Snapshot**: Completed submission の response data。Retry 時に同じ response を再生成するために保存。

**関係性**:
- 1つの Score Submission は 0 または 1 つの Score を生成する
- Validation に失敗した submission は score を生成せず、failure category だけ記録する
- Performance Calculation は Result Snapshot に焼き込まず、retry response 作成時に current Performance Calculation から合成する

---

### Score
Validated された gameplay result の canonical record。Leaderboard、stats、rank calculation の source of truth。

**Identity**:
- **Online Checksum**: Score payload 自体の checksum (client が生成)。Global unique constraint。同じ gameplay result の重複送信を防ぐ。
- **Replay Checksum**: Replay blob の SHA-256。Global unique constraint。Replay 使い回し攻撃を防ぐ。

**Attributes**:
- User ID, beatmap ID, beatmap checksum
- Ruleset (osu, taiko, catch, mania)
- Playstyle (vanilla, relax, autopilot)
- Mods (`ModCombination`; persistence stores the canonical bitmask integer)
- Hit counts (n300, n100, n50, miss, geki, katu)
- Score value, max combo, accuracy, grade
- Passed (true/false) — failed play も score として保存
- Perfect (full combo flag)
- Client version, client flags
- Submitted timestamp

**Uniqueness Rules**:
1. Online checksum が一致 → Reject (同じ gameplay result の重複)
2. Replay checksum が一致 → Reject (replay 使い回し攻撃)

**関係性**:
- 1つの Score は 0 または 1 つの Replay を持つ
- Failed play (passed=false) は score として保存するが、leaderboard/PP/stats から除外

---

### Beatmap File Warmup
Stable client が beatmap を参照した段階で、その後の score submission や Performance Calculation に必要な Beatmap File を事前準備対象にすること。Response の source of truth ではなく、後続処理の待ち時間と retry を減らすための準備状態として扱う。
_Avoid_: Beatmap metadata lookup, synchronous file fetch, PP calculation

**関係性**:
- Beatmap File Warmup は Score を生成しない
- Beatmap File Warmup は Performance Calculation の代わりに PP を計算しない
- Beatmap File がまだ unavailable でも、stable response は各入口の互換形式を維持する

---

### Performance Calculation
PP-eligible Score に PP と star rating を付与した結果。Ranked / Approved の passed score の競技的な強さを表し、ranked leaderboard や ranked stats が参照する performance source になる。
_Avoid_: PPだけ, calculator response

**関係性**:
- 1つの Score は 0 または 1 つの current Performance Calculation を持つ
- 1つの Score は複数の historical Performance Calculation を持てる
- Score 自体は gameplay result の source of truth であり、PP は Score へ直接混ぜない
- Performance Calculation は Score の gameplay result と Beatmap File から導かれ、Replay を正本入力にしない
- 同じ Score に対する重複 calculation request は current state と provenance を見て冪等に収束させる

**State**:
- `queued`, `fetching_file`, `calculating` — PP result がまだ確定していない
- `completed` — PP result が確定している
- `unavailable` — PP result が恒久的に得られない
- `superseded` — PP Recalculation により current ではなくなった historical record

### Performance Provenance
Performance Calculation の由来を説明する記録。どの calculator profile、calculator version、beatmap file attachment から計算されたかを表す。
_Avoid_: Debug metadata, calculator log

### Performance Unavailable
PP-eligible Score に対する Performance Calculation が恒久的に得られない状態。Score は accepted のまま保持し、stable client retry は止め、operator が原因を調査できるようにする。
_Avoid_: Score reject, retry pending, pp zero score

### Performance Completion Signal
Performance Calculation の完了または利用不可確定を app に知らせる一時的な通知。待機を効率化するための signal であり、performance value の source of truth ではない。
_Avoid_: Task result, canonical PP result

### Formula Profile
Athena が採用する PP 計算ポリシーの名前。Playstyle ごとに分離し、同じ calculator version でも profile が変われば PP Recalculation の対象になる。
_Avoid_: Calculator version, mode name

**Policy**:
- 同じ playstyle の ranked PP は同じ Formula Profile に収束させる
- User flag や user subset で Formula Profile を分岐させない

### PP Recalculation
既存 Score の Performance Calculation を再生成する操作。保存済み provenance が現在の calculator version / formula profile と異なる場合、または beatmap file や保存済み score data が変化した場合に、古い performance value を置き換えるために使う。
_Avoid_: Backfill, stats rebuild

### Performance Recalculation Batch
PP Recalculation の対象 work を durable に束ねる単位。Queue signal ではなく DB 上の batch / work item が未処理 work の source of truth になる。
_Avoid_: Task queue as source of truth, one-shot CLI loop

---

### Replay
Score に付随する replay data。Score の証跡、重複検出、将来の verification / audit に使う。

- **Blob Key**: Storage backend での識別子
- **SHA-256 Checksum**: Replay bytes のハッシュ。Global unique constraint。
- **Byte Size**: Replay サイズ (safety limit で制限)

**Uniqueness Constraint**:
- Replay checksum は全 user、全 beatmap で unique
- 同じ replay を複数の score で使い回すことは不可能 (正規 play ではありえない)

**関係性**:
- 1つの Replay は exactly 1つの Score に属する
- Score は replay なしで存在可能 (client が replay を送らない場合)
- Replay は Performance Calculation の正本入力ではない

---

### Playstyle
Score の mod category axis。Leaderboard と stats を分離するための次元。

**Values**:
- `vanilla` (0) — 通常 play。Wave 1 で実装。
- `relax` (1) — Relax mod。将来実装予定。
- `autopilot` (2) — Autopilot mod。将来実装予定。

**Policy**:
- Wave 1 では vanilla のみ受け付ける
- Relax/Autopilot mod を含む submission は terminal reject
- Schema には playstyle column を用意し、将来の拡張に備える

**本家との差異**:
- osu! 公式: RX/AP score は保存しない
- Athena: Akatsuki と同様、RX/AP score も保存し、別 leaderboard で管理

---

### Beatmap Eligibility
Score を受け付ける条件。本家 osu! と同じ基準。

**Eligible Status** (leaderboard が存在):
- Ranked — Ranked PP 付与、global/country rank に反映
- Approved — Ranked と同じ扱い
- Loved — Leaderboard のみ。PP なし、rank なし。
- Qualified — Leaderboard のみ。PP なし。(Ranked 候補)

**Ineligible Status**:
- Pending, WIP, Graveyard, NotSubmitted — Score を受け付けない (terminal reject)
- Unknown (beatmap が mirror に存在しない) — Terminal reject

**Rationale**:
- Leaderboard が存在しない beatmap の score は意味がない
- Beatmap metadata がなければ ruleset や difficulty も不明
- Loved / Qualified / failed score は Score として保存できるが、Wave 2 では Performance Calculation を持たない

---

### Terminal Reject
Score submission が永続的に失敗する条件。Client は retry すべきでない。

**Terminal Reject Conditions**:
1. **Transport validation failure**: Multipart parsing 失敗、required field 欠損
2. **Crypto validation failure**: Decryption 失敗、payload checksum 不一致
3. **Authorization failure**: Password 不一致、active session なし、payload identity mismatch
4. **Uniqueness violation**: Online checksum 重複、replay checksum 重複
5. **Beatmap ineligibility**: Unknown beatmap、ineligible status
6. **Playstyle not supported**: Wave 1 では relax/autopilot を reject
7. **Score validation failure**: Hit counts 不整合、ruleset-specific validation 失敗

**Retryable Conditions** (Wave 1 scope 外):
- Beatmap file 取得中 (processing pending)
- Worker queue 過負荷
- Temporary storage/DB error
- Performance Calculation が bounded wait 内に完了していない

---

## Reference Implementations

Athena の設計は以下の既存実装を参考にしています:

### bancho.py (Akatsuki)
- Python + FastAPI
- Single process architecture
- Score table with `mode` column (vanilla/RX/AP を packed integer で表現)
- Repository pattern (直接 SQLAlchemy import)

### osuRipple/lets
- Python + Cython
- Score table with `play_mode` と relax flag
- Checksum + lock による duplicate 防止

### osuTitanic/deck
- Python + FastAPI (modern)
- rosu-pp-py 使用
- Helper pattern で validation と calculation を分離

### Pure-Peace/peace (参考、実験的実装)
- **Rust** implementation
- Clean architecture with **clear layer separation**
- Score/leaderboard/stats を **mode/playstyle ごとに物理分割**
- Entity-based design (scores_standard, leaderboard_standard, user_stats_standard)
- 型安全、明確な境界を持つ設計

**Note**: 実験的実装のため参考程度。Athena は table 物理分割は採用せず、axis column で統一します。

---

## Architectural Boundaries

### Wave 1: Score Ingestion
**Responsibility**: Stable client からの score 受付、validation、保存、replay 保存。

**In Scope**:
- Multipart parsing (duplicate `score` field の order-preserving)
- Rijndael 256-bit decryption (特殊仕様: Rijndael-256 / block_size=32 / CBC / 32-byte IV)
- Score payload parsing (colon-separated → domain object)
- Authorization (password + active session + payload identity)
- Score validation (hit counts 整合性、ruleset-specific)
- Replay uniqueness check
- Completed response (PP なし、chart placeholder)

**Crypto Implementation Note**:
- osu! の Rijndael 実装は標準 AES-256 と異なる
- Rijndael-256 (key size 256-bit, **block size 256-bit = 32 bytes**)
- Mode: CBC
- IV: 32-byte (block size と同じ)
- Standard AES-256 は block size 128-bit なので、cryptography library では対応不可
- 対応ライブラリを調査するか、PyO3 + Rust の rijndael crate を使う必要あり

**Out of Scope**:
- PP calculation (Wave 2)
- Leaderboard projection (Wave 3)
- User stats projection (Wave 3)
- User ranking projection (Wave 4)

**Dependencies**:
- Beatmap mirror (beatmap metadata と eligibility)
- Blob storage (replay 保存)
- Active session store (authorization)
- Score authorization command service (password + active session 検証)

---

## Future Waves

### Wave 2: score-pp-calculation
**Goal**: Ranked / Approved の passed Score に PP と star rating を付与する。

**Scope**:
- rosu-pp-py による ranked PP と star rating 計算
- Performance provenance (calculator version, formula profile, beatmap file attachment)
- .osu file dependency と bounded wait
- Completed response with PP included

**Dependencies**: score-ingestion (Wave 1), beatmap-mirror

**Out of Scope**: Leaderboard への反映、user stats への反映

---

### Wave 3: beatmap-leaderboards & user-stats
**Goal**: Beatmap leaderboard と user stats を stable client と Web に表示する。

**beatmap-leaderboards Scope**:
- Beatmap leaderboard projection table
- Personal best tracking と replacement logic
- Getscores score rows provider
- Score descending ordering、PP display

**user-stats Scope**:
- User stats per ruleset/playstyle/category
- Play count, play time, ranked score, weighted PP, accuracy
- Grade counts、hit totals
- Stats update worker job

**Dependencies**: score-ingestion (Wave 1), score-pp-calculation (Wave 2)

**Out of Scope**: Global/country rank (Wave 4 で実装)

---

### Wave 4: user-ranking
**Goal**: Global/country rank を時系列で tracking し、user profile と ranking graph に表示する。

**Scope**:
- User rank projection table (current snapshot)
- Rank 時系列履歴 table (daily/hourly snapshots)
- Rank rebuild worker job (window function による bulk calculation)
- Ranking graph API (time series data)
- Login packet と Web ranking API への rank 提供

**Dependencies**: user-stats (Wave 3)

**Design Considerations**:
- Snapshot frequency (hourly? daily?)
- Historical data retention policy
- Rebuild strategy (incremental vs full rebuild)
- Tie-break ordering (PP → ranked score → user ID)
