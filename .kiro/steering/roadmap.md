# Roadmap

## 完了済み

- **bancho-protocol** — パケット解析（read_packets）、ディスパッチャー、S2C パケット定義・ビルダー
- **bancho-login** — ログイン・登録・セッション管理・RBAC・Host ベースルーティング
- **dev-proxy** — nginx リバースプロキシ（HTTP/HTTPS）・mkcert・Nix flake 統合・ヘルスチェック
- **valkey-migration** — Redis → Valkey 移行（redis-py → valkey-glide、ARQ → taskiq + taskiq-redis）
- **packet-polling** — ログイン後の POST `/`（osu-token あり）でキューに溜まった S2C パケットを返す
- **c2s-handlers** — C2S パケットハンドラ群（PONG、EXIT、USER_QUIT ブロードキャスト）

## 次のステップ（優先度順）

### 最優先: 型安全基盤

0. **/.** — basedpyright strict で検出されたテストコードの型エラー修正。AsyncMock → InMemory 置換、method-assign 排除、Protocol パラメータ名統一。pre-commit フック完全通過が目標

### Phase 1: クライアント基本動作

1. **channel-system** — チャットチャンネル管理（#osu 等）。Valkey でチャンネル状態・参加者リスト・メッセージ配信を管理（実装中）
2. **event-boundary-refactor** — 水平スケーリング前提で Local Event / Distributed Event / Durable Work を分離する。既存 EventBus を production-critical workflow の source of truth にしない
3. **presence-status** — ユーザーのオンライン状態・プレイ情報（Action/BeatmapID/Mods）の管理と他ユーザーへの配信。Disconnect Notification は一時的通知とし、TTL / heartbeat で stale state から回復する
4. **chat-persistence-durability** — Chat Persistence Work を Durable Work として扱い、queue signal だけに依存しない未処理 work の source of truth と retry / 重複収束を設計する

### Phase 2: ゲームプレイ

5. **blob-storage** — `.osu` ファイル、将来のリプレイファイル、画像アップロードを保存する汎用 blob storage。`blob_sha256` を軸に Local backend を先行実装し、S3 backend へ拡張できる interface / config を用意する。共通責務は `blobs` テーブルと storage service までとし、polymorphic attachment は採用しない。用途別 attachment table（例: beatmap file、score replay、screenshot）は各 domain spec が所有し、外部キーと domain 固有制約を明示する
6. **beatmap-mirror** — ビートマップ情報取得（osu! API v1/v2 を正、ミラーは障害時フォールバック）。`.osu` ファイル保存は blob-storage に委譲する。依存: blob-storage
7. **score-ingestion** (Wave 1) — Stable client からの score 受付、validation、保存、replay 保存。PP なし、completed response 返却。依存: beatmap-mirror, blob-storage
8. **score-pp-calculation** (Wave 2) — rosu-pp-py による PP/stars 計算、provenance tracking。依存: score-ingestion
9. **friend-relationships** — Stable friends list と Friends leaderboard の source of truth になる friend relationship。関係の向き、friends list packet、将来の friend 管理 API との境界を定義する。依存: bancho-login
10. **beatmap-leaderboards** (Wave 3) — Beatmap leaderboard projection、personal best tracking、Global / Country / Selected Mods / Friends category の getscores rows。依存: score-ingestion, score-pp-calculation, friend-relationships
11. **user-stats** (Wave 3) — User stats 集計 (play count, ranked score, weighted PP, accuracy) と PP 優先の `beatmap_performance_bests` projection。依存: score-ingestion, score-pp-calculation
12. **user-ranking** (Wave 4) — Global/country rank 時系列履歴、rank snapshot rebuild、ranking graph API。依存: user-stats

### Phase 3: 運用・拡張

13. **email-verification** — メール認証。PostgreSQL の durable account state と Valkey の TTL付き challenge state を分離する。`Privileges.VERIFIED` は Role からではなく email verification state から派生させ、Default role からは外す。メール送信は provider interface 化し、SendGrid などは adapter として扱う。登録時に verification code と WebUI verification link を送信し、未認証ユーザーには Limited Bancho Session を与える。メール送信失敗時も user 作成は成功させ、resend 導線で回復する。BanchoBot の `!verify` / resend 導線、notification packet による案内、Limited Session Packet Gate、Verified Play Access 付与、active session authorization refresh を扱う
14. **athena-web-app** — monorepo 内の統合 Web App。Next.js App Router + HeroUI を採用し、Next.js の best practices に従って Public / User / Admin / Ops workflows を扱う。Athena backend の source of truth は Python の Starlette + FastAPI に置き、Web App は OpenAPI generated client / WebUI 専用 API contract 経由で接続する。Web App API は same-origin の `/api/web/*` として公開する first-party 専用だが露出前提の surface とし、隠されていることを security boundary にしない。Public API は `/api/public/v1/*` のような URL path versioning を使い、同一 version 内では additive change を基本にする。Deprecated Public API version / endpoint は最低6か月維持し、response header と公開 docs で deprecation status、sunset date、移行先を告知する。Web App 認証は FastAPI-issued server-side session cookie を基本とし、HttpOnly / Secure / SameSite=Lax cookie を使う。Active session は Valkey TTL state、durable user state と audit / security event は PostgreSQL を source of truth にする。Web App Session は idle timeout、absolute lifetime、session rotation を持ち、初期 default は idle 12時間、absolute 30日、Web App Sudo Mode window 15分とする。Password/email 変更、2FA 設定、moderation mutation、Admin/Ops mutation、Billing 操作、API token 発行・削除には Web App Sudo Mode を要求する。API token は Public API 用 credential とし、Web App API `/api/web/*` の authentication には使わない。Public API では `Authorization: Bearer` のみ受け付け、query parameter token は拒否する。API token の raw value は発行時に一度だけ表示し、DB には keyed token hash / HMAC value、hash_key_version、display_prefix、key_id、scope、expires_at、last_used_at、owner user/integration、status metadata だけを保存する。HMAC key ring は DB に保存せず、AppConfig / environment variable / secret manager 由来の runtime secret として扱う。HMAC key rotation は verify-many / issue-one とし、新規 token は active key で発行し、既存 token は自身の hash_key_version に対応する key で検証し続ける。古い HMAC key を廃止する場合、対象 hash_key_version の token は forced rotation 対象として Web App UI と API metadata で警告し、期限後は `token_key_retired` で authentication を拒否する。API token authentication では non-secret key_id で候補を絞ったうえで hash_key_version に対応する runtime key を使った keyed hash / HMAC を検証し、display_prefix と key_id は単独では authentication proof として扱わない。API token validity failure（`invalid_token` / `expired_token` / `revoked_token` / `token_key_retired`）は HTTP 401 を基本にし、reason は machine-readable error code で区別する。Permission failure は valid token の scope 不足（`insufficient_scope`）として token validity failure と分け、HTTP 403 を基本にする。Raw API token は token type、key_id、CSPRNG 生成の 256-bit 以上 URL-safe secret を含む構造化文字列にする。API token の `last_used_at` は毎 request で PostgreSQL 更新せず、間引きして非同期反映する利用状況 metadata として扱う。API token は `expires_at` 必須、初期 default 1年とし、無期限 token は初期では許可しない。API token rotation は新 token を発行して旧 token を明示 revoke する方式にし、raw token の再表示や既存 token の in-place regeneration は行わない。API token owner は User と Integration の両方を表現できる設計にし、初期実装は User-owned token のみ有効化してよい。Integration は User とは別の first-class actor とし、将来の Bot、外部 tool、automation の token owner、audit、rate limit、停止・移譲の単位にする。Integration-owned API token の認証時は Integration status も評価し、Integration が disabled の場合は全 token を即時無効扱いにする。Integration disabled は owner disabled と admin/operator disabled を区別し、再有効化条件、audit、UI 表示に使う。Integration 管理権限は `owner` / `maintainer` の2段階から始め、User の Role / Privilege とは別に扱う。Integration の削除・移譲・membership 変更・API token 発行/revoke は Web App Sudo Mode と Security/Audit Event の対象にし、削除・移譲には Operator Intent Confirmation も要求する。API token scope は初期 `read` / `write` / `admin` から始め、API surface が固まってから細分化する。Public API rate limit は API Token 単位、owner user/integration 単位、request IP 単位の複合キーで評価する。Public API rate limit failure は HTTP 429 と `rate_limited` code に統一し、`Retry-After` header と `request_id` を返す。Public API failure response は HTTP status に加えて machine-readable error code と request_id を含む統一 JSON 形式にする。Public API の state-changing request は `Idempotency-Key` を受け付け、二重実行が危険な mutation から必須化する。破壊的または高影響な moderation / Admin / Ops operation には Operator Intent Confirmation も要求する。Security-sensitive workflow と operator action は actor、target、operation、reason、request/session context、outcome を PostgreSQL の append-only Security/Audit Event として保存し、成功した操作だけでなく authorization failure、Sudo Mode failure、CSRF failure、Operator Intent Confirmation failure も記録する。Secret、raw token、password、支払いカード情報、payload 全文は保存しない。Security/Audit Event の初期 retention は1年で、期限切れ record は retention job により pruning する。State-changing `/api/web/*` には Web App Session に紐づく synchronizer CSRF token gate を置く。Next.js の Route Handler / Server Actions は thin frontend / BFF 補助層に限定し、domain mutation の正規経路にはしない。初期 scope はユーザー管理・RBAC 管理・運用導線
   - Public API の `Idempotency-Key` は owner/token、method、route、request fingerprint に紐づけ、同じ key で異なる payload / intent が来た場合は HTTP 409 と `idempotency_key_conflict` を返す
   - Public API の Idempotency Record は API token authentication 成功後に owner/token が確定してから作成し、owner 未確定の authentication failure は idempotency の対象にしない
   - 完了済みの Idempotency replay は one-time secret 例外を除き、初回 request の HTTP status、response body、relevant response headers を再利用する
   - Idempotency replay の header 再利用は `Location`、`ETag`、`Sunset`、`Deprecation` などの contract header に限定し、`Date`、`Server`、`Set-Cookie`、`request_id` は新しい request context で生成する
   - Public API の Idempotency outcome は成功した mutation と deterministic な 4xx validation / authorization failure を保存対象にし、5xx や timeout は replayable failure として保存しない。ただし mutation が commit 済みなら成功 outcome を保存済みとして扱う
   - 同じ `Idempotency-Key` / fingerprint の request が処理中に再送された場合は待機させず、HTTP 409 と `idempotency_request_in_progress`、`Retry-After` を返す
   - API token 発行の Idempotency replay では raw token / secret を再表示せず、token metadata と secret 再表示不可の状態を返し、必要なら revoke + reissue に誘導する
   - Public API request fingerprint は正規化した method、route、relevant query、body intent の hash とし、raw request body や secret / payment payload は保存しない
   - Public API の Idempotency Record は PostgreSQL に durable record として保存し、対象 mutation の transaction と同じ整合性境界で key、fingerprint、outcome を確定する。Valkey-only にはしない
   - Public API Idempotency Record の retention は初期 default 7日、設定で変更可能とし、期限切れ後は deduplication guarantee 対象外として pruning する
15. **api-v2** — lazer 互換 REST API + OAuth2
16. **signalr** — lazer 互換 SignalR ハブ（リアルタイム通信）
17. **log-writer-pipeline** — 専用ログ writer による統合ログ出力。起動直後は各プロセスがローカル `latest.jsonl` に直接書き込み、Valkey 接続確立後に writer 経由へ昇格する案を検証する。Valkey 未起動・writer 障害時はローカル直接書き込みへフォールバックする前提で設計する

## メモ

- Phase 1 の 1→2→3→4 を順に進めればチャットと presence の基本動作を水平スケーリング前提へ寄せられる
- Phase 2 はゲームプレイに必須だが、PP 計算（rosu-pp-py）やビートマップ取得の外部依存が増える
- Phase 3 はプロダクション運用に向けた機能
- email-verification / athena-web-app / supporter-entitlements は方針を先に固めるが、正式 spec は stable bancho の基本機能（chat、presence、score、leaderboard、stats）の実用体験が固まってから生成する
- ログ writer パイプラインは現行のファイルロック方式を置き換える可能性があるが、Valkey / writer の起動順・障害時にもログを失わないことを最優先の設計条件にする

## 将来 spec メモ（channel-system grill-me で洗い出し）

- **channel-management-api** — チャンネル CRUD の REST API エンドポイント設計（WebUI / Lazer から呼び出し）
- **chat-history-api** — チャンネル/PM メッセージ履歴取得 API（Lazer / WebUI 向け）
- **irc-server** — IRC サーバー実装（RFC 1459/2812 準拠、ChannelService 呼び出し）
- **bot-api** — 外部 Bot 接続用 API（REST/WS/Webhook 方式の選定含む）
- **moderation-system** — Silence 付与/解除、Channel Ban、通報、モデレーションログ
- **athena-web-app** — monorepo 内のオープンソース統合 Web App。`apps/web` を想定し、Next.js App Router + HeroUI を初期基盤とする。TanStack Query は必要に応じて Next.js 内の補助ライブラリとして採用し、TanStack Router / TanStack Start は初期基盤にはしない。チャンネル管理・チャットログ閲覧・ユーザー管理、beatmap request / rank 状態変更などを扱う。rank 変更ルール自体は beatmap-rank-management に委譲する
- **supporter-entitlements** — Stripe などの billing provider や operator grant から Supporter Entitlement を付与・失効する。Supporter Entitlement は osu!direct Access の条件ではなく、community perks / Web display perks の入力として扱う
- **osu-direct-access-policy** — osu!direct Access を通常ユーザーへ開放するかを Server Policy として設定する。初期案は AppConfig の default setting とし、DB-backed server settings は後続 scope とする
- **stable-presence-filter-semantics** — `RECEIVE_UPDATES`、`PRESENCE_REQUEST`、`PRESENCE_REQUEST_ALL`、friends-only visibility / roster filter の Stable client 挙動を Lekuruu / Akatsuki / 実クライアントで確認して実装する。初期 Stable Presence Roster は all active online users + explicit system presence を送る方針とし、この filter semantics は今回 scope 外にする
- **beatmap-rank-request** — !request コマンドや WebUI からのビートマップランクリクエスト（リクエストキュー、承認フロー、BanchoBot 通知）。依存: channel-system, beatmap-mirror
- **beatmap-rank-management** — BanchoBot / 管理コマンド / WebUI から beatmap の rank 状態を確認・変更する運用機能。外部由来の ranked status とローカル override の優先順位、変更権限、監査ログ、request 承認時の status 更新を扱う。Bot と Athena Web App は直接 DB を更新せず、この機能の共通サービス/APIを正規経路として利用する。依存: channel-system, beatmap-mirror, beatmap-rank-request, athena-web-app
- **operator-leaderboard-inspection** — Admin / moderator などの operator が restricted user や public leaderboard から非表示になった Score / Personal Best 候補を調査できる内部表示。public stable/Web Beatmap Leaderboard とは別 surface とし、score owner visibility を無視した閲覧には明示的な権限、監査ログ、reason を要求する。依存: beatmap-leaderboards, athena-web-app, moderation-system
