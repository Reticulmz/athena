# Requirements Document

## Introduction
athena はグリーンフィールドの osu! bancho 互換プライベートサーバー。現状 devenv.nix と pyproject.toml のみ存在し、src/ ディレクトリすらない。後続機能（bancho プロトコル、ログイン、チャット等）を実装するための基盤として、プロジェクト骨格・設定管理・依存性注入・インフラ接続・ステートストア抽象・コード品質ツールを整備する。

## Boundary Context
- **In scope**: プロジェクト構造、アプリケーション起動、設定管理、DI コンテナ、DB 接続基盤、Redis 接続基盤、ステートストア抽象（Protocol + 実装）、レイヤー依存制約、コード品質ツール設定、依存パッケージ管理
- **Out of scope**: bancho バイナリプロトコル定義（bancho-protocol spec）、認証フロー（bancho-login spec）、EventBus / JobQueue 実装（後続 spec）、個別ドメインのビジネスロジック
- **Adjacent expectations**: devenv 環境で PostgreSQL と Redis が起動済みであること。後続 spec はここで定義された DI コンテナ・ステートストア抽象・DB 基盤の上に構築される

## Requirements

### Requirement 1: アプリケーション起動
**Objective:** As a 開発者, I want サーバーアプリケーションを単一コマンドで起動できる, so that 開発サイクルを素早く回せる

#### Acceptance Criteria
1. When 開発者がアプリケーション起動コマンドを実行した場合, the サーバー shall 指定ポートで HTTP リクエストを受け付ける状態になる
2. When サーバーが起動完了した場合, the サーバー shall ルートパス (`/`) への HTTP リクエストに対してレスポンスを返す（bancho エンドポイントの受け口として機能する）
3. When サーバーが起動完了した場合, the サーバー shall ホスト名ベースのルーティングにより複数のサブアプリケーション（bancho / web_legacy / api）を振り分ける準備が整っている

### Requirement 2: 設定管理
**Objective:** As a 運用者, I want 環境変数でサーバーの設定を変更できる, so that 環境ごとに設定を外部化できる

#### Acceptance Criteria
1. The サーバー shall 環境変数からデータベース接続先 (`DATABASE_URL`) と Redis 接続先 (`REDIS_URL`) を読み取る
2. If 必須の環境変数が未設定または不正な場合, the サーバー shall 起動時にバリデーションエラーを報告し、起動を中断する
3. The サーバー shall 設定値を型安全なオブジェクトとして提供し、文字列のまま扱わない

### Requirement 3: データベース接続基盤
**Objective:** As a 開発者, I want データベースへの非同期接続が確立される, so that 後続機能でユーザー・スコア等のデータを永続化できる

#### Acceptance Criteria
1. When アプリケーションが起動した場合, the サーバー shall データベースへの接続プールを確立する
2. When アプリケーションが終了した場合, the サーバー shall データベース接続を適切にクローズする
3. The サーバー shall データベーススキーマのバージョン管理とマイグレーション実行の仕組みを提供する
4. The サーバー shall 非同期でのデータベースクエリ実行をサポートする

### Requirement 4: Redis 接続基盤
**Objective:** As a 開発者, I want Redis への非同期接続が確立される, so that セッション・プレゼンス等の揮発的ステートを管理できる

#### Acceptance Criteria
1. When アプリケーションが起動した場合, the サーバー shall Redis への接続を確立する
2. When アプリケーションが終了した場合, the サーバー shall Redis 接続を適切にクローズする
3. The サーバー shall 非同期での Redis 操作をサポートする

### Requirement 5: 依存性注入
**Objective:** As a 開発者, I want サービス・リポジトリ・インフラコンポーネントを注入可能にする, so that コンポーネント間の結合度を低く保ち、テスト時に実装を差し替えられる

#### Acceptance Criteria
1. The サーバー shall コンポーネント間の依存関係を外部から注入する仕組みを提供する
2. When テスト実行時に, the DI の仕組み shall 本番実装をモック・スタブ実装に差し替え可能にする
3. When アプリケーションが起動した場合, the DI の仕組み shall 全ての必要なコンポーネントを解決し、不足があればエラーを報告する

### Requirement 6: ステートストア抽象
**Objective:** As a 開発者, I want 揮発的ステート（セッション、プレゼンス等）の読み書きを抽象化されたインターフェースで行いたい, so that 実装を差し替え可能にし、テスト時にインメモリ実装を使える

#### Acceptance Criteria
1. The サーバー shall ステートストアの操作を抽象インターフェースとして定義する
2. The サーバー shall ステートストアの本番実装（Redis ベース）を提供する
3. The サーバー shall ステートストアのインメモリ実装をテスト用に提供する
4. When ステートストアの実装を差し替えた場合, the サーバー shall 呼び出し元のコードを変更せずに動作する

### Requirement 7: レイヤー依存制約
**Objective:** As a 開発者, I want レイヤー間の依存方向違反を自動検出したい, so that アーキテクチャの劣化を防げる

#### Acceptance Criteria
1. The プロジェクト shall レイヤー依存ルール（Transports → Services → Domain → Repositories → Infrastructure → Shared、上位→下位のみ許可）を定義する
2. When 依存方向に違反する import が存在する場合, the 検証ツール shall エラーを報告する
3. When 全ての import がルールに準拠している場合, the 検証ツール shall 成功を報告する

### Requirement 8: コード品質ツール設定
**Objective:** As a 開発者, I want リンター・フォーマッター・型チェッカーが設定済みであること, so that チーム全体で一貫したコード品質を維持できる

#### Acceptance Criteria
1. The プロジェクト shall リントルールが設定され、コマンド一つで全ソースコードを検査できる
2. The プロジェクト shall フォーマットルールが設定され、コマンド一つで全ソースコードを整形できる
3. The プロジェクト shall 型チェックが厳格モードで設定され、コマンド一つで型エラーを検出できる

### Requirement 9: プロジェクト構造
**Objective:** As a 開発者, I want 設計書に従ったモジュール構造が存在する, so that 後続機能を適切な場所に配置でき、レイヤー境界が明確になる

#### Acceptance Criteria
1. The プロジェクト shall 設計書で定義されたレイヤー別ディレクトリ構造（transports, services, domain, repositories, infrastructure, shared）を持つ
2. The プロジェクト shall 各ディレクトリに `__init__.py` を配置し、Python パッケージとして認識可能にする
3. The プロジェクト shall 必要な依存パッケージがパッケージ定義ファイルに宣言されている
