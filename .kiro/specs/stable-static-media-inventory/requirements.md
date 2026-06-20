# 要件ドキュメント

## 概要

Athena の stable client 互換性を担当する実装者は、screenshots、avatars、beatmap thumbnails、preview audio、menu assets、host-based aliases を含む static/media routes について、実装前に必要性、優先度、未確認 evidence、fixture extraction 対象を判断できる必要がある。

現在は `docs/stable-compatibility-guide.md` と `docs/stable-compatibility-matrix.md` に外部実装由来の候補 route inventory があるが、route family ごとの required / deferred / out-of-scope / needs-reference 分類、response contract 候補、host alias の確認状態、cache headers / content type / redirect / missing asset / expiry behavior、fixture extraction へ渡すべき matrix rows が未確定である。

この spec は issue #35 を入力として Stable Static/Media Route Inventory を確定し、Stable Reference Candidate と Stable Compatibility Evidence を分けて扱い、後続の design、fixture extraction、implementation task が推測に依存しない状態を作る。

## 境界コンテキスト

- **対象範囲**: static/media route inventory matrix、route classification、implementation priority、current Athena coverage、behavior contract gap、fixture extraction row、host-based alias 候補、screenshot compatibility workflow、avatar serving と asset source expectation、beatmap thumbnail / preview audio delivery expectation、menu / seasonal / title image の deferred classification。
- **対象外**: `.osu` / `.osz` download/search contract の詳細、osu!direct search response、score submission、player online state / presence sharing、user stats display、user-facing avatar profile UI、画像処理手段の選定、内部構造の責任分担。
- **隣接期待**: `.osu` / `.osz` route は関連 route として inventory に残すが詳細契約は beatmap/direct 側に委譲する。Static/media implementation は Stable Gameplay Core Workflow の後に進める。#17 fixture extraction は route family ではなく matrix row を入力として利用する。

## 要件

### Requirement 1: Route Inventory Matrix

**目的:** stable compatibility の実装者が static/media route 候補を単一 matrix で監査でき、実装と fixture extraction を明示的な evidence から進められるようにする。

#### 受け入れ基準

1. Athena Static/Media Inventory は、監査対象の各 row に route family、method、host alias、path pattern、compatibility classification、implementation priority、current Athena coverage、response contract candidate、cache headers、content type、redirect、missing asset response、expiry behavior、evidence status、fixture extraction row を記録する。
2. route 候補が複数の client-observable contract を持つ場合、Athena Static/Media Inventory は method、path pattern、host alias、response shape、redirect behavior ごとに別 matrix row へ分割する。
3. route behavior が target stable client traffic または同等 evidence で確認されていない場合、Athena Static/Media Inventory はその behavior を `needs-reference` として記録する。
4. route behavior が既存 private server 実装または documentation だけに由来する場合、Athena Static/Media Inventory は confirmed Stable Compatibility Evidence ではなく Stable Reference Candidate として扱う。
5. Athena Static/Media Inventory は fixture extraction 対象を route family 単位ではなく matrix row 単位で特定する。

### Requirement 2: Classification And Scope Boundaries

**目的:** maintainer が route の必要性と実装順序を分離して扱え、低優先度の互換作業を対象外と誤認しないようにする。

#### 受け入れ基準

1. Athena Static/Media Inventory は各 route row に `required`、`deferred`、`out-of-scope`、`needs-reference` のいずれか 1 つの compatibility classification を割り当てる。
2. Athena Static/Media Inventory は対象範囲内の各 route row に `P1`、`P2`、`P3` のいずれか 1 つの implementation priority を割り当てる。
3. `.osu` または `.osz` route が inventory に現れる場合、Athena Static/Media Inventory は詳細な download/search contract を adjacent beatmap/direct scope として記録する。
4. Athena Static/Media Inventory は beatmap thumbnails、avatars、screenshot serving を `required` に分類し、`P1` priority を割り当てる。
5. Athena Static/Media Inventory は、target stable client evidence が core gameplay surface であることを示さない限り、preview audio を `deferred` に分類し、`P2` priority を割り当てる。
6. Athena Static/Media Inventory は menu、seasonal、title image routes を `out-of-scope` ではなく `deferred` に分類し、`P3` priority を割り当てる。
7. Stable Gameplay Core Workflow がより高い優先度である間、Athena Static/Media Inventory は static/media implementation を score submission、online state / presence sharing、user stats display の後続作業として提示する。

### Requirement 3: Evidence Gates

**目的:** maintainer が未確認の client-visible behavior で最終 contract 決定をブロックでき、Athena が推測で stable compatibility を実装しないようにする。

#### 受け入れ基準

1. matrix row が `needs-reference` の場合、Athena Static/Media Inventory はその row を client-visible contract behavior の implementation-ready として扱わない。
2. `needs-reference` row に non-observable preparation work がある場合、Athena Static/Media Inventory は client-visible contract を確定しない範囲に限って準備作業を許可する。
3. target stable client traffic または同等 evidence が row を確認した場合、Athena Static/Media Inventory は row の evidence status を `needs-reference` から confirmed へ更新する。
4. evidence が Stable Reference Candidate と矛盾する場合、Athena Static/Media Inventory は Stable Compatibility Evidence を優先し、candidate を rejected または superseded として記録する。

### Requirement 4: Screenshot Compatibility Workflow

**目的:** stable client user が screenshot upload と serving route を 1 つの互換 workflow として利用でき、upload 済み screenshot を stable serving surface から取得できるようにする。

#### 受け入れ基準

1. screenshot upload を含める場合、Athena は upload、numeric id response、serving、missing/hidden response、expiry policy、serving headers を 1 つの Screenshot Compatibility Workflow として扱う。
2. screenshot upload が成功した場合、Athena は preferred response contract candidate として numeric screenshot id を返す。
3. screenshot content を受け入れる場合、Athena は screenshot serving で JPEG または PNG content type を保持する。
4. Screenshot Compatibility Workflow は operator-configurable expiry policy を公開し、default は unlimited retention とする。
5. screenshot expiry を文書化する場合、Athena Static/Media Inventory は reference seven-day expiry を target stable client behavior が確認または否定するまで evidence gap として保持する。
6. screenshot serving checksum を文書化する場合、Athena Static/Media Inventory は md5-shaped checksum を candidate として扱い、checksum source を `needs-reference` として保持する。
7. screenshot が missing、hidden、または configured policy により expired の場合、Athena は対応する matrix row に記録された missing asset behavior を返す。

### Requirement 5: Avatar Serving And Asset Source

**目的:** stable client user が avatar route から stable-compatible avatar image を取得でき、stable surface 全体で user identity display が機能するようにする。

#### 受け入れ基準

1. Athena Static/Media Inventory は `/a/`、`/a/<filename>`、`/forum/download.php?avatar=<filename>`、relevant avatar host aliases を avatar route candidates として含める。
2. avatar asset が supported source から供給される場合、Athena は visible validation、variant availability、checksum、fallback behavior を supported source 全体で同じように適用する。
3. stable client が avatar size `25`、`128`、`256` を要求する場合、Athena は対応する Avatar Serving Variant を返す。
4. Avatar Serving Variant は `image/png` として返す。
5. avatar serving variant が missing だが stored avatar source から生成可能な場合、Athena は stable avatar response を返す前にその variant を利用可能にする。
6. requested user avatar が unavailable の場合、Athena は対応する matrix row に記録された default avatar behavior を返す。
7. avatar checksum を文書化する場合、Athena Static/Media Inventory は stable serving variant content hash を candidate として扱い、expected stable checksum source を `needs-reference` として保持する。

### Requirement 6: Beatmap Thumbnail And Preview Audio Delivery

**目的:** stable client user が beatmap thumbnails と preview audio を Athena-controlled stable routes から取得でき、client behavior が upstream source HTTP behavior に依存しないようにする。

#### 受け入れ基準

1. Athena Static/Media Inventory は `/mt/<filename>`、`/thumb/<filename>`、`/images/map-thumb/<filename>`、`/preview/<filename>`、`/mp3/preview/<filename>`、relevant host aliases を beatmap media route candidates として含める。
2. beatmap thumbnail または preview audio が要求され、Athena が requested media を利用できる場合、Athena は matrix row に記録された behavior で stable route から media を返す。
3. beatmap thumbnail または preview audio が Athena で利用できない場合、Athena は mirror fallback より先に official source retrieval を優先する。
4. official source と mirror source の両方が requested beatmap media を提供できない場合、Athena はその route row の stable missing asset response として 404 を返す。
5. recent beatmap media miss が configured retry suppression window 内にある間、Athena は stable client request ごとに upstream retrieval を繰り返さない。
6. preview audio が core gameplay として未確認の間、Athena Static/Media Inventory は preview audio classification を `deferred`、priority を `P2` として保持する。

### Requirement 7: Host-Based Alias Coverage

**目的:** stable client user が asset-host request から canonical stable routes と同じ互換 behavior を得られ、host-based stable client が static/media assets を読み込めるようにする。

#### 受け入れ基準

1. Athena Static/Media Inventory は `a.$DOMAIN`、`assets.$DOMAIN`、`b.$DOMAIN`、`d.$DOMAIN`、`d.osu.$DOMAIN`、`s.$DOMAIN`、bare domain、`ha.$DOMAIN` の host-based alias candidate rows を含める。
2. exact host/path combination が target stable client traffic または同等 evidence で確認されていない場合、Athena Static/Media Inventory はその host/path combination を `needs-reference` として記録する。
3. host-based alias が確認された場合、Athena はその alias を対応する canonical static/media route と同じ client-visible behavior へ map する。
4. host-based alias が未確認 behavior を持つ route family を指す場合、Athena Static/Media Inventory はその alias row を同じ evidence gap で blocked のままにする。

### Requirement 8: Behavior Contract Columns

**目的:** compatibility verifier が各 route family の stable-visible HTTP behavior を確認でき、tests が status code と body presence 以外の差分も検出できるようにする。

#### 受け入れ基準

1. Athena Static/Media Inventory はすべての route family について cache headers、content type、redirect behavior、missing asset response、expiry behavior を記録する。
2. behavior contract column に confirmed evidence がない場合、Athena Static/Media Inventory は `unknown` ではなく `needs-reference` を記録する。
3. route row が media bytes を返す場合、Athena はその matrix row に記録された content type を使う。
4. route row が redirect する場合、Athena はその matrix row に記録された redirect target shape と status を使う。
5. route row が cache behavior を持つ場合、Athena はその matrix row に記録された cache headers を公開する。

### Requirement 9: Current Coverage And Follow-Up Readiness

**目的:** project maintainer が Athena の既存 coverage と missing scope を確認でき、同じ route list を再監査せずに follow-up tasks を作成できるようにする。

#### 受け入れ基準

1. Athena Static/Media Inventory は各 matrix row の current Athena coverage を `missing`、`partial`、`implemented` として記録する。
2. route row が Athena に registered されていない、または behaviorally covered ではない場合、Athena Static/Media Inventory は current Athena coverage を `missing` として記録する。
3. Athena が route path を cover しているが、記録された behavior contract columns のすべてを満たしていない場合、Athena Static/Media Inventory は current Athena coverage を `partial` として記録する。
4. Athena が route path と記録された behavior contract columns の両方を cover している場合、Athena Static/Media Inventory は current Athena coverage を `implemented` として記録する。
5. requirements が approved になった時点で、Athena Static/Media Inventory は design と #17 fixture extraction が concrete follow-up rows を選べるだけの matrix 情報を提供する。
