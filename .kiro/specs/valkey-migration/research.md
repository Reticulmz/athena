# Research & Design Decisions

## Summary
- **Feature**: valkey-migration
- **Discovery Scope**: Extension (既存 Redis インフラの差し替え)
- **Key Findings**:
  - valkey-glide は型安全な API を提供 (`bytes | None`, `int`, `bool` 等の明示的な戻り値型)
  - redis-py → valkey-glide の API 差異は限定的だが、Lua スクリプト呼び出しとパイプラインの構文が異なる
  - ChannelStateStore と RateLimiter は DI 未登録（実装済みだが wiring されていない）

## Research Log

### valkey-glide Python API (v2.4.0)

- **Context**: redis-py の型安全性問題を根本解決するための代替クライアント調査
- **Sources Consulted**: Context7 docs, PyPI, GitHub wiki, 公式 Lua scripting guide
- **Findings**:
  - `GlideClient.create(config)` は async classmethod。`GlideClientConfiguration(addresses=[NodeAddress(host, port)])` で設定
  - `Script(code)` + `client.invoke_script(script, keys=[], args=[])` で Lua 実行。SCRIPT LOAD + EVALSHA を自動管理
  - `Batch(is_atomic=True)` でトランザクション。`client.exec(batch)` で実行
  - `await client.close()` は async method
  - 戻り値型: `get()` → `bytes | None`, `incr()` → `int`, `sismember()` → `bool`, `smembers()` → `set[bytes]`
  - `exists()` は `list[str]` を受け取り `int` を返す（redis-py と異なる）
  - `sadd/srem` は `set[str]` を受け取る（redis-py の可変長引数と異なる）
  - `scan()` は cursor が `str` 入力 / `bytes` 出力
- **Implications**: 全 Redis メソッド呼び出しで引数パターンの変換が必要。型は改善される

### 既存コードベース Redis 使用パターン

- **Context**: 移行対象の特定と影響範囲の把握
- **Findings**:
  - **7 Lua スクリプト**: SessionStore 4本、PacketQueue 3本。全て `redis.eval(script, numkeys, *keys_and_args)` パターン
  - **Pipeline 使用**: ChannelStateStore のみ (`pipeline(transaction=True)` で MULTI/EXEC)
  - **DI キー**: `redis.asyncio.Redis` クラス自体 → `GlideClient` に変更
  - **shutdown hook**: `redis.aclose()` (async) → `client.close()` (async) — 同形式で移行可能
  - **ChannelStateStore / RateLimiter**: 実装済みだが DI 未登録。移行時に wiring する必要なし（channel-system スペックが担当）
  - **worker.py**: ARQ の `RedisSettings` のみ使用。`redis.asyncio.Redis` は使わない
  - **Integration テスト**: 3ファイル。`create_redis_client()` でクライアント生成、key prefix でテスト分離

### taskiq + taskiq-redis

- **Context**: ARQ 代替としての taskiq 調査
- **Sources Consulted**: PyPI, GitHub (taskiq-python org)
- **Findings**:
  - taskiq-redis: Star 85, 活発にメンテナンス (2026-02 最終コミット)
  - taskiq-valkey: Star 8, 事実上初期段階 (2025-05 停滞) → 不採用
  - taskiq-redis は内部で redis-py を使うが、推移的依存であり自前コードからの直接 import はゼロ
  - `ListQueueBroker` / `RedisStreamBroker` / `PubSubBroker` の3種のブローカー提供
  - 現在の worker は `functions = []` の空スケルトンのため、移行コストは極小

### devenv Valkey サーバー

- **Context**: 開発環境の Redis → Valkey 切り替え
- **Findings**:
  - devenv の `services.redis` は `pkgs.redis` を使用
  - Nix で `pkgs.valkey` が利用可能か、または `services.valkey` をネイティブサポートしているかは実装フェーズで確認
  - Valkey は Redis プロトコル互換のため、接続 URL スキーマ `redis://` はそのまま使用可能

## Design Decisions

### Decision: valkey-glide Script オブジェクトの採用
- **Context**: 7本の Lua スクリプトの移行方針
- **Alternatives Considered**:
  1. `client.eval()` で単純置換
  2. `Script` オブジェクト + `invoke_script()` に移行
- **Selected Approach**: Script オブジェクト (Option 2)
- **Rationale**: SCRIPT LOAD + EVALSHA 自動管理でホットパスのパフォーマンス改善。クラス変数として `Script()` を持つ構造は現在の `Final[str]` パターンと同形
- **Trade-offs**: 初回呼び出しで SCRIPT LOAD が走るが、以降は SHA 再利用。追加コストはゼロに近い

### Decision: Batch によるトランザクション移行
- **Context**: ChannelStateStore の pipeline パターンの移行方針
- **Alternatives Considered**:
  1. Batch に置換
  2. Lua スクリプトに統合
- **Selected Approach**: Batch (Option 1)
- **Rationale**: パイプラインと Lua は用途が異なる。単純な複数コマンド一括実行は Batch が適切。valkey-glide のパターンに従う

### Decision: taskiq-redis ブローカーの採用
- **Context**: ジョブキューブローカーの選定
- **Alternatives Considered**:
  1. taskiq-redis (成熟、redis-py 推移的依存)
  2. taskiq-valkey (ネイティブだが未成熟)
- **Selected Approach**: taskiq-redis (Option 1)
- **Rationale**: Star 85 vs 8、メンテナンス状況の差が決定的。推移的依存の redis-py は自前コードの型安全に影響しない

## Risks & Mitigations

- **valkey-glide の py.typed 不在リスク** — 実装フェーズで `basedpyright` で検証。不足があればインライン抑制（ポリシー許容範囲）
- **devenv の Valkey サポート不在リスク** — `processes` で `valkey-server` を直接起動するフォールバック
- **SCAN API 差異** — cursor が `str` 入力 / `bytes` 出力。ループ条件の調整が必要

## References
- [valkey-glide PyPI](https://pypi.org/project/valkey-glide/)
- [valkey-glide GitHub](https://github.com/valkey-io/valkey-glide)
- [valkey-glide Python Lua Scripting Guide](https://glide.valkey.io/tutorials/lua-scripting/)
- [valkey-glide Migration Guide (redis-py)](https://github.com/valkey-io/valkey-glide/wiki/Migration-Guide-redis%E2%80%90py)
- [taskiq-redis PyPI](https://pypi.org/project/taskiq-redis/)
- [taskiq Documentation](https://taskiq-python.github.io/)
