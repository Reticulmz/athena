# Requirements Document

## Introduction

GitHub Issue #24として、現行Target Stable Clientが使用するbeatmap info binary contractを、実装から独立したexact payload bytesで固定する。対象は`StableGrade`、`BeatmapInfoRequest`、`BeatmapInfo`、`BeatmapInfoReply`であり、将来のpacket runtime実装がfield順序、値表現、index semanticsを推測せずに検証できる状態を作る。

## Boundary Context

- **In scope**: 現行Target Stable Clientの4-Grade layout、`StableGrade`のwire値、request / row / replyのbinary contract、独立golden fixtureによるencode / decode検証、Stable Compatibility Matrixのfixture状態
- **Out of scope**: C2S 68 handler、S2C 69 packet builder、beatmap metadata lookup、`/web/osu-getbeatmapinfo.php`、旧client layout、grade集計 / projection、truncatedまたはmalformed packetのruntime処理
- **Adjacent expectations**: C2S 68とS2C 69のruntime状態は`Missing`のままとし、malformed packet処理はIssue #15の責務とする。Target packet captureは必須条件にせず、入手できた場合は既存fixtureより強い互換性証拠として評価する

## Requirements

### Requirement 1: 対象プロトコル範囲

**Objective:** Athenaの保守者として、fixtureが保証する範囲と保証しない範囲を区別したい。これにより、struct evidenceの整備をruntime機能の完成と誤認せずに進捗を判断できる。

#### Acceptance Criteria

1. The Athena Stable Compatibility Evidence shall 現行Target Stable Clientの4-Grade beatmap info layoutだけを対象とする
2. The Athena Stable Compatibility Evidence shall `StableGrade`、`BeatmapInfoRequest`、`BeatmapInfo`、`BeatmapInfoReply`を対象に含める
3. The Athena Stable Compatibility Evidence shall C2S 68 handler、S2C 69 packet builder、metadata lookup、HTTP beatmap info endpoint、旧client layoutを対象に含めない
4. The Athena Stable Compatibility Evidence shall grade集計、grade projection、truncatedまたはmalformed packetのruntime処理を対象に含めない
5. When このfixture整備が完了したとき, the Athena compatibility status shall beatmap infoのruntime supportを完成扱いにしない

### Requirement 2: StableGradeのwire vocabulary

**Objective:** Athenaの保守者として、stable client固有のgradeをclosed setとして固定したい。これにより、canonical score gradeやraw byteと混同せずに互換性を検証できる。

#### Acceptance Criteria

1. The Athena Stable Compatibility Evidence shall `StableGrade`を`XH=0`、`SH=1`、`X=2`、`S=3`、`A=4`、`B=5`、`C=6`、`D=7`、`F=8`、`N=9`のclosed setとして表現する
2. When `StableGrade`値をencodeするとき, the Athena stable protocol contract shall 対応する1-byte wire値を生成する
3. When 対応範囲内の`StableGrade` wire値をdecodeするとき, the Athena stable protocol contract shall 対応するgrade memberを復元する
4. The Athena Stable Compatibility Evidence shall `StableGrade`をcanonical score grade、grade集計結果、またはfree-form integerとして扱わない

### Requirement 3: BeatmapInfoRequestのbinary contract

**Objective:** Athenaの保守者として、filename requestとbeatmap ID requestが混在するpayload layoutを固定したい。これにより、requestの境界と順序を正確に検証できる。

#### Acceptance Criteria

1. The Athena stable protocol contract shall `BeatmapInfoRequest`を`i32 filename_count`、`BanchoString[filename_count]`、`i32 id_count`、`i32[id_count]`の順序で表現する
2. When filename requestとbeatmap ID requestが同じpayloadに含まれるとき, the Athena stable protocol contract shall 各listの件数と入力順序を保持する
3. When `filename_count`が0のとき, the Athena stable protocol contract shall filename entryを含めず、直後の`id_count`を正しいfield境界で表現する
4. When `id_count`が0のとき, the Athena stable protocol contract shall beatmap ID entryを含めず、payloadをそのcount fieldで完結させる
5. When 有効な`BeatmapInfoRequest` payloadをdecodeするとき, the Athena stable protocol contract shall filename listとbeatmap ID listを区別して復元する

### Requirement 4: BeatmapInfo rowのbinary contract

**Objective:** Athenaの保守者として、beatmap info rowのfield順序とindex semanticsを固定したい。これにより、mode gradeの並び替えやrequest種別の誤判定を検出できる。

#### Acceptance Criteria

1. The Athena stable protocol contract shall `BeatmapInfo`を`s16 request_index`、`i32 beatmap_id`、`i32 beatmapset_id`、`i32 thread_id`、`i8 ranked`、4個のgrade、`BanchoString md5`の順序で表現する
2. The Athena stable protocol contract shall 4個のgradeを`osu`、`fruits`、`taiko`、`mania`の順序で表現する
3. When filename requestへのrowを表現するとき, the Athena stable protocol contract shall `request_index`を対応するfilename list内の0以上のindexとして表現する
4. When beatmap ID requestへのrowを表現するとき, the Athena stable protocol contract shall `request_index`を`-1`として表現する
5. When 有効な`BeatmapInfo` payloadをdecodeするとき, the Athena stable protocol contract shall identifiers、ranked status、4 mode grades、MD5をfield境界を変えずに復元する

### Requirement 5: BeatmapInfoReplyのbinary contract

**Objective:** Athenaの保守者として、複数rowを返すreply layoutを固定したい。これにより、count、row境界、reply順序を検証できる。

#### Acceptance Criteria

1. The Athena stable protocol contract shall `BeatmapInfoReply`を`i32 count`と、その直後に連続する`BeatmapInfo[count]`として表現する
2. When replyが複数rowを含むとき, the Athena stable protocol contract shall 宣言したcount、row順序、各rowのfield境界を保持する
3. When `count`が0のとき, the Athena stable protocol contract shall rowを含まないreply payloadとして表現する
4. When 有効な`BeatmapInfoReply` payloadをdecodeするとき, the Athena stable protocol contract shall 宣言された件数と同数のrowsを同じ順序で復元する

### Requirement 6: 独立golden fixtureによる検証

**Objective:** Athenaの保守者として、production encoderの自己一致ではない互換性証拠を持ちたい。これにより、encodeとdecodeが同じ誤ったlayoutを共有しても検出できる。

#### Acceptance Criteria

1. The Athena Stable Compatibility Evidence shall production encoderの出力を生成元にせず、確認済みprotocol layoutから独立に導出したfixed payload bytesをgolden fixtureとして保持する
2. When canonical request値をencodeするとき, the Athena compatibility verification shall request golden fixtureとbyte-for-byteで一致することを確認する
3. When request golden fixtureをdecodeするとき, the Athena compatibility verification shall canonical request値を復元することを確認する
4. When canonical reply値をencodeするとき, the Athena compatibility verification shall reply golden fixtureとbyte-for-byteで一致することを確認する
5. When reply golden fixtureをdecodeするとき, the Athena compatibility verification shall canonical reply値を復元することを確認する
6. The canonical request fixture shall filename requestとbeatmap ID requestを同じpayloadに含める
7. The canonical reply fixture shall 2 rows以上を含み、filename由来rowに0以上の`request_index`、ID由来rowに`-1`を設定する
8. The canonical reply fixture shall 少なくとも1 rowの4 mode grade fieldにfield間で異なる`StableGrade`を設定し、non-zeroのbeatmap ID / beatmapset ID / thread ID / ranked statusと32文字のhexadecimal MD5文字列を含める
9. When empty collection境界を検証するとき, the Athena compatibility verification shall canonical multi-entry fixtureとは分離した小さなboundary caseとして確認する

### Requirement 7: Fixture provenanceと証拠の更新方針

**Objective:** Athenaの保守者として、golden bytesの由来と適用可能なclient範囲を追跡したい。これにより、推測やrevision driftを互換性根拠として扱うことを防げる。

#### Acceptance Criteria

1. The Athena Stable Compatibility Evidence shall Lekuruu protocol documentationと複数の互換実装について、参照したrepositoryと固定revisionを記録する
2. The Athena Stable Compatibility Evidence shall field layoutを実際に確認できなかった参照実装を肯定的な根拠として扱わない
3. The Athena Stable Compatibility Evidence shall Target packet captureが未取得であることと、fixtureが現行client layout向けのreference-backed evidenceであることを明示する
4. When Target packet captureを入手したとき, the Athena compatibility review shall captureとfixtureを比較し、一致または差異を記録してからevidence statusを更新する
5. If Target packet captureがreference-backed fixtureと矛盾するとき, the Athena compatibility review shall 差異を黙って受け入れず、fixtureまたは対象client範囲を再評価する

### Requirement 8: Stable Compatibility Matrixの状態分離

**Objective:** Athenaの保守者として、struct fixtureの証拠状態とpacket runtimeの実装状態を別々に追跡したい。これにより、Issue #24で解消したblockerだけを正確に反映できる。

#### Acceptance Criteria

1. When canonical fixtureのencodeとdecode検証が成功したとき, the Stable Compatibility Matrix shall `StableGrade`、`BeatmapInfoRequest`、`BeatmapInfo`、`BeatmapInfoReply`を`Fixture-backed`として示す
2. When Issue #24を完了したとき, the Stable Compatibility Matrix shall C2S 68とS2C 69のruntime statusを`Missing`のまま保持する
3. When Issue #24を完了したとき, the Stable Compatibility Matrix shall beatmap infoのfixture blockerだけを解消済みとして示す
