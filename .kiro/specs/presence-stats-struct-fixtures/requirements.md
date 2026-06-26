# 要件定義

## はじめに

Presence/Stats Struct Fixtures は, GitHub Issue #51 に基づき, stable client に送る UserPresence, UserStats, UserPresenceBundle パケットの wire format を golden bytes で検証し, Stable 固有の enum 型を canonical IntEnum として定義する spec である。

ADR-0012 の wire format 決定に従い, StatusUpdate の cpstruct 分離, enum のファイル分割配置, encode + decode 両方の fixture 検証を行う。

## 境界コンテキスト

- **対象範囲**: Stable enum 型定義 (StableStatus, StableMode, StablePresenceFilter), StatusUpdate cpstruct 分離, golden bytes fixture テスト (encode + decode), C2S STATUS_CHANGE parser 検証, BanchoBot fixture, テストファイルのリファクタリング (既存テスト移動), matrix struct rows 更新。
- **対象外**: stats テーブル作成, stats 集計ロジック, presence filter runtime behavior, Mods 型定義 (#52 scope), rank 値の実データ投入, getscores text response の accuracy 変換。
- **隣接する期待値**: golden bytes の正解は guide 仕様 + reference builder コードから手計算で導出する。accuracy は 0-1 ratio で送信し変換不要 (ADR-0012)。

## 要件

### 要件 1: Stable enum 型定義

**目的:** 実装エージェントが Status, Mode, PresenceFilter の stable wire 値を canonical IntEnum として参照でき, raw int の誤用を防げるようにする。

#### 受け入れ基準

1. The Athena codebase shall define `StableStatus` IntEnum in `domain/compatibility/stable/status.py` with values 0..13 matching guide 仕様
2. The Athena codebase shall define `StableMode` IntEnum in `domain/compatibility/stable/mode.py` with values 0..3 (Osu, Taiko, Fruits, Mania)
3. The Athena codebase shall define `StablePresenceFilter` IntEnum in `domain/compatibility/stable/presence_filter.py` with values 0..2 (NoPlayers, All, Friends)
4. The test suite shall verify all enum member names and values for each Stable enum type

### 要件 2: StatusUpdate cpstruct 分離

**目的:** C2S STATUS_CHANGE parser と S2C USER_STATS builder が同一の StatusUpdate wire type を共有でき, layout の重複定義を防げるようにする。

#### 受け入れ基準

1. The protocol layer shall define `StatusUpdate` as an independent cpstruct with status, status_text, beatmap_md5, mods, play_mode, beatmap_id fields
2. The S2C `USER_STATS` builder shall use the `StatusUpdate` cpstruct as a nested field instead of inline field definitions
3. The C2S `STATUS_CHANGE` parser shall use the same `StatusUpdate` cpstruct for parsing
4. When StatusUpdate を encode/decode するとき, the test suite shall verify round-trip consistency with golden bytes

### 要件 3: UserPresence golden fixture

**目的:** UserPresence builder の wire output が stable client の期待する byte layout と一致することを golden bytes で検証する。

#### 受け入れ基準

1. The test suite shall verify UserPresence encode output against golden bytes including user_id, username, timezone, country_id, permissions_mode, longitude, latitude, rank
2. The test suite shall verify UserPresence decode from golden bytes back to structured data
3. When permissions=16 and mode=3 (boundary case) のとき, the test suite shall verify permissions_mode byte is `16 | (3 << 5)` = 112
4. The test suite shall verify UserPresence golden bytes for BanchoBot (bot=true, stats=0, rank=0)

### 要件 4: UserStats golden fixture

**目的:** UserStats builder の wire output が stable client の期待する byte layout と一致することを golden bytes で検証する。

#### 受け入れ基準

1. The test suite shall verify UserStats encode output against golden bytes including StatusUpdate fields + ranked_score, accuracy, play_count, total_score, rank, pp
2. The test suite shall verify UserStats decode from golden bytes back to structured data
3. When accuracy を encode するとき, the builder shall pack 0-1 ratio as f32 without conversion
4. When pp > 65535 のとき, the builder shall clamp pp to 65535 before packing as uint16
5. The test suite shall verify UserStats golden bytes for BanchoBot (all stats fields = 0)

### 要件 5: UserPresenceBundle golden fixture

**目的:** UserPresenceBundle builder の wire output が stable client の期待する IntList layout と一致することを golden bytes で検証する。

#### 受け入れ基準

1. The test suite shall verify UserPresenceBundle encode output against golden bytes
2. The test suite shall verify UserPresenceBundle decode from golden bytes back to user id list

### 要件 6: C2S STATUS_CHANGE parser 検証

**目的:** C2S STATUS_CHANGE parser が StatusUpdate payload を正しく decode できることを golden bytes で検証する。

#### 受け入れ基準

1. The test suite shall verify STATUS_CHANGE parser correctly decodes StatusUpdate from golden bytes
2. The test suite shall verify parser handles empty status_text and beatmap_md5 strings

### 要件 7: テストファイルリファクタリング

**目的:** テストコードが責務別に整理され, presence/stats fixture テストが独立ファイルに分離されるようにする。

#### 受け入れ基準

1. The test suite shall organize presence/stats tests into test_stable_enums.py, test_presence_fixtures.py, test_stats_fixtures.py
2. When テストを移動するとき, existing TestUserPresence, TestUserStats, TestUserPresenceBundle classes shall be moved from test_s2c_login.py to the new files
3. The test_s2c_login.py shall retain only scalar packet tests (LoginReply, ProtocolVersion, LoginPermissions, Notification, FriendsList, Channel, SilenceInfo)
4. The full test suite shall pass after reorganization with no test count reduction

### 要件 8: Matrix 更新

**目的:** Bancho Struct Coverage の struct rows が fixture evidence で更新され, 実装追跡が正確であるようにする。

#### 受け入れ基準

1. When fixture テストが完了したとき, the matrix shall update Status, Mode, PresenceFilter rows from Missing to Implemented with fixture evidence
2. When fixture テストが完了したとき, the matrix shall update UserPresence, UserPresenceBundle, UserStats rows from Partial to fixture-backed with golden bytes evidence
