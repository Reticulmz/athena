# 要件定義

## はじめに

Legacy Web Endpoint Inventory Audit は、GitHub Issue #32「[stable-compat] Legacy /web endpoint inventory を監査する」に基づき、現行 osu!stable client を primary target とする legacy web-family endpoint の監査分類を確定するための spec である。

この監査は GitHub Issue #16 の互換性インベントリ監査の子 task であり、route 実装、fixture 作成、traffic capture 実施そのものではなく、`docs/stable-compatibility-matrix.md` と `docs/stable-compatibility-guide.md` から次の実装・検証 task が推測なしで着手できる状態を作る。

## 境界コンテキスト

- **対象範囲**: legacy `/web/*.php` endpoint inventory、同一 legacy web-family の `/rating/ingame-rate*.php` aliases、endpoint family ごとの分類、exact path ごとの追跡可能性、request/response evidence note、matrix / guide の docs 更新。
- **対象外**: route 実装、runtime behavior 実装、golden fixture file 作成、real-client traffic capture 実施、release / static / media / download route inventory の本体監査。
- **隣接する期待値**: release / static / media / download 系 overlap は該当 task へ渡す adjacent context として記録する。古い stable client 向け getscores / submit aliases は best effort support 候補として扱い、現行 osu!stable client の P0 required route と混同しない。

## 要件

### 要件 1: 監査対象の完全性

**目的:** Stable compatibility 保守者が Issue #32 の legacy web-family endpoint を漏れなく監査対象として確認でき、route 実装や fixture 抽出の前提に未確認の endpoint が残らないようにする。

#### 受け入れ基準

1. Legacy Web Endpoint Inventory Audit 実行時、GitHub Issue #32 の source docs に含まれる legacy `/web/*.php` endpoint row をすべて監査対象として扱う
2. Legacy Web Endpoint Inventory Audit 実行時、同一 legacy web-family の `/rating/ingame-rate.php` と `/rating/ingame-rate2.php` を監査対象として扱う
3. Legacy Web Endpoint Inventory Audit 実行時、`docs/stable-compatibility-matrix.md` の Stable HTTP Endpoint Coverage と Reference Route Inventory の legacy web-family row を照合する
4. release / static / media / download route が legacy web endpoint row と overlap する場合、その route を adjacent context として記録し、この spec の本体監査対象として分類しない

### 要件 2: 分類語彙の一貫性

**目的:** AI 実装エージェントが endpoint 分類を固定語彙で読め、次に必要な実装、検証、延期、または除外判断を迷わず選べるようにする。

#### 受け入れ基準

1. legacy web-family endpoint row を分類するとき、その row を `required`、`compatibility no-op`、`deferred`、`out of scope`、`needs reference evidence` のいずれかとして分類する
2. legacy web-family endpoint row を監査後の最終状態として記録するとき、`candidate` を最終分類として使用しない
3. endpoint が P0 core login/play workflow に real behavior を必要とする場合、その endpoint を `required` として分類する
4. endpoint が現行 osu!stable client 互換の route / response contract だけを必要とし、real behavior や durable state mutation を必要としない場合、その endpoint を `compatibility no-op` として分類する
5. endpoint の request / response / auth / target client traffic evidence が不足している場合、その endpoint を推測で分類せず `needs reference evidence` として分類する

### 要件 3: Evidence note の完全性

**目的:** Stable compatibility reviewer が endpoint family ごとの request / response evidence を同じ形で確認でき、success case だけでなく failure sentinel も実装前に確認できるようにする。

#### 受け入れ基準

1. endpoint family を監査するとき、auth method を確認済み、未確認、または scope 外として記録する
2. endpoint family を監査するとき、required request params を確認済み、未確認、または scope 外として記録する
3. endpoint family を監査するとき、success response を確認済み、未確認、または scope 外として記録する
4. endpoint family を監査するとき、auth failure response を確認済み、未確認、または scope 外として記録する
5. endpoint family を監査するとき、domain / data-not-found response を確認済み、未確認、または scope 外として記録する
6. endpoint family を監査するとき、malformed request response を確認済み、未確認、または scope 外として記録する

### 要件 4: Evidence source の制約

**目的:** Compatibility 保守者が classification の根拠を確認可能な source に限定でき、undocumented guess による stable client 互換性の破損を避けられるようにする。

#### 受け入れ基準

1. endpoint classification を確定するとき、classification の evidence source を row または endpoint family から読めるようにする
2. `needs reference evidence` endpoint を別分類へ移動するとき、target stable client traffic、公式または準公式 protocol docs、既存 reference implementation、または Athena focused fixture/test のいずれかを解除根拠として示す
3. endpoint の response shape が未確認である場合、その endpoint を `compatibility no-op` として分類しない
4. endpoint の現行 osu!stable client traffic が未確認で、reference implementation にしか存在しない場合、その endpoint を P0 `required` として分類しない

### 要件 5: 現行 stable client と legacy alias の切り分け

**目的:** Stable compatibility planner が現行 osu!stable client と古い stable client alias の扱いを分けて読め、P0 scope と best effort support が混ざらないようにする。

#### 受け入れ基準

1. endpoint classification が現行 client 必須性を判断するとき、現行 osu!stable client を primary target として扱う
2. 古い `/web/osu-getscores.php` から `/web/osu-getscores6.php` までの aliases を監査するとき、alias ごとの response variant が特定されるまで `needs reference evidence` として分類する
3. 古い submit aliases である `/web/osu-submit-modular.php`、`/web/osu-submit.php`、`/web/osu-submit-new.php` を監査するとき、alias ごとの request / response variant が特定されるまで `needs reference evidence` として分類する
4. legacy alias が現行 osu!stable client の P0 workflow では呼ばれないが古い client support 候補である場合、その alias を best effort support 候補として読めるようにする

### 要件 6: Deferred と out-of-scope の明示

**目的:** Roadmap 管理者が後回しにする endpoint と対象外 endpoint を分けて読め、将来実装予定と product scope 外を混同しないようにする。

#### 受け入れ基準

1. `/web/osu-bmsubmit-*` または `/web/osu-osz2-bmsubmit-*` 配下の beatmap submission endpoints を監査するとき、それらを P0 core login/play 完成後の `deferred` endpoint として分類する
2. `/web/coins.php` を監査し、現行 osu!stable client 通常プレイに必要な evidence がない場合、その endpoint を `out of scope` として分類する
3. `/web/osu-benchmark.php` を監査し、現行 osu!stable client 通常プレイに必要な evidence がない場合、その endpoint を `out of scope` として分類する
4. endpoint を `deferred` または `out of scope` として分類する場合、後続 milestone、operator policy、product scope 外、または removed/private-server-specific workflow の理由を示す

### 要件 7: Compatibility no-op endpoint の扱い

**目的:** Stable client 互換性確認者が route / response contract は必要だが real behavior は不要な endpoint を区別でき、P0 scope を広げすぎず client-visible failure を防げるようにする。

#### 受け入れ基準

1. `/web/osu-getseasonal.php` を監査するとき、現行 osu!stable client が呼び出す確認済み endpoint として扱う
2. `/web/osu-getseasonal.php` の initial behavior を分類するとき、dynamic seasonal background 管理を後続 scope とし、現行 client 呼び出し確認と reference JSON array family shape は記録するが、exact empty-array body と cache contract が fixture-backed になるまでは `needs reference evidence` として扱う
3. `/web/osu-title-image.php` や `/menu-content.json` などの title / menu endpoint が current client traffic evidence を欠く場合、その endpoint を `needs reference evidence` として分類する
4. social / status endpoint が empty body、static body、または sentinel response を安全に使える場合、その endpoint の confirmed response shape を evidence note に示したうえで `compatibility no-op` として分類する

### 要件 8: Family 方針と exact path 追跡

**目的:** Docs consumer が endpoint family の方針と exact path の差分を両方追跡でき、grouped rows の中で response variant を見落とさないようにする。

#### 受け入れ基準

1. endpoint family を監査するとき、family-level classification または family-level evidence gap を示す
2. family に複数 exact path が含まれる場合、Reference Route Inventory の exact path row から分類または evidence note を追跡できるようにする
3. exact path ごとに response variant が異なる場合、family-level summary だけで差分を隠さない
4. grouped Stable HTTP Endpoint Coverage row が複数 exact path を代表する場合、grouped row と exact path row の対応を読めるようにする

### 要件 9: Matrix と guide への反映

**目的:** Stable compatibility 保守者が監査結果を既存 docs から読め、GitHub Issue #16 と #32 の進捗を同じ source of truth で追跡できるようにする。

#### 受け入れ基準

1. Legacy Web Endpoint Inventory Audit が完了するとき、`docs/stable-compatibility-matrix.md` の Stable HTTP Endpoint Coverage に監査分類を反映する
2. Legacy Web Endpoint Inventory Audit が完了するとき、`docs/stable-compatibility-matrix.md` の Reference Route Inventory に exact path の追跡情報を反映する
3. endpoint family に詳細 evidence gap がある場合、`docs/stable-compatibility-guide.md` に endpoint family 別の evidence gap を記録する
4. matrix と guide の endpoint behavior 記述が矛盾する場合、その矛盾を unresolved evidence gap として示す

### 要件 10: Audit-only 境界

**目的:** Spec reviewer がこの spec が監査と docs 更新だけを要求していることを確認でき、implementation work と verification work が混ざらないようにする。

#### 受け入れ基準

1. Legacy Web Endpoint Inventory Audit は route implementation completion を要求しない
2. Legacy Web Endpoint Inventory Audit は golden fixture file creation を要求しない
3. Legacy Web Endpoint Inventory Audit は real-client traffic capture execution を要求しない
4. audit result が missing implementation を特定した場合、その不足を classification、evidence note、または follow-up checklist として記録し、implementation complete として扱わない
5. audit result が missing fixture または traffic evidence を特定した場合、その不足を `needs reference evidence` または follow-up checklist として記録し、fixture extraction complete または traffic capture complete として扱わない
