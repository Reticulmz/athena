# 調査と設計判断

## 概要

- **機能**: `bancho-packet-struct-inventory-audit`
- **発見範囲**: 既存ドキュメントの拡張
- **主要な発見**:
  - GitHub Issue #33 がこの作業の authoritative scope source である。対象は C2S packet row、S2C packet row、Bancho struct row、evidence note、#17 fixture extraction blocker に限定される。
  - `docs/stable-compatibility-matrix.md` はすでに canonical stable compatibility inventory と project field vocabulary を所有しているため、別の packet inventory を作らずこの文書を更新するべきである。
  - `docs/stable-compatibility-guide.md` は Bancho payload と struct field reference を整理しているため、監査ではこれを整合性確認の参照元として使い、matrix と guide が食い違う場合は unresolved evidence gap として記録する。

## 調査ログ

### GitHub Issue の scope

- **文脈**: ユーザーは、local assumption ではなく GitHub issue から spec を導出するよう指示した。
- **参照した source**:
  - GitHub Issue #33: `[stable-compat] Bancho packet / struct inventory を監査する`
  - GitHub Issue #16: `[stable-compat] 互換性インベントリ監査を完了する`
  - GitHub Issue #17: `[stable-compat] Stable golden fixtures を抽出する`
- **発見**:
  - #33 は、すべての C2S packet row に current implementation status と evidence note を持たせることを要求している。
  - #33 は、すべての S2C packet row に builder/runtime status または documented non-emission reason を示すことを要求している。
  - #33 は、すべての Bancho struct row に confirmed source、missing field/value audit note、または explicit deferral reason を示すことを要求している。
  - #33 は、#17 fixture extraction をブロックする packet/struct row に exact reference source name を列挙することを要求している。
  - #16 は #33 を broader inventory audit の子 task として位置づけ、#17 は matrix 更新後の confirmed reference を消費する。
- **含意**:
  - 設計は `/web`、static/media、release/update、persistence、fixture extraction へ広げてはならない。
  - #17 への引き渡しは、実装された fixture ではなく matrix 上で読める list または row-level marker にする。

### 既存 matrix 構造

- **文脈**: 要件 1、2、3、4、5、8 は既存 inventory row の更新を要求している。
- **参照した source**:
  - `docs/stable-compatibility-matrix.md` Source-Of-Truth Policy
  - `docs/stable-compatibility-matrix.md` C2S Packet Coverage
  - `docs/stable-compatibility-matrix.md` S2C Packet Coverage
  - `docs/stable-compatibility-matrix.md` Bancho Struct Coverage
  - `docs/stable-compatibility-matrix.md` GitHub Project Shape
- **発見**:
  - matrix は stable compatibility work の source-of-truth checklist としてすでに定義されている。
  - 既存 status label は implementation maturity を表し、#33 が要求する audit classification とは別概念である。
  - GitHub Project Shape は `Reference status`、`Reference implementation`、`Implementation status`、`Verification`、`Priority` に使える値をすでに定義している。
- **含意**:
  - audit は既存 implementation status label を維持しつつ、audit classification と evidence detail を追加するべきである。
  - 分類語彙は #33 に合わせて `required`、`deferred`、`out of scope`、`needs reference evidence` とする。
  - S2C packet の documented non-emission reason は、base classification の理由を細分化する補助語彙として扱う。`deferred-non-emission` は stable behavior を方針として延期する場合、`out-of-scope-intentional` は scope 外 packet を意図的に送信しない場合、`compatible-without-emission` は送信しなくても互換性を保てる evidence がある場合に使う。

### Bancho guide の reference data

- **文脈**: 要件 3、4、5、8 は packet payload と struct source の整合性に依存する。
- **参照した source**:
  - `docs/stable-compatibility-guide.md` Bancho Binary Packet Envelope
  - `docs/stable-compatibility-guide.md` Bancho Primitive Types
  - `docs/stable-compatibility-guide.md` Bancho Struct Field Reference
  - `docs/stable-compatibility-guide.md` Bancho Packet Payload Reference
  - `docs/stable-compatibility-guide.md` Fixture Extraction Backlog
- **発見**:
  - guide は packet envelope shape、current stable struct layout、payload mapping、fixture extraction priority を記録している。
  - 注意が必要な箇所には `USER_QUIT` の old/modern shape、S2C 45/46 ordering、`CHANGE_FRIENDONLY_DMS` width、`UserPresence` packing、C2S/S2C `ScoreFrame` size difference がある。
  - fixture backlog は `Match`、`MatchJoin`、`ReplayFrameBundle`、`ScoreFrame`、S2C enum correction case を挙げている。
- **含意**:
  - matrix audit は guide が所有する full field layout を重複させず、guide evidence が不足または矛盾している row を明示する。
  - #17 blocker list は high-priority struct と payload fixture の exact reference を示す。

### 既存コードと test evidence

- **文脈**: 要件は current implementation status と evidence note を要求している。
- **参照した source**:
  - `src/osu_server/transports/stable/bancho/protocol/enums.py`
  - `src/osu_server/transports/stable/bancho/protocol/types.py`
  - `src/osu_server/transports/stable/bancho/protocol/s2c/login.py`
  - `src/osu_server/transports/stable/bancho/protocol/s2c/chat.py`
  - `src/osu_server/transports/stable/bancho/protocol/reader.py`
  - `src/osu_server/transports/stable/bancho/dispatch.py`
  - `tests/unit/transports/bancho/protocol/test_enums.py`
  - `tests/unit/transports/bancho/protocol/test_s2c_login.py`
  - `tests/unit/transports/bancho/protocol/test_s2c_chat.py`
  - `tests/integration/test_login_flow.py`
  - `tests/integration/test_polling_e2e.py`
  - `tests/integration/test_chat_e2e.py`
- **発見**:
  - `ClientPacketID` と `ServerPacketID` enum は存在し、regression coverage がある。
  - login、chat、channel、presence、user stats、friends、silence packet 向けの S2C builder がいくつか存在する。
  - runtime emission と builder availability は異なる。たとえば builder が存在しても full presence/user stats behavior は partial のままである。
  - `USER_QUIT` test は現在 4-byte user id payload を検証しているが、guide は modern stable が `QuitState` を追加することを記録している。
- **含意**:
  - S2C audit row は builder status と runtime emission status を分離する必要がある。
  - evidence note は implemented/builder row では既存 test を引用できるが、partial row は単純な pass/fail ではなく missing behavior note を持つ必要がある。

## アーキテクチャパターン評価

| 選択肢 | 説明 | 強み | risk / limitation | 備考 |
| --- | --- | --- | --- | --- |
| Matrix-first documentation audit | 既存 matrix row を更新し、#17 handoff section を追加する | source of truth を一つに保てる。#16/#33 と一致する | 手作業の table editing は慎重な review が必要 | 採用 |
| 新しい standalone audit document | matrix とは別に packet audit document を作る | table churn を避けて書きやすい | source of truth が競合する | 不採用 |
| 生成される machine-readable catalog | JSON/YAML catalog を追加して docs を生成する | 将来の automation に向く | audit-only task として過剰で tooling surface が増える | この spec では不採用 |
| runtime verification implementation | packet row を検証する code/test を追加する | drift を自動検出できる | audit-only 境界に反し、#17 と重複する | 不採用 |

## 設計判断

### 判断: `docs/stable-compatibility-matrix.md` を authoritative artifact として維持する

- **文脈**: #16 は matrix に audit result と evidence を更新することを要求し、#33 source docs も matrix section を指している。
- **検討した代替案**:
  1. `docs/` 配下に新しい audit report を追加する。
  2. 既存 matrix を更新し、row table が rollup を必要とする箇所だけ focused audit section を追加する。
- **採用方針**: matrix の packet/struct section をその場で更新し、明示的な fixture extraction blocker rollup を matrix に追加する。
- **理由**: matrix はすでに stable compatibility の source of truth であり、別 inventory を追加すると drift が生まれる。
- **trade-off**: matrix table は密度が上がり、formatting の careful review が必要になる。
- **follow-up**: task generation では C2S、S2C、struct、blocker rollup の edit を小さな task に分ける。

### 判断: audit classification と implementation status を分離する

- **文脈**: 既存 row は `Implemented`、`Partial`、`Builder`、`Declared`、`Missing`、`Candidate`、`Out of scope` を使う。#33 は `required`、`deferred`、`out of scope`、`needs reference evidence` を必要とする。
- **検討した代替案**:
  1. implementation status を audit classification に置き換える。
  2. implementation status を残し、audit classification と evidence を notes または supplemental column/section に追加する。
- **採用方針**: implementation status は維持し、audit classification と evidence を note または補助 column/section に追加する。
- **理由**: implementation maturity と compatibility target decision は別の問いに答えるため。
- **trade-off**: 読み手は関連する二つの status concept を解釈する必要がある。
- **follow-up**: ambiguity を避けるため、design で短い status legend update を要求する。

### 判断: guide との不整合は unresolved evidence gap として扱う

- **文脈**: 要件 8.4 は audit result と payload reference の矛盾を示すことを要求している。
- **検討した代替案**:
  1. 正しそうな文書を推測で選び、もう一方を暗黙に更新する。
  2. source evidence が確認されるまで、矛盾を unresolved evidence gap として記録する。
- **採用方針**: matrix と guide の矛盾は、必要な reference source を明記した unresolved evidence gap として matrix に記録する。
- **理由**: stable compatibility は直感で推測してはならないため。
- **trade-off**: 一部 row は後続 evidence task が解決するまで blocked のまま残る。
- **follow-up**: 矛盾が見つかった場合、task は evidence source が confirmed のときだけ guide を更新できる。

### 判断: #17 handoff は fixture work ではなく blocker rollup とする

- **文脈**: #17 は confirmed inventory の後に fixture を抽出する。#33 は blocker と exact source name の識別だけを行う。
- **検討した代替案**:
  1. この spec で fixture を作成する。
  2. exact source name 付きの fixture-blocking packet/struct row list を追加する。
- **採用方針**: matrix に #17 blocker row、classification、exact reference source を列挙する handoff subsection を追加する。
- **理由**: #33 を audit-only に保ちつつ、#17 に実行可能な input を渡せる。
- **trade-off**: #17 は extraction と validation を別途実行する必要がある。
- **follow-up**: #17 task は rollup を消費し、confirmed row の fixture を作成する。

## risk と mitigation

- audit 後に matrix と guide が drift する - 矛盾は unresolved evidence gap として記録し、affected row の近くに source reference を残す。
- implementation status が compatibility requirement と誤読される - 既存 status label と分離した classification language を追加する。
- #17 が exact source のない row から開始する - exact source name のない blocker は必ず `needs reference evidence` とする。
- parser/builder 実装へ scope creep する - File Structure Plan から runtime code と fixture file を除外する。
- 密な markdown table change が review しづらくなる - task を table 単位に分割し、各 slice 後に markdown diff check を実行する。

## 参照

- GitHub Issue #33 - この spec の authoritative issue。
- GitHub Issue #16 - 親 stable compatibility inventory audit。
- GitHub Issue #17 - downstream stable golden fixture extraction。
- `docs/stable-compatibility-matrix.md` - canonical stable compatibility matrix。
- `docs/stable-compatibility-guide.md` - Bancho packet payload と struct field reference。
- `src/osu_server/transports/stable/bancho/protocol/enums.py` - C2S/S2C enum source。
- `src/osu_server/transports/stable/bancho/protocol/types.py` - 現在実装済みの protocol wire type。
- `tests/unit/transports/bancho/protocol/test_enums.py` - enum regression evidence。
- `tests/unit/transports/bancho/protocol/test_s2c_login.py` - login/presence/user stats builder evidence。
