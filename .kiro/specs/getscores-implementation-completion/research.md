# Research & Design Decisions

## Summary

- **Feature**: `getscores-implementation-completion`
- **Discovery Scope**: 既存modern getscores実装をcompletion evidenceで固定するためのlight discovery
- **Key Findings**:
  - `/web/osu-osz2-getscores.php` はauth failure、unavailable、update available、header-only、Personal Best + leaderboard rowsの主要branchを既に実装している。
  - Global、Local、Selected Mods、Friends、Country、song select、unsupported selection、malformed optional fieldも既存testで広く検証されている。
  - 現在のevidenceはstatus別body fixture、integration test、live probe caseへ分散しており、HTTP status、headers、body bytes、末尾newlineを一体で表すcompletion contractがない。
  - 既存status別text fixtureの末尾newlineはruntime short bodyと一致しない。completion fixtureは既存fixtureを無条件に再利用せず、distinct wire shapeごとのexact bytesとして新設する必要がある。
  - Repository text hookはEOF newlineをnormalizeするため、raw body fileではshort bodyのno-LFとheader-onlyの複数terminal LFを保存できない。Canonical Base64 textから復元したbytesをcompatibility contractにする必要がある。
  - Getscores status mappingは確定している一方、beatmap info側はofficial fixtureでRanked=`1`のみ確認済みで、他statusの数値は未確認である。
  - Target Stable Client trafficによる最終確認はIssue #27 / #28が所有する。Issue #12はAthena-owned behaviorのimplementation completionを扱う。

## Research Log

### Existing runtime and evidence integration points

- **Context**: Design生成前に、runtime、fixture、verification CLI、documentationの責務境界を確認した。
- **Sources Consulted**:
  - `src/osu_server/transports/stable/web_legacy/getscores.py`
  - `src/osu_server/transports/stable/web_legacy/mappers/getscores.py`
  - `src/osu_server/domain/compatibility/stable/getscores.py`
  - `src/athena_cli/stable_verification/getscores.py`
  - `src/athena_cli/stable_verification/models.py`
  - `tests/integration/test_getscores_endpoint.py`
  - `tests/integration/test_getscores_unavailable_paths.py`
  - `tests/integration/test_getscores_status_fixtures.py`
  - `tests/integration/test_getscores_diagnostics.py`
- **Findings**:
  - `StableGetscoresExchange.respond` がauth、parse、resolve、warmup、wire formattingを順に調整する。
  - Formatterはshort bodyを末尾newlineなしで返し、header responseはPersonal Bestとrowsが空でも末尾に空行を保持する。
  - `GetscoresVerifier` は既存body fixtureとlive `probe_cases.json` を検証するが、completion manifestのschema validationは持たない。
  - `GetscoresVerifier` の直接利用者はCLI dev commandとunit testに限定され、拡張のblast radiusは低い。GitNexus indexは715 commits staleだったため、Serena reference searchでも利用箇所を再確認した。
- **Implications**:
  - Runtime behaviorを新しいsource of truthへ移さず、existing endpointをexact fixtureに照合する。
  - Completion manifestのtyped loaderとvalidatorをstable verification境界へ追加する。
  - Live target probe catalogとcompletion branch catalogは別artifactにする。

### Distinct wire shape and newline contract

- **Context**: Requirement 2はcategory別ではなくclient-observable wire shape別のexact fixtureを要求する。
- **Sources Consulted**:
  - `tests/fixtures/web_legacy/getscores/*.txt`
  - `format_getscores_unavailable_response`
  - `format_getscores_update_available_response`
  - `format_getscores_header_response`
  - Existing formatter and integration tests
- **Findings**:
  - Auth failureはHTTP 401 + empty bodyで、text media typeを付与しない。
  - Unavailableはexact bytes `-1|false`、update availableはexact bytes `1|false`で、いずれも末尾LFを持たない。
  - Header-only responseはheader grammarを維持し、Personal Best lineとscore row sectionが空のため末尾の空行を保持する。
  - Personal Bestはleaderboard row countに含まれず、header countはscore rowsだけを数える。
  - Existing status fixtureはstatus mapping検証には有効だが、一部short body fixtureが末尾LFを持つためruntime exact fixtureとしては使えない。
- **Implications**:
  - `response_shapes.json` はauth failure、unavailable、update available、header-only、Personal Best + leaderboard rowsの5 shapeを定義する。
  - Body bytesはshape専用のcanonical Base64 fixtureから復元し、manifestはencoding、HTTP status、relevant header subset、newline contract、row/PB semanticsを持つ。
  - Approved status `3`はcrosswalkとexisting mapper testで固定する。Distinct wire shapeではないため専用body fixtureは追加しない。

### Branch catalog versus live probe cases

- **Context**: Existing `probe_cases.json` はtarget probe用で、Athena runtime branchの全条件を表すcompletion catalogではない。
- **Sources Consulted**:
  - `tests/fixtures/stable_compatibility/getscores/probe_cases.json`
  - Getscores parser、category mapper、diagnostic tests
  - Existing integration tests for Local、Selected Mods、Friends、Country、song select
- **Findings**:
  - `probe_cases.json` は実際のquery shapeを組み立てるためchecksum、filename、mode、modsなどを保持する。
  - Completion catalogにはGlobal、Local、Selected Mods、Friends、Country、song select、unsupported leaderboard type、missing identity、invalid checksum、malformed optional fieldsが必要である。
  - Stable raw selectorのLocalはdomain Global categoryへmapされるため、catalogではrequest selectorとexpected domain categoryを分離しないと意味が曖昧になる。
  - Raw credentials、raw username、captured raw query valuesはcompletion evidenceへ保存してはならない。
- **Implications**:
  - `branch_cases.json` はsymbolic request profile、seed scenario、request selector、expected domain category、expected shape id、warning categories、provisional flagだけを持つ。
  - Synthetic malformed valuesはtest builderがruntimeに生成し、fixtureには保存しない。
  - Categoryごとのbody copyは作らず、全caseを5つのshape idへ外部参照させる。

### Stable Beatmap Status Crosswalk

- **Context**: Getscoresとbeatmap infoはcanonical statusを共有するが、endpoint固有wire mappingを共有してはならない。
- **Sources Consulted**:
  - `src/osu_server/domain/beatmaps/models.py` `BeatmapRankStatus`
  - `src/osu_server/transports/stable/web_legacy/mappers/getscores.py`
  - `tests/unit/transports/web_legacy/test_getscores_status_mapper.py`
  - `.kiro/specs/beatmap-info-endpoint/research.md`
  - `.kiro/specs/beatmap-info-endpoint/design.md`
- **Findings**:
  - Getscores mappingはPending/WIP/Graveyard=`0`、Ranked=`2`、Approved=`3`、Qualified=`4`、Loved=`5`である。
  - NotSubmittedとUnknownはheader statusを持たず、unavailable responseへmapされる。
  - Local override適用後のeffective canonical statusがmapper入力になる。
  - Beatmap info official response fixtureではRanked=`1`が確認済みである。
  - Beatmap infoのApproved、Loved、Qualified、Pending-like valuesは現時点で未確認であり、数値を推測できない。
- **Implications**:
  - `beatmap_status_crosswalk.json` は全`BeatmapRankStatus`を列挙し、getscores representationとbeatmap info representationを別objectで保持する。
  - Beatmap info側は`confirmed`、`unsupported`、`unconfirmed`を区別し、未確認値を`null`にする。
  - Validatorはgetscores mappingとruntime mapperの一致をtestできるが、shared numeric mapperは導入しない。

### Existing test coverage and completion gaps

- **Context**: New designが既存testを重複させず、missing evidenceだけを補うか確認した。
- **Sources Consulted**:
  - All getscores unit and integration tests
  - `tests/fixtures/web_legacy/getscores/`
- **Findings**:
  - Auth failure、unavailable、update available、category scope、PB/rows、top-50 behavior、status mapping、malformed warning、song selectは既に個別testを持つ。
  - Missing componentは個別branch実装ではなく、manifest schema、shape-to-case foreign key、exact runtime-to-body comparison、docs status synchronizationである。
  - Metadata preparationまたはwarmup失敗がselected responseを変えないcontractは既存exchange testをcompletion fixtureと結び付けて明示する必要がある。
  - Existing stable verifierは正常なscore rowsをstaleな`KNOWN_GAP`として扱っており、completion後は`PASS`へ更新する必要がある。
  - Existing parse-only invariance testは`mods`、`s`、`v`も不変fieldとして扱うが、これらはselectionを変え得る。Catalog導入時に本当にparse-onlyなfieldだけへ限定する必要がある。
- **Implications**:
  - Existing integration filesをruntime contractの所有者として拡張し、重いseed setupを新規test fileへ複製しない。
  - Manifest schema、secret policy、cross-reference validationは新しいfocused unit testへ置く。
  - Completion validationはexisting test suiteを置換せず、fixtureとの結合を追加する。

### Documentation state

- **Context**: Guide / Matrixが現行runtimeと一致しているか確認した。
- **Sources Consulted**:
  - `docs/stable-compatibility-guide.md`
  - `docs/stable-compatibility-matrix.md`
- **Findings**:
  - Matrixはmodern getscoresを`Partial`とし、complete leaderboard projectionsをmissing implementationとして扱うstale記述を含む。
  - Guideのfixture backlogはbranch fixtureとreal-client probeを同じ未完了群として記録している。
  - Current implementation、missing completion evidence、missing target traffic evidenceを分離する必要がある。
- **Implications**:
  - Validation完了後、Matrixはmodern getscoresを`Implemented`として記録する。
  - Guide / MatrixはTarget Stable Client traffic gapをIssue #27 / #28へ明示的に引き継ぐ。
  - `Implemented`はFull Stable Compatibilityまたはtarget-confirmedを意味しないと明記する。

### Toolchain and dependency impact

- **Context**: Implementation tasksにenvironment変更が必要か確認した。
- **Findings**:
  - JSON、dataclass、enum、path handling、pytestで実装可能である。
  - DB schema、migration、Valkey、taskiq、external libraryは不要である。
  - `pyproject.toml`、`uv.lock`、Nix、CI configurationを変更する理由はない。
- **Implications**:
  - New dependencyやproject-wide config changeを禁止する。
  - Relevant unit/integration testsとproject quality/test gatesだけを使用する。

### Evidence authority

| Priority | Evidence | Use |
| --- | --- | --- |
| 1 | Target Stable Client traffic | Target clientが実際に送受信するcontract |
| 2 | Official client-observable fixture | Exact response body / field evidence |
| 3 | Protocol documentation | Field meaning、wire grammar、packet / endpoint contract |
| 4 | Multiple reference implementations in agreement | Cross-implementation consensus |
| 5 | Single reference implementation | Supporting evidence with lower authority |
| 6 | Athena deterministic behavior and focused tests | Provisional Athena regression contract |

Official fixtureとreference implementationが矛盾する場合はofficial fixtureを優先する。Athena deterministic behaviorだけを根拠にtarget未確認のwire contractを変更しない。

## Evidence Authority Decision Log

### 判定基準と記録範囲

- Task 4.1ではTarget Stable Client trafficを新規取得していない。未解決のtraffic evidenceはIssue #27 / #28が所有する。
- 判定順はTarget Stable Client traffic、official client-observable fixture、protocol documentation、複数reference implementationの一致、単一reference implementation、Athena deterministic behaviorの順とする。
- ここでのAthena fixture、focused test、verifier結果は実装regressionを検出するための証跡であり、Target Stable Client trafficの代替またはtarget-confirmed contractではない。

| 対象 | sourceと優先度 | precedence decision | correction / no-correction | 未解決gap |
| --- | --- | --- | --- | --- |
| Formatterのexact row / sanitization | `tests/unit/transports/web_legacy/test_getscores_formatter.py`、completion response fixture、Task 2.1のruntime comparison。Athena deterministic behavior (優先度6)。 | 上位のtraffic、official fixture、protocol documentation、reference consensus、single referenceとの矛盾は今回の証跡内で確認されなかった。 | **no-correction**。formatter出力はcanonical `header_with_rows` fixtureにbyte-for-byteで一致し、Task 4.1でruntimeは変更しない。 | Target Stable Client trafficによる最終確認は未取得で、Issue #27 / #28へ残る。 |
| Auth / unavailable / update / failure-invariance | `tests/integration/test_getscores_unavailable_paths.py`、completion short-response fixture、Task 2.2のruntime comparison。Athena deterministic behavior (優先度6)。 | 上位根拠とのconfirmed contradictionは見つからず、選択済みshort responseがwarmup / metadata failureで変化しないことだけをAthena-owned contractとして確認した。 | **no-correction**。Task 4.1でshort response branchを変更しない。 | Target Stable Client trafficによるstatus、header、bodyの最終確認は未取得で、Issue #27 / #28へ残る。 |
| Leaderboard selection | `tests/integration/test_getscores_endpoint.py`、`branch_cases.json`、Task 2.3のcatalog-driven comparison。Athena deterministic behavior (優先度6)。 | Global / Local / Selected Mods / Friends / Country / song select / unsupported selectionについて、上位根拠とのconfirmed contradictionは見つからなかった。 | **no-correction**。selection、projection、RX / APを変更しない。 | Target Stable Client trafficによるselectionの最終確認は未取得で、Issue #27 / #28へ残る。 |
| Malformed `a` | Task 2.4のImplementation Notes、commit `bdbfb8f3`、`src/osu_server/transports/stable/web_legacy/mappers/getscores.py`、`tests/unit/transports/web_legacy/test_getscores_query_parser.py`、`tests/integration/test_getscores_diagnostics.py`。Athena deterministic behavior (優先度6)。 | `a`はinteger-backed booleanとして解析し、non-integerは`INVALID_ANTI_CHEAT_SIGNAL`とfalse fallbackにする既存のone-branch correctionを記録する。これはtarget confirmationではなく、将来の上位evidenceが矛盾した場合はそちらを優先するprovisional behaviorである。 | **existing correction, no new correction**。Task 4.1はparserやruntimeを変更しない。 | Target Stable Client trafficによるmalformed `a` contractは未確認で、Issue #27 / #28へ残る。 |
| Status crosswalkとApproved provenance | Approved=`3`について、単一reference implementation `reference_implementation:osuAkatsuki/bancho.py/blob/master/app/api/domains/osu.py` (優先度5) と、Athena mapper / focused test (優先度6)。Ranked beatmap infoは`.kiro:specs/beatmap-info-endpoint/research.md#observed-official-response-fixture-osu-getbeatmapinfophp` (優先度2)。 | 単一reference implementationはAthena deterministic behaviorより優先する。Approved=`3`は両者で一致し、wire/runtime mismatchではなくevidence provenanceの矛盾だけがあった。Ranked beatmap infoのofficial fixture anchorは既にcanonicalであり、変更しない。 | **evidence metadata correction**。Approved getscoresのstateを`reference_implementation`へ昇格し、reference sourceを先頭、Athena mapper / testをlower-priority corroborationとして保持する。`src/osu_server/`は変更しない。 | Approved getscoresのTarget Stable Client trafficまたはofficial fixtureは未取得で、beatmap infoのRanked以外のwire valueも未確認のまま保持する。 |
| Stable verifier / catalog projection | `src/athena_cli/stable_verification/getscores.py`、`src/athena_cli/stable_verification/catalog.py`、対応unit test、Task 3.1 / 3.2。Athena verification projection (優先度6)。 | これはwire sourceではなく、Athena-owned implementation completionとmissing traffic evidenceを分離する投影である。上位wire evidenceとの矛盾を示さない。 | **no-correction**。verifier / catalogのruntime behaviorをTask 4.1で変更しない。 | `KNOWN_GAP`はIssue #27 / #28所有のTarget Stable Client traffic confirmationだけを表す。 |

### Production symbol correction gate

- Task 2.1-2.5およびTask 3.1-3.2の結果を再確認したところ、Task 4.1で新たに修正すべき`src/osu_server/`のruntime mismatchはない。Approved=`3`はwire値が一致しており、修正対象はevidence provenanceだけである。
- このためTask 4.1はproduction symbolを編集せず、GitNexus impact analysisは実行しない。これはimpact analysisを省略してproduction editを行う判断ではない。
- 将来、優先度1-5のevidenceがcurrent runtimeまたはcrosswalkと矛盾した場合だけ、対象をone response branchまたはone mapper ruleへ限定する。その編集前にGitNexus impact analysisを実行し、HIGH / CRITICALなら編集を停止してユーザーへwarningとdirection requestを行う。承認なしにproduction correctionを行わない。

## Design Decisions

### Decision: Keep completion evidence separate from target probe inputs

- **Context**: Live probe cases and deterministic completion cases have different security and lifecycle requirements.
- **Alternatives Considered**:
  1. `probe_cases.json`へ全completion branchとexpected bodyを追加する。
  2. Add a separate symbolic `branch_cases.json` linked to response shape ids.
- **Selected Approach**: Separate `branch_cases.json`を追加する。
- **Rationale**: Probe inputはactual query construction、completion catalogはbranch-to-contract traceabilityを目的とする。分離によりraw query-like valuesのcopyを避け、target probe変更でAthena contractがdriftしない。
- **Trade-offs**: JSON fileが一つ増えるが、両artifactの責務が明確になる。

### Decision: Model exact fixtures by distinct wire shape

- **Context**: Multiple leaderboard categories share the same wire grammar.
- **Alternatives Considered**:
  1. Add one exact body fixture per category and malformed case.
  2. Add five distinct shape fixtures and map all cases to them.
- **Selected Approach**: Five distinct shape fixturesを作成する。
- **Rationale**: Client-observable differenceを直接表し、category duplicationとfixture driftを防げる。
- **Trade-offs**: Scenario-specific field valuesはcase catalogとruntime seedから追跡する必要がある。

### Decision: Store exact body contracts as canonical Base64 text

- **Context**: Repository text hookがterminal newlineをnormalizeし、raw fixtureではshort bodyのno-LFとheader-onlyの3 terminal LFを保持できない。
- **Alternatives Considered**:
  1. Hook configurationを変更してraw `.body` fileを除外する。
  2. Body bytesをJSON string escapeへ埋め込む。
  3. Shapeごとのcanonical Base64 textを保存し、strict decoderでexact bytesへ戻す。
- **Selected Approach**: Non-empty `.body.b64`はASCII Base64 payload 1つとrepository terminal LF 1つだけを持ち、empty bodyはcanonical empty Base64としてzero-byte fileを持つ。Validationとruntime comparisonはdecoded bytesをcontractとして扱う。
- **Rationale**: Existing hookとproject-wide configを変更せず、no-LF、複数terminal LF、empty bodyをlosslessに表現できる。Strict decoderはnon-empty payloadのmissing terminal LF、extra / interior whitespace、non-ASCII、invalid / non-canonical Base64、unsupported encodingをsafe diagnosticで拒否する。
- **Trade-offs**: Fixtureを目視するときdecodeが必要だが、typed public methodとtestが唯一のdecode boundaryを提供する。

### Decision: Add typed manifest loading to stable verification

- **Context**: JSONだけではrequired field、enum、foreign key、secret policyをmechanically enforceできない。
- **Alternatives Considered**:
  1. Testsでraw `dict[str, object]` を直接assertする。
  2. Frozen slotted dataclassとenumへparseし、`GetscoresVerifier`からvalidation resultを返す。
- **Selected Approach**: Typed dataclass + enum loaderを新しい`getscores_evidence.py`へ集約し、既存`GetscoresVerifier`から呼び出す。
- **Rationale**: `Any`を使わずschema errorをfixture単位で報告でき、CLI validationにも同じcontractを再利用できる。
- **Trade-offs**: Stable verification moduleが一つ増えるが、probe orchestrationとevidence schemaの責務を分離でき、runtime serverへのdependencyは増えない。

### Decision: Keep endpoint-specific status mappings separate

- **Context**: Canonical domain meaningは共通でもgetscoresとbeatmap infoのwire valuesは異なる。
- **Alternatives Considered**:
  1. Shared stable status enum / numeric mapperを作る。
  2. Crosswalkだけを共有し、各endpoint mapperは独立させる。
- **Selected Approach**: Crosswalk artifactだけを共有し、numeric mapperは独立させる。
- **Rationale**: Confirmed evidenceがendpointごとに異なり、shared mapperはunconfirmed valueの推測を誘発する。
- **Trade-offs**: Two mappersのdriftはcrosswalk validation testで検出する必要がある。

### Decision: Gate production corrections on higher-authority evidence

- **Context**: Current Athena behaviorだけを根拠にwire behaviorを変更するとcompatibility regressionを作り得る。
- **Alternatives Considered**:
  1. Completion fixtureをcurrent runtimeから自動生成してruntimeを常に正とする。
  2. Evidence hierarchyを適用し、confirmed contradictionだけを最小修正する。
- **Selected Approach**: Target traffic、official fixture、protocol docs、reference consensusをAthena deterministic behaviorより優先する。
- **Rationale**: Fixtureはimplementation snapshotではなくcompatibility evidenceであるべきため。
- **Trade-offs**: Unconfirmed malformed behaviorはprovisionalのまま残る。

### Decision: Declare implementation completion without claiming target confirmation

- **Context**: Issue #12をclose可能にしつつ、Target Stable Client traffic gapを失わない必要がある。
- **Alternatives Considered**:
  1. Target traffic取得までMatrixを`Partial`に保つ。
  2. Implementationとtraffic evidenceを別axisとして記録する。
- **Selected Approach**: Runtime/fixture/testがcompleteなら`Implemented`、traffic evidenceはIssue #27 / #28のopen gapとして記録する。
- **Rationale**: Missing implementationとmissing external evidenceは異なるwork itemである。
- **Trade-offs**: Readersが`Implemented`をFull Stable Compatibilityと誤読しない明示文が必要になる。

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Decision |
| --- | --- | --- | --- | --- |
| Distinct shape manifest + branch catalog | Exact bodiesとscenario mappingを分離する | 重複が少なくtraceabilityが高い | 2 artifact間のforeign key validationが必要 | Selected |
| Category-specific golden fixtures | 各categoryごとにresponse bodyを保存する | Testの見た目は直接的 | 同一grammarの大量複製とdrift | Rejected |
| Runtime-generated snapshots | Current endpoint outputからfixtureを生成する | 作成が容易 | Current bugをcontractとして固定する | Rejected |
| Shared stable numeric status mapper | Getscoresとbeatmap infoを同一mapperへ統合する | Numeric mappingが一箇所になる | Endpoint差とunconfirmed valuesを隠す | Rejected |
| Documentation-only completion | Guide / Matrixだけを更新する | Diffが小さい | Exact evidenceとregression detectionが不足 | Rejected |

## Risks & Mitigations

- Fixture bodyの末尾newlineがrepository hookで変わる: Empty Base64はzero-byte file、non-empty Base64 textはrepository terminal LFを1つだけ許可し、decoded bytesをruntime responseと直接比較してmanifestの末尾連続LF数も検証する。
- Branch catalogがlive probe inputと重複する: Completion catalogはsymbolic profileだけを持ち、raw request valuesを保存しない。
- New manifestがruntimeからdriftする: Relevant integration testsをshape manifestへ接続し、CLI validationも同じfixtureを読む。
- Beatmap info未確認値が推測される: `unconfirmed` + `null`をschemaで許可し、numeric valueとの同時指定を禁止する。
- Secretまたはcaptured queryがfixtureへ混入する: Forbidden key/value validationとdiagnostic redaction testを追加する。
- `Implemented`がFull Stable Compatibilityと誤読される: Guide / Matrixにcompletion scopeとIssue #27 / #28 handoffを明記する。
- Evidence correctionがbroad refactorへ拡大する: Correction gateはconfirmed contradiction、one branch、exact fixture、focused regression testを必須にする。

## References

- GitHub Issue #12 - Modern getscores completion scope
- GitHub Issue #27 / #28 - Target Stable Client traffic evidence handoff
- `CONTEXT.md` - Modern Getscores Implementation Completion glossary
- `docs/stable-compatibility-guide.md` - Modern getscores contract and remaining evidence
- `docs/stable-compatibility-matrix.md` - Modern getscores implementation status
- `.kiro/specs/beatmap-info-endpoint/research.md` - Official beatmap info Ranked=`1` evidence
- `.kiro/specs/beatmap-info-endpoint/design.md` - Endpoint-specific status mapping boundary
- `tests/fixtures/stable_compatibility/replay_download/response_contract.json` - Typed response-contract precedent
