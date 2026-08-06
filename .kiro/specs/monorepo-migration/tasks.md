# Implementation Plan

- [ ] 1. Python workspace cutoverの基盤を確立する
- [x] 1.1 移行前の互換contractとcleanup inventoryを固定する
  - Runtime import namespace、app/worker entrypoint、worker task名、CLI command/confirmation/exit behaviorのbaselineを取得する。
  - Alembic revision identifierとcurrent/head、server/crypto build、現在のquality/test対象を記録する。
  - `--alembic-current`はrecorded `migrations.head`と完全一致する単一current revisionだけを成功とし、空値、複数値、prefix/substr一致をrejectする。
  - Legacy task capability、generated state、tracked template、normative stale path、Kiro/TODO statusのinventoryを作る。
  - Baselineを再実行すると、移行前のobservable contractが機械的に確認できる状態を完了条件とする。
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 9.5, 9.6, 9.7, 10.1, 10.3_
  - _Boundary: Preflight Baseline, Validation Policy_

- [x] 1.2 Crypto artifactをpackage ownerへ移管する
  - Native extension source、Python tests、Rust/Python manifestsをcrypto workspaceへ集約する。
  - Distribution/import/module nameと既存crypto behaviorを維持し、public typing sourceをpackage ownershipへ移す。
  - Package ownerのbuild/test/type artifact入口として、clean wheelをtemporary directoryへbuildし、archiveを検査してwheelのみをisolated consumer venvへinstallし、native testとtype-aware consumer checkを実行する。
  - Root testはこのverifierを一度だけ実行し、package testはroot conftestまたはsource treeのnative build artifactをloadしない。
  - Root quality inventoryは移設中のnon-ignored/untracked crypto Python source/testを検査し、削除済みindex pathをtoolへ渡さない。
  - Crypto workspace単独でbuild、test、type artifact検査を実行できる状態を完了条件とする。
  - _Requirements: 2.3, 2.6, 2.7, 6.1, 6.2, 6.3, 6.4_
  - _Boundary: Crypto Workspace, Validation Policy_

- [x] 1.3 Server runtime、管理CLI、root orchestrationをatomic cutoverする
  - Server runtimeと管理CLIのsourceおよびsingle distribution metadataをserver workspaceへ集約する。
  - 同じcutoverでroot distribution ownershipを除き、rootをserverとcryptoを含むnon-package uv workspaceへ切り替え、authoritative single lockを再生成する。
  - App、worker、console commandとPython namespaceを維持し、`athena_cli -> osu_server`だけを許可するimport directionを保つ。
  - Cutoverを阻害するruntime/test/tooling consumerを同じtaskで新しいsource rootとserver-owned import configurationへ更新し、canonical root quality/test gateをgreenに保つ。
  - root packageとserver packageの二重distributionを残さず、clean locked sync、server artifact build、installed app/worker/CLI entrypoint smokeとcanonical root quality/testがbaselineと一致する状態を完了条件とする。
  - _Depends: 1.1, 1.2_
  - _Requirements: 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 6.1, 6.2, 10.1, 10.7_
  - _Boundary: Server Workspace, Workspace Manifests, Validation Policy_

- [x] 1.4 Python workspace artifactを統合検証する
  - Serverとcryptoのbuild contractをroot workflowから実行し、installed importsとconsole entrypointを検証する。
  - Crypto wheelにpublic typing artifactが含まれ、editable installだけに依存しないことを確認する。
  - Root quality/testがserver、worker、管理CLI、crypto package、repository toolingを検査し、known workspace/test omissionを機械的に検出することを確認する。
  - Server workspaceがfrontend workspaceなしでsync、build、quality、testできることを確認する。
  - Single lock、server artifact、crypto artifactのintegration smokeがすべて成功する状態を完了条件とする。
  - _Depends: 1.3_
  - _Requirements: 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 2.7, 3.1, 3.2, 3.3, 6.1, 6.2, 6.3, 6.4_
  - _Boundary: Workspace Manifests, Server Workspace, Crypto Workspace, Validation Policy_

- [ ] 2. Server-owned artifactsとcompatibility evidenceをcutoverする
- [x] 2.1 Server、worker、CLI test assetsをowner workspaceへ移管する
  - Unit、integration、e2e、fixtures、factories、supportをserver productのtest ownershipへ集約する。
  - Test import、fixture discovery、relative evidence pathを新しいowner基準へ更新する。
  - Root test contractからserver、worker、CLIの全testが発見されることを検証する。
  - 既存test countと重要test catalogに意図しない欠落がない状態を完了条件とする。
  - _Requirements: 1.1, 1.5, 2.6, 6.2, 6.3, 6.4_

- [x] 2.2 Alembic lifecycleをserver productへ移管する
  - Migration configurationとrevision chainをserver workspaceへ集約する。
  - Revision identifier、head、schema semanticsを変更せず、新しいownerからupgrade可能にする。
  - CLIとroot taskからmigration/test database operationのfailure codeを保持する。
  - Empty test databaseがexisting headまでupgradeされ、移行前baselineと一致する状態を完了条件とする。
  - _Requirements: 1.6, 2.6, 4.1, 6.6, 8.3_

- [x] 2.3 Server-specific stubsとtechnical evidenceをownerへ移管する
  - Server/test-only third-party stubsをserver workspaceへ集約し、crypto public stubとのownershipを分離する。
  - Architecture、Stable compatibility、server operation evidenceをserver ownerから参照できるようにする。
  - Type checkerとcompatibility toolingが新しいstub/evidence locationを使用するよう更新する。
  - Root private stubへの暗黙依存がなく、server type/compatibility checksが通る状態を完了条件とする。
  - _Requirements: 2.6, 2.7, 6.1, 9.2, 10.1_

- [x] 2.4 Environment resolutionをserver project基準へ固定する
  - Supported environmentのtyped nameとvalidationをserver config boundaryへ集約し、CLIが再利用する。
  - Source checkoutではserver project基準のenvironment fileを解決し、current working directoryへの依存を除く。
  - Process environment precedenceとenvironment-only installed startupを維持する。
  - Root environment exampleはcross-workspace値だけ、server exampleはserver固有値だけを所有し、production secretを含めない。
  - 隔離環境へserver wheelをinstallし、workspace environment fileがない状態でもprocess environmentだけからapp、worker、CLIが起動し、source checkoutの異なるworking directoryでも同じconfig outcomeになる状態を完了条件とする。
  - _Requirements: 1.2, 1.3, 1.4, 1.5, 5.3, 5.5, 5.6_

- [x] 2.5 Moved path consumerを一括更新する
  - Task 1.3で更新したcutover-blocking consumerを含め、Active fixture catalog、verification report、allowlist、tool configuration、current instructionの残余source/test pathを新配置へ更新する。
  - Normative/current pathとhistorical Kiro snapshotを区別する暫定audit ruleを用意する。
  - Old pathをruntime/test/tooling consumerが参照していないことをtargeted scanで確認する。
  - Path scanがhistorical exception以外のstale consumerを0件として報告する状態を完了条件とする。
  - _Requirements: 9.7, 10.1, 10.3, 10.7_

- [x] 2.6 Boundary 1のruntime compatibility checkpointを通す
  - App、worker、CLI、Stable/Lazer/API focused tests、crypto behavior、Alembic headをbaselineと比較する。
  - Root locked sync、server/crypto build、quality、test、import-boundary checksを実行する。
  - Failure時はtooling cutoverへ進まず、Python ownership boundary内で修復可能な状態を保つ。
  - Baseline contractと全Python gateが一致してBoundary 1を完了できる状態を完了条件とする。
  - _Depends: 2.1, 2.2, 2.3, 2.4, 2.5_
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 6.1, 6.2, 6.6, 10.1, 10.7_

- [ ] 3. Development toolingとinfrastructureを構築する
- [x] 3.1 Side-effect-free Nix compositionを構築する (P)
  - Root environment compositionからserver/crypto固有toolchain、build、checkをworkspace moduleへ分離する。
  - Shell entryはtoolとworktree-relative path variableだけを提供し、sync、state、hook、certificate、trust changeを実行しない。
  - Root-only Flake/lockからdefault shell、workspace checks、reproducible validationを評価できるようにする。
  - Environment entry前後でrepository stateに差分がなく、Nix checksが成功する状態を完了条件とする。
  - _Depends: 2.6_
  - _Requirements: 3.5, 3.6, 5.1, 5.2, 8.2, 8.5_
  - _Boundary: Nix Composition_

- [x] 3.2 Explicit setupとdevelopment task gatewayを構築する (P)
  - Root task catalogへlocked sync、worktree state、hook、certificate/trust setupを明示的に提供する。
  - Core developmentとtunnel developmentのpreflightを分け、setup不足をactionable failureとして返す。
  - Database migration/test database operationとspecialized worktree helperへの導線を維持する。
  - Setupを再実行して同じ利用可能状態へ収束し、devがsetupを暗黙実行しない状態を完了条件とする。
  - _Depends: 2.6_
  - _Requirements: 3.4, 3.5, 3.6, 4.1, 4.3, 4.4, 7.1, 7.2, 7.3_
  - _Boundary: Root Task Gateway_

- [x] 3.3 Worktree-local process graphとingress profileを構築する (P)
  - Database、initialization、state service、app、worker、reverse proxyのreadiness/dependency/shutdownを維持する。
  - Tracked ingress templateとgenerated certificate、actual proxy/tunnel config、credentialを分離する。
  - Core profileをcredential-free named HTTPSとして提供し、同じapplication routingを使用するtunnelをoptional profileへ分離する。
  - App loopback portはhealth check/internal debugging専用とし、通常client向けcanonical URLとして案内しない。
  - Frontend processとapex Web catch-allを追加せず、core profileがreadyになる状態を完了条件とする。
  - _Depends: 2.6_
  - _Requirements: 5.1, 5.2, 5.4, 5.5, 5.6, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 10.4, 10.5_
  - _Boundary: Process Graph, Development Infra_

- [x] 3.4 Repository-wide validation policyとtool ownershipを構築する (P)
  - Format、lint、docstring、type、import-boundary、testの対象をserver、crypto、repository toolsへ明示する。
  - Workspace/test omissionを機械的に検出し、future empty system-test memberを要求しない。
  - Gitlint rule/testをrepository tooling ownerへ移し、root configurationからloadする。
  - Root validation contractがserver、crypto、toolsをすべて列挙して成功する状態を完了条件とする。
  - _Depends: 2.6_
  - _Requirements: 4.1, 4.3, 6.1, 6.2, 6.3, 6.4, 6.5, 8.4_
  - _Boundary: Validation Policy_

- [x] 3.5 Task、process、validation contractをroot interfaceへ統合する
  - Quality、docstring、test、build、migration、aggregate CI、monorepo auditをpublic root recipeとして接続する。
  - Legacy quality/test/database helperのcapabilityとmeaningful exit propagationを移管する。
  - Process profileとvalidation policyをroot taskから同じworkspace/state resolutionで実行する。
  - Public task listから全canonical workflowが発見でき、legacy scriptなしで同じoutcomeを得られる状態を完了条件とする。
  - _Depends: 3.1, 3.2, 3.3, 3.4_
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 6.1, 6.2, 7.1, 7.2, 8.1, 8.6_

- [ ] 4. CI、governance、cleanupを統合する
- [x] 4.1 CIをcanonical task contractへ切り替える
  - Native dependency/tool setupとservice containerを維持し、quality/test/build/migration/auditをroot recipeから実行する。
  - Quality、test、build、migration、Nix、auditをdistinct statusとして報告する。
  - Test jobはmigration head適用後に全workspace testを実行する。
  - CIがlocal certificate、tunnel credential、trust-store、developer hookを要求せず全jobを開始できる状態を完了条件とする。
  - _Depends: 3.5_
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

- [x] 4.2 Boundary 2のtooling compatibility checkpointを通す
  - Environment entry前後にrepository、state、hook、certificate、trust storeの差分がないことを検証する。
  - Explicit setupのidempotencyと、2 linked worktree間のvirtual environment、runtime state、certificate、proxy/tunnel config、hook stateの隔離を検証する。
  - Credential-free core ingress、optional tunnel、process readiness/dependency/graceful shutdownを検証する。
  - Root quality/test/build/migration/NixとBoundary 2時点のprovisional auditがdistinct CI statusと同じsuccess/failure contractを返すことを検証し、old pathを拒否する完成版auditはTask 4.5/4.6後の成功条件へ限定する。
  - Tooling compatibilityとprovisional auditが成功し、Boundary 3へ進める状態を完了条件とする。
  - _Depends: 4.1_
  - _Requirements: 3.4, 3.5, 3.6, 4.2, 5.1, 5.2, 5.4, 5.5, 7.1, 7.2, 7.3, 7.4, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

- [ ] 4.3 Repositoryとworkspaceのtechnical authorityを切り替える
  - Root overview/common agent policyとserver/crypto runbook/delta guidanceを新ownershipへ分ける。
  - ADR single sequenceを維持し、server architecture/compatibility/operation evidenceをownerから参照可能にする。
  - Canonical command、worktree state、environment、test ownershipのinstructionをroot task/layoutと一致させ、Markdown link auditを通す。
  - Humanとagentがold command/pathを参照せず新workflowへ到達できる状態を完了条件とする。
  - _Depends: 4.2_
  - _Requirements: 4.5, 9.1, 9.2, 9.3, 9.4, 9.7_

- [ ] 4.4 Kiro lifecycleとbacklog authorityを整合させる
  - Current behavior、ADR、feature specのauthorityとactive/completed/superseded/abandoned lifecycleを明文化する。
  - Active/current specのphase、task、implementation evidenceを監査し、historical path exceptionをcurrent instructionから区別する。
  - TODO backlogをroadmap/specへ照合し、未登録durable itemだけを移管する。
  - Completed specを失わず、TODO削除後も全durable itemのownerを辿れる状態を完了条件とする。
  - _Requirements: 9.5, 9.6, 9.7, 10.3_

- [ ] 4.5 Monorepo cutover auditを完成させる
  - Old canonical directory、member lock、legacy helper、root generated infra path、stale normative referenceを検出する。
  - Unexpected frontend workspace、JavaScript workspace files、Web process、system-test workspace、PP binding decisionを検出する。
  - Repository guide、validation policy、package layout、public task interfaceのownership一致とMarkdown link integrityを検査する。
  - Historical exceptionをallowし、pre-cleanupではinventory済みの削除予定artifactだけをexpected findingとしてnon-zeroで報告する。
  - 完成版auditがexpected deletion setを正確に識別し、それ以外のunexpected findingを0件として報告する状態を完了条件とする。
  - _Depends: 4.3, 4.4_
  - _Requirements: 6.3, 9.7, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7_

- [ ] 4.6 Legacy artifactをconsumer-free状態で削除する
  - Capability移管が完了し、pre-cleanup auditのunexpected findingが0件でexpected deletion setが固定された後だけlegacy scripts、old directories、member lock、moved root templatesを削除する。
  - Generated/machine-specific stateをsource treeから除き、per-worktree locationだけを残す。
  - Deprecated command/pathをcanonical sourceとして残さず、specialized worktree helperだけを維持する。
  - Cleanup後のauditがunexpected old/new duplicateを0件として報告する状態を完了条件とする。
  - _Depends: 4.2, 4.5_
  - _Requirements: 4.3, 4.4, 4.5, 5.4, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

- [ ] 5. Cross-boundary validationでmigrationを完了する
- [ ] 5.1 Runtime artifactとmigration compatibilityを最終検証する (P)
  - Installed server/crypto artifacts、import namespaces、app/worker/CLI entrypoints、CLI behaviorをpreflight baselineと比較する。
  - Existing Stable/Lazer/API focused regressionを実行し、worker task名とobservable outcomeの両方をpreflight baselineと比較する。
  - Alembic revision chain、current/head、test database upgradeを比較する。
  - Baseline差分が0件、または別specで明示された差分だけになる状態を完了条件とする。
  - _Depends: 4.6_
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 2.2, 2.3, 2.7, 6.6_
  - _Boundary: Server Workspace, Crypto Workspace_

- [ ] 5.2 Explicit setupとlinked worktree isolationを最終検証する (P)
  - Environment entryがrepository、state、hooks、certificate、trust storeを変更しないことを検証する。
  - Setupのidempotencyとactionable failure contractを検証する。
  - 2 linked worktreeの`.venv`、state、certificate、proxy/tunnel config、hook stateが独立しfallbackしないことを検証する。
  - 片方のsetup/test/cleanupが他方を変更しないことが観測できる状態を完了条件とする。
  - _Depends: 4.6_
  - _Requirements: 3.4, 3.5, 3.6, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_
  - _Boundary: Nix Composition, Root Task Gateway_

- [ ] 5.3 Core/tunnel ingressとprocess lifecycleを最終検証する (P)
  - Credentialなしでcore profileを起動し、named HTTPS、readiness、health/debug routeを検証する。
  - Missing tunnel stateがcore profileを停止せず、tunnel profileだけactionable failureになり、設定済みtunnelがcoreと同じapplication routingを使用することを検証する。
  - Database/state serviceより後にapp/workerが起動し、逆順にgraceful shutdownすることを検証する。
  - Loopback app portをcanonical URLとして案内せず、Web process/apex catch-allなしでreal-client向けcore routingが利用できる状態を完了条件とする。
  - _Depends: 4.6_
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 10.5_
  - _Boundary: Process Graph, Development Infra_

- [ ] 5.4 Repository-wide quality、test、build、CI parityを最終検証する (P)
  - Root quality/docstring/type/import contractとserver/crypto/tools testを実行する。
  - Server/crypto artifact build、migration status、Nix validation、audit statusをCI-equivalent contractで実行する。
  - Workspace/test omission detectorが既知memberをすべて認識することを検証する。
  - Local aggregate gateとCI job contractが同じsuccess/failureを返す状態を完了条件とする。
  - _Depends: 4.6_
  - _Requirements: 4.1, 4.2, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_
  - _Boundary: Validation Policy, CI Workflow_

- [ ] 5.5 Final ownership、scope、cleanup auditを通す
  - Root/workspace technical authority、Kiro lifecycle、TODO reconciliation、historical exceptionをreviewする。
  - Old canonical path、legacy command、duplicate lock/template、unexpected frontend/system-test/PP artifactがないことを確認する。
  - Requirements traceabilityと全checkpoint evidenceを最終diffへ照合する。
  - Guide、validation、layout、task interfaceが同じownership boundaryを示し、全gateが成功する状態をmigration完了条件とする。
  - _Depends: 5.1, 5.2, 5.3, 5.4_
  - _Requirements: 4.5, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7_

## Implementation Notes

- Task 1.1のpost-cutover verifierはrelocation semantic contractだけを検証する。root task gatewayの実行内容とfailure propagationはTasks 3.4/3.5で検証する。
- 2026-07-31: User approval後、Task 1.1/1.2のblockerを明示的な受入条件へ戻し、server physical moveとroot non-package workspace/single-lock切替をTask 1.3のatomic integration taskへ統合した。
- 2026-08-02: User approval後、Task 1.3へcanonical root gateをgreenに保つcutover-blocking runtime/test/tooling consumer更新を移管した。Task 2.5は残余consumerの全量audit、historical exception、current instructionのreconciliationを所有する。
- Task 1.2 debug round 1: stale `.venv` extensionはcaptured score vectorを通したが、clean wheelは`InvalidDataSize`で失敗した。source importをartifact evidenceにせず、captured vectorと確認済みstable crypto contractだけで修復を判断する。
- Task 1.2のpre-cutover fixtureはTask 1.1 commit SHAへ固定し、CI test checkoutはそのhistorical objectを取得できるfull historyを使用する。
- 2026-08-03: Task 2.5のpath consumer auditはactive docs、stable fixture/catalog、verification report、tool configurationだけをscanし、historical Kiro snapshot、preflight reconstruction、Task 3.4までのGitlint配置を理由付きexceptionとして扱う。
- 2026-08-03: Task 2.6 Boundary 1はpost-cutover preflight、隔離PostgreSQLへのAlembic head適用/current一致、server/crypto artifact検証、root quality/import-linter、全workspace test（3465 passed, 57 skipped）で完了した。
- 2026-08-03: Task 3.1はserver/crypto workspace module、root composed devShell、Nix checksを追加し、`nix develop`のsync/state/hook/certificate副作用を除去した。`nix flake check`、関連validation test 28件、side-effect-free shell実測、`prek run --all-files`が成功した。
- Task 3.1ではworkspace artifact buildとNix-native structural checksを先に分離し、project dependencyを必要とする全hook実行はexplicit setupとTask 3.4のvalidation ownerへ残す。Flakeはhook configurationの生成とconsumer pathを検証する。
- 2026-08-04: Task 3.2のCloudflared 2026.6.0 loginはcredentialを`$HOME/.cloudflared/cert.pem`へ出力するため、`HOME`をworktree-local stateへ隔離した。`dev-tunnel` preflightはconfigとorigin certificateの両方を要求する。
- 2026-08-04: Task 3.4のroot test policyはcrypto package testsをdirect pytestで重複実行せず、`test_crypto_workspace_artifact.py`からwheel-only artifact verifierを一度だけ実行する。`--test-coverage`がserver、crypto、monorepo tooling、Gitlint toolingのexecution contractを列挙する。
- 2026-08-05: Task 3.5はvalidationとtest database operationをroot-owned helperへ移し、Justを唯一のpublic task catalogにした。Legacy helperはTask 4.1/4.6まで同じimplementationまたはJustへdelegateするcompatibility entrypointに限定し、Flake docstring hookも`just docstrings`へ切り替えた。`just ci`、isolated PostgreSQL/Valkeyでのdatabase recipes、monorepo audit、independent Standards/Spec reviewが成功した。
- 2026-08-05: Task 4.1はCIのquality、test、build、migration、Nix、auditをdistinct jobへ分離し、native jobをroot Just recipeへ統一した。Test jobは`db-migrate`後に全workspace testを実行し、post-cutover baselineとfocused contract testがworkflow driftおよびlocal-only setupを拒否する。Full test 3526件、quality、build、Nix、isolated PostgreSQL migration、audit、independent reviewが成功した。
