# Requirements Document

## Introduction

Athena の開発者・運用者は、水平スケーリングと production readiness を進める上で、既存 EventBus が local-only fanout、distributed notification、durable work trigger を一つの境界に混在させているため、重要処理が in-process notification に依存しているか判断しにくい。現在は chat persistence enqueue、disconnect broadcast、channel cleanup が EventBus listener 経由で結合しており、複数 app replica、worker runtime、将来の SignalR / lazer broadcast の保証が曖昧になっている。

この feature は、event-like workflow を Local Event、Distributed Event、Durable Work に分類し、production-critical workflow が Local Event を source of truth にしない状態へ寄せる。Chat Persistence Work は Durable Work として扱い、Disconnect Notification は non-durable な Distributed Event として扱う。

## Boundary Context

- **In scope**: Local Event / Distributed Event / Durable Work の分類、既存 in-process event 境界の local-only 化、Distributed Event の基礎契約、Chat Persistence Work の Durable Work 境界への分離、既存 stable client / worker behavior の維持。
- **Out of scope**: Chat Persistence Work の persistent work-item 実装、presence / channel membership の TTL・heartbeat 実装、Distributed Event の常駐 subscriber runtime、SignalR / lazer broadcast の本体実装、production topology の決定。
- **Adjacent expectations**: `presence-status` は Disconnect Notification を source of truth にせず TTL・heartbeat で stale state から回復する。`chat-persistence-durability` は Chat Persistence Work の retry、重複収束、未処理 work の source of truth を扱う。

## Requirements

### Requirement 1: Event 境界分類

**Objective:** As an Athena developer, I want event-like workflow が Local Event、Distributed Event、Durable Work に分類されること, so that 水平スケーリング時に重要処理の保証を誤解しない。

#### Acceptance Criteria

1. When event-like workflow が production-critical state を変更する, the Athena codebase shall その workflow を Durable Work として扱う。
2. When event-like workflow が runtime 間の一時的な通知だけを表す, the Athena codebase shall その workflow を Distributed Event として扱う。
3. When event-like workflow が同一 process 内の非重要な fanout に閉じる, the Athena codebase shall その workflow を Local Event として扱う。
4. If workflow の分類が不明確な場合, then the Athena documentation shall Local Event、Distributed Event、Durable Work のどれに属するかを明示する。
5. The Athena codebase shall production-critical workflow の source of truth を Local Event に置かない。

### Requirement 2: Local Event の制約

**Objective:** As an Athena developer, I want local-only event delivery が名前と契約で明示されること, so that in-process fanout を distributed guarantee と誤認しない。

#### Acceptance Criteria

1. When developer が local-only event delivery を参照する, the Athena codebase shall それが同一 process 内でのみ有効な通知であることを名前または契約で示す。
2. If Local Event handler が失敗する場合, then the Athena server shall 既存の fire-and-forget 期待を維持し、他の non-critical local handler の実行を妨げない。
3. While Local Event が残っている, the Athena codebase shall Local Event を worker や別 app replica へ届く通知として扱わない。
4. The Athena codebase shall Local Event を chat history persistence の起動境界として使わない。

### Requirement 3: Chat Persistence Work

**Objective:** As an Athena operator, I want accepted chat message の履歴保存が Durable Work として扱われること, so that realtime delivery と履歴保存の保証を分けて運用できる。

#### Acceptance Criteria

1. When channel message が受け付けられる, the Athena server shall Chat Persistence Work を発生させる。
2. When private message が受け付けられる, the Athena server shall Chat Persistence Work を発生させる。
3. If channel message が拒否される、または delivery target が解決できない場合, then the Athena server shall Chat Persistence Work を発生させない。
4. If private message が拒否される、または target user が存在しない場合, then the Athena server shall Chat Persistence Work を発生させない。
5. While Chat Persistence Work の persistent work-item 実装が後続 spec に残っている, the Athena server shall 既存の chat delivery response と worker task outcome を維持する。

### Requirement 4: Distributed Event 基礎契約

**Objective:** As an Athena developer, I want Distributed Event の基礎契約が定義されること, so that 将来の presence、SignalR、lazer broadcast が同じ通知言語に乗れる。

#### Acceptance Criteria

1. When Distributed Event が表現される, the Athena codebase shall event identity、event type、発生時刻、schema version、primitive payload を含む契約を持つ。
2. When Distributed Event payload が runtime 境界を越える, the Athena codebase shall internal domain value から通知 payload への明示的な変換契約を持つ。
3. If Distributed Event が subscriber に届かない場合, then the Athena server shall その event 自体を durable source of truth として扱わない。
4. Where Distributed Event support is included, the Athena codebase shall publisher と subscriber の契約を検証できる。
5. The Athena codebase shall Distributed Event を Chat Persistence Work の source of truth として使わない。

### Requirement 5: Disconnect Notification と presence 回復

**Objective:** As an Athena operator, I want disconnect notification が一時通知として扱われること, so that process crash や network 異常時に presence / membership の正本が通知配送へ依存しない。

#### Acceptance Criteria

1. When user disconnects from stable bancho session, the Athena server shall 既存の stable client-visible disconnect behavior を維持する。
2. When disconnect is observed, the Athena codebase shall Disconnect Notification を Distributed Event として分類する。
3. If Disconnect Notification が missed された場合, then the Athena server shall その missed notification を presence / channel membership の恒久的な source of truth 欠損として扱わない。
4. While TTL・heartbeat recovery が presence-status に残っている, the Athena documentation shall Disconnect Notification が best-effort notification であることを示す。
5. The Athena codebase shall channel membership の最終回復保証を Disconnect Notification の必達性に依存させない。

### Requirement 6: 互換性と検証

**Objective:** As an Athena maintainer, I want event 境界の refactor が既存 client と worker の外部挙動を変えないこと, so that production readiness を改善しながら回帰を防げる。

#### Acceptance Criteria

1. When stable bancho chat workflow runs, the Athena server shall existing packet delivery behavior を維持する。
2. When stable bancho lifecycle workflow runs, the Athena server shall existing PONG / EXIT behavior を維持する。
3. When chat persistence worker tasks run, the Athena worker shall existing task names and payload outcomes を維持する。
4. If event boundary regression が導入された場合, then the Athena quality checks shall それを検出できる。
5. The Athena codebase shall EventBus、Local Event、Distributed Event、Durable Work の境界を検証する automated tests を持つ。
