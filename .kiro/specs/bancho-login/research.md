# Research & Design Decisions

## Summary
- **Feature**: `bancho-login`
- **Discovery Scope**: Complex Integration（新規ドメイン + 既存基盤との統合）
- **Key Findings**:
  - argon2-cffi はイベントループをブロックする → `run_in_executor` 必須
  - HIBP k-Anonymity API はレート制限なし、API キー不要、httpx で簡単に呼べる
  - SessionStore は `dict[str, object]` を受け取る → 型安全な SessionData dataclass で wrap

## Research Log

### argon2-cffi の非同期互換性
- **Context**: パスワードハッシュに argon2id を使用。async ハンドラ内での呼び出し方法を確認
- **Sources**: argon2-cffi 公式ドキュメント
- **Findings**:
  - `PasswordHasher().hash()` / `.verify()` は C バインディングで同期的にブロック
  - `asyncio.get_running_loop().run_in_executor(None, ph.hash, password)` で回避
  - デフォルトパラメータ（time_cost=3, memory_cost=65536 KiB, parallelism=4, argon2id）は OWASP 推奨に合致
  - `check_needs_rehash()` でパラメータ変更後の透過的リハッシュが可能
- **Implications**: PasswordService 内で `run_in_executor` をラップ。将来のパラメータ変更にも `check_needs_rehash` で対応可能

### HIBP Passwords API (k-Anonymity)
- **Context**: 登録時に漏洩パスワードをチェック
- **Sources**: haveibeenpwned.com API ドキュメント
- **Findings**:
  - エンドポイント: `GET https://api.pwnedpasswords.com/range/{SHA1_PREFIX_5}`
  - レート制限なし、API キー不要
  - レスポンス: `{35-char suffix}:{count}` の行リスト（約800行）
  - `Add-Padding: true` ヘッダでプライバシー強化可能
- **Implications**: httpx を新規依存として追加。薄いクライアントを自作（ライブラリ不要）

### Starlette リクエスト/レスポンス処理
- **Context**: POST / と POST /users のハンドラ実装パターン
- **Findings**:
  - Raw body: `await request.body()` — bancho ログイン用
  - Form data: `async with request.form() as form:` — 登録フォーム用
  - Response: `Response(content=bytes, headers={"cho-token": token}, media_type="application/octet-stream")`
  - `request.body()` と `request.stream()` は排他的

### 既存コードベース分析
- **Context**: 統合ポイントの特定
- **Findings**:
  - DI Container: `register_singleton` / `resolve` パターン、asyncio.Lock でスレッドセーフ
  - SessionStore: Protocol + InMemory + Redis の3層。`create(user_id, token, data)` で既存セッション自動置換
  - S2C ビルダー12関数が実装済み、全て `bytes` を返す
  - import-linter: Transports → Services → Domain → Repositories → Infrastructure → Shared
  - テスト: pytest fixtures、InMemory 実装でユニットテスト、TestClient で統合テスト

## Design Decisions

### Decision: サービス層の3分割
- **Context**: 認証フロー（login/register）、パスワード処理、権限計算の責務を分離
- **Alternatives**:
  1. AuthService 1つに全部 → 肥大化、テスト困難
  2. Login + Registration 分離 → 共通処理（パスワード照合）の重複
  3. AuthService + PasswordService + PermissionService → 各責務が明確
- **Selected**: 選択肢3
- **Rationale**: PasswordService はブロッキング処理 + 外部 API、PermissionService は RBAC 計算という独立した責務。AuthService はオーケストレーションに集中
- **Trade-offs**: サービス数が増えるが、各サービスのテストが単純になる

### Decision: DisallowedUsername を UserRepository に統合
- **Context**: 禁止ユーザー名の管理方法
- **Alternatives**:
  1. 独立 Repository → 過剰な抽象化
  2. UserRepository にメソッド追加 → 十分なスコープ
- **Selected**: 選択肢2
- **Rationale**: ユーザー登録の文脈でしか使わない。将来の管理 UI で分離の必要が生じたら、その時点でリファクタリング

### Decision: CountryResolver Protocol の維持
- **Context**: Cloudflare ヘッダ1つからの取得に Protocol が必要か
- **Selected**: Protocol を維持
- **Rationale**: GeoIP フォールバックが次 spec で予定済み。コスト極小（Protocol 1メソッド、実装3行）。テスト時のモック容易

### Decision: SessionData dataclass
- **Context**: SessionStore の `dict[str, object]` に型安全性を導入
- **Selected**: `@dataclass(slots=True)` で SessionData を定義
- **Rationale**: プロジェクト規約に合致。`asdict()` で SessionStore 互換。復元時は `SessionData(**data)` で型安全

### Decision: 権限ビットフラグ定義
- **Context**: RBAC の Permission 体系
- **Selected**: IntFlag 8フラグ（NONE, NORMAL, VERIFIED, SUPPORTER, MODERATOR, ADMIN, DEVELOPER, TOURNAMENT, UNRESTRICTED）
- **Default Role シード**: Default (NORMAL|VERIFIED|UNRESTRICTED, position=0), Admin (全フラグ, position=100)
- **Client 変換**: MODERATOR→NOMINATOR=2, SUPPORTER→4, ADMIN/DEVELOPER→PEPPY=16, TOURNAMENT→TOURNAMENT_STAFF=32, else→1

## Risks & Mitigations
- **argon2 ブロッキング**: `run_in_executor` でイベントループブロック回避
- **HIBP API 不達**: カスタム禁止リストへのフォールバック（Req 4.5-4.6）
- **httpx 新規依存**: 軽量、async ネイティブ、広く使用されているため低リスク
- **セッション競合**: SessionStore の atomic Lua スクリプトで TOCTOU 回避済み

## References
- [argon2-cffi ドキュメント](https://argon2-cffi.readthedocs.io/)
- [HIBP Passwords API](https://haveibeenpwned.com/API/v3#PwnedPasswords)
- [Starlette Requests](https://www.starlette.io/requests/)
- [bancho-documentation Wiki](https://github.com/Lekuruu/bancho-documentation/wiki)
- [bancho.py 登録実装](https://github.com/osuAkatsuki/bancho.py)
