# Implementation Plan

- [ ] 1. Foundation: ドメイン横断 Protocol の shared/ports/ 移動
- [x] 1.1 shared/ports/ ディレクトリを新設し leaderboard_rebuild_wake Protocol を移動する
  - shared/ports/__init__.py を作成し、BeatmapLeaderboardRebuildWorkerWake と NoopBeatmapLeaderboardRebuildWorkerWake を公開する
  - services/commands/leaderboard_rebuild_wake.py の内容を shared/ports/leaderboard_rebuild.py に移動する
  - services/commands/leaderboard_rebuild_wake.py を削除する
  - 消費側 (identity/change_role.py, beatmaps/fetch.py, scores/leaderboards/__init__.py) の import path を shared.ports に更新する
  - composition/providers/ (beatmaps.py, identity.py, scores.py) の import path を shared.ports に更新する
  - basedpyright と ruff check がエラーなしで通ること
  - _Requirements: 4.1, 4.2_

- [ ] 2. Core: BeatmapHttpClient Protocol の分離
- [x] 2.1 (P) infrastructure/http/interfaces.py を新設し BeatmapHttpClient Protocol を定義する
  - BeatmapHttpClient の公開メソッドシグネチャを Protocol として定義する
  - HttpFetchResult dataclass を interfaces.py に移動する
  - is_permanent_error 関数は具象側 (beatmap_http_client.py) に残す
  - beatmap_http_client.py の具象 BeatmapHttpClient が Protocol を満たす形に調整する
  - infrastructure/http/__init__.py の re-export を interfaces.py 経由に更新する
  - services/queries/beatmaps/mirror/file_provider_service.py と metadata_provider_service.py の import path を interfaces 経由に更新する
  - basedpyright がエラーなしで通ること
  - _Requirements: 1.2, 2.1, 2.2_
  - _Boundary: infrastructure/http_

- [ ] 3. Core: 旧 leaderboard_rebuild_wake パスの消費側更新漏れ確認
- [x] 3.1 (P) 旧 import path の残存参照を grep で検出し、ゼロであることを確認する
  - `grep -rn 'leaderboard_rebuild_wake' src/` で旧パス (services.commands.leaderboard_rebuild_wake) への参照がゼロであること
  - `grep -rn 'from osu_server.services.commands.leaderboard' src/` がゼロ件であること
  - テスト側 (`tests/`) にも旧パスの参照が残っていないこと
  - 残存があれば import path を shared.ports に更新する
  - _Requirements: 4.3_
  - _Boundary: shared/ports_

- [ ] 4. Integration: import-linter 契約の追加と全体検証
- [x] 4.1 pyproject.toml に具象 infrastructure 遮断の forbidden 契約を追加する
  - "Services don't import concrete infrastructure backends" 契約を追加し、services から具象バックエンドモジュールへの直接 import を禁止する
  - "Cross-domain protocols live in shared ports" 契約を追加し、旧 leaderboard_rebuild_wake パスへの依存を禁止する
  - 契約追加前に、forbidden_modules に指定するモジュールパスが実在するか確認する
  - `uv run lint-imports` が既存 13 契約 + 新規契約すべてパスし Exit Code 0 を返すこと
  - _Requirements: 2.3, 3.2, 3.3, 4.3, 5.1, 5.2, 5.3, 5.4_
  - _Depends: 1.1, 2.1, 3.1_

- [ ] 5. Validation: 全品質ゲートの通過確認
- [x] 5.1 全静的解析とテストを実行し、リグレッションがないことを確認する
  - `ruff format --check src/` がパスすること
  - `ruff check src/` がパスすること
  - `basedpyright src/` がパスすること
  - `uv run lint-imports` が全契約パスすること (既存 13 + 新規)
  - `pytest tests/` が全テストパスすること
  - Dishka provider 構成が変更前と同一の依存解決グラフを構築すること (既存テストで検証)
  - _Requirements: 6.1, 6.2, 6.3, 6.4_
  - _Depends: 4.1_
