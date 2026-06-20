# Implementation Plan

- [x] 1. Matrix foundation を確定する
- [x] 1.1 Inventory matrix の列、enum、fixture id 規約を確定する
  - Matrix が design の必須列をすべて持つ状態にする。
  - `compatibility classification`、`implementation priority`、`current Athena coverage`、`evidence status` の許可値を matrix 近くに明記する。
  - Placeholder だけの未確定行を、後続 row completion のための実 row または作業中注記へ置き換える。
  - 完了時には、matrix schema を見れば実装者が row に何を入れるべきか判断できる。
  - _Requirements: 1.1, 2.1, 2.2, 8.1, 8.2, 9.1_
  - _Boundary: StableStaticMediaInventoryMatrix, EvidenceGatePolicy, FixtureExtractionHandoff_

- [x] 1.2 Reference source と current coverage source の監査メモを揃える
  - Candidate route の出典を `docs/stable-compatibility-guide.md` と `docs/stable-compatibility-matrix.md` から追跡できるようにする。
  - Current Athena coverage の根拠を runtime route と stable web legacy handler の現状に結びつける。
  - Stable Reference Candidate と Stable Compatibility Evidence の違いを row 更新者が誤読しない注記にする。
  - 完了時には、各 row が reference docs 由来か runtime coverage 由来かを説明できる。
  - _Requirements: 1.3, 1.4, 3.3, 3.4, 9.2, 9.3, 9.4_
  - _Boundary: CurrentCoverageAuditor, EvidenceGatePolicy_

- [x] 2. Canonical route family rows を作成する
- [x] 2.1 Screenshot Compatibility Workflow rows を完成させる
  - Screenshot upload と serving を一つの workflow として、upload、id response、serving、redirect、missing/hidden/expired behavior を分けて row 化する。
  - Numeric screenshot id を preferred response candidate とし、filename/URL response は reference candidate として分ける。
  - JPEG/PNG content type preservation、configurable default unlimited expiry、reference seven-day expiry gap、md5-shaped checksum gapを記録する。
  - 完了時には、screenshot upload から serving までの fixture extraction row が route family ではなく matrix row 単位で揃っている。
  - _Requirements: 1.2, 1.5, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 8.1, 8.2_
  - _Boundary: ScreenshotWorkflowInventory_

- [x] 2.2 Avatar serving rows を完成させる
  - `/a/`、`/a/<filename>`、`/forum/download.php?avatar=<filename>` を canonical avatar rows として登録する。
  - `25`、`128`、`256` の Avatar Serving Variant、size+checksum query variants、`image/png` content type、default avatar fallback を behavior columns に反映する。
  - Avatar asset source は将来の API と operator import が同じ visible validation と variant behavior を通る前提として記録する。
  - Stable serving variant content hash を checksum candidate とし、exact checksum source は `needs-reference` として残す。
  - 完了時には、avatar request path ごとに response candidate、fallback、content type、fixture extraction row が欠けずに埋まっている。
  - _Requirements: 1.2, 1.5, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 8.1, 8.2, 8.3_
  - _Boundary: AvatarServingInventory_

- [x] 2.3 Beatmap thumbnail と preview audio rows を完成させる
  - `/mt/<filename>`、`/thumb/<filename>`、`/images/map-thumb/<filename>` を P1 beatmap thumbnail rows として登録する。
  - `/preview/<filename>`、`/mp3/preview/<filename>` を原則 classification `deferred` かつ priority `P2` の preview audio rows として登録する。
  - Official source first、mirror fallback、404 missing asset response、short negative cache expectation を future implementation input として記録する。
  - Thumbnail と preview audio の content type、cache header、checksum query、filename key が未確認の場合は `needs-reference` とし、checksum query は別 row として fixture extraction できるようにする。
  - 完了時には、thumbnail と preview audio が別 row 群として分類され、priority と evidence status が混ざっていない。
  - _Requirements: 1.2, 1.5, 2.4, 2.5, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 8.1, 8.2, 8.3_
  - _Boundary: BeatmapMediaInventory_

- [x] 2.4 Menu、seasonal、title、adjacent beatmap/direct rows を整理する
  - Menu、seasonal、title image routes を classification `deferred` かつ priority `P3` として inventory に残す。
  - `.osu` / `.osz` / osu!direct 関連 route は adjacent beatmap/direct scope として、詳細 contract をこの spec に吸収しないことを row に記録する。
  - Stable Gameplay Core Workflow の後に static/media implementation を進める優先順位を follow-up readiness に反映する。
  - 完了時には、低優先度 route が `out-of-scope` と誤分類されず、adjacent scope と deferred scope が区別されている。
  - _Requirements: 2.3, 2.6, 2.7, 8.1, 8.2, 9.5_
  - _Boundary: StableStaticMediaInventoryMatrix_

- [x] 3. Host aliases と current coverage を audit する
- [x] 3.1 Host-based alias rows を canonical route rows に結びつける
  - `a.$DOMAIN`、`assets.$DOMAIN`、`b.$DOMAIN`、`d.$DOMAIN`、`d.osu.$DOMAIN`、`s.$DOMAIN`、bare domain、`ha.$DOMAIN` の candidate rows を追加する。
  - Exact host/path combination が未確認の row は `needs-reference` にする。
  - Confirmed ではない alias row も、対応する canonical route family を response contract candidate に明記する。
  - 完了時には、host alias row が canonical row と fixture extraction row の両方に追跡できる。
  - _Requirements: 1.2, 1.5, 7.1, 7.2, 7.3, 7.4, 8.1, 8.2_
  - _Boundary: HostAliasInventory_

- [x] 3.2 Current Athena coverage を全 row に反映する
  - Registered route と handler coverage がない rows は `missing` とする。
  - Adjacent beatmap/direct scope rows (`.osu` / `.osz` related) は route registration と behavior coverage の両方が確認されるまで `missing` とし、path-only の `partial` 判定を適用しない。
  - Non-adjacent rows で route path だけ存在し behavior columns が満たされないケースは `partial` として扱うルールを適用する。
  - Static/media runtime coverage は現時点で missing、`.osu` / `.osz` adjacent route rows は内部 warmup/fetch を context として記録しつつ、registered route がない行は missing として記録する。
  - 完了時には、すべての row が `missing`、`partial`、`implemented` のいずれかを持ち、根拠が current runtime code と矛盾しない。
  - _Requirements: 2.7, 9.1, 9.2, 9.3, 9.4, 9.5_
  - _Boundary: CurrentCoverageAuditor_

- [x] 4. Evidence gate と behavior columns を完成させる
- [x] 4.1 Client-visible behavior columns を全 row で埋める
  - Cache headers、content type、redirect、missing asset response、expiry behavior を全 route family で記録する。
  - Confirmed evidence がない値は `unknown` ではなく `needs-reference` にする。
  - Media bytes rows には content type candidate、redirect rows には status と target shape candidate、cache rows には header candidate を明記する。
  - 完了時には、behavior columns に空欄や曖昧な placeholder が残っていない。
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_
  - _Boundary: StableStaticMediaInventoryMatrix, EvidenceGatePolicy_

- [x] 4.2 Evidence status と implementation readiness gate を適用する
  - `needs-reference` row が client-visible final contract implementation-ready と読めないように明示する。
  - Non-observable preparation work が許される row と、observable contract が blocked の row を区別する。
  - Stable Compatibility Evidence が Stable Reference Candidate と矛盾する場合の rejected/superseded 記録方針を matrix に反映する。
  - 完了時には、未確認 behavior がある row はすべて evidence gate により final implementation blocked と判断できる。
  - _Requirements: 1.3, 1.4, 3.1, 3.2, 3.3, 3.4, 8.2_
  - _Boundary: EvidenceGatePolicy_

- [x] 4.3 Fixture extraction handoff rows を確定する
  - すべての audited row に stable fixture extraction row id を割り当てる。
  - Method、host alias、path pattern、response shape、redirect behavior が異なる fixture は別 id にする。
  - #17 fixture extraction が選択できるように、row id と route family の対応を読みやすく整える。
  - 完了時には、fixture extraction row 列に空欄がなく、row id だけで抽出対象の observable contract を特定できる。
  - _Requirements: 1.5, 9.5_
  - _Boundary: FixtureExtractionHandoff_

- [x] 5. Task outcome を検証する
- [x] 5.1 Requirements coverage と design component coverage を cross-check する
  - すべての requirement ID が matrix、evidence gate、coverage audit、fixture handoff のいずれかに反映されていることを確認する。
  - Design components が orphan になっていないことを確認し、必要なら matrix または research log の見出しに反映する。
  - 完了時には、requirements と design traceability を見ても未対応の row family や component が残っていない。
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 7.1, 7.2, 7.3, 7.4, 8.1, 8.2, 8.3, 8.4, 8.5, 9.1, 9.2, 9.3, 9.4, 9.5_
  - _Boundary: StableStaticMediaInventoryMatrix_

- [x] 5.2 Inventory quality checks を実施する
  - Matrix に required columns、valid enum values、non-empty fixture extraction row が揃っていることを確認する。
  - `unknown`、blank behavior column、unexplained `implemented` coverage、confirmed evidence without source が残っていないことを確認する。
  - 完了時には、`research.md` の matrix が design の review gate と #17 fixture extraction handoff に耐える状態になっている。
  - _Requirements: 1.1, 1.3, 1.5, 3.1, 8.1, 8.2, 9.1, 9.5_
  - _Boundary: StableStaticMediaInventoryMatrix, EvidenceGatePolicy, FixtureExtractionHandoff_
