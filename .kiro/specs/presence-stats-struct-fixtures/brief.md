# Brief: presence-stats-struct-fixtures

## Problem

Issue #51 (Presence/Stats struct golden fixtures) として、UserPresence, UserStats, StatusUpdate, UserPresenceBundle の wire format を golden bytes で検証し、Stable 固有の enum 型 (StableStatus, StableMode, StablePresenceFilter) を canonical IntEnum として定義する必要がある。

これらの fixture がないと user-stats 実装 (#18) や presence fanout の正確性が検証できない。

## Current State

- `_UserPresenceData`, `_UserStatsData` cpstruct と builder 関数は `s2c/login.py` に実装済み
- テストは packet_id, user_id, permissions_mode packing の基本検証のみ。golden bytes なし
- Status/Mode/PresenceFilter は raw int として使用されており、canonical enum 型がない
- StatusUpdate フィールドは _UserStatsData に inline 埋め込み (DRY 違反)

## Desired Outcome

- Stable enum 型が domain/compatibility/stable/ に定義され、全値のテストがある
- StatusUpdate が独立 cpstruct として分離され、C2S parser と S2C builder で共有
- UserPresence/UserStats/UserPresenceBundle の golden encode/decode bytes テストがある
- BanchoBot の presence/stats fixture がある
- 既存テストが責務別に分割されている

## Approach

ADR-0012 の決定事項に従い、以下の順序で実装:
1. Stable enum 型定義 + 値テスト
2. StatusUpdate cpstruct 分離
3. Golden bytes fixture テスト (encode + decode)
4. 既存テストのリファクタリング (移動)
5. Matrix 更新

## Grill 決定事項

ADR-0012 に全決定事項を記録済み。主要決定:
- accuracy: 0-1 ratio (f32), 変換不要
- permissions_mode: max 16, ビット衝突なし
- pp: uint16 + clamp (65535)
- StatusUpdate: 独立 cpstruct に分離
- enum: Stable プレフィックス, ファイル分割
- fixture: テスト内インライン, 3ファイル分割
- USER_QUIT: モダン形式のみ
- BanchoBot: presence/stats 送信 (stats=0)

## Scope

- **In**: enum 定義, StatusUpdate 分離, golden bytes fixture, テスト分割, matrix 更新, ADR コミット, CONTEXT.md 更新
- **Out**: stats テーブル作成, stats 集計ロジック, presence filter runtime behavior, Mods 型定義 (#52), rank 値の実データ投入

## Upstream / Downstream

- **Upstream**: guide の struct 仕様, reference implementation (bancho.py, titanic) の builder コード
- **Downstream**: user-stats spec (stats テーブル + 集計), presence spec (filter runtime), #18 (Presence/UserStats)

## Constraints

- golden bytes の正解は guide 仕様 + reference builder コードから手計算で導出
- accuracy は 0-1 ratio。getscores text での *100 変換は別 scope
- caterpillar のネスト機能を使用 (StatusUpdate 分離)
