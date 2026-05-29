# Research & Design Decisions

## Summary
- **Feature**: `c2s-handlers`
- **Discovery Scope**: Extension（既存の PacketDispatcher / EventBus / PacketQueue インフラ上に構築）
- **Key Findings**:
  - 既存インフラ（PacketDispatcher, EventBus, PacketQueue）は C2S ハンドラ追加に対応可能。dispatch の user_id 伝達修正のみ必要
  - SessionStore.delete は token ベースで user_id ベースの削除が欠如 → `delete_by_user` 追加が必要
  - 全オンラインユーザー列挙は SessionStore の責務ではなく、OnlineUsersService として分離

## Research Log

### PacketDispatcher の拡張性
- **Context**: C2S ハンドラの DI パターン選定
- **Findings**:
  - `dispatch(packet_id, payload, *args, **kwargs)` は既に可変引数を handler に転送する設計
  - `register()` は callable を受け取るため、バウンドメソッドもそのまま登録可能
  - PacketHandler 型は `Callable[..., Awaitable[None]]` で緩い → 厳格化が望ましい
- **Implications**: 既存の dispatch/register インターフェースへの変更は不要。型定義の厳格化のみ

### SessionStore インターフェースのギャップ
- **Context**: EXIT ハンドラがセッション削除を実行する際、user_id しか持っていないが delete は token ベース
- **Findings**:
  - `delete(token: str)` のみ存在。`delete_by_user(user_id: int)` が未実装
  - InMemorySessionStore / RedisSessionStore の両方に追加が必要
  - Redis 実装は `user:{user_id}:session` キーで user_id → token マッピングを保持している
- **Implications**: SessionStore Protocol と2つの実装に `delete_by_user` を追加

### オンラインユーザー列挙の責務
- **Context**: EXIT 時に全オンラインユーザーへ USER_QUIT を配信する必要
- **Findings**:
  - SessionStore に `get_all_user_ids()` を追加する案は責務超過
  - 一度 SessionStore に追加すると移行コストが発生しやすい
  - OnlineUsersService は将来 presence-status で拡張される前提
- **Implications**: OnlineUsersService を services 層に新設。今は SessionStore に委譲、将来 Redis SET ベースに差し替え可能

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| A. kwargs 透過 | dispatch に全依存を毎回渡す | シンプル | LoginHandler 密結合、引数肥大化 | 却下 |
| B. クロージャ | setup 関数内でクロージャ生成 | デコレータ co-location | テストで直接呼べない | 却下 |
| C. コンテキストオブジェクト | HandlerContext を毎回渡す | 引数1つ | God Object 化、LoginHandler 密結合 | 却下 |
| D. ハンドラクラス 1:1 | 1クラス1ハンドラ + composition root 登録 | 疎結合、テスト容易 | デコレータ不可、登録忘れリスク | 却下 |
| E. HandlerGroup + RouteGroup | ドメイン別グループクラス + @handles デコレータ | 宣言的、DI、テスト容易、登録漏れ防止 | RouteGroup インフラが必要 | **採用** |

## Design Decisions

### Decision: DI パターン — HandlerGroup + @handles デコレータ

- **Context**: ハンドラが SessionStore / EventBus 等の依存にアクセスする方法
- **Alternatives Considered**:
  1. kwargs 透過 — LoginHandler に全依存が集中
  2. クロージャ — テストで直接呼べない
  3. コンテキストオブジェクト — God Object 化リスク
  4. 1:1 ハンドラクラス — デコレータと相性が悪い、登録忘れリスク
  5. HandlerGroup + RouteGroup — 宣言的デコレータとクラス DI を両立
- **Selected Approach**: E. HandlerGroup（RouteGroup 継承）に @handles デコレータでパケット ID を宣言し、コンストラクタで依存注入
- **Rationale**: FastAPI 的な宣言的 DX、クラスベースの DI でテスト容易、ドメイン別グルーピングと自然に一致
- **Trade-offs**: RouteGroup というカスタムインフラが必要だが、routing.py 1ファイルに閉じている
- **Follow-up**: basedpyright strict との互換性確認

### Decision: ルートキー保持 — モジュールレベル辞書

- **Context**: @route デコレータがメソッドとキーの対応をどこに保持するか
- **Alternatives Considered**:
  1. メソッドに `__route_key__` 属性を付ける — basedpyright が嫌う
  2. モジュールレベル辞書 `_ROUTE_KEYS` で管理 — 型安全
- **Selected Approach**: 2. モジュールレベル辞書
- **Rationale**: basedpyright strict と完全互換、`type: ignore` 不要
- **Trade-offs**: 辞書が関数への参照を保持し続けるが、クラスメソッドのため実質的に問題なし

### Decision: ルートスキャン — `__init_subclass__`

- **Context**: デコレータ付きメソッドの収集タイミング
- **Alternatives Considered**:
  1. `__init_subclass__` でクラス定義時に1回スキャン
  2. `get_routes()` で呼び出し時に毎回スキャン
- **Selected Approach**: 1. `__init_subclass__`
- **Rationale**: 結果がキャッシュされデバッグ性が高い（`cls.__routes__` で即確認可能）。routing.py 1ファイルに閉じた5行の追加で複雑性は許容範囲
- **Trade-offs**: メタプログラミングだが、Django/Pydantic/dataclass で広く使われるパターン

### Decision: S2C 応答方式 — EventBus 経由

- **Context**: ハンドラが他ユーザーに S2C パケットを配信する方法
- **Alternatives Considered**:
  1. PacketQueue に直接 enqueue — ハンドラに S2C の知識が漏れる
  2. return でパケットを返す — 宛先パターンが多様で EventBus の劣化版になる
  3. EventBus 経由 — ハンドラは「何が起きたか」のみ発火
- **Selected Approach**: 3. EventBus 経由
- **Rationale**: ハンドラ（C2S 解釈）とリスナー（S2C 配信）の責務が分離。複数リスナーが同一イベントを購読可能
- **Trade-offs**: 間接的だが、レイヤー分離と拡張性を得る

### Decision: OnlineUsersService 分離

- **Context**: EXIT 時に全オンラインユーザーを列挙する方法
- **Alternatives Considered**:
  1. SessionStore.get_all_user_ids() — 責務超過、API 追加後に移行しにくい
  2. OnlineUsersService — 設計意図明示、presence-status で拡張前提
- **Selected Approach**: 2. OnlineUsersService
- **Rationale**: SessionStore に追加すると固定化しやすい。サービスとして分離すれば内部実装を差し替え可能
- **Trade-offs**: 今は SessionStore のラッパーに見えるが、presence-status で責務が膨らむ

## Synthesis Outcomes

### Generalization
- RouteGroup は HandlerGroup と ListenerGroup の共通基盤。同じ `@route` / `__init_subclass__` / `get_routes()` パターンで動作
- bancho 以外（SignalR, API）で必要になれば `infrastructure/` に昇格可能だが、現時点では YAGNI で bancho 配下に配置

### Build vs. Adopt
- ルーティング基盤は自前構築（既存ライブラリで bancho プロトコルの要件を満たすものがない）
- 約50行の小さなインフラで、外部依存を増やすより適切

### Simplification
- PresenceService は今回作らない（STATUS_CHANGE 等のハンドラがスコープ外）
- ハンドラ継承は禁止（暗黙的結合を防ぐ）
- PacketQueue の即時削除不要（TTL 自然消滅で十分）

## Risks & Mitigations
- `_ROUTE_KEYS` 辞書が GC を阻害するリスク → クラスメソッドは元々クラスが参照保持するため実質的に問題なし
- `__init_subclass__` の動作が継承チェーンで混乱するリスク → `vars(cls)` で自クラスのみ走査、ハンドラ継承を規約で禁止
- OnlineUsersService が YAGNI と見なされるリスク → presence-status での拡張が確定しており、設計意図の明示という価値がある
