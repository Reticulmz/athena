# Implementation Plan

- [ ] 1. Foundation: ルーティング基盤とインターフェース拡張

- [x] 1.1 RouteGroup ルーティング基盤の実装
  - `_ROUTE_KEYS` モジュールレベル辞書と `@route(key)` デコレータを実装する（デコレータは辞書への登録のみ、メソッドへの属性付与なし）
  - `RouteGroup` 基底クラスを実装する。`__init_subclass__` でクラス定義時に `_ROUTE_KEYS` を走査し `__routes__: ClassVar` に収集する
  - `get_routes()` メソッドで `(key, bound_method)` イテレータを返す
  - ユニットテスト: デコレータによるメソッド収集、`__routes__` の自動構築、`get_routes` が正しいバウンドメソッドを返すこと、デコレータなしメソッドが収集されないこと
  - `rtk basedpyright src/osu_server/transports/bancho/routing.py` が型エラーなしで通ること
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 1.2 (P) SessionStore インターフェース拡張
  - `SessionStore` Protocol に `delete_by_user(user_id: int) -> None` と `get_all_user_ids() -> list[int]` を追加する
  - `InMemorySessionStore` に両メソッドを実装する。`delete_by_user` は存在しない user_id に対してエラーなし（冪等）
  - `RedisSessionStore` に両メソッドを実装する。`delete_by_user` は `user:{user_id}:session` キーから token を取得して両キーを削除、存在しない場合は no-op
  - ユニットテスト: 正常系、冪等性（存在しない user_id）、空ストアでの `get_all_user_ids` が空リスト
  - `rtk pytest tests/unit/ -k session_store` が全テスト通過すること
  - _Requirements: 6.1, 6.5_
  - _Boundary: SessionStore, InMemorySessionStore, RedisSessionStore_

- [ ] 2. Core: 基盤クラスとドメインモデル

- [x] 2.1 HandlerGroup + ListenerGroup 基盤クラスの実装
  - `HandlerGroup(RouteGroup)` を実装する。`handles = route` エイリアスと `register_all(dispatcher)` メソッド。内部で `dispatcher.register(packet_id)(handler)` のデコレータ呼び出しパターンを使用する
  - `ListenerGroup(RouteGroup)` を実装する。`listens = route` エイリアスと `register_all(event_bus)` メソッド。内部で `event_bus.subscribe(event_type, handler)` を呼び出す
  - 両クラスの `register_all` で登録完了時にグループ名と登録数を構造化ログに記録する。登録メソッドが0件の場合は警告ログを出力する
  - ユニットテスト: register_all 後に dispatcher/event_bus に正しく登録されること、空グループで警告ログが出ること、重複パケット ID で DuplicateHandlerError が発生すること
  - `rtk basedpyright` が handlers/base.py と listeners/base.py に対して型エラーなしで通ること
  - _Requirements: 1.5, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3_

- [x] 2.2 (P) UserDisconnected ドメインイベント + OnlineUsersService の実装
  - `domain/users/` ディレクトリを作成する（`__init__.py` 含む）
  - `domain/users/events.py` に `UserDisconnected(Event)` を定義する。`@dataclass(frozen=True, slots=True)` で不変、`user_id: int` フィールドを持つ
  - `services/online_users.py` に `OnlineUsersService` を実装する。コンストラクタで `SessionStore` を受け取り、`get_all_user_ids()` は SessionStore に委譲する
  - ユニットテスト: UserDisconnected の不変性（frozen）、OnlineUsersService が SessionStore に正しく委譲すること
  - `domain/events/__init__.py` からの既存 `Event` 基底クラスのインポートパスが正しいこと
  - _Requirements: 7.1, 7.2, 7.3, 6.3_
  - _Boundary: domain/users/events.py, services/online_users.py_
  - _Depends: 1.2_

- [ ] 3. Core: ハンドラとリスナー実装

- [x] 3.1 LifecycleHandlers の実装（PONG + EXIT）
  - `LifecycleHandlers(HandlerGroup)` クラスを実装する。コンストラクタで `SessionStore` と `EventBus` を受け取る
  - `@handles(ClientPacketID.PONG)` の `handle_pong` メソッドを実装する（メソッド本体は `pass`）。ログは既存の PacketDispatcher の QUIET_C2S_PACKETS 機構で DEBUG レベル出力されることを確認する
  - `@handles(ClientPacketID.EXIT)` の `handle_exit` メソッドを実装する。try ブロックでイベント発火、finally ブロックでセッション削除を保証する。`delete_by_user` の冪等性により2回目の EXIT もエラーなし
  - ユニットテスト: handle_pong が例外なく完了、handle_exit で SessionStore.delete_by_user と EventBus.fire が呼ばれること、イベント発火失敗時もセッション削除が実行されること、冪等性（2回目の EXIT がエラーにならない）
  - `rtk pytest tests/unit/test_lifecycle_handlers.py` が全テスト通過すること
  - _Requirements: 5.1, 5.2, 6.1, 6.2, 6.4, 6.5, 6.6, 9.1_

- [x] 3.2 (P) LifecycleListeners の実装（UserDisconnected → USER_QUIT 配信）
  - `LifecycleListeners(ListenerGroup)` クラスを実装する。コンストラクタで `OnlineUsersService` と `PacketQueue` を受け取る
  - `@listens(UserDisconnected)` の `on_user_disconnected` メソッドを実装する。全オンラインユーザーの PacketQueue に USER_QUIT パケットを enqueue し、退出ユーザー自身は配信対象から除外する
  - ユニットテスト: 全オンラインユーザーに USER_QUIT が enqueue されること、退出ユーザー自身が除外されること、オンラインユーザーが0人の場合にエラーなく完了すること
  - `rtk pytest tests/unit/test_lifecycle_listeners.py` が全テスト通過すること
  - _Requirements: 6.3, 9.1_
  - _Boundary: listeners/lifecycle.py_
  - _Depends: 2.1, 2.2_

- [ ] 4. Integration: 統合配線

- [x] 4.1 PacketHandler 型厳格化 + user_id 伝達 + composition root 配線
  - `dispatch.py` の `PacketHandler` 型を `Callable[..., Awaitable[None]]` から `Callable[[bytes, int], Awaitable[None]]` に変更する
  - `login.py` の `_handle_polling` 内の dispatch 呼び出しに `user_id` 引数を追加する（1行変更）
  - `app.py` の `_register_services` に LifecycleHandlers / LifecycleListeners / OnlineUsersService の生成と登録を追加する
  - `listeners/__init__.py` の `setup_listeners` を ListenerGroup ベースに変更する（LifecycleListeners の register_all 呼び出し）
  - `rtk basedpyright src/` が型エラーなしで通ること
  - _Requirements: 4.1, 4.2_

- [ ] 5. Validation: 統合・E2E テスト

- [x] 5.1 統合テスト
  - EXIT パイプライン統合テスト: LifecycleHandlers.handle_exit → InMemoryEventBus → LifecycleListeners.on_user_disconnected → InMemoryPacketQueue に USER_QUIT が投入されること
  - HandlerGroup + PacketDispatcher 統合テスト: register_all 後に dispatch が正しいハンドラを呼ぶこと
  - ListenerGroup + EventBus 統合テスト: register_all 後に fire が正しいリスナーを呼ぶこと
  - `rtk pytest tests/integration/test_c2s_pipeline.py` が全テスト通過すること
  - _Requirements: 9.2_

- [x] 5.2 E2E テスト
  - EXIT → USER_QUIT 配信: HTTP POST（EXIT パケット含む）送信後、他ユーザーの polling レスポンスに USER_QUIT バイトが含まれること
  - PONG 受理: HTTP POST（PONG パケット含む）がエラーなく空レスポンスを返すこと
  - 例外隔離の動作確認: 不正ペイロードのパケット + PONG の組み合わせで、既存の LoginHandler try/except が新しい2引数シグネチャで正しく機能し、PONG が正常に処理されること
  - `rtk pytest tests/e2e/test_c2s_e2e.py` が全テスト通過すること
  - _Requirements: 8.1, 8.2, 8.3, 9.3_
