# Research & Design Decisions

## Summary
- **Feature**: packet-polling
- **Discovery Scope**: Extension
- **Key Findings**:
  - EventBus は tech.md に記載あるが未実装。本スペックで基盤を構築する必要あり
  - `read_packets()` は既存（Caterpillar ベース）。C2S パケット解析は再利用可能
  - SessionStore の Protocol + memory/redis パターンが PacketQueue の設計テンプレートとなる

## Research Log

### EventBus の実装状況
- **Context**: Req 7（イベント駆動配信）の実現に EventBus が必要
- **Findings**:
  - `infrastructure/` 配下に EventBus クラスは存在しない
  - `domain/events/` ディレクトリも存在しない
  - tech.md には「自前実装 (Redis Pub/Sub + in-memory) ~40行の軽量実装」と記載
  - 実体はまだ作られていない
- **Implications**: 本スペックで EventBus の基盤（インターフェース + in-memory 実装）を構築する。Redis Pub/Sub 版はマルチプロセス対応時に追加

### C2S パケット解析の既存実装
- **Context**: Req 2（C2S パケット受信とディスパッチ）に既存コードを再利用できるか
- **Sources**: `src/osu_server/transports/bancho/protocol/reader.py`
- **Findings**:
  - `read_packets(data: bytes) -> list[tuple[ClientPacketID, bytes]]` が存在
  - Caterpillar の `unpack()` で RawPacket 構造体（7バイトヘッダ + ペイロード）を解析
  - 不正データ時は `PacketReadError` を送出
  - 未知のパケットIDはスキップ
- **Implications**: 新規実装不要。ポーリングハンドラから直接呼び出し可能

### bancho.py のポーリング実装パターン
- **Context**: リファレンス実装との一貫性確認
- **Sources**: https://github.com/osuAkatsuki/bancho.py/blob/master/app/api/domains/cho.py
- **Findings**:
  - C2S 処理 → S2C drain → レスポンス の順序（パターン A）
  - タイムアウト: 300秒（`OSU_CLIENT_MIN_PING_INTERVAL`）、チェック間隔: 100秒
  - インメモリでセッション管理（Redis 不使用）
  - `player.dequeue()` でパケットキューを drain
- **Implications**: 処理順序とタイムアウト値を踏襲。ストレージは Redis を採用（プロセス再起動耐性）

### SessionStore のアーキテクチャパターン
- **Context**: PacketQueue の設計テンプレート
- **Sources**: `infrastructure/state/` ディレクトリ
- **Findings**:
  - Protocol（インターフェース）+ InMemory（テスト用）+ Redis（本番用）の3層構成
  - Redis 実装は Lua スクリプトで原子性を保証
  - DI コンテナで環境変数ベースの切り替え（test → InMemory, else → Redis）
- **Implications**: PacketQueue も同一パターンで実装。Lua スクリプトで LRANGE+DEL を原子化

## Design Decisions

### Decision: Redis データ構造
- **Context**: S2C パケットキューのストレージ選択
- **Alternatives**:
  1. List (RPUSH/LRANGE+DEL) — シンプル、1 RTT で drain
  2. List (LPOP ループ) — 部分消費可能だが N RTT
  3. Stream (XADD/XREAD) — Consumer Group で再配信可能だが過剰
- **Selected**: List + Lua（LRANGE+DEL 原子操作）
- **Rationale**: S2C パケットはエフェメラル（通知目的のみ）。本体データ（チャット、スコア）は DB に永続化されるため、キューに永続性は不要。1 RTT + 原子性が最適バランス
- **Trade-offs**: レスポンス未達時にパケット消失するが、エフェメラルデータなので許容

### Decision: C2S ハンドラの DI パターン
- **Context**: C2S パケットハンドラへの依存注入方式
- **Alternatives**:
  1. Context オブジェクト — 全ハンドラに同一コンテキストを渡す
  2. *args, **kwargs — 現状のまま
  3. クラス化 + コンストラクタ DI — ハンドラをクラスにして依存を明示
  4. コンテナ直接解決 — Service Locator パターン
- **Selected**: クラス化 + コンストラクタ DI
- **Rationale**: 依存の透明性が最高。LoginHandler と同一パターン。テスト時に必要な依存だけモック可能
- **Trade-offs**: ボイラープレート増加（各ハンドラがクラスになる）だが、構造は統一的

### Decision: S2C パケット配信の仕組み
- **Context**: サービス層からプロトコル層への通知配信方式
- **Alternatives**:
  1. EventBus（fire-and-forget イベント駆動）
  2. UserNotifier Protocol（依存性逆転）
  3. サービス層が直接 enqueue（レイヤー違反）
- **Selected**: EventBus
- **Rationale**: 開放閉鎖原則。新しい通知タイプ追加時に既存コード変更なし。マルチプロトコル対応（bancho/SignalR/Web）に自然に拡張。UserNotifier は15-20メソッドの肥大インターフェースになる
- **Trade-offs**: イベントフローが暗黙的になるが、ディレクトリ規約 + docstring + structured logging で追跡可能性を確保

### Decision: セッション TTL
- **Context**: タイムアウト値の選定
- **Sources**: bancho.py (300秒), pep.py (100秒)
- **Selected**: 300秒（bancho.py と同等）
- **Rationale**: クライアントは ~30秒間隔でポーリング。300秒 = ポーリング10回分の猶予。100秒は短すぎる（ネットワーク不調で切断されやすい）

### Decision: パケットキューのキー設計
- **Context**: `packet_queue:{user_id}` vs `packet_queue:{token}`
- **Selected**: `packet_queue:{user_id}`
- **Rationale**: エンキュー時に知っているのは user_id（トークンは不明）。token ベースだと毎回 user_id→token の逆引きが必要（余計な RTT）。再ログイン時の孤立キーも発生しない
- **Trade-offs**: tourney マルチセッション時にキー変更が必要だが、`{user_id}:{session_index}` への拡張で対応可能

## Risks & Mitigations
- **EventBus 未実装**: 本スペックで基盤を構築。初期は in-memory 実装のみ（単一プロセス）。Redis Pub/Sub はワーカー連携時に追加
- **read_packets の例外ハンドリング**: `PacketReadError` が送出される可能性あり。ポーリングハンドラで catch して残パケットをスキップする設計（Req 3.1）
- **セッション TTL 変更の影響**: 3600秒→300秒。既存の SessionStore のデフォルト TTL を変更する必要あり。影響範囲は config.py + SessionStore 初期化

## References
- [bancho.py bg_loops.py](https://github.com/osuAkatsuki/bancho.py/blob/master/app/bg_loops.py) — タイムアウト値 300秒
- [bancho.py cho.py](https://github.com/osuAkatsuki/bancho.py/blob/master/app/api/domains/cho.py) — ポーリングハンドラ実装
- [Ripple Wiki](https://github.com/osuripple/ripple/wiki/Bancho-server-config-file) — タイムアウト設定 100秒
