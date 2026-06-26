# Implementation Plan

- [x] 1. Stable enum 型定義
- [x] 1.1 StableStatus, StableMode, StablePresenceFilter IntEnum を定義する
  - `domain/compatibility/stable/status.py` に StableStatus IntEnum (Idle=0 .. Submitting=13) を定義
  - `domain/compatibility/stable/mode.py` に StableMode IntEnum (Osu=0, Taiko=1, Fruits=2, Mania=3) を定義
  - `domain/compatibility/stable/presence_filter.py` に StablePresenceFilter IntEnum (NoPlayers=0, All=1, Friends=2) を定義
  - `domain/compatibility/stable/__init__.py` から re-export する
  - Done: 3つの enum ファイルが存在し, import 可能
  - _Requirements: 1.1, 1.2, 1.3_
  - _Boundary: domain/compatibility/stable_

- [x] 1.2 Stable enum 値テストを作成する
  - `tests/unit/domain/compatibility/stable/test_stable_enums.py` を新規作成
  - StableStatus の全14値, StableMode の全4値, StablePresenceFilter の全3値の name/value を検証
  - Done: pytest が enum テストを全 PASS
  - _Requirements: 1.4_
  - _Boundary: tests_

- [x] 2. StatusUpdate cpstruct 分離
- [x] 2.1 StatusUpdate を独立 cpstruct として定義する
  - `transports/stable/bancho/protocol/types.py` に StatusUpdate cpstruct を追加 (status uint8, status_text BanchoString, beatmap_md5 BanchoString, mods int32, play_mode uint8, beatmap_id int32)
  - Done: StatusUpdate が types.py から import 可能
  - _Requirements: 2.1_
  - _Boundary: transports/stable/bancho/protocol/types.py_

- [x] 2.2 S2C USER_STATS builder を StatusUpdate ネストに変更する
  - `s2c/login.py` の _UserStatsData から inline StatusUpdate フィールドを削除し, `status_update: StatusUpdate` ネストフィールドに置換
  - `user_stats()` 関数のシグネチャは変更しない (内部で StatusUpdate を構築)
  - Done: user_stats() の出力バイト列が変更前と同一
  - _Requirements: 2.2_
  - _Depends: 2.1_
  - _Boundary: transports/stable/bancho/protocol/s2c/login.py_

- [x] 2.3 C2S STATUS_CHANGE parser を共有 cpstruct に変更する
  - `c2s/status.py` の StatusUpdate 解析を types.py の StatusUpdate cpstruct を使うように変更
  - Done: STATUS_CHANGE parser の出力が変更前と同一
  - _Requirements: 2.3_
  - _Depends: 2.1_
  - _Boundary: transports/stable/bancho/protocol/c2s/status.py_

- [x] 3. Golden bytes fixture テスト
- [x] 3.1 UserPresence golden bytes テストを作成する
  - `tests/unit/transports/bancho/protocol/test_presence_fixtures.py` を新規作成
  - reference builder + guide から手計算した golden bytes で encode/decode を検証
  - boundary case: permissions=16, mode=3 で permissions_mode=112 を検証
  - BanchoBot の UserPresence fixture (user_id=1, username="BanchoBot", rank=0)
  - Done: test_presence_fixtures.py が全 PASS
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 5.1, 5.2_
  - _Depends: 2.2_
  - _Boundary: tests_

- [x] 3.2 UserStats golden bytes テストを作成する
  - `tests/unit/transports/bancho/protocol/test_stats_fixtures.py` を新規作成
  - reference builder + guide から手計算した golden bytes で encode/decode を検証
  - accuracy=0.985 の f32 パック検証 (0-1 ratio, 変換なし)
  - pp=70000 で 65535 clamp 検証
  - BanchoBot の UserStats fixture (全 stats=0)
  - C2S STATUS_CHANGE parser の golden bytes 検証
  - Done: test_stats_fixtures.py が全 PASS
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 6.1, 6.2_
  - _Depends: 2.2, 2.3_
  - _Boundary: tests_

- [x] 4. テストリファクタリングと matrix 更新
- [x] 4.1 既存テストを新規ファイルに移動する
  - test_s2c_login.py から TestUserPresence, TestUserStats, TestUserPresenceBundle を削除
  - 移動先の test_presence_fixtures.py, test_stats_fixtures.py に統合
  - test_s2c_login.py にはスカラーパケットテストのみ残す
  - Done: 全テスト PASS, テスト数の減少なし
  - _Requirements: 7.1, 7.2, 7.3, 7.4_
  - _Depends: 3.1, 3.2_
  - _Boundary: tests_

- [x] 4.2 Matrix struct rows を更新する
  - Status, Mode, PresenceFilter rows を Missing -> Implemented に更新
  - UserPresence, UserPresenceBundle, UserStats rows を Partial -> fixture-backed に更新
  - 各 row に fixture evidence (テストファイルパス) を記載
  - Done: matrix の該当 rows が更新済み
  - _Requirements: 8.1, 8.2_
  - _Depends: 3.1, 3.2, 4.1_
  - _Boundary: docs_
