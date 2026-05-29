# Implementation Plan

- [x] 1. Protocol 移動 + 型変更
- [x] 1.1 SessionStore Protocol を repositories/interfaces/ に移動し、型シグネチャを SessionData ベースに変更
  - `infrastructure/state/interfaces/session_store.py` を `repositories/interfaces/session_store.py` に移動
  - `from osu_server.domain.session import SessionData` をトップレベルでインポート（`runtime_checkable` Protocol のため `TYPE_CHECKING` ガード不要）
  - `create()` の `data` パラメータ型を `dict[str, object]` → `SessionData` に変更
  - `get()` / `get_by_user()` の戻り値型を `dict[str, object] | None` → `SessionData | None` に変更
  - `delete()`, `exists()`, `refresh()` のシグネチャは変更なし
  - 旧ファイル `infrastructure/state/interfaces/session_store.py` を削除
  - basedpyright が新 Protocol ファイルで型エラーを報告しないこと
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 4.1, 4.2_

- [x] 2. 実装の移動 + 型対応
- [x] 2.1 (P) InMemorySessionStore を repositories/memory/ に移動し、SessionData ベースに変更
  - `infrastructure/state/memory/session_store.py` を `repositories/memory/session_store.py` に移動
  - 内部ストレージ `_by_token` の型を `dict[str, dict[str, object]]` → `dict[str, SessionData]` に変更
  - `create()` は `SessionData` をそのまま保存
  - `get()` / `get_by_user()` は `dataclasses.replace(data)` でコピーを返す（`dict(data)` を置換）
  - 同一 user_id での `create()` 呼び出し時に旧セッションが正しく置換されること（既存の overwrite 動作維持）
  - 旧ファイルを削除
  - InMemorySessionStore が SessionStore Protocol を満たすこと（isinstance チェック）
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 4.1, 4.4_
  - _Boundary: InMemorySessionStore_

- [x] 2.2 (P) RedisSessionStore を repositories/redis/ に移動し、_INTERNAL_USER_ID_KEY ハックを廃止
  - `repositories/redis/` ディレクトリと `__init__.py` を新規作成
  - `infrastructure/state/redis/session_store.py` を `repositories/redis/session_store.py` に移動
  - `_INTERNAL_USER_ID_KEY` 定数と関連する追加・除去処理を全て削除
  - `create()`: `asdict(data)` で JSON シリアライズ。`_user_id` 内部キーの追加を廃止し、`SessionData.user_id` を Lua スクリプトで使用
  - `get()` / `get_by_user()`: `SessionData(**json.loads(raw))` で復元
  - Lua スクリプト内の `_user_id` フィールド参照を `user_id` に更新
  - `get()` 内の `pop(_INTERNAL_USER_ID_KEY)` 処理を削除
  - 同一 user_id での `create()` 呼び出し時に旧セッションが正しく置換されること（既存の overwrite 動作維持）
  - 旧ファイルを削除
  - RedisSessionStore が SessionStore Protocol を満たすこと
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 4.1, 4.4_
  - _Boundary: RedisSessionStore_

- [x] 3. 利用側コードの更新
- [x] 3.1 インポートパス更新 + 型キャスト除去
  - `providers.py`: SessionStore / InMemorySessionStore / RedisSessionStore のインポートパスを `repositories/` に変更
  - `app.py`: SessionStore のインポートパスを `repositories/interfaces/session_store` に変更
  - `auth_service.py`: SessionStore のインポートパスを変更、`asdict(session_data)` を除去して `SessionData` を直接渡す
  - `login.py`: SessionStore のインポートパスを変更、`int(session["user_id"])` → `session.user_id` に変更、`# pyright: ignore[reportArgumentType]` を除去
  - 全利用側ファイルで SessionStore 関連の `# pyright: ignore` が存在しないこと
  - _Requirements: 2.3, 4.1, 4.3, 5.1, 5.2, 5.3_
  - _Depends: 2.1, 2.2_

- [x] 4. テスト更新 + 最終検証
- [x] 4.1 テストファイルの更新
  - `tests/unit/infrastructure/state/test_session_store.py` のインポートパスを `repositories/` に更新
  - `tests/integration/test_redis_session_store.py` のインポートパスを `repositories/` に更新
  - テストデータを `dict` → `SessionData` インスタンスに変更
  - テストのアサーションを `SessionData` フィールドアクセスに更新
  - ログイン→セッション作成→ポーリングの一連フローをカバーする既存統合テスト（`test_polling_e2e.py`）がパスすること
  - 全テストがパスすること
  - _Requirements: 6.1, 6.2, 6.3_
  - _Depends: 3.1_

- [x] 4.2 basedpyright + import-linter + 全テストスイート実行
  - `basedpyright src/` が SessionStore 関連ファイルで型エラーを報告しないこと
  - `import-linter` がレイヤー違反を報告しないこと
  - `pytest tests/` が全テストパスすること（684+ テスト）
  - _Requirements: 4.3, 5.2, 6.1_
  - _Depends: 4.1_
