# Requirements Document

## Introduction

osu! stable クライアントが `-devserver athena.local` でローカル開発サーバーに接続できるようにするための、nginx リバースプロキシ環境と devenv 統合を構築する。stable クライアントはポート 80/443 に固定接続するため、nginx で athena（uvicorn :8000）に転送する。全サブドメイン（bancho 系・web_legacy・アバター・バナー・API）を1つの server ブロックで受け、WebSocket 対応ヘッダを含める。

## Boundary Context
- **In scope**: nginx.dev.conf 作成、devenv.nix への nginx プロセス統合、CAP_NET_BIND_SERVICE によるポート 80 非 root 起動、全サブドメインルーティング（c/c1/ce/c4-c6, osu, a, b, api）、ヘルスチェックエンドポイント（GET / on c.* と osu.*）、hosts.example ファイル、HTTPS コメントアウト設定 + mkcert パッケージ、config.py の domain デフォルト変更
- **Out of scope**: mitmproxy 統合、本番環境のデプロイ設定、TLS 証明書の自動取得（Let's Encrypt 等）、WSL2 以外のプラットフォーム固有設定、アバター/バナーサーバーの実装
- **Adjacent expectations**: athena（uvicorn）が :8000 で起動していること、bancho-login spec の Host ベースルーティングが動作していること

## Requirements

### Requirement 1: nginx リバースプロキシ設定

**Objective:** As a 開発者, I want stable クライアントからのリクエストを athena に転送するリバースプロキシが欲しい, so that ポート 80 固定の stable クライアントが開発サーバーに接続できる

#### Acceptance Criteria

1. athena shall リポジトリに `nginx.dev.conf` を配置し、全 osu! サブドメインのリクエストをポート 8000 に転送する設定を含む
2. When リクエストが bancho サブドメイン（c, c1, ce, c4, c5, c6）に到着した場合, nginx shall リクエストを athena のポート 8000 に転送し、Host ヘッダを保持する
3. When リクエストが web_legacy サブドメイン（osu）に到着した場合, nginx shall リクエストを athena のポート 8000 に転送し、Host ヘッダを保持する
4. When リクエストがアバター（a）、バナー（b）、API（api）サブドメインに到着した場合, nginx shall リクエストを athena のポート 8000 に転送する
5. athena shall nginx 設定に WebSocket 対応ヘッダ（`Upgrade`, `Connection`, `proxy_http_version 1.1`）を含め、将来の SignalR 接続に対応する
6. athena shall 全サブドメインを単一の server ブロックで受け付ける

### Requirement 2: devenv 統合

**Objective:** As a 開発者, I want `devenv up` だけで nginx を含む開発環境全体が起動して欲しい, so that 手動設定なしで stable クライアント接続テストができる

#### Acceptance Criteria

1. athena shall devenv.nix に nginx プロセスを `processes.nginx` として定義し、`devenv up` で自動起動する
2. athena shall nginx プロセスに `CAP_NET_BIND_SERVICE` を付与し、非 root ユーザーでポート 80 をバインド可能にする
3. athena shall nginx プロセスを athena アプリプロセスの起動後に開始する（依存順序）
4. When `devenv up` を実行した場合, athena shall nginx がポート 80 でリッスンし、athena が :8000 でリッスンしている状態を確立する

### Requirement 3: ドメイン設定

**Objective:** As a 開発者, I want ドメイン名を設定で管理したい, so that 環境に応じてドメインを切り替えられる

#### Acceptance Criteria

1. athena shall AppConfig の `domain` フィールドのデフォルト値を `athena.local` とする
2. athena shall リポジトリに `hosts.example` ファイルを配置し、全サブドメインの hosts エントリ例を含む
3. athena shall `hosts.example` に HTTPS 有効化手順をコメントで記載する

### Requirement 4: ヘルスチェックエンドポイント

**Objective:** As a 開発者, I want ブラウザでサブドメインにアクセスしたときに動作確認したい, so that nginx の設定ミスやサーバー停止をすぐに検出できる

#### Acceptance Criteria

1. When ブラウザが `c.athena.local` に GET `/` でアクセスした場合, athena shall ステータス 200 のプレーンテキストレスポンスでサーバー名とバージョン情報を返却する
2. When ブラウザが `osu.athena.local` に GET `/` でアクセスした場合, athena shall ステータス 200 のプレーンテキストレスポンスでサーバー名とバージョン情報を返却する
3. athena shall ヘルスチェックレスポンスに pyproject.toml のバージョン番号を含める

### Requirement 5: HTTPS オプション対応

**Objective:** As a 開発者, I want 必要に応じて HTTPS を有効化できるようにしておきたい, so that HTTPS が必要な機能のテスト時にすぐ切り替えられる

#### Acceptance Criteria

1. athena shall `nginx.dev.conf` に HTTPS 対応の server ブロックをコメントアウト状態で含める
2. athena shall devenv.nix に mkcert パッケージを含め、ローカル証明書生成を可能にする
3. athena shall `hosts.example` に mkcert による証明書生成コマンド例をコメントで記載する
