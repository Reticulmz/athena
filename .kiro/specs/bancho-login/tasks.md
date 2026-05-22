# Implementation Plan

- [ ] 1. Foundation: ドメインモデル・スキーマ・プロジェクト設定

- [x] 1.1 ドメインモデル定義 + 共有エラー型
  - User dataclass: id, username, safe_username, email, password_hash, country, created_at, updated_at + `normalize_username()` 静的メソッド（小文字化 + スペース→アンダースコア）
  - Role dataclass: id, name, permissions (Privileges IntFlag), position
  - Privileges IntFlag: NONE, NORMAL, VERIFIED, SUPPORTER, MODERATOR, ADMIN, DEVELOPER, TOURNAMENT, UNRESTRICTED
  - ClientPermissions IntFlag: NORMAL(1), MODERATOR(2), SUPPORTER(4), PEPPY(8), DEVELOPER(16)
  - SessionData dataclass: user_id, username, privileges, country, osu_version, utc_offset, display_city, client_hashes, pm_private
  - LoginResult IntEnum: AUTHENTICATION_FAILED(-1) 〜 PASSWORD_RESET(-7) の全コード定義
  - LoginRequest dataclass + ClientInfo dataclass
  - LoginResponse dataclass: token, user, privileges, country, session_data
  - RegistrationForm dataclass: username, email, password
  - RegistrationResult dataclass: success, errors (dict[str, list[str]])
  - AuthenticationError(AppError): result: LoginResult
  - RegistrationError(AppError): errors: dict[str, list[str]]
  - `basedpyright src/osu_server/domain/ src/osu_server/shared/errors.py` が成功すること
  - ユニットテスト: normalize_username() の正規化、Privileges OR 結合、LoginResult 値
  - _Requirements: 1.3, 3.1, 3.2, 3.3, 3.4, 4.1, 5.4, 5.5, 5.6, 8.2, 8.4_

- [x] 1.2 SQLAlchemy ORM モデル + Alembic マイグレーション + シードデータ
  - SQLAlchemy User モデル（Base 継承、users テーブル）: id SERIAL PK, username VARCHAR(15), safe_username VARCHAR(15) UNIQUE, email VARCHAR(255) UNIQUE, password_hash VARCHAR(255), country VARCHAR(2) DEFAULT 'XX', created_at/updated_at TIMESTAMPTZ
  - SQLAlchemy Role モデル（roles テーブル）: id SERIAL PK, name VARCHAR(32) UNIQUE, permissions INTEGER, position INTEGER
  - UserRole 関連テーブル（user_roles）: user_id FK → users.id, role_id FK → roles.id, 複合 PK
  - DisallowedUsername モデル（disallowed_usernames テーブル）: id SERIAL PK, safe_username VARCHAR(15) UNIQUE, created_at TIMESTAMPTZ
  - Alembic マイグレーションファイル生成（全4テーブル一括）
  - シードデータ投入: Default ロール (NORMAL|VERIFIED|UNRESTRICTED, position=0), Admin ロール (全フラグ ON, position=100)
  - `alembic upgrade head` が成功し、4テーブル + 2シードロールが存在すること
  - _Requirements: 1.2, 3.6, 8.6_

- [x] 1.3 プロジェクト設定更新
  - pyproject.toml: httpx を dev 依存から production dependencies に移動
  - import-linter 契約更新: services 層のインポートルール追加
  - `import-linter` が新規契約で成功すること
  - _Requirements: 4.5_

- [x] 1.4 SessionStore Protocol 拡張（TTL リフレッシュ）
  - SessionStore Protocol に `refresh(token: str) -> bool` メソッド追加
  - InMemorySessionStore: 存在チェックのみ（TTL 概念なし → True/False 返却）
  - RedisSessionStore: Redis `EXPIRE` コマンドで TTL リセット
  - 既存テストに refresh テストケース追加（存在するトークン → True、存在しないトークン → False）
  - `pytest tests/unit/` の SessionStore 関連テストが全パスすること
  - _Requirements: 7.2, 10.2_

- [ ] 2. Repository 層実装

- [x] 2.1 (P) UserRepository（Protocol + InMemory + SQLAlchemy）
  - UserRepository Protocol 定義: create, get_by_id, get_by_safe_username, get_by_email, is_username_disallowed, add_disallowed_username
  - InMemoryUserRepository 実装（テスト用、dict ベース、safe_username で case-insensitive 検索）
  - SQLAlchemyUserRepository 実装（async_sessionmaker 使用）
  - Protocol 準拠テスト（parametrized fixture で InMemory + SQLAlchemy 両方テスト）: CRUD、safe_username 検索、email 検索、禁止ユーザー名チェック、重複エラー
  - `pytest tests/unit/repositories/test_user_repository.py` が全パスすること
  - _Requirements: 1.3, 1.5, 1.6, 1.7, 3.6, 5.1_
  - _Boundary: UserRepository_

- [x] 2.2 (P) RoleRepository（Protocol + InMemory + SQLAlchemy）
  - RoleRepository Protocol 定義: get_by_id, get_by_name, get_roles_for_user, assign_role, get_default_role
  - InMemoryRoleRepository 実装（シードデータ付きで初期化可能）
  - SQLAlchemyRoleRepository 実装
  - Protocol 準拠テスト: ロール取得、ユーザーへのロール付与、デフォルトロール取得、複数ロール取得（position 昇順ソート）
  - `pytest tests/unit/repositories/test_role_repository.py` が全パスすること
  - _Requirements: 8.1, 8.3, 8.4, 8.6_
  - _Boundary: RoleRepository_

- [ ] 3. Infrastructure・サービス層実装

- [x] 3.1 (P) PasswordService（ハッシュ/検証）
  - argon2-cffi PasswordHasher を使用した hash() / verify() 実装
  - `asyncio.get_running_loop().run_in_executor(None, ...)` でイベントループブロック回避
  - prepare_password(plain_password): 平文 → hashlib.md5() → argon2id の一連処理（登録時用）
  - テスト: ラウンドトリップ（hash → verify 成功）、不一致検出、prepare_password で生成したハッシュが verify(hash, md5(password)) で一致すること
  - `pytest tests/unit/services/test_password_service.py` が全パスすること
  - _Requirements: 4.1, 4.2, 4.3_
  - _Boundary: PasswordService_

- [x] 3.2 (P) HIBPClient + パスワードセキュリティ強化
  - HIBPClient: httpx.AsyncClient で `GET https://api.pwnedpasswords.com/range/{prefix}` 呼び出し、SHA-1 先頭5文字 → サフィックス照合
  - PasswordService.check_hibp(): HIBPClient 呼び出しで漏洩パスワード判定
  - API 到達不能時は False を返す（フォールバック）
  - カスタム禁止パスワードリスト: 設定ベース（AppConfig に banned_passwords: list[str] 追加）で管理
  - PasswordService.is_password_banned(): HIBP チェック + カスタムリスト照合の統合メソッド。HIBP 不達時はカスタムリストのみ
  - テスト: 漏洩パスワード検出（モック）、非漏洩パスワード、API 不達フォールバック、カスタムリスト照合、統合メソッドの優先順位
  - `pytest tests/unit/services/test_password_service.py tests/unit/infrastructure/test_hibp.py` が全パスすること
  - _Requirements: 4.4, 4.5, 4.6_
  - _Boundary: HIBPClient, PasswordService_

- [x] 3.3 (P) CountryResolver（Protocol + Cloudflare 実装 + 国コード変換）
  - CountryResolver Protocol: resolve(request) -> str（2文字の国コード）
  - CloudflareCountryResolver: `request.headers.get("CF-IPCountry", "XX")`
  - 国コード変換ユーティリティ: 2文字コード（"JP", "US" 等）→ osu! 数値 ID への変換テーブル。不明コードは 0
  - テスト: Cloudflare ヘッダあり → 国コード返却、ヘッダなし → "XX"、文字列→数値変換（既知コード、不明コード）
  - `pytest tests/unit/infrastructure/test_country_resolver.py` が全パスすること
  - _Requirements: 9.1, 9.2, 9.3_
  - _Boundary: CountryResolver_

- [ ] 3.4 (P) PermissionService（RBAC 計算 + クライアントフラグ変換）
  - compute_permissions(user_id): RoleRepository から全ロール取得 → permissions を OR 結合して Privileges 返却
  - to_client_flags(privileges): Privileges → ClientPermissions 変換（MODERATOR→2, SUPPORTER→4, ADMIN→8, DEVELOPER→16, else→1）
  - テスト: 単一ロール計算、複数ロール OR 結合、クライアントフラグ変換（全組み合わせ）、ロールなし → Privileges.NONE
  - `pytest tests/unit/services/test_permission_service.py` が全パスすること
  - _Requirements: 8.3, 8.5_
  - _Boundary: PermissionService_
  - _Depends: 2.2_

- [ ] 4. ビジネスロジック（AuthService）

- [ ] 4.1 AuthService.register()（登録オーケストレーション）
  - バリデーション: ユーザー名（2-15文字、`[a-zA-Z0-9_ -]+`、スペース+アンダースコア共存不可）、パスワード（8-32文字、ユニーク文字数4以上）、メール形式
  - 重複チェック: UserRepository.get_by_safe_username()、UserRepository.get_by_email()
  - 禁止ユーザー名チェック: UserRepository.is_username_disallowed()
  - パスワードセキュリティ: PasswordService.is_password_banned()（HIBP + カスタムリスト統合）
  - check_only モード（check=1）: バリデーションのみ実行、アカウント作成しない → RegistrationResult 返却
  - 作成モード（check=0）: PasswordService.prepare_password() → UserRepository.create() → RoleRepository.get_default_role() + assign_role() でデフォルトロール付与
  - 登録時に VERIFIED フラグをデフォルトロール経由で即付与（メール認証スキップ、Req 8.7 対応）
  - テスト: 正常登録（ユーザー作成 + デフォルトロール付与確認）、各バリデーションエラー、重複チェック、禁止名、HIBP、check_only モード、VERIFIED 即付与確認
  - `pytest tests/unit/services/test_auth_service.py` の register 関連テストが全パスすること
  - _Requirements: 1.1, 1.2, 1.4, 1.5, 1.6, 1.7, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 3.5, 4.4, 4.5, 4.6, 8.7_
  - _Depends: 2.1, 2.2, 3.1, 3.2_

- [ ] 4.2 AuthService.login()（ログインオーケストレーション）
  - UserRepository.get_by_safe_username(normalize(username)) でユーザー検索
  - PasswordService.verify(user.password_hash, password_md5) でパスワード照合
  - 認証失敗時: LoginResult.AUTHENTICATION_FAILED (-1) 返却（ユーザー不在/パスワード不一致を区別しない）
  - サーバーエラー時: try/except で LoginResult.SERVER_ERROR (-5) 返却
  - 認証成功時: PermissionService.compute_permissions(user.id) → CountryResolver.resolve(request) → SessionStore.delete(既存) + SessionStore.create(新規) → LoginResponse 構築
  - SessionData を dataclasses.asdict() で変換して SessionStore に格納
  - テスト: 認証成功（LoginResponse 全フィールド検証）、ユーザー不在、パスワード不一致、既存セッション破棄+新規作成（シングルセッション後勝ち）、サーバーエラーハンドリング
  - `pytest tests/unit/services/test_auth_service.py` の login 関連テストが全パスすること
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.7, 5.8, 10.1, 10.3_
  - _Depends: 3.3, 3.4_

- [ ] 5. Transport 層実装

- [ ] 5.1 LoginParser（ログインリクエストパーサー）
  - parse_login_request(body: bytes) → LoginRequest: body を改行で3行に分離（username, password_md5, client_info_raw）
  - parse_client_info(raw: str) → ClientInfo: パイプ区切りで分離（osu_version|utc_offset|display_city|client_hashes|pm_private）
  - 型変換: utc_offset → int、display_city → bool（"1"/"0"）、pm_private → bool
  - テスト: 正常パース、不正フォーマット（行数不足、空ボディ）、client_info フィールド不足、型変換エッジケース
  - `pytest tests/unit/transports/test_login_parser.py` が全パスすること
  - _Requirements: 5.2, 5.3_
  - _Boundary: LoginParser_

- [ ] 5.2 (P) LoginHandler（POST / ログイン + ポーリング stub）
  - bancho_handler(request): `osu-token` ヘッダの有無でログイン/ポーリングを判別
  - _handle_login(request): LoginParser.parse_login_request() → AuthService.login() → 成功時: build_login_response_stream() でS2Cパケットストリーム構築 → Response(content=stream, headers={"cho-token": token})、失敗時: Response(content=login_reply(error_code))
  - build_login_response_stream(login_response): 12個のS2Cビルダー関数を順次呼び出し、b"".join() で結合。login_reply, protocol_version, login_permissions（to_client_flags 変換）, user_presence（country_id 数値変換使用）, user_stats, channel_info, channel_info_end, friends_list, silence_end, user_presence_bundle
  - _handle_polling(request): SessionStore.get(token) → 存在すれば SessionStore.refresh(token) + Response(空body)、不在なら Response(content=login_reply(-1))
  - テスト: ログイン成功（cho-token ヘッダ + パケットストリームにlogin_reply正値が含まれること）、認証失敗（login_reply(-1)）、ポーリング成功（空body + TTL延長）、セッション不在ポーリング
  - `pytest tests/unit/transports/test_login_handler.py` が全パスすること
  - _Requirements: 5.7, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 6.10, 7.1, 7.2, 7.3, 7.4_
  - _Boundary: LoginHandler_
  - _Depends: 4.2, 5.1_

- [ ] 5.3 (P) RegistrationHandler（POST /users）
  - register_handler(request): フォームデータパース — user[username], user[user_email], user[password], check パラメータ
  - check パラメータ判定: int(check) == 1 → AuthService.register(form, check_only=True)、== 0 → AuthService.register(form, check_only=False)
  - 成功時: Response(content=b"ok", status_code=200)
  - 失敗時: Response(content=json.dumps({"form_error": {"user": errors}}), status_code=400)
  - テスト: 正常登録 → b"ok"、バリデーションエラー → 400 + form_error JSON、check=1 → バリデーションのみ
  - `pytest tests/unit/transports/test_registration.py` が全パスすること
  - _Requirements: 1.1, 1.4, 2.1, 2.2, 2.3_
  - _Boundary: RegistrationHandler_
  - _Depends: 4.1_

- [ ] 6. 統合・検証

- [ ] 6.1 DI 統合 + ルート登録 + サブドメインルーティング
  - providers.py 更新: UserRepository, RoleRepository（環境別: InMemory/SQLAlchemy）, PasswordService, HIBPClient, httpx.AsyncClient, PermissionService, AuthService, CountryResolver（CloudflareCountryResolver）の DI 登録
  - httpx.AsyncClient の lifecycle 管理: startup で作成、shutdown hook で aclose()
  - app.py 更新: Starlette の Host ベースルーティングに変更。`c.$DOMAIN` → bancho トランスポート（POST / ログイン/ポーリング）、`osu.$DOMAIN` → web_legacy トランスポート（POST /users 登録等）
  - POST / を bancho_handler に差し替え、/web（osu.$DOMAIN）に registration routes 追加
  - `python -c "from osu_server.app import app"` がインポートエラーなく成功すること
  - `import-linter` が成功すること
  - _Requirements: 1.1, 5.1_
  - _Depends: 5.2, 5.3_

- [ ] 6.2 E2E 統合テスト
  - 登録 → ログインフロー: POST /users (check=0) → b"ok" → POST / (credentials) → cho-token + パケットストリーム検証
  - 登録バリデーション: POST /users (check=1) → 200 ok → DB にユーザー未作成
  - 登録エラー: 重複ユーザー名 → 400 form_error、短すぎるパスワード → 400 form_error
  - ログイン成功: パケットストリームに login_reply(正の user_id), protocol_version, login_permissions が含まれること
  - ポーリング stub: ログイン → cho-token で POST / → 200 空 body
  - 再ログイン: ログイン → 再ログイン → 新 cho-token 返却 + 旧トークンでポーリング失敗
  - 認証失敗: 未登録ユーザーでログイン → login_reply(-1)
  - `pytest tests/integration/` が全パスすること
  - _Requirements: 1.1, 1.2, 1.4, 1.5, 2.1, 2.2, 2.3, 5.1, 5.4, 5.7, 5.8, 6.1, 6.2, 6.3, 6.10, 7.1, 7.2, 7.3, 7.4, 10.1, 10.2, 10.3, 10.4_
  - _Depends: 6.1_
