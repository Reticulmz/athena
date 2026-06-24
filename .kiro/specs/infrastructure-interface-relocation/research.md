# Gap Analysis: infrastructure-interface-relocation

## 1. Current State Investigation

### Protocol/Interface インベントリ

現在 infrastructure/ 内に分散している Protocol/interface は以下の通り:

| ファイル | シンボル | 種別 | 消費元 |
|---|---|---|---|
| `infrastructure/state/interfaces/channel_state_store.py` | `ChannelStateStore` | Protocol | chat commands (join/leave), chat queries, bancho listeners |
| `infrastructure/state/interfaces/packet_queue.py` | `PacketQueue` | Protocol | bancho handlers (chat/presence), bancho listeners, bancho polling |
| `infrastructure/state/interfaces/rate_limiter.py` | `RateLimiter` | Protocol | chat commands (channel/PM) |
| `infrastructure/state/interfaces/performance_completion_signal.py` | `PerformanceCompletionSignal` | Protocol | scores commands, scores queries |
| `infrastructure/storage/interfaces.py` | `StagedBlobWrite`, `BlobStorageBackend` | Protocol | storage commands |
| `infrastructure/storage/errors.py` | `BlobContentMissingError` 等 | Exception (具象) | storage commands |
| `infrastructure/performance/interfaces.py` | `PerformanceCalculator` + I/O types | Protocol + dataclass | scores commands |
| `infrastructure/http/beatmap_http_client.py` | `BeatmapHttpClient`, `HttpFetchResult` | 具象クラス (httpx 依存) | beatmaps queries |
| `infrastructure/security/hibp.py` | `HIBPClient` | Protocol | identity queries |
| `infrastructure/messaging/local.py` | `LocalEventBus` | Protocol | bancho handlers/listeners/login |
| `infrastructure/country/interfaces.py` | `CountryResolver` | Protocol | bancho login |
| `infrastructure/country/codes.py` | `country_code_to_id` | 具象関数 | bancho mappers/presence_roster |
| `infrastructure/parsers/multipart_parser.py` | `MultipartLimits`, `ParsedSubmission`, `ParseError` | 具象 dataclass/exception | web_legacy transports |
| `infrastructure/jobs/registry.py` | `jobs` | 具象 | jobs (全ファイル) |

#### ドメイン横断 Protocol (infrastructure 外)

| ファイル | シンボル | 種別 | 消費元 |
|---|---|---|---|
| `services/commands/leaderboard_rebuild_wake.py` | `BeatmapLeaderboardRebuildWorkerWake`, `NoopBeatmapLeaderboardRebuildWorkerWake` | Protocol + 具象 Noop | identity commands, beatmaps commands, scores commands, composition providers |

### 依存パターンの分類

Services → Infrastructure (16件):

| 分類 | 件数 | 例 |
|---|---|---|
| Protocol/interface への依存 | 12件 | ChannelStateStore, RateLimiter, PerformanceCalculator, HIBPClient 等 |
| 具象 Exception への依存 | 1件 | BlobContentMissingError |
| 具象クラスへの依存 | 2件 | BeatmapHttpClient (httpx 依存), is_permanent_error |
| 具象 I/O dataclass への依存 | 1件 | PerformanceCalculatorInput 等 (Protocol と同一モジュール) |

Transports → Infrastructure (17件 / ユニーク import 行):

| 分類 | 件数 | 例 |
|---|---|---|
| Protocol/interface への依存 | 10件 | PacketQueue, ChannelStateStore, LocalEventBus, CountryResolver |
| 具象関数/定数への依存 | 2件 | country_code_to_id |
| 具象クラスへの依存 | 5件 | MultipartLimits, ParsedSubmission, ParseError, MultipartParser |

### import-linter 契約の現状

Layered architecture 契約の層順序:
```
transports > jobs > services > repositories > infrastructure > domain > shared
```

**重要な発見**: `infrastructure` は `services` より下位レイヤーとして定義されているため、services → infrastructure への依存は layers 契約で**構造的に許可されている**。現在の契約は「services が infrastructure の具象実装を触ってはいけない」とは言っていない。`forbidden_modules` で禁止されているのは `infrastructure.database` と `sqlalchemy` のみ。

### 既存パターンの観察

1. **infrastructure/state/interfaces/ は既に分離されている**: Protocol 定義専用ディレクトリが存在する
2. **infrastructure/performance/interfaces.py も分離されている**: Protocol と I/O dataclass が同居
3. **infrastructure/storage/interfaces.py も分離されている**: Protocol のみ
4. **infrastructure/http/, infrastructure/messaging/, infrastructure/parsers/ は Protocol と具象が混在**: BeatmapHttpClient は httpx 直接依存の具象クラスだが services が参照している
5. **shared/ には Protocol が存在しない**: 現在は NewType のみ

## 2. Requirements Feasibility Analysis

### 要件ごとのギャップ分析

| 要件 | 現状 | ギャップ | 難度 |
|---|---|---|---|
| R1: 配置の層帰属明確化 | state/interfaces, performance/interfaces, storage/interfaces は分離済み。http, messaging, parsers, country は混在 | Protocol 未分離の4モジュールの整理が必要 | 低 |
| R2: Services→具象 infra 遮断 | 16件中4件が具象依存 (BeatmapHttpClient 2件, BlobContentMissingError 1件, is_permanent_error 1件) | BeatmapHttpClient の Protocol 化、errors の配置検討 | 中 |
| R3: Transports→具象 infra 整理 | 17件中7件が具象依存 | country_code_to_id, MultipartParser 系は具象ユーティリティ | 中 |
| R4: ドメイン横断 Protocol 配置 | leaderboard_rebuild_wake が services/commands/ トップレベルに存在 | shared/ への移動 | 低 |
| R5: import-linter 契約追加 | 既存 13 契約はすべてパス。具象 infra 遮断の契約は未定義 | 新規 forbidden 契約の追加 | 低 |
| R6: 互換性維持 | - | テスト・静的解析のパス確認 | 自動 |

### 課題と制約

1. **BeatmapHttpClient は純粋な具象クラス (httpx 依存)**: Protocol 化するには、(a) BeatmapHttpClient Protocol を infrastructure/http/interfaces.py に切り出すか、(b) repositories/interfaces/ に BeatmapSource Protocol を置くか、の選択がある
2. **country_code_to_id は純粋関数 (副作用なし)**: Protocol 化は過剰。transport 内にコピーするか、shared/ に移すか、import-linter の許可リストに入れるかの選択
3. **MultipartParser 系は transport 専用のパース処理**: transport 内部に移動するか、infrastructure での配置を import-linter で許可するかの選択
4. **infrastructure/storage/errors.py の Exception クラス**: services/commands/storage が import している。Exception は「契約の一部」とも「具象実装の一部」とも解釈できる
5. **PerformanceCalculator の I/O dataclass**: Protocol と同居しており、Protocol と同じモジュールに置くのが自然

## 3. Implementation Approach Options

### Option A: Protocol を infrastructure/*/interfaces に統一 (最小移動)

既に `infrastructure/state/interfaces/`, `infrastructure/performance/interfaces.py`, `infrastructure/storage/interfaces.py` が存在するパターンを、未分離のモジュール (http, messaging, country, parsers) に展開する。

**変更内容**:
- `infrastructure/http/interfaces.py` を新設し `BeatmapHttpClient` Protocol を定義
- `infrastructure/messaging/interfaces.py` を新設 (LocalEventBus は既に Protocol なので移動のみ)
- `infrastructure/country/` は CountryResolver Protocol は既に interfaces.py にある (変更不要)
- leaderboard_rebuild_wake を `shared/ports/` に移動
- import-linter に `Services は infrastructure.*.interfaces のみ許可` 契約を追加

**Trade-offs**:
- 既存パターンの自然な延長。AI エージェントにとって最も学習コストが低い
- `infrastructure/` 内部の整理のみで完結
- ただし Protocol が `infrastructure/` 内にある以上、「infra は下位レイヤーだから services から触れる」という構造的曖昧さは残る

### Option B: Protocol を shared/ports/ に集約 (明確な境界)

全ての Protocol/interface を `shared/ports/` (新設ディレクトリ) に移動する。infrastructure は具象実装のみを持つ。

**変更内容**:
- `shared/ports/` を新設
- `shared/ports/state.py` (ChannelStateStore, PacketQueue, RateLimiter, PerformanceCompletionSignal)
- `shared/ports/storage.py` (StagedBlobWrite, BlobStorageBackend)
- `shared/ports/performance.py` (PerformanceCalculator + I/O types)
- `shared/ports/http.py` (BeatmapHttpClient Protocol)
- `shared/ports/messaging.py` (LocalEventBus)
- `shared/ports/security.py` (HIBPClient)
- `shared/ports/country.py` (CountryResolver)
- `shared/ports/leaderboard.py` (BeatmapLeaderboardRebuildWorkerWake)
- import-linter に `Services/Transports は infrastructure 具象を直接触らない` 契約を追加

**Trade-offs**:
- 最も明確な境界。ファイルパスだけで「これは Port か具象か」が自明
- layers 契約と整合する (shared は最下層)
- ただし大量の import path 変更が発生する (全消費元)
- infrastructure/state/interfaces/ の既存パターンを破壊する

### Option C: Hybrid (Protocol は各帰属先に分散配置)

Protocol をその**意味的な帰属先**に配置する。infra 横断的なものは `shared/ports/`、ドメイン固有のものは各ドメインの services/interfaces に。

**変更内容**:
- `shared/ports/` に横断的 Protocol (RateLimiter, LocalEventBus, CountryResolver, leaderboard_rebuild_wake)
- `services/commands/scores/ports.py` に PerformanceCalculator, PerformanceCompletionSignal
- `services/commands/storage/ports.py` に StagedBlobWrite, BlobStorageBackend
- `services/commands/chat/ports.py` に ChannelStateStore
- `transports/stable/bancho/ports.py` に PacketQueue
- import-linter 契約を追加

**Trade-offs**:
- 意味的に最も正確。「誰がこの Protocol を必要としているか」がファイルパスで分かる
- ただし配置ルールが複雑で、AI エージェントが新しい Protocol の配置先を判断しにくい
- Protocol が分散しすぎると一覧性が下がる

## 4. Implementation Complexity & Risk

**Effort: M (3-7 days)**
- Protocol 分離と移動は機械的だが、import path の書き換えが 30+ ファイルに及ぶ
- import-linter 契約の追加と検証が必要
- basedpyright / ruff / テストの全パス確認が必要

**Risk: Low**
- 既存パターン (infrastructure/*/interfaces) の延長
- ビジネスロジックの変更なし
- import path の変更のみで、型シグネチャやランタイム動作は不変
- import-linter で機械的に検証可能

## 5. Recommendations for Design Phase

### 推奨アプローチ: Option A (最小移動) をベースに Option B の利点を部分的に取り込む

1. **infrastructure 内で既に分離されている Protocol (state/interfaces, performance/interfaces, storage/interfaces) はそのまま維持する** -- 既存パターンを壊さない
2. **未分離のモジュール (http, messaging) に interfaces.py を新設し Protocol を分離する**
3. **leaderboard_rebuild_wake は `shared/ports/` に移動する** -- 複数ドメインから参照される横断的 Protocol の帰属先として `shared/` が最も自然
4. **具象ユーティリティ (country_code_to_id, MultipartParser) は import-linter の許可リストで管理する** -- Protocol 化は過剰
5. **import-linter に新規 forbidden 契約を追加**: `services は infrastructure.database, infrastructure.*.valkey 等の具象バックエンドを直接触らない` を明示

### Design Phase で検討すべき事項

- **BeatmapHttpClient**: Protocol 化するか、現状の具象クラスのまま許可リストで管理するか
- **infrastructure/storage/errors.py**: Exception を shared/errors.py に移すか、infrastructure に残して許可するか
- **import-linter 契約の粒度**: forbidden_modules で具象実装パッケージを列挙するか、independence 契約で Protocol モジュールと具象モジュールを分離するか
- **shared/ports/ の命名**: `ports` vs `interfaces` vs `contracts` のどれが最も AI エージェントにとって直感的か
