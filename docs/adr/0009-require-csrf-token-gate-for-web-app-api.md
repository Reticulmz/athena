# ADR 0009: Require CSRF Token Gate for Web App API

## Status
Accepted (2026-06-17)

## Context
Athena Web App uses same-origin `/api/web/*` routes and FastAPI-issued server-side session cookies. SameSite=Lax reduces cross-site request risk, but it should not be the only control for state-changing browser requests.

## Decision
State-changing Web App API requests must pass an explicit CSRF token gate in addition to using HttpOnly, Secure, SameSite=Lax session cookies. Athena will use a synchronizer CSRF token bound to the active Web App Session state in Valkey. Route secrecy and SameSite behavior alone are not sufficient.

## Consequences
Web App API adapters must reject unsafe methods without a valid session-bound CSRF token before invoking command use-cases. Read-only requests can remain token-free unless a future threat model requires stricter handling. Next.js may help fetch or attach the CSRF token, but FastAPI owns token generation and validation at the Web App API boundary.
