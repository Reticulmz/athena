# Design Document

## Overview

本featureは、現行Target Stable Client向けのStableGrade、BeatmapInfoRequest、BeatmapInfo、BeatmapInfoReplyをtyped wire contractとして追加し、固定payload bytesとのencode / decode一致で互換性証拠を作る。

runtime packet flowは変更しない。C2S 68 handler、S2C 69 builder、metadata lookup、HTTP endpointは後続実装へ残し、本specはそれらが依存できるstructとfixture evidenceだけを所有する。

### Goals

- stable wire固有のgrade closed setをcore score gradeから分離する
- 現行4-Grade request / row / reply layoutをCaterpillar structで固定する
- production serializerから独立したcanonical request / reply bytesで双方向検証する
- Stable Compatibility Matrixのstruct evidenceとruntime statusを分離して更新する

### Non-Goals

- C2S 68 BEATMAP_INFO handlerまたはpayload validation policy
- S2C 69 BEATMAP_INFO_REPLY packet builderまたはruntime emission
- beatmap metadata / personal grade lookup
- /web/osu-getbeatmapinfo.php
- grade集計、score grade mapping、projection
- 旧1-Grade / 3-Grade client layout
- truncated、negative count、trailing bytes、unknown valueに対するpacket-level error translation

## Boundary Commitments

### This Spec Owns

- StableGradeの10個のwire値とcompatibility meaning
- 現行BeatmapInfoRequest、BeatmapInfo、BeatmapInfoReplyのfield型、field順序、list count contract
- canonical mixed request、2-row reply、empty collectionのgolden payload bytes
- fixed revision provenanceとTarget capture未取得状態の記録
- structをFixture-backedとしつつC2S 68 / S2C 69 runtimeをMissingに保つmatrix同期

### Out of Boundary

- handler、dispatcher registration、packet writer、runtime workflow
- repository、query service、Unit of Work、DB schema
- stable web legacy adapter
- canonical score gradeからStableGradeへのmapper
- client version negotiationとlegacy layout branch
- malformed packetの受理 / 拒否方針

### Allowed Dependencies

- domain/compatibility/stableはPython標準ライブラリだけに依存する
- C2S structはCaterpillarと既存BanchoStringに依存できる
- S2C structはCaterpillar、既存BanchoString、StableGradeに依存できる
- fixture testはproduction structとCaterpillar pack / unpackを呼び出せるが、golden bytesの生成にはproduction serializerを使わない
- evidence documentationはLekuruu wiki、固定revision実装、focused testsを参照できる

依存方向は domain compatibility <- stable protocol structs <- tests とする。protocol structからservice、repository、handler、web transportへのimportは禁止する。

### Revalidation Triggers

- Target Stable Client captureがgolden bytesと矛盾した場合
- Target client範囲を旧clientまたは別protocol versionへ拡張する場合
- Lekuruuの現行BeatmapInfo layoutまたはmode grade順序が変更された場合
- Caterpillarのstrict enum、dynamic array、nested struct array behaviorが変わる場合
- Stable Compatibility Matrixのstatus / blocker vocabularyが変更された場合
- 後続runtime実装がcount、index、grade field contractを変更しようとする場合

## Architecture

### Existing Architecture Analysis

- stable wire固有enumはdomain/compatibility/stable/<concept>.pyのIntEnumとして配置され、package rootからre-exportされる
- direction-specific payload definitionsはprotocol/c2s/とprotocol/s2c/に分離される
- Caterpillar 2.8.1はthis.count dynamic array、nested struct array、strict enum transformerを提供する
- test_presence_fixtures.pyとtest_stats_fixtures.pyは小さなgolden bytesをtest module内へ固定し、production outputとの一致を検証する
- C2S 68とS2C 69のpacket ID enumは存在するが、BeatmapInfo familyのstruct、handler、builderは存在しない

### Architecture Pattern & Boundary Map

~~~mermaid
graph LR
    StableGrade[StableGrade enum]
    Request[BeatmapInfoRequest struct]
    Info[BeatmapInfo row]
    Reply[BeatmapInfoReply struct]
    Fixture[Golden fixture verification]
    Matrix[Compatibility matrix]

    Info --> StableGrade
    Reply --> Info
    Fixture --> Request
    Fixture --> Reply
    Fixture --> StableGrade
    Fixture --> Matrix
~~~

- Selected pattern: direction-specific protocol structsとdomain compatibility enum
- Domain boundary: StableGradeだけをtransport-independent compatibility languageとしてdomainに置く
- Transport boundary: requestはC2S、row / replyはS2Cへ置き、runtime helperは追加しない
- Evidence boundary: test literalがbytes authority、Caterpillar structがproduction contract、matrixがcompletion statusを表す
- Existing patterns preserved: StableStatus family、Caterpillar cpstruct、inline golden fixture、direction-specific protocol package
- New dependencies: なし

### Technology Stack

| Layer | Choice / Version | Role in Feature | Notes |
| --- | --- | --- | --- |
| Domain compatibility | Python 3.14 IntEnum | StableGrade closed set | stdlib only |
| Stable protocol | caterpillar-py 2.8.1 | little-endian struct、dynamic array、strict enum | 既存dependency |
| Verification | pytest、Caterpillar pack / unpack | exact bytes encode / decode | golden bytesは固定literal |
| Documentation | Markdown | provenance、matrix status、boundary | runtime completionと分離 |

## File Structure Plan

### Directory Structure

~~~text
src/osu_server/
├── domain/compatibility/stable/
│   ├── grade.py
│   └── __init__.py
└── transports/stable/bancho/protocol/
    ├── c2s/
    │   ├── __init__.py
    │   └── beatmap_info.py
    └── s2c/
        └── beatmap_info.py

tests/unit/
├── domain/compatibility/stable/
│   └── test_stable_enums.py
└── transports/bancho/protocol/
    └── test_beatmap_info_fixtures.py

docs/
└── stable-compatibility-matrix.md

CONTEXT.md
~~~

### New Files

- src/osu_server/domain/compatibility/stable/grade.py: StableGradeCompatibilityEnumを定義する
- src/osu_server/transports/stable/bancho/protocol/c2s/beatmap_info.py: BeatmapInfoRequestWireStructを定義する
- src/osu_server/transports/stable/bancho/protocol/s2c/beatmap_info.py: BeatmapInfoRowReplyWireStructを定義する
- tests/unit/transports/bancho/protocol/test_beatmap_info_fixtures.py: BeatmapInfoGoldenFixtureVerificationを保持する

### Modified Files

- src/osu_server/domain/compatibility/stable/__init__.py: StableGradeをre-exportする
- src/osu_server/transports/stable/bancho/protocol/c2s/__init__.py: BeatmapInfoRequestを既存C2S package interfaceからre-exportする
- tests/unit/domain/compatibility/stable/test_stable_enums.py: StableGrade全memberを検証する
- docs/stable-compatibility-matrix.md: BeatmapInfoCompatibilityEvidenceDocsとしてstructとpacket blocker rowsを同期する
- CONTEXT.md: Stable Grade、Beatmap Info Struct Fixture、file placement、fixture namingを同期する
- .kiro/specs/beatmap-info-struct-fixtures/research.md: fixed revision evidenceとrevalidation policyを記録する
- .kiro/specs/beatmap-info-struct-fixtures/spec.json: design生成状態とrequirements承認状態を記録する

## System Flows

canonical fixtureは次のevidence flowだけを持つ。packet runtime flowは存在しない。

~~~mermaid
sequenceDiagram
    participant Literal as Fixed payload bytes
    participant Struct as Caterpillar structs
    participant Test as Fixture tests
    participant Matrix as Compatibility matrix

    Test->>Struct: Canonical valuesをencode
    Struct-->>Test: Payload bytes
    Test->>Literal: Byte exact comparison
    Test->>Struct: Fixed payload bytesをdecode
    Struct-->>Test: Typed values
    Test->>Matrix: Fixture backed evidence
~~~

## Requirements Traceability

| Requirement | Summary | Components | Interfaces | Flows |
| --- | --- | --- | --- | --- |
| 1.1, 1.2, 1.3, 1.4, 1.5 | 現行4-Grade scopeとruntime除外 | 全components、BeatmapInfoCompatibilityEvidenceDocs | Boundary Commitments | Evidence flow |
| 2.1, 2.2, 2.3, 2.4 | StableGrade closed set | StableGradeCompatibilityEnum、BeatmapInfoRowReplyWireStruct、BeatmapInfoGoldenFixtureVerification | StableGrade contract | Encode / decode |
| 3.1, 3.2, 3.3, 3.4, 3.5 | Mixed BeatmapInfoRequest contract | BeatmapInfoRequestWireStruct、BeatmapInfoGoldenFixtureVerification | Request field contract | Encode / decode |
| 4.1, 4.2, 4.3, 4.4, 4.5 | BeatmapInfo rowとindex semantics | BeatmapInfoRowReplyWireStruct、BeatmapInfoGoldenFixtureVerification | Row field contract | Encode / decode |
| 5.1, 5.2, 5.3, 5.4 | BeatmapInfoReply count / row contract | BeatmapInfoRowReplyWireStruct、BeatmapInfoGoldenFixtureVerification | Reply field contract | Encode / decode |
| 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9 | Independent canonical / empty fixtures | BeatmapInfoGoldenFixtureVerification | Fixture data contract | Evidence flow |
| 7.1, 7.2, 7.3, 7.4, 7.5 | Provenanceとcapture更新方針 | BeatmapInfoCompatibilityEvidenceDocs、BeatmapInfoGoldenFixtureVerification | Evidence provenance contract | Revalidation |
| 8.1, 8.2, 8.3 | Struct / runtime status分離 | BeatmapInfoCompatibilityEvidenceDocs | Matrix status contract | Evidence flow |

## Components and Interfaces

| Component | Domain / Layer | Intent | Requirement Coverage | Key Dependencies | Contract |
| --- | --- | --- | --- | --- | --- |
| StableGradeCompatibilityEnum | Domain compatibility | Stable grade bytesをclosed setとして表す | 2.1, 2.2, 2.3, 2.4 | Python IntEnum P0 | Value |
| BeatmapInfoRequestWireStruct | Stable C2S protocol | filename / ID mixed request layoutを表す | 3.1, 3.2, 3.3, 3.4, 3.5 | Caterpillar P0、BanchoString P0 | Wire |
| BeatmapInfoRowReplyWireStruct | Stable S2C protocol | rowとcounted reply layoutを表す | 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4 | StableGrade P0、Caterpillar P0、BanchoString P0 | Wire |
| BeatmapInfoGoldenFixtureVerification | Tests | fixed bytesで双方向contractを検証する | 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9 | Production types P0 | Verification |
| BeatmapInfoCompatibilityEvidenceDocs | Documentation | provenanceとmatrix状態を同期する | 1.1, 1.2, 1.3, 1.4, 1.5, 7.1, 7.2, 7.3, 7.4, 7.5, 8.1, 8.2, 8.3 | Focused tests P0、research log P1 | Evidence |

### Domain Compatibility

#### StableGradeCompatibilityEnum

| Field | Detail |
| --- | --- |
| Intent | stable client固有の1-byte grade classificationをcore score gradeから分離する |
| File | src/osu_server/domain/compatibility/stable/grade.py |
| Requirements | 2.1, 2.2, 2.3, 2.4 |

| Member | Wire value |
| --- | ---: |
| XH | 0 |
| SH | 1 |
| X | 2 |
| S | 3 |
| A | 4 |
| B | 5 |
| C | 6 |
| D | 7 |
| F | 8 |
| N | 9 |

Responsibilities and constraints:

- classはIntEnumとし、追加aliasやdefault memberを持たない
- canonical score Gradeをimportせず、score計算 / projection behaviorを持たない
- public class docstringは日本語Google Styleでwire meaningとcore gradeとの境界を記述する

Dependencies:

- Inbound: BeatmapInfoRowReplyWireStructがgrade field型として使用する P0
- Outbound: Python stdlib enum.IntEnum P0

### Stable C2S Protocol

#### BeatmapInfoRequestWireStruct

| Order | Field | Python type | Caterpillar field | Invariant |
| ---: | --- | --- | --- | --- |
| 1 | filename_count | int | signed int32 | len(filenames)と一致する |
| 2 | filenames | list[str] | BanchoString[filename_count] | 入力順序を保持する |
| 3 | id_count | int | signed int32 | len(beatmap_ids)と一致する |
| 4 | beatmap_ids | list[int] | int32[id_count] | 入力順序を保持する |

Responsibilities and constraints:

- little-endian Caterpillar structとしてfield順序を固定する
- BeatmapInfoRequestはprotocol.c2s package rootからre-exportし、既存C2S import patternを維持する
- countを隠すbuilderやpacket-level parserを追加しない
- struct docstringは日本語Google Styleでcount invariant、pack / unpack error条件、制約を記述する
- negative count、trailing bytes、maximum count policyは定義しない

Dependencies:

- Outbound: Caterpillar LittleEndian、this、int32 P0
- Outbound: existing BanchoString P0

### Stable S2C Protocol

#### BeatmapInfoRowReplyWireStruct

BeatmapInfo wire contract:

| Order | Field | Python type | Caterpillar field | Meaning |
| ---: | --- | --- | --- | --- |
| 1 | request_index | int | signed int16 | filename list index、ID requestなら-1 |
| 2 | beatmap_id | int | signed int32 | beatmap identifier |
| 3 | beatmapset_id | int | signed int32 | beatmapset identifier |
| 4 | thread_id | int | signed int32 | forum thread identifier |
| 5 | ranked | int | signed int8 | beatmap info submission status |
| 6 | osu_grade | StableGrade | strict enum over uint8 | osu grade |
| 7 | fruits_grade | StableGrade | strict enum over uint8 | fruits grade |
| 8 | taiko_grade | StableGrade | strict enum over uint8 | taiko grade |
| 9 | mania_grade | StableGrade | strict enum over uint8 | mania grade |
| 10 | md5 | str | BanchoString | beatmap checksum |

BeatmapInfoReply wire contract:

| Order | Field | Python type | Caterpillar field | Invariant |
| ---: | --- | --- | --- | --- |
| 1 | count | int | signed int32 | len(beatmaps)と一致する |
| 2 | beatmaps | list[BeatmapInfo] | BeatmapInfo[count] | row順序を保持する |

Responsibilities and constraints:

- StableGrade fieldはstrict enum decodeを使い、0から9以外をcompatibility memberとして受理しない
- structはindex semanticsを保持するが、filename / ID lookupやindex妥当性検証を行わない
- md5はwire stringとして保持し、production structでは32文字hex validationを追加しない
- packet headerやS2C 69 writer functionを追加しない
- public struct docstringは日本語Google Styleで全field、例外、制約を記述する

Dependencies:

- Outbound: StableGradeCompatibilityEnum P0
- Outbound: Caterpillar primitive、strict enum、nested array P0
- Outbound: existing BanchoString P0

### Verification

#### BeatmapInfoGoldenFixtureVerification

Canonical request data:

- filenames = alpha.osu, beta.osu
- beatmap_ids = 12345, 67890
- filename countとID countを同じpayload内に置き、各listの順序を検証する

Canonical reply data:

| Row | request index | beatmap id | set id | thread id | ranked | osu | fruits | taiko | mania | md5 |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- |
| Filename row | 1 | 12345 | 23456 | 34567 | 2 | XH | S | B | N | 0123456789abcdef0123456789abcdef |
| ID row | -1 | 67890 | 78901 | 89012 | 1 | SH | A | C | F | fedcba9876543210fedcba9876543210 |

Verification contract:

- requestとreplyのgolden bytesはfield segmentごとのfixed literalとして記述し、pack、builder、fixture generation scriptから生成しない
- encode testはcanonical typed valueのpack結果とliteralをbyte-for-byte比較する
- decode testはliteralをunpackし、count、list順序、index、identifiers、ranked、4 grades、md5を完全一致で比較する
- request empty caseは8 zero bytes、reply empty caseは4 zero bytesとしてcanonical multi-entry testsから分離する
- test module docstringとコメントは日本語でprovenanceとproduction encoder非依存を明記する
- manual struct.unpackはtest evidenceの補助に限り、production packageへ追加しない

Dependencies:

- Inbound: fixed revision evidence P0
- Outbound: production structs P0
- Outbound: pytest P0

### Documentation Evidence

#### BeatmapInfoCompatibilityEvidenceDocs

Files:

- .kiro/specs/beatmap-info-struct-fixtures/research.md
- CONTEXT.md
- docs/stable-compatibility-matrix.md

Matrix update contract:

- Grade rowをAthena canonical name StableGradeとしてFixture-backedへ更新し、external source名Gradeとの対応をnoteに残す
- BeatmapInfo、BeatmapInfoRequest、BeatmapInfoReply rowsをFixture-backedへ更新し、production struct path、focused test path、verification=unit,fixture、fixture blocker=noneを記録する
- C2S 68 rowはstatus=Missingのまま、payload struct / fixture evidenceを追加し、handler missingを残してfixture blockerだけをnoneへ変更する
- S2C 69 rowはstatus=Missingのまま、payload struct / fixture evidenceを追加し、builder / runtime missingを残してfixture blockerだけをnoneへ変更する
- #17 Fixture Extraction Blocker RollupからC2S 68、S2C 69、StableGrade、BeatmapInfo familyの解消済みfixture rowsを除去する
- matrix内の同一概念の全出現を確認し、audit row、inventory row、rollup間でstatusを矛盾させない

Provenance contract:

- research.mdにLekuruu wikiと全調査repositoryの固定revisionを記録する
- positive evidenceと実装を確認できなかったsourceを区別する
- Target capture未取得とcurrent-only layoutを明示する
- capture入手時にfixture comparisonを行うrevalidation policyを維持する

## Data Models

### Domain Model

StableGradeはstable compatibility value objectとして扱う。aggregate、persistence、domain eventは追加しない。

### Wire Data Model

~~~text
BeatmapInfoRequest
├── filename_count
├── filenames
├── id_count
└── beatmap_ids

BeatmapInfoReply
├── count
└── beatmaps
    └── BeatmapInfo
        ├── request_index
        ├── beatmap_id
        ├── beatmapset_id
        ├── thread_id
        ├── ranked
        ├── osu_grade
        ├── fruits_grade
        ├── taiko_grade
        ├── mania_grade
        └── md5
~~~

Invariantsはwire countとcollection length、field順序、strict grade closed setに限定する。metadata存在性、MD5内容、request index参照先の妥当性はruntime workflowの責務である。

## Error Handling

- struct constructionまたはpackでprimitive範囲を超えた場合はCaterpillar errorをそのまま送出する
- strict StableGrade decodeで0から9以外を読んだ場合はCaterpillar validation errorとする
- truncated payload、negative count、trailing bytes、count abuseをPacketReadErrorへ変換する責務は後続C2S parserに残す
- fixture testは正常系contractとempty boundaryだけを検証し、Issue #15のmalformed behaviorを先取りしない
- runtime componentを追加しないためlogging、metrics、health checkの変更はない

## Testing Strategy

### Unit Tests

- StableGradeの全10 memberについてnameとwire valueの完全一致を検証する
- mixed BeatmapInfoRequestのencode結果が独立golden bytesと一致し、decodeで2 filenames / 2 IDsと順序を復元する
- 2-row BeatmapInfoReplyのencode結果が独立golden bytesと一致し、decodeでfilename index 1とID index -1を区別する
- 各reply rowの4 gradeが指定mode順で復元され、field swapを検出できることを検証する
- request empty caseとreply empty caseを別testとして検証する

### Documentation Validation

- matrixの4 struct rowsがFixture-backedでfocused test pathを参照することを確認する
- C2S 68 / S2C 69がMissingかつfixture blocker=noneであることを確認する
- #17 rollupから解消済みbeatmap info fixture entriesが除去されていることを確認する
- git diff --checkでMarkdown formattingを検証する

### Quality Gates

- focused pytest: stable enum testとbeatmap info fixture test
- Ruff format / lint: 変更Python files
- basedpyright strict: 変更Python filesを含むproject check
- import-linter: domain compatibilityとtransport dependency方向
- implementation完了時は./scripts/ci.sh qualityと./scripts/ci.sh testを実行する

Integration / E2E testはruntime packet pathを追加しないため本specでは作成しない。

## Supporting References

詳細なsource比較、fixed revisions、count signedness差、Target capture policyは[research.md](research.md)を参照する。
