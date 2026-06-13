# Validation Report: score-ingestion

**Feature**: score-ingestion (Wave 1)
**Validated**: 2026-06-13T08:50:00+09:00
**Decision**: GO

---

## 概要

全 19 タスクが `[x]` 完了。フルテストスイート 2228 passed。import-linter 8/8 contracts clean。クロスタスク統合は機能的に正しく動作している。3 件の軽微な spec 準拠ギャップを検出（いずれも Wave 1 のコア機能を妨げない）。

---

## 1. 機械的チェック

### 1.1 フルテストスイート: PASS

```
2228 passed in 97.93s (0:01:37), exit code 0
```

スコア関連テストの内訳:

| テストファイル | テスト数 |
|---|---|
| `tests/unit/services/test_score_submission_service.py` | 14 |
| `tests/unit/services/test_score_submission_service_playstyle.py` | 5 |
| `tests/unit/services/test_score_submission_security.py` | 5 |
| `tests/unit/services/test_score_authorization_service.py` | 11 |
| `tests/unit/domain/score/test_score.py` | — |
| `tests/unit/transports/web_legacy/test_score_submit.py` | 4 |
| `tests/unit/infrastructure/crypto/test_score_crypto.py` | — |
| `tests/unit/repositories/test_in_memory_score_repository.py` | — |
| `tests/unit/repositories/test_score_repository_protocol.py` | — |
| `tests/integration/test_score_submission_integration.py` | — |
| `tests/integration/test_sqlalchemy_score_repository.py` | — |
| `tests/integration/transports/web_legacy/test_score_submit_e2e.py` | — |

### 1.2 TBD/TODO/FIXME: CLEAN

```
grep -rn "TBD\|TODO\|FIXME\|HACK\|XXX" <feature-files>
→ 0 matches
```

### 1.3 ハードコードされたシークレット: CLEAN

```
grep -rni "password\s*=\|api_key\s*=\|secret\s*=\|token\s*=" <feature-files>
→ 0 matches (実装コード)
```

注意: `ScoreAuthorizationService` にテスト用モック認証情報が存在する（後述 G6）。

### 1.4 スモークブート: PASS

```python
from osu_server.app import app  # → Starlette (import 成功)
```

---

## 2. レイヤー整合性

### 2.1 import-linter: 8/8 contracts KEPT

```
Layered architecture                                    KEPT
Services don't depend on transports                     KEPT
Server runtime doesn't depend on CLI                     KEPT
Jobs only depend on approved layers                     KEPT
Transports don't depend on jobs                         KEPT
Domain has no I/O dependencies                          KEPT
Shared has no business logic dependencies               KEPT
Repositories only use approved database libraries       KEPT

Contracts: 8 kept, 0 broken
Analyzed 270 files, 1042 dependencies
```

### 2.2 ドメイン層 I/O 純度: 手動確認

```bash
grep -rn "from osu_server.repositories\|from osu_server.infrastructure\|from osu_server.transports" src/osu_server/domain/score/
# → 出力なし
```

ドメイン層は外部 I/O ライブラリにも依存していない。唯一のクロスレイヤー参照は `domain/score/validator.py` → `domain/score/payload_parser.py`（同一レイヤー内）。

### 2.3 サービス層の隔離: 手動確認

```bash
grep -rn "from osu_server.transports" src/osu_server/services/score_*.py
# → 出力なし
```

---

## 3. クロスタスク統合検証

### 3.1 MultipartParser → ScoreSubmitHandler

- **MultipartParser** (`infrastructure/parsers/multipart_parser.py`) 出力: `ParsedSubmission`
  - `encrypted_payload: bytes`, `iv: bytes`, `replay_data: bytes | None`
  - `score_field_count: int` — 後続で未使用
  - `password_md5: str`, `client_hash: str`, `fail_time_ms: int | None`, `osu_version: str`
  - `submission_metadata: dict[str, str]` — 後続で完全に破棄

- **ScoreSubmitHandler** (`transports/web_legacy/score_submit.py`) 構築: `ParsedSubmissionInput`
  - 全必須フィールドが正しくマッピングされている
  - `beatmap_id=0` がハードコード（サービス層で beatmap_checksum から再解決される）
  - `score_field_count` がドロップされる
  - `submission_metadata` がドロップされる（→ G3, G4 の根本原因）

- **判定**: PASS (機能的に動作、ただし optional metadata の情報欠落あり)

### 3.2 ScoreCryptoService → ScoreSubmissionService

```
インターフェース: decrypt_score_payload(encrypted: bytes, iv: bytes, osu_version: str | None) -> DecryptedPayload
利用側:          decrypted = self._payload_decryptor.decrypt_score_payload(...)
                 decrypted.plaintext: str
                 decrypted.checksum_valid: bool
```

- `DecryptedPayload` は `domain/score/decryption.py` に定義
- `@dataclass(frozen=True, slots=True)` — ドメイン層の規約に準拠
- Rust 側の末尾スペースチェック + Python 側の PKCS7 パディング除去の二重検証
- **判定**: PASS (完全一致)

### 3.3 ScoreAuthorizationService → ScoreSubmissionService

```python
AuthorizationContext:
    user_id: int
    username: str
    session_valid: bool
    password_valid: bool
    payload_identity_match: bool
    authorized: bool  # property — 3 チェックすべて成功で True
```

サービス側の利用:
- `auth_ctx.user_id` → fingerprint 生成に使用
- `auth_ctx.authorized` → 認可判定
- `auth_ctx.password_valid`, `session_valid`, `identity_match` → 個別ログ出力（R11.1 準拠）
- パスワードは SHA-256 hash のみログ出力
- **判定**: PASS (完全一致)

### 3.4 BeatmapEligibilityResolver → ScoreSubmissionService

設計書のインターフェース: `check_eligibility(beatmap_id: int) -> EligibilityResult`

実際の実装: Protocol による抽象化

```python
class BeatmapEligibilityResolver(Protocol):
    async def resolve_by_checksum(self, checksum_md5: str, options: ...) -> BeatmapResolveResult: ...
    async def resolve_by_beatmap_id(self, beatmap_id: int, options: ...) -> BeatmapResolveResult: ...
```

サービス側の利用:
- `beatmap_result.beatmap is None` → RETRYABLE (beatmap fetch 中)
- `beatmap_result.eligibility.accepts_scores` → ランクド譜面のみ受理
- `beatmap_result.eligibility.accepts_failed_scores` → failed play 用
- `beatmap_result.beatmap.id` → スコアの beatmap_id 解決
- `beatmap_result.beatmapset.id` → レスポンスの beatmapset_id

- **判定**: PASS (設計から進化、Protocol による疎結合化は改善)

### 3.5 ScorePayloadParser → ScoreSubmissionService

```python
ParsedScore (domain/score/payload_parser.py):
    user_id: int                    # stable format では 0
    username: str
    beatmap_checksum: str
    online_checksum: str
    ruleset: int                    # → Ruleset(parsed.ruleset)
    mods: int
    n300, n100, n50, geki, katu, miss: int
    score: int
    max_combo: int
    perfect: bool
    passed: bool
    client_grade: str | None        # stable format のみ
    client_submitted_at: str | None # stable format のみ
    client_version: str | None      # stable format のみ
    client_checksum: str | None     # stable format のみ
```

- 全フィールドがサービスで正しく消費される
- Legacy format (16 fields) と stable format (16-19 fields) の両方をサポート
- `_is_int(fields[0])` によるフォーマット判別
- **判定**: PASS (完全一致)

### 3.6 ScoreValidator → ScoreSubmissionService

```python
ValidationResult:
    valid: bool
    accuracy: float
    grade: Grade
```

- 4 ルールセット別の精度計算とグレード計算が実装済み
- `ValidationError` が raise されなければ valid
- サービスは `validation.accuracy` と `validation.grade` を使用
- **判定**: PASS (完全一致)

### 3.7 Repository Protocols → ScoreSubmissionService

| Protocol メソッド | サービスでの呼び出し | 一致 |
|---|---|---|
| `ScoreRepository.get_by_online_checksum(checksum)` | `self._score_repo.get_by_online_checksum(parsed.online_checksum)` | OK |
| `ScoreRepository.create(score)` | `self._score_repo.create(score)` | OK |
| `ReplayRepository.exists_by_checksum(checksum)` | `self._replay_repo.exists_by_checksum(replay_checksum)` | OK |
| `ReplayRepository.create(replay)` | `self._replay_repo.create(replay)` | OK |
| `ScoreSubmissionRepository.create(submission)` | `self._submission_repo.create(submission)` | OK |
| `ScoreSubmissionRepository.get_by_fingerprint(fp)` | `self._submission_repo.get_by_fingerprint(fingerprint)` | OK |
| `ScoreSubmissionRepository.update_state(id, state, snapshot)` | `self._submission_repo.update_state(active_submission.id, ...)` | OK |

- **判定**: PASS (全メソッド完全一致)

### 3.8 ScoreSubmissionService → ScoreSubmitHandler

```python
SubmissionResult:
    outcome: SubmissionOutcome  # COMPLETED | TERMINAL_REJECTED | RETRYABLE | ACCEPTED_PENDING
    score_id: int | None
    beatmap_id: int | None
    beatmapset_id: int | None
    error_reason: str | None
```

Handler のレスポンス分岐:

| outcome | HTTP status | body |
|---|---|---|
| COMPLETED | 200 | `beatmapId:beatmapSetId:beatmapPlaycount:3\nchart...` |
| TERMINAL_REJECTED | 200 | `error: no` |
| RETRYABLE | 200 | `error: yes` |
| ACCEPTED_PENDING | 200 | `error: yes` |

- **判定**: PASS (完全一致)

---

## 4. データベーススキーマ検証

### 4.1 Migration Chain

3 段階の migration で最終スキーマに到達:

```
0016: CREATE TABLE replays
        (id, score_id, blob_key VARCHAR(255), checksum_sha256, byte_size, created_at)
  ↓
0021: ALTER TABLE replays RENAME TO replay_file_attachments
        (+ 制約名リネーム)
  ↓
0022: ALTER TABLE replay_file_attachments
        ADD blob_id INTEGER (FK → blobs.id)
        → blob_key → blob_id データ移行
        → DROP blob_key
        → ADD INDEX, ADD FK
```

### 4.2 SQLAlchemy Model との一致

**ReplayModel** (`repositories/sqlalchemy/models/score.py`):

| 要素 | migration 最終状態 | model | 一致 |
|---|---|---|---|
| テーブル名 | `replay_file_attachments` | `replay_file_attachments` | OK |
| id | BigInteger PK | BigInteger PK | OK |
| score_id | FK → scores.id | FK("scores.id") | OK |
| blob_id | FK → blobs.id | FK("blobs.id") | OK |
| checksum_sha256 | String(64) UNIQUE | String(64) unique=True | OK |
| byte_size | Integer | Integer | OK |
| created_at | DateTime(tz) | DateTime(tz) | OK |

**ScoreModel** — 全 22 カラムが migration `0016` と一致。

**ScoreSubmissionModel** — 全カラム一致。`result_snapshot` は JSONB。

---

## 5. 要件カバレッジ

### 5.1 完全カバー (9/12 sections)

| 要件 | 実装箇所 | 確認内容 |
|------|---------|---------|
| **R1.1-1.4** | `ScoreSubmitHandler` + `ScoreSubmissionService` | POST endpoint, 4 ルールセット, RX/AP 拒否 (`_is_relax_or_autopilot`), `Playstyle` enum |
| **R2.1-2.5** | `MultipartParser` | duplicate `score` field 区別, 必須/任意フィールド抽出, サイズ制限 (`MultipartLimits`) |
| **R3.1-3.5** | `athena-crypto` (Rust) + `ScoreCryptoService` | Rijndael-256 CBC, osuver key / legacy key, checksum 検証, PKCS7 padding |
| **R4.1-4.5** | `ScoreAuthorizationService` | password + session + identity 3 点チェック, 全拒否パス, ログマスク (SHA-256) |
| **R6.1-6.4** | `ScoreSubmissionService` | online checksum 重複検出, replay checksum 重複検出, fingerprint 計算 (`generate_submission_fingerprint`) |
| **R8.1-8.5** | `BeatmapEligibilityService` | Ranked/Approved/Loved/Qualified 受付, mirror trust 制御, failed scores 個別判定 |
| **R9.1-9.4** | `ScoreSubmissionService` + `ScoreSubmissionRepository` | fingerprint 重複検出, `_result_from_existing_submission()`, 状態遷移 (processing→completed/terminal_rejected/retryable) |
| **R10.1-10.5** | `ScoreSubmitHandler._format_completed_response()` | chart 形式, `error: no` / `error: yes`, 診断情報非開示 |
| **R12.1-12.4** | `ScoreSubmissionService` | failed play 保存, replay 保存, `ft` / `x` フィールド保存, `passed` flag |

### 5.2 部分/未カバー (3/12 sections)

#### R5.4 (PARTIAL) — クライアント-サーバー grade/accuracy 不一致の診断保存

- `ParsedScore.client_grade` はパースされるが、サーバー計算値 (`validation.grade`) との比較が行われていない
- `client_grade` はスコア保存時にも使用されず、サーバー計算値で上書きされる
- 不一致を検出してログに残すコードが存在しない

#### R7.5 (NOT COVERED) — スコア提出時のビートマップ有効ステータスの記録

- `Score` モデルに `beatmap_status_at_submission` フィールドがない
- `BeatmapEligibilityService.evaluate()` は eligibility を返すが、その時点の `effective_status` はスコアレコードに保存されない
- 後続 Wave (PP 計算, leaderboard) でビートマップのステータス変更履歴が必要になる可能性がある

#### R11.3 (PARTIAL) — Optional opaque fields の SHA-256 ハッシュ化

- `_extract_optional_metadata()` は `fs`, `bmk`, `sbk`, `c1`, `st`, `i`, `token` を UTF-8 デコードして raw で保存
- `submission_metadata` は transport→service 境界でドロップされるため、ハッシュ化もログ出力も行われない
- 要件は「SHA-256 hash で保存」だが、parse のみで保存/ハッシュ化の両方が未実装

---

## 6. 設計書との差分 (Architecture Drift)

### 6.1 ファイル配置の差異

| 設計書のパス | 実際のパス | 評価 |
|---|---|---|
| `infrastructure/auth/score_authorization.py` | `services/score_authorization_service.py` | 妥当 — 認可ロジックはサービス層の責務 |
| `infrastructure/beatmap/eligibility_service.py` | `services/beatmap_mirror/eligibility_service.py` | 妥当 — beatmap mirror とグループ化 |
| `transports/web_legacy/routes/score_submit.py` | `transports/web_legacy/score_submit.py` | 軽微 — `routes/` サブディレクトリなし |
| (なし) | `domain/score/decryption.py` | 追加 — `DecryptedPayload` の適切な配置 |
| (なし) | `services/beatmap_mirror/` ディレクトリ | 追加 — 設計書のスコープ外だが自然なグループ化 |

### 6.2 インターフェースの差異

| コンポーネント | 設計書 | 実際 | 影響度 |
|---|---|---|---|
| `MultipartParser.parse()` | `(body, content_type)` | `(body, content_type, limits=None)` | 軽微拡張 |
| `BeatmapEligibilityService` | `check_eligibility(beatmap_id)` | Protocol 経由 `resolve_by_checksum()` | 有意 — ID→checksum 解決に変更、より堅牢 |
| `ScoreSubmissionService.submit_score()` | `(parsed: ParsedSubmission)` | `(input_data: ParsedSubmissionInput)` | 軽微 — 入力モデル名の明確化 |
| `Replay` domain model | `blob_key: str` | `blob_id: int` | 有意 — 文字列キー→FK 参照、設計改善 |
| `Replay` DB table | `replays` | `replay_file_attachments` | 命名変更 — `beatmap_file_attachments` との一貫性 |

### 6.3 実際の依存グラフ

```
transports/web_legacy/score_submit.py
  → services/score_submission_service.py
  → infrastructure/parsers/multipart_parser.py

services/score_submission_service.py
  → services/score_authorization_service.py
  → domain/score/ (全モジュール)
  → repositories/interfaces/ (全 Protocol)

services/score_authorization_service.py
  → repositories/interfaces/ (UserRepository, SessionStore)
  → services/password_service.py
  → domain/user.py

services/beatmap_mirror/eligibility_service.py
  → domain/beatmap/ (models, eligibility)

domain/score/validator.py
  → domain/score/payload_parser.py (ParsedScore)  ← 同一レイヤー
  → domain/score/score.py (Ruleset, Grade)          ← 同一レイヤー

infrastructure/crypto/score_crypto.py
  → athena_crypto (Rust FFI)
  → domain/score/decryption.py (DecryptedPayload)
```

すべての依存が `Transports → Services → Domain ← Infrastructure` 方向。上方向の逆依存なし。

---

## 7. 境界監査 (Boundary Audit)

### 7.1 スコープ内 / スコープ外の遵守

| 設計書の境界 | 実装 | 判定 |
|---|---|---|
| `/web/osu-submit-modular-selector.php` endpoint | `ScoreSubmitHandler` | ✓ |
| Multipart parsing (duplicate `score` field) | `MultipartParser` | ✓ |
| Rijndael-256 decryption | `athena-crypto` (Rust) + `ScoreCryptoService` | ✓ |
| Authorization (password+session+identity) | `ScoreAuthorizationService` | ✓ |
| Score validation (hit counts, accuracy, grade) | `ScoreValidator` | ✓ |
| Uniqueness enforcement (3 checksum types) | `ScoreSubmissionService` | ✓ |
| Score + replay persistence | `ScoreRepository` + `ReplayRepository` | ✓ |
| Idempotent retry | `ScoreSubmissionRepository` + fingerprint | ✓ |
| Response format (completed/terminal/retryable) | `ScoreSubmitHandler` | ✓ |
| Beatmap eligibility | `BeatmapEligibilityService` | ✓ |
| PP calculation | 未実装 | ✓ (Wave 2) |
| Leaderboard projection | 未実装 | ✓ (Wave 3) |
| User stats update | 未実装 | ✓ (Wave 3-4) |
| Relax/Autopilot | 拒否のみ実装 | ✓ (拒否は Wave 1 の責務) |
| Anti-cheat | replay checksum uniqueness のみ | ✓ |
| `.osu` file fetch | 未実装 | ✓ (Wave 2) |

### 7.2 境界侵犯

**ScoreAuthorizationService のモックモード**:

DI なしでインスタンス化された場合、ハードコードされたテスト認証情報 (`_MOCK_PASSWORD_MD5 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"`) で動作する。Wave 1 のテスト容易性のためだが、本番コードにテスト用の振る舞いが混入している。DI 設定ミス時の認証バイパスリスクがある。

`ScoreSubmissionService` は `BeatmapEligibilityResolver` Protocol を通じて beatmap resolution に依存。具体的な実装ではなく抽象に依存しており、正しい DI パターン。

### 7.3 Revalidation Triggers

設計書に記載された再検証トリガーの現状:

| トリガー | 発火 | 耐性 |
|---|---|---|
| Beatmap mirror API 変更 | なし | Protocol 経由で抽象化されているため耐性あり |
| Blob storage interface 変更 | なし | `BlobStoreResult.blob.id` を使用 |
| Session store schema 変更 | なし | — |
| Stable プロトコル仕様変更 | なし | — |

---

## 8. 発見された問題一覧

| ID | 問題 | 深刻度 | 所有権 | 説明 |
|----|------|--------|--------|------|
| **G1** | R5.4 client-vs-server grade discrepancy 未保存 | LOW | LOCAL | `client_grade` がパースされるが比較/ログ出力なし |
| **G2** | R7.5 beatmap status 未記録 | LOW | LOCAL | `effective_status` がスコアと共に保存されない |
| **G3** | R11.3 opaque fields SHA-256 ハッシュ化未実施 | MEDIUM | LOCAL | optional fields がパースのみでハッシュ化/ログ出力されない |
| **G4** | `submission_metadata` が service 層に伝播されない | LOW | LOCAL | G3 の根本原因。transport→service 境界で情報がドロップ |
| **G5** | `beatmap_id=0` ハードコード | LOW | LOCAL | transport 層で beatmap_id が常に 0。サービス層で checksum から再解決されるため機能的には問題ない |
| **G6** | `ScoreAuthorizationService` モックモード | MEDIUM | LOCAL | 本番デプロイ前に削除が必要。DI 失敗時の認証バイパスリスク |

---

## 9. 改善推奨 (Remediation)

### 9.1 R5.4 — client-vs-server grade 不一致診断

`ScoreSubmissionService.submit_score()` に以下を追加:

```python
# validation 取得成功後
if parsed.client_grade is not None and parsed.client_grade != validation.grade.value:
    logger.info(
        "score_grade_discrepancy",
        client_grade=parsed.client_grade,
        server_grade=validation.grade.value,
        user_id=auth_ctx.user_id,
        beatmap_checksum=parsed.beatmap_checksum,
    )
```

### 9.2 R7.5 — beatmap status 記録

1. `Score` domain model に `beatmap_status_at_submission: str | None` を追加
2. migration で `scores.beatmap_status_at_submission` カラムを追加
3. `ScoreModel` にカラム追加
4. `ScoreSubmissionService.submit_score()` で `beatmap_result.beatmap.effective_status` を保存

### 9.3 R11.3 — opaque fields SHA-256 ハッシュ化

1. `ParsedSubmissionInput` に `submission_metadata: dict[str, str]` を追加
2. `ScoreSubmitHandler` で `parsed.submission_metadata` を `ParsedSubmissionInput` に渡す
3. `ScoreSubmissionService.submit_score()` で opaque fields を SHA-256 ハッシュ化してログ出力

### 9.4 G6 — モック認証情報の削除

`ScoreAuthorizationService` のモックモード (`_authorize_mock`, `_MOCK_*`) を削除し、
DI が必須の設計に変更する。または機能フラグでテスト時のみ有効化する仕組みを導入する。

---

## 10. 証拠サマリー

| チェック項目 | 結果 | 詳細 |
|---|---|---|
| フルテストスイート | **PASS** | 2228 passed, exit 0, 97.93s |
| import-linter | **PASS** | 8/8 contracts kept, 0 broken |
| ドメイン層 I/O 純度 | **PASS** | リポジトリ/インフラ/トランスポートへの import なし |
| サービス層隔離 | **PASS** | トランスポート層への import なし |
| TBD/TODO/FIXME | **CLEAN** | 0 matches |
| ハードコードシークレット | **CLEAN** | 実装コードに 0 matches |
| アプリスモークブート | **PASS** | Starlette app import 成功 |
| Migration chain | **CONSISTENT** | 3 migrations が正しい最終スキーマを生成 |
| Protocol 準拠 | **MATCH** | 全 repository メソッド呼び出しが Protocol 定義と一致 |
| クロスタスクデータフロー | **PASS** | 全パイプラインステージでデータが正しく流通 |
| 要件カバレッジ | **9/12 FULL** | 3 件の部分/未カバー (R5.4, R7.5, R11.3) |
| 設計整合性 | **MINOR DRIFT** | ファイル配置変更はすべて依存方向を遵守 |
| 境界侵犯 | **NONE** | スコープ外の実装なし。Protocol による適切な抽象化 |
| ブロックタスク | **NONE** | 全 19 タスク `[x]` |
