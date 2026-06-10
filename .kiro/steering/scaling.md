# Horizontal Scaling Memo

## 結論

athena の設計方針は水平スケールしやすい方向に寄っている。モジュラモノリスのままでも、app process と worker process を個別に複数台へ増やす前提はかなり作りやすい。

ただし現状は「複数 app replica を立てる下地はあるが、production-grade に雑に台数を増やせる完成度ではまだない」という評価に留める。感覚値としては、設計思想は 8/10、現実の実装成熟度は 5.5-6.5/10 程度。

## スケールしやすい点

- セッションは `ValkeySessionStore` に外出しされているため、app instance 固有の sticky session には基本依存しない。
- S2C packet queue は `ValkeyPacketQueue` に外出しされているため、ある app instance が enqueue し、別 app instance が polling response で dequeue する構成が成立しやすい。
- channel membership は `ValkeyChannelStateStore` に外出しされている。
- rate limit は `ValkeyRateLimiter` 実装がある。
- 重い処理は `taskiq + Valkey` の worker queue へ逃がす構成になっている。
- DB access は repository 越しで、app / worker を分けて増やす構成と相性がよい。
- stable bancho は HTTP polling 型なので、常時接続中心の WebSocket / SignalR より app process の水平分散がしやすい。

## 現時点の制約

- `EventBus` は `InMemoryEventBus`。同一 process 内の同期的な domain event fanout には使えるが、worker や別 app instance をまたぐ distributed event bus ではない。
- `ValkeyChannelStateStore` の membership には TTL がない。正常 logout / quit では消せるが、process crash、network disconnect、client 異常終了で stale member が残る可能性がある。
- blob storage の default が local の場合、複数 app / worker から同じ content を共有できない。水平スケールする production では S3-compatible storage などが必要。
- logging は local file 前提が残っている。複数 replica 運用では stdout 集約、ログ基盤、または専用 writer pipeline が必要。
- Valkey が session、packet queue、channel state、rate limit、task queue の中心になるため、単一障害点になりやすい。production topology と HA 方針が必要。
- worker job は複数 worker で処理できる構成だが、各 job の idempotency と retry 時の重複実行耐性を個別に検証する必要がある。
- app replica を増やすほど DB connection pool、transaction 境界、unique constraint による競合設計が重要になる。
- lazer / SignalR を本格実装すると、接続状態や broadcast の分散処理が stable bancho より難しくなる。

## 優先して固めること

1. `EventBus` の用途を分ける。
   Local-only domain event と、process をまたいで publish すべき distributed event を明確に分離する。

2. presence / channel membership に TTL or heartbeat を入れる。
   stale online user や stale channel member を自動回復できるようにする。

3. blob storage を production では S3-compatible backend に寄せる。
   score replay、beatmap file、将来の user-uploaded asset を複数 app / worker から読めるようにする。

4. worker job を idempotent にする。
   score processing、beatmap fetch、rank rebuild は重複実行されても壊れない形にする。

5. DB / Valkey の production topology を決める。
   DB connection pool、Valkey HA、migration 実行者を一つにする運用、queue isolation を明示する。

## 判断基準

stable bancho の基本機能だけなら、複数 app replica にする設計障害は少ない。ただし次を満たすまでは production-grade な水平スケールとは見なさない。

- process crash 後も presence / channel membership が自然に回復する。
- worker を複数台にしても score、rank、beatmap fetch が二重反映で壊れない。
- blob content が全 app / worker から読める。
- Valkey / DB の障害時挙動と復旧手順が定義されている。
- SignalR / lazer broadcast の分散方式が明確になっている。
