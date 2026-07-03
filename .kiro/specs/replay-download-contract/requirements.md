# 要件文書

## はじめに

Replay Download Contract は、GitHub Issue #35「[stable-compat] Replay download contract と fixtures を確定する」に基づき、Stable replay download の外部 contract を実装前に固定するための spec である。

対象は `/web/osu-getreplay.php` を主 route とし、`/web/replays/<id>` のような replay alias は Target Stable Client traffic または reference evidence で必要性を確認する。成果は #36「`/web/osu-getreplay.php` で保存済み replay bytes を返す」が推測なしで開始できる状態でなければならない。

## 境界コンテキスト

- **対象範囲**: Replay download route/path/auth/request/response contract の確認、Target Stable Client traffic capture の sanitized fixture 化、`bancho.py` / `deck` / `lets` reference audit、Replay blob integrity 診断、Replay Download Body Assembly Decision、stable compatibility docs への evidence 反映。
- **対象外**: replay download endpoint の実装、view count / latest activity 更新、score submission replay persistence の修正、raw capture / raw replay bytes の repository 保存、anti-cheat / replay validation policy。
- **隣接期待**: #36 はこの spec の confirmed contract を実装入力として扱う。#37 は replay view count と latest activity update を扱う。既存 score submission は Replay blob を保存するが、Replay Download Response Body が保存済み blob bytes と同一かどうかはこの spec で確認する。

## 要件

### 要件 1: Target route と auth contract の確定

**目的:** Stable compatibility 保守者として、Target Stable Client が replay download workflow で実際に送る route と auth contract を確認でき、#36 が path や credential requirement を推測せずに実装できるようにしたい。

#### 受け入れ基準

1. When Target Stable Client replay download workflow is captured, the Replay Download Contract shall record method, path, query key set, auth field presence, workflow entrance, target client family, observed client build or not-observed status, observed `osuver` or not-observed status, user agent, and capture time as sanitized metadata.
2. When Target Stable Client route evidence is evaluated, the Replay Download Contract shall require real target-client traffic for route path, method, query key set, and auth field presence.
3. If route path or auth field presence is missing from target-client traffic, then the Replay Download Contract shall keep #36 implementation blocked.
4. When auth success and auth failure behavior is evaluated, the Replay Download Contract shall accept target-client traffic or `bancho.py` / `deck` / `lets` reference-backed evidence.
5. If auth success condition or auth failure response remains unconfirmed, then the Replay Download Contract shall keep #36 implementation blocked.

### 要件 2: Replay download response contract の確定

**目的:** 実装担当者として、成功、not found、malformed、auth failure の response contract を同じ evidence model で読めることで、client-visible behavior を推測せずに実装したい。

#### 受け入れ基準

1. When success response evidence is recorded, the Replay Download Contract shall identify status, response header key set, body kind, safe body hash when allowed, and byte size.
2. When missing replay, hidden score, and storage-missing branches are evaluated, the Replay Download Contract shall record the selected reference-compatible status and response summary.
3. When malformed request branches are evaluated, the Replay Download Contract shall record missing score id, malformed score id, missing mode, malformed mode, and unknown field behavior or mark each branch as unresolved.
4. If a response branch is unresolved after target traffic and reference audit, then the Replay Download Contract shall mark that branch as `unconfirmed` and prevent #36 from treating it as implementation-ready.
5. The Replay Download Contract shall distinguish Replay Download Response Body from the storage backend Replay blob object.

### 要件 3: Target-client-compatible 成功 body の確認

**目的:** Stable client 利用者として、download された replay response body が target client の replay download workflow で消費できることで、server から取得した replay を実際に再生できるようにしたい。

#### 受け入れ基準

1. When success body evidence is accepted, the Replay Download Contract shall require the body to be target-client-compatible as replay download response bytes.
2. If the stored Replay blob bytes cannot be imported after renaming to `.osr`, then the Replay Download Contract shall not treat that rename failure alone as storage corruption.
3. When stored Replay blob bytes and expected download body differ, the Replay Download Contract shall record whether #36 needs Replay Download Body Assembly.
4. If target-client-compatible body validation cannot be completed safely without raw replay bytes in the repository, then the Replay Download Contract shall store only sanitized metadata and mark the raw artifact as local-only.

### 要件 4: Reference implementation audit の範囲

**目的:** Compatibility reviewer として、reference 実装ごとの根拠を分けて確認でき、single-source assumption で contract を固定しないようにしたい。

#### 受け入れ基準

1. When reference implementation evidence is collected, the Replay Download Contract shall include `bancho.py`, `deck`, and `lets` in the Replay Download Reference Set.
2. When `bancho.py` is audited, the Replay Download Contract shall use it as stable baseline comparison evidence.
3. When `deck` is audited, the Replay Download Contract shall use it as missing, hidden, and storage-missing branch comparison evidence.
4. When `lets` is audited, the Replay Download Contract shall use it as `/web/replays/<id>` alias comparison evidence.
5. If reference implementations disagree, then the Replay Download Contract shall record the disagreement and select a contract only when target-client traffic or an explicit compatibility rationale resolves it.

### 要件 5: Sanitized fixture と秘匿情報保護

**目的:** OSS 保守者として、互換性 evidence を repository で共有でき、password や raw replay payload を漏らさないようにしたい。

#### 受け入れ基準

1. When traffic capture or reference response evidence is committed, the Replay Download Contract shall commit only Replay Download Sanitized Fixture metadata.
2. The Replay Download Contract shall not commit password, password hash, session token, raw credential value, raw query value, raw replay bytes, HAR archive, or complete `.osr` bytes.
3. When sanitized fixture describes auth, the Replay Download Contract shall record auth field names or redacted field categories without credential-like values.
4. When sanitized fixture describes response body, the Replay Download Contract shall record body kind, byte size, and safe hash only when the hash cannot expose raw replay content.
5. If raw capture is needed for diagnosis, then the Replay Download Contract shall keep it as local-only temporary artifact outside repository-managed files.

### 要件 6: Replay blob integrity 診断

**目的:** 開発者として、保存済み Replay blob が壊れているのか、download body format が違うだけなのかを切り分けられるようにしたい。

#### 受け入れ基準

1. When Replay Blob Diagnostic Procedure is executed for a score id, the Replay Download Contract shall verify replay attachment existence, blob metadata existence, storage object existence, size equality, and SHA-256 equality.
2. If blob metadata and storage bytes mismatch, then the Replay Download Contract shall classify the result as storage integrity failure.
3. If blob metadata and storage bytes match but target-client-compatible body validation fails, then the Replay Download Contract shall classify the result as download body format mismatch unless other evidence proves corruption.
4. The Replay Blob Diagnostic Procedure shall not output raw replay bytes or credential-like values.
5. The Replay Download Contract shall record the diagnostic outcome needed to decide whether #36 returns blob bytes directly or assembles a replay download body.

### 要件 7: Alias 方針の確定

**目的:** Route 実装者として、`/web/replays/<id>` alias を #36 に含めるか後続候補として残すかを判断でき、unconfirmed alias を required route と混同しないようにしたい。

#### 受け入れ基準

1. When Target Stable Client traffic confirms `/web/osu-getreplay.php`, the Replay Download Contract shall classify it as the primary replay download route for #36.
2. When Target Stable Client traffic or `lets` reference evidence confirms `/web/replays/<id>`, the Replay Download Contract shall decide whether the alias is required, deferred, or candidate-only.
3. If `/web/replays/<id>` is supported only by reference implementation and not target-client traffic, then the Replay Download Contract shall not classify it as current target-client required.
4. If alias request or response shape differs from `/web/osu-getreplay.php`, then the Replay Download Contract shall record the difference as separate evidence rather than inheriting the primary route contract silently.

### 要件 8: Docs と issue handoff

**目的:** 次の実装エージェントとして、docs と GitHub issue から #36 の着手条件、blocker、未確認点を読めるようにしたい。

#### 受け入れ基準

1. When replay download contract evidence is finalized, the Replay Download Contract shall update `docs/stable-compatibility-guide.md` Replay Download evidence note.
2. When replay download contract evidence is finalized, the Replay Download Contract shall update `docs/stable-compatibility-matrix.md` replay download rows with current classification, evidence source, and remaining gaps.
3. When #36 remains blocked by unresolved evidence, the Replay Download Contract shall record exact blockers in docs and issue handoff text.
4. When #36 becomes implementation-ready, the Replay Download Contract shall state confirmed route, auth, request fields, response branches, body assembly decision, and sanitized fixture locations.
5. The Replay Download Contract shall leave #37 replay view count and latest activity behavior out of #36 readiness unless the contract evidence directly affects download response behavior.
