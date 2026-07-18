# Research & Design Decisions

## Summary

- **Feature**: `beatmap-info-struct-fixtures`
- **Discovery Scope**: Extension
- **Key Findings**:
  - 現行Athenaはstable固有enumを`domain/compatibility/stable/`へ分離し、Caterpillar 2.8.1のdirection-specific protocol structとインラインgolden bytesを使う既存パターンを持つ
  - Lekuruu wikiの現行4-Grade layoutと、`chio.py` / Titanic `anchor` / Akatsuki旧serializerのfield順序が一致する
  - Target Stable Client captureは未取得だが、複数の固定revisionからproduction serializerと独立した正常系payload bytesを導出できる

## Research Log

### Athenaのextension pointと既存fixture pattern

- **Context**: 新しいwire struct、stable enum、golden fixtureの配置と依存方向を既存アーキテクチャへ合わせる必要がある
- **Sources Consulted**:
  - `src/osu_server/domain/compatibility/stable/status.py`
  - `src/osu_server/domain/compatibility/stable/mode.py`
  - `src/osu_server/domain/compatibility/stable/presence_filter.py`
  - `src/osu_server/transports/stable/bancho/protocol/types.py`
  - `src/osu_server/transports/stable/bancho/protocol/c2s/presence.py`
  - `tests/unit/domain/compatibility/stable/test_stable_enums.py`
  - `tests/unit/transports/bancho/protocol/test_presence_fixtures.py`
  - `tests/unit/transports/bancho/protocol/test_stats_fixtures.py`
  - `pyproject.toml`
- **Findings**:
  - Stable wire固有enumはstdlib `IntEnum`としてdomain compatibility packageに配置され、transportから参照される
  - C2S payload structは`protocol/c2s/`、S2C payload structは`protocol/s2c/`に置くdirection-specific patternが確立している
  - Caterpillar 2.8.1は`this.count`によるdynamic array、nested struct array、strict enum transformerを提供する。ローカルprototypeで`BanchoString[this.filename_count]`、`BeatmapInfo[this.count]`、strict `StableGrade` encode / decodeが動作することを確認した
  - 既存golden fixtureはtest module内の固定bytes literalと独立decoderでfield境界を可視化している。本specではCaterpillar `pack` / `unpack`を固定bytesと双方向比較する
  - 新規dependency、DB migration、runtime composition変更は不要である
- **Implications**:
  - `StableGrade`は新しいdomain compatibility enumとし、request / reply structは方向別moduleに分ける
  - 汎用serializer、repository、service、handlerは追加しない

### Primary protocol layout

- **Context**: BeatmapInfo familyのfield順序、count型、grade順序、request index semanticsを推測せず確定する必要がある
- **Sources Consulted**:
  - Lekuruu `bancho-documentation` wiki revision `7c177543497beacf443b6fecd3f52045c6cf1c5c`
  - `Types/Grade.md`
  - `Types/BeatmapInfoRequest.md`
  - `Types/BeatmapInfo.md`
  - `Types/BeatmapInfoReply.md`
  - `Packets/Client/68 BeatmapInfo.md`
  - `Packets/Server/69 BeatmapInfoReply.md`
- **Findings**:
  - `StableGrade` wire値は`XH=0, SH=1, X=2, S=3, A=4, B=5, C=6, D=7, F=8, N=9`である
  - 現行requestは`sInt filename_count`, `String[filename_count]`, `sInt id_count`, `sInt[id_count]`である
  - 現行rowは`sShort request_index`, 3個の`sInt` identifier, 1-byte ranked status, `osu`, `fruits`, `taiko`, `mania`の4 grades, `String md5`である
  - filename requestへのrowはfilename list内indexを持ち、beatmap ID requestへのrowは`request_index=-1`を持つ
  - replyは`sInt count`と`BeatmapInfo[count]`である
  - wikiは旧client layoutの履歴も記録しているが、本specは現行4-Grade layoutだけを採用する
- **Implications**:
  - countとidentifierはsigned 32-bit、request indexはsigned 16-bit、rankedはsigned 8-bitとしてmodel化する
  - grade fieldはfield順序の入れ替わりを検出できるよう、canonical fixtureで相互に異なる値を使う
  - 旧1-Grade / 3-Grade layout向けversion branchは作らない

### Fixed-revision compatibility implementations

- **Context**: Primary documentationだけでなく、実際にbinary flowを実装した互換serverで現行layoutとindex semanticsをcross-checkする必要がある
- **Sources Consulted**:
  - `Lekuruu/chio.py@9d2391a5b2d3610d72e2e794d0749a00329286c1` (1.1.20)
  - `osuAkatsuki/bancho.py@0651b54c66daa839c1bb3998e4f9a8d1173e144d`
  - `osuripple/lets@98e9e07faa48398fbccf17251650011e36bdf6e4`
  - `osuripple/pep.py@9754e583ca1688ad33d2eaf695f128c3d3d31068`
  - `osuTitanic/titanic@215bb180bcb00d6345639f88a283b041c314d938`
  - Titanic submodule `osuTitanic/anchor@b19d14ccdcdf157026c257586faf49bf4542971e`
  - Titanic submodule `osuTitanic/deck@a81d697cbc2d65524829f2e9a903bf0f55684322`
- **Findings**:
  - `chio.py`とTitanic `anchor`はBeatmapInfo request / replyのbinary flowを実装し、wikiと同じfield順序を使う
  - ID request rowの`request_index=-1`はTitanic flowで確認できる
  - Akatsukiの現行flowではBeatmapInfo packet処理が廃止されているが、残存する旧serializerは同じrow field順序を示す
  - Titanic `deck`はHTTP beatmap infoのindex semanticsを補強するが、HTTP grade順序はbinary layoutと異なるためbinary serializerの根拠には使わない
  - Ripple `lets`と`pep.py`ではBeatmapInfo binary実装を確認できず、肯定的なlayout evidenceには採用しない
  - `chio.py`はcountをunsigned 32-bitとして読む箇所がある一方、primary wikiはsigned `sInt`を指定する。正常な非負countのwire bytesは同一である
- **Implications**:
  - 型の意味はprimary wikiに従ってsigned 32-bitとし、canonical fixtureでは非負countだけを使う
  - negative countやtruncated payloadのruntime policyはIssue #15へ残す
  - sourceを確認できなかった実装名をprovenanceの肯定材料として列挙しない

### Target packet captureの扱い

- **Context**: 実client captureがない状態でfixtureを確定できるか判断する必要がある
- **Sources Consulted**:
  - Requirements reviewで確定した現行Target Stable Client限定方針
  - 上記primary documentationと固定revision実装
- **Findings**:
  - Target packet captureは現時点で未取得である
  - primary documentationと複数のbinary implementationは現行正常系layoutについて一致している
  - Athena自身のencoder outputをgolden生成元にしなければ、reference-backed fixtureとして自己一致を避けられる
- **Implications**:
  - capture未取得を明示したうえで実装を進める
  - capture入手時はfixtureと比較し、矛盾があればfixtureまたはTarget client範囲を再評価する

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Decision |
| --- | --- | --- | --- | --- |
| Direction-specific structs | RequestをC2S、row / replyをS2C moduleに配置 | Transport familyの依存方向とpacket directionが明確 | 同じfeature名のmoduleが2つになる | 採用 |
| Shared `protocol/types.py` | 3 structを共通types moduleに集約 | import先が1か所 | C2S専用 / S2C専用型までshared ownershipにする | 不採用 |
| Runtime parser / builder同時実装 | structとhandler用helperを同じspecで追加 | 次Issueの作業量が減る | runtime、error policy、metadata lookupへscopeが拡大する | 不採用 |
| Inline golden bytes | 小さなpayloadをtest module内のliteralで保持 | field境界をreviewしやすく既存patternと一致 | 長大payloadには向かない | 採用 |
| Binary fixture files | `.bin`としてpayloadを保持 | 大きなpayloadに適する | 小さなfixtureの由来とfield境界が見えにくい | 不採用 |

## Design Decisions

### Decision: StableGradeをstrict compatibility enumとしてmodel化する

- **Context**: Grade bytesをcanonical score gradeやfree-form integerと混同できない型境界が必要である
- **Alternatives Considered**:
  1. `int` fieldとして保持する
  2. core score `Grade`を直接使う
  3. `StableGrade`を独立`IntEnum`として使う
- **Selected Approach**: `StableGrade`をdomain compatibility packageへ追加し、wire fieldはCaterpillar strict enum transformerと`uint8`でencode / decodeする
- **Rationale**: `F`と`N`を含むstable closed setを正確に表し、core scoring meaningとの境界を保てる
- **Trade-offs**: 未知grade byteはstruct decode errorになるが、そのruntime error translationは本specでは定義しない
- **Follow-up**: score grade mappingが必要になった時点で別のcompatibility mapperを設計する

### Decision: Explicit countを持つdirection-specific cpstructを採用する

- **Context**: 外部wire contractのcount fieldとlist順序をそのままfixtureで検証する必要がある
- **Alternatives Considered**:
  1. countを隠すconvenience builderだけを公開する
  2. request / replyを1つのshared moduleへ置く
  3. countをfieldとして持つC2S / S2C structを分離する
- **Selected Approach**: `BeatmapInfoRequest`、`BeatmapInfo`、`BeatmapInfoReply`をdirection-specific Caterpillar structとして定義し、countとlistを明示する
- **Rationale**: fixtureがwire fieldそのものを検証でき、runtime helperを先行設計せずに済む
- **Trade-offs**: 呼び出し側はcountとlist長の整合を保つ必要がある。runtime validationは後続Issueの責務とする
- **Follow-up**: C2S 68 handler / S2C 69 builder設計時に、structを包むtyped helperの要否を再評価する

### Decision: Reference-backed exact bytesをfixture authorityとする

- **Context**: Athena encoderのround-tripだけでは同一layout bugを検出できない
- **Alternatives Considered**:
  1. `pack`結果をsnapshotとして生成する
  2. Target capture取得まで実装を停止する
  3. 固定revision evidenceから手動導出したbytesを保持する
- **Selected Approach**: field単位で独立導出したbytes literalをauthorityとし、Caterpillar `pack`と`unpack`の両方向を比較する
- **Rationale**: 自己一致を避けつつ、確認済み現行layoutの実装を進められる
- **Trade-offs**: capture由来fixtureよりevidence strengthは低い
- **Follow-up**: Target capture入手時に一致確認またはfixture置換を行う

## Design Synthesis

- **Generalization**: Stable wire closed setは既存`StableStatus` / `StableMode`と同じdomain compatibility enum patternを再利用する。汎用enum registryや汎用counted-list abstractionは追加しない
- **Build vs. Adopt**: Dynamic array、nested struct、strict enumはCaterpillar 2.8.1を採用し、custom binary serializerは作らない
- **Simplification**: enum、3 struct、focused fixture test、matrix同期だけに限定し、handler、builder、metadata service、HTTP adapter、legacy layout branchを除外する

## Risks & Mitigations

- Target captureがreference-backed bytesと矛盾するリスク: captureをrevalidation triggerとし、差異を明示してTarget範囲を再評価する
- 4 mode grade field順序を誤るリスク: 少なくとも1 rowで4 fieldに相互に異なるgrade値を設定する
- signed / unsigned count表記差のリスク: primary wikiのsigned `sInt`を採用し、fixtureは両表現で同一になる非負値に限定する
- Matrixがruntime完成と誤読されるリスク: structを`Fixture-backed`へ更新してもC2S 68 / S2C 69を`Missing`のまま保持し、fixture blockerだけを除去する
- Caterpillar typing driftのリスク: focused pytestとbasedpyrightでstrict enum / nested array contractを検証する

## References

- Lekuruu `bancho-documentation` wiki revision `7c177543497beacf443b6fecd3f52045c6cf1c5c`
- [Lekuruu/chio.py@9d2391a](https://github.com/Lekuruu/chio.py/commit/9d2391a5b2d3610d72e2e794d0749a00329286c1)
- [osuAkatsuki/bancho.py@0651b54](https://github.com/osuAkatsuki/bancho.py/commit/0651b54c66daa839c1bb3998e4f9a8d1173e144d)
- [osuripple/lets@98e9e07](https://github.com/osuripple/lets/commit/98e9e07faa48398fbccf17251650011e36bdf6e4)
- [osuripple/pep.py@9754e58](https://github.com/osuripple/pep.py/commit/9754e583ca1688ad33d2eaf695f128c3d3d31068)
- [osuTitanic/titanic@215bb18](https://github.com/osuTitanic/titanic/commit/215bb180bcb00d6345639f88a283b041c314d938)
- [osuTitanic/anchor@b19d14c](https://github.com/osuTitanic/anchor/commit/b19d14ccdcdf157026c257586faf49bf4542971e)
- [osuTitanic/deck@a81d697](https://github.com/osuTitanic/deck/commit/a81d697cbc2d65524829f2e9a903bf0f55684322)
- `docs/stable-compatibility-guide.md` Bancho Struct Field Reference / Beatmap Info Packet Flow
- `docs/stable-compatibility-matrix.md` C2S 68 / S2C 69 / Grade / BeatmapInfo family rows
