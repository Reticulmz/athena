# 要件ドキュメント

## はじめに

Issue #12のModern Getscores Implementation Completionとして、modern `/web/osu-osz2-getscores.php` のAthena-owned behaviorをclient-observableなfixtureとtestで固定し、Compatibility Guide / Matrixを現行実装へ同期する。これはTarget Stable Client trafficによる最終互換確認ではなく、Athena実装が完了していることと、残るtraffic evidence gapが分離されていることを示すための仕様である。

## 境界コンテキスト

- **対象**: modern getscoresの全response branch、distinct wire shape fixture、branch case catalog、Stable Beatmap Status Crosswalk、provisional malformed behavior、evidenceに基づく最小修正、Compatibility Guide / Matrix同期。
- **対象外**: Target Stable Client traffic取得、legacy getscores alias、beatmap info endpoint実装、leaderboard projection再設計、RX / AP拡張、osu!direct。
- **隣接期待**: Target Stable Clientによる最終確認はIssue #27 / #28が所有し、将来のbeatmap info実装はStable Beatmap Status Crosswalkを参照する。

## 要件

### Requirement 1: Modern getscores response contract

**Objective:** Stable client利用者として、modern getscoresの各branchがdeterministicなresponseを返してほしい。これによりsong selectとleaderboard表示がAthena内部状態に左右されず動作する。

#### Acceptance Criteria

1. When stable credential authenticationが失敗する, the Modern Getscores Endpoint shall HTTP 401とempty bodyを返す。
2. When request identityが不足している、checksumが不正である、またはbeatmapがunavailableである, the Modern Getscores Endpoint shall unavailable wire shape `-1|false` を返す。
3. When checksumが一致せず同一beatmapset内のfilenameが一致して保存済みchecksumとの差分が確認される, the Modern Getscores Endpoint shall update-available wire shape `1|false` を返す。
4. When display可能なbeatmapが解決される, the Modern Getscores Endpoint shall beatmap headerと、request scopeで利用可能なPersonal Bestおよびleaderboard rowsを含むresponseを返す。
5. When song select、unsupported leaderboard selection、unsupported playstyle、または候補が存在しないviewer-dependent selectionである, the Modern Getscores Endpoint shall beatmap headerを維持し、Personal Bestとleaderboard rowsを返さない。
6. If metadata preparationまたはbeatmap file warmupがresponse branch決定後に失敗する, the Modern Getscores Endpoint shall 選択済みのwire responseを変更しない。
7. The Modern Getscores Endpoint shall response bodyへcredential、internal provenance、fetch source、verification stateを含めない。

### Requirement 2: Getscores Wire Shape Fixture

**Objective:** Maintainerとして、distinctなclient-observable responseをexact fixtureで検証したい。これによりformatterやroute変更によるwire regressionを検出できる。

#### Acceptance Criteria

1. The Getscores Completion Evidence shall auth failure、unavailable、update available、header-only、Personal Best + leaderboard rowsの各distinct wire shapeにexact response fixtureを持つ。
2. The Getscores Wire Shape Fixture shall HTTP status、relevant content headers、body bytes、および適用される末尾newline contractを検証可能にする。
3. When header responseがleaderboard rowsを含む, the Getscores Wire Shape Fixture shall score row countを返却leaderboard row数と一致させ、Personal Bestをcountへ含めない。
4. When Personal Bestまたはleaderboard rowを表現する, the Getscores Wire Shape Fixture shall score id、username、score、combo、hit counts、miss、perfect、mods、user id、rank、submitted timestamp、replay availabilityを固定する。
5. When artist、title、またはusernameにpipe、CR、LFが含まれる, the Getscores Wire Shape Fixture shall stable text grammarを壊さないsanitized outputを固定する。
6. If複数のLeaderboard Categoryが同一のHTTP status、headers、body grammarを返す, the Getscores Completion Evidence shall categoryごとにexact body fixtureを複製しない。
7. The Modern Getscores Endpoint shall 全てのGetscores Wire Shape Fixtureと一致するresponseを生成する。

### Requirement 3: Getscores Branch Case Catalog

**Objective:** Maintainerとして、request selectionと期待wire shapeの関係を一つのcatalogで確認したい。これによりcategory固有のbehaviorをbody fixtureの重複なしで検証できる。

#### Acceptance Criteria

1. The Getscores Branch Case Catalog shall Global、Local、Selected Mods、Friends、Country、song select、unsupported leaderboard typeを網羅する。
2. When Local selectionが指定される, the Getscores Branch Case Catalog shall Globalと同じcandidate scopeおよびwire shapeを期待する。
3. When Selected Mods selectionが指定される, the Getscores Branch Case Catalog shall raw Stable mod bitmaskに基づくexact selectionを期待し、unsupported bitmaskではheader-only shapeを期待する。
4. When Friends selectionが指定される, the Getscores Branch Case Catalog shall viewer自身とviewerが追加したfriendを候補とし、reverse-only relationshipを候補へ含めないbehaviorを期待する。
5. When Country selectionが指定される, the Getscores Branch Case Catalog shall viewer countryで候補を限定し、countryが未設定または`XX`ならheader-only shapeを期待する。
6. When song selectまたはunsupported leaderboard typeが指定される, the Getscores Branch Case Catalog shall Global rowsへのfallbackではなくheader-only shapeを期待する。
7. The Getscores Branch Case Catalog shall 各caseを一つのGetscores Wire Shape Fixtureへ対応付ける。
8. When parse-onlyまたはdiagnostic fieldがresponse selectionを変更しない, the Getscores Branch Case Catalog shall 同じwire shapeが維持されることを期待する。

### Requirement 4: Stable Beatmap Status Crosswalk

**Objective:** Maintainerとして、canonical beatmap statusとendpoint固有wire statusの関係を明示したい。これによりgetscoresとbeatmap infoのdomain meaningがdriftしない。

#### Acceptance Criteria

1. The Stable Beatmap Status Crosswalk shall canonicalなBeatmapRankStatusごとにgetscores wire statusまたはunsupportedを示す。
2. The Stable Beatmap Status Crosswalk shall Pending、WIP、Graveyardを`0`、Rankedを`2`、Approvedを`3`、Qualifiedを`4`、Lovedを`5`として固定する。
3. The Stable Beatmap Status Crosswalk shall NotSubmittedとUnknownをgetscores headerではunsupportedとして扱い、unavailable responseへ対応付ける。
4. When local status overrideが存在する, the Modern Getscores Endpoint shall override適用後のcanonical statusをcrosswalkへ入力する。
5. The Stable Beatmap Status Crosswalk shall beatmap info側について確認済みwire representation、unsupported、または`未確認`を明示する。
6. If beatmap info側のwire representationを確認できるevidenceが存在しない, the Stable Beatmap Status Crosswalk shall 数値を推測しない。
7. The Stable Beatmap Status Crosswalk shall getscoresとbeatmap infoがendpoint固有wire mappingを維持し、同じ数値mapperを共有することを要求しない。

### Requirement 5: Provisional malformed request behavior

**Objective:** Operatorとして、target未確認のmalformed requestでもAthenaの現在のbehaviorをdeterministicに観測したい。これにより最終互換確認前のregressionを区別できる。

#### Acceptance Criteria

1. When checksum形式が不正またはbeatmap identityが不足する, the Modern Getscores Endpoint shall provisional unavailable shapeを返す。
2. When optionalなmode、mods、leaderboard type、leaderboard version、song select flag、またはbeatmapset hintがmalformedであり有効なidentityが残る, the Modern Getscores Endpoint shall warningをoperatorへ観測可能にし、deterministicなfallbackで処理を継続する。
3. When複数のoptional fieldがmalformedである, the Modern Getscores Endpoint shall 各warning categoryを区別可能にする。
4. The Getscores Completion Evidence shall malformed branchをGetscores Provisional Malformed Request Behaviorとして明示し、target-confirmed contractと表現しない。
5. The Getscores Completion Evidence shall raw credential、raw username、raw query valueをfixtureまたはoperator diagnosticsへ保存しない。
6. If将来のStable Compatibility Evidenceがprovisional behaviorと矛盾する, the Modern Getscores Endpoint shall 確認済みevidenceを優先する。

### Requirement 6: Evidence authority and limited correction

**Objective:** Maintainerとして、互換evidenceが競合した場合の判断順序を固定したい。これによりAthena内部の期待だけでwire behaviorが変更されない。

#### Acceptance Criteria

1. When compatibility evidenceが競合する, the Getscores Completion Effort shall Target Stable Client traffic、official client-observable fixture、protocol documentation、複数reference implementationの一致、単一reference implementation、Athena deterministic behaviorの順に優先する。
2. When official client-observable fixtureとreference implementationが矛盾する, the Getscores Completion Effort shall official fixtureを優先する。
3. When現行runtime behaviorが確認済みStable Compatibility EvidenceまたはStable Beatmap Status Crosswalkと矛盾する, the Getscores Completion Effort shall Getscores Evidence-Limited Correctionとして最小のruntime correctionを行う。
4. If矛盾の根拠がAthena内部の期待値またはtest-only assumptionだけである, the Getscores Completion Effort shall target未確認のwire behaviorを変更せずevidence gapを記録する。
5. When Getscores Evidence-Limited Correctionを行う, the Getscores Completion Effort shall 対象branchのexact fixtureとregression validationを追加する。
6. The Getscores Completion Effort shall unrelatedなruntime behaviorまたはadjacent featureをcorrectionへ含めない。

### Requirement 7: Compatibility documentation synchronization

**Objective:** Maintainerとして、Guide、Matrix、fixture、testが同じ実装状態を示してほしい。これによりIssue #12の完了と残る互換gapを区別できる。

#### Acceptance Criteria

1. When全てのAthena-owned response branch、wire shape fixture、branch case、status crosswalkがvalidationを通過する, the Compatibility Matrix shall Modern getscoresのcurrent implementation statusを`Implemented`として記録する。
2. The Compatibility Matrix shall Modern getscoresのroute classificationを`required`として維持する。
3. The Compatibility Matrix shall missing implementation、missing evidence、missing traffic evidenceを同一状態として扱わず分離して記録する。
4. The Compatibility Guide shall current response branch、status mapping、provisional malformed behavior、remaining target traffic gapをfixtureおよびvalidation結果と一致させる。
5. The Compatibility Guide and Matrix shall Target Stable Client trafficによる最終確認をIssue #27 / #28へ引き継ぐことを明示する。
6. The Compatibility Guide and Matrix shall Modern Getscores Implementation CompletionをFull Stable Compatibilityまたはtarget-confirmed getscoresと表現しない。
7. If既存documentationが完了済みleaderboard behaviorをmissing implementationとして扱っている, the Compatibility Documentation shall 現行validation evidenceに基づいてstale記述を更新する。
8. Whenこれらのcompletion criteriaが満たされる, the Compatibility Documentation shall Issue #12をimplementation-completeとしてclose可能な根拠を示す。

### Requirement 8: Scope protection

**Objective:** Maintainerとして、Issue #12のcompletion workをmodern getscoresの証拠整備へ限定したい。これにより隣接featureの推測実装とdiff拡大を防げる。

#### Acceptance Criteria

1. The Getscores Completion Effort shall `/web/osu-getscores.php`から`/web/osu-getscores6.php`までのlegacy aliasを追加またはmodern formatterへ接続しない。
2. The Getscores Completion Effort shall beatmap info endpointを実装しない。
3. The Getscores Completion Effort shall leaderboard projectionを再設計せず、現行のGlobal、Country、Friends、Selected Mods behaviorをvalidation対象として扱う。
4. The Getscores Completion Effort shall RX / AP leaderboard拡張とosu!directを含めない。
5. The Getscores Completion Effort shall Target Stable Client traffic取得をIssue #12のcompletion条件にしない。
6. The Getscores Completion Effort shall target未確認のresponse sentinel、legacy alias behavior、beatmap info wire valueを推測しない。
