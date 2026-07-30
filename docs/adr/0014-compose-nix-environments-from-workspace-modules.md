# ADR 0014: Compose Nix environments from workspace modules

## Status
Accepted (2026-07-30)

## Context
Athenaはlinked Git worktreeごとにvirtual environment、runtime state、generated Git hook設定を分離する必要があります。Devenvはmonorepo importとGit root参照を提供しますが、linked worktree固有stateの分離をAthenaのcontractとして保証していません。現在のenvironmentにもworktree rootを明示的に解決する処理が必要です。

## Decision
Devenvは採用せず、repository rootの単一`flake.nix`と`flake.lock`をNix entrypointにします。Initial monorepo migrationではRoot Flakeが`apps/athena_server/default.nix`と`packages/athena_crypto/default.nix`をimportし、workspace固有のtoolchain、build、check定義を合成します。`apps/athena_web/default.nix`はfrontend workspace作成時に追加します。Workspaceごとの`flake.nix`とlockfileは作りません。

Root Flakeはfull workspace用のdefault dev shellに加え、存在するworkspaceへscopeを限定したdev shellを提供します。Initial migrationではserverとcryptoを提供し、Web shellはfrontend workspace作成時に追加します。Worktree固有のgenerated stateは各Git worktreeの`.state/`と`.venv/`に閉じ込め、primary checkoutや他のworktreeのpathを再利用しません。

Cross-workspace process graphはroot `process-compose.yml`をreview可能なsource of truthとして維持します。Initial migrationではPostgreSQL、Valkey、server、worker、reverse proxyとoptional ingressの起動順、readiness、shutdown、log lifecycleをprocess-composeが所有し、frontend workspace作成時にWeb processを同じgraphへ追加します。Nix moduleへ同じprocess graphを重複定義したり、Nix evaluationからYAMLを生成したりしません。Root Just recipeはprocess-composeの利用者向けinterfaceを提供します。

Root `justfile`をrepositoryで唯一のJust entrypointとします。Justはdevelopment、quality、test、build、release preparationなどのcross-workspace taskを公開し、実処理はuv、Cargo、Maturin、process-composeへ委譲します。Frontend workspace作成後はpnpmも委譲先に加えます。Workspaceごとの`justfile`は作らず、同じtool invocationをJustとecosystem manifestへ重複実装しません。Recipe数が増えた場合もroot管理のfragmentへ分割し、利用者のentrypointはrootに維持します。

LocalとCIのparity boundaryはNix invocationではなくJust recipeとします。Localでは`nix develop`内からJustを実行し、GitHub ActionsではCI向けにsetupしたuv、Rust toolchain、service containerから同じrecipeを実行します。Frontend workspace作成後はpnpm setupとcacheを該当jobへ追加します。CI workflowはecosystem commandや旧`scripts/ci.sh`を直接呼びません。別jobで`nix flake check`を実行し、Flake evaluation、workspace shell、Nix build/check定義を検証します。

`nix develop`はtoolchainとenvironment variableを提供するだけとし、repository state、dependency environment、Git hooks、OS trust storeを変更しません。Dependency sync、`.state/`初期化、local certificate生成、Git hook設定は明示的な`just setup`が所有します。Cloudflare accountとcredentialを必要とする対話的初期化は`just tunnel-setup`へ分離します。Setup failureを無視せず、`just dev`は前提不足を検出した場合に必要なsetup commandを案内して失敗します。CI setupはlocal certificate、Cloudflare credential、Git hookを生成しません。

## Consequences
Nixはsystem toolchainとreproducible build/check environmentを所有し、uv、Cargo、将来追加するpnpmのecosystem dependency ownershipを奪いません。Workspace moduleは独立したNix projectではなくroot Flakeの構成要素なので、Nix inputとlock updateはrepository単位で行います。

Devenv固有のstate、task、service abstractionへ依存せず、linked worktreeのpathとstate lifecycleをAthena側で明示的に制御します。Nix、process-compose、Just、ecosystem package managerはそれぞれenvironment composition、process management、task interface、dependency/build metadataという別のsource of truthを所有します。CIはJust recipeを再利用しますが、全jobを`nix develop`へ強制せず、Actions cacheとservice integrationを利用できます。
