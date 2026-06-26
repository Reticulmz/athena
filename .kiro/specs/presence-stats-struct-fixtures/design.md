# 設計書

## 概要

Presence/Stats Struct Fixtures は, stable client に送る UserPresence, UserStats, UserPresenceBundle パケットの wire format を golden bytes で検証し, Stable 固有 enum 型を canonical IntEnum として定義する。

StatusUpdate を独立 cpstruct に分離して C2S parser と S2C builder で共有し, テストファイルを責務別に3分割する。

### 目標

- Stable enum 型 (StableStatus, StableMode, StablePresenceFilter) を domain/compatibility/stable/ にファイル分割で定義
- StatusUpdate を独立 cpstruct に分離
- UserPresence, UserStats, UserPresenceBundle の golden encode/decode bytes テスト
- 既存テストの責務別リファクタリング

### 対象外

- stats テーブル作成, stats 集計ロジック
- Presence filter runtime behavior
- Mods 型定義 (#52 scope)
- getscores text response の accuracy 変換

## 境界コミットメント

### この spec が扱うこと

- `domain/compatibility/stable/` に StableStatus, StableMode, StablePresenceFilter IntEnum を新規定義
- `transports/stable/bancho/protocol/types.py` に StatusUpdate cpstruct を新規定義
- `s2c/login.py` の _UserStatsData を StatusUpdate ネストに変更
- `c2s/status.py` の StatusUpdate parser を共有 cpstruct に変更
- golden bytes テスト3ファイルを新規作成
- 既存 test_s2c_login.py から presence/stats テストを移動

### 境界外

- `s2c/login.py` の builder 関数シグネチャ変更 (互換性維持)
- 新規 S2C パケットの追加
- stats テーブルや migration

### 参照してよい依存

- `docs/stable-compatibility-guide.md` Bancho Struct Field Reference
- `docs/adr/0012-stable-userstats-userpresence-wire-format.md`
- Reference implementation builder コード (bancho.py, titanic)

### 再検証トリガー

- StatusUpdate の wire layout が変更された場合
- caterpillar のネスト挙動が変更された場合
- Stable enum 値が追加された場合

## アーキテクチャ

### 既存アーキテクチャ分析

- `_UserPresenceData`, `_UserStatsData`: `s2c/login.py` に cpstruct として定義済み
- `user_presence()`, `user_stats()`: builder 関数が既存
- C2S `STATUS_CHANGE` parser: `c2s/status.py` に StatusUpdate 解析が存在
- テスト: `test_s2c_login.py` に TestUserPresence, TestUserStats, TestUserPresenceBundle が存在

### 技術スタック

| 層 | 選択 / version | この feature での役割 |
|-------|------------------|-----------------|
| Protocol | caterpillar (cpstruct, pack/unpack) | StatusUpdate 分離, golden bytes 検証 |
| Domain | IntEnum | Stable enum 型定義 |
| Tests | pytest | golden bytes テスト |

## ファイル構成計画

### 新規作成ファイル

- `src/osu_server/domain/compatibility/stable/status.py`: StableStatus IntEnum
- `src/osu_server/domain/compatibility/stable/mode.py`: StableMode IntEnum
- `src/osu_server/domain/compatibility/stable/presence_filter.py`: StablePresenceFilter IntEnum
- `tests/unit/domain/compatibility/stable/test_stable_enums.py`: enum 値テスト
- `tests/unit/transports/bancho/protocol/test_presence_fixtures.py`: UserPresence golden bytes
- `tests/unit/transports/bancho/protocol/test_stats_fixtures.py`: UserStats golden bytes

### 変更対象ファイル

- `src/osu_server/transports/stable/bancho/protocol/types.py`: StatusUpdate cpstruct 追加
- `src/osu_server/transports/stable/bancho/protocol/s2c/login.py`: _UserStatsData を StatusUpdate ネストに変更
- `src/osu_server/transports/stable/bancho/protocol/c2s/status.py`: StatusUpdate cpstruct を共有
- `tests/unit/transports/bancho/protocol/test_s2c_login.py`: UserPresence/UserStats/UserPresenceBundle テスト削除 (移動)
- `docs/stable-compatibility-matrix.md`: struct rows 更新

### 明示的に変更しないファイル

- `user_presence()`, `user_stats()` の外部シグネチャ (互換性維持)
- `src/osu_server/domain/scores/mods.py` (#52 scope)

## 要件トレーサビリティ

| 要件 | コンポーネント | ファイル |
|------|------------|--------|
| 1.1-1.4 | Stable enum 型 | status.py, mode.py, presence_filter.py, test_stable_enums.py |
| 2.1-2.4 | StatusUpdate 分離 | types.py, login.py, status.py |
| 3.1-3.4 | UserPresence fixture | test_presence_fixtures.py |
| 4.1-4.5 | UserStats fixture | test_stats_fixtures.py |
| 5.1-5.2 | UserPresenceBundle fixture | test_presence_fixtures.py |
| 6.1-6.2 | STATUS_CHANGE parser | test_stats_fixtures.py |
| 7.1-7.4 | テストリファクタリング | test_s2c_login.py (削除), 新規3ファイル |
| 8.1-8.2 | Matrix 更新 | stable-compatibility-matrix.md |

## 検証戦略

- enum テスト: 全値の name/value 一致を検証
- golden bytes テスト: 手計算したバイト列と builder 出力を比較 (encode), バイト列から構造体を復元して値を検証 (decode)
- boundary テスト: permissions=16 mode=3, pp=65536 (clamp), accuracy=0.985 (f32 precision)
- BanchoBot テスト: bot 固有の presence/stats (stats=0)
- リファクタリング検証: 全テスト通過, テスト数の減少なし
