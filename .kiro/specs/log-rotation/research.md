# Research & Design Decisions

## Summary
- **Feature**: `log-rotation`
- **Discovery Scope**: Extension (既存のロギングインフラストラクチャの拡張)
- **Key Findings**:
  - Python stdlib の RotatingFileHandler/TimedRotatingFileHandler は「起動時トリガー」をサポートしないため、カスタム実装が必要
  - worker プロセスは現在 `setup_logging` を呼んでおらず、ファイルログが有効化されていない (要修正)
  - gzip 圧縮、ファイルロック (`fcntl`) は全て Python 標準ライブラリで完結し、外部依存は不要

## Research Log

### stdlib RotatingFileHandler の適用可否
- **Context**: 起動時ローテーションに既存の stdlib ハンドラが使えるか検討
- **Sources Consulted**: Python logging.handlers ドキュメント
- **Findings**:
  - `RotatingFileHandler`: maxBytes ベースのローテーション。起動時トリガーなし
  - `TimedRotatingFileHandler`: 時間ベース。`when='S'` 等で時間経過時にローテーション。起動時トリガーは `atTime` パラメータだが、日次ローテーションとの組み合わせのみ
  - どちらも gzip 圧縮をネイティブサポートしない
  - `namer` / `rotator` コールバックで圧縮を追加可能だが、起動時トリガーは実現できない
- **Implications**: カスタムのローテーション関数を `setup_logging` 呼び出し前に実行する設計が最もシンプル

### worker プロセスのロギング状態
- **Context**: マルチプロセス対応 (Requirement 5) のための現状調査
- **Sources Consulted**: `src/osu_server/worker.py`
- **Findings**:
  - worker.py は `structlog.get_logger(__name__)` でロガーを取得するが、`setup_logging()` を呼んでいない
  - structlog はデフォルト設定で動作し、カスタムプロセッサ (sensitive field masking 等) も適用されていない
  - worker は独自の startup イベントハンドラを持つが、そこでログ設定は行われていない
- **Implications**: worker にも `setup_logging()` 呼び出しを追加する必要がある。これにより両プロセスが同じ latest.jsonl に書き込む

### ファイルロック (`fcntl.flock`) の安全性
- **Context**: app と worker が同時起動した場合のローテーション競合防止
- **Sources Consulted**: Linux fcntl(2) man page, Python fcntl ドキュメント
- **Findings**:
  - `fcntl.flock(fd, LOCK_EX | LOCK_NB)` で非ブロッキング排他ロックが取得可能
  - ロック取得失敗時は `BlockingIOError` が発生
  - ロックファイルは `logs/.rotation.lock` として、ローテーション完了後に解放
  - プロセスクラッシュ時は OS がロックを自動解放
- **Implications**: シンプルで安全な排他制御が stdlib のみで実現可能

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| カスタム rotate_logs 関数 | setup_logging 前に呼ばれるスタンドアロン関数 | シンプル、テスタブル、stdlib のみ | 独自実装の保守コスト | 選定 |
| stdlib RotatingFileHandler カスタマイズ | namer/rotator コールバックで拡張 | 既存クラス活用 | 起動時トリガー不可、gzip 制約 | 不適合 |
| loguru | 高機能ロギングライブラリ | 多機能、ローテーション内蔵 | 外部依存追加、structlog との統合が複雑 | 不採用 |

## Design Decisions

### Decision: カスタム rotate_logs 関数
- **Context**: 起動時ローテーション + gzip 圧縮 + ファイルロックの組み合わせ
- **Alternatives Considered**:
  1. stdlib RotatingFileHandler のカスタマイズ
  2. loguru への移行
  3. カスタム関数
- **Selected Approach**: `rotate_logs(log_dir, max_files)` 関数を `setup_logging` 前に呼び出す
- **Rationale**: 最もシンプル。stdlib のみで完結し、structlog の設定と独立してテスト可能
- **Trade-offs**: 独自実装だが、ロジックは 50-80 行程度と小さい
- **Follow-up**: ファイルロック取得のタイムアウトやリトライは不要 (LOCK_NB で即座に判定)

### Decision: FileHandler mode="a" の維持
- **Context**: ローテーション後の新しい latest.jsonl への書き込みモード
- **Selected Approach**: `mode="a"` を維持
- **Rationale**: ローテーション後は空ファイルに追記するため `"w"` と `"a"` に差はない。`"a"` のままにすることで、ローテーションが何らかの理由でスキップされた場合でもログが失われない

### Synthesis: Generalization
- Requirements 1-3 は「ログアーカイブのライフサイクル管理」という一つの責務に統合
- `rotate_logs()` 関数が「アーカイブ → 圧縮 → クリーンアップ」を一括実行

### Synthesis: Simplification
- 抽象レイヤーやクラス階層は不要。トップレベル関数 1 つで完結
- RotationConfig のような専用データクラスは不要。log_dir と log_max_files を直接引数として渡す

## Risks & Mitigations
- **同時書き込みによるログ行の混在**: JSONL は行単位の append。PIPE_BUF (4096 bytes on Linux) 以内の書き込みはアトミック。structlog の JSON 出力は通常この範囲内
- **ローテーション中の書き込み競合**: ファイルロックでローテーション自体は排他。ローテーション中の他プロセスのログ書き込みは、リネーム完了まで旧ファイルに書かれるが、リネーム後は新 latest.jsonl が作成される。FileHandler の fd は旧ファイルを指し続けるため、ローテーション側でなく書き込み側の handler を再設定する必要はない (OS が fd を維持)
- **config 互換性**: `log_json_enabled` / `log_json_path` の廃止は breaking change。環境変数を設定している既存デプロイメントは新しい `LOG_DIR` / `LOG_MAX_FILES` に移行が必要

## References
- [Python logging.handlers](https://docs.python.org/3/library/logging.handlers.html)
- [fcntl.flock](https://docs.python.org/3/library/fcntl.html#fcntl.flock)
- [gzip module](https://docs.python.org/3/library/gzip.html)
- [Minecraft Log Rotation](https://minecraft.wiki/w/Tutorials/Log_files)
