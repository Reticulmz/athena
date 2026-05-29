# Implementation Plan

## Implementation Rules (全タスク共通)

> **各タスク着手前**に以下の規約ファイルを再読み込みし、実装がルールから逸脱していないか確認すること。
> 長時間作業でコンテキストからルールが欠落する傾向があるため、タスクの区切りごとに必ず再読み込みを行う。

### 必読規約ファイル
- `.agents/rules/code-quality.md` -- 既存パターン遵守、SOLID/DRY/KISS/YAGNI、Self-Review Loop
- `.agents/rules/type-safety-policy.md` -- basedpyright strict、ハック禁止、インライン抑制は最終手段のみ
- `.agents/rules/senior-engineer-conduct.md` -- 根本原因分析、No Silent Failures、Chain of Thought

### 完了前チェック (全タスク必須)
1. `ruff check src/` -- lint エラーなし
2. `ruff format --check src/` -- フォーマット準拠
3. `basedpyright src/` -- 型チェック pass
4. `pytest tests/` -- 関連テスト pass
5. Self-Review Loop: ロジックエラー、エッジケース、レイヤー違反、型安全性、可読性を自己レビュー
6. 既存テストを壊していないことを確認 (テスト失敗時はまず実装を疑う)

### このフィーチャー固有の注意事項
- `infrastructure/logging.py` は `config` のみに依存する (TYPE_CHECKING)。services / transports / domain からの import 禁止
- エラーハンドリングは既存パターン (`warnings.warn` + 続行) を踏襲する
- `# pyright: ignore[reportAny]` は structlog 由来の箇所のみ許容

---

- [x] 1. Foundation: config フィールド再設計
- [x] 1.1 AppConfig のログ関連フィールドを再設計する
  - `log_json_enabled: bool` と `log_json_path: str` を削除し、`log_dir: str = "logs"` と `log_max_files: int = 30` を追加する
  - `log_max_files` に `@field_validator` を追加し、0 以上の整数であることを検証する
  - 既存の `_normalize_log_level` バリデータは変更しない
  - 環境変数 `LOG_DIR` / `LOG_MAX_FILES` で設定可能であることを確認する
  - `log_json_enabled` / `log_json_path` を参照している既存テストやフィクスチャを新しいフィールドに更新する
  - テスト: `AppConfig(log_dir="custom", log_max_files=10)` で正しくインスタンス化できる。`log_max_files=-1` で `ValueError` が発生する
  - _Requirements: 3.2, 3.3, 4.2, 7.1, 7.2, 7.3_
  - _Boundary: AppConfig_

- [ ] 2. Core: rotate_logs 関数の実装
- [ ] 2.1 ログファイルのアーカイブ・圧縮ロジックを実装する
  - `latest.jsonl` の存在・サイズチェックを行い、不在/空ならスキップする
  - 既存の `{today}-*.jsonl.gz` をスキャンして最大連番を取得し、`{YYYY-MM-DD}-{N+1}.jsonl.gz` で命名する
  - `latest.jsonl` を読み取り、`gzip.open()` で圧縮アーカイブを生成し、元ファイルを削除する
  - 全ての `OSError` を `warnings.warn` で警告して例外を伝播させない
  - テスト: 非空の `latest.jsonl` が `{date}-1.jsonl.gz` にアーカイブされ、gzip 解凍すると元の内容と一致する。空ファイルではアーカイブが生成されない
  - _Requirements: 1.1, 1.3, 2.1, 2.2, 2.3, 6.2_
  - _Boundary: rotate_logs_

- [ ] 2.2 ファイルロックによる排他制御を実装する
  - `fcntl.flock(fd, LOCK_EX | LOCK_NB)` でロックファイル (`logs/.rotation.lock`) を使用した排他制御を追加する
  - `BlockingIOError` 発生時はローテーションをスキップする
  - ロック取得成功時のみアーカイブ・圧縮・クリーンアップを実行する
  - ローテーション完了後にロックを解放する
  - テスト: ロックファイルが存在する状態で `rotate_logs` を呼ぶとローテーションがスキップされ、`warnings.warn` は呼ばれない (正常動作)
  - _Requirements: 5.2, 5.3_
  - _Boundary: rotate_logs_

- [ ] 2.3 古いアーカイブの自動削除 (保持ポリシー) を実装する
  - `*.jsonl.gz` を mtime でソートし、`max_files` を超える分を古い順に `Path.unlink()` で削除する
  - 個別ファイルの削除失敗は `warnings.warn` で警告して残りの処理を続行する
  - テスト: `max_files=3` で 5 個のアーカイブがある場合、古い 2 個が削除され 3 個が残る。削除エラー時は警告のみで例外が伝播しない
  - _Requirements: 3.1, 6.3_
  - _Boundary: rotate_logs_

- [ ] 3. Integration: setup_logging 改修と worker 対応
- [ ] 3.1 setup_logging にローテーション呼び出しと常時ファイルログを統合する
  - `setup_logging` の冒頭で `rotate_logs(Path(config.log_dir), config.log_max_files)` を呼び出す
  - `log_json_enabled` のチェックを削除し、JSON file handler を常に作成する
  - FileHandler のパスを `Path(config.log_dir) / "latest.jsonl"` に変更する
  - ディレクトリ作成 (`mkdir(parents=True, exist_ok=True)`) の `OSError` は `warnings.warn` で警告してコンソールのみで続行
  - `logging_configured` イベントのログ出力を新しいフィールドに合わせて更新する
  - テスト: `setup_logging` 後に root logger に FileHandler が設定され、`latest.jsonl` にログが書き込まれる
  - _Requirements: 1.2, 4.1, 5.1, 6.1_
  - _Depends: 1.1, 2.1, 2.2, 2.3_
  - _Boundary: setup_logging_

- [ ] 3.2 worker プロセスに setup_logging 呼び出しを追加する
  - `worker.py` の startup イベントハンドラ内で `setup_logging(config)` を呼び出す
  - app プロセスと同じ `latest.jsonl` にログが出力されることを確認する
  - テスト: worker の startup 後に structlog のカスタムプロセッサ (mask_sensitive_fields 等) が有効になっている
  - _Requirements: 5.1_
  - _Depends: 3.1_
  - _Boundary: worker.py_

- [ ] 4. Validation: ユニットテスト
- [ ] 4.1 rotate_logs のユニットテストを作成する
  - `tests/unit/test_log_rotation.py` を新規作成する
  - 正常ローテーション: 非空 latest.jsonl がアーカイブされ gzip 圧縮される (1.1)
  - スキップ: latest.jsonl が不在/空でローテーションがスキップされる (1.3)
  - 命名規則: `{date}-{N}.jsonl.gz` 形式で同日の連番が正しくインクリメントされる (2.1, 2.3)
  - 保持ポリシー: max_files 超過で古いアーカイブが削除される (3.1)
  - ファイルロック: ロック取得失敗でローテーションがスキップされる (5.2, 5.3)
  - エラー耐性: OSError 発生時に warnings.warn が呼ばれ例外が伝播しない (6.2, 6.3)
  - 全テストが `pytest tests/unit/test_log_rotation.py` で pass する
  - _Requirements: 1.1, 1.3, 2.1, 2.3, 3.1, 5.2, 5.3, 6.2, 6.3_
  - _Depends: 2.1, 2.2, 2.3_
  - _Boundary: rotate_logs_

- [ ] 4.2 setup_logging 改修の統合テストを作成する
  - setup_logging がローテーションを呼び出し、latest.jsonl に FileHandler が設定されることを検証する (1.2, 4.1)
  - config の `log_dir` / `log_max_files` を設定して正しく動作することを検証する (7.1, 7.2)
  - 旧設定フィールドが存在しないことを検証する (7.3)
  - 全テストが pass する
  - _Requirements: 1.2, 4.1, 7.1, 7.2, 7.3_
  - _Depends: 3.1_
  - _Boundary: setup_logging_
