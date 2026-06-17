# ADR 0006: Adopt Next.js App Router for Athena Web App

## Status
Accepted (2026-06-17)

## Context
Athena Web App は Public、User、Admin、Ops workflows を統合する first-party Web App として monorepo 内に置きます。HeroUI の採用は決定済みで、frontend framework は Next.js App Router、TanStack Router、TanStack Start が候補でした。

## Decision
Athena Web App の初期基盤は Next.js App Router + HeroUI とします。TanStack Router / TanStack Start は初期基盤にはせず、TanStack Query は Next.js 内で client-side cache や mutation 管理が必要になった場合の補助ライブラリ候補として扱います。

## Consequences
Athena backend の source of truth は Python の Starlette + FastAPI に置き、Next.js を domain backend にはしません。Web App は OpenAPI generated client / WebUI 専用 API contract 経由で backend に接続し、Next.js の Route Handler / Server Actions は cookie、session、CSRF、軽い response shaping などの thin frontend / BFF 補助処理に限定します。Domain mutation の正規経路や public API contract は FastAPI + OpenAPI に置きます。
