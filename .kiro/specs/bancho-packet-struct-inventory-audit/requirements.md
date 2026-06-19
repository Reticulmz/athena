# 要件文書

## はじめに

Bancho Packet / Struct Inventory Audit は、GitHub Issue #33「[stable-compat] Bancho packet / struct inventory を監査する」に基づき、stable Bancho の C2S packet、S2C packet、Bancho struct を確認済みの実装対象、明示的な延期、scope 外、または追加 evidence 待ちへ分類するための監査である。

この監査は GitHub Issue #16 の互換性インベントリ監査の子 task であり、#17「Stable golden fixtures を抽出する」が推測ではなく confirmed required surfaces から fixture 抽出を開始できる状態を作る。成果は `docs/stable-compatibility-matrix.md` の C2S Packet Coverage、S2C Packet Coverage、Bancho Struct Coverage と、`docs/stable-compatibility-guide.md` の Bancho Packet Payload Reference に対する根拠付き分類として読める必要がある。

## 境界コンテキスト

- **対象範囲**: GitHub Issue #33 が指定する C2S packet、S2C packet、Bancho struct の監査分類、current implementation status、evidence note、reference source、#17 fixture extraction blocker の明示。
- **対象外**: packet parser、packet builder、packet handler、runtime behavior、golden fixture file、real-client traffic capture の実装または抽出。
- **隣接期待**: #16 は stable compatibility inventory 全体の親 issue として扱う。#17 は、この監査で confirmed required または needs reference evidence とされた packet / struct 行を fixture extraction 入力として扱う。

## 要件

### 要件 1: 監査対象の完全性

**目的:** stable compatibility 保守者として、Issue #33 の packet / struct 行が漏れなく監査対象になることで、packet-family 実装が未確認行を見落とさないようにしたい。

#### 受け入れ条件

1. Bancho packet / struct inventory audit が実行されるとき、Bancho Packet / Struct Inventory Audit は GitHub Issue #33 の source docs に含まれる C2S packet row をすべて監査対象として扱う。
2. Bancho packet / struct inventory audit が実行されるとき、Bancho Packet / Struct Inventory Audit は GitHub Issue #33 の source docs に含まれる S2C packet row をすべて監査対象として扱う。
3. Bancho packet / struct inventory audit が実行されるとき、Bancho Packet / Struct Inventory Audit は GitHub Issue #33 の source docs に含まれる Bancho struct row をすべて監査対象として扱う。
4. Issue #33 の範囲外の stable surface row が同じ関連ドキュメントに存在する場合、Bancho Packet / Struct Inventory Audit はその row をこの spec の必須監査対象として分類しない。

### 要件 2: 分類語彙と evidence note

**目的:** AI 実装エージェントとして、各 packet / struct row の分類理由を同じ語彙で読めることで、次の実装または調査を迷わず選べるようにしたい。

#### 受け入れ条件

1. 監査対象 row が分類されるとき、Bancho Packet / Struct Inventory Audit はその row を `required`、`deferred`、`out of scope`、`needs reference evidence` のいずれかとして分類する。
2. 監査対象 row が分類されるとき、Bancho Packet / Struct Inventory Audit は current implementation status と evidence note を row ごとに示す。
3. row を `required` と分類する場合、Bancho Packet / Struct Inventory Audit は `required` と判断した evidence または reference source を示す。
4. row を `deferred` または `out of scope` と分類する場合、Bancho Packet / Struct Inventory Audit は stable compatibility 上の延期理由または除外理由を示す。
5. row を `deferred` または `out of scope` と分類し、その row が Athena が意図的に送信しない S2C packet である場合、Bancho Packet / Struct Inventory Audit は non-emission reason を `deferred-non-emission`、`out-of-scope-intentional`、`compatible-without-emission` のいずれかとして示す。
6. row の分類に必要な根拠が不足している場合、Bancho Packet / Struct Inventory Audit はその row を `needs reference evidence` として示す。

### 要件 3: C2S packet row の監査

**目的:** packet-family 実装者として、C2S packet の現状と不足 evidence を packet row ごとに読めることで、client request parser や handler の着手条件を判断できるようにしたい。

#### 受け入れ条件

1. C2S packet row が監査されるとき、Bancho Packet / Struct Inventory Audit はその row の current implementation status と evidence note を示す。
2. C2S packet row が監査されるとき、Bancho Packet / Struct Inventory Audit はその packet の payload または no-payload 判断が確認済みかどうかを示す。
3. C2S packet behavior が曖昧である場合、Bancho Packet / Struct Inventory Audit は doc audit、reference implementation audit、real-client traffic capture のどれが必要かを示す。
4. C2S packet row が #17 fixture extraction をブロックする場合、Bancho Packet / Struct Inventory Audit はその blocker 関係を packet row から読めるようにする。

### 要件 4: S2C packet row の監査

**目的:** stable response 実装者として、S2C packet の builder status と runtime emission status を区別できることで、packet が作れる状態と実際に送られる状態を混同しないようにしたい。

#### 受け入れ条件

1. S2C packet row が監査されるとき、Bancho Packet / Struct Inventory Audit はその row の builder status、runtime emission status、または documented non-emission reason を示す。
2. S2C packet builder は存在するが runtime emission が未完成である場合、Bancho Packet / Struct Inventory Audit は builder 完了と runtime 未完成を別の状態として示す。
3. S2C packet を Athena が送信しない方針である場合、Bancho Packet / Struct Inventory Audit は互換性上の non-emission reason を示す。
4. S2C packet behavior が曖昧である場合、Bancho Packet / Struct Inventory Audit は doc audit、reference implementation audit、real-client traffic capture のどれが必要かを示す。

### 要件 5: Bancho struct row の監査

**目的:** fixture 抽出担当者として、Bancho struct の field / value 根拠と不足点を row ごとに読めることで、golden fixture の抽出順序を決められるようにしたい。

#### 受け入れ条件

1. Bancho struct row が監査されるとき、Bancho Packet / Struct Inventory Audit は confirmed source、missing field/value audit note、または explicit deferral reason のいずれかを示す。
2. Bancho struct row が packet payload に使われるとき、Bancho Packet / Struct Inventory Audit は blocking packet dependencies を示す。
3. Bancho struct の current stable layout または enum value が未確認である場合、Bancho Packet / Struct Inventory Audit は追加で必要な reference evidence を示す。
4. Bancho struct が #17 fixture extraction の優先入力である場合、Bancho Packet / Struct Inventory Audit は exact reference source name を示す。

### 要件 6: #17 fixture extraction への引き渡し

**目的:** golden fixture 抽出担当者として、fixture extraction をブロックする packet / struct を exact reference source とともに一覧できることで、#17 を推測なしで開始できるようにしたい。

#### 受け入れ条件

1. Bancho packet / struct inventory audit が完了するとき、Bancho Packet / Struct Inventory Audit は #17 fixture extraction をブロックする packet / struct row を一覧できるようにする。
2. blocker row が一覧されるとき、Bancho Packet / Struct Inventory Audit は audit classification (`required`、`deferred`、`out of scope`、`needs reference evidence`) と exact reference source または source gap を row ごとに示す。
3. blocker row の exact reference source が未確定である場合、Bancho Packet / Struct Inventory Audit はその row を `needs reference evidence` として示す。
4. #17 が fixture extraction 入力を選ぶとき、Bancho Packet / Struct Inventory Audit は confirmed required row と needs reference evidence row を区別できる情報を提供する。

### 要件 7: audit-only 境界

**目的:** spec reviewer として、この spec が監査だけを要求していることを確認できることで、implementation task と evidence task が混ざらないようにしたい。

#### 受け入れ条件

1. Bancho Packet / Struct Inventory Audit は packet parser、packet builder、packet handler、runtime behavior の実装完了を要求しない。
2. Bancho Packet / Struct Inventory Audit は golden fixture file の作成または real-client traffic capture の実施を要求しない。
3. 監査中に実装不足が見つかる場合、Bancho Packet / Struct Inventory Audit はその不足を分類と evidence note として記録し、実装完了扱いにしない。
4. 監査中に fixture 不足が見つかる場合、Bancho Packet / Struct Inventory Audit はその不足を #17 の入力または needs reference evidence として記録し、fixture 抽出完了扱いにしない。

### 要件 8: 監査結果の反映

**目的:** stable compatibility 保守者として、監査結果が matrix から読めることで、GitHub Issue #16 と #33 の進捗を同じ source of truth で追跡できるようにしたい。

#### 受け入れ条件

1. Bancho packet / struct inventory audit が完了するとき、Bancho Packet / Struct Inventory Audit は `docs/stable-compatibility-matrix.md` の C2S Packet Coverage に監査結果を反映する。
2. Bancho packet / struct inventory audit が完了するとき、Bancho Packet / Struct Inventory Audit は `docs/stable-compatibility-matrix.md` の S2C Packet Coverage に監査結果を反映する。
3. Bancho packet / struct inventory audit が完了するとき、Bancho Packet / Struct Inventory Audit は `docs/stable-compatibility-matrix.md` の Bancho Struct Coverage に監査結果を反映する。
4. audit result が `docs/stable-compatibility-guide.md` の Bancho Packet Payload Reference と矛盾する場合、Bancho Packet / Struct Inventory Audit は矛盾を unresolved evidence gap として示す。
