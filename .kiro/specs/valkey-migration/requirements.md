# Requirements Document

## Introduction

athena が使用する Redis クライアント (redis-py) およびジョブキュー (ARQ) を、型安全性に優れた Valkey エコシステム (valkey-glide, taskiq) に移行する。サーバー側も Redis から Valkey に切り替え、redis-py への自前コードからの直接依存をゼロにする。

## Boundary Context

- **In scope**: Redis クライアント実装の valkey-glide 置換、ARQ スケルトンの taskiq 置換、開発環境のサーバー切り替え、設定・環境変数リネーム、ドキュメント更新、型安全の達成
- **Out of scope**: 本番環境のデータ移行手順、InMemory 実装の変更、Protocol インターフェースの変更、Services / Transports 層の変更
- **Adjacent expectations**: Protocol 抽象化 (SessionStore, PacketQueue, ChannelStateStore, RateLimiter) が上位層を変更から隔離すること。taskiq-redis が Valkey サーバーにプロトコル互換で接続可能であること。

## Requirements

### Requirement 1: Valkey クライアント移行

**Objective:** As a 開発者, I want redis-py の代わりに valkey-glide を使用したい, so that 型安全なコードを書ける。

#### Acceptance Criteria

1. When アプリケーションが起動した場合, the クライアントファクトリ shall valkey-glide ベースのクライアントを生成し、Valkey サーバーへの接続を確立する。
2. When アプリケーションが終了した場合, the DI コンテナ shall クライアントの終了処理を実行し、コネクションを解放する。
3. The SessionStore 実装 shall Lua スクリプトを Script オブジェクト経由 (SCRIPT LOAD + EVALSHA パターン) で実行する。
4. The PacketQueue 実装 shall Lua スクリプトを Script オブジェクト経由で実行する。
5. The ChannelStateStore 実装 shall アトミック Batch (トランザクション) で複数キー操作を実行する。
6. The RateLimiter 実装 shall カウンター操作をサーバーに対して実行し、レート判定結果を返す。
7. The ソースコード shall `redis-py` を直接 import しない。

### Requirement 2: ジョブキュー移行

**Objective:** As a 開発者, I want ARQ の代わりに taskiq を使用したい, so that アクティブにメンテナンスされたジョブキュー基盤を利用できる。

#### Acceptance Criteria

1. When ワーカープロセスが起動した場合, the ワーカー shall taskiq ブローカー経由で Valkey サーバーに接続する。
2. The ワーカー設定 shall taskiq のエントリポイントとして構成される。
3. The 依存定義 shall ARQ への依存を含まない。

### Requirement 3: 開発環境のサーバー切り替え

**Objective:** As a 開発者, I want 開発環境で Valkey サーバーを使用したい, so that 本番同等の環境で開発できる。

#### Acceptance Criteria

1. When `devenv up` を実行した場合, the 開発環境 shall Valkey サーバーを起動する。
2. When アプリケーションが Valkey サーバーに接続した場合, the ヘルスチェックエンドポイント shall Valkey の接続状態を "ok" と報告する。
3. The 開発環境 shall `VALKEY_URL` 環境変数を設定する。

### Requirement 4: 設定と環境変数

**Objective:** As a 開発者, I want 環境変数と設定名が Valkey を反映していてほしい, so that 設定の意図が明確になる。

#### Acceptance Criteria

1. The アプリケーション設定 shall `VALKEY_URL` 環境変数からサーバー接続先を読み取る。
2. The 設定モデル shall `redis://` スキーマの DSN バリデーションを型エイリアス経由で維持する。
3. The ソースコード shall 環境変数名 `REDIS_URL` を参照しない。

### Requirement 5: ディレクトリとクラスのリネーム

**Objective:** As a 開発者, I want ファイルパスとクラス名が Valkey を反映していてほしい, so that コードの意図が明確になる。

#### Acceptance Criteria

1. The Valkey 実装ファイル shall `valkey/` ディレクトリに配置される。
2. The Valkey 実装クラス shall クラス名に "Valkey" プレフィクスを使用する。
3. The ソースコード shall `redis/` ディレクトリ内の実装ファイルを含まない。

### Requirement 6: 型安全

**Objective:** As a 開発者, I want Valkey 実装コードが basedpyright strict モードでエラーゼロであってほしい, so that ファイルレベルの pyright 抑制やインライン抑制が不要になる。

#### Acceptance Criteria

1. The Valkey 実装ファイル shall ファイルレベルの `# pyright:` 抑制コメントを含まない。
2. The Valkey 実装ファイル shall basedpyright strict モードでエラーゼロとなる。
3. The Valkey 実装ファイル shall `# type: ignore` コメントを含まない。

### Requirement 7: テスト維持

**Objective:** As a 開発者, I want 既存テストが Valkey 移行後も全て通ってほしい, so that 機能的な退行がないことを保証できる。

#### Acceptance Criteria

1. When 全テストスイートを実行した場合, the テスト shall 全てパスする。
2. The Integration テスト shall valkey-glide ベースのクライアントを使用して Valkey サーバーに接続する。
3. The Integration テストファイル shall `test_valkey_` プレフィクスで命名される。
4. The InMemory テスト shall 変更されない。

### Requirement 8: ドキュメント更新

**Objective:** As a 開発者, I want ドキュメントが現在の技術スタックを正確に反映していてほしい, so that オンボーディングや設計判断に支障がない。

#### Acceptance Criteria

1. The `CLAUDE.md` shall 技術スタック説明に valkey-glide と taskiq を記載する。
2. The `.kiro/steering/tech.md` shall 技術選定表を Valkey / taskiq に更新する。
3. The `.kiro/steering/roadmap.md` shall Valkey 移行の完了を反映する。
4. The `bancho_server_design.md` shall ステート設計の記述を Valkey に更新する。
5. The `.kiro/specs/channel-system/` shall Redis 参照箇所を Valkey に更新する。
6. The `.claude/rules/type-safety-policy.md` shall 外部ライブラリスタブ対応手順を更新する。

### Requirement 9: 依存定義

**Objective:** As a 開発者, I want pyproject.toml が Valkey エコシステムの依存を正確に宣言していてほしい, so that 不要な依存が残らない。

#### Acceptance Criteria

1. The 依存定義 shall `valkey-glide` を含む。
2. The 依存定義 shall `taskiq` および `taskiq-redis` を含む。
3. The 依存定義 shall `redis[hiredis]` を直接依存として含まない。
4. The 依存定義 shall `arq` を直接依存として含まない。
