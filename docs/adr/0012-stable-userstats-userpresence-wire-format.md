# ADR-0012: Stable UserStats/UserPresence wire format decisions

## Status

Accepted

## Context

Issue #51 (Presence/Stats struct golden fixtures) の grill session で、
stable client に送る UserStats と UserPresence パケットの wire format に
関する設計判断が必要になった。

既存の builder (`_UserStatsData`, `_UserPresenceData` in `s2c/login.py`) は
動作しているが、以下の点が未文書化だった:

1. accuracy フィールドの値域 (0-1 ratio vs 0-100 percent)
2. permissions_mode のビットパッキングの安全性
3. pp の uint16 上限超過時の挙動
4. StatusUpdate の cpstruct 分離可否
5. Stable 固有 enum の配置場所と命名
6. golden bytes fixture の検証パターン

## Decision

### accuracy は 0-1 ratio (f32) で送る

Reference 実装の裏付け:
- bancho.py: 内部 0-100 を `gm_stats.acc / 100.0` で f32 にパック
- titanic (chio.py): 内部 0-1 を `write_f32(stream, info.stats.accuracy)` でそのまま送信

Athena の `scores.accuracy` は 0-1 (ratio) で保存しているため、変換不要。

getscores text response では `accuracy * 100` への変換が必要になる。
これは getscores formatter の責務であり、wire format の問題ではない。

### permissions_mode は安全にパック済み

`to_user_presence_permissions()` が返す値は最大 16 (DEVELOPER)。
5ビットに収まるため `permissions | (mode << 5)` でビット衝突は発生しない。

### pp は uint16 + clamp

guide の仕様は `uShort pp`。bancho.py は int16 として pack しているが、
guide に従い uint16 (0-65535) を採用し、超過時は 65535 に clamp する。

### StatusUpdate を独立 cpstruct に分離する

caterpillar はネスト対応済み (`chunk_header: CAFChunkHeader` パターン)。
StatusUpdate を独立 cpstruct にすることで:
- C2S `STATUS_CHANGE` parser と S2C `USER_STATS` builder で共有可能 (DRY)
- guide の struct 定義と 1:1 対応
- StatusUpdate 単体の encode/decode テストが可能

### Stable 固有 enum は domain/compatibility/stable/ にファイル分割

- `domain/compatibility/stable/status.py` (`StableStatus`)
- `domain/compatibility/stable/mode.py` (`StableMode`)
- `domain/compatibility/stable/presence_filter.py` (`StablePresenceFilter`)

命名は `Stable` プレフィックス。既存の `BanchoClientPermission` は
`Bancho` プレフィックスだが、新規 enum は `Stable` で統一する。

### Golden bytes はテスト内インライン

テストファイルを責務別に3分割:
- `test_stable_enums.py`
- `test_presence_fixtures.py`
- `test_stats_fixtures.py`

既存 `test_s2c_login.py` の UserPresence/UserStats テストは新規ファイルに移動。

### USER_QUIT はモダン形式のみ

user_id (sInt) + QuitState (byte) の形式を採用。
古い 4-byte user_id 形式は将来の backward compat で検討。

## Consequences

- accuracy 変換が不要なため、stats -> wire のパスが単純になる
- getscores formatter で 0-1 -> 0-100 変換が必要 (別 Issue scope)
- StatusUpdate 分離により cpstruct 定義が1つ増えるが、DRY と testability が向上
- pp clamp により 65535pp 超のユーザーは表示上 65535 に丸められる
  (stable client の制限であり、API では制限なし)
