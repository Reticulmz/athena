# Athena Domain Glossary

## Score Submission Context

### Score Submission
Client からの score submit request を記録する entity。Network error や processing delay による retry を検出し、idempotent response を保証する。

- **Fingerprint**: Submission の canonical identifier。User ID + beatmap checksum + submitted timestamp + request hash で構成。Global unique constraint。
- **State**: `received` → `processing` → `completed` / `terminal_rejected`
- **Result Snapshot**: Completed submission の response data。Retry 時に同じ response を再生成するために保存。

**関係性**:
- 1つの Score Submission は 0 または 1 つの Score を生成する
- Validation に失敗した submission は score を生成せず、failure category だけ記録する

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
- Mods (bitmask)
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

### Replay
Score に付随する replay data。Blob storage に保存。

- **Blob Key**: Storage backend での識別子
- **SHA-256 Checksum**: Replay bytes のハッシュ。Global unique constraint。
- **Byte Size**: Replay サイズ (safety limit で制限)

**Uniqueness Constraint**:
- Replay checksum は全 user、全 beatmap で unique
- 同じ replay を複数の score で使い回すことは不可能 (正規 play ではありえない)

**関係性**:
- 1つの Replay は exactly 1つの Score に属する
- Score は replay なしで存在可能 (client が replay を送らない場合)

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
- Legacy auth service (password 検証)

---

## Future Waves

### Wave 2: score-pp-calculation
**Goal**: Score に PP と star rating を付与する。

**Scope**:
- rosu-pp-py による PP と star rating 計算
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
