# Tech Steering

## 確定済み技術スタック (from design doc)

| レイヤー | 技術 | 備考 |
|----------|------|------|
| 言語 | Python 3.14+ | uv でパッケージ管理 |
| ASGI | uvicorn | app プロセス |
| ルーティング | Starlette (bancho/web_legacy/signalr), FastAPI (api) | |
| バイナリプロトコル | Caterpillar | 宣言的定義、parse + build |
| API I/O | Pydantic v2 | ドメイン層では使わない |
| ドメインモデル | `@dataclass(slots=True)` | 標準ライブラリのみ |
| ORM | SQLAlchemy 2.0 async + asyncpg | Alembic でマイグレーション |
| ジョブキュー | taskiq + taskiq-redis | redis-py 経由で Valkey に接続、async ネイティブ |
| EventBus | 自前実装 (Valkey Pub/Sub + in-memory) | ~40行の軽量実装 |
| DI | Dishka + starlette-dishka | ADR 0002 で採用決定。app / worker / test の依存構成は `composition/providers/` が所有する |
| 型チェック | basedpyright (strict) | Pyright フォーク。conformance 95.7%、uv dev dependency でインストール |
| Lint/Format | ruff | |
| テスト | pytest + pytest-asyncio | |
| import 規則 | import-linter | レイヤー違反検出 |
| 環境構築 | devenv (Nix) | 設定済み |

## 追加決定事項

| 項目 | 選定 | 理由 |
|------|------|------|
| パスワードハッシュ | argon2-cffi (argon2id) | stable は MD5 送信 → サーバーで argon2id(md5) 保存。passlib はメンテ停滞 |
| Valkey クライアント | valkey-glide | Valkey 公式クライアント、async ネイティブ、Redis プロトコル互換 |
| 統合 Web App | Next.js App Router + HeroUI | Public / User / Admin / Ops workflows を統合する first-party Web App として成熟度と運用実績を優先する。Athena backend の source of truth は Python の Starlette + FastAPI に置き、Next.js は Web App / BFF 補助層として扱う |
| Web App API 接続 | OpenAPI generated client / WebUI 専用 API contract | Python backend の API contract を明示し、Web App は domain service や repository を直接 import しない |
| Next.js backend features | Thin frontend / BFF 補助層に限定 | Route Handler / Server Actions は cookie、session、CSRF、軽い response shaping など Web App 固有の補助処理に限定する。Domain mutation の正規経路や public API contract は FastAPI + OpenAPI に置く |
| API surface policy | Public API / Web App API / Admin-Ops API を分離 | Web App API は first-party 専用だが browser から露出する前提で設計する。隠されていることを security boundary にせず、認証・認可・CSRF・audit によって保護する。Public API とは互換性保証とドキュメント公開範囲を分ける |
| Public API versioning | URL path versioning `/api/public/v1/*` | Public API は URL path で version を切る。`v1` 内では additive change を基本にし、破壊的変更は新しい path version に逃がす。OpenAPI と公開 docs が route と直感的に対応することを優先する |
| Public API deprecation | Minimum 6 months + `Deprecation` / `Sunset` headers | Deprecated Public API version / endpoint は最低6か月維持する。Response header と公開 docs で deprecation status、sunset date、移行先を告知し、外部 integration が計画的に移行できる状態にする |
| Web App API route | Same-origin `/api/web/*` | Athena Web App と同一 origin で公開し、reverse proxy / Starlette routing から FastAPI の Web App API surface へ流す。CORS と cookie scope の複雑さを避け、Web App 専用 API であることを path で明示する |
| Web App authentication | FastAPI-issued server-side session cookie | FastAPI が Web App Session を発行し、HttpOnly / Secure / SameSite=Lax cookie で browser に保持させる。Next.js は token を localStorage に保持せず、thin frontend / BFF 補助層として cookie 前提で表示制御と中継を行う |
| Web App session storage | Valkey TTL active session + PostgreSQL durable state | Web App Session の active state は Valkey の TTL 付き state とし、PostgreSQL は user state、authorization source、audit / security event の source of truth にする。強制ログアウトや権限更新は session authorization refresh / versioning で反映する |
| Web App session lifecycle | Idle timeout + absolute lifetime + session rotation | 通常利用中は idle TTL を延長するが、absolute lifetime は超えない。Login、privilege escalation、重要操作前後では session ID を rotation し、stale session や fixation risk を抑える |
| Web App session defaults | Configurable: idle 12h / absolute 30d / sudo 15m | 初期 default として idle timeout 12時間、absolute lifetime 30日、Web App Sudo Mode window 15分を使う。値は AppConfig などの運用設定で変更可能にする |
| Web App Sudo Mode scope | Sensitive operations only | GitHub の Sudo mode に近い再認証済み状態として扱う。Password/email 変更、2FA 設定、moderation mutation、Admin/Ops mutation、Billing 操作、API token 発行・削除を初期対象にする。通常の閲覧、低リスク profile edit、一般的な navigation には要求しない |
| Operator intent confirmation | Destructive / high-impact moderation and Admin/Ops operations | Web App Sudo Mode とは別に、破壊的または高影響な moderation / Admin / Ops operation では対象、操作内容、必要に応じた理由入力を要求し、audit record に残す |
| Security/Audit Event storage | PostgreSQL append-only durable record | Security-sensitive workflow と operator action は actor、target、operation、reason、request/session context、outcome を PostgreSQL の append-only record として保存する。成功した操作だけでなく、authorization failure、Web App Sudo Mode failure、CSRF failure、Operator Intent Confirmation failure も記録する。Secret、raw token、password、支払いカード情報、payload 全文は保存しない。通常 application log や metrics には委ねない |
| Security/Audit Event retention | Configurable default 1 year + pruning job | 初期 default は1年保持とし、運用設定で変更可能にする。期限切れ record は通常操作で直接物理削除せず、retention job による pruning で削除する |
| API token storage | One-time raw display + hashed durable record | API token は Public API 用 credential とし、Web App API `/api/web/*` の authentication には使わない。Raw value は発行時に一度だけ表示する。PostgreSQL には token hash、display_prefix、key_id、scope、expires_at、last_used_at、owner user/integration、status などの管理 metadata だけを保存し、raw token は保存しない。発行・削除は Web App Sudo Mode と Security/Audit Event の対象にする |
| API token issue replay | No raw secret redisplay | API token 発行 mutation が Idempotency replay されても raw token / secret は再表示しない。Replay response は token metadata と secret 再表示不可の状態を返し、caller が secret を失った場合は revoke + reissue に誘導する |
| API token lookup | `key_id` candidate lookup + hash verification | API token authentication では non-secret `key_id` で候補 token record を絞り込んだうえで token hash を検証する。`display_prefix` は短い UI 表示用 metadata とし、lookup optimization や authentication proof として扱わない |
| Raw API token format | Structured token type + `key_id` + secret | Raw API token は概念的に `<type>_<key_id>_<secret>` のような構造化文字列にする。`type` は token 種別の判別、`key_id` は候補 lookup、`secret` は hash verification の入力として扱い、raw value は保存しない |
| API token secret generation | CSPRNG 256-bit+ URL-safe random | API token secret は user 指定値にせず、server が CSPRNG で生成する 256-bit 以上の URL-safe random value にする。Secret の十分な entropy を前提に、password と同じ扱いにはしない |
| API token hash | Keyed hash / HMAC with server-side key | API token secret は高 entropy なので password hash ではなく、server-side key / pepper を使った keyed hash または HMAC を保存する。DB 単体の漏洩で token verification を完結できないようにする |
| API token hash key version | Store `hash_key_version` | API token record に HMAC key version を保存する。初期は version `1` だけでよいが、将来の key rotation 時にどの server-side key / pepper で検証するかを token record から判断できるようにする |
| API token hash key ring | Runtime secret source, not database | HMAC key 本体は DB に保存せず、AppConfig / environment variable / secret manager 由来の versioned key ring として扱う。初期は AppConfig 経由で active_key_version と versioned keys を読み、将来 secret manager へ移せる形にする |
| API token hash key rotation | Verify many, issue one | HMAC key rotation 時は新規 API token 発行だけ active key を使い、既存 token は token record の `hash_key_version` に対応する key で検証し続ける。古い key を廃止する場合は対象 version の token を期限までに rotation させる運用にする |
| API token hash key retirement | Forced rotation warning, then `token_key_retired` | 古い HMAC key を廃止する場合、対象 `hash_key_version` の token を forced rotation 対象として Web App UI と API metadata で警告する。期限後は authentication で拒否し、Public API error code は `token_key_retired` とする |
| API token failure codes | Separate validity failure from permission failure | Public API の token failure は、token 自体が使えない `invalid_token` / `expired_token` / `revoked_token` / `token_key_retired` と、valid token だが scope 不足の `insufficient_scope` を分ける。Integration が再発行・再認可・権限追加を機械判定できるようにする |
| API token validity failure status | 401 with machine-readable reason code | Public API の token validity failure は HTTP status を基本 401 に統一し、`invalid_token` / `expired_token` / `revoked_token` / `token_key_retired` などの error code で reason を分ける。Integration の機械判定を維持しつつ、token probing へ返す情報量を必要最低限にする |
| API token permission failure status | 403 with `insufficient_scope` | Public API の API token permission failure は HTTP status を 403 に統一し、error code は `insufficient_scope` にする。Token は valid だが requested operation の scope が足りない状態として、401 系の再発行・再認証判断と分ける |
| API token ownership | User or Integration owner model | API token owner は User と Integration の両方を表現できる設計にする。初期実装は User-owned token のみ有効化してよいが、データモデルと言葉は将来の Bot、外部ツール、運用連携 token を User 固定にしない |
| API token lifetime | Default 1 year; no indefinite tokens initially | API token は `expires_at` を必須にし、初期 default は1年にする。無期限 token は初期では許可せず、将来 server-to-server の強い要件が出た場合のみ Admin/Ops 承認付きの長期 token として別扱いにする |
| API token rotation | Issue new token then revoke old token | API token rotation は既存 token の raw value 再表示や in-place regeneration ではなく、新しい token record を発行して旧 token を明示 revoke する方式にする。初期は短い overlap window を設けず、必要になった場合に後続判断する |
| API token usage metadata | Throttled `last_used_at` write-back | API token の `last_used_at` は毎 request で PostgreSQL を更新しない。Valkey などで token ごとに更新を間引き、最大数分遅れてもよい利用状況 metadata として非同期反映する。Authentication / authorization の判定とは分離する |
| Integration model | First-class non-user API actor | Integration は User とは別の責任主体として扱う。初期実装では entity 作成や共同管理 UI を後回しにしてよいが、将来の Bot、外部 tool、automation の token owner、audit、rate limit、停止・移譲の単位として予約する |
| Integration status | Disabled integration invalidates owned tokens | Integration-owned API token の認証時は token status だけでなく Integration status も評価する。Integration が `disabled` の場合、その Integration に属する全 token を即時無効扱いにし、個別 revoke 漏れで止められない状態を避ける |
| Integration disable metadata | Distinguish owner-disabled and admin-disabled | Integration が `disabled` になった理由は owner disabled と admin/operator disabled を区別して記録する。`disabled_by`、`disabled_reason`、`disabled_at` に加えて disable source を持たせ、再有効化条件、audit、UI 表示を判断できるようにする |
| Integration membership | Initial levels: owner / maintainer | Integration 管理権限は `owner` と `maintainer` の2段階から始める。`owner` は削除、移譲、billing、危険操作まで可能とし、`maintainer` は token 発行・revoke・通常設定変更まで可能とする。User の Role / Privilege とは別の Integration-local authority として扱う |
| Integration sensitive operations | Sudo + audit; intent confirmation for delete / transfer | Integration の削除、移譲、membership 変更、API token 発行・revoke は Web App Sudo Mode と Security/Audit Event の対象にする。削除・移譲は高影響操作として Operator Intent Confirmation も要求する |
| API token scopes | Initial coarse scopes: read / write / admin | API surface が固まる前に endpoint-specific scope を増やしすぎない。初期は `read`、`write`、`admin` の粗い scope で始め、公開 API と運用 workflow が固まってから必要に応じて細分化する |
| API token transport | `Authorization: Bearer` only | Public API の API token は `Authorization: Bearer <token>` のみ受け付ける。Query parameter token は URL、proxy log、browser history、referer に残りやすいため拒否する |
| Public API rate limit | Composite token + owner + IP keys | Public API は API Token 単位、owner user/integration 単位、request IP 単位の複数軸で rate limit を評価する。Token rotation や NAT/VPN による単一軸の抜け・誤爆を避けるため、初期制限が粗くても複合キー前提にする |
| Public API rate limit response | 429 + `rate_limited` + `Retry-After` | Public API の rate limit failure は HTTP 429 に統一し、error code は `rate_limited` にする。Response には `Retry-After` header と `request_id` を含め、外部 integration が標準的に backoff できるようにする |
| Public API error response | Unified JSON with code + request_id | Public API の failure response は HTTP status に加えて machine-readable error code と request_id を必ず含める。Token validity failure は HTTP 401、token permission failure は HTTP 403、rate limit failure は HTTP 429 に寄せる。Human-readable message は補助情報とし、`invalid_token`、`expired_token`、`revoked_token`、`token_key_retired`、`insufficient_scope`、`rate_limited`、`idempotency_key_conflict`、`idempotency_request_in_progress` など integration が分岐できる code を contract として扱う |
| Public API idempotency | `Idempotency-Key` for high-risk mutations | Public API の state-changing request は `Idempotency-Key` を受け付ける。初期は全 write endpoint 必須ではなく、API token 発行、billing 連携、moderation mutation など二重実行が危険な mutation から必須化する |
| Public API idempotency actor boundary | After token authentication only | Idempotency Record は API token authentication に成功し、owner/token が確定した後だけ作成する。`invalid_token` など owner 未確定の authentication failure は idempotency record にせず、通常の Public API failure、rate limit、Security/Audit Event の責務として扱う |
| Public API idempotency replay | Recorded status/body/headers | 完了済みの Idempotency replay は、one-time secret 例外を除き、初回 request の HTTP status、response body、relevant response headers を再利用する。Retry により成功済み mutation の response shape や status が変わらないようにする |
| Public API idempotency replay headers | Replay contract headers only | Idempotency replay で再利用する header は `Location`、`ETag`、`Sunset`、`Deprecation` など mutation outcome の contract header に限定する。`Date`、`Server`、`Set-Cookie`、`request_id` は replay せず、新しい request context で生成する |
| Public API idempotency outcome | Record success + deterministic client failures | Idempotency Record に保存する outcome は、成功した mutation と deterministic な 4xx validation / authorization failure を対象にする。5xx や timeout は replayable failure として保存しない。ただし durable mutation が commit 済みなら、その成功 outcome を保存済みとして扱い、retry で二重実行しない |
| Public API idempotency conflict | 409 + `idempotency_key_conflict` | Public API の `Idempotency-Key` は owner/token、HTTP method、route、request fingerprint に紐づける。同じ key で異なる payload / intent が来た場合は安全な retry ではなく conflict として扱い、HTTP 409 と `idempotency_key_conflict` を返す |
| Public API idempotency in-progress | 409 + `idempotency_request_in_progress` + `Retry-After` | 同じ `Idempotency-Key` と request fingerprint の request がまだ処理中に再送された場合、server-side wait は行わず HTTP 409 と `idempotency_request_in_progress` を返す。Response には `Retry-After` header と `request_id` を含め、integration に明示的な retry を促す |
| Public API request fingerprint | Canonical non-secret digest | Public API の request fingerprint は、正規化した HTTP method、route、relevant query、body intent から hash を作る。Raw request body、API token、password、payment payload などの secret / sensitive payload は Idempotency Record に保存しない |
| Public API idempotency storage | PostgreSQL durable record in mutation boundary | Public API の Idempotency Record は Valkey-only にせず PostgreSQL に保存する。対象 mutation の transaction / Unit of Work と同じ整合性境界で key、request fingerprint、outcome を確定し、restart / failover 後も高リスク mutation の二重実行を防ぐ。Valkey は補助 cache に限定する |
| Public API idempotency retention | Configurable default 7 days + pruning | Public API Idempotency Record の初期 retention は7日とし、AppConfig などの運用設定で変更可能にする。Retention 期限後は deduplication guarantee の対象外とし、期限切れ record は pruning job で削除する |
| Web App CSRF protection | SameSite=Lax + session-bound synchronizer token | Web App Session cookie の SameSite=Lax を前提にしつつ、state-changing `/api/web/*` は Valkey の Web App Session state に紐づく synchronizer CSRF token を必須にする。SameSite や route secrecy だけを CSRF 対策の source of truth にしない |

## データベース・永続化方針

- 現行の production target は **PostgreSQL + asyncpg** とする
- DB dialect は **SQLAlchemy 2.0 async + command/query Repository + Unit of Work** でアプリケーション層から隔離する
- MySQL など別 dialect を導入する場合は spec で明示し、driver、migration、model compatibility を検証する
- データベース読み書きは **SQLAlchemy 2.0 async** 経由に統一する
- アプリケーションの永続化処理は **command/query Repository パターン** で実装する
  - mutation と consistency check は `repositories/interfaces/commands` に Protocol を定義し、`UnitOfWork` 経由で扱う
  - read-only / presentation read は `repositories/interfaces/queries` に Protocol を定義する
  - SQLAlchemy 実装は `repositories/sqlalchemy/commands`、`repositories/sqlalchemy/queries`、`repositories/sqlalchemy/models` に閉じ込める
  - test double は `repositories/memory/commands`、`repositories/memory/queries`、typed fake、または stub を使う
- `services`、`transports`、`jobs` は SQLAlchemy model、DB session、raw SQL を直接扱わない
- migration は Alembic に集約する。schema 変更を通常コードや unit test fixture に埋め込まない
- DB-backed 検証が必要な場合は、`DATABASE_URL` で明示された test DB を使う。現行既定は PostgreSQL test DB とする
- unit test のためだけに SQLite / aiosqlite などの別 DB driver を暗黙導入しない。DB が不要な範囲は typed fake / stub / in-memory 実装で検証する

## 開発方針

- **TDD (テスト駆動開発)**: Red → Green → Refactor サイクルで進める
  - テストを先に書き、失敗を確認してから実装する
  - タスク生成時は各タスクにテスト作成ステップを含める
  - in-memory 実装（StateStore, Repository）をテストで積極的に活用
  - pytest + pytest-asyncio で非同期コードもテストファースト

## 未決定 (PoC スコープ外、後続 spec で決定)

| 項目 | 候補 | 必要タイミング |
|------|------|---------------|
| HTTP クライアント | httpx | beatmap mirror / osu! API 連携時 |
| JWT | PyJWT | lazer OAuth2 対応時 |
| OAuth2 | authlib / 自前 | lazer 対応時 |
| ロギング | structlog | 本格運用前 |
| PP 計算 | rosu-pp-py | スコア送信実装時 |
| TanStack Query | TanStack Query | Next.js 内で client-side cache / mutation 管理が必要になった時点で採用判断する。TanStack Router / TanStack Start は初期 Web App 基盤にはしない |
