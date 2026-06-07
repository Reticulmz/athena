# Implementation Plan

- [ ] 1. Foundation: fixtures, shared prerequisites, and metadata lookup support
- [x] 1.1 Add decoded stable getscores fixtures and baseline compatibility tests
  - Capture official application bodies for Ranked, Loved, Qualified, Pending, WIP, Graveyard, NotSubmitted, and converted-mode requests without HTTP chunk framing.
  - Add failing tests that load the fixtures and assert request field meanings, status values, header shape, short response shape, and official-fixture precedence over reference implementation differences.
  - The completed state is visible when fixture tests can distinguish official response bodies from transport framing and cover every observed status fixture.
  - _Requirements: 1.3, 7.1, 8.1, 8.2, 9.1, 9.2, 9.4, 9.6, 9.7, 10.4, 11.8, 13.1, 13.2, 13.3, 13.4, 13.5_

- [x] 1.2 Add exact filename-within-beatmapset lookup support
  - Add the repository read capability needed to find an exact original `.osu` filename within a specific beatmapset.
  - Preserve checksum as the authoritative identity and keep beatmapset id from selecting a difficulty by itself.
  - Add persistence support only if existing metadata cannot satisfy the exact set-scoped filename lookup.
  - The completed state is visible when known checksum lookup remains unchanged and a stored filename can be resolved only within its matching beatmapset.
  - _Requirements: 3.2, 3.3, 4.3, 4.4, 4.6, 6.1, 6.3_

- [x] 1.3 Add or reuse legacy web credential authentication
  - Provide stable web authentication that accepts endpoint-extracted username and password md5 values.
  - Require active bancho session presence before serving getscores metadata.
  - Ensure `h` is not treated as the password field for getscores and credential values are redacted from diagnostics.
  - The completed state is visible when auth tests distinguish valid `us` / `ha` with active session, invalid credentials, missing credentials, no session, and ignored `h`.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 12.2_

- [ ] 2. Core getscores transport behavior
- [ ] 2.1 (P) Parse stable getscores query requests
  - Parse all observed query fields into a typed single-beatmap request while separating identity fields from parse-only controls.
  - Treat malformed non-identity fields as warnings and insufficient identity data as an unavailable outcome.
  - Preserve `v`, `vv`, `s`, `m`, and `mods` for future score rows without allowing them to change MVP header output.
  - The completed state is visible when parser tests cover observed queries, invalid checksum, missing identity, malformed non-identity fields, anti-cheat signal parsing, and beatmapset id hint semantics.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 12.1, 12.4_
  - _Boundary: GetscoresQueryParser_

- [ ] 2.2 (P) Format stable getscores status and response bodies
  - Map submitted and unavailable beatmap states to getscores wire values `-1`, `0`, `1`, `2`, `3`, `4`, and `5`.
  - Format unavailable, update-available, and known-header response bodies with `text/plain; charset=UTF-8` semantics.
  - Emit score count `0`, failed flag `false`, rating `0`, empty personal best, empty score rows, and sanitized artist/title values.
  - The completed state is visible when formatter tests assert fixture-compatible short bodies, header bodies, delimiter sanitization, no chunk framing, and no internal provenance fields.
  - _Requirements: 6.2, 7.1, 7.2, 7.3, 7.4, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8, 11.9, 12.5_
  - _Boundary: GetscoresFormatter, GetscoresStatusMapper_

- [ ] 3. Metadata resolution outcomes
- [ ] 3.1 Resolve checksum-first header and unavailable outcomes
  - Resolve by checksum before any filename or beatmapset hint, and prefer checksum results when request hints disagree.
  - Request metadata-only resolution with bounded wait for unknown checksum targets.
  - Return header, unavailable, pending-after-wait, or failed-metadata outcomes without consulting score state or requiring `.osu` file availability.
  - The completed state is visible when resolver tests prove known checksum returns immediately, conflicting hints do not override checksum, pending/failed metadata returns unavailable, and metadata-only options are used.
  - _Depends: 1.2, 2.1, 2.2_
  - _Requirements: 4.1, 4.2, 4.5, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 7.2, 7.3, 8.3, 12.3_

- [ ] 3.2 Resolve UpdateAvailable and set-scoped fallback outcomes
  - Detect update-available only when checksum misses and the same beatmapset plus exact filename identifies a submitted beatmap with a different checksum.
  - Avoid update-available from filename similarity or beatmapset id alone.
  - Make lookup conflicts and update-available outcomes observable to operators without changing stable response shape.
  - The completed state is visible when resolver tests cover update-available, filename collision across sets, set-id-only requests, NotSubmitted, unknown identity, and conflict diagnostics.
  - _Depends: 3.1_
  - _Requirements: 4.3, 4.4, 4.5, 6.1, 6.2, 6.3, 6.4, 7.1, 7.4, 12.3_

- [ ] 4. Endpoint integration and routing
- [ ] 4.1 Wire the getscores endpoint into the web legacy app
  - Register the getscores handler through the existing composition, lifespan, and service registration pattern.
  - Route `GET /web/osu-osz2-getscores.php` only on `osu.$DOMAIN` without adding a path-based fallback for other hosts.
  - Return `401` without beatmap data for auth failures and stable `200` bodies for unavailable, update-available, and known-header outcomes.
  - The completed state is visible when integration tests can reach the endpoint on the osu host, cannot reach it through non-osu fallback routing, and observe the expected status/body pairs.
  - _Depends: 1.3, 2.1, 2.2, 3.2_
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 7.5, 11.1, 11.6_

- [ ] 4.2 Add operator-observable diagnostics for getscores
  - Emit diagnostics for anti-cheat signal, parse warnings, invalid identity, lookup conflicts, unavailable outcomes, update-available outcomes, and auth failures.
  - Redact `ha`, `us` when needed, and raw credential values from all diagnostic events.
  - Ensure stable response bodies never include internal source, verification, policy, fetch-state, or override provenance fields.
  - The completed state is visible when tests or log assertions show diagnostic events without credential leakage or stable response contamination.
  - _Depends: 4.1_
  - _Requirements: 2.4, 4.5, 12.1, 12.2, 12.3, 12.4, 12.5_

- [ ] 5. Compatibility and behavior validation
- [ ] 5.1 Validate known submitted status fixtures end to end
  - Exercise Ranked, Loved, Qualified, Pending, WIP, and Graveyard fixtures through the endpoint with known metadata.
  - Assert status mapping, beatmap id, beatmapset id, score count `0`, failed flag `false`, display title formatting, rating `0`, and no score/personal-best rows.
  - The completed state is visible when all submitted status fixture integration tests pass and official behavior takes precedence over bancho.py differences.
  - _Depends: 4.2_
  - _Requirements: 8.1, 8.2, 8.4, 8.5, 8.6, 8.7, 8.8, 9.2, 9.4, 9.6, 9.7, 11.2, 11.3, 11.4, 11.5, 13.2, 13.3, 13.5_

- [ ] 5.2 Validate unavailable, update, auth, and parse-only paths end to end
  - Exercise NotSubmitted, unknown, pending-after-wait, failed metadata, missing identity, update-available, invalid credentials, and no-session cases.
  - Assert `m`, `mods`, `s`, `v`, and `vv` are preserved but do not vary MVP header output, including converted-mode fixture requests.
  - The completed state is visible when end-to-end tests pass for short responses, auth disclosure prevention, parse-only controls, and metadata-only resolution.
  - _Depends: 5.1_
  - _Requirements: 2.2, 2.3, 2.4, 3.8, 3.9, 5.2, 5.3, 5.5, 5.6, 5.7, 5.8, 6.1, 6.2, 7.1, 7.2, 7.3, 7.4, 10.4, 10.5, 10.6, 13.1, 13.2_

- [ ] 6. Final quality verification
- [ ] 6.1 Run focused and project quality checks for the endpoint
  - Run relevant unit and integration tests for web legacy getscores, auth, repository lookup, and beatmap mirror interaction.
  - Run formatter, linter, type checker, and migration checks for the changed areas.
  - Fix failures by addressing root causes rather than suppressing type or lint errors.
  - The completed state is visible when pytest, ruff, basedpyright, and any migration checks pass or unavailable external prerequisites are explicitly reported.
  - _Depends: 5.2_
  - _Requirements: 1.1, 1.3, 11.8, 13.1, 13.2, 13.4_
