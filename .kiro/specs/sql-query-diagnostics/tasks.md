# 実装計画

- [ ] 1. Foundation: SQL diagnostics collector と engine instrumentation を作る
- [x] 1.1 Query diagnostics collector の unit tests を先に追加する
  - SQL normalization、fingerprint、duplicate threshold、params 非保存、scope reset を RED として確認する
  - No active scope では query が蓄積されないことを確認する
  - Failure output 用 summary が SQL params や raw values を含まないことを確認する
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 4.1, 4.2, 4.3_
  - _Boundary: Query Diagnostics Collector_

- [x] 1.2 Query diagnostics collector と SQLAlchemy event install を実装する
  - `shared/query_diagnostics.py` に collector、summary dataclass、context manager を追加し、`infrastructure/database/query_diagnostics.py` に event installer を追加する
  - `create_engine` が作成した AsyncEngine に diagnostics event listener を idempotent に install する
  - Listener は active scope がない場合に no-op になり、scope exit で contextvars が reset されることが tests から確認できる
  - _Depends: 1.1_
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 4.1, 4.2, 4.3, 5.2, 5.4_
  - _Boundary: Query Diagnostics Collector, Database Engine_

- [ ] 2. Test: pytest query budget fixture と hot path budgets を追加する
- [x] 2.1 Query budget fixture の tests と fixture 実装を追加する
  - Budget 超過時に redacted summary で hard fail する RED test を追加する
  - Budget 内の SQL count だけを対象にし、未使用 test には影響しない fixture を実装する
  - DB unavailable skip を budget fixture が上書きしないことが確認できる
  - _Depends: 1.2_
  - _Requirements: 2.1, 2.2, 2.3, 2.5, 4.1, 4.2, 4.3_
  - _Boundary: Pytest Query Budget_

- [x] 2.2 Replay download / score submission integration hot path の baseline を測定して budget を設定する
  - Setup/cleanup を scope 外に置き、hot path のみ query budget で囲む
  - Baseline count を測定して小さな余白を加えた budget にする
  - Targeted PostgreSQL integration tests が budget 付きで pass することを確認する
  - _Depends: 2.1_
  - _Requirements: 2.1, 2.2, 2.4, 2.5_
  - _Boundary: Integration Test Budgets_

- [ ] 3. Runtime: development warning scope を HTTP と Taskiq に接続する
- [x] 3.1 AppConfig に runtime SQL diagnostics 設定と validation を追加する
  - `query_diagnostics_enabled`、`query_diagnostics_max_queries`、`query_diagnostics_duplicate_threshold` を追加する
  - Effective enabled state が development 既定、production/test 既定 disabled、明示 override 可能であることを unit tests で確認する
  - 不正な threshold が config validation error になることを確認する
  - _Requirements: 3.5, 4.5, 5.1, 5.5_
  - _Boundary: AppConfig_

- [x] 3.2 Starlette request SQL diagnostics middleware を追加して application に wiring する
  - Development かつ threshold 超過時に `sql_query_diagnostics_warning` が 1 回出る tests を追加する
  - Disabled / non-development では warning が出ない tests を追加する
  - Scope name は method + path にし、query string や credential value が出ないことを確認する
  - _Depends: 1.2, 3.1_
  - _Requirements: 3.1, 3.2, 3.5, 4.1, 4.2, 4.3, 4.4, 5.2, 5.3_
  - _Boundary: Starlette SQL Diagnostics Middleware_

- [x] 3.3 Taskiq job SQL diagnostics integration を追加する
  - Taskiq middleware / wrapper の型安全な接続点を確認し、broker に一度だけ install する
  - Development かつ threshold 超過時に job 名付き warning が出る tests を追加する
  - Job adapter 関数に診断責務を追加しないことを diff review で確認する
  - _Depends: 1.2, 3.1_
  - _Requirements: 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 5.2, 5.3_
  - _Boundary: Taskiq SQL Diagnostics Integration_

- [ ] 4. Validation: 境界、型、安全性、quality gate を確認する
- [x] 4.1 Focused diagnostics tests と affected integration tests を通す
  - Collector / config / HTTP / Taskiq / pytest fixture の unit tests が pass する
  - Replay download と score submission の budget 付き integration tests が pass する
  - Failure がある場合は budget を緩める前に実装の scope と counting semantics を確認する
  - _Depends: 2.2, 3.2, 3.3_
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4, 5.5_
  - _Boundary: Validation_

- [x] 4.2 Quality checks と redaction review を通す
  - `prek run --all-files` と relevant quality checks が pass する
  - Diff review で SQL params、password、token、email、blob path、raw replay bytes、complete payload が出力や fixture に混入していないことを確認する
  - `detect_changes` で affected symbols / execution flows が想定範囲であることを確認する
  - _Depends: 4.1_
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 5.2, 5.3, 5.4_
  - _Boundary: Validation_
