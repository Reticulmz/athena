# Roadmap

## 完了済み

- **bancho-protocol** — パケット解析（read_packets）、ディスパッチャー、S2C パケット定義・ビルダー
- **bancho-login** — ログイン・登録・セッション管理・RBAC・Host ベースルーティング
- **dev-proxy** — nginx リバースプロキシ（HTTP/HTTPS）・mkcert・devenv 統合・ヘルスチェック
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
11. **user-stats** (Wave 3) — User stats 集計 (play count, ranked score, weighted PP, accuracy)。依存: score-ingestion, score-pp-calculation
12. **user-ranking** (Wave 4) — Global/country rank 時系列履歴、rank snapshot rebuild、ranking graph API。依存: user-stats

### Phase 3: 運用・拡張

13. **email-verification** — メール認証（confirmed_at + SendGrid）
14. **athena-web-app** — monorepo 内の統合 Web App。Public / User / Admin / Ops workflows を扱い、WebUI 専用 API contract 経由で Athena backend に接続する。初期 scope はユーザー管理・RBAC 管理・運用導線
15. **api-v2** — lazer 互換 REST API + OAuth2
16. **signalr** — lazer 互換 SignalR ハブ（リアルタイム通信）
17. **log-writer-pipeline** — 専用ログ writer による統合ログ出力。起動直後は各プロセスがローカル `latest.jsonl` に直接書き込み、Valkey 接続確立後に writer 経由へ昇格する案を検証する。Valkey 未起動・writer 障害時はローカル直接書き込みへフォールバックする前提で設計する

## メモ

- Phase 1 の 1→2→3→4 を順に進めればチャットと presence の基本動作を水平スケーリング前提へ寄せられる
- Phase 2 はゲームプレイに必須だが、PP 計算（rosu-pp-py）やビートマップ取得の外部依存が増える
- Phase 3 はプロダクション運用に向けた機能
- ログ writer パイプラインは現行のファイルロック方式を置き換える可能性があるが、Valkey / writer の起動順・障害時にもログを失わないことを最優先の設計条件にする

## 将来 spec メモ（channel-system grill-me で洗い出し）

- **channel-management-api** — チャンネル CRUD の REST API エンドポイント設計（WebUI / Lazer から呼び出し）
- **chat-history-api** — チャンネル/PM メッセージ履歴取得 API（Lazer / WebUI 向け）
- **irc-server** — IRC サーバー実装（RFC 1459/2812 準拠、ChannelService 呼び出し）
- **bot-api** — 外部 Bot 接続用 API（REST/WS/Webhook 方式の選定含む）
- **moderation-system** — Silence 付与/解除、Channel Ban、通報、モデレーションログ
- **athena-web-app** — monorepo 内のオープンソース統合 Web App。チャンネル管理・チャットログ閲覧・ユーザー管理、beatmap request / rank 状態変更などを扱う。rank 変更ルール自体は beatmap-rank-management に委譲する
- **beatmap-rank-request** — !request コマンドや WebUI からのビートマップランクリクエスト（リクエストキュー、承認フロー、BanchoBot 通知）。依存: channel-system, beatmap-mirror
- **beatmap-rank-management** — BanchoBot / 管理コマンド / WebUI から beatmap の rank 状態を確認・変更する運用機能。外部由来の ranked status とローカル override の優先順位、変更権限、監査ログ、request 承認時の status 更新を扱う。Bot と WebUI は直接 DB を更新せず、この機能の共通サービス/APIを正規経路として利用する。依存: channel-system, beatmap-mirror, beatmap-rank-request, web-ui
