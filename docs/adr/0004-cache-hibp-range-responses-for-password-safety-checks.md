# Cache HIBP range responses for password safety checks

Athena treats compromised-password detection as a synchronous Password Safety Check for account creation and future self-service password changes, instead of moving the decision to worker-side post-registration audit. To protect registration responsiveness without sending password-derived secrets through durable job payloads, Athena caches successful HIBP `/range/{prefix}` response bodies in Valkey for 24 hours and compares the SHA-1 suffix only in request-local memory. If HIBP or the cache is unavailable, Athena fails open for the external compromised-password check while still enforcing local password policy and custom banned-password lists.

**Considered Options**

- Synchronous HIBP check without cache: simple, but every cache miss pays external API latency.
- Worker-side post-registration audit: keeps registration fast, but changes the user-visible contract and risks placing password-derived data in job payloads, logs, retries, or monitoring.
- Cache individual password verdicts: fast, but stores credential-derived verdicts rather than the k-anonymity range data already returned by HIBP.

**Consequences**

Registration may accept a compromised password during HIBP or Valkey outages, by design. Logs and metrics may record cache hit/miss and fail-open reasons, but must not include password text, SHA-1 prefixes or suffixes, or HIBP response bodies.
