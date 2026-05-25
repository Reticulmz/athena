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

0. **test-type-safety** — basedpyright strict で検出されたテストコードの型エラー修正。AsyncMock → InMemory 置換、method-assign 排除、Protocol パラメータ名統一。pre-commit フック完全通過が目標

### Phase 1: クライアント基本動作

1. **channel-system** — チャットチャンネル管理（#osu 等）。Valkey でチャンネル状態・参加者リスト・メッセージ配信を管理（実装中）
2. **presence-status** — ユーザーのオンライン状態・プレイ情報（Action/BeatmapID/Mods）の管理と他ユーザーへの配信

### Phase 2: ゲームプレイ

5. **beatmap-mirror** — ビートマップ情報取得（osu! API v1/v2 or ミラー）
6. **score-submission** — スコア送信パイプライン（受付 → PP 計算 → リーダーボード更新）
7. **leaderboard** — ビートマップ別・グローバルランキング

### Phase 3: 運用・拡張

8. **email-verification** — メール認証（confirmed_at + SendGrid）
9. **admin-panel** — 管理画面フロントエンド（ユーザー管理・RBAC 管理）
10. **api-v2** — lazer 互換 REST API + OAuth2
11. **signalr** — lazer 互換 SignalR ハブ（リアルタイム通信）

## メモ

- Phase 1 の 1→2→3 を順に進めればチャットが動くようになり、サーバーの基本動作が確認できる
- Phase 2 はゲームプレイに必須だが、PP 計算（rosu-pp-py）やビートマップ取得の外部依存が増える
- Phase 3 はプロダクション運用に向けた機能

## 将来 spec メモ（channel-system grill-me で洗い出し）

- **channel-management-api** — チャンネル CRUD の REST API エンドポイント設計（WebUI / Lazer から呼び出し）
- **chat-history-api** — チャンネル/PM メッセージ履歴取得 API（Lazer / WebUI 向け）
- **irc-server** — IRC サーバー実装（RFC 1459/2812 準拠、ChannelService 呼び出し）
- **bot-api** — 外部 Bot 接続用 API（REST/WS/Webhook 方式の選定含む）
- **moderation-system** — Silence 付与/解除、Channel Ban、通報、モデレーションログ
- **web-ui** — 別リポジトリ（osu-web + Admin 一体型）、チャンネル管理・チャットログ閲覧・ユーザー管理
- **beatmap-rank-request** — !request コマンドによるビートマップランクリクエスト（リクエストキュー、承認フロー、BanchoBot 通知）。依存: channel-system, beatmap-mirror
