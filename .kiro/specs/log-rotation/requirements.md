# Requirements Document

## Introduction
athena サーバーのログファイルシステムを改善する。現在は単一ファイルへの無制限追記で肥大化が進んでいるため、Minecraft 方式の起動時ローテーション (latest.jsonl + 過去ログアーカイブ) を導入し、ログの可読性・管理性・ストレージ効率を向上させる。

## Boundary Context
- **In scope**: JSONL ファイルログの起動時ローテーション、gzip 圧縮アーカイブ、保持件数制御、設定フィールドの再設計
- **Out of scope**: コンソール (stderr) 出力のローテーション、ログの集約・転送 (外部サービス連携)、ログの検索・クエリ機能、稼働中 (サイズ/時間ベース) のローテーション
- **Adjacent expectations**: structlog の ProcessorFormatter / JSONRenderer はそのまま利用する。設定フィールドの変更は既存の環境変数・設定ファイルの互換性に影響する。

## Requirements

### Requirement 1: 起動時ログローテーション
**Objective:** As a サーバー運用者, I want サーバー起動時に前回のログが自動的にアーカイブされる, so that latest.jsonl が常に現在のセッションのログのみを含み、前回分を容易に参照できる

#### Acceptance Criteria
1. When athena サーバーが起動する, the logging system shall 既存の `latest.jsonl` を日付ベースのアーカイブファイルにリネームし、gzip 圧縮する
2. When ローテーション完了後, the logging system shall 新しい空の `latest.jsonl` を作成してログ書き込みを開始する
3. When `latest.jsonl` が存在しないまたはサイズが 0 バイトである, the logging system shall ローテーションをスキップし、新しい `latest.jsonl` への書き込みを直接開始する

### Requirement 2: アーカイブファイルの命名と配置
**Objective:** As a サーバー運用者, I want 過去ログが日付順で識別しやすいファイル名で保存される, so that 特定の日時のログを迅速に見つけられる

#### Acceptance Criteria
1. The logging system shall アーカイブファイルを `{YYYY-MM-DD}-{N}.jsonl.gz` の命名規則で生成する（N は同日内の連番、1 始まり）
2. The logging system shall アーカイブファイルを `latest.jsonl` と同じディレクトリに配置する
3. When 同日に複数回サーバーが再起動される, the logging system shall 連番 N をインクリメントして重複しないファイル名を生成する

### Requirement 3: アーカイブの保持ポリシー
**Objective:** As a サーバー運用者, I want 古いアーカイブが自動的に削除される, so that ログディレクトリのストレージ使用量が際限なく増大しない

#### Acceptance Criteria
1. When ローテーション実行後にアーカイブファイルの総数が設定された最大保持件数を超える, the logging system shall 最も古いアーカイブファイルから順に削除して最大保持件数以下にする
2. The logging system shall デフォルトの最大保持件数を 30 件とする
3. The logging system shall 最大保持件数を設定で変更可能にする

### Requirement 4: ファイルログの常時有効化
**Objective:** As a サーバー運用者, I want ファイルログが常に記録される, so that プロセス異常終了時にもログが残りトラブルシュートできる

#### Acceptance Criteria
1. The logging system shall JSONL ファイルログを常に有効にする（ON/OFF の切り替え設定は廃止）
2. The logging system shall ログ出力先ディレクトリをデフォルト `logs` として設定で変更可能にする

### Requirement 5: マルチプロセス対応
**Objective:** As a サーバー運用者, I want app プロセスと worker プロセスの両方のログが同じファイルに統合される, so that 一つのログファイルでサーバー全体の動作を追跡できる

#### Acceptance Criteria
1. The logging system shall 複数プロセスから同じ `latest.jsonl` への同時書き込みをサポートする
2. When 複数プロセスが同時に起動してローテーションを実行しようとする, the logging system shall ファイルロックによる排他制御で一つのプロセスのみがローテーションを実行する
3. When ファイルロックの取得に失敗したプロセス, the logging system shall ローテーションをスキップして通常のログ書き込みを開始する

### Requirement 6: エラー耐性
**Objective:** As a サーバー運用者, I want ログローテーションの失敗がサーバーの起動を妨げない, so that ディスク障害やパーミッション問題があってもサービスを継続できる

#### Acceptance Criteria
1. If ログディレクトリの作成に失敗する, the logging system shall 警告を stderr に出力してコンソールログのみで動作を継続する
2. If アーカイブファイルのリネームや圧縮に失敗する, the logging system shall 警告を stderr に出力してローテーションをスキップし、既存の `latest.jsonl` への追記で動作を継続する
3. If 古いアーカイブファイルの削除に失敗する, the logging system shall 警告を stderr に出力して残りの処理を継続する

### Requirement 7: 設定フィールドの再設計
**Objective:** As a サーバー運用者, I want ログ関連の設定が新しいローテーション機能に合わせて整理される, so that 設定が直感的で過不足ない

#### Acceptance Criteria
1. The logging system shall ログ出力先ディレクトリの設定 (`log_dir`) を提供する
2. The logging system shall アーカイブ最大保持件数の設定 (`log_max_files`) を提供する
3. When 以前の設定フィールド (`log_json_enabled`, `log_json_path`) が使用される, the logging system shall それらを認識せず、新しい設定フィールドのみを参照する
