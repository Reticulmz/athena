# Requirements Document

## Introduction

Athenaの既存client、operator、developer向け契約を維持したまま、repositoryをproduct ownershipに沿ったmonorepoへ移行する。移行後はserver product、管理CLI、crypto package、test、migration、type stub、development infrastructure、CI、documentationの責務が明確で、clean checkoutとlinked worktreeのどちらでも一貫した開発workflowを利用できる状態にする。同時に、旧配置、重複lockfile、暗黙setup、stale path、重複規約、未整理backlogを安全に除去する。

## Boundary Context

- **In scope**: 既存server、worker、管理CLI、crypto packageのmonorepo化、test/migration/type stub/documentation/toolingの所有境界整理、root開発workflow、worktree隔離、local ingress、CI parity、Kiro spec/TODO/旧設定の監査とcleanup。
- **Out of scope**: Web App workspaceとfrontend dependencyの作成、Web processとapex Web routingの有効化、cross-workspace system test workspaceの作成、PP計算library/binding方式の決定、protocol/domain featureの追加または意味変更。
- **Adjacent expectations**: 将来のWeb Appは予約されたproduct boundaryへ追加される。現行Stable/Lazer/API、database、worker、CLI契約は各ownerの既存specとtestを正本とし、本specはその意味を変更しない。

## Requirements

### Requirement 1: Runtimeと公開interfaceの互換性

**Objective:** 運用者として、repository移行後も既存のserver、worker、CLI、client integrationを変更せず利用できることで、構造変更を機能変更から分離したい。

#### Acceptance Criteria

1. When monorepo移行が完了したとき, the Athena repository shall 現在supportしているStable/Lazer/APIのwire behaviorとresponse outcomeを維持する。
2. When app processを起動するとき, the Athena repository shall `python -m osu_server`による起動と`osu_server` import namespaceを維持する。
3. When worker processを起動するとき, the Athena repository shall `osu_server.worker:broker`と既存task名およびobservable outcomeを維持する。
4. When 管理CLIを起動するとき, the Athena repository shall `athena` console commandと`athena_cli` import namespaceを維持する。
5. When 管理CLIを利用するとき, the Athena repository shall 既存の`env`、`db`、`config`、`dev`、`pp`、`test` command familyとそのvalidation、confirmation、exit-code contractを維持する。
6. When database migrationを実行するとき, the Athena repository shall 既存schema、revision identifier、migration head、failure propagationを移動だけを理由に変更しない。
7. If runtime、protocol、domain、databaseのobservable behavior変更が必要になった場合, the Athena repository shall その変更を本specへ混在させず、別specと互換性証拠で扱う。

### Requirement 2: Productとpackageの所有境界

**Objective:** 開発者として、各artifactのproduct/release ownershipをdirectoryから判別できることで、process数をpackage数と誤認せず変更対象を選びたい。

#### Acceptance Criteria

1. The Athena repository shall app、worker、管理CLIを単一の`apps/athena_server` productとして提供する。
2. The Athena repository shall 管理CLIをserver productと同じversion、installation artifact、release lifecycleで提供する。
3. The Athena repository shall `athena_crypto`を`packages/athena_crypto`から独立してbuild、test、型検査できるartifactとして提供する。
4. The Athena repository shall repository rootをruntime applicationの配布artifactとして提供しない。
5. While frontend workspaceが存在しない間, the Athena repository shall server、worker、CLI、cryptoのsetup、build、quality、test、developmentをWeb Appなしで完了できるようにする。
6. When workspace固有のtest、migration、type stub、documentationを探すとき, the Athena repository shall そのconsumerまたはdistribution ownerから発見できるようにする。
7. When built `athena_crypto` artifactをtype-aware consumerが利用するとき, the Athena repository shall repository rootのprivate stub pathに依存せずpublic type informationを提供する。

### Requirement 3: 一貫したdependency resolutionとsetup

**Objective:** 開発者として、clean checkoutから重複しないdependency stateを再現できることで、workspaceごとのversion driftを避けたい。

#### Acceptance Criteria

1. When clean checkoutをsetupするとき, the Athena development workflow shall 初回移行に含まれるすべてのPython workspaceを単一のrepository-wide dependency resolutionからinstallする。
2. The Athena repository shall Python dependency resolutionのauthoritative lockを1つだけ保持する。
3. If workspace manifestとauthoritative lockが不整合な場合, the Athena development workflow shall setupまたはvalidationを失敗させ、更新が必要なartifactを示す。
4. When setupを同じworktreeで再実行するとき, the Athena development workflow shall 既存の正しいstateを破壊せず同じ利用可能状態へ収束する。
5. When developerがdevelopment environmentへ入るだけの場合, the Athena development workflow shall dependency同期、state初期化、certificate生成、Git hook変更、OS trust store変更を暗黙実行しない。
6. If explicit setupの前提条件が不足している場合, the Athena development workflow shall failureを無視せず、必要な回復操作を報告する。

### Requirement 4: 単一の公開task workflow

**Objective:** 開発者とCI operatorとして、repository rootから同じtask interfaceを利用できることで、実行場所や旧scriptを意識せず正しいworkflowを選びたい。

#### Acceptance Criteria

1. The Athena repository shall setup、development、quality、docstring validation、test、build、database migration、test database operationを発見可能な単一のroot task interfaceから提供する。
2. When taskをlocalまたはCIで実行するとき, the Athena development workflow shall 同じtask contractとsuccess/failure判定を使用する。
3. When 旧quality/test/database helperを削除するとき, the Athena repository shall 既存能力と意味のあるexit behaviorをroot task interfaceまたは管理CLIへ移管済みにする。
4. The Athena repository shall linked worktreeの作成とlifecycleを扱う既存agent worktree helperを維持する。
5. If developerがdeprecated commandまたはpathをdocumentationから探した場合, the Athena repository shall それをcanonical workflowとして案内しない。

### Requirement 5: Linked worktreeのstate隔離

**Objective:** 複数worktreeを利用する開発者として、各worktreeのenvironmentとruntime stateが独立することで、並行作業同士の汚染や破壊を防ぎたい。

#### Acceptance Criteria

1. When 2つ以上のlinked worktreeをsetupするとき, the Athena development workflow shall virtual environment、runtime state、generated certificate、proxy/tunnel設定、generated hook stateをworktreeごとに分離する。
2. When 1つのworktreeでsetup、development、test、cleanupを実行するとき, the Athena development workflow shall primary checkoutまたは別worktreeのgenerated stateを変更しない。
3. When server configまたは管理CLIがenvironment fileを解決するとき, the Athena repository shall 呼び出し時のcurrent working directoryに依存せずserver projectの既定locationを使用する。
4. The Athena repository shall generated state、machine固有credential、local secretをversioned sourceとして追跡しない。
5. If generated stateが不足または不正な場合, the Athena development workflow shall 他worktreeのstateへfallbackせず、現在のworktreeでの回復方法を報告する。
6. When environment設定例を参照するとき, the Athena repository shall cross-workspace値とserver固有値をそれぞれのownerから取得でき、production secretを例示fileへ保存しない。

### Requirement 6: Testとquality gateの完全なcoverage

**Objective:** 開発者として、rootからquality/test gateを実行したときに全workspaceが検証されることで、移動による検査漏れを防ぎたい。

#### Acceptance Criteria

1. When root quality gateを実行するとき, the Athena development workflow shall server、管理CLI、crypto package、repository toolingに適用されるformat、lint、docstring、type、import-boundary validationをすべて実行する。
2. When root test gateを実行するとき, the Athena development workflow shall server、worker、管理CLI、crypto package、repository toolingに属するtestをすべて実行する。
3. If 新しいworkspaceまたはtest locationがroot gateの対象から漏れている場合, the Athena repository shall validationを失敗させるか、機械的に検出可能な不整合として報告する。
4. When testを分類するとき, the Athena repository shall 単一workspace内で完結するtestをowner workspaceから実行可能にする。
5. While cross-workspace behavior testが存在しない間, the Athena repository shall 空のsystem test workspaceや将来用dependencyを要求しない。
6. When database-backed testを実行するとき, the Athena development workflow shall 既存のtest database作成、migration、failure propagation contractを維持する。

### Requirement 7: Local development ingressとprocess lifecycle

**Objective:** 開発者として、外部credentialなしのlocal profileと任意の高忠実度tunnel profileを選べることで、日常開発とreal-client integrationを同じrouting contractで検証したい。

#### Acceptance Criteria

1. When canonical local development profileを起動するとき, the Athena development workflow shall external accountまたはtunnel credentialなしでnamed HTTPS ingressを提供する。
2. Where tunnel profileを選択した場合, the Athena development workflow shall local profileと同じapplication routingへexternal tunnelを追加する。
3. If tunnel credentialまたはconfigurationが存在しない場合, the Athena development workflow shall core local servicesを失敗させず、tunnel固有setupを案内する。
4. When development process graphを起動するとき, the Athena development workflow shall database、state service、app、worker、reverse proxyのreadiness、dependency order、graceful shutdown contractを維持する。
5. When app loopback portへ直接接続するとき, the Athena development workflow shall その経路をhealth checkまたはinternal debugging用途として扱い、通常client向けcanonical URLとして案内しない。
6. While frontend workspaceが存在しない間, the Athena development workflow shall Web processまたはapex Web catch-all routeを必須processとして起動しない。

### Requirement 8: CIとlocal validationのparity

**Objective:** Maintainerとして、localで通過した公開gateとCIの判定が一致することで、環境固有の検査漏れを防ぎたい。

#### Acceptance Criteria

1. When pull requestまたはmain branch更新を検証するとき, the Athena CI shall canonical root quality/test taskと同じvalidation contractを実行する。
2. When independent validationが失敗するとき, the Athena CI shall quality、test、build、migration、reproducible-environment validationのfailureを区別して報告する。
3. When CIがdatabase-backed validationを実行するとき, the Athena CI shall migration headを適用してから対象testを実行する。
4. The Athena CI shall server productとcrypto packageのbuild、test、quality coverageを検証する。
5. The Athena CI shall local certificate、tunnel credential、interactive trust-store変更、developer Git hook生成を前提にしない。
6. If canonical local taskとCI workflowのvalidation contractが乖離した場合, the Athena CI shall validationを失敗させるか、差分を明示的に報告する。

### Requirement 9: Documentation、agent guidance、spec lifecycleの整合性

**Objective:** 人間とcoding agentとして、現在のpath、command、ownership、計画状態を正しい文書から取得できることで、移行前の案内による誤操作を避けたい。

#### Acceptance Criteria

1. When migrationが完了したとき, the Athena repository shall root documentationにrepository概要、quick start、workspace map、cross-workspace workflowを記載する。
2. When serverまたはcrypto固有の実行、test、build、運用情報を探すとき, the Athena repository shall owner workspaceのdocumentationから取得できるようにする。
3. The Athena repository shall root agent guidanceを共通規約の正本とし、child guidanceをworkspace固有差分に限定する。
4. When long-lived architecture decisionを追加または参照するとき, the Athena repository shall repository-wideの単一ADR系列から取得できるようにする。
5. When Kiro specを監査するとき, the Athena repository shall active、completed、superseded、abandonedの状態をimplementation evidenceと整合させ、completed feature documentationを一括削除しない。
6. When `TODO.md`を削除するとき, the Athena repository shall 未完了のdurable requirementをroadmapまたはfeature specへ移管済みにする。
7. If tracked documentation、fixture、validation、allowlist、agent instructionに旧pathまたは廃止commandが残る場合, the Athena repository shall migration validationを失敗させるか未完了として報告する。

### Requirement 10: 安全なcutoverとcleanup boundary

**Objective:** Maintainerとして、旧構造と新構造を長期併存させず不要物だけを除去できることで、二重のsource of truthを残さず移行を完了したい。

#### Acceptance Criteria

1. When artifactを新しいownerへ移動するとき, the Athena repository shall import、configuration、test discovery、documentation、validation referenceを同じcutoverで更新する。
2. When cutoverが完了したとき, the Athena repository shall 旧directory、重複manifest、member lockfile、deprecated helper、root直下の移動済みtemplateをcanonical sourceとして残さない。
3. If cleanup対象がまだtracked consumerまたは未移管requirementから参照されている場合, the Athena repository shall そのartifactを削除せずmigrationを未完了として報告する。
4. The Athena repository shall tracked development templateとgenerated/machine-specific stateを区別し、generated artifactをsource directoryへ混在させない。
5. While 初回monorepo migrationを実施している間, the Athena repository shall `apps/athena_web`、frontend workspace metadata、frontend lockfile、Web用environment module、Web process、root system test workspaceを作成しない。
6. While 初回monorepo migrationを実施している間, the Athena repository shall PP計算library、managed runtime、native binary、language binding方式を決定または実装しない。
7. When migration completionを判定するとき, the Athena repository shall repository guide、validation rule、package layout、public task interfaceが同じownership boundaryを示すことを確認する。
