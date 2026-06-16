# Implementation Gap Analysis: password-safety-check-cache

Generated at: 2026-06-17T05:44:49+09:00

## Context

Requirements are generated but not yet approved (`approvals.requirements.approved=false`). This analysis proceeds because gap validation can inform requirement revisions and the design phase.

Relevant decisions and glossary:

- `CONTEXT.md` defines Password Safety Check as a synchronous identity gate.
- `CONTEXT.md` separates Self-Service Password Change from Administrative Password Reset.
- `docs/adr/0004-cache-hibp-range-responses-for-password-safety-checks.md` records the chosen direction: synchronous check, range response reuse, 24 hour freshness, 1.0 second wait cap, fail-open on HIBP/cache unavailability, no worker-side audit.

Core steering constraints:

- Runtime dependency construction belongs in Dishka providers under `src/osu_server/composition/providers/`.
- Services should remain adapter independent and not reach into database or concrete runtime construction.
- Tests should prefer typed fakes/stubs over `AsyncMock`.
- Existing stack already includes `httpx` and `valkey-glide`; no new dependency appears necessary.

## Current State Investigation

### Existing registration and password flow

- `src/osu_server/services/commands/identity/auth_service.py`
  - `AuthService.register()` performs format validation, username/email availability checks, `PasswordService.is_password_banned()`, then password hashing and user creation.
  - `check_only=True` uses the same validation path before account creation.
  - The Password Safety Check is already synchronous for registration.
- `src/osu_server/services/queries/identity/password_service.py`
  - Owns `hash()`, `verify()`, `prepare_password()`, `check_hibp()`, and `is_password_banned()`.
  - Checks custom banned-password list before HIBP, so local list hits avoid external work.
  - Logs `password_banned` with `source=custom_list` or `source=hibp`.
- `src/osu_server/infrastructure/security/hibp.py`
  - Defines `HIBPClient` Protocol with `is_password_compromised(password: str) -> bool`.
  - `HTTPHIBPClient` hashes the password, sends only the SHA-1 5-character prefix to HIBP, then compares suffixes from the response body.
  - Catches `httpx.HTTPError` and returns `False`, so current external HIBP failures are effectively fail-open.
  - Does not have an explicit HIBP-specific timeout or evidence cache.
- `src/osu_server/composition/providers/identity.py`
  - Wires `PasswordService` with `HIBPClient` and `config.banned_passwords`.
  - App graph `ChangeUserPasswordCommandUseCase` also receives this `PasswordService`.
- `src/osu_server/composition/providers/infrastructure.py`
  - Provides process-wide `httpx.AsyncClient`.
  - Provides `HIBPClient` as `HTTPHIBPClient(http_client)`.
  - Provides app-scope `GlideClient`, currently used by session, packet queue, rate limiter, taskiq, and other runtime resources.
- `src/osu_server/composition/management.py`
  - The dev CLI password command builds `PasswordService(hibp_client=None, banned_passwords=config.banned_passwords)`.
  - This already matches the requirement that Administrative Password Reset/dev tooling is not made dependent on external compromised-password evidence.

### Existing Valkey patterns

- `src/osu_server/infrastructure/cache/valkey_client.py`
  - Central Glide client factory and database selection.
- `src/osu_server/repositories/valkey/session_store.py`
  - Uses `GlideClient.get()` for reads.
  - Uses Lua `Script` via `invoke_script()` for atomic `SET ... EX`, delete, refresh, and TTL-preserving updates.
- `src/osu_server/infrastructure/state/valkey/packet_queue.py`
  - Uses Lua `Script` for TTL-bearing queue state.
- `src/osu_server/infrastructure/state/valkey/rate_limiter.py`
  - Uses `incr()` and `expire()` directly.

There is no existing generic cache abstraction or HIBP-specific evidence cache. The closest established pattern is a small focused Valkey adapter with key helpers, explicit TTL, and tests against either a fake or integration Valkey.

### Existing tests and fakes

- `tests/unit/infrastructure/test_hibp.py`
  - Uses a typed `StubAsyncClient`, not `AsyncMock`.
  - Verifies prefix-only request, suffix matching, case-insensitive matching, and HTTP-error fail-open.
- `tests/unit/services/test_password_service.py`
  - Uses `FakeHIBPClient`.
  - Verifies custom list before HIBP and HIBP source logging.
- `tests/unit/services/test_auth_service.py`
  - Verifies registration rejects custom banned and HIBP-compromised passwords.
- `tests/support/fakes.py`
  - Contains `FakeHIBPClient` and other typed fakes.
- `tests/factories/config.py`
  - Typed `make_app_config()` factory will need fields added if HIBP timeout/cache settings become `AppConfig` values.
- Composition graph tests resolve `PasswordService` and app provider groups, so provider wiring changes should be covered.

### Existing privacy/logging surface

- `src/osu_server/infrastructure/logging.py`
  - Masks `password`, `password_hash`, and `password_md5` keys.
  - Does not currently mask `sha1_prefix`, `sha1_suffix`, `hibp_response`, or similar derived fields.
- Current HIBP implementation does not log prefix, suffix, response body, or password verdict details.
- New diagnostics can satisfy requirements by avoiding sensitive/derived fields entirely. Extending the sensitive-key mask is optional defense-in-depth, but not sufficient by itself.

## Requirement-to-Asset Map

| Requirement | Existing assets | Status / gap |
| --- | --- | --- |
| Req 1: Synchronous Password Safety Gate | `AuthService.register()`, `PasswordService.is_password_banned()`, `validate_plain_password()`, `FakeHIBPClient` tests | Mostly present. Missing only stronger naming/diagnostics around external evidence and assurance that future changes do not route verdict through worker. |
| Req 2: Evidence Freshness and Responsiveness | `HTTPHIBPClient`, app-scope `GlideClient`, Valkey TTL patterns | Missing. No range evidence cache, no 24h freshness setting, no explicit 1.0s HIBP wait cap, no cache hit path. |
| Req 3: Fail-Open Degradation | `HTTPHIBPClient` catches `httpx.HTTPError`; dev CLI has `hibp_client=None` | Partially present. External HTTP errors fail open, but cache read/write failures do not exist yet and operator-visible fail-open diagnostics are missing. |
| Req 4: Password Operation Scope | `composition/management.py` uses `hibp_client=None`; `ChangeUserPasswordCommandUseCase`; glossary/ADR | Partially present. Dev CLI is already external-evidence-free. Self-Service Password Change is not implemented and should remain future scope; current app graph change-password command is not a self-service API contract. |
| Req 5: Privacy and Operator Diagnostics | `mask_sensitive_fields`, current HIBP no-prefix logs, structlog tests | Partially present. Need safe diagnostic categories for cache hit/miss/new evidence/timeout/fail-open. Must avoid logging prefix/suffix/body/verdict cache keys. |

## Technical Gaps

### Missing capabilities

1. HIBP range evidence cache
   - No Protocol or adapter exists for `get_range(prefix)` / `store_range(prefix, body, ttl)` semantics.
   - No cache failure path currently exists.
   - No TTL/freshness tests exist for HIBP evidence.

2. HIBP-specific timeout
   - The shared `httpx.AsyncClient` is constructed without an Athena-level explicit HIBP timeout.
   - `HTTPHIBPClient` currently calls `get(url)` without a HIBP-specific timeout parameter.
   - Requirement needs a 1.0 second external evidence wait cap.

3. Diagnostic outcomes
   - Current logs only record `password_banned` on positive custom/HIBP matches.
   - Requirements need operator-visible categories for fresh evidence used, new evidence obtained, timeout, and fail-open.
   - Logging must not include prefix/suffix/body or per-password verdict.

4. Configuration shape
   - `AppConfig` has no HIBP timeout or evidence freshness settings.
   - Requirements use fixed values, but design must decide whether they are constants or config values.
   - If config values are added, tests/factories/config.py and config validation tests will need updates.

5. Composition graph integration
   - `InfrastructureProviderSet.hibp_client()` currently returns a plain `HTTPHIBPClient`.
   - Any new cache adapter or wrapper must be wired app-scope without affecting test overrides.
   - `PassingHIBPClient` test override should remain simple and should not require Valkey.

6. Typed test doubles
   - Current `FakeHIBPClient` only records plaintext password calls and returns bool.
   - Cache behavior is better tested below `PasswordService`, at infrastructure/wrapper level, with typed fake range cache or fake range provider.

### Constraints

- Do not route compromised-password decisions through jobs. The requirements and ADR explicitly reject worker-side audit for this feature.
- Do not place password-derived material in task payloads, logs, retries, or monitoring.
- Avoid repository placement for HIBP cache, because repositories are forbidden from HTTP clients and repository interfaces stay pure.
- Keep domain code independent from HIBP, Valkey, HTTP, and cache implementation. The domain glossary should keep `Password Safety Check`, not `HIBP`.
- Configuration edits are project-wide config changes and require explicit implementation-phase approval.

## Implementation Approach Options

### Option A: Extend `HTTPHIBPClient` directly

Add optional cache and timeout dependencies directly to `HTTPHIBPClient`, keeping the public `HIBPClient` Protocol unchanged.

Files likely touched:

- `src/osu_server/infrastructure/security/hibp.py`
- `src/osu_server/composition/providers/infrastructure.py`
- `src/osu_server/config.py` and `tests/factories/config.py` if settings are added
- `tests/unit/infrastructure/test_hibp.py`
- composition graph tests if provider wiring changes are visible

Pros:

- Smallest surface area.
- `PasswordService` and command/use-case layers do not change.
- Existing tests are close to the target behavior.

Cons:

- `HTTPHIBPClient` would own hashing, external HTTP, cache reads/writes, timeout, diagnostics, and fail-open policy in one class.
- Harder to test cache read failure, cache write failure, HTTP timeout, and response parsing independently.
- Single responsibility becomes weaker as more diagnostics are added.

Fit:

- Viable for a small patch, but likely to become crowded.

### Option B: Create separate range evidence components

Split responsibilities into explicit infrastructure pieces:

- A range evidence provider that fetches successful HIBP range response bodies.
- A range evidence cache that stores/reads response bodies with TTL.
- A policy/evaluator that hashes password, resolves cached/fetched range evidence, checks suffix, and returns bool.

Files likely touched:

- New files under `src/osu_server/infrastructure/security/` or `src/osu_server/infrastructure/cache/`
- `src/osu_server/infrastructure/security/hibp.py`
- `src/osu_server/composition/providers/infrastructure.py`
- config/tests if settings are added
- new unit tests for cache/provider/evaluator

Pros:

- Strong separation of concerns.
- Easy to unit-test cache failure, fetch failure, suffix matching, and diagnostics without network or Valkey.
- Better future path if HIBP is replaced or multiple compromised-password providers are added.

Cons:

- More files and interfaces for a narrow feature.
- Requires careful naming so implementation details do not leak into domain/service language.
- May be more abstraction than needed if HIBP remains the only provider.

Fit:

- Cleanest for long-term maintainability, but possibly heavy for the current scope.

### Option C: Hybrid wrapper around existing `HTTPHIBPClient` responsibilities

Keep `PasswordService` and `HIBPClient` Protocol unchanged, but introduce a focused cached HIBP implementation/wrapper:

- Keep suffix parsing/hash behavior in or near `HTTPHIBPClient`.
- Add a small `HIBPRangeEvidenceCache` Protocol/adapter for range bodies.
- Provide `CachedHIBPClient` or refactored `HTTPHIBPClient` with injected optional cache and timeout.
- Composition wires production HIBP as cached; tests can still override `HIBPClient` with `PassingHIBPClient`.

Files likely touched:

- `src/osu_server/infrastructure/security/hibp.py`
- Possibly new `src/osu_server/infrastructure/security/hibp_cache.py` or `src/osu_server/infrastructure/cache/hibp.py`
- `src/osu_server/composition/providers/infrastructure.py`
- `src/osu_server/config.py`
- `tests/factories/config.py`
- `tests/unit/infrastructure/test_hibp.py`
- new focused tests for cache behavior and diagnostics
- composition/provider graph tests if new dependency is resolvable

Pros:

- Preserves `PasswordService` and app command/query boundaries.
- Keeps test override simple because consumers still depend on `HIBPClient`.
- Gives cache behavior its own testable boundary.
- Avoids placing HTTP in repositories or services.

Cons:

- Needs a clear design decision on whether the wrapper or the HTTP client owns SHA-1 hashing and suffix matching.
- If over-split, can resemble Option B complexity.

Fit:

- Best balance for design phase based on current codebase.

## Effort and Risk

- Effort: M (3-7 days)
  - Existing registration flow and HIBP Protocol are already present.
  - Work spans infrastructure, composition, config/tests, logging diagnostics, and unit coverage.
- Risk: Medium
  - Main risks are credential-derived logging, fail-open correctness, cache failure behavior, and preserving test graph overrides.
  - No new third-party dependency is expected.

## Design Phase Recommendations

Preferred direction to evaluate first: Option C, a hybrid that preserves `HIBPClient` as the service-facing contract while adding a focused range evidence cache and HIBP-specific timeout behavior inside infrastructure/composition.

Key design decisions to make:

1. Cache abstraction placement
   - Candidate: infrastructure/security if treated as HIBP-specific evidence.
   - Candidate: infrastructure/cache if treated as generic cache adapter.
   - Avoid repositories for this feature.

2. Protocol shape
   - Keep `HIBPClient.is_password_compromised(password)` as the only service-facing contract.
   - Consider internal protocols for range cache/fetch only below infrastructure.

3. Timeout ownership
   - Decide whether timeout is a constant or `AppConfig` field.
   - If config-backed, add range validation and update `tests/factories/config.py`.
   - Requirement 2.4 sets a 1.0 second upper bound, so tuning must not allow values above 1.0 second without requirements/design revalidation.

4. Freshness ownership
   - Requirement says no longer than 24 hours.
   - Decide if this is a constant, config field, or constructor parameter from config.
   - If config-backed, tuning must not allow values above 86,400 seconds without requirements/design revalidation.

5. Diagnostics
   - Define safe event names and fields.
   - Suggested categories: cache hit, cache miss, external timeout, external unavailable, cache read unavailable, cache write unavailable, fail-open.
   - Do not log SHA-1 prefix/suffix/body or verdict cache details.
   - Consider extending `mask_sensitive_fields` for defense-in-depth only if logs might accidentally use derived names.

6. Valkey implementation detail
   - Existing code verifies Lua `Script` + `SET ... EX` is an established TTL pattern.
   - Design should verify the exact preferred `valkey-glide` API for simple set-with-expiry or choose the existing Lua pattern to avoid relying on unverified helper signatures.

7. Test plan
   - Unit tests for cache hit avoids HTTP.
   - Unit tests for cache miss fetches once and stores successful body.
   - Unit tests for stale/missing evidence follows timeout/fail-open behavior.
   - Unit tests for cache read/write failures fail open or use current evidence as required.
   - Unit tests that diagnostics do not include password, prefix, suffix, or body.
   - Existing registration tests should still pass with fake HIBP.
   - Composition tests should ensure production graph can resolve the cached HIBP client while test override remains simple.

## Research Needed

- Verify exact `valkey-glide` 2.4.0 typed API for set-with-expiry if avoiding Lua scripts.
- Verify exact `httpx` 0.28.1 per-request timeout call shape if implementing timeout directly on `AsyncClient.get()`.
- Decide whether HIBP timeout/cache TTL are config-backed or constructor constants before editing `AppConfig`.
- Decide whether future Self-Service Password Change should get a new use-case name now in design notes or remain an adjacent future requirement only.

---

# Design Discovery and Synthesis

Generated at: 2026-06-17T06:12:38+09:00

## Summary

- **Feature**: `password-safety-check-cache`
- **Discovery Scope**: Extension
- **Key Findings**:
  - Existing registration already performs the Password Safety Check synchronously through `AuthService.register()` and `PasswordService.is_password_banned()`.
  - `httpx` 0.28.1 supports per-request `timeout=` on `AsyncClient.get()`, so the HIBP 1.0 second wait cap can be local to HIBP.
  - `valkey-glide` 2.4.0 supports `GlideClient.set(..., expiry=ExpirySet(ExpiryType.SEC, ttl))`, so HIBP range cache writes do not require a Lua script.

## Research Log

### Existing Identity Integration Points

- **Context**: The design must preserve registration behavior while adding freshness and timeout semantics.
- **Sources Consulted**:
  - `src/osu_server/services/commands/identity/auth_service.py`
  - `src/osu_server/services/queries/identity/password_service.py`
  - `src/osu_server/composition/providers/identity.py`
  - `src/osu_server/composition/management.py`
- **Findings**:
  - Public registration already calls `PasswordService.is_password_banned()` before password hashing and durable user creation.
  - `check_only=True` uses the same registration validation path.
  - The dev CLI password management path constructs `PasswordService(hibp_client=None, ...)`, so external compromised-password evidence is already absent from Administrative Password Reset.
- **Implications**:
  - The service-facing `HIBPClient.is_password_compromised(password)` contract can remain unchanged.
  - No transport, job, or command use-case change is needed to satisfy the registration synchronization requirement.

### HIBP and HTTP Timeout API Verification

- **Context**: Requirement 2.4 requires a 1.0 second external evidence wait cap.
- **Sources Consulted**:
  - Local introspection with `uv run python` against installed `httpx` 0.28.1.
  - HIBP API v3 documentation: `https://haveibeenpwned.com/API/v3#SpecifyingTheUserAgent`
  - `src/osu_server/infrastructure/security/hibp.py`.
- **Findings**:
  - `httpx.AsyncClient.get()` has a keyword-only `timeout` parameter.
  - `httpx.Timeout` accepts a positional timeout value and explicit `connect`, `read`, `write`, and `pool` keyword values.
  - HIBP requires an identifying `User-Agent` header; missing user agent can be rejected with HTTP 403.
  - Existing `HTTPHIBPClient` catches `httpx.HTTPError` and already fails open for HTTP errors.
- **Implications**:
  - HIBP timeout can be applied per HIBP request instead of changing the shared `httpx.AsyncClient`.
  - `HTTPHIBPRangeProvider` must include a fixed safe `User-Agent` request header as part of its external API contract.
  - Timeout/unavailable categories should be surfaced as typed fetch statuses so diagnostics can distinguish them without logging password-derived data.

### Valkey Range Cache API Verification

- **Context**: Requirement 2.2 requires fresh compromised-password range evidence to be reused for no longer than 24 hours.
- **Sources Consulted**:
  - Local introspection with `uv run python` against installed `valkey-glide` 2.4.0.
  - `src/osu_server/repositories/valkey/session_store.py`.
  - `src/osu_server/infrastructure/state/valkey/packet_queue.py`.
- **Findings**:
  - `GlideClient.get(key)` returns `bytes | None`.
  - `GlideClient.set(key, value, expiry=ExpirySet(ExpiryType.SEC, seconds))` is available.
  - Existing Valkey code uses explicit key helpers and TTL-bearing values.
- **Implications**:
  - The HIBP range cache can be a small focused Valkey adapter without repository involvement.
  - Cache values should be decoded/encoded as text response bodies; cache keys may include the SHA-1 prefix but must never be logged.

### Privacy and Diagnostics Surface

- **Context**: Requirement 5 requires operator-visible diagnostics without exposing credential-derived data.
- **Sources Consulted**:
  - `src/osu_server/infrastructure/logging.py`
  - `tests/unit/infrastructure/test_logging.py`
  - `tests/unit/services/test_password_service.py`
- **Findings**:
  - Existing sensitive masking covers `password`, `password_hash`, and `password_md5`.
  - Current HIBP code does not log prefix, suffix, response body, or safe verdicts.
  - `PasswordService` logs only positive `password_banned` source events.
- **Implications**:
  - New HIBP diagnostics should avoid including prefix/suffix/body fields entirely.
  - Extending the masking key list for SHA-1 and HIBP body field names is useful defense-in-depth but cannot replace safe event design.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
| --- | --- | --- | --- | --- |
| Extend `HTTPHIBPClient` directly | Add cache, timeout, and diagnostics into the existing class | Smallest file count | One class owns HTTP, hashing, cache, diagnostics, and fail-open policy | Rejected as too crowded |
| Full range evidence subsystem | Separate provider, cache, evaluator, and HIBP facade | Cleanest boundaries | More abstractions than the current scope needs | Deferred unless HIBP becomes multi-provider |
| Hybrid cached HIBP facade | Keep `HIBPClient` stable; add internal range provider/cache contracts below infrastructure | Preserves service boundary, testable cache behavior, no new dependency | Requires careful file ownership | Selected |

## Design Decisions

### Decision: Preserve `HIBPClient` as the Service-Facing Contract

- **Context**: `PasswordService` and identity commands already depend on `HIBPClient`.
- **Alternatives Considered**:
  1. Change `PasswordService` to call a richer Password Safety Check service.
  2. Preserve `HIBPClient` and implement range evidence behavior behind it.
- **Selected Approach**: Preserve `HIBPClient.is_password_compromised(password)` and make the cached implementation an infrastructure detail.
- **Rationale**: Registration and password command boundaries do not need cache or provider details.
- **Trade-offs**: The method name remains HIBP-specific, but the blast radius is low and existing tests/fakes stay useful.
- **Follow-up**: If multiple compromised-password providers are later added, introduce a new provider-neutral service-facing Protocol.

### Decision: Use a Focused Valkey Range Cache Adapter

- **Context**: Requirements need 24 hour reuse of range evidence and fail-open on cache unavailability.
- **Alternatives Considered**:
  1. Store range bodies inside `HTTPHIBPClient`.
  2. Add a repository for HIBP evidence.
  3. Add a focused infrastructure cache adapter.
- **Selected Approach**: Add a focused HIBP range cache adapter under infrastructure, using Valkey `GET` and `SET` with expiry.
- **Rationale**: Repositories should not perform HTTP/cache infrastructure work, and the cache is not durable command/query persistence.
- **Trade-offs**: Adds one infrastructure file, but keeps the ownership clear.
- **Follow-up**: Verify typed tests cover cache read/write failures.

### Decision: Make Timeout and TTL Config-Backed Caps

- **Context**: Requirements cap the values at 1.0 second and 24 hours, but operational tuning may need shorter environment-specific values.
- **Alternatives Considered**:
  1. Hardcode constants in `CachedHIBPClient`.
  2. Add `AppConfig` fields with defaults and range validation.
- **Selected Approach**: Add config-backed caps: `hibp_timeout_seconds=1.0` with `0 < value <= 1.0`, and `hibp_range_cache_ttl_seconds=86400` with `0 < value <= 86400`.
- **Rationale**: This preserves the requirement caps while allowing only stricter deployment-specific tuning without code changes.
- **Trade-offs**: Implementation touches project-wide config and config tests, and operators cannot loosen the wait/freshness bounds without requirements/design revalidation.
- **Follow-up**: Add range validation and update `tests/factories/config.py`.

## Synthesis Outcomes

- **Generalization**: Requirements 2 and 3 are both range evidence resolution concerns. The design uses one `CachedHIBPClient` orchestration path with typed cache/fetch statuses rather than separate cache and fail-open flows.
- **Build vs Adopt**: Existing `httpx` and `valkey-glide` cover the HTTP and TTL cache needs. No new dependency is justified.
- **Simplification**: The design avoids a new Password Safety Check use-case and avoids worker jobs. It keeps service-facing behavior stable and confines cache/provider mechanics to infrastructure.
- **External API Contract**: HIBP-specific timeout and `User-Agent` requirements remain in `HTTPHIBPRangeProvider`, keeping them out of `PasswordService` and command use-cases.

## Risks & Mitigations

- Credential-derived data leakage — Use safe diagnostics with no prefix/suffix/body fields and add masking defense-in-depth for obvious SHA-1/HIBP field names.
- Cache outage hides HIBP result — Fail open by requirement, emit operator-visible diagnostic category.
- HTTP outage increases accepted compromised-password risk — Keep local password policy and custom banned list mandatory, emit timeout/unavailable diagnostics.
- Config drift — Range validation for HIBP timeout and TTL prevents zero, negative, or requirement-exceeding wait/cache windows.
- HIBP request rejection due to missing user agent — Treat `User-Agent` as an explicit provider contract and verify it in provider unit tests.
- Composition override regressions — Keep test provider override at `HIBPClient` so in-memory app graphs do not require production cache behavior.

## References

- `CONTEXT.md` — Password Safety Check, Self-Service Password Change, Administrative Password Reset glossary.
- `docs/adr/0004-cache-hibp-range-responses-for-password-safety-checks.md` — accepted architecture trade-off.
- `uv.lock` — `httpx` 0.28.1 and `valkey-glide` 2.4.0 resolved versions.
- HIBP API v3 documentation — `User-Agent` request requirement.
- Local introspection via `uv run python` — verified `httpx.AsyncClient.get(timeout=...)` and `GlideClient.set(expiry=ExpirySet(...))` signatures.
