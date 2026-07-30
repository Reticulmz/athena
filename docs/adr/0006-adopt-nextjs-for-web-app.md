# ADR 0006: Adopt Next.js App Router for Athena Web App

## Status
Accepted (2026-06-17, reaffirmed 2026-07-30)

## Context
Athena Web App は Public、User、Admin、Ops workflows を統合する first-party Web App として monorepo 内に置きます。Frontend framework は Next.js App Router、TanStack Router、TanStack Start が候補でした。

2026-07-30 に TanStack Start を再評価しました。TanStack Start は typed routing、typed search params、Vite/Rsbuild、明示的な loader、TanStack Query integration で優れた開発体験を提供しますが、公式には Release Candidate であり、公開された LTS、security backport、maintained version policy を確認できませんでした。Next.js 16.x は Active LTS で、upgrade command、codemod、Node/Docker self-host、multi-instance deployment の公式資料を提供しています。調査根拠は [TanStack StartとNext.jsの評判比較調査](../research/tanstack-start-vs-nextjs-reputation-2026-07-30.md) に記録します。

## Decision
Athena Web App の初期frameworkはNext.js App Routerとします。TanStack Router / TanStack Start は初期基盤にはせず、TanStack Query は Next.js 内で client-side cache や mutation 管理が必要になった場合の補助ライブラリ候補として扱います。

UI component systemはこのADRのscopeに含めません。HeroUIを確定dependencyとして扱わず、shadcn/uiを含む候補は実際のWeb workflow、design system、accessibility、component ownership、upgrade方針を設計する時点で別途決定します。

この判断は Next.js の既存採用コストを守るためではなく、Athena が FastAPI、OpenAPI、server-side session、authorization を source of truth とするため TanStack Start の Server Functions による差別化価値が小さく、現時点では Next.js の support と self-host 運用の予測可能性が上回るため維持します。

## Consequences
Athena backend の source of truth は Python の Starlette + FastAPI に置き、Next.js を domain backend にはしません。Web App は OpenAPI generated client / WebUI 専用 API contract 経由で backend に接続し、Next.js の Route Handler / Server Actions は cookie、session、CSRF、軽い response shaping などの thin frontend / BFF 補助処理に限定します。Domain mutation の正規経路や public API contract は FastAPI + OpenAPI に置きます。

TanStack Start は恒久的に却下しません。公式 status が GA となり、maintained version と security backport policy が公開され、Node/Nitro production integration と version upgrade support が成熟した場合に再評価します。再評価では同一の OpenAPI client、session cookie、CSRF、SSR route、Admin table を使い、build、navigation、memory、rolling deployment、error observability を比較します。
