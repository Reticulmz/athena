# ADR 0007: Treat Web App API as an Exposed First-Party Surface

## Status
Accepted (2026-06-17)

## Context
Athena Web App needs API endpoints that are convenient for first-party browser workflows, but hiding those endpoints is not a reliable security boundary because browser traffic can be inspected and replayed. The main alternatives were to treat the Web App API as an internal/private API, or to design it as a first-party-only API surface that is still exposed to clients.

## Decision
Athena will treat the Web App API as a first-party-only but exposed API surface. It is not part of the externally documented Public API compatibility contract, but it must be protected as if callers can discover and replay requests.

## Consequences
Public API, Web App API, and Admin/Ops API are separate surfaces with different compatibility guarantees and documentation scope. Security for Web App and Admin/Ops workflows comes from authentication, authorization, CSRF protection, audit logging, and operator-intent checks rather than route secrecy. Web App API routes use same-origin `/api/web/*` and are forwarded by reverse proxy or Starlette routing to the FastAPI Web App API surface to avoid unnecessary CORS and cookie-scope complexity. Domain mutation remains behind Python command/query use-cases reached through FastAPI/OpenAPI contracts.
