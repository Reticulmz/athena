# Research & Design Decisions

## Summary

- **Feature**: `monorepo-migration`
- **Discovery Scope**: Extension / light discovery
- **Key Findings**:
  - 現行root `pyproject.toml`は配布package、server/CLI runtime dependency、全quality policyを同時に所有し、`athena-crypto/uv.lock`との二重lockを生んでいる。
  - 現行`flake.nix` shellHookはdependency sync、state作成、hook生成、certificate/trust-store変更を暗黙実行し、linked worktree isolationを利用者が検証しにくい。
  - 現行root test/type gateは`athena-crypto/tests`を通常対象に含めず、script、CI、documentation、fixtureには旧root pathが広く埋め込まれている。
  - Runtime namespace、CLI command、Alembic revision、process readiness/shutdownは配置とは独立した互換contractとして保護する必要がある。

## Research Log

### Python packagingとworkspace ownership

- **Context**: Root packageをorchestration rootへ変更しても、server/CLI/cryptoの配布契約を維持できるか確認した。
- **Sources Consulted**: `pyproject.toml`、`athena-crypto/pyproject.toml`、`athena-crypto/Cargo.toml`、`uv.lock`、`athena-crypto/uv.lock`、ADR 0013。
- **Findings**:
  - Root distribution `athena`は`src/osu_server`と`src/athena_cli`を同一wheelへ含め、console script `athena`を公開する。
  - `athena-crypto`はMaturin/PyO3による独立extension artifactで、rootからeditable path dependencyとして参照される。
  - Rootとcrypto memberが別々の`uv.lock`を持ち、通常root test discoveryはcrypto testを含めない。
- **Implications**:
  - Rootはnon-package uv workspaceとrepository-wide development policyへ限定する。
  - Server distribution metadataとruntime dependencyは`apps/athena_server/pyproject.toml`へ移す。
  - Cryptoは独立artifactのままrootの単一lockへ参加し、wheel contents testでpublic stub同梱を検証する。

### Runtime、CLI、migration compatibility

- **Context**: Directory移動がruntime contractを破壊する箇所を確認した。
- **Sources Consulted**: `src/osu_server/__main__.py`、`src/osu_server/worker.py`、`src/athena_cli/`、`alembic.ini`、CLI test、architecture/import-linter contract。
- **Findings**:
  - `python -m osu_server`、`osu_server.worker:broker`、`athena` console commandは外部entrypointである。
  - `osu_server -> athena_cli`禁止は既にimport-linter contractとして存在する。
  - Alembicはroot-relative `%(here)s/alembic`と`prepend_sys_path = .`を利用し、配置変更時にconfig pathの同時cutoverが必要である。
  - CLIは`env`、`db`、`config`、`dev`、`pp`、`test` familyとenvironment/confirmation/exit-code contractをtestで保護する。
- **Implications**:
  - Python namespaceやentrypoint名は変更せず、physical rootだけを移動する。
  - Server workspace cutoverはsource、tests、Alembic、typings、docs、manifest、path-based fixturesを同じmigration boundaryで更新する。
  - DB schemaとrevision内容は変更しない。

### Development environmentとprocess graph

- **Context**: Worktree isolation、明示setup、local/tunnel ingressを実現するため現在の副作用とprocess lifecycleを確認した。
- **Sources Consulted**: `flake.nix`、`process-compose.yml`、`.envrc`、`.worktreeinclude`、`.gitignore`、ADR 0014、ADR 0015、ADR 0016。
- **Findings**:
  - Shell entryが`uv sync`、`.state`作成、Git hook生成、`mkcert -install`、certificate生成を実行し、一部failureを無視する。
  - Process graphはPostgreSQL、init、Valkey、app、worker、Nginx、cloudflaredを持ち、readinessとordered shutdownは有効な既存contractである。
  - Cloudflare credential不足が通常process graphへ混入し、generated stateはroot `certs/`、`cloudflared/`、`nginx.dev.conf`へ分散する。
- **Implications**:
  - Root Flakeはtoolchain/env variable/checkのcompositionだけを行い、workspace `default.nix`をimportする。
  - `just setup`がdependency sync、per-worktree state、hook、certificate/trust setupを明示的に所有する。
  - Root `process-compose.yml`をprocess graphの唯一の正本とし、`just dev`はcore graph、`just dev-tunnel`は同じgraphへoptional tunnelを加える。
  - Tracked templateは`infra/development`、generated stateは各worktreeの`.state`へ分離する。

### Quality、test、CI parity

- **Context**: Root task interfaceへ移管すべき既存能力とcoverage gapを確認した。
- **Sources Consulted**: `scripts/ci.sh`、`scripts/dev-tasks.sh`、`.github/workflows/ci.yml`、root/crypto tests、root tool configuration、ADR 0013、ADR 0014。
- **Findings**:
  - `scripts/ci.sh`はtracked PythonへのRuff/interrogateと`src tests`限定のtype/import/test gateを持つ。
  - Crypto testsとGitlint testsはownershipが異なるが、現在のroot pytest/test recipeで一貫して扱われない。
  - CIはnative uv setupとservice containerを使うが、旧scriptを直接呼び、Nix validationを持たない。
- **Implications**:
  - Root `justfile`が公開task contractを定義し、localとCIは同じrecipeを呼ぶ。
  - Root quality/test recipeはserver、crypto、repository toolsの対象を明示し、workspace追加時のsilent omissionを防ぐ。
  - CIはnative ecosystem setup/cacheを維持し、別jobで`nix flake check`を実行する。

### Config path、documentation、cleanup

- **Context**: CWD依存とstale pathがcutoverを不完全にする範囲を確認した。
- **Sources Consulted**: `src/osu_server/config.py`、`src/athena_cli/env`、README、AGENTS、CLAUDE、`.kiro`、`TODO.md`、Stable fixture/catalog、`.gitleaks.toml`、ADR 0013。
- **Findings**:
  - `load_config()`と`load_routing_config()`はCWD相対`.env.<environment>`を読む。
  - Stable fixture metadata、verification catalog、docs、tests、allowlistにroot-relative `src/`、`tests/` pathが多数存在する。
  - Completed Kiro specsは歴史資料でもあるため、旧pathの一律置換は当時のevidenceを歪める可能性がある。
  - `TODO.md`は非構造化backlogを保持し、Kiro statusにも実装との不整合riskがある。
- **Implications**:
  - ConfigとCLIはserver project rootを単一のdefault env-file baseとして共有する。
  - Normative docs、active specs、fixtures、validation、allowlistは新pathへ更新する。
  - Completed Kiro specのhistorical pathはpre-migration snapshotとして扱い、`.kiro/specs/README.md`でauthority/lifecycleと例外を明示する。
  - `TODO.md`はroadmap/specへ照合後に削除する。

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Product-boundary monorepo | Root orchestration + server product + crypto artifact | Release ownershipとtest/doc localityが明確 | Atomic path cutoverが必要 | 選択。ADR 0013と整合 |
| Process-per-app | app、worker、CLIを別appsへ分割 | Process topologyがdirectoryに見える | Domain、schema、releaseを人工的に分断 | 却下 |
| Shared core extraction | Server/CLI共通codeをgeneric packageへ抽出 | 表面的なreuse境界 | 単一consumerの深いmoduleを浅くし、dependency graphを複雑化 | 却下 |
| Root monolithic environment | 現行Flake/scriptをrootに集中 | File数が少ない | Ownership、副作用、worktree stateが混在 | 却下 |
| Root Flake + workspace modules | Root lock/entrypoint、workspace `default.nix` composition | Worktree-safeで責務を分離 | Root interfaceの設計が必要 | 選択。ADR 0014と整合 |
| Per-workspace Flake | 各workspaceにFlake/lockを置く | 単独checkoutに近い | lock/input driftとcross-workspace重複 | 却下 |

## Design Decisions

### Decision: Rootをorchestration-only workspaceにする

- **Context**: Root packageはserver distributionとrepository policyを同時に所有している。
- **Alternatives Considered**:
  1. Root distributionを維持する。
  2. Rootをnon-package workspaceへ切り替える。
- **Selected Approach**: Rootはworkspace membership、単一lock、quality/test policy、task、Nix、process graph、CI/documentationだけを所有する。
- **Rationale**: Product artifactとrepository policyのrelease boundaryが異なる。
- **Trade-offs**: Tool invocationはworkspace pathを意識するが、root Just interfaceが吸収する。
- **Follow-up**: Clean checkoutのlocked sync、server wheel、crypto wheelをCIで検証する。

### Decision: Server、worker、CLIを1つのproduct workspaceに置く

- **Context**: 3 entrypointはdomain、composition、schema、dependency、releaseを共有する。
- **Alternatives Considered**:
  1. `apps/athena_server`へ統合する。
  2. CLIを別app/packageにする。
- **Selected Approach**: `apps/athena_server/src/osu_server`と`src/athena_cli`を同じdistributionに置き、`osu_server -> athena_cli`を禁止する。
- **Rationale**: Entry point数ではなくproduct/release ownershipをdirectory境界にする。
- **Trade-offs**: CLI単独releaseは提供しない。
- **Follow-up**: Existing import-linter contract、console script、CLI testsを移行後も実行する。

### Decision: Explicit setupとside-effect-free shellを分離する

- **Context**: 現行shellHookがmutable stateを暗黙変更する。
- **Alternatives Considered**:
  1. Shell entryで自動setupを継続する。
  2. Shellはtoolchain/envだけ、setupは明示taskにする。
- **Selected Approach**: `nix develop`は副作用なし、`just setup`がsync/state/hooks/certificatesを所有し、`just tunnel-setup`がCloudflare固有setupを所有する。
- **Rationale**: Worktree isolationとfailure observabilityを同時に保証できる。
- **Trade-offs**: 初回利用者はsetupを1回明示実行する。
- **Follow-up**: Setup idempotencyと2 worktree isolationをtestする。

### Decision: Just recipeをlocal/CI parity boundaryにする

- **Context**: Nix shellとGitHub Actionsはsetup方式が異なるが、validation意味は一致させる必要がある。
- **Alternatives Considered**:
  1. CIをすべて`nix develop`で実行する。
  2. CIとlocalで別command catalogを持つ。
  3. Native setup後に同じJust recipeを呼ぶ。
- **Selected Approach**: LocalはNix shell、CIはnative tool/cache/service setupを使い、両方がroot Just recipeを呼ぶ。Nix自体は独立jobで検証する。
- **Rationale**: Semanticsを共有しながらCI cacheとservice integrationを利用できる。
- **Trade-offs**: Just recipeはecosystem commandを薄く委譲し、二重実装を避ける必要がある。
- **Follow-up**: RecipeとActions workflowの乖離をfinal diff reviewで検査する。

### Decision: Atomic ownership cutoverを3 boundaryで実施する

- **Context**: 新旧pathの長期併存はimport、test discovery、docsの二重source of truthを生む。
- **Alternatives Considered**:
  1. Compatibility facadeを置いた段階的移動。
  2. Python、tooling/infra、documentation/backlogを順にatomic cutoverする。
- **Selected Approach**: 各boundary内ではmoveと全consumer更新を同時に行い、boundary間でvalidation checkpointを置く。
- **Rationale**: Rollback可能性を保ちながら旧pathをcanonicalに残さない。
- **Trade-offs**: 各boundaryのdiffは大きいが、責務とrollback pointが明確になる。
- **Follow-up**: Task generationでboundaryごとにcommit/checkpointを分ける。

## Synthesis

- **Generalization**: Dependency、quality、CI、documentationの問題はすべて「artifact ownerとorchestration ownerの混同」として統一できる。Rootはinvoke/policy、workspaceはruntime/build/test/docを所有する。
- **Build vs. Adopt**: Workspace resolution、task execution、environment composition、process lifecycleは既存のuv、Just、Nix Flake、process-composeを採用し、独自package manager/task runner/process supervisorは作らない。
- **Simplification**: 初回はserverとcryptoだけをmemberとし、Web、pnpm、system test、generic shared package、workspace別Flake/Just、PP bindingを作らない。

## Risks & Mitigations

- Path-bearing fixture/catalog/allowlistの更新漏れ — ownership boundaryごとにtargeted `rg` auditとfull quality/test gateを行う。
- Git moveでhistoryまたはreviewabilityが低下 — pure moveとsemantic config changeを可能な範囲で別checkpointにし、old/new pathを同時に残さない。
- Root quality/testからworkspaceが漏れる — target pathをroot policyへ明示し、server/crypto/toolsの独立jobまたはrecipeを持つ。
- Config path変更がinstalled runtimeへ影響 — environment variable priorityを維持し、source checkoutのenv-file defaultだけをserver project rootへ固定してarbitrary-CWD testを追加する。
- Crypto stubがwheelへ入らない — built wheel contentsとtype-aware importをCIで検証する。
- Completed Kiro specのhistorical evidenceを誤って書き換える — normative/active資料とhistorical snapshotをlifecycle policyで区別する。
- Cloudflare設定不足がcore devを停止する — tunnel processをoptional profileへ分離し、core profile testをcredentialなしで実行する。

## References

- `docs/adr/0013-organize-monorepo-apps-by-product-boundary.md` — product、test、docs、tool ownership。
- `docs/adr/0014-compose-nix-environments-from-workspace-modules.md` — Nix、Just、CI parity、side-effect policy。
- `docs/adr/0015-provide-local-and-cloudflare-development-ingress.md` — local/tunnel profile。
- `docs/adr/0016-use-apex-domain-for-web-app.md` — frontend routing activation boundary。
- `docs/monorepo-layout.md` — target treeとmigration boundaries。
- `pyproject.toml`、`athena-crypto/pyproject.toml`、`flake.nix`、`process-compose.yml` — current implementation evidence。
