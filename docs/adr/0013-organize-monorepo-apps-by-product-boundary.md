# ADR 0013: Organize monorepo apps by product and release boundary

## Status
Accepted (2026-07-30)

## Context
Athena の monorepo は Python server、管理 CLI、first-party Web App を所有します。ASGI app、taskiq worker、管理 CLI は別 entrypoint ですが、同じ domain、application services、composition、database schema、dependency set、version、release lifecycle を共有します。現在の管理 CLI も server の config、domain、services、composition、database administration、stable compatibility implementationを利用します。

## Decision
`apps/` は独立した product と release ownership の境界とし、`apps/athena_server` と `apps/athena_web` を置きます。ASGI app、taskiq worker、管理 CLI は process や executable 単位では分割せず、すべて `apps/athena_server` が所有します。

`apps/athena_web`はtarget ownershipとして予約しますが、monorepo移行だけを理由に空workspaceやNext.js scaffoldを作りません。最初のfrontend featureを実装する時点で、UI component system、source layout、test harness、verified dependency versionと一緒にworkspaceを作成します。それまではroot pnpm manifest、pnpm lockfile、Web用Nix moduleも追加しません。

管理 CLI は `apps/athena_server/src/athena_cli` の独立した Python package namespace として保持します。`athena_cli` は server application moduleを利用できますが、`athena_server` から `athena_cli` への依存は禁止します。CLIだけの独立version、installation artifact、releaseは提供しません。

`packages/` は独立したbuild artifactまたは複数の実consumerに対して深いinterfaceを提供するmoduleだけを置きます。初期状態ではRust/PyO3 extensionとして独立したbuild、test、FFI interfaceを持つ`packages/athena_crypto`だけを置きます。汎用的な`athena_core`、単一Web Appだけが使うOpenAPI generated client、UI library、test utility、TypeScript設定はpackage化しません。2つ目の実consumer、独立配布、または異なるtoolchainを閉じ込める必要が生じた時点で抽出を再評価します。

Repository rootは配布packageではなくworkspace orchestrationを所有します。Root `pyproject.toml`は`tool.uv.package = false`のuv workspace rootとし、repository横断のPython quality/test dependency groupとRuff、basedpyright、interrogate、pytestの共通policyを所有します。Python distribution、runtime dependency、build metadata、console script、server architecture固有のimport-linter設定は`apps/athena_server/pyproject.toml`が所有します。Python workspaceはrootの単一`uv.lock`を共有し、member固有のlockfileは持ちません。Frontend workspace作成後はroot `package.json`を`private`なpnpm workspace metadataだけに限定し、Web dependencyとscriptは`apps/athena_web/package.json`が所有します。JavaScript workspaceもrootの単一`pnpm-lock.yaml`を共有します。

Database schemaとmigration lifecycleはserver productの一部なので、Alembic設定とrevisionは`apps/athena_server/alembic.ini`および`apps/athena_server/alembic/`に置きます。Repository rootはmigration implementationを所有せず、cross-workspace task interfaceからserver側のAlembicまたはAthena CLIを呼び出します。

Documentationも同じownership boundaryに従います。Root `README.md`はrepository全体の概要、quick start、workspace map、横断workflowを説明し、初回移行では`apps/athena_server/README.md`と`packages/athena_crypto/README.md`を作成します。`apps/athena_web/README.md`はfrontend workspace作成時に追加し、各child READMEはworkspace固有の実行、test、build、運用情報を所有します。`tests/system/README.md`はsystem testが作成された時点で、その前提service、実行方法、failure investigationを説明するために置きます。

Agent向け規約は初回移行でroot、`apps/athena_server`、`packages/athena_crypto`の`AGENTS.md`を作成し、frontend workspace作成時に`apps/athena_web/AGENTS.md`を追加します。Rootはrepository共通の必須規約を、childはそのworkspaceだけに適用する差分を記載します。READMEは人間向けの説明とrunbook、AGENTS.mdはagentが従う規範の正本とし、同じ規則を両方へ複製しません。より細かいlayer単位のAGENTS.mdは、実際に差分規約が必要になるまで作りません。

Root `justfile`をdevelopment、quality、test、build、CI taskの公開interfaceとします。Root `scripts/`はJust recipeへ直接記述すると理解や安全性を損なう複雑なrepository横断helperだけを所有し、一般的なcommand catalogにはしません。初期移行ではworktree lifecycleを扱う`scripts/agent-worktree.sh`を残し、`scripts/ci.sh`と`scripts/dev-tasks.sh`はworkspace別recipe、Athena CLI、service orchestrationへ責務を移して削除します。

Version controlするlocal development infrastructureのtemplateは`infra/development/`にまとめます。Nginx、Cloudflare Tunnel、hostsのexampleはそれぞれ`infra/development/nginx/`、`infra/development/cloudflared/`、`infra/development/hosts.example`が所有します。生成したcertificate、実際に使用するNginx設定、machine固有のCloudflare Tunnel設定はrepository sourceではないため、gitignoreされた`.state/certs/`、`.state/nginx/`、`.state/cloudflared/`に置きます。Root直下の`certs/`、`cloudflared/`、`nginx.dev.conf*`、`hosts.example`は移行後に残しません。

Type stubもconsumerまたはdistributionのownershipに従います。Caterpillar、Glide、httpxなどserverとそのtestだけが利用するthird-party stubは`apps/athena_server/typings/`に置きます。`athena_crypto`のpublic type interfaceは`packages/athena_crypto`自身が所有し、build artifactへ同梱します。共有virtual environmentだけを理由にroot `typings/`へ集約しません。複数の独立Python workspaceが同じstubを必要とした時点で、専用stub packageへの抽出を再評価します。

Repository全体の開発支援コードはruntime appやdistribution packageと分けて`tools/`に置きます。Gitlint設定`.gitlint`はrootに残し、custom ruleとそのtestは`tools/gitlint/rules/`および`tools/gitlint/tests/`へ移します。Gitlint ruleのtestを`apps/athena_server/tests/`やroot `tests/system/`へ混在させません。規模が小さい間は`tools/gitlint`専用のREADMEやAGENTS.mdを作らず、実行入口はroot Just recipeにします。

Kiroのproject planning metadataとfeature specificationはworkspaceへ分割せず、root `.kiro/settings/`、`.kiro/steering/`、`.kiro/specs/`に置きます。Featureのrequirements、design、research、implementation planは複数workspaceへ影響し得るため、app directoryへ移しません。`.kiro/specs/`は進行中のplanだけでなく、完了したfeatureのversioned specificationも保持します。完了specは`phase`を実装状況と一致させて残し、superseded specは後継を明示して残します。永続的な設計情報を持たないabandoned draftだけを個別確認後に削除し、一括削除や別archive directoryへの移動は行いません。

`.kiro/specs/README.md`はspec lifecycleとauthorityを説明します。Current observable behaviorの正本はcodeとtest、横断的で長期的なarchitecture decisionの正本はADR、feature単位のrequirements、design、research、implementation historyの正本はKiro specとします。Monorepo移行時は既存specの削除監査ではなく、`phase`、task completion、実装状態の整合性監査を行います。

Long-lived architecture decisionはscopeにかかわらずroot `docs/adr/`で単一の連番を維持します。Workspace固有のimplementation architecture、protocol、operation documentはownerの`docs/`へ置き、複数workspaceを横断するresearchだけをroot `docs/research/`に置きます。現在のserver architecture documentとStable compatibility guide/matrixは`apps/athena_server/docs/`へ移します。TanStack StartとNext.jsの比較調査はfrontend workspace作成まではroot `docs/research/`に置き、作成時に`apps/athena_web/docs/research/`へ移します。Root `CONTEXT.md`はAthena全体のdomain glossaryとして維持します。

Environment fileはconsumer ownershipで分けます。Root `.env.example`はdomain、portなどlocal orchestrationで複数workspaceが共有する値だけをdocumentします。Server固有設定は`apps/athena_server/.env.example`とgitignoreされた`.env.development`、`.env.test`が、Web固有設定は`apps/athena_web/.env.example`とframework標準のgitignoreされたlocal env fileが所有します。Server configとAthena CLIはcurrent working directoryではなくserver project rootをdefaultのenv file locationとして解決します。CIはenv fileに依存せず値を明示し、production secretとCloudflare固有設定はこれらのfileへ保存しません。

Agent toolingはrootでrepository全体を所有します。`AGENTS.md`とchild AGENTS.mdを共通規約とworkspace差分の正本とし、root `CLAUDE.md`はAGENTS.mdを参照するClaude固有差分だけを持ちます。`.agents/skills/`は共通skill、`.claude/skills/`はClaude向けadapterとsymlink、`.codex/agents/`はCodex固有agent、`skills-lock.json`はskill source lockとして維持します。Monorepo移行時に`CLAUDE.md`のshared state記述をper-worktree `.state/`方針へ修正します。

Root `TODO.md`はbacklogのsource of truthとして維持しません。既存項目を`.kiro/steering/roadmap.md`と`.kiro/specs/`へ照合し、未登録のdurable requirementだけを移した後に削除します。

```text
apps/
├── athena_server/
└── athena_web/

packages/
└── athena_crypto/
```

## Consequences
directory 名は `backend`、`bancho`、`webui` のような部分的な責務ではなく、Athena が提供する product boundary を表します。CLIを独立appに見せるためにserver implementationの大部分を汎用的な`core` packageへ移動せず、深いserver moduleとCLI adapterのlocalityを維持します。共有 library、generated client、build tooling、cross-app dependency の配置は `packages/` の責務として別途決定し、process 数やentrypoint数だけを理由に app directory を増やしません。

確定したtarget treeと各directoryのownershipは[作業用monorepo layout](../monorepo-layout.md)にまとめます。

Test は ownership を持つ workspace と同じ directory に置きます。Server、worker、CLI固有のunit、integration、e2e、fixture、factory、test supportは`apps/athena_server/tests/`に、Web App固有のtestは`apps/athena_web/tests/`に、package固有のtestは`packages/<package>/tests/`に置きます。Root `tests/system/` は Web App、server、workerなど複数 workspace を横断する observable behavior の検証だけを所有し、共有 test utility のdumping groundにはしません。

`tests/system/`は最初のcross-workspace testを追加する時点でprivate test workspaceとして作成します。Playwrightなどsystem test固有のJavaScript dependency、configuration、fixtureは`tests/system/package.json`が所有し、pnpm workspace memberに含めます。Python system testはroot pytest policyで同じdirectoryから実行できます。Webだけで完結するbrowser testやserverだけで完結するprotocol E2Eをroot system testへ移しません。

`apps/athena_web`内部のroute、feature、component、API adapterのsource layoutはmonorepo boundaryでは決定しません。Next.js実装を開始する時点で、確定したuser workflow、rendering boundary、data flow、test strategyから別途設計します。
