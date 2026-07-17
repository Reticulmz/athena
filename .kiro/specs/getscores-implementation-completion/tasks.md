# 実装タスク

- [ ] 1. Typed completion evidence基盤を構築する

- [x] 1.1 Versioned manifest契約と安全なtyped loadingを実装する
  - 先にschema id、top-level collection、unknown field、duplicate id、fixture root escape、safe error redactionを検証する失敗テストを追加する。
  - response shape、branch case、status crosswalkを共通のimmutable typed bundleへ変換するloaderとvalidation resultを実装する。
  - `Any`、raw credential、raw username、captured raw query、internal provenanceを型契約へ持ち込まない。
  - 完了状態: 正常なmanifestはtyped bundleとして読み込まれ、不正なmanifestはraw valueを含まない決定的なvalidation failureになる。
  - _Requirements: 2.2, 3.7, 5.5_
  - _Boundary: Getscores Completion Evidence_

- [x] 1.2 5種類のexact response shape fixtureと不変条件を整備する
  - 先にauth failure、unavailable、update available、header-only、header with rowsのstatus、header、body bytes、末尾LF数を検証するテストを追加する。
  - 5種類のbody bytesを作成し、short bodyの末尾LFなし、header-onlyの空section、rows responseの末尾LFを固定する。
  - Personal Bestをleaderboard row countへ含めないこと、score rowの全wire field、syntheticなpipe / CR / LFのsanitized outputを検証する。
  - Categoryごとのbody複製を作らず、shape id単位で同じwire grammarを共有させる。
  - 完了状態: 5つのshapeがHTTP status、relevant headers、exact body bytes、newline、PB / row semanticsを検証できる。
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.7, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_
  - _Boundary: Getscores Wire Shape Fixture_

- [x] 1.3 Symbolic branch-case catalogを定義する
  - 先にclosed identity、request selector、seed、mutation、warning vocabularyとshape foreign keyを検証するテストを追加する。
  - Global、Local、Selected Mods、Friends、Country、song select、unsupported leaderboard / playstyle、missing identity、invalid checksum、malformed optional fieldをcatalogへ登録する。
  - Local selectorとexpected domain categoryを分離し、Selected Modsのunsupported bitmask、Friendsのreverse-only除外、Countryのmissing / `XX`を明示する。
  - Malformed branchを`provisional_athena_behavior`として記録し、target-confirmed contractと混同しない。
  - 完了状態: すべてのcaseが一つのshape id、期待category、warning集合、provisional stateへ決定的に解決される。
  - _Requirements: 1.2, 1.3, 1.5, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 5.1, 5.2, 5.3, 5.4, 5.5_
  - _Boundary: Getscores Branch Case Catalog_

- [x] 1.4 Safe symbolic scenario builderを実装する
  - 先にsymbolic profileからsafe synthetic queryを生成するテストと、unknown profile / root escapeを拒否するテストを追加する。
  - Catalogのprofileをruntime test用のquery mutationとexpected body fixtureへ変換し、raw credentialやraw query valueを保存しない。
  - Database seedの責務は既存のcategory、short response、diagnostics integration testへ残し、helperへ永続化責務を移さない。
  - `mods`、`s`、`v`などselectionを変更し得るfieldをparse-only invarianceから除外する。
  - 完了状態: 全branch caseが同じ入力から再現可能なsynthetic queryを生成し、未知のprofileをfallback処理しない。
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 5.1, 5.2, 5.3, 5.5_
  - _Boundary: Symbolic Scenario Builder_

- [x] 1.5 Canonical status crosswalkを固定する
  - 先に全`BeatmapRankStatus`の集合、getscores wire value、beatmap info evidence stateを検証するテストを追加する。
  - Pending / WIP / Graveyard、Ranked、Approved、Qualified、Loved、NotSubmitted、Unknownのrepresentationをcrosswalkへ登録する。
  - Getscores側のlocal override後のeffective statusを入力とし、beatmap info側のRanked=`1`以外の未確認値をnumeric推測しない。
  - Crosswalkをevidence validationへ限定し、getscoresとbeatmap infoのnumeric mapperを共有しない。
  - 完了状態: 全canonical statusが一度ずつ検証され、未確認beatmap info entryは`wire_status=null`で表現される。
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 8.2, 8.6_
  - _Boundary: Stable Beatmap Status Crosswalk_

- [ ] 2. Runtime contractをevidenceへ照合する

- [x] 2.1 (P) Formatterのexact row / sanitization contractを検証する
  - 先にartist、title、usernameへpipe / CR / LFを含むsynthetic dataを投入するformatter testを追加する。
  - Header、Personal Best、leaderboard rowsのbody bytesをshape fixtureと比較し、PBをrow countへ混ぜないことを検証する。
  - score id、username、score、combo、hit counts、miss、perfect、mods、user id、rank、submitted timestamp、replay availabilityの全fieldを固定する。
  - Production correctionはこのtaskで行わず、confirmed mismatchだけを後続のcorrection gateへ渡す。
  - 完了状態: Formatter outputがheader-with-rows fixtureとbyte-for-byteで一致し、sanitizationがwire grammarを壊さない。
  - _Depends: 1.2_
  - _Requirements: 1.4, 1.7, 2.3, 2.4, 2.5, 2.7_
  - _Boundary: Runtime Contract Comparison: Formatter_

- [x] 2.2 (P) Auth、unavailable、update、failure-invariance contractを検証する
  - 先にHTTP status、content headers、empty body、short body bytes、terminal LFを検証するintegration testを追加する。
  - Invalid credentialの401 empty body、missing identity / invalid checksum / unavailable beatmapのunavailable body、same-set filename checksum mismatchのupdate bodyを照合する。
  - Metadata preparationまたはbeatmap file warmupの例外が選択済みresponse bodyを置き換えないことを検証する。
  - Foundationで固定したscenario builderを利用し、helperのschemaや共有fixtureをこのtaskから変更しない。
  - 完了状態: すべてのshort response branchがstatus、relevant headers、exact body bytesまで一致する。
  - _Depends: 1.2, 1.4_
  - _Requirements: 1.1, 1.2, 1.3, 1.6, 1.7, 2.1, 2.2, 2.7, 5.1_
  - _Boundary: Runtime Contract Comparison: Short Responses_

- [x] 2.3 (P) Leaderboard selection branch contractを検証する
  - 先にcategory mapper contractとcatalog-driven integration testを追加し、Stable Localとexpected Global categoryの対応を固定する。
  - Global、Local、Selected Mods supported / unsupported、Friendsのdirectionality、Country match / missing / `XX`、song select、unsupported leaderboard / playstyleを実行する。
  - Personal Bestとleaderboard rowsの有無、unsupported selectionのheader-only、Global fallback禁止、selection-changing fieldの扱いを検証する。
  - Foundationで固定したscenario builderとcatalogをread-onlyで利用し、並列task間でhelperを変更しない。
  - 完了状態: catalogの全selection caseが期待shapeへ一致し、category scopeとrow countがfixture contractを満たす。
  - _Depends: 1.2, 1.3, 1.4_
  - _Requirements: 1.4, 1.5, 2.3, 2.6, 2.7, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 8.3_
  - _Boundary: Runtime Contract Comparison: Leaderboard Selection_

- [x] 2.4 (P) Malformed diagnosticsとprovisional fallbackを検証する
  - 先に各optional fieldのinvalid warningと複数warning集合を検証するdiagnostics testを追加する。
  - mode、mods、leaderboard type、leaderboard version、song select flag、anti-cheat signal、beatmapset hintのmalformed inputごとにwarning categoryを区別する。
  - Warning後のdeterministic fallback shape、provisional evidence state、operator diagnosticのredactionを検証する。
  - Raw credential、username、query value、internal provenanceをログやfixtureへ出さず、confirmed target behaviorとして表現しない。
  - 完了状態: 単一および複数malformed caseで期待warning集合とwire shapeが一致し、diagnostic outputがsafeである。
  - _Depends: 1.3, 1.4_
  - _Requirements: 1.7, 3.8, 5.1, 5.2, 5.3, 5.4, 5.5_
  - _Boundary: Runtime Contract Comparison: Malformed Diagnostics_

- [x] 2.5 (P) Status mapperとcrosswalkのruntime contractを検証する
  - 先にcrosswalkをinputとしてgetscores mapperのwire valueとunsupported representationを検証するunit / integration testを追加する。
  - Effective local override後のstatus、NotSubmitted / Unknownのunavailable、全confirmed getscores valueを照合する。
  - Beatmap info側はevidence-onlyとして扱い、endpoint-specific mapper ownershipとshared numeric mapper禁止を検証する。
  - Production correctionはこのtaskで行わず、confirmed mismatchを後続gateへ渡す。
  - 完了状態: Crosswalkとgetscores mapperの値が一致し、unsupported statusが推測値へ変換されない。
  - _Depends: 1.5_
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 8.2, 8.6_
  - _Boundary: Runtime Contract Comparison: Status Mapping_

- [ ] 3. Stable verificationへcompletion evidenceを統合する

- [x] 3.1 Completion evidenceをstable verifierへ統合する
  - 先にmanifest validation result、safe failure、normal score row statusを検証するunit testを追加する。
  - 3つのmanifestとbody fixtureをmandatory evidenceとして検証し、既存のoptional target probe実行条件を変えない。
  - 正常なPersonal Best / leaderboard rowsをstaleな`KNOWN_GAP`ではなく`PASS`へ更新し、diagnosticにraw valueを出さない。
  - Development verification commandがcompletion surfacesの結果を列挙し、fixture不備を決定的に報告する。
  - 完了状態: Stable verifierがcompletion evidenceを検証し、正常なscore-row surfaceをimplementation gapとして報告しない。
  - _Depends: 1.1, 1.2, 1.3, 1.4, 1.5_
  - _Requirements: 2.7, 5.4, 5.5, 6.4, 7.8_
  - _Boundary: Getscores Completion Evidence, Stable Verification Completion Projection_

- [ ] 3.2 Stale implementation gapを明示的なtarget traffic gapへ置換する
  - 先にverification catalogとreportのstatus分類を検証するテストを追加する。
  - Leaderboard projectionが未実装というstale gapを削除し、Implementation completion、missing evidence、missing Target Stable Client trafficを別状態として投影する。
  - Modern getscoresの`required` route classificationを維持し、Issue #27 / #28のtraffic handoffをreportへ残す。
  - 完了状態: Verification reportはAthena-owned implementationをcompleteとして示しつつ、target-confirmedではないことを明示する。
  - _Depends: 3.1_
  - _Requirements: 6.4, 7.1, 7.2, 7.3, 7.5, 7.6, 7.7, 8.5_
  - _Boundary: Stable Verification Completion Projection_

- [ ] 4. Evidence-limited integrationと最終handoffを完了する

- [ ] 4.1 Evidence authorityとbounded correction gateを適用する
  - 先行taskのmismatch結果をTarget Stable Client traffic、official fixture、protocol documentation、reference consensus、single reference、Athena deterministic behaviorの順で判定する。
  - Evidence Authority Decision Logへsource、precedence decision、correction / no-correction result、未解決gapを記録し、結果がresearch artifactから観測できるようにする。
  - Athena内部の期待だけであればruntimeを変更せず、confirmed evidenceとの矛盾だけをone-branch correctionへ限定する。
  - Production symbolを編集する前にGitNexus impact analysisを実行し、HIGH / CRITICALなら編集を停止してユーザーへwarningとdirection requestを行う。承認なしに編集しない。
  - Confirmed correction時はexact fixture、focused regression test、関連mapper / formatterだけを同じintegrationへ含め、legacy aliasや隣接featureを変更しない。
  - 完了状態: すべてのmismatchがcorrection済みまたは明示的なevidence gapとなり、production diffがないかone-branchへ限定される。
  - _Depends: 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2_
  - _Requirements: 5.6, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_
  - _Boundary: Evidence-Limited Correction Gate_

- [ ] 4.2 全quality、scope、regression gateを実行する
  - 先にtargeted getscores tests、category mapper test、quality gate、full test gate、all-files hooksの実行結果を収集する。
  - Failure時はimplementationを疑い、root causeを修正して同じgateを再実行する。Testやconfigを無効化して通過させない。
  - GitNexusのmain比較change detectionでexpected symbols / flowsだけが変更されていることを確認する。
  - Legacy alias、beatmap info implementation、leaderboard projection redesign、RX / AP、osu!direct、dependency / config / schema変更がないことをscope reviewする。
  - 完了状態: Relevant tests、quality、full test、hooks、change detectionが成功し、scope reviewに違反がない。
  - _Depends: 4.1_
  - _Requirements: 2.7, 6.6, 7.8, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_
  - _Boundary: Runtime Contract Comparison, Stable Verification Completion Projection, Evidence-Limited Correction Gate_

- [ ] 4.3 Validated completion stateをCompatibility Guide / Matrixへ同期する
  - 4.2で取得したvalidation結果を先に確認し、GuideとMatrixが同じimplementation / evidence / traffic stateを示すよう更新する。
  - Modern getscoresを`Implemented` / `required`へ反映し、response branches、status mapping、provisional malformed behavior、remaining Issue #27 / #28 gapを記録する。
  - `Implemented`をFull Stable Compatibilityまたはtarget-confirmed getscoresと表現せず、Issue #12をclose可能にする根拠と実行結果を明示する。
  - Docs変更後にdiff-check、all-files hooks、Guide / Matrix consistency checkを再実行する。
  - 完了状態: Guide、Matrix、fixtures、tests、verification reportのcompletion stateが相互に一致し、staleなmissing implementation記述が残らない。
  - _Depends: 4.2_
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 8.5_
  - _Boundary: Compatibility Documentation Sync, Stable Verification Completion Projection_

## Implementation Notes

- 1.1: Manifest validationはevidence sourceのtraversal、deep JSON、非UTF-8、valid-but-unregistered foreign keyをsafe failureとして扱い、productionとtestの両方をstrict type-checkする。
- 1.2: Exact response fixtureは既存status fixtureを変更せず、5つのshape専用bodyとmanifest mutation testでheaders、LF、PB / row grammarを固定する。
- 1.3: Branch catalogは28件のsymbolic caseとcase-local coherence validationを持つ。`INVALID_ANTI_CHEAT_SIGNAL`はruntime未対応のため、Task 2.4開始前にcredentialを除いた実requestの`a` field contractを確認する。
- 1.4: Scenario builderはcaller-owned `c/f/i/us/ha`を保持し、identity -> selector -> mutationの順でsafe queryを生成する。Body resolverはcanonical rootをstrict resolveし、public `read_body_bytes()`境界だけを使用する。
- 1.5: Getscoresは7 statusをofficial fixture、Approved / UnknownをAthena deterministic evidenceで固定する。Beatmap infoはRanked=`1`のみofficial fixtureとし、他8 statusは`unconfirmed/null/[]`を維持する。Markdown sourceは実在pathと正規化anchorまで検証する。
- 2.1: Formatterはcanonical `header_with_rows` fixtureとbyte-for-byte一致した。PBをrow countへ含めず、artist / title / 全usernameのpipe / CR / LF sanitationと全score wire fieldを同じtestで固定し、production correctionは不要だった。
- 2.2: Auth / unavailable / updateのshort responseはscenario builderからcanonical status / headers / body / terminal LFへ一致した。Metadata preparationとfile warmupの例外seam到達を各1回assertし、選択済みupdate / unavailable bodyが維持されるためproduction correctionは不要だった。
- 2.3: 12 selection casesをcatalog / scenario builderからparser、category mapper、endpointへ接続した。Global / Local / Selected Mods / Friends / Country / song select / unsupported selection / no-scoreがexpected category、PB、2 rowsまたはheader-onlyへ一致し、詳細な既存rank / mod coverageも保持した。
- 2.4: 8 malformed caseと2 invariance controlをcatalogからparser / endpointへ接続し、warning集合、provisional state、fallback shape、PB / rows、diagnostic redactionを固定した。`a`はinteger-backed booleanとして解析し、non-integerを`INVALID_ANTI_CHEAT_SIGNAL` + false fallbackへ限定修正した判断をTask 4.1のDecision Logへ引き継ぐ。
- 2.5: Typed crosswalkの全9 statusをruntime mapperとendpointへ照合し、Approved header、NotSubmitted / Unknownのexact unavailable、persisted local overrideを固定した。ASTでmodule-local `_STATUS_TO_WIRE`のdirect lookupを検証し、Approved=`3`のprovenance再分類はTask 4.1へ残した。
- 3.1: Stable verifierはlegacy fixtureに加えて3種類のcompletion evidenceをmandatory golden fixtureとして投影する。loader failureは固定3件のsafe FAIL、body grammar failureは該当surfaceだけのFAILとして扱い、正常なscore rowはPASSへ更新した。
