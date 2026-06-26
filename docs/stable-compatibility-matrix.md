# Stable Compatibility Matrix

This document is the source-of-truth checklist for Athena's osu! stable
compatibility work. Its purpose is to prevent missing required stable packets,
legacy endpoints, request forms, and response formats while keeping the README
short.

Athena is still a proof of concept. A checked or implemented row means the
repository has code for that surface, not that the behavior is production-ready
or fully compatible with every stable client edge case.

## Source-Of-Truth Policy

Use this document as the input for GitHub Projects and implementation issues.
GitHub Projects should track execution state; this file should track the canonical
inventory.

Every stable compatibility item should eventually have:

- a stable packet, endpoint, request shape, or response shape identifier,
- an implementation status that describes runtime code state only,
- the owning module or planned module,
- reference paths from the relevant implementation family,
- verification evidence through tests, golden fixtures, or real-client probes.

Reference sources, in order of preference:

1. Lekuruu `bancho-documentation` wiki for Bancho packet IDs, primitive wire
   types, and struct layouts.
2. Observed stable client traffic.
3. Athena's own compatibility tests and fixtures.
4. Reference implementations listed below, split by stable surface ownership.
5. Athena design notes in `bancho_server_design.md` and `CONTEXT.md`.

Reference implementations are comparison targets, not architecture targets.
Athena should preserve compatible behavior without copying their process-global
state, large dispatch files, or persistence coupling.

## Release/Update Audit Row Contract

Release/update rows keep the existing `Status` column as runtime implementation
state. Audit policy is recorded separately so `Missing`, `Candidate`, or
`Implemented` is not overwritten by compatibility classification.

Use this structured note form in the row's Notes cell unless a future matrix
section explicitly adds dedicated columns:

```text
Audit: stable_compatibility_route_classification=<value>;
response_shape=<value>;
evidence_source=<source-list>;
stable_operational_dependency=<value>;
stable_fixture_requirement=<value>.
```

The audit fields have these meanings:

| Field | Meaning |
| --- | --- |
| `stable_compatibility_route_classification` | Stable compatibility policy for the route, such as `required-no-update`, `deferred`, or `needs-reference`. This is not the runtime implementation status. |
| `response_shape` | Selected client-observable response shape for no-update rows, or `deferred` when the response contract is intentionally not selected yet. |
| `evidence_source` | Source names used to justify the selected classification and response shape. Use `needs-reference` when evidence is insufficient. |
| `stable_operational_dependency` | Operational decision required before implementation, using the values below. This does not approve proxying or artifact hosting. |
| `stable_fixture_requirement` | Downstream fixture handoff state: shared fixture identifier, `deferred`, `not-required`, or `needs-reference`. |

### Release/Update Fixture Handoff Catalog

Use this catalog as the #17 fixture handoff source for release/update
no-update response contracts. Routes with the same no-update response bytes
reuse one fixture identifier. The `Source Row Fixture Requirement` value must
match the affected matrix row's `stable_fixture_requirement` audit field.

| Fixture Identifier | Routes | Response Shape | Source Row Fixture Requirement |
| --- | --- | --- | --- |
| `check_updates_no_update_json_array` | `/web/check-updates.php` | `[]` | `check_updates_no_update_json_array` |
| `release_no_update_empty` | `/release/update`, `/update`, `/release/update2.php`, `/update2.php`, `/release/patches.php`, `/patches.php` | empty body | `release_no_update_empty` |
| `release_update_php_zero` | `/release/update.php`, `/update.php` | `0` | `release_update_php_zero` |

Deferred release file/proxy routes keep fixture requirement `deferred` and have
no fixture identifier. #17 should not create placeholder fixture files or
identifiers for these routes.

| Fixture Requirement | Routes | Response Shape | Fixture Identifier |
| --- | --- | --- | --- |
| `deferred` | `/release/<filename>` | deferred file bytes | none |
| `deferred` | `/release/filter.txt` | deferred proxy response | none |
| `deferred` | `/release/Localisation/<filename>` | deferred proxy response | none |
| `deferred` | `/release/<language>/<filename>` | deferred file bytes | none |

### Operational Dependency Matrix

Use these operational dependency values for release/update audit rows:

| Value | Meaning |
| --- | --- |
| `none` | The audited policy does not require external proxying or hosted release artifacts. |
| `proxy-decision-required` | Implementing the route would require an explicit decision about external proxying. |
| `hosted-artifact-decision-required` | Implementing the route would require an explicit decision about Athena-hosted release artifacts. |

If evidence cannot support a stable route classification, set
`stable_compatibility_route_classification` to `needs-reference` and do not
invent a response contract. If a row appears to need both proxying and hosted
artifacts, keep it at `needs-reference` until evidence separates the
operational dependency.

### Release/Update Evidence Consistency Notes

The audited release/update rows are consistent with the guide's
`Update And Release Endpoints` section. Selected no-update response shapes use
guide-backed responses: `[]` for `/web/check-updates.php`, empty body for
`/release/update`, `/release/update2.php`, and `/release/patches.php`, and `0`
for `/release/update.php`. Root aliases share the corresponding release route
contracts recorded by the research decision.

Deferred release file, filter, and Localisation rows also match the guide's
file bytes or proxy behavior and keep `response_shape=deferred`. There are
currently no release/update `needs-reference` rows because every audited row
has an `evidence_source` field. Future release/update evidence gaps must be
left in the matrix as
`stable_compatibility_route_classification=needs-reference` and
`stable_fixture_requirement=needs-reference` rather than filled with guessed
response contracts.

## Reference Implementation Map

Use these repositories to audit stable packets, endpoints, request forms, and
response formats. Record the specific file path or route/handler name in the
relevant issue before implementing behavior.

| Repository | Use for | Notes |
| --- | --- | --- |
| `osuAkatsuki/bancho.py` | Integrated stable behavior across bancho packets and legacy web endpoints. | Treat as broad comparison coverage because it is an all-in-one server backend. Do not copy its global-state or large-dispatch structure. |
| `osuRipple/lets` | Legacy web endpoints, request parameters, and response body compatibility. | Use primarily for `/web/*.php` behavior and score/beatmap legacy forms. |
| `osuRipple/pep.py` | Bancho server packets and runtime session behavior. | Use primarily for C2S/S2C packet handling and online-state flows. |
| `osuTitanic/deck` | Legacy web endpoints, request parameters, and response body compatibility. | Use primarily as a modern stable client API comparison point. |
| `osuTitanic/titanic` | Bancho server packets and multi-client stable behavior. | Use primarily for packet coverage, session behavior, and long-tail client compatibility. |
| `sutekina/osu-gulag` | Avatar/static/media route variants and ppy/mirror proxy behavior. | Use as secondary evidence for static hosting choices, not as an architecture target. |
| `SunriseCommunity/Sunrise` | Avatar/static/media, direct, and update route variants in a C# implementation. | Use as secondary evidence for route aliases and request-key behavior. |

When references disagree, prefer observed stable client behavior. If traffic is
not available, compare at least two implementations and document the chosen
Athena behavior in the implementation issue.

## Status Labels

These labels describe the existing implementation or inventory status of a
stable surface. They are not the Issue #32 final audit classification for
legacy web-family endpoints. In particular, `Candidate` is a pre-audit input
status for rows derived from docs, traffic, or reference implementations.

| Status | Meaning |
| --- | --- |
| `Implemented` | The surface has a runtime implementation and at least basic verification. |
| `Partial` | The surface exists but key stable behavior is known to be missing. |
| `Builder` | S2C packet builder exists, but runtime emission may still be incomplete. |
| `Declared` | Packet ID exists in the enum, but payload parsing/building or runtime behavior is missing. |
| `Missing` | No meaningful implementation exists yet. |
| `Candidate` | Likely stable surface that needs confirmation from docs, traffic, or reference code. |
| `Out of scope` | Known surface intentionally excluded from the current stable scope. |

## Legacy Web Final Audit Classification Contract

Issue #32 records a second, final classification axis for legacy web-family
endpoint audit rows. Later matrix updates must keep this axis separate from the
status labels above: a row may start as `Candidate`, `Missing`, `Partial`, or
`Implemented`, but after audit its final classification must be exactly one of
the values below. Final audited rows must not use `candidate`.

| Final audit classification | Use when |
| --- | --- |
| `required` | Current osu!stable P0 core login/play traffic needs endpoint-specific real behavior, such as auth validation, durable mutation, read-model data, replay/file bytes, or leaderboard response content. A reference-only endpoint with no current osu!stable traffic evidence is not P0 `required`. |
| `compatibility no-op` | Current osu!stable compatibility needs the route and a confirmed empty, static, JSON, or sentinel response contract, but not dynamic behavior or durable state mutation. Unknown response shape cannot be `compatibility no-op`. |
| `deferred` | The endpoint is a plausible compatibility surface, but implementation is intentionally moved to a later milestone, operator policy, or product decision. The reason must be stated. |
| `out of scope` | The endpoint is intentionally excluded because it belongs to removed workflow, private-server-specific behavior, adjacent release/static/media/download scope, or Athena product scope outside this audit. The exclusion reason must be stated. |
| `needs reference evidence` | Request parameters, response body, error sentinel, auth behavior, or target-client traffic evidence is insufficient to choose another final classification. This is the safe classification for unknown response shape, unresolved alias variants, and reference-only endpoints that lack current osu!stable traffic evidence. |

Evidence that can move a row out of `needs reference evidence` is limited to
current osu!stable traffic, official or semi-official protocol docs, existing
reference implementations, or Athena focused fixtures/tests. When the evidence
does not confirm response shape, keep the row in `needs reference evidence`
instead of guessing `compatibility no-op`. When the evidence is only a reference
route with no current osu!stable traffic, do not mark it P0 `required`.

## Audit Classification And Evidence Notes

For the Bancho packet / struct audit, the existing `Status` label and the audit
classification are separate concepts. `Status` reports Athena's current
implementation maturity. Audit classification reports the compatibility
decision for that row:

- `required`: Athena should cover the row for stable compatibility. Note the
  exact source name or evidence that makes the row required.
- `deferred`: The row is stable-relevant, but intentionally not pursued in the
  current pass. Note the stable compatibility deferral reason and the trigger
  for revisiting it.
- `out of scope`: The row is excluded from the current stable scope. Note the
  exclusion reason, such as non-Bancho sibling inventory or an unsupported
  compatibility family.
- `needs reference evidence`: The row cannot be classified confidently yet.
  Note the evidence gap and required audit type: `needs-doc-audit`,
  `needs-reference-implementation-audit`, or `needs-traffic-capture`.

Row notes for C2S packet, S2C packet, and Bancho struct audit rows should make
the following facts readable in compact clauses:

- `classification`: one of `required`, `deferred`, `out of scope`, or
  `needs reference evidence`.
- `evidence`: the proof, deferral reason, exclusion reason, or unresolved
  evidence gap behind the classification.
- `exact source`: exact source name for the cited proof, such as a Lekuruu page
  name, reference implementation repository/path or handler, Athena test path,
  fixture path, or redacted traffic capture name. Avoid vague names such as
  "wiki" or "reference implementation".
- `verification`: verification status, using `none`, `unit`, `integration`,
  `fixture`, or `real-client-probe` when known.
- `fixture blocker`: `none` or `#17: <reason>`. A fixture blocker without an
  exact source remains `needs reference evidence`; fixture gaps are recorded as
  blockers, not completed fixture extraction.

Implementation gaps and fixture gaps are recorded in notes, not completed by
this audit. A `Missing` or `Partial` row can still be `required`, while an
`Implemented` or `Builder` row can still block #17 until exact source and
verification evidence are confirmed. S2C rows must keep builder availability
separate from runtime emission.

## Current Stable Surfaces

These surfaces are tracked by `src/athena_cli/stable_verification/catalog.py`.

| Surface | Status | Evidence |
| --- | --- | --- |
| Registration | Implemented | `tests/integration/test_registration_flow.py` |
| Bancho login | Implemented | `tests/integration/test_login_flow.py` |
| Packet polling | Implemented | `tests/integration/test_polling_e2e.py` |
| Chat | Implemented | `tests/integration/test_chat_e2e.py` |
| Getscores | Partial | known leaderboard row gap, getscores fixtures |
| Score submit | Partial | known rank/user-stat projection gaps |
| Akatsuki Relax/Autopilot leaderboards | Missing | compatibility extension; `bancho.py` separates vanilla, Relax, and Autopilot mode families. |

## Bancho Packet / Struct Audit Boundary

Scope Boundary Checklist for GitHub Issue #33:

This audit-only section does not complete packet parser, packet builder, packet
handler, runtime behavior, golden fixture file, fixture extraction, fixture
validation, or real-client traffic capture work.

| Area | #33 audit treatment | Out-of-scope handling |
| --- | --- | --- |
| C2S packet rows | Required audit rows in C2S Packet Coverage. | Record status, evidence, and blockers only; parser and handler work is not complete in this audit-only task. |
| S2C packet rows | Required audit rows in S2C Packet Coverage. | Record builder and runtime behavior gaps separately; packet builder work and runtime emission work are not complete in this audit-only task. |
| Bancho struct rows | Required audit rows in Bancho Struct Coverage. | Record source, missing field/value evidence, and packet dependencies only; struct implementation work is not complete in this audit-only task. |
| Parent #16 sibling inventory | Context only for the broader stable compatibility inventory. | `/web`, static/media, release/update, persistence, and other non-Bancho rows are not required audit rows for #33. |
| Downstream #17 fixture extraction | Consumer only for fixture blockers identified by #33. | Golden fixture file creation, fixture extraction completion, fixture validation, and real-client traffic capture remain outside this audit-only task. |

## C2S Packet Coverage

Current enum source: `ClientPacketID` in
`src/osu_server/transports/stable/bancho/protocol/enums.py`.

| ID | Packet | Status | Notes |
| --- | --- | --- | --- |
| 0 | `STATUS_CHANGE` | Partial | Decoded for beatmap file warmup; full presence and user-stat propagation is missing. Lekuruu packet file is named `ChangeStatus`; `STATUS_CHANGE` is Athena's alias. Audit: classification=required; evidence=guide lists this row in the payload reference and Status And Presence processing, while `StatusChangeHandlers` only implements beatmap warmup; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Status And Presence, `src/osu_server/transports/stable/bancho/handlers/status.py`, `tests/unit/transports/bancho/test_status_handlers.py`; verification=unit; payload=confirmed:StatusUpdate; fixture blocker=none. |
| 1 | `SEND_MESSAGE` | Implemented | Channel message handler exists. Audit: classification=required; evidence=guide lists this row in Chat And Channels processing and `ChatHandlers.handle_send_message` is registered; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Chat And Channels, `src/osu_server/transports/stable/bancho/handlers/chat.py`, `tests/integration/test_chat_e2e.py`; verification=integration; payload=confirmed:Message; fixture blocker=none. |
| 2 | `EXIT` | Partial | Session cleanup and disconnect event exist, but the payload is not parsed or validated. Audit: classification=required; evidence=guide lists `sInt is_updating` while `LifecycleHandlers.handle_exit` ignores `_payload` and current e2e coverage exercises disconnect cleanup; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, `src/osu_server/transports/stable/bancho/handlers/lifecycle.py`, `tests/e2e/test_c2s_e2e.py`; verification=integration; payload=confirmed:sInt is_updating; parser gap=EXIT payload validation and golden bytes are missing; fixture blocker=#17: EXIT payload golden bytes are needed before treating parser coverage as complete. |
| 3 | `REQUEST_STATUS` | Missing | Needed for targeted status refresh. Audit: classification=required; evidence=guide lists this row in Status And Presence processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Status And Presence, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:empty; fixture blocker=none. |
| 4 | `PONG` | Implemented | Keepalive no-op exists. Audit: classification=required; evidence=guide lists this row in the payload reference and `LifecycleHandlers.handle_pong` is registered as a quiet keepalive handler; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, `src/osu_server/transports/stable/bancho/handlers/lifecycle.py`, `src/osu_server/transports/stable/bancho/dispatch.py`, `tests/e2e/test_c2s_e2e.py`; verification=integration; payload=confirmed:empty; fixture blocker=none. |
| 16 | `START_SPECTATING` | Missing | Spectator state and frame relay missing. Audit: classification=required; evidence=guide lists this row in Spectator required processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Spectator, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:sInt user_id; fixture blocker=none. |
| 17 | `STOP_SPECTATING` | Missing | Spectator state and notifications missing. Audit: classification=required; evidence=guide lists this row in Spectator required processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Spectator, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:empty; fixture blocker=none. |
| 18 | `SEND_FRAMES` | Missing | Spectator frame relay missing. Audit: classification=required; evidence=guide lists this row in Spectator frame relay processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Spectator, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:ReplayFrameBundle; fixture blocker=#17: ReplayFrameBundle golden encode/decode bytes are needed before spectator frame parser work; source gap=Fixture Extraction Backlog has no extracted ReplayFrameBundle bytes. |
| 20 | `ERROR_REPORT` | Missing | Client error-report ingestion missing. Audit: classification=needs reference evidence; evidence=needs-reference-implementation-audit because guide confirms the packet row and enum membership, but no source here defines server-side ingestion behavior and no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:String error_report; next-audit=needs-reference-implementation-audit; fixture blocker=none. |
| 21 | `CANT_SPECTATE` | Missing | Spectator failure propagation missing. Audit: classification=required; evidence=guide lists this row in Spectator failure handling, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Spectator, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:empty; fixture blocker=none. |
| 25 | `SEND_PRIVATE_MESSAGE` | Implemented | Private message handler exists. Audit: classification=required; evidence=guide lists this row in Chat And Channels processing and `ChatHandlers.handle_send_private_message` is registered; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Chat And Channels, `src/osu_server/transports/stable/bancho/handlers/chat.py`, `tests/integration/test_chat_e2e.py`; verification=integration; payload=confirmed:Message; fixture blocker=none. |
| 29 | `PART_LOBBY` | Missing | Multiplayer lobby missing. Audit: classification=required; evidence=guide lists this row in Multiplayer lobby processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:empty; fixture blocker=none. |
| 30 | `JOIN_LOBBY` | Missing | Multiplayer lobby missing. Audit: classification=required; evidence=guide lists this row in Multiplayer lobby processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:empty; fixture blocker=none. |
| 31 | `CREATE_MATCH` | Missing | Multiplayer match lifecycle missing. Audit: classification=required; evidence=guide lists this row in Multiplayer match lifecycle processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:Match; fixture blocker=#17: Match golden encode/decode bytes are needed before multiplayer create parser work; source gap=Fixture Extraction Backlog has no extracted Match bytes. |
| 32 | `JOIN_MATCH` | Missing | Multiplayer match lifecycle missing. Audit: classification=required; evidence=guide lists this row in Multiplayer match lifecycle processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:MatchJoin; fixture blocker=#17: MatchJoin golden encode/decode bytes are needed before multiplayer join parser work; source gap=Fixture Extraction Backlog has no extracted MatchJoin bytes. |
| 33 | `LEAVE_MATCH` | Missing | Multiplayer match lifecycle missing. Audit: classification=required; evidence=guide lists this row in Multiplayer match lifecycle processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:empty; fixture blocker=none. |
| 38 | `MATCH_CHANGE_SLOT` | Missing | Multiplayer slot state missing. Audit: classification=required; evidence=guide lists this row in Multiplayer slot processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:sInt slot_id; fixture blocker=none. |
| 39 | `MATCH_READY` | Missing | Multiplayer ready state missing. Audit: classification=required; evidence=guide lists this row in Multiplayer ready-state processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:empty; fixture blocker=none. |
| 40 | `MATCH_LOCK` | Missing | Multiplayer slot lock state missing. Audit: classification=required; evidence=guide lists this row in Multiplayer host-only lock processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:sInt slot_id; fixture blocker=none. |
| 41 | `MATCH_CHANGE_SETTINGS` | Missing | Multiplayer match settings missing. Audit: classification=required; evidence=guide lists this row in Multiplayer settings processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:Match; fixture blocker=#17: Match golden encode/decode bytes are needed before multiplayer settings parser work; source gap=Fixture Extraction Backlog has no extracted Match bytes. |
| 44 | `MATCH_START` | Missing | Multiplayer start flow missing. Audit: classification=required; evidence=guide lists this row in Multiplayer start processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:empty; fixture blocker=none. |
| 47 | `MATCH_SCORE_UPDATE` | Missing | Multiplayer live score update missing. Audit: classification=required; evidence=guide lists this row in Multiplayer score-frame processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:28-byte client ScoreFrame; fixture blocker=#17: client ScoreFrame golden bytes are needed before multiplayer score-update parser work; source gap=Fixture Extraction Backlog has no extracted client ScoreFrame bytes. |
| 49 | `MATCH_COMPLETE` | Missing | Multiplayer completion flow missing. Audit: classification=required; evidence=guide lists this row in Multiplayer completion processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:empty; fixture blocker=none. |
| 50 | `MATCH_CHANGE_BEATMAP` | Missing | Multiplayer beatmap state missing. Audit: classification=required; evidence=guide lists this row in Multiplayer beatmap-state processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:Match; fixture blocker=#17: Match golden encode/decode bytes are needed before multiplayer beatmap-change parser work; source gap=Fixture Extraction Backlog has no extracted Match bytes. |
| 51 | `MATCH_CHANGE_MODS` | Missing | Multiplayer mod state missing. Audit: classification=required; evidence=guide lists this row in Multiplayer mod-state processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:4-byte Mods bitmask; fixture blocker=none. |
| 52 | `MATCH_LOAD_COMPLETE` | Missing | Multiplayer load state missing. Audit: classification=required; evidence=guide lists this row in Multiplayer load-state processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:empty; fixture blocker=none. |
| 54 | `MATCH_NO_BEATMAP` | Missing | Multiplayer beatmap availability state missing. Audit: classification=required; evidence=guide lists this row in Multiplayer beatmap-availability processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:empty; fixture blocker=none. |
| 55 | `MATCH_NOT_READY` | Missing | Multiplayer ready state missing. Audit: classification=required; evidence=guide lists this row in Multiplayer ready-state processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:empty; fixture blocker=none. |
| 56 | `MATCH_FAILED` | Missing | Multiplayer failure state missing. Audit: classification=required; evidence=guide lists this row in Multiplayer failure-state processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:empty; fixture blocker=none. |
| 59 | `MATCH_HAS_BEATMAP` | Missing | Multiplayer beatmap availability state missing. Audit: classification=required; evidence=guide lists this row in Multiplayer beatmap-availability processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:empty; fixture blocker=none. |
| 60 | `MATCH_SKIP` | Missing | Multiplayer skip vote flow missing. Audit: classification=required; evidence=guide lists this row in Multiplayer skip processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:empty; fixture blocker=none. |
| 63 | `JOIN_CHANNEL` | Implemented | Channel join handler exists. Audit: classification=required; evidence=guide lists this row in Chat And Channels processing and `ChatHandlers.handle_join_channel` is registered; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Chat And Channels, `src/osu_server/transports/stable/bancho/handlers/chat.py`, `tests/integration/test_chat_e2e.py`; verification=integration; payload=confirmed:String channel_name; fixture blocker=none. |
| 68 | `BEATMAP_INFO` | Missing | Beatmap info reply flow missing. Audit: classification=required; evidence=guide lists this row in Beatmap Info Packet Flow required processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Beatmap Info Packet Flow, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:BeatmapInfoRequest; fixture blocker=#17: BeatmapInfoRequest golden request bytes are needed before beatmap-info parser work; source gap=Fixture Extraction Backlog lists beatmap info fixtures but none are extracted. |
| 70 | `MATCH_TRANSFER_HOST` | Missing | Multiplayer host transfer missing. Audit: classification=required; evidence=guide lists this row in Multiplayer host-transfer processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:sInt slot_id; fixture blocker=none. |
| 73 | `ADD_FRIEND` | Implemented | Friend relationship command exists. Audit: classification=required; evidence=guide lists this row in Friends And PM Privacy processing and `FriendHandlers.handle_add_friend` is registered; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Friends And PM Privacy, `src/osu_server/transports/stable/bancho/handlers/friends.py`, `tests/integration/test_friend_relationship_pipeline.py`; verification=integration; payload=confirmed:sInt user_id; fixture blocker=none. |
| 74 | `REMOVE_FRIEND` | Implemented | Friend relationship command exists. Audit: classification=required; evidence=guide lists this row in Friends And PM Privacy processing and `FriendHandlers.handle_remove_friend` is registered; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Friends And PM Privacy, `src/osu_server/transports/stable/bancho/handlers/friends.py`, `tests/integration/test_friend_relationship_pipeline.py`; verification=integration; payload=confirmed:sInt user_id; fixture blocker=none. |
| 77 | `MATCH_CHANGE_TEAM` | Missing | Multiplayer team state missing. Audit: classification=required; evidence=guide lists this row in Multiplayer team-state processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:empty; fixture blocker=none. |
| 78 | `LEAVE_CHANNEL` | Implemented | Channel leave handler exists. Audit: classification=required; evidence=guide lists this row in Chat And Channels processing and `ChatHandlers.handle_leave_channel` is registered; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Chat And Channels, `src/osu_server/transports/stable/bancho/handlers/chat.py`, `tests/integration/test_chat_e2e.py`; verification=integration; payload=confirmed:String channel_name; fixture blocker=none. |
| 79 | `RECEIVE_UPDATES` | Missing | Presence/update subscription behavior missing. Audit: classification=required; evidence=guide lists this row in Status And Presence receive-update filtering, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Status And Presence, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:4-byte PresenceFilter; fixture blocker=none. |
| 82 | `SET_AWAY_MESSAGE` | Missing | Away message state missing. Audit: classification=required; evidence=guide lists this row in Chat And Channels away-message processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Chat And Channels, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:Message; fixture blocker=none. |
| 85 | `STATS_REQUEST` | Missing | Requested user stats response missing. Audit: classification=required; evidence=guide lists this row in Status And Presence requested-stat responses, but dispatcher only marks this quiet and no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Status And Presence, `src/osu_server/transports/stable/bancho/dispatch.py`, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; payload=confirmed:IntList player ids, 32 max; fixture blocker=none. |
| 87 | `MATCH_INVITE` | Missing | Multiplayer invite flow missing. Audit: classification=required; evidence=guide lists this row in Multiplayer invite processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:sInt user_id; fixture blocker=none. |
| 90 | `MATCH_CHANGE_PASSWORD` | Missing | Multiplayer password update missing. Audit: classification=required; evidence=guide lists this row in Multiplayer password processing, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:Match; fixture blocker=#17: Match golden encode/decode bytes are needed before multiplayer password-change parser work; source gap=Fixture Extraction Backlog has no extracted Match bytes. |
| 93 | `TOURNAMENT_MATCH_INFO` | Missing | Tournament support missing. Audit: classification=required; evidence=guide lists this row in Multiplayer tournament packet family, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:sInt match_id; fixture blocker=none. |
| 97 | `PRESENCE_REQUEST` | Implemented | Targeted presence response handler exists. Audit: classification=required; evidence=guide lists this row in Status And Presence targeted presence responses and `PresenceHandlers.handle_presence_request` returns `USER_PRESENCE` for requested online users through targeted session lookup; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Status And Presence, `src/osu_server/transports/stable/bancho/handlers/presence.py`, `src/osu_server/services/queries/identity/online_sessions.py`, `tests/unit/transports/bancho/test_presence_handlers.py`; verification=unit; payload=confirmed:IntList player ids, 256 max; fixture blocker=none. |
| 98 | `PRESENCE_REQUEST_ALL` | Implemented | Full presence response handler exists. Audit: classification=required; evidence=guide lists this row in Status And Presence full presence response and `PresenceHandlers.handle_presence_request_all` emits online `USER_PRESENCE` packets plus `USER_PRESENCE_BUNDLE`; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Status And Presence, `src/osu_server/transports/stable/bancho/handlers/presence.py`, `tests/unit/transports/bancho/test_presence_handlers.py`; verification=unit; payload=confirmed:empty-or-reserved-int32; fixture blocker=none. |
| 99 | `CHANGE_FRIENDONLY_DMS` | Implemented | Active-session DM preference update exists. Audit: classification=needs reference evidence; evidence=guide lists this row in Friends And PM Privacy processing and `FriendHandlers.handle_change_friendonly_dms` is registered, but exact payload width remains unresolved; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Friends And PM Privacy, `src/osu_server/transports/stable/bancho/handlers/friends.py`, `tests/integration/test_chat_pipeline.py`; verification=integration; payload=needs-reference:one-byte enabled flag conflicts with wiki sInt datatype label; next-audit=needs-traffic-capture; fixture blocker=#17: exact-width golden fixture is needed before treating the one-byte payload as confirmed; source gap=Fixture Extraction Backlog has no extracted CHANGE_FRIENDONLY_DMS bytes. |
| 108 | `TOURNAMENT_JOIN_MATCH_CHANNEL` | Missing | Tournament support missing. Audit: classification=required; evidence=guide lists this row in Multiplayer tournament packet family, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:sInt match_id; fixture blocker=none. |
| 109 | `TOURNAMENT_LEAVE_MATCH_CHANNEL` | Missing | Tournament support missing. Audit: classification=required; evidence=guide lists this row in Multiplayer tournament packet family, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:sInt match_id; fixture blocker=none. |

## S2C Packet Coverage

Canonical source: Lekuruu `bancho-documentation` wiki packet files and
`PacketEnums.md`. Cross-check Athena's `ServerPacketID` in
`src/osu_server/transports/stable/bancho/protocol/enums.py` before
implementation.

| ID | Packet | Status | Notes |
| --- | --- | --- | --- |
| 5 | `LOGIN_REPLY` | Builder | Login packet builder exists. Audit: classification=required; builder=implemented:login_reply; runtime=emitted:login-success-auth-failure-and-invalid-poll-token; evidence=dedicated builder is used by login and polling workflows; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, `src/osu_server/transports/stable/bancho/protocol/s2c/login.py`, `src/osu_server/transports/stable/bancho/workflows/login.py`, `src/osu_server/transports/stable/bancho/workflows/polling.py`, `tests/integration/test_login_flow.py`; verification=integration; fixture blocker=none. |
| 6 | `COMMAND_ERROR` | Missing | Builder and runtime behavior missing. Audit: classification=required; builder=missing; runtime=missing:command-error-emission; evidence=guide lists a no-payload row and enum exists, but no dedicated builder or call site exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/protocol/s2c/`; verification=none; fixture blocker=none. |
| 7 | `SEND_MESSAGE` | Builder | Chat delivery builder exists. Audit: classification=required; builder=implemented:send_message; runtime=emitted:channel-private-and-bancho-bot-chat; evidence=chat handlers enqueue the S2C builder for delivered messages and command responses; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Chat And Channels, `src/osu_server/transports/stable/bancho/protocol/s2c/chat.py`, `src/osu_server/transports/stable/bancho/handlers/chat.py`, `tests/integration/test_chat_e2e.py`; verification=integration; fixture blocker=none. |
| 8 | `PING` | Missing | Builder and runtime keepalive emission missing. Audit: classification=required; builder=generic-writer-only:empty-payload; runtime=missing:server-keepalive-emission; evidence=writer can encode the empty packet, but no dedicated keepalive builder or runtime call site exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, `src/osu_server/transports/stable/bancho/protocol/writer.py`, `tests/unit/transports/bancho/protocol/test_writer.py`; verification=unit; fixture blocker=none. |
| 9 | `IRC_CHANGE_USERNAME` | Missing | Rename flow missing. Audit: classification=required; builder=missing; runtime=missing:rename-notification-flow; evidence=guide lists a String payload row and enum exists, but no builder or runtime call site exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/protocol/s2c/`; verification=none; fixture blocker=none. |
| 10 | `IRC_QUIT` | Missing | Quit notification builder missing. Audit: classification=needs reference evidence; builder=missing; runtime=missing:irc-quit-notification-flow; evidence=guide lists a String payload row and lifecycle fanout currently emits `USER_QUIT` instead; evidence gap=payload reference and runtime fanout disagree on whether quit notification uses `IRC_QUIT` or `USER_QUIT`; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, `src/osu_server/transports/stable/bancho/workflows/presence_roster.py`, `src/osu_server/transports/stable/bancho/listeners/lifecycle.py`; verification=none; next-audit=needs-reference-implementation-audit; fixture blocker=none. |
| 11 | `USER_STATS` | Builder | Builder exists; full stats projection is incomplete. Audit: classification=required; builder=implemented:user_stats; runtime=partial:login-default-stats-only; evidence=login roster emits placeholder stats, while guide requires status/stat fanout and request responses; payload=confirmed:UserStats; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, Bancho Struct Field Reference, and Status And Presence, `src/osu_server/transports/stable/bancho/protocol/s2c/login.py`, `src/osu_server/transports/stable/bancho/workflows/presence_roster.py`, `tests/unit/transports/bancho/protocol/test_s2c_login.py`; verification=unit; next-audit=needs-traffic-capture; fixture blocker=#17: UserStats golden encode bytes and stat-projection fixtures are needed before expanding stat fanout beyond login placeholders; source gap=Fixture Extraction Backlog has no extracted UserStats bytes. |
| 12 | `USER_QUIT` | Partial | Athena broadcasts the old 4-byte user id form; modern stable adds a `QuitState` byte. Audit: classification=needs reference evidence; builder=partial:inline-old-form; runtime=emitted:disconnect-fanout-old-form; evidence=presence roster writes a 4-byte user id directly and lifecycle listener enqueues it on disconnect, but compatible payload shape remains unresolved; payload=needs-reference:old-user-id-only-vs-modern-user-id-plus-QuitState; evidence gap=runtime emits old form while payload reference requires modern `QuitState`; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Bancho Struct Field Reference, `src/osu_server/transports/stable/bancho/workflows/presence_roster.py`, `src/osu_server/transports/stable/bancho/listeners/lifecycle.py`, `tests/integration/test_c2s_pipeline.py`; verification=integration; next-audit=needs-traffic-capture; fixture blocker=#17: modern USER_QUIT golden bytes are needed before replacing the old-form fanout; source gap=Fixture Extraction Backlog has no extracted USER_QUIT bytes. |
| 13 | `SPECTATOR_JOINED` | Missing | Spectator support missing. Audit: classification=required; builder=missing; runtime=missing:spectator-join-fanout; evidence=guide lists user id payload but spectator runtime and builder are absent; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Spectator, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |
| 14 | `SPECTATOR_LEFT` | Missing | Spectator support missing. Audit: classification=required; builder=missing; runtime=missing:spectator-left-fanout; evidence=guide lists user id payload but spectator runtime and builder are absent; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Spectator, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |
| 15 | `SPECTATE_FRAMES` | Missing | Spectator support missing. Audit: classification=required; builder=missing; runtime=missing:spectator-frame-relay; evidence=guide lists ReplayFrameBundle payload but spectator frame relay and builder are absent; payload=confirmed:ReplayFrameBundle; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, Bancho Struct Field Reference, Spectator, and Fixture Extraction Backlog, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=#17: ReplayFrameBundle golden encode/decode bytes are needed before spectator frame builder work; source gap=Fixture Extraction Backlog has no extracted ReplayFrameBundle bytes. |
| 19 | `VERSION_UPDATE` | Missing | Update flow missing. Audit: classification=deferred; builder=generic-writer-only:empty-payload; runtime=non-emitted:no-update-policy-unless-client-traffic-requires-updater; non-emission=deferred-non-emission; evidence=guide lists a no-payload row and matrix update inventory records Athena's initial no-update/no-op policy; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, `docs/stable-compatibility-matrix.md` Stable HTTP Endpoint Coverage, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |
| 22 | `CANT_SPECTATE` | Missing | Spectator failure packet missing. Audit: classification=required; builder=missing; runtime=missing:spectator-failure-response; evidence=guide lists user id payload but spectator failure handling and builder are absent; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Spectator, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |
| 23 | `GET_ATTENTION` | Missing | Moderation/admin attention flow missing. Audit: classification=required; builder=generic-writer-only:empty-payload; runtime=missing:moderation-attention-flow; evidence=guide lists a no-payload row and enum exists, but no moderation/admin emission path exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |
| 24 | `ANNOUNCE` | Builder | Notification builder exists. Audit: classification=required; builder=implemented:notification; runtime=missing:no-notification-call-site; evidence=dedicated builder exists, but source search finds no runtime caller; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, `src/osu_server/transports/stable/bancho/protocol/s2c/login.py`; verification=unit; fixture blocker=none. |
| 26 | `MATCH_UPDATE` | Missing | Multiplayer support missing. Audit: classification=required; builder=missing; runtime=missing:multiplayer-match-update; evidence=guide lists Match payload but multiplayer runtime and builder are absent; payload=confirmed:Match; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, Bancho Struct Field Reference, Multiplayer, and Fixture Extraction Backlog, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=#17: Match golden encode/decode bytes are needed before multiplayer match-update builder work; source gap=Fixture Extraction Backlog has no extracted Match bytes. |
| 27 | `NEW_MATCH` | Missing | Multiplayer support missing. Audit: classification=required; builder=missing; runtime=missing:multiplayer-new-match; evidence=guide lists Match payload but multiplayer runtime and builder are absent; payload=confirmed:Match; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, Bancho Struct Field Reference, Multiplayer, and Fixture Extraction Backlog, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=#17: Match golden encode/decode bytes are needed before multiplayer new-match builder work; source gap=Fixture Extraction Backlog has no extracted Match bytes. |
| 28 | `MATCH_DISBAND` | Missing | Multiplayer support missing. Audit: classification=required; builder=missing; runtime=missing:multiplayer-disband; evidence=guide lists match id payload but multiplayer runtime and builder are absent; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |
| 34 | `LOBBY_JOIN` | Missing | Multiplayer lobby support missing. Audit: classification=required; builder=missing; runtime=missing:lobby-join-fanout; evidence=guide lists user id payload but multiplayer lobby runtime and builder are absent; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |
| 35 | `LOBBY_PART` | Missing | Multiplayer lobby support missing. Audit: classification=required; builder=missing; runtime=missing:lobby-part-fanout; evidence=guide lists user id payload but multiplayer lobby runtime and builder are absent; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |
| 36 | `MATCH_JOIN_SUCCESS` | Missing | Multiplayer support missing. Audit: classification=required; builder=missing; runtime=missing:multiplayer-join-success; evidence=guide lists Match payload but multiplayer runtime and builder are absent; payload=confirmed:Match; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, Bancho Struct Field Reference, Multiplayer, and Fixture Extraction Backlog, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=#17: Match golden encode/decode bytes are needed before multiplayer join-success builder work; source gap=Fixture Extraction Backlog has no extracted Match bytes. |
| 37 | `MATCH_JOIN_FAIL` | Missing | Multiplayer support missing. Audit: classification=required; builder=generic-writer-only:empty-payload; runtime=missing:multiplayer-join-failure; evidence=guide lists a no-payload row and enum exists, but no multiplayer runtime call site exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |
| 42 | `FELLOW_SPECTATOR_JOINED` | Missing | Spectator support missing. Audit: classification=required; builder=missing; runtime=missing:fellow-spectator-join-fanout; evidence=guide lists user id payload but spectator runtime and builder are absent; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Spectator, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |
| 43 | `FELLOW_SPECTATOR_LEFT` | Missing | Spectator support missing. Audit: classification=required; builder=missing; runtime=missing:fellow-spectator-left-fanout; evidence=guide lists user id payload but spectator runtime and builder are absent; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Spectator, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |
| 45 | `ALL_PLAYERS_LOADED` | Missing | Lekuruu marks this unused; prefer `MATCH_ALL_PLAYERS_LOADED` (53). Enum value is guarded by a regression test. Audit: classification=out of scope; builder=generic-writer-only:empty-payload; runtime=non-emitted:unused-legacy-alias-prefer-53; non-emission=out-of-scope-intentional; evidence=guide documents this as unused/no-payload and enum regression protects the ID split; payload=confirmed:empty-unused-alias; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Fixture Extraction Backlog, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `tests/unit/transports/bancho/protocol/test_enums.py`; verification=unit; fixture blocker=none; fixture note=excluded unused legacy alias unless later compatibility evidence reclassifies S2C 45. |
| 46 | `MATCH_START` | Missing | Multiplayer start packet with `Match` payload. Enum value is guarded by a regression test. Audit: classification=required; builder=missing; runtime=missing:multiplayer-match-start; evidence=guide lists Match payload and enum regression protects the corrected ID, but multiplayer runtime and builder are absent; payload=confirmed:Match; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, Bancho Struct Field Reference, Multiplayer, and Fixture Extraction Backlog, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `tests/unit/transports/bancho/protocol/test_enums.py`; verification=unit; fixture blocker=#17: Match golden bytes and S2C 46 enum-correction fixture bytes are needed before multiplayer match-start builder work; source gap=Fixture Extraction Backlog has no extracted Match or S2C 46 bytes. |
| 48 | `MATCH_SCORE_UPDATE` | Missing | Multiplayer support missing. Audit: classification=required; builder=missing; runtime=missing:multiplayer-score-frame-fanout; evidence=guide lists server ScoreFrame payload but multiplayer score update runtime and builder are absent; payload=confirmed:45-byte-server-ScoreFrame; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, Bancho Struct Field Reference, Multiplayer, and Fixture Extraction Backlog, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=#17: 45-byte server ScoreFrame golden bytes are needed before multiplayer score-update builder work; source gap=Fixture Extraction Backlog has no extracted server ScoreFrame bytes. |
| 50 | `MATCH_TRANSFER_HOST` | Missing | Multiplayer support missing. Audit: classification=required; builder=generic-writer-only:empty-payload; runtime=missing:multiplayer-host-transfer; evidence=guide lists empty payload with recipient-as-host semantics, but multiplayer runtime call site is absent; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |
| 53 | `MATCH_ALL_PLAYERS_LOADED` | Missing | Multiplayer support missing. Audit: classification=required; builder=generic-writer-only:empty-payload; runtime=missing:multiplayer-all-loaded; evidence=guide lists the preferred no-payload all-loaded row, but multiplayer runtime call site is absent; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |
| 57 | `MATCH_PLAYER_FAILED` | Missing | Multiplayer support missing. Audit: classification=required; builder=missing; runtime=missing:multiplayer-player-failed; evidence=guide lists slot id payload but multiplayer runtime and builder are absent; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |
| 58 | `MATCH_COMPLETE` | Missing | Multiplayer support missing. Audit: classification=required; builder=generic-writer-only:empty-payload; runtime=missing:multiplayer-complete; evidence=guide lists a no-payload row and enum exists, but multiplayer runtime call site is absent; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |
| 61 | `MATCH_SKIP` | Missing | Multiplayer support missing. Audit: classification=required; builder=generic-writer-only:empty-payload; runtime=missing:multiplayer-skip; evidence=guide lists a no-payload row and enum exists, but multiplayer runtime call site is absent; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |
| 62 | `UNAUTHORIZED` | Missing | Authorization failure packet missing. Audit: classification=needs reference evidence; builder=generic-writer-only:empty-payload; runtime=missing:authorization-failure-packet; evidence=guide lists a no-payload row, while current login and polling failures emit negative `LOGIN_REPLY` instead; evidence gap=payload reference includes `UNAUTHORIZED` while runtime failure paths use `LOGIN_REPLY`; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, `src/osu_server/transports/stable/bancho/workflows/login.py`, `src/osu_server/transports/stable/bancho/workflows/polling.py`; verification=none; next-audit=needs-reference-implementation-audit; fixture blocker=none. |
| 64 | `CHANNEL_JOIN_SUCCESS` | Builder | Channel join builder exists. Audit: classification=required; builder=implemented:channel_join_success; runtime=emitted:successful-channel-join; evidence=join handler enqueues the builder when channel authorization succeeds; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Chat And Channels, `src/osu_server/transports/stable/bancho/protocol/s2c/chat.py`, `src/osu_server/transports/stable/bancho/handlers/chat.py`, `tests/integration/test_chat_e2e.py`; verification=integration; fixture blocker=none. |
| 65 | `CHANNEL_AVAILABLE` | Builder | Channel listing builder exists. Audit: classification=required; builder=implemented:channel_available; runtime=emitted:login-visible-channel-list; evidence=login response builder emits one packet per visible channel; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Chat And Channels, `src/osu_server/transports/stable/bancho/protocol/s2c/login.py`, `src/osu_server/transports/stable/bancho/workflows/login_response_builder.py`, `tests/integration/test_login_flow.py`; verification=integration; fixture blocker=none. |
| 66 | `CHANNEL_REVOKED` | Builder | Channel leave/revoke builder exists. Audit: classification=required; builder=implemented:channel_revoked; runtime=emitted:channel-leave-and-failed-join; evidence=chat handler enqueues the builder on leave or denied join; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Chat And Channels, `src/osu_server/transports/stable/bancho/protocol/s2c/chat.py`, `src/osu_server/transports/stable/bancho/handlers/chat.py`, `tests/integration/test_chat_e2e.py`; verification=integration; fixture blocker=none. |
| 67 | `CHANNEL_AVAILABLE_AUTOJOIN` | Builder | Autojoin channel builder exists. Audit: classification=required; builder=implemented:channel_available_autojoin; runtime=emitted:login-autojoin-channel-list; evidence=login response builder emits one packet per autojoin channel; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Chat And Channels, `src/osu_server/transports/stable/bancho/protocol/s2c/login.py`, `src/osu_server/transports/stable/bancho/workflows/login_response_builder.py`, `tests/integration/test_login_flow.py`; verification=integration; fixture blocker=none. |
| 69 | `BEATMAP_INFO_REPLY` | Missing | Beatmap info flow missing. Audit: classification=required; builder=missing; runtime=missing:beatmap-info-reply-flow; evidence=guide lists BeatmapInfoReply payload but beatmap info S2C builder and runtime are absent; payload=confirmed:BeatmapInfoReply; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, Bancho Struct Field Reference, and Fixture Extraction Backlog, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=#17: BeatmapInfoReply golden response bytes are needed before beatmap-info reply builder work; source gap=Fixture Extraction Backlog lists beatmap info fixtures but none are extracted. |
| 71 | `LOGIN_PERMISSIONS` | Builder | Login packet builder exists. Audit: classification=required; builder=implemented:login_permissions; runtime=emitted:login-success; evidence=login response builder emits permission bitmask after successful authentication; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, `src/osu_server/transports/stable/bancho/protocol/s2c/login.py`, `src/osu_server/transports/stable/bancho/workflows/login_response_builder.py`, `tests/integration/test_login_flow.py`; verification=integration; fixture blocker=none. |
| 72 | `FRIENDS_LIST` | Builder | Login/friends builder exists. Audit: classification=required; builder=implemented:friends_list; runtime=emitted:login-friend-list; evidence=login response builder queries friend ids and emits the IntList packet; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Friends And PM Privacy, `src/osu_server/transports/stable/bancho/protocol/s2c/login.py`, `src/osu_server/transports/stable/bancho/workflows/login_response_builder.py`, `tests/integration/test_friend_relationship_pipeline.py`; verification=integration; fixture blocker=none. |
| 75 | `PROTOCOL_VERSION` | Builder | Login packet builder exists. Audit: classification=required; builder=implemented:protocol_version; runtime=emitted:login-success; evidence=login response builder emits `PROTOCOL_VERSION` using the configured stable protocol constant; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, `src/osu_server/transports/stable/bancho/protocol/s2c/login.py`, `src/osu_server/transports/stable/bancho/workflows/login_response_builder.py`, `tests/integration/test_login_flow.py`; verification=integration; fixture blocker=none. |
| 76 | `MENU_ICON` | Missing | Menu icon packet missing. Audit: classification=deferred; builder=missing; runtime=non-emitted:no-menu-icon-asset-policy-yet; non-emission=deferred-non-emission; evidence=guide lists String menu icon payload but no asset/menu policy, builder, or runtime call site exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, `docs/stable-compatibility-matrix.md` Static and Media Route Coverage, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |
| 80 | `MONITOR` | Missing | Monitor packet missing. Audit: classification=needs reference evidence; builder=generic-writer-only:empty-payload; runtime=missing:monitor-behavior-unaudited; evidence=guide lists a no-payload row, but compatibility purpose and emission trigger still need reference evidence; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; next-audit=needs-reference-implementation-audit; fixture blocker=none. |
| 81 | `MATCH_PLAYER_SKIPPED` | Missing | Multiplayer support missing. Audit: classification=required; builder=missing; runtime=missing:multiplayer-player-skipped; evidence=guide lists slot id payload but multiplayer runtime and builder are absent; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |
| 83 | `USER_PRESENCE` | Builder | Builder exists; full presence behavior incomplete. Audit: classification=required; builder=implemented:user_presence; runtime=partial:login-roster-and-connect-fanout; evidence=login roster emits own, bot, and active-session presence, and lifecycle listener fans out connected users, but request/filter behavior remains incomplete; payload=confirmed:UserPresence; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, Bancho Struct Field Reference, and Status And Presence, `src/osu_server/transports/stable/bancho/protocol/s2c/login.py`, `src/osu_server/transports/stable/bancho/workflows/presence_roster.py`, `src/osu_server/transports/stable/bancho/listeners/lifecycle.py`, `tests/integration/test_login_flow.py`; verification=integration; next-audit=needs-traffic-capture; fixture blocker=#17: UserPresence golden encode bytes and presence request/filter fixtures are needed before completing presence fanout; source gap=Fixture Extraction Backlog has no extracted UserPresence bytes. |
| 84 | `IRC_ONLY` | Missing | IRC-only mode packet missing. Audit: classification=deferred; builder=generic-writer-only:empty-payload; runtime=non-emitted:bancho-mode-is-supported-and-irc-only-policy-is-not-targeted; non-emission=compatible-without-emission; evidence=guide lists a no-payload row, but Athena's stable transport exposes bancho login/polling rather than IRC-only fallback; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, `src/osu_server/transports/stable/bancho/workflows/login.py`, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |
| 86 | `RESTART` | Missing | Restart notification packet missing. Audit: classification=required; builder=missing; runtime=missing:restart-notification-flow; evidence=guide lists reconnect-after payload but no builder or runtime call site exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |
| 88 | `INVITE` | Missing | Multiplayer invite packet missing. Audit: classification=required; builder=missing; runtime=missing:multiplayer-invite-flow; evidence=guide lists Message payload but multiplayer invite runtime and builder are absent; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |
| 89 | `CHANNEL_INFO_COMPLETE` | Builder | Channel listing terminator builder exists. Audit: classification=required; builder=implemented:channel_info_complete; runtime=emitted:login-channel-list-terminator; evidence=login response builder emits the terminator after channel availability packets; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Chat And Channels, `src/osu_server/transports/stable/bancho/protocol/s2c/login.py`, `src/osu_server/transports/stable/bancho/workflows/login_response_builder.py`, `tests/unit/transports/bancho/protocol/test_s2c_login.py`; verification=unit; fixture blocker=none. |
| 91 | `MATCH_CHANGE_PASSWORD` | Missing | Multiplayer password packet missing. Audit: classification=required; builder=missing; runtime=missing:multiplayer-password-change; evidence=guide lists String payload but multiplayer password runtime and builder are absent; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |
| 92 | `SILENCE_INFO` | Builder | Silence info builder exists; moderation workflow incomplete. Audit: classification=required; builder=implemented:silence_info; runtime=partial:login-zero-silence-only; evidence=login response emits `silence_info(0)`, but moderation silence state projection is not wired; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, `src/osu_server/transports/stable/bancho/protocol/s2c/login.py`, `src/osu_server/transports/stable/bancho/workflows/login_response_builder.py`, `tests/unit/transports/bancho/protocol/test_s2c_login.py`; verification=unit; fixture blocker=none. |
| 94 | `USER_SILENCED` | Missing | Moderation workflow missing. Audit: classification=required; builder=missing; runtime=missing:user-silenced-notification; evidence=guide lists user id payload but moderation runtime and builder are absent; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |
| 95 | `USER_PRESENCE_SINGLE` | Missing | Targeted presence packet missing. Audit: classification=required; builder=missing; runtime=missing:targeted-presence-response; evidence=guide lists user id payload and Status And Presence requires explicit presence responses, but builder and runtime are absent; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Status And Presence, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |
| 96 | `USER_PRESENCE_BUNDLE` | Builder | Presence bundle builder exists. Audit: classification=required; builder=implemented:user_presence_bundle; runtime=emitted:login-roster-bundle,presence-request-all-bundle; evidence=login roster builds the online id bundle and login response emits it; `PRESENCE_REQUEST_ALL` emits an online id bundle with the presence response; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Status And Presence, `src/osu_server/transports/stable/bancho/protocol/s2c/login.py`, `src/osu_server/transports/stable/bancho/workflows/presence_roster.py`, `src/osu_server/transports/stable/bancho/handlers/presence.py`, `tests/integration/test_chat_e2e.py`, `tests/unit/transports/bancho/test_presence_handlers.py`; verification=unit,integration; fixture blocker=none. |
| 100 | `USER_DM_BLOCKED` | Builder | Private-message rejection builder exists. Audit: classification=required; builder=implemented:user_dm_blocked; runtime=emitted:friend-only-dm-rejection; evidence=private-message handler enqueues this builder when target privacy blocks delivery; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Friends And PM Privacy, `src/osu_server/transports/stable/bancho/protocol/s2c/chat.py`, `src/osu_server/transports/stable/bancho/handlers/chat.py`, `tests/unit/transports/bancho/protocol/test_s2c_chat.py`; verification=unit; fixture blocker=none. |
| 101 | `TARGET_IS_SILENCED` | Missing | Moderation workflow missing. Audit: classification=required; builder=missing; runtime=missing:silenced-target-pm-response; evidence=guide lists Message payload and Chat And Channels calls out silenced-target responses as incomplete; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Chat And Channels, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |
| 102 | `VERSION_UPDATE_FORCED` | Missing | Forced update flow missing. Audit: classification=deferred; builder=generic-writer-only:empty-payload; runtime=non-emitted:no-forced-update-policy-unless-client-traffic-requires-updater; non-emission=deferred-non-emission; evidence=guide lists a no-payload row and matrix update inventory records Athena's initial no-update/no-op policy; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, `docs/stable-compatibility-matrix.md` Stable HTTP Endpoint Coverage, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |
| 103 | `SWITCH_SERVER` | Missing | Server switch flow missing. Audit: classification=deferred; builder=missing; runtime=non-emitted:no-multi-bancho-server-switch-policy; non-emission=deferred-non-emission; evidence=guide lists required idle seconds payload, but Athena has no server-switch runtime or builder; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |
| 104 | `ACCOUNT_RESTRICTED` | Missing | Restriction workflow missing. Audit: classification=required; builder=generic-writer-only:empty-payload; runtime=missing:restriction-notification-flow; evidence=guide lists a no-payload row but restriction runtime emission is absent; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |
| 105 | `RTX` | Missing | Unknown/rare stable packet; verify before implementing. Audit: classification=needs reference evidence; builder=missing; runtime=non-emitted:unknown-rare-packet-pending-reference-audit; evidence=guide lists String payload but no Athena behavior or compatibility trigger is confirmed; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; next-audit=needs-reference-implementation-audit; fixture blocker=none. |
| 106 | `MATCH_ABORT` | Missing | Multiplayer support missing. Audit: classification=required; builder=generic-writer-only:empty-payload; runtime=missing:multiplayer-abort-flow; evidence=guide lists a no-payload row and enum exists, but multiplayer abort runtime is absent; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |
| 107 | `SWITCH_TOURNAMENT_SERVER` | Missing | Tournament support missing. Audit: classification=required; builder=missing; runtime=missing:tournament-server-switch-flow; evidence=guide lists String payload but tournament runtime and builder are absent; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; fixture blocker=none. |

## Bancho Struct Coverage

Canonical source: Lekuruu `Types/*.md`. Struct rows should be implemented as
local transport wire types before packet handlers/builders depend on them.
Exact current field layouts and enum values are summarized in
[stable-compatibility-guide.md](stable-compatibility-guide.md#bancho-struct-field-reference).

| Type | Status | Blocking packet dependencies | Notes |
| --- | --- | --- | --- |
| `String` | Implemented | Chat, login, channel, match, beatmap info packets | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types and Bancho Struct Field Reference, `src/osu_server/transports/stable/bancho/protocol/types.py`, `tests/unit/transports/bancho/protocol/test_types.py`; dependencies=C2S `SEND_MESSAGE`, `SEND_PRIVATE_MESSAGE`, `ERROR_REPORT`, `JOIN_CHANNEL`, `LEAVE_CHANNEL`, `SET_AWAY_MESSAGE`, S2C `SEND_MESSAGE`, `ANNOUNCE`, `CHANNEL_JOIN_SUCCESS`, `CHANNEL_REVOKED`, `INVITE`, `USER_DM_BLOCKED`, plus nested `Message`, `Channel`, `StatusUpdate`, `BeatmapInfo`, `Match`, `MatchJoin`; confirmed=implemented as `BanchoString` with empty/non-empty ULEB128 layout covered by unit tests; fixture priority=none; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference and `tests/unit/transports/bancho/protocol/test_types.py`; fixture blocker=none. |
| `Message` | Implemented | C2S/S2C `SEND_MESSAGE`, private message packets | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types, Bancho Struct Field Reference, and Bancho Packet Payload Reference, `src/osu_server/transports/stable/bancho/protocol/types.py`, `src/osu_server/transports/stable/bancho/protocol/c2s/chat.py`, `src/osu_server/transports/stable/bancho/protocol/s2c/chat.py`, `tests/unit/transports/bancho/protocol/test_types.py`; dependencies=C2S `SEND_MESSAGE`, `SEND_PRIVATE_MESSAGE`, `SET_AWAY_MESSAGE`, S2C `SEND_MESSAGE`, `INVITE`, `USER_DM_BLOCKED`, `TARGET_IS_SILENCED`; confirmed=implemented sender/content/target/sender_id layout; fixture priority=none; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference and `tests/unit/transports/bancho/protocol/test_types.py`; fixture blocker=none. |
| `IntList` | Implemented | `FRIENDS_LIST`, `USER_PRESENCE_BUNDLE` | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types, Bancho Struct Field Reference, and Bancho Packet Payload Reference, `src/osu_server/transports/stable/bancho/protocol/types.py`, `src/osu_server/transports/stable/bancho/protocol/s2c/login.py`, `tests/unit/transports/bancho/protocol/test_types.py`; dependencies=C2S `STATS_REQUEST`, `PRESENCE_REQUEST`, S2C `FRIENDS_LIST`, nested `UserPresenceBundle`; confirmed=implemented u16 count plus sInt values layout; fixture priority=none; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference and `tests/unit/transports/bancho/protocol/test_types.py`; fixture blocker=none. |
| `Channel` | Implemented | `CHANNEL_AVAILABLE`, `CHANNEL_AVAILABLE_AUTOJOIN` | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types, Bancho Struct Field Reference, and Bancho Packet Payload Reference, `src/osu_server/transports/stable/bancho/protocol/types.py`, `src/osu_server/transports/stable/bancho/protocol/s2c/login.py`, `tests/unit/transports/bancho/protocol/test_types.py`, `tests/unit/transports/bancho/protocol/test_s2c_login.py`; dependencies=S2C `CHANNEL_AVAILABLE`, `CHANNEL_AVAILABLE_AUTOJOIN`; confirmed=implemented name/topic/user_count layout; fixture priority=none; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference and `tests/unit/transports/bancho/protocol/test_types.py`; fixture blocker=none. |
| `StatusUpdate` | Implemented | C2S `STATUS_CHANGE`, S2C `USER_STATS` | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types, Bancho Struct Field Reference, and Bancho Packet Payload Reference, `src/osu_server/transports/stable/bancho/protocol/types.py`, `src/osu_server/transports/stable/bancho/protocol/c2s/status.py`, `src/osu_server/transports/stable/bancho/protocol/s2c/login.py`, `tests/unit/transports/bancho/protocol/test_types.py`; dependencies=C2S `STATUS_CHANGE`, nested S2C `USER_STATS`; confirmed=implemented current stable status/status_text/beatmap_md5/mods/play_mode/beatmap_id layout; missing=full presence and stat fanout behavior remains packet-row work; fixture priority=none; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference and `tests/unit/transports/bancho/protocol/test_types.py`; fixture blocker=none. |
| `Status` | Implemented | `STATUS_CHANGE`, `USER_STATS` | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types and Bancho Struct Field Reference; dependencies=C2S `STATUS_CHANGE`, nested S2C `USER_STATS`; confirmed=canonical `StableStatus` IntEnum values 0..13 and value tests; evidence=`src/osu_server/domain/compatibility/stable/status.py`, `tests/unit/domain/compatibility/stable/test_stable_enums.py`; verification=unit; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `Status` values; fixture blocker=none. |
| `Mode` | Implemented | `STATUS_CHANGE`, `USER_STATS`, `USER_PRESENCE`, score modes | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types and Bancho Struct Field Reference; dependencies=C2S `STATUS_CHANGE`, nested S2C `USER_STATS`, S2C `USER_PRESENCE`, nonpacket score mode mapping; confirmed=canonical `StableMode` IntEnum values 0..3 and value tests; evidence=`src/osu_server/domain/compatibility/stable/mode.py`, `tests/unit/domain/compatibility/stable/test_stable_enums.py`; verification=unit; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `Mode` values; fixture blocker=none. |
| `Mods` | Missing | `STATUS_CHANGE`, score submit, `MATCH`, leaderboard family policy | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types and Bancho Struct Field Reference; dependencies=C2S `STATUS_CHANGE`, `MATCH_CHANGE_MODS`, nested C2S/S2C `MATCH`, nonpacket score submit and leaderboard compatibility; confirmed=guide lists stable bitmask values including ScoreV2 and key mods; missing=canonical bitmask type, conversion tests, and Relax2/Autopilot naming policy evidence; fixture priority=p1; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `Mods` bitmask; fixture blocker=#17: stable mod bitmask and Relax2/Autopilot evidence fixtures are needed before match and score-family compatibility work. |
| `Grade` | Missing | score submit, getscores, `BEATMAP_INFO_REPLY` | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types and Bancho Struct Field Reference; dependencies=nested `BeatmapInfo`, S2C `BEATMAP_INFO_REPLY`, nonpacket score submit and getscores display; confirmed=guide lists stable grade values 0..9; missing=canonical enum type and score/beatmap mapping evidence; fixture priority=p1; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `Grade` values; fixture blocker=#17: grade enum and beatmap-info grade bytes are needed before score and beatmap-info fixtures. |
| `ButtonState` | Missing | `SEND_FRAMES`, `SPECTATE_FRAMES` | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types and Bancho Struct Field Reference; dependencies=nested `ReplayFrame`, C2S `SEND_FRAMES`, S2C `SPECTATE_FRAMES`; confirmed=guide lists replay input bitmask values; missing=canonical bitmask type and replay fixture evidence; fixture priority=p0; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `ButtonState` bitmask; fixture blocker=#17: replay input bitmask bytes directly block `ReplayFrame` and `ReplayFrameBundle` golden fixtures. |
| `PresenceFilter` | Implemented | `RECEIVE_UPDATES` | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types, Bancho Struct Field Reference, Bancho Packet Payload Reference, and Status And Presence; dependencies=C2S `RECEIVE_UPDATES`; confirmed=canonical `StablePresenceFilter` IntEnum values 0..2 and value tests; evidence=`src/osu_server/domain/compatibility/stable/presence_filter.py`, `tests/unit/domain/compatibility/stable/test_stable_enums.py`; verification=unit; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `PresenceFilter` values and Bancho Packet Payload Reference `RECEIVE_UPDATES`; fixture blocker=none. |
| `QuitState` | Missing | `USER_QUIT` | Audit: classification=needs reference evidence; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types, Bancho Struct Field Reference, and Bancho Packet Payload Reference, `docs/stable-compatibility-matrix.md` S2C `USER_QUIT` row; dependencies=S2C `USER_QUIT`; confirmed=guide lists modern quit state values 0..2; missing=canonical enum type plus reference evidence for old 4-byte user id form vs modern user id plus `QuitState`; fixture priority=p1; exact source gap=reference implementation or traffic evidence must choose old 4-byte `USER_QUIT` form vs modern `UserId` plus `QuitState`; next-audit=needs-reference-implementation-audit; fixture blocker=#17: `USER_QUIT` fixture extraction must wait for the selected stable-client quit payload source. |
| `ReplayAction` | Missing | `SEND_FRAMES`, `SPECTATE_FRAMES` | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types and Bancho Struct Field Reference; dependencies=nested `ReplayFrameBundle`, C2S `SEND_FRAMES`, S2C `SPECTATE_FRAMES`; confirmed=guide lists replay action values 0..8; missing=canonical enum type and spectator fixture evidence; fixture priority=p0; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `ReplayAction` values; fixture blocker=#17: replay action bytes directly block `ReplayFrameBundle` golden fixtures. |
| `ReplayFrame` | Missing | `SEND_FRAMES`, `SPECTATE_FRAMES` | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types and Bancho Struct Field Reference; dependencies=nested `ReplayFrameBundle`, C2S `SEND_FRAMES`, S2C `SPECTATE_FRAMES`; confirmed=guide lists ButtonState, legacy byte, mouse_x, mouse_y, and time layout; missing=transport wire type and replay frame golden bytes; fixture priority=p0; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `ReplayFrame` layout; fixture blocker=#17: replay frame encode/decode bytes directly block C2S `SEND_FRAMES` and S2C `SPECTATE_FRAMES` fixtures. |
| `ScoreFrame` | Missing | C2S 47 `MATCH_SCORE_UPDATE`, S2C 48 `MATCH_SCORE_UPDATE`, `SPECTATE_FRAMES` | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types, Bancho Struct Field Reference, Bancho Packet Payload Reference, and Fixture Extraction Backlog, `docs/stable-compatibility-matrix.md` C2S 47 and S2C 48 rows; dependencies=C2S `MATCH_SCORE_UPDATE`, S2C `MATCH_SCORE_UPDATE`, optional nested `ReplayFrameBundle` in C2S `SEND_FRAMES` and S2C `SPECTATE_FRAMES`; confirmed=guide documents 28-byte client and 45-byte server shape difference; missing=transport wire type, optional ScoreV2 tail handling evidence, and client/server golden bytes; fixture priority=p0; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `ScoreFrame` layout and Fixture Extraction Backlog; fixture blocker=#17: client/server score frame golden bytes are a first extraction input before match score and spectator frame implementation. |
| `ReplayFrameBundle` | Missing | C2S `SEND_FRAMES`, S2C `SPECTATE_FRAMES` | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types, Bancho Struct Field Reference, Bancho Packet Payload Reference, and Fixture Extraction Backlog, `docs/stable-compatibility-matrix.md` C2S `SEND_FRAMES` and S2C `SPECTATE_FRAMES` rows; dependencies=C2S `SEND_FRAMES`, S2C `SPECTATE_FRAMES`, nested `ReplayFrame`, `ReplayAction`, optional `ScoreFrame`; confirmed=guide lists extra/frame_count/frames/action/optional-score/sequence layout; missing=transport wire type and spectator frame bundle golden bytes; fixture priority=p0; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `ReplayFrameBundle` layout and Fixture Extraction Backlog; fixture blocker=#17: spectator frame bundle bytes are a first extraction input before C2S `SEND_FRAMES` and S2C `SPECTATE_FRAMES` work. |
| `BeatmapInfo` | Missing | S2C `BEATMAP_INFO_REPLY`, `/web/osu-getbeatmapinfo.php` | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types, Bancho Struct Field Reference, Bancho Packet Payload Reference, Beatmap Info Packet Flow, and Fixture Extraction Backlog; dependencies=nested S2C `BEATMAP_INFO_REPLY`, nonpacket `/web/osu-getbeatmapinfo.php`; confirmed=guide lists request_index/ids/thread/ranked/grades/md5 layout; missing=transport wire type and beatmap info response fixture evidence; fixture priority=p1; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `BeatmapInfo` layout and Beatmap Info Packet Flow; fixture blocker=#17: beatmap info row bytes are needed before S2C `BEATMAP_INFO_REPLY` and web beatmap-info response implementation. |
| `BeatmapInfoRequest` | Missing | C2S `BEATMAP_INFO` | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types, Bancho Struct Field Reference, Bancho Packet Payload Reference, Beatmap Info Packet Flow, and Fixture Extraction Backlog, `docs/stable-compatibility-matrix.md` C2S `BEATMAP_INFO` row; dependencies=C2S `BEATMAP_INFO`, nested `String` and id list primitives; confirmed=guide lists filename count, filenames, id count, and beatmap id list layout; missing=transport wire type and golden request bytes; fixture priority=p1; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `BeatmapInfoRequest` layout and Bancho Packet Payload Reference `BEATMAP_INFO`; fixture blocker=#17: beatmap info request bytes are needed before C2S `BEATMAP_INFO` parser work. |
| `BeatmapInfoReply` | Missing | S2C `BEATMAP_INFO_REPLY` | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types, Bancho Struct Field Reference, Bancho Packet Payload Reference, Beatmap Info Packet Flow, and Fixture Extraction Backlog, `docs/stable-compatibility-matrix.md` S2C `BEATMAP_INFO_REPLY` row; dependencies=S2C `BEATMAP_INFO_REPLY`, nested `BeatmapInfo`; confirmed=guide lists count plus `BeatmapInfo[count]` layout; missing=transport wire type and golden response bytes; fixture priority=p1; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `BeatmapInfoReply` layout and Bancho Packet Payload Reference `BEATMAP_INFO_REPLY`; fixture blocker=#17: beatmap info reply bytes are needed before S2C `BEATMAP_INFO_REPLY` builder work. |
| `UserPresence` | Fixture-backed | `USER_PRESENCE`, login presence roster | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types, Bancho Struct Field Reference, Bancho Packet Payload Reference, and Status And Presence, `src/osu_server/transports/stable/bancho/protocol/s2c/login.py`, `tests/unit/transports/bancho/protocol/test_presence_fixtures.py`, `tests/integration/test_login_flow.py`; dependencies=S2C `USER_PRESENCE`, login presence roster; confirmed=builder layout packs `permissions \| (mode << 5)`, golden encode/decode bytes, boundary `permissions=16, mode=3`, and BanchoBot fixture; missing=targeted presence runtime behavior evidence remains packet-row work; verification=unit,integration; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `UserPresence` layout and Status And Presence; fixture blocker=none. |
| `UserPresenceBundle` | Fixture-backed | `USER_PRESENCE_BUNDLE`, login online user list | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types, Bancho Struct Field Reference, Bancho Packet Payload Reference, and Status And Presence, `src/osu_server/transports/stable/bancho/protocol/s2c/login.py`, `tests/unit/transports/bancho/protocol/test_presence_fixtures.py`, `tests/integration/test_chat_e2e.py`; dependencies=S2C `USER_PRESENCE_BUNDLE`, login online user list, nested `IntList`; confirmed=builder emits IntList-compatible online user id bundle and golden encode/decode bytes; verification=unit,integration; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `UserPresenceBundle` layout; fixture blocker=none. |
| `UserStats` | Fixture-backed | `USER_STATS`, login stats, requested stats | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types, Bancho Struct Field Reference, Bancho Packet Payload Reference, and Status And Presence, `src/osu_server/transports/stable/bancho/protocol/s2c/login.py`, `src/osu_server/transports/stable/bancho/workflows/presence_roster.py`, `tests/unit/transports/bancho/protocol/test_stats_fixtures.py`; dependencies=S2C `USER_STATS`, C2S `STATS_REQUEST`, login stats fanout, nested `StatusUpdate`; confirmed=builder uses nested `StatusUpdate`, golden encode/decode bytes, 0-1 accuracy f32 packing, pp uint16 clamp, BanchoBot fixture, and C2S `STATUS_CHANGE` empty-string fixture; missing=stat projection behavior and requested-stats runtime remain packet-row work; verification=unit; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `UserStats` layout and Status And Presence; fixture blocker=none. |
| `Match` | Missing | C2S `CREATE_MATCH`, `MATCH_CHANGE_SETTINGS`, `MATCH_CHANGE_BEATMAP`, `MATCH_CHANGE_PASSWORD`; S2C `MATCH_UPDATE`, `NEW_MATCH`, `MATCH_START`, `MATCH_JOIN_SUCCESS` | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types, Bancho Struct Field Reference, Bancho Packet Payload Reference, Multiplayer, and Fixture Extraction Backlog, `docs/stable-compatibility-matrix.md` C2S `CREATE_MATCH`, `MATCH_CHANGE_SETTINGS`, `MATCH_CHANGE_BEATMAP`, `MATCH_CHANGE_PASSWORD` and S2C `MATCH_UPDATE`, `NEW_MATCH`, `MATCH_JOIN_SUCCESS`, `MATCH_START` rows; dependencies=C2S `CREATE_MATCH`, `MATCH_CHANGE_SETTINGS`, `MATCH_CHANGE_BEATMAP`, `MATCH_CHANGE_PASSWORD`, S2C `MATCH_UPDATE`, `NEW_MATCH`, `MATCH_JOIN_SUCCESS`, `MATCH_START`, nested `Mods`; confirmed=guide lists current stable room/slot/player/freemod layout; missing=transport wire type, multiplayer runtime, freemod/per-slot-mod evidence, and Match golden bytes; fixture priority=p0; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `Match` layout, Multiplayer, and Fixture Extraction Backlog; fixture blocker=#17: Match golden bytes are a first extraction input before multiplayer parser/builder work. |
| `MatchJoin` | Missing | C2S `JOIN_MATCH` | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types, Bancho Struct Field Reference, Bancho Packet Payload Reference, Multiplayer, and Fixture Extraction Backlog, `docs/stable-compatibility-matrix.md` C2S `JOIN_MATCH` row; dependencies=C2S `JOIN_MATCH`, nested `String`; confirmed=guide lists match_id plus password layout; missing=transport wire type, multiplayer join runtime, and MatchJoin golden bytes; fixture priority=p0; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `MatchJoin` layout, Multiplayer, and Fixture Extraction Backlog; fixture blocker=#17: MatchJoin golden bytes are a first extraction input before `JOIN_MATCH` parser work. |

## #17 Fixture Extraction Blocker Rollup

This rollup is planning input for GitHub Issue #17 fixture extraction, not
fixture completion. Rows below still need #17 to extract and validate golden
bytes; this audit-only section only identifies confirmed inputs and evidence
gaps. Rows without exact reference evidence are separated from fixture-ready
planning inputs and remain `needs reference evidence`.

### Confirmed Required Fixture Inputs

| Row | Type | Classification | Status | Exact reference source | Blocker reason |
| --- | --- | --- | --- | --- | --- |
| C2S 18 `SEND_FRAMES` | C2S packet | required | Missing | `docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Spectator | `ReplayFrameBundle` golden encode/decode bytes are needed before spectator frame parser work. |
| C2S 2 `EXIT` | C2S packet | required | Partial | `docs/stable-compatibility-guide.md` Bancho Packet Payload Reference; `src/osu_server/transports/stable/bancho/handlers/lifecycle.py` | `EXIT` payload golden bytes are needed before parser validation can be treated as complete. |
| C2S 31 `CREATE_MATCH` | C2S packet | required | Missing | `docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer | `Match` golden encode/decode bytes are needed before multiplayer create parser work. |
| C2S 32 `JOIN_MATCH` | C2S packet | required | Missing | `docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer | `MatchJoin` golden encode/decode bytes are needed before multiplayer join parser work. |
| C2S 41 `MATCH_CHANGE_SETTINGS` | C2S packet | required | Missing | `docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer | `Match` golden encode/decode bytes are needed before multiplayer settings parser work. |
| C2S 47 `MATCH_SCORE_UPDATE` | C2S packet | required | Missing | `docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer | 28-byte client `ScoreFrame` golden bytes are needed before multiplayer score-update parser work. |
| C2S 50 `MATCH_CHANGE_BEATMAP` | C2S packet | required | Missing | `docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer | `Match` golden encode/decode bytes are needed before multiplayer beatmap-change parser work. |
| C2S 68 `BEATMAP_INFO` | C2S packet | required | Missing | `docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Beatmap Info Packet Flow | `BeatmapInfoRequest` golden request bytes are needed before beatmap-info parser work. |
| C2S 90 `MATCH_CHANGE_PASSWORD` | C2S packet | required | Missing | `docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Multiplayer | `Match` golden encode/decode bytes are needed before multiplayer password-change parser work. |
| S2C 11 `USER_STATS` | S2C packet | required | Fixture-backed | `docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, Bancho Struct Field Reference, and Status And Presence; `tests/unit/transports/bancho/protocol/test_stats_fixtures.py` | Stat-projection and requested-stats runtime fixtures are still needed before expanding stat fanout beyond login placeholders. |
| S2C 15 `SPECTATE_FRAMES` | S2C packet | required | Missing | `docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, Bancho Struct Field Reference, Spectator, and Fixture Extraction Backlog | `ReplayFrameBundle` golden encode/decode bytes are needed before spectator frame builder work. |
| S2C 26 `MATCH_UPDATE` | S2C packet | required | Missing | `docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, Bancho Struct Field Reference, Multiplayer, and Fixture Extraction Backlog | `Match` golden encode/decode bytes are needed before multiplayer match-update builder work. |
| S2C 27 `NEW_MATCH` | S2C packet | required | Missing | `docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, Bancho Struct Field Reference, Multiplayer, and Fixture Extraction Backlog | `Match` golden encode/decode bytes are needed before multiplayer new-match builder work. |
| S2C 36 `MATCH_JOIN_SUCCESS` | S2C packet | required | Missing | `docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, Bancho Struct Field Reference, Multiplayer, and Fixture Extraction Backlog | `Match` golden encode/decode bytes are needed before multiplayer join-success builder work. |
| S2C 46 `MATCH_START` | S2C packet | required | Missing | `docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, Bancho Struct Field Reference, Multiplayer, and Fixture Extraction Backlog; `tests/unit/transports/bancho/protocol/test_enums.py` | `Match` golden bytes and S2C 46 enum-correction fixture bytes are needed before multiplayer match-start builder work. |
| S2C 48 `MATCH_SCORE_UPDATE` | S2C packet | required | Missing | `docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, Bancho Struct Field Reference, Multiplayer, and Fixture Extraction Backlog | 45-byte server `ScoreFrame` golden bytes are needed before multiplayer score-update builder work. |
| S2C 69 `BEATMAP_INFO_REPLY` | S2C packet | required | Missing | `docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, Bancho Struct Field Reference, and Fixture Extraction Backlog | `BeatmapInfoReply` golden response bytes are needed before beatmap-info reply builder work. |
| S2C 83 `USER_PRESENCE` | S2C packet | required | Fixture-backed | `docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, Bancho Struct Field Reference, and Status And Presence; `tests/unit/transports/bancho/protocol/test_presence_fixtures.py` | Presence request/filter runtime fixtures are still needed before completing presence fanout. |
| `Mods` | Bancho struct | required | Missing | `docs/stable-compatibility-guide.md` Bancho Struct Field Reference `Mods` bitmask | Stable mod bitmask and Relax2/Autopilot evidence fixtures are needed before match and score-family compatibility work. |
| `Grade` | Bancho struct | required | Missing | `docs/stable-compatibility-guide.md` Bancho Struct Field Reference `Grade` values | Grade enum and beatmap-info grade bytes are needed before score and beatmap-info fixtures. |
| `ButtonState` | Bancho struct | required | Missing | `docs/stable-compatibility-guide.md` Bancho Struct Field Reference `ButtonState` bitmask | Replay input bitmask bytes directly block `ReplayFrame` and `ReplayFrameBundle` golden fixtures. |
| `PresenceFilter` runtime behavior | Bancho packet behavior | required | Missing | `docs/stable-compatibility-guide.md` Bancho Packet Payload Reference `RECEIVE_UPDATES` and Status And Presence | Receive-updates traffic evidence is still needed before presence filter behavior can be finalized. |
| `ReplayAction` | Bancho struct | required | Missing | `docs/stable-compatibility-guide.md` Bancho Struct Field Reference `ReplayAction` values | Replay action bytes directly block `ReplayFrameBundle` golden fixtures. |
| `ReplayFrame` | Bancho struct | required | Missing | `docs/stable-compatibility-guide.md` Bancho Struct Field Reference `ReplayFrame` layout | Replay frame encode/decode bytes directly block C2S `SEND_FRAMES` and S2C `SPECTATE_FRAMES` fixtures. |
| `ScoreFrame` | Bancho struct | required | Missing | `docs/stable-compatibility-guide.md` Bancho Struct Field Reference `ScoreFrame` layout and Fixture Extraction Backlog | Client/server score frame golden bytes are a first extraction input before match score and spectator frame implementation. |
| `ReplayFrameBundle` | Bancho struct | required | Missing | `docs/stable-compatibility-guide.md` Bancho Struct Field Reference `ReplayFrameBundle` layout and Fixture Extraction Backlog | Spectator frame bundle bytes are a first extraction input before C2S `SEND_FRAMES` and S2C `SPECTATE_FRAMES` work. |
| `BeatmapInfo` | Bancho struct | required | Missing | `docs/stable-compatibility-guide.md` Bancho Struct Field Reference `BeatmapInfo` layout and Beatmap Info Packet Flow | Beatmap info row bytes are needed before S2C `BEATMAP_INFO_REPLY` and web beatmap-info response implementation. |
| `BeatmapInfoRequest` | Bancho struct | required | Missing | `docs/stable-compatibility-guide.md` Bancho Struct Field Reference `BeatmapInfoRequest` layout and Bancho Packet Payload Reference `BEATMAP_INFO` | Beatmap info request bytes are needed before C2S `BEATMAP_INFO` parser work. |
| `BeatmapInfoReply` | Bancho struct | required | Missing | `docs/stable-compatibility-guide.md` Bancho Struct Field Reference `BeatmapInfoReply` layout and Bancho Packet Payload Reference `BEATMAP_INFO_REPLY` | Beatmap info reply bytes are needed before S2C `BEATMAP_INFO_REPLY` builder work. |
| `UserPresence` runtime behavior | Bancho packet behavior | required | Partial | `docs/stable-compatibility-guide.md` Status And Presence; `tests/unit/transports/bancho/protocol/test_presence_fixtures.py` | Targeted presence and receive-update behavior fixtures are still needed before runtime fanout work. |
| `UserStats` runtime behavior | Bancho packet behavior | required | Partial | `docs/stable-compatibility-guide.md` Status And Presence; `tests/unit/transports/bancho/protocol/test_stats_fixtures.py` | Stat projection and requested-stats behavior fixtures are still needed before runtime fanout work. |
| `Match` | Bancho struct | required | Missing | `docs/stable-compatibility-guide.md` Bancho Struct Field Reference `Match` layout, Multiplayer, and Fixture Extraction Backlog | `Match` golden bytes are a first extraction input before multiplayer parser/builder work. |
| `MatchJoin` | Bancho struct | required | Missing | `docs/stable-compatibility-guide.md` Bancho Struct Field Reference `MatchJoin` layout, Multiplayer, and Fixture Extraction Backlog | `MatchJoin` golden bytes are a first extraction input before `JOIN_MATCH` parser work. |

### Needs Reference Evidence Before Fixture Extraction

| Row | Type | Classification | Status | Exact reference source | Blocker reason |
| --- | --- | --- | --- | --- | --- |
| C2S 99 `CHANGE_FRIENDONLY_DMS` | C2S packet | needs reference evidence | Implemented | Evidence gap: stable-client traffic capture for the one-byte enabled flag versus wiki `sInt` datatype label | Exact-width golden fixture extraction must wait for traffic evidence that resolves the one-byte versus `sInt` payload conflict. |
| S2C 12 `USER_QUIT` | S2C packet | needs reference evidence | Partial | Evidence gap: stable-client traffic capture or reference implementation source for old 4-byte user id form versus modern `UserId` plus `QuitState` | Modern `USER_QUIT` fixture extraction must wait for the selected stable-client quit payload source. |
| `QuitState` | Bancho struct | needs reference evidence | Missing | Exact source gap: reference implementation or traffic evidence must choose old 4-byte `USER_QUIT` form versus modern `UserId` plus `QuitState` | `USER_QUIT` fixture extraction must wait for the selected stable-client quit payload source. |

### Excluded From Fixture Extraction

| Row | Type | Classification | Status | Exclusion source | Review note |
| --- | --- | --- | --- | --- | --- |
| S2C 45 `ALL_PLAYERS_LOADED` | S2C packet | out of scope | Missing | Guide records this unused legacy alias and Athena prefers S2C 53 `MATCH_ALL_PLAYERS_LOADED` | Do not treat this as a confirmed required fixture input unless later compatibility evidence reclassifies S2C 45. |

## Bancho Packet / Struct Audit Validation

Task 7 final scope review is documentation-only validation. It does not claim
`$kiro-validate-impl` feature-level GO; parent validation remains responsible for
that gate.

| Check | Result | Evidence |
| --- | --- | --- |
| `git diff --check` | PASS | No whitespace errors. |
| Focused row coverage check | PASS | `c2s=49 s2c=62 struct=24 bad=`. |
| Classification vocabulary / blocker rollup / unresolved evidence gap targeted check | PASS | Required terms present: `#17 Fixture Extraction Blocker Rollup`, `Guide Consistency Check`, `needs reference evidence`, `fixture blocker=#17`, `unresolved evidence gap`. |
| Scope guard diff check | PASS | `git diff --name-only main...HEAD` showed only spec documentation and `docs/stable-compatibility-matrix.md`; no `src/`, `tests/fixtures/`, migrations, package manager, or runtime configuration files. |
| Markdown table / diff review | PASS | Packet and struct gaps remain audit rows or rollups; no implementation gap or fixture gap is marked complete. |

Unresolved evidence gaps remain by design and are not implementation or fixture
completion: C2S 20 `ERROR_REPORT`, C2S 99 `CHANGE_FRIENDONLY_DMS`, S2C 10
`IRC_QUIT`, S2C 12 `USER_QUIT`, S2C 62 `UNAUTHORIZED`, S2C 80 `MONITOR`, S2C
105 `RTX`, and struct `QuitState`.

## Guide Consistency Check

No `docs/stable-compatibility-guide.md` rows were changed in this task. The
matrix and guide were compared against the Bancho Packet Payload Reference and
Bancho Struct Field Reference; contradictions without confirmed evidence remain
unresolved evidence gaps below instead of silent drift.

| Row | Matrix / guide comparison | Required audit type | Exact source gap | Review note |
| --- | --- | --- | --- | --- |
| C2S 20 `ERROR_REPORT` | Guide confirms `String error_report`; matrix has no confirmed server-side ingestion behavior. | `needs-reference-implementation-audit` | Reference implementation path or behavior note for stable client error-report ingestion is missing. | Keep classification as `needs reference evidence`; no guide change is justified by payload shape alone. |
| C2S 99 `CHANGE_FRIENDONLY_DMS` | Guide and matrix both record Athena's one-byte enabled flag, but also preserve the wiki `sInt` datatype label conflict. | `needs-traffic-capture` | Stable-client traffic capture for the exact enabled-flag width is missing. | Unresolved evidence gap blocks treating the one-byte payload as confirmed fixture input. |
| S2C 10 `IRC_QUIT` | Guide lists `String`; matrix notes runtime disconnect fanout emits `USER_QUIT` instead. | `needs-reference-implementation-audit` | Reference implementation evidence choosing `IRC_QUIT` versus `USER_QUIT` for quit notification is missing. | Keep this as a matrix/runtime/guide evidence gap; no guide row change without source evidence. |
| S2C 12 `USER_QUIT` | Guide lists modern `UserId` plus `QuitState`; matrix records Athena's old 4-byte user-id runtime form. | `needs-traffic-capture` or `needs-reference-implementation-audit` | Stable-client traffic capture or reference implementation evidence selecting old 4-byte form versus modern `UserId` plus `QuitState` is missing. | This also keeps struct `QuitState` as `needs reference evidence`. |
| S2C 62 `UNAUTHORIZED` | Guide lists no-payload `UNAUTHORIZED`; matrix records current login and polling failures using negative `LOGIN_REPLY`. | `needs-reference-implementation-audit` | Reference implementation evidence for when stable clients expect `UNAUTHORIZED` instead of `LOGIN_REPLY` is missing. | Keep runtime behavior gap visible before adding or omitting this emission path. |
| S2C 80 `MONITOR` | Guide lists no-payload `MONITOR`; matrix has no confirmed compatibility purpose or emission trigger. | `needs-reference-implementation-audit` | Reference implementation path or client-observable trigger for `MONITOR` is missing. | Keep classification as `needs reference evidence`; no fixture or runtime completion is claimed. |
| S2C 105 `RTX` | Guide lists `String`; matrix marks the packet unknown/rare with no confirmed Athena behavior or trigger. | `needs-reference-implementation-audit` | Reference implementation path or client-observable trigger for `RTX` is missing. | Keep classification as `needs reference evidence`; payload shape alone does not prove requirement. |
| `QuitState` | Guide lists values `0..2`; matrix records missing canonical enum support and unresolved dependency on S2C `USER_QUIT` shape. | `needs-reference-implementation-audit` | Reference implementation or traffic evidence must choose old 4-byte `USER_QUIT` form versus modern `UserId` plus `QuitState`. | Struct fixture extraction remains blocked until the packet shape is selected. |

## Stable HTTP Endpoint Coverage

Implemented route source: `src/osu_server/composition/application.py`. Candidate
rows are derived from `osuRipple/lets` and `osuTitanic/deck`; confirm each by
target client traffic before making it a required Athena surface.

Candidate rows must not remain indefinite. For each candidate endpoint, create a
tracking issue that records whether target stable clients call it, then promote
it to `Implemented` / `Partial` / `Missing` when it is required, or demote it to
`Out of scope` when traffic and reference review show it is unnecessary.

The `Current status` column remains implementation or inventory state. The
`Final audit classification` column is the Issue #32 legacy web-family audit
axis. Bancho host/login and adjacent registration rows use `N/A` because they
are not legacy endpoint body rows. Adjacent release, static, media, download,
and non-web diagnostic rows use `out of scope` when they are listed here only to
preserve overlap boundaries for later specs.

| Method | Endpoint | Current status | Final audit classification | Concise reason / evidence |
| --- | --- | --- | --- | --- |
| `POST` | `/` on `c.$DOMAIN`, `c<int>.$DOMAIN`, `ce.$DOMAIN` | Implemented | N/A | Bancho login and packet polling entrypoint; outside Issue #32 legacy web-family endpoint audit. |
| `POST` | `/` on `cho.$DOMAIN`, `mahbahowc.$DOMAIN`, `server.$DOMAIN` | Candidate | N/A | Bancho host aliases observed in `osuTitanic/titanic`; not currently routed by Athena and not a legacy web body row. |
| `POST` | `/users` on `osu.$DOMAIN` | Implemented | N/A | Adjacent registration context, not a legacy PHP exact path. Evidence: `src/osu_server/composition/application.py`, `src/osu_server/transports/stable/web_legacy/registration.py`; guide `/users` evidence note. |
| `POST` | `/web/users` local fallback | Implemented | N/A | Development registration fallback, not a legacy PHP exact path. Evidence: `src/osu_server/composition/application.py`, `src/osu_server/transports/stable/web_legacy/registration.py`; guide `/users` evidence note. |
| `GET` | `/web/bancho_connect.php` | Partial | `needs reference evidence` | Bancho reachability: current route returns reachability-only empty 200 and delegates credentials to login, but reference alternatives still leave pre-login validation, country-code/IP response, and malformed-query fixture gaps open. |
| `GET` | `/web/osu-osz2-getscores.php` | Partial | `required` | Modern getscores: stable response mapping exists, but full score rows, branch fixtures, and real-client evidence remain incomplete; guide `/web/osu-osz2-getscores.php` evidence note. |
| `POST` | `/web/osu-submit-modular-selector.php` | Partial | `required` | Modern score submit selector: score submission route exists, but rank/stat projection fields, auth-specific sentinels, and fixture coverage remain incomplete; guide `/web/osu-submit-modular-selector.php` evidence note. |
| `POST` | `/web/osu-submit-modular.php` | Candidate | `needs reference evidence` | Legacy score submit aliases: no Athena route and alias-specific request/response fixtures are missing; guide Legacy score submit aliases / Task 2.3 evidence note. |
| `POST` | `/web/osu-submit.php`, `/web/osu-submit-new.php` | Candidate | `needs reference evidence` | Legacy score submit aliases: no Athena routes and current target-client traffic is unconfirmed; guide Legacy score submit aliases / Task 2.3 evidence note. |
| `POST` | `/web/osu-session.php` | Candidate | `needs reference evidence` | Session candidate: no Athena route; `bancho.py` lists it as unhandled, but no source Reference Route Inventory exact row or current target-client traffic confirms the contract; guide `/web/osu-session.php` evidence note. |
| `GET` | `/web/osu-getscores.php` through `/web/osu-getscores6.php` | Candidate | `needs reference evidence` | Legacy getscores aliases: per-path response variants must not share the modern osz2 formatter without fixtures; guide Legacy getscores aliases / Task 2.3 evidence note. |
| `GET` | `/web/osu-getreplay.php` | Missing | `needs reference evidence` | Replay download PHP route: missing implementation plus unresolved auth, target path choice, fixture, and traffic evidence; guide Replay Download / Task 2.2 evidence note. |
| `GET` | `/web/replays/<id>` | Candidate | N/A | Adjacent non-PHP replay alias from `lets`; keep beside `/web/osu-getreplay.php` without classifying it as a legacy PHP exact path. |
| `GET` | `/web/check-updates.php` | Missing | `compatibility no-op` | Update check PHP route: initial no-update policy selects `[]` as the stable-compatible body; release/update audit records fixture handoff `check_updates_no_update_json_array`, no external operational dependency, `deck` JSON-array evidence, `bancho.py` empty-body contrast, and user-confirmed current osu!stable `--devserver` behavior. Proxy/nope variants remain future operational policy. |
| `GET` | `/release/update`, `/release/update.php`, `/release/update2.php`, `/release/patches.php`, `/update`, `/update.php`, `/update2.php`, `/patches.php` | Missing | `out of scope` | Adjacent release-update scope, not legacy web-family body audit rows; no Athena routes are registered, and release/update audit records no-update sibling contracts with empty-body and `0` fixture handoffs for later implementation. |
| `GET` | `/release/<filename>`, `/release/filter.txt`, `/release/Localisation/<filename>`, `/release/<language>/<filename>` | Candidate | `out of scope` | Release files, filters, and localisation artifacts are adjacent release-update scope; hosted artifact and proxy routes remain deferred behind explicit operational decisions. |
| `GET` | `/web/osu-search.php`, `/web/osu-search-set.php` | Missing | `needs reference evidence` | osu!direct search and set lookup: real compatibility surface, but P0/deferred timing needs target-client traffic and failure fixtures; guide Task 2.4 osu!direct PHP evidence note. |
| `GET` | `/d/<set>`, `/s/<set>`, `/bss/<set>`, `/osu/<map>`, `/web/maps/<file>`, `b.$DOMAIN/<path>`, `s.$DOMAIN/<path>`, `d.$DOMAIN/d/<set>` | Candidate | `out of scope` | Adjacent beatmap file delivery scope; keep file bytes, redirects, and download headers outside the legacy PHP body audit. |
| `GET` | `/mt/*`, `/thumb/*`, `/images/map-thumb/*`, `/preview/*`, `/mp3/preview/*` | Candidate | `out of scope` | Adjacent beatmap media delivery scope; thumbnail and preview fixtures belong to static/media follow-up work. |
| `POST` | `/web/osu-getbeatmapinfo.php` | Missing | `needs reference evidence` | Legacy beatmap info: separate from Bancho packet 68/69, and exact current-client traffic plus body fixtures are unconfirmed; guide Task 2.4 `/web/osu-getbeatmapinfo.php` evidence note. |
| `GET` | `/web/osu-gethashes.php`, `/web/osu-osz2-getfileinfo.php`, `/web/osu-osz2-getrawheader.php`, `/web/osu-osz2-getfilecontents.php`, `/web/osu-magnet.php` | Candidate | `needs reference evidence` | OSZ2/hash helpers: reference-only variants require per-path auth, success bytes/text, not-found, 501, malformed params, and traffic fixtures; guide Task 2.4 OSZ2/hash helper evidence note. |
| `POST` | `/web/osu-screenshot.php`, `/web/osu-ss.php` | Missing | `needs reference evidence` | Screenshot upload and client diagnostics: upload response variants differ across references and `/ss/*` serving remains adjacent media scope; guide Task 2.5 screenshots and diagnostics evidence note. |
| `GET` | `/ss/`, `/ss/<id>`, `/ss/<id>/<checksum>`, `/ss/<id>.<extension>` | Candidate | `out of scope` | Adjacent screenshot media serving scope; keep separate from `/web/osu-screenshot.php` and `/web/osu-ss.php` upload classifications. |
| `GET` | `/a/`, `/a/<filename>`, `/forum/download.php` | Candidate | `out of scope` | Adjacent static/media context; avatar delivery belongs to static/media scope. |
| `GET` | `/assets/menu-content.json`, `/menu-content.json` | Candidate | `needs reference evidence` | Title/menu UI: client-visible menu JSON contract is named by Requirement 7.3 and needs current-client traffic, exact JSON body, cache, and disabled/missing-asset fixtures. |
| `POST` | `/web/osu-error.php` | Candidate | `needs reference evidence` | Screenshot upload and client diagnostics: client error report route needs request body and success/failure response fixtures before no-op or required behavior can be chosen. |
| `GET` | `/web/osu-rate.php`, `/rating/ingame-rate.php`, `/rating/ingame-rate2.php` | Candidate | `needs reference evidence` | Ratings: response sentinels are reference-documented, but current-client traffic and per-path fixtures are missing; guide Task 2.5 ratings evidence note. |
| `POST` | `/web/osu-comment.php` | Candidate | `needs reference evidence` | Comments and favourites: comment get/post variants and moderation/error sentinels require fixtures; guide Task 2.5 comments and favourites evidence note. |
| `GET` | `/web/osu-addfavourite.php`, `/web/osu-getfavourites.php` | Candidate | `needs reference evidence` | Comments and favourites: favourite mutation/list behavior needs auth, limit, already-state, and not-found fixtures; guide Task 2.5 comments and favourites evidence note. |
| `GET` | `/web/osu-stat.php`, `/web/osu-statoth.php` | Candidate | `needs reference evidence` | Stats and friends: stats/avatar row shape is reference-documented, but current-client traffic and projection ownership are unresolved; guide Task 2.5 stats and friends evidence note. |
| `GET` | `/web/osu-getstatus.php` | Candidate | `needs reference evidence` | Beatmap checksum status: checksum/status shape is reference-documented, but current-client traffic and fixture coverage are missing; guide `/web/osu-getstatus.php` evidence note. |
| `GET` | `/web/osu-getfriends.php` | Missing | `needs reference evidence` | Stats and friends: friend packets exist, but this web route has no Athena implementation or target-client traffic fixture; guide Task 2.5 stats and friends evidence note. |
| `GET` | `/web/osu-markasread.php`, `/web/osu-checktweets.php`, `/web/lastfm.php` | Candidate | `needs reference evidence` | Social/status no-op candidates: exact empty/static response body, `/web/lastfm.php` request shape, and current-client traffic are unconfirmed; guide Task 2.5 social/status no-op evidence note. |
| `GET` | `/web/osu-getseasonal.php` | Missing | `needs reference evidence` | Seasonal UI: current osu!stable call is confirmed and reference behavior is a JSON array, but the exact empty-array body and cache contract still need a focused fixture before final no-op classification. |
| `GET` | `/web/osu-login.php` | Candidate | `needs reference evidence` | Login preflight: web login usage, `1`/`0` failure behavior, and relationship to Bancho login need current-client traffic and auth fixtures; guide Task 2.5 login preflight evidence note. |
| `GET` | `/web/osu-title-image.php` | Candidate | `needs reference evidence` | Title/menu UI: image bytes, empty body, redirect variants, and paired menu JSON body/cache behavior are unresolved; guide Task 2.5 title/menu evidence note. |
| `GET` | `/web/coins.php` | Candidate | `out of scope` | Private-server currency and benchmark: private-server currency is outside current osu!stable normal-play compatibility; guide Task 2.5 private-server decision. |
| `POST` | `/web/osu-benchmark.php` | Candidate | `out of scope` | Private-server currency and benchmark: benchmark diagnostics are outside current osu!stable normal-play compatibility; guide Task 2.5 private-server decision. |
| `POST` | `/difficulty-rating` | Candidate | `out of scope` | Non-web diagnostics: outside the legacy `/web/*.php` and `/rating/ingame-rate*.php` audit boundary; product-scope revalidation remains future work if Athena supports it. |
| mixed | beatmap submission endpoints under `/web/osu-bmsubmit-*` and `/web/osu-osz2-bmsubmit-*` | Candidate | `deferred` | Beatmap submission is planned after core login/play/score compatibility and is not implemented by this audit; guide Task 2.5 beatmap submission decision. |

### Legacy Web Audit Scope Index

Task 1.1 locks the Issue #32 inventory boundary before classification work.
In-scope rows are legacy `/web/*.php` exact paths plus the same-family
`/rating/ingame-rate*.php` aliases. Release, static, media, and download rows
that overlap a legacy web family stay visible as adjacent context, but their
body policy is not classified by this audit scope.

| Endpoint family | Stable HTTP Endpoint Coverage grouped row | In-scope exact path rows |
| --- | --- | --- |
| Bancho reachability | `/web/bancho_connect.php` | `/web/bancho_connect.php` |
| Modern getscores | `/web/osu-osz2-getscores.php` | `/web/osu-osz2-getscores.php` |
| Legacy getscores aliases | `/web/osu-getscores.php` through `/web/osu-getscores6.php` | `/web/osu-getscores.php`, `/web/osu-getscores2.php`, `/web/osu-getscores3.php`, `/web/osu-getscores4.php`, `/web/osu-getscores5.php`, `/web/osu-getscores6.php` |
| Modern score submit selector | `/web/osu-submit-modular-selector.php` | `/web/osu-submit-modular-selector.php` |
| Legacy score submit aliases | `/web/osu-submit-modular.php`; `/web/osu-submit.php`, `/web/osu-submit-new.php` | `/web/osu-submit-modular.php`, `/web/osu-submit.php`, `/web/osu-submit-new.php` |
| Session candidate | `/web/osu-session.php` | `/web/osu-session.php` grouped-row-only candidate; `bancho.py` unhandled-route trace exists, but no matching Reference Route Inventory row yet |
| Replay download PHP route | `/web/osu-getreplay.php` | `/web/osu-getreplay.php` |
| Update check PHP route | `/web/check-updates.php` | `/web/check-updates.php`; release/update artifact routes are adjacent context |
| osu!direct search and set lookup | `/web/osu-search.php`, `/web/osu-search-set.php` | `/web/osu-search.php`, `/web/osu-search-set.php` |
| Legacy beatmap info | `/web/osu-getbeatmapinfo.php` | `/web/osu-getbeatmapinfo.php` |
| Beatmap checksum status | `/web/osu-getstatus.php` | `/web/osu-getstatus.php` |
| OSZ2/hash helpers | `/web/osu-gethashes.php`, `/web/osu-osz2-getfileinfo.php`, `/web/osu-osz2-getrawheader.php`, `/web/osu-osz2-getfilecontents.php`, `/web/osu-magnet.php` | `/web/osu-gethashes.php`, `/web/osu-osz2-getfileinfo.php`, `/web/osu-osz2-getrawheader.php`, `/web/osu-osz2-getfilecontents.php`, `/web/osu-magnet.php` |
| Screenshot upload and client diagnostics | `/web/osu-screenshot.php`, `/web/osu-ss.php`; `/web/osu-error.php` | `/web/osu-screenshot.php`, `/web/osu-ss.php`, `/web/osu-error.php`; `/ss/*` serving routes are adjacent media context |
| Ratings | `/web/osu-rate.php`, `/rating/ingame-rate.php`, `/rating/ingame-rate2.php` | `/web/osu-rate.php`, `/rating/ingame-rate.php`, `/rating/ingame-rate2.php` |
| Comments and favourites | `/web/osu-comment.php`; `/web/osu-addfavourite.php`, `/web/osu-getfavourites.php` | `/web/osu-comment.php`, `/web/osu-addfavourite.php`, `/web/osu-getfavourites.php` |
| Stats and friends | `/web/osu-stat.php`, `/web/osu-statoth.php`; `/web/osu-getfriends.php` | `/web/osu-stat.php`, `/web/osu-statoth.php`, `/web/osu-getfriends.php` |
| Social/status no-op candidates | `/web/osu-markasread.php`, `/web/osu-checktweets.php`, `/web/lastfm.php` | `/web/osu-markasread.php`, `/web/osu-checktweets.php`, `/web/lastfm.php` |
| Seasonal UI | `/web/osu-getseasonal.php` | `/web/osu-getseasonal.php` |
| Title/menu UI | `/web/osu-title-image.php`, `/assets/menu-content.json`, `/menu-content.json` | `/web/osu-title-image.php`, `/assets/menu-content.json`, `/menu-content.json` |
| Login preflight | `/web/osu-login.php` | `/web/osu-login.php` |
| Private-server currency and benchmark | `/web/coins.php`, `/web/osu-benchmark.php` | `/web/coins.php`, `/web/osu-benchmark.php` |
| Beatmap submission | Beatmap submission endpoints under `/web/osu-bmsubmit-*` and `/web/osu-osz2-bmsubmit-*` | `/web/osu-osz2-bmsubmit-getid.php`, `/web/osu-osz2-bmsubmit-upload.php`, `/web/osu-osz2-bmsubmit-post.php`, `/web/osu-get-beatmap-topic.php`, `/web/osu-bmsubmit-getid5.php`, `/web/osu-bmsubmit-getid4.php`, `/web/osu-bmsubmit-getid3.php`, `/web/osu-bmsubmit-getid2.php`, `/web/osu-bmsubmit-getid.php`, `/web/osu-bmsubmit-upload.php`, `/web/osu-bmsubmit-novideo.php`, `/web/osu-bmsubmit-post3.php`, `/web/osu-bmsubmit-post2.php`, `/web/osu-bmsubmit-post.php` |

Adjacent context rows that must not be absorbed into the Issue #32 body audit:

| Adjacent context | Matrix rows / exact paths | Scope note |
| --- | --- | --- |
| Registration fallback | `/users` on `osu.$DOMAIN`; `/web/users` local fallback | Stable web registration context, but not a legacy `/web/*.php` route. |
| Replay non-PHP alias | `/web/replays/<id>` grouped row; `/web/replays/{id}` exact alias | Keep as replay download context beside `/web/osu-getreplay.php`. |
| Release/update artifacts | `/release/update*`, `/update*`, `/patches.php`, `/release/<filename>`, `/release/filter.txt`, `/release/Localisation/<filename>`, `/release/<language>/<filename>` | Body policy belongs to release/update scope; only `/web/check-updates.php` is in the legacy web path inventory. |
| Beatmap downloads and files | `/d/*`, `/s/*`, `/bss/*`, `/osu/*`, `/web/maps/{query}`, download host aliases | Download and `.osu` file delivery scope, adjacent to osu!direct and OSZ2 helpers. |
| Static/media serving | `/ss/*`, `/a/*`, `/forum/download.php`, `/mt/*`, `/thumb/*`, `/images/map-thumb/*`, `/preview/*`, `/mp3/preview/*`, static host aliases | Media delivery scope; PHP upload or menu routes remain listed above when they match in-scope path rules. |
| Menu JSON | `/assets/menu-content.json`, `/menu-content.json` | Title/menu UI needs-evidence context adjacent to `/web/osu-title-image.php`; not a `/web/*.php` exact path but named by Requirement 7.3. |
| Non-web diagnostics | `/difficulty-rating` | Outside the legacy web-family path rules. |

### Task 2.2 P0 Play-Adjacent Family Audit

This table records current implementation status separately from final audit
classification and evidence gaps. `Missing implementation` means Athena does
not currently register a route in `src/osu_server/composition/application.py`.
`Missing evidence` means request/response fixtures or branch-specific evidence
are absent. `Missing traffic evidence` means no current osu!stable client probe
has confirmed that exact path and behavior.

| Endpoint family | Current implementation status | Task 2.2 classification / audit result | Evidence source | Separated gaps |
| --- | --- | --- | --- | --- |
| Registration fallback | Implemented on `POST /users` and local `POST /web/users` fallback | Adjacent required registration context; not a legacy `/web/*.php` final-audit row | `src/osu_server/composition/application.py`; `src/osu_server/transports/stable/web_legacy/registration.py`; guide `/users` evidence note | Missing evidence: malformed-form fixture and stable registration traffic branch evidence. Missing traffic evidence: local fallback usage is development-oriented. |
| Bancho reachability | Partial | `needs reference evidence` until the reachability-only empty response, pre-login validation, and country-code/IP variants are fixture-backed | `src/osu_server/composition/application.py`; `src/osu_server/transports/stable/web_legacy/bancho_connect.py`; guide `/web/bancho_connect.php` evidence note | Missing evidence: real-client fixture proving empty body is sufficient across target builds. Missing traffic evidence: pre-login validation/country-code need is unconfirmed. |
| Modern getscores | Partial | `required` | `src/osu_server/composition/application.py`; `src/osu_server/transports/stable/web_legacy/getscores.py`; `src/osu_server/transports/stable/web_legacy/mappers/getscores.py`; guide `/web/osu-osz2-getscores.php` evidence note | Missing evidence: branch fixtures for auth failure, unavailable, update available, header/rows, malformed identity, friends/country selections, and real-client probes. Missing implementation: complete leaderboard projections remain partial. |
| Modern score submit selector | Partial | `required` | `src/osu_server/composition/application.py`; `src/osu_server/transports/stable/web_legacy/score_submit.py`; `src/osu_server/transports/stable/web_legacy/mappers/score_submit.py`; guide `/web/osu-submit-modular-selector.php` evidence note | Missing evidence: auth-specific sentinel mapping, multipart variant fixtures, failure branch fixtures, and real-client probes. Missing implementation: rank/stat/achievement projection and some post-submit durability remain partial. |
| Replay download PHP route | Missing | `needs reference evidence` until target path, auth, and response fixtures are confirmed | Stable HTTP Endpoint Coverage row; guide Replay Download section; Reference Route Inventory `/web/osu-getreplay.php` row | Missing implementation: no Athena route. Missing evidence: success bytes, auth failure, malformed request, and missing-replay fixture coverage. Missing traffic evidence: current target-client path choice between `/web/osu-getreplay.php` and adjacent `/web/replays/{id}` is unconfirmed. |
| Session candidate | Candidate only | `needs reference evidence` | Stable HTTP Endpoint Coverage row; guide `/web/osu-session.php` evidence note; `bancho.py` unhandled-route trace | Missing implementation: no Athena route. Missing evidence: auth method, params, success body, failure sentinels, and exact Reference Route Inventory row. Missing traffic evidence: no current target-client probe confirms the path is still called. |

### Task 2.3 Legacy Alias Audit

These aliases are best effort support candidates for older stable clients. They
are not part of the current osu!stable P0 required path while target-client
traffic is unconfirmed. Keep them `needs reference evidence` until exact
request, response, auth failure, domain failure, and malformed request fixtures
exist per alias.

| Exact path | Family | Current implementation status | Task 2.3 classification / audit result | Variant and evidence note |
| --- | --- | --- | --- | --- |
| `/web/osu-getscores6.php` | Legacy getscores alias | Candidate only | `needs reference evidence` | Reference inventory lists the path in `deck`, but the exact response delta from `/web/osu-osz2-getscores.php` still needs a fixture. |
| `/web/osu-getscores5.php` | Legacy getscores alias | Candidate only | `needs reference evidence` | Reference inventory lists the path in `deck`; per-version omitted fields and failure sentinels are unconfirmed. |
| `/web/osu-getscores4.php` | Legacy getscores alias | Candidate only | `needs reference evidence` | Reference inventory lists the path in `deck`; per-version omitted fields and failure sentinels are unconfirmed. |
| `/web/osu-getscores3.php` | Legacy getscores alias | Candidate only | `needs reference evidence` | Reference inventory lists the path in `deck`; per-version omitted fields and failure sentinels are unconfirmed. |
| `/web/osu-getscores2.php` | Legacy getscores alias | Candidate only | `needs reference evidence` | Reference inventory lists the path in `deck`; per-version omitted fields and failure sentinels are unconfirmed. |
| `/web/osu-getscores.php` | Legacy getscores alias | Candidate only | `needs reference evidence` | Guide notes the oldest route returns legacy score rows separated by `:`, but auth, not-found, malformed, and current-client traffic evidence are still missing. |
| `/web/osu-submit-modular.php` | Legacy score submit alias | Candidate only | `needs reference evidence` | Reference inventory lists the alias in `lets` and `deck`; request source, multipart/query variant, and response sentinel mapping are unconfirmed. |
| `/web/osu-submit.php` | Legacy score submit alias | Candidate only | `needs reference evidence` | Reference inventory lists the alias in `deck`; old payload shape, auth failure, and malformed request behavior are unconfirmed. |
| `/web/osu-submit-new.php` | Legacy score submit alias | Candidate only | `needs reference evidence` | Reference inventory lists the alias in `deck`; request/response variant and target-client traffic evidence are unconfirmed. |

### Task 2.4 Beatmap Lookup And File-Helper Audit

This audit keeps legacy PHP lookup endpoints separate from adjacent file,
download, and static/media delivery routes. `/web/maps/{query}` is adjacent
because it returns `.osu` file bytes rather than a PHP response contract, even
though the path starts with `/web/`.

| Endpoint family | In-scope exact paths | Current implementation status | Task 2.4 classification / audit result | Evidence source | Separated gaps |
| --- | --- | --- | --- | --- | --- |
| osu!direct search and set lookup | `/web/osu-search.php`, `/web/osu-search-set.php` | Missing | `needs reference evidence` | Stable HTTP Endpoint Coverage row; guide Task 2.4 osu!direct PHP evidence note; Reference Route Inventory rows | Missing implementation: no Athena routes. Missing evidence: auth variants, search/set success fixtures, 401/404/error fixtures, pagination variants, and current-client traffic. Timing may become deferred only after target-client evidence proves it is outside P0. |
| Legacy beatmap info | `/web/osu-getbeatmapinfo.php` | Missing | `needs reference evidence` | Stable HTTP Endpoint Coverage row; guide Task 2.4 `/web/osu-getbeatmapinfo.php` evidence note; Reference Route Inventory row | Missing implementation: no Athena route. Missing evidence: exact request body encoding, auth behavior, >100 request sentinel, malformed body behavior, and relationship to Bancho packet 68/69. |
| Beatmap checksum status | `/web/osu-getstatus.php` | Candidate only | `needs reference evidence` | Stable HTTP Endpoint Coverage row; guide `/web/osu-getstatus.php` evidence note; Reference Route Inventory row | Missing implementation: no Athena route. Missing evidence: current-client traffic, checksum limit behavior, malformed checksum list behavior, and status mapping fixtures. |
| OSZ2/hash helpers | `/web/osu-gethashes.php`, `/web/osu-osz2-getfileinfo.php`, `/web/osu-osz2-getrawheader.php`, `/web/osu-osz2-getfilecontents.php`, `/web/osu-magnet.php` | Candidate only | `needs reference evidence` | Stable HTTP Endpoint Coverage row; guide Task 2.4 OSZ2/hash helper evidence note; Reference Route Inventory rows | Missing implementation: no Athena routes. Missing evidence: per-path auth, success bytes/text, file-not-found behavior, 501 magnet policy, malformed params, and current-client traffic. |
| Adjacent beatmap file delivery | `/web/maps/{query}`, `/d/*`, `/s/*`, `/bss/*`, `/osu/*`, download host aliases | Adjacent context | Not classified by Issue #32 body audit | Adjacent context table; guide file/media behavior table | Missing implementation/evidence belongs to static/media/download route scope, not this legacy PHP audit. |
| Adjacent beatmap media delivery | `/mt/*`, `/thumb/*`, `/images/map-thumb/*`, `/preview/*`, `/mp3/preview/*` | Adjacent context | Not classified by Issue #32 body audit | Adjacent context table; guide file/media behavior table | Missing implementation/evidence belongs to static/media/download route scope, not this legacy PHP audit. |

### Task 2.5 Social, UI, And Private-Server Audit

This table records remaining social/status/UI/private-server families. It
keeps confirmed no-op candidates separate from dynamic routes that need fixtures
or later product scope decisions.

| Endpoint family | In-scope exact paths | Current implementation status | Task 2.5 classification / audit result | Evidence source | Separated gaps |
| --- | --- | --- | --- | --- | --- |
| Screenshot upload and client diagnostics | `/web/osu-screenshot.php`, `/web/osu-ss.php`, `/web/osu-error.php` | Missing/candidate | `needs reference evidence` | Stable HTTP Endpoint Coverage row; guide Task 2.5 screenshots and diagnostics evidence note | Missing implementation: no Athena routes. Missing evidence: upload/error request bodies, success bodies, failure sentinels, media-serving handoff, and current-client traffic. |
| Ratings | `/web/osu-rate.php`, `/rating/ingame-rate.php`, `/rating/ingame-rate2.php` | Candidate only | `needs reference evidence` | Stable HTTP Endpoint Coverage row; guide Task 2.5 ratings evidence note | Missing implementation: no Athena routes. Missing evidence: per-path success variants, failure sentinels, malformed request behavior, and target-client traffic. |
| Comments and favourites | `/web/osu-comment.php`, `/web/osu-addfavourite.php`, `/web/osu-getfavourites.php` | Candidate only | `needs reference evidence` | Stable HTTP Endpoint Coverage row; guide Task 2.5 comments and favourites evidence note | Missing implementation: no Athena routes. Missing evidence: auth, get/post variants, favourite limit/already state, malformed request behavior, and current-client traffic. |
| Stats and friends | `/web/osu-stat.php`, `/web/osu-statoth.php`, `/web/osu-getfriends.php` | Candidate/missing | `needs reference evidence` | Stable HTTP Endpoint Coverage row; guide Task 2.5 stats and friends evidence note | Missing implementation: no Athena routes. Missing evidence: stats projection ownership, avatar hash source, auth failure, empty friends response, and current-client traffic. |
| Social/status no-op candidates | `/web/osu-markasread.php`, `/web/osu-checktweets.php`, `/web/lastfm.php` | Candidate only | `needs reference evidence` | Stable HTTP Endpoint Coverage row; guide Task 2.5 social/status no-op evidence note | Missing implementation: no Athena routes. Missing evidence: exact empty/static body, unknown-channel behavior, malformed request behavior, and current-client traffic. |
| Seasonal UI | `/web/osu-getseasonal.php` | Missing | `needs reference evidence` | User-confirmed current osu!stable call; guide Task 2.5 seasonal UI evidence note; reference JSON array family shape | Missing implementation: no Athena route. Missing evidence: focused fixture for exact empty JSON array body, cache headers, and dynamic seasonal asset management follow-up. |
| Title/menu UI | `/web/osu-title-image.php`, `/assets/menu-content.json`, `/menu-content.json` | Candidate only | `needs reference evidence` | Stable HTTP Endpoint Coverage row; guide Task 2.5 title/menu evidence note | Missing implementation: no Athena routes. Missing evidence: current-client traffic, image/empty/redirect variant selection, menu JSON body/cache, missing-asset behavior, and static asset policy. |
| Login preflight | `/web/osu-login.php` | Candidate only | `needs reference evidence` | Stable HTTP Endpoint Coverage row; guide Task 2.5 login preflight evidence note | Missing implementation: no Athena route. Missing evidence: current-client usage, auth failure behavior, malformed params, and relationship to Bancho login. |
| Private-server currency and benchmark | `/web/coins.php`, `/web/osu-benchmark.php` | Candidate only | `out of scope` | Stable HTTP Endpoint Coverage row; guide Task 2.5 private-server decision and evidence note | Missing implementation intentionally remains outside current normal-play compatibility unless product scope changes. |
| Beatmap submission | `/web/osu-osz2-bmsubmit-*`, `/web/osu-bmsubmit-*`, `/web/osu-get-beatmap-topic.php` | Candidate only | `deferred` | Stable HTTP Endpoint Coverage row; guide Task 2.5 beatmap submission decision and evidence note | Missing implementation/evidence tracked as post-core compatibility work after login/play/score core is complete. |

### Task 5.1 Requirement Coverage And Classification Completeness

This verification table ties every Issue #32 requirement ID to the audit docs
that now prove it. It does not introduce new runtime scope; it only records
where the matrix, guide, or follow-up checklist demonstrates coverage.

| Requirement | Verification evidence |
| --- | --- |
| 1.1 | Legacy Web Audit Scope Index lists every in-scope legacy `/web/*.php` family and exact path from the Issue #32 source inventory. |
| 1.2 | Legacy Web Audit Scope Index and Reference Route Inventory include `/rating/ingame-rate.php` and `/rating/ingame-rate2.php` under Ratings. |
| 1.3 | Stable HTTP Endpoint Coverage, Legacy Web Audit Scope Index, Reference Route Inventory, and Coverage Rows Without Reference Exact Routes cross-check grouped rows against exact paths. |
| 1.4 | Adjacent context table keeps release, static, media, download, menu JSON, replay alias, registration, and non-web diagnostics out of the body audit. |
| 2.1 | Final Audit Classification Contract in the guide and the matrix policy define the allowed final classifications. |
| 2.2 | Stable HTTP Endpoint Coverage separates `Current status` from `Final audit classification`; the final classification column has no `candidate` value. |
| 2.3 | Modern getscores and modern score submit selector are classified `required` because their current osu!stable workflows need real behavior. |
| 2.4 | Bancho reachability remains `needs reference evidence` until pre-login validation, country-code/IP response, and malformed-query fixture gaps are closed; Seasonal UI remains `needs reference evidence` until its exact no-op body/cache contract is fixture-backed. |
| 2.5 | Unknown aliases, response shapes, auth sentinels, and target-client traffic gaps remain `needs reference evidence` instead of guessed classifications. |
| 3.1 | Guide endpoint family evidence notes include an Auth method row for every audited family updated by Tasks 2.2 through 2.5. |
| 3.2 | Guide endpoint family evidence notes include a Required request params row for every audited family updated by Tasks 2.2 through 2.5. |
| 3.3 | Guide endpoint family evidence notes include a Success response row for every audited family updated by Tasks 2.2 through 2.5. |
| 3.4 | Guide endpoint family evidence notes include an Auth failure response row for every audited family updated by Tasks 2.2 through 2.5. |
| 3.5 | Guide endpoint family evidence notes include a Domain/data-not-found response row for every audited family updated by Tasks 2.2 through 2.5. |
| 3.6 | Guide endpoint family evidence notes include a Malformed request response row for every audited family updated by Tasks 2.2 through 2.5. |
| 4.1 | Stable HTTP Endpoint Coverage concise reasons, task audit tables, and Reference Route Inventory traceability name the matrix row, guide note, or implementation evidence source. |
| 4.2 | Final Audit Classification Contract states the evidence sources needed to leave `needs reference evidence`; follow-up checklist rows keep unresolved evidence visible. |
| 4.3 | Rows with unknown response shape, including old aliases, title/menu, ratings, and social/status, remain `needs reference evidence` rather than `compatibility no-op`; `/web/check-updates.php` is excluded from that unknown set because release/update evidence selected the `[]` no-update body. |
| 4.4 | Reference-only routes without current osu!stable traffic, including session, legacy aliases, OSZ2 helpers, and social/status routes, are not marked P0 `required`. |
| 5.1 | Guide Final Audit Classification Contract and legacy alias notes state current osu!stable is the primary target. |
| 5.2 | Legacy getscores alias table keeps `/web/osu-getscores.php` through `/web/osu-getscores6.php` as `needs reference evidence` until per-alias variants are known. |
| 5.3 | Legacy score submit alias table keeps `/web/osu-submit-modular.php`, `/web/osu-submit.php`, and `/web/osu-submit-new.php` as `needs reference evidence`. |
| 5.4 | Legacy alias audit text identifies those aliases as best effort support candidates for older stable clients, not current-client P0 requirements. |
| 6.1 | Beatmap submission grouped and exact path rows are classified `deferred`. |
| 6.2 | `/web/coins.php` is classified `out of scope` with private-server currency rationale. |
| 6.3 | `/web/osu-benchmark.php` is classified `out of scope` with benchmark diagnostics rationale. |
| 6.4 | Deferred and out-of-scope reasons appear in Stable HTTP Endpoint Coverage and the guide private-server / beatmap submission decision table. |
| 7.1 | Seasonal UI row records user-confirmed current osu!stable traffic for `/web/osu-getseasonal.php`. |
| 7.2 | Seasonal UI keeps current-client traffic evidence visible but remains `needs reference evidence` until the exact empty-array/cache fixture confirms the no-op contract; dynamic seasonal asset management stays follow-up scope. |
| 7.3 | Title/menu UI keeps `/web/osu-title-image.php`, `/assets/menu-content.json`, and `/menu-content.json` as `needs reference evidence` until current-client traffic and exact body/cache behavior are confirmed. |
| 7.4 | Social/status no-op candidates remain `needs reference evidence` until exact empty/static bodies are confirmed in guide evidence notes. |
| 8.1 | Task 2.2 through 2.5 audit tables provide family-level classification or evidence gap for every in-scope family. |
| 8.2 | Reference Route Inventory exact rows point back to grouped rows, classification, and guide evidence notes. |
| 8.3 | Legacy getscores, submit aliases, OSZ2 helpers, title/menu, and screenshot rows preserve per-path variant gaps instead of collapsing them into family summaries. |
| 8.4 | Legacy Web Audit Scope Index maps each grouped Stable HTTP Endpoint Coverage row to its in-scope exact path rows. |
| 9.1 | Stable HTTP Endpoint Coverage includes the Final audit classification column and concise reason for each grouped row. |
| 9.2 | Reference Route Inventory includes Audit traceability for exact paths and Coverage Rows Without Reference Exact Routes for grouped rows without source exact rows. |
| 9.3 | Guide endpoint family evidence notes record detailed evidence gaps for every audited family that needs detail beyond the matrix. |
| 9.4 | Matrix and guide disagreements or insufficient behavior evidence are represented as `needs reference evidence` and unresolved follow-up gaps. |
| 10.1 | Audit-only Boundary Verification states this spec does not complete route implementation. |
| 10.2 | Audit-only Boundary Verification states this spec does not create golden fixture files. |
| 10.3 | Audit-only Boundary Verification states this spec does not execute real-client traffic capture. |
| 10.4 | Legacy Web Follow-up Checklist separates missing implementation work from audit completion. |
| 10.5 | Legacy Web Follow-up Checklist separates missing fixture/reference evidence and missing current-client traffic from audit completion. |

Classification completeness check:

| Check | Result |
| --- | --- |
| In-scope grouped rows have a final audit decision | Complete: every in-scope Stable HTTP Endpoint Coverage row has `required`, `compatibility no-op`, `deferred`, `out of scope`, or `needs reference evidence`. Non-legacy adjacent rows use `N/A` only when the final-audit axis does not apply. |
| Final `candidate` values are absent | Complete: `Candidate` remains only a `Current status`, source-inventory, or prose term. The `Final audit classification` column does not use `candidate`. |
| Evidence gaps remain explicit | Complete: unresolved request/response/auth/traffic gaps are classified `needs reference evidence` and carried into guide evidence notes or the follow-up checklist. |
| Audit-only scope remains intact | Complete: missing implementation, fixture, and traffic work are recorded as follow-up work rather than completed by this audit. |

## Akatsuki-Compatible Score Extensions

These are not baseline osu!stable requirements, but they are part of the
Akatsuki behavior set the project is using as an integrated reference. Keep them
visible so Athena does not accidentally design leaderboard persistence that
cannot support them later.

Decision status: RX/AP is not part of the initial vanilla stable compatibility
baseline, but score ingestion, leaderboard query repositories, and stats
projections must preserve a `leaderboard_family` or equivalent read-model key so
Athena can add separated vanilla, Relax, and Autopilot boards without a schema
redesign. The family belongs to score/stat projections, not to beatmap identity.

| Surface | Status | Requirement |
| --- | --- | --- |
| Relax score submit classification | Missing | Detect stable `Relax` mod (`128`) and map the submitted play to a separate Relax leaderboard family instead of vanilla. |
| Autopilot score submit classification | Missing | Detect stable `Autopilot` mod (`8192`) and map osu!standard plays to a separate Autopilot leaderboard family. |
| Expanded mode ids | Missing | Preserve a read-model policy for `vn!std=0`, `vn!taiko=1`, `vn!catch=2`, `vn!mania=3`, `rx!std=4`, `rx!taiko=5`, `rx!catch=6`, `ap!std=8`; Akatsuki declares `rx!mania=7` and `ap!taiko/catch/mania=9..11` but treats them as unused. |
| RX/AP getscores | Missing | `/web/osu-osz2-getscores.php` must be able to query personal best and top rows for the selected leaderboard family without mixing vanilla, Relax, and Autopilot rows. |
| RX/AP user stats and ranks | Missing | Stats projections need separate total/ranked score, pp, accuracy, play count, rank, country rank, and grade counts per supported leaderboard family. |
| RX/AP API/profile exposure | Candidate | First-party APIs and future profile/ranking pages should expose the same separated leaderboard families if Athena chooses Akatsuki-compatible RX/AP support. |

## Reference Route Inventory

This exact-path inventory is used to audit the grouped endpoint rows above.
Entries come from `osuTitanic/deck` route decorators, `osuTitanic/titanic`
host routing, and `osuAkatsuki/bancho.py` routes. Keep this list exact enough
for mechanical diff checks; implementation issues can still group related rows.
Task 3.1 adds traceability from each exact path back to the grouped matrix row
and to the final audit classification or evidence note that owns the current
decision. Adjacent static, media, download, release, and host-rewrite rows stay
separate from the legacy web-family final classification.

### Deck Web Routes

| Method | Endpoint | Area | Audit traceability |
| --- | --- | --- | --- |
| `GET` | `/web/bancho_connect.php` | connection | Grouped row: Bancho reachability. Task 2.2 classification: `needs reference evidence`; evidence: guide `/web/bancho_connect.php` evidence note. |
| `GET` | `/web/check-updates.php` | update | Grouped row: Update check PHP route. Task 3.2 classification: `compatibility no-op`; release/update audit selected the `[]` no-update body and fixture handoff `check_updates_no_update_json_array`, while proxy/nope variants and release artifacts remain adjacent future policy. |
| `POST` | `/web/osu-error.php` | diagnostics | Grouped row: Screenshot upload and client diagnostics. Task 2.5 classification: `needs reference evidence`; evidence: guide Task 2.5 screenshots and diagnostics evidence note. |
| `POST` | `/web/osu-screenshot.php` | screenshots | Grouped row: Screenshot upload and client diagnostics. Task 2.5 classification: `needs reference evidence`; response variants differ across references, and `/ss/*` serving is adjacent media scope. |
| `POST` | `/web/osu-ss.php` | screenshots/monitor | Grouped row: Screenshot upload and client diagnostics. Task 2.5 classification: `needs reference evidence`; response variant is not assumed to match `/web/osu-screenshot.php`. |
| `GET` | `/web/osu-osz2-getscores.php` | leaderboards | Grouped row: Modern getscores. Task 2.2 classification: `required`; evidence: guide `/web/osu-osz2-getscores.php` evidence note. |
| `GET` | `/web/osu-getscores6.php` | legacy leaderboards | Grouped row: Legacy getscores aliases. Task 2.3 classification: `needs reference evidence`; variant gap: exact response delta from modern osz2 formatter still needs a fixture. |
| `GET` | `/web/osu-getscores5.php` | legacy leaderboards | Grouped row: Legacy getscores aliases. Task 2.3 classification: `needs reference evidence`; variant gap: per-version omitted fields and failure sentinels are unconfirmed. |
| `GET` | `/web/osu-getscores4.php` | legacy leaderboards | Grouped row: Legacy getscores aliases. Task 2.3 classification: `needs reference evidence`; variant gap: per-version omitted fields and failure sentinels are unconfirmed. |
| `GET` | `/web/osu-getscores3.php` | legacy leaderboards | Grouped row: Legacy getscores aliases. Task 2.3 classification: `needs reference evidence`; variant gap: per-version omitted fields and failure sentinels are unconfirmed. |
| `GET` | `/web/osu-getscores2.php` | legacy leaderboards | Grouped row: Legacy getscores aliases. Task 2.3 classification: `needs reference evidence`; variant gap: per-version omitted fields and failure sentinels are unconfirmed. |
| `GET` | `/web/osu-getscores.php` | legacy leaderboards | Grouped row: Legacy getscores aliases. Task 2.3 classification: `needs reference evidence`; guide notes oldest-route `:` separated legacy rows, with auth/not-found/malformed evidence still missing. |
| `POST` | `/web/osu-submit-modular-selector.php` | score submit | Grouped row: Modern score submit selector. Task 2.2 classification: `required`; evidence: guide `/web/osu-submit-modular-selector.php` evidence note. |
| `POST` | `/web/osu-submit-modular.php` | score submit | Grouped row: Legacy score submit aliases. Task 2.3 classification: `needs reference evidence`; request source, multipart/query variant, and response sentinel mapping are unconfirmed. |
| `POST` | `/web/osu-submit.php` | legacy score submit | Grouped row: Legacy score submit aliases. Task 2.3 classification: `needs reference evidence`; old payload shape, auth failure, and malformed request behavior are unconfirmed. |
| `POST` | `/web/osu-submit-new.php` | legacy score submit | Grouped row: Legacy score submit aliases. Task 2.3 classification: `needs reference evidence`; request/response variant and target-client traffic evidence are unconfirmed. |
| `GET` | `/web/osu-getreplay.php` | replays | Grouped row: Replay download PHP route. Task 2.2 classification: `needs reference evidence`; evidence: guide Replay Download section. |
| `GET` | `/web/osu-search.php` | osu!direct | Grouped row: osu!direct search and set lookup. Task 2.4 classification: `needs reference evidence`; evidence: guide Task 2.4 osu!direct PHP evidence note. |
| `GET` | `/web/osu-search-set.php` | osu!direct | Grouped row: osu!direct search and set lookup. Task 2.4 classification: `needs reference evidence`; evidence: guide Task 2.4 osu!direct PHP evidence note. |
| `POST` | `/web/osu-getbeatmapinfo.php` | beatmaps | Grouped row: Legacy beatmap info. Task 2.4 classification: `needs reference evidence`; evidence: guide Task 2.4 `/web/osu-getbeatmapinfo.php` evidence note. |
| `GET` | `/web/osu-getstatus.php` | beatmaps | Grouped row: Beatmap checksum status. Task 2.4 classification: `needs reference evidence`; evidence: guide `/web/osu-getstatus.php` evidence note. |
| `GET` | `/web/maps/{query}` | beatmap files | Adjacent beatmap file delivery context. Not classified by the legacy PHP body audit; see Task 2.4 adjacent beatmap file delivery row and guide file/media behavior table. |
| `GET` | `/web/osu-gethashes.php` | osz2 | Grouped row: OSZ2/hash helpers. Task 2.4 classification: `needs reference evidence`; evidence: guide Task 2.4 OSZ2/hash helper evidence note. |
| `GET` | `/web/osu-osz2-getfileinfo.php` | osz2 | Grouped row: OSZ2/hash helpers. Task 2.4 classification: `needs reference evidence`; per-path file-info response fixtures are missing. |
| `GET` | `/web/osu-osz2-getrawheader.php` | osz2 | Grouped row: OSZ2/hash helpers. Task 2.4 classification: `needs reference evidence`; raw-header byte/text success and failure fixtures are missing. |
| `GET` | `/web/osu-osz2-getfilecontents.php` | osz2 | Grouped row: OSZ2/hash helpers. Task 2.4 classification: `needs reference evidence`; file-content success bytes and not-found behavior need fixtures. |
| `GET` | `/web/osu-magnet.php` | osz2 | Grouped row: OSZ2/hash helpers. Task 2.4 classification: `needs reference evidence`; magnet-specific 501 policy and malformed params need fixtures. |
| `GET` | `/web/osu-getfriends.php` | social | Grouped row: Stats and friends. Task 2.5 classification: `needs reference evidence`; evidence: guide Task 2.5 stats and friends evidence note. |
| `GET` | `/web/osu-addfavourite.php` | favourites | Grouped row: Comments and favourites. Task 2.5 classification: `needs reference evidence`; evidence: guide Task 2.5 comments and favourites evidence note. |
| `GET` | `/web/osu-getfavourites.php` | favourites | Grouped row: Comments and favourites. Task 2.5 classification: `needs reference evidence`; list response, auth, and not-found variants remain unconfirmed. |
| `GET` | `/web/osu-rate.php` | ratings | Grouped row: Ratings. Task 2.5 classification: `needs reference evidence`; evidence: guide Task 2.5 ratings evidence note. |
| `POST` | `/web/osu-comment.php` | comments | Grouped row: Comments and favourites. Task 2.5 classification: `needs reference evidence`; get/post variants and moderation/error sentinels require fixtures. |
| `GET` | `/web/osu-stat.php` | stats | Grouped row: Stats and friends. Task 2.5 classification: `needs reference evidence`; stats projection and avatar hash source are unresolved. |
| `GET` | `/web/osu-statoth.php` | stats | Grouped row: Stats and friends. Task 2.5 classification: `needs reference evidence`; alternate stats row shape and auth failure behavior need fixtures. |
| `GET` | `/web/osu-markasread.php` | social | Grouped row: Social/status no-op candidates. Task 2.5 classification: `needs reference evidence`; exact empty/static body and unknown-channel behavior need fixtures. |
| `GET` | `/web/osu-checktweets.php` | social | Grouped row: Social/status no-op candidates. Task 2.5 classification: `needs reference evidence`; current-client traffic and exact static/no-op response are unconfirmed. |
| `GET` | `/web/osu-getseasonal.php` | seasonal | Grouped row: Seasonal UI. Task 2.5 classification: `needs reference evidence`; evidence: guide Task 2.5 seasonal UI evidence note, user-confirmed current client traffic, and missing exact empty-array/cache fixture. |
| `GET` | `/web/osu-login.php` | login | Grouped row: Login preflight. Task 2.5 classification: `needs reference evidence`; evidence: guide Task 2.5 login preflight evidence note. |
| `GET` | `/web/osu-title-image.php` | menu | Grouped row: Title/menu UI. Task 2.5 classification: `needs reference evidence`; image bytes, empty body, and redirect variants need fixtures alongside menu JSON. |
| `GET` | `/web/coins.php` | optional/private-server | Grouped row: Private-server currency and benchmark. Task 2.5 classification: `out of scope`; evidence: guide Task 2.5 private-server decision and evidence note. |
| `POST` | `/web/osu-benchmark.php` | diagnostics | Grouped row: Private-server currency and benchmark. Task 2.5 classification: `out of scope`; evidence: guide Task 2.5 private-server decision and evidence note. |
| `GET` | `/web/osu-osz2-bmsubmit-getid.php` | beatmap submission | Grouped row: Beatmap submission. Task 2.5 classification: `deferred`; evidence: guide Task 2.5 beatmap submission decision and evidence note. |
| `POST` | `/web/osu-osz2-bmsubmit-upload.php` | beatmap submission | Grouped row: Beatmap submission. Task 2.5 classification: `deferred`; upload workflow remains post-core compatibility work. |
| `POST` | `/web/osu-osz2-bmsubmit-post.php` | beatmap submission | Grouped row: Beatmap submission. Task 2.5 classification: `deferred`; post workflow remains post-core compatibility work. |
| `GET` | `/web/osu-get-beatmap-topic.php` | beatmap submission | Grouped row: Beatmap submission. Task 2.5 classification: `deferred`; topic lookup remains post-core compatibility work. |
| `POST` | `/web/osu-bmsubmit-getid5.php` | legacy beatmap submission | Grouped row: Beatmap submission. Task 2.5 classification: `deferred`; legacy alias variant remains post-core compatibility work. |
| `POST` | `/web/osu-bmsubmit-getid4.php` | legacy beatmap submission | Grouped row: Beatmap submission. Task 2.5 classification: `deferred`; legacy alias variant remains post-core compatibility work. |
| `POST` | `/web/osu-bmsubmit-getid3.php` | legacy beatmap submission | Grouped row: Beatmap submission. Task 2.5 classification: `deferred`; legacy alias variant remains post-core compatibility work. |
| `POST` | `/web/osu-bmsubmit-getid2.php` | legacy beatmap submission | Grouped row: Beatmap submission. Task 2.5 classification: `deferred`; legacy alias variant remains post-core compatibility work. |
| `POST` | `/web/osu-bmsubmit-getid.php` | legacy beatmap submission | Grouped row: Beatmap submission. Task 2.5 classification: `deferred`; legacy alias variant remains post-core compatibility work. |
| `POST` | `/web/osu-bmsubmit-upload.php` | legacy beatmap submission | Grouped row: Beatmap submission. Task 2.5 classification: `deferred`; legacy upload variant remains post-core compatibility work. |
| `GET` | `/web/osu-bmsubmit-novideo.php` | legacy beatmap submission | Grouped row: Beatmap submission. Task 2.5 classification: `deferred`; no-video submission variant remains post-core compatibility work. |
| `POST` | `/web/osu-bmsubmit-post3.php` | legacy beatmap submission | Grouped row: Beatmap submission. Task 2.5 classification: `deferred`; legacy post variant remains post-core compatibility work. |
| `POST` | `/web/osu-bmsubmit-post2.php` | legacy beatmap submission | Grouped row: Beatmap submission. Task 2.5 classification: `deferred`; legacy post variant remains post-core compatibility work. |
| `POST` | `/web/osu-bmsubmit-post.php` | legacy beatmap submission | Grouped row: Beatmap submission. Task 2.5 classification: `deferred`; legacy post variant remains post-core compatibility work. |

### Static, Release, Rating, And Host Routes

| Method | Endpoint | Area | Audit traceability |
| --- | --- | --- | --- |
| `GET` | `/a/` | avatars | Adjacent static/media context. Not classified by the legacy web-family body audit; see Adjacent context table and guide file/media behavior table. |
| `GET` | `/a/{filename}` | avatars | Adjacent static/media context. Avatar delivery belongs to static/media scope, not the `/web/*.php` final classification. |
| `GET` | `/forum/download.php` | avatars | Adjacent static/media context. Kept separate from legacy web-family classification. |
| `GET` | `/mt/{filename}` | beatmap thumbnails | Adjacent beatmap media delivery context. Not classified by Issue #32 body audit. |
| `GET` | `/thumb/{filename}` | beatmap thumbnails | Adjacent beatmap media delivery context. Not classified by Issue #32 body audit. |
| `GET` | `/images/map-thumb/{filename}` | beatmap thumbnails | Adjacent beatmap media delivery context. Not classified by Issue #32 body audit. |
| `GET` | `/preview/{filename}` | preview audio | Adjacent beatmap media delivery context. Not classified by Issue #32 body audit. |
| `GET` | `/mp3/preview/{filename}` | preview audio | Adjacent beatmap media delivery context. Not classified by Issue #32 body audit. |
| `GET` | `/d/{filename}` | beatmap downloads | Adjacent beatmap file delivery context. Not classified by the legacy PHP body audit. |
| `GET` | `/bss/{filename}` | beatmap downloads | Adjacent beatmap file delivery context. Not classified by the legacy PHP body audit. |
| `GET` | `/osu/{query}` | beatmap files | Adjacent beatmap file delivery context. Not classified by the legacy PHP body audit. |
| `GET` | `/ss/` | screenshots | Adjacent screenshot media delivery context. Kept separate from `/web/osu-screenshot.php` and `/web/osu-ss.php` upload classifications. |
| `GET` | `/ss/{id}` | screenshots | Adjacent screenshot media delivery context. Kept separate from upload response classification. |
| `GET` | `/ss/{id}/{checksum}` | screenshots | Adjacent screenshot media delivery context. Kept separate from upload response classification. |
| `GET` | `/assets/menu-content.json` | menu | Grouped row: Title/menu UI. Task 2.5 classification: `needs reference evidence`; JSON body, cache behavior, and current-client usage need fixtures. |
| `GET` | `/menu-content.json` | menu host rewrite | Grouped row: Title/menu UI. Task 2.5 classification: `needs reference evidence`; host rewrite and disabled/missing-content behavior need fixtures. |
| `GET` | `/release/update` | update | Adjacent release/update context. Not classified by legacy web-family final audit. |
| `GET` | `/release/patches.php` | update | Adjacent release/update context. Not classified by legacy web-family final audit. |
| `GET` | `/release/update.php` | update | Adjacent release/update context. Not classified by legacy web-family final audit. |
| `GET` | `/release/update2.php` | update | Adjacent release/update context. Not classified by legacy web-family final audit. |
| `GET` | `/update` | root update alias | Adjacent release/update context. Not classified by legacy web-family final audit. |
| `GET` | `/update.php` | root update alias | Adjacent release/update context. Not classified by legacy web-family final audit. |
| `GET` | `/update2.php` | root update alias | Adjacent release/update context. Not classified by legacy web-family final audit. |
| `GET` | `/patches.php` | root update alias | Adjacent release/update context. Not classified by legacy web-family final audit. |
| `GET` | `/release/{filename}` | release files | Adjacent release/update context. Not classified by legacy web-family final audit. |
| `GET` | `/release/filter.txt` | release files | Adjacent release/update context. Not classified by legacy web-family final audit. |
| `GET` | `/release/Localisation/{filename}` | release files | Adjacent release/update context. Not classified by legacy web-family final audit. |
| `GET` | `/release/{language}/{filename}` | release files | Adjacent release/update context. Not classified by legacy web-family final audit. |
| `GET` | `/rating/ingame-rate.php` | ratings | Grouped row: Ratings. Task 2.5 classification: `needs reference evidence`; evidence: guide Task 2.5 ratings evidence note. |
| `GET` | `/rating/ingame-rate2.php` | ratings | Grouped row: Ratings. Task 2.5 classification: `needs reference evidence`; response sentinel variant must be checked per alias. |
| `GET` | `a.$DOMAIN/*` | avatar host rewrite to `/a{uri}` | Adjacent static/media host rewrite. Not classified by legacy web-family final audit. |
| `GET` | `a.$DOMAIN/avatar/*` | external avatar host variant | Adjacent static/media host rewrite. Not classified by legacy web-family final audit. |
| `GET` | `a.$DOMAIN/ss/*.jpg` | external screenshot host variant | Adjacent screenshot media host rewrite. Not classified by legacy web-family final audit. |
| `GET` | `b.$DOMAIN/d/*` | beatmap download host | Adjacent beatmap download host route. Not classified by legacy web-family final audit. |
| `GET` | `b.$DOMAIN/mt/*` | beatmap thumbnail host | Adjacent beatmap media host route. Not classified by legacy web-family final audit. |
| `GET` | `b.$DOMAIN/thumb/*` | beatmap thumbnail host | Adjacent beatmap media host route. Not classified by legacy web-family final audit. |
| `GET` | `b.$DOMAIN/images/map-thumb/*` | beatmap thumbnail host | Adjacent beatmap media host route. Not classified by legacy web-family final audit. |
| `GET` | `b.$DOMAIN/preview/*` | preview audio host | Adjacent beatmap media host route. Not classified by legacy web-family final audit. |
| `GET` | `b.$DOMAIN/mp3/preview/*` | preview audio host | Adjacent beatmap media host route. Not classified by legacy web-family final audit. |
| `GET` | `d.$DOMAIN/d/*` | beatmap download host | Adjacent beatmap download host route. Not classified by legacy web-family final audit. |
| `GET` | `d.osu.$DOMAIN/d/*` | beatmap download host | Adjacent beatmap download host route. Not classified by legacy web-family final audit. |
| `GET` | `s.$DOMAIN/images/map-thumb/*` | static host | Adjacent static/media host route. Not classified by legacy web-family final audit. |
| `GET` | `s.$DOMAIN/images/*` | static image host | Adjacent static/media host route. Not classified by legacy web-family final audit. |
| `GET` | `s.$DOMAIN/a/*` | static avatar host | Adjacent static/media host route. Not classified by legacy web-family final audit. |
| `GET` | `s.$DOMAIN/thumb/*` | static thumbnail host | Adjacent static/media host route. Not classified by legacy web-family final audit. |
| `GET` | `s.$DOMAIN/mt/*` | static thumbnail host | Adjacent static/media host route. Not classified by legacy web-family final audit. |
| `GET` | `s.$DOMAIN/preview/*` | static preview host | Adjacent static/media host route. Not classified by legacy web-family final audit. |
| `GET` | `s.$DOMAIN/mp3/preview/*` | static preview host | Adjacent static/media host route. Not classified by legacy web-family final audit. |

### Lets Route Aliases

| Method | Endpoint | Area | Audit traceability |
| --- | --- | --- | --- |
| `GET` | `/d/{filename}` | beatmap downloads | Adjacent beatmap download alias. Not classified by legacy web-family final audit. |
| `GET` | `/s/{filename}` | beatmap downloads | Adjacent beatmap download alias. Not classified by legacy web-family final audit. |
| `GET` | `/web/replays/{id}` | replay download | Adjacent non-PHP replay alias. Kept beside `/web/osu-getreplay.php`; not classified as a legacy PHP exact path. |
| `GET` | `/ss/{filename}` | screenshots | Adjacent screenshot media alias. Kept separate from `/web/osu-screenshot.php` upload classification. |
| `GET` | `/p/changelog` | public web redirect/content | Adjacent public web route. Outside legacy web-family final classification. |
| `GET` | `/p/verify` | verification redirect | Adjacent public web route. Outside legacy web-family final classification. |
| `GET` | `/u/{user}` | profile redirect | Adjacent public web route. Outside legacy web-family final classification. |

### Coverage Rows Without Reference Exact Routes

These Stable HTTP Endpoint Coverage rows are still part of the traceability
surface, but this Reference Route Inventory has no matching exact reference
route row from the sources above.

| Method | Endpoint | Grouped row | Audit traceability |
| --- | --- | --- | --- |
| `POST` | `/web/osu-session.php` | Session candidate | Task 2.2 classification: `needs reference evidence`; evidence: guide `/web/osu-session.php` evidence note and `bancho.py` unhandled-route trace. Missing reference exact row and missing current-client traffic remain explicit gaps. |
| `GET` | `/web/lastfm.php` | Social/status no-op candidates | Task 2.5 classification: `needs reference evidence`; evidence: guide Task 2.5 social/status no-op evidence note. Missing reference exact row, request shape, response body, and current-client traffic remain explicit gaps. |

## Persistence Inventory Coverage

Reference database schemas and repository queries are useful for discovering
which durable facts production servers needed to answer stable clients. They are
not schema templates for Athena. Implement Athena tables through its domain,
repository, and Unit of Work boundaries, then verify that the observable stable
responses can be produced.

Primary schema references:

- `osuAkatsuki/bancho.py`: `migrations/base.sql`,
  `migrations/migrations.sql`, and `app/repositories/*.py`.
- `osuTitanic/titanic`: `migrations/*.up.sql`.
- `osuRipple/lets` and `osuRipple/pep.py`: query usage in legacy web and Bancho
  handlers, especially score, beatmap, relationship, client, and report flows.

GitHub discovery note: direct GitHub code search was attempted for additional
avatar/static/thumbnail implementations, but the authenticated API hit rate
limits during this audit. Public repository pages for `osuAkatsuki/bancho.py`
and `osuTitanic/deck` were reachable, and detailed route behavior was audited
from the local clones listed above.

| Area | Domain owner | Durable data to audit | Primary consumers | Current gap | Status |
| --- | --- | --- | --- | --- | --- |
| Identity and login | `identity/users.py`, `identity/authentication.py`, `identity/passwords.py` | user id, username/safe name, password hash, email, country, activation, latest activity, preferred mode, play style, supporter/donor state | Bancho login, registration, profile/user lookup | **Covered**: user id, username, safe_username, email, password_hash, country, created_at, updated_at, disallowed_usernames. **Missing**: activation state (ref: bancho.py `users.priv` PENDING_VERIFICATION bit, titanic `users.activated` boolean, Ripple `users.privileges` bit), latest activity (ref: all 3 have `users.latest_activity` unix/timestamp; durable, throttled write), preferred mode (ref: bancho.py/titanic `users.preferred_mode` int), play style (ref: bancho.py `users.play_style` bitfield, titanic `users.playstyle` int), supporter/donor end (ref: bancho.py `users.donor_end`, titanic `users.supporter_end`, Ripple `users.donor_expire`; all unix/timestamp), bot account flag (ref: titanic `users.bot` boolean), avatar hash (ref: titanic `users.avatar_hash`/`avatar_last_changed`). Gaps feed #18 (presence/stats) and new child work (activation/supporter model). | Partial |
| Permissions and moderation | `identity/roles.py`, `identity/authorization.py` | role/group membership, Bancho permissions, silence end, restricted/banned state, infringement/report/audit logs | login replies, channel access, chat, restrictions, admin actions | **Covered**: roles (name, permissions IntFlag, position), user_roles (user_id, role_id). **Missing**: silence end (ref: all 3 have `users.silence_end` unix/timestamp), restricted/banned state (ref: bancho.py `users.priv` bitfield, titanic `users.restricted` boolean, Ripple `users.privileges` + `users.ban_datetime`), infringement logs (ref: titanic `infringements` table with action/length/is_permanent/description), report logs (ref: titanic `reports` table, Ripple `reports` table), audit logs (ref: bancho.py `logs` table, titanic `logs` table). Gaps feed #26 (moderation) and new child work (infringement/audit model). | Partial |
| Client integrity | `integrity: client hash validation` | client hashes, executable/path hashes, adapters, unique id, disk signature, verified hardware exceptions, login history | login validation, multi-account policy, score submit validation (depends on: `identity/authentication.py`) | No durable integrity model. All facts missing. Reference evidence: bancho.py `client_hashes` table (composite PK: userid/osupath/adapters/uninstall_id/disk_serial, with occurrences counter and latest_time), titanic `clients` table (composite PK: user_id/executable/adapters/unique_id/disk_signature, with banned flag) + `clients_verified` (type/hash whitelist), Ripple `hw_user` (userid/mac/unique_id/disk_id with occurencies counter). Login history: bancho.py `ingame_logins`, titanic `logins`, Ripple `ip_user`. Feeds #29 (client integrity epic). | Missing |
| Social graph | `identity/friends.py` | friends, blocks, friend-only DMs, direct messages/read state | friend packets, private messages, DM privacy | **Covered**: user_friend_relationships (owner_user_id, target_user_id, created_at, no-self constraint). **Missing**: blocks (ref: bancho.py `relationships.type='block'`, titanic `relationships.status=1`; Ripple not found), friend-only DM setting (ref: titanic `users.friendonly_dms` boolean), DM read status (ref: bancho.py `mail.read` boolean; not found in titanic/Ripple). Gaps feed #17 (fixture extraction) and new child work (blocks/read-state model). | Partial |
| Chat and channels | `chat/channels.py`, `chat/policies.py` | channel definitions, read/write permissions, autojoin channels, persisted messages, chat filters | login channel list, channel join/leave, public/private chat | **Covered**: channels (name, topic, type, auto_join, rate_limit), channel_role_overrides (can_read, can_write), channel_messages (sender, channel, content), private_messages (sender, target, content). **Missing**: chat filters (ref: titanic `filters` table with pattern/replacement/block/timeout_duration; not found in bancho.py/Ripple). Gaps feed new child work (chat filter model). | Partial |
| Beatmaps and beatmapsets | `beatmaps/models.py`, `beatmaps/eligibility.py` | beatmap id, set id, md5, filename, status, metadata, mode, difficulty stats, play/pass counts, mirrors/resources, favourites, ratings, comments | getscores, beatmap info packet, osu!direct, downloads, comments (depends on: `scores/leaderboards.py` for getscores) | **Covered**: beatmapsets (id, artist, title, creator, unicode, official_status/source/verified, fetch/refresh), beatmaps (id, set_id, md5, mode, version, length, combo, bpm, cs/od/ar/hp, stars, status, local_override), beatmap_file_attachments (blob link, md5, source, original_filename), beatmap_fetch_states (target tracking). Filename note: beatmap table has no filename column (ref: all 3 have it), but `BeatmapFileAttachmentModel.original_filename` covers getscores filename fallback; design choice, not a stable response gap. **Missing**: play/pass counts (ref: bancho.py `maps.plays/passes`, titanic `beatmaps.playcount/passcount`, Ripple `beatmaps.playcount/passcount`), favourites (ref: bancho.py `favourites`, titanic `favourites`, Ripple not found), ratings (ref: bancho.py `ratings`, titanic `ratings`, Ripple `beatmaps_rating`), comments (moved to social aggregate per reference audit), osu!direct search fields, `.osz` download metadata (ref: titanic `beatmapsets.osz_filesize/osz_filesize_novideo`). Gaps feed #23 (beatmap info/direct). | Partial |
| Scores and leaderboard | `scores/score.py`, `scores/submission.py`, `scores/leaderboards.py`, `scores/personal_best.py`, `scores/performance.py`, `scores/replay.py` | score id, user id, beatmap id/md5, score checksum, client version/hash, mode, mods, hit counts, grade, combo, pp, accuracy, status, submitted time, replay md5, fail time, time elapsed, client flags, leaderboard family for vanilla/Relax/Autopilot where enabled | score submit, getscores, rankings, user stats, replay download, Akatsuki-compatible RX/AP boards (depends on: `beatmaps/models.py` for beatmap lookup, `identity/friends.py` for friends leaderboard) | **Covered**: scores (full row: user_id, beatmap_id, checksum, ruleset, playstyle, mods, hit counts, score, combo, accuracy, grade, passed, perfect, client_version, submitted_at, leaderboard_eligible), score_submissions (fingerprint dedup, state, result_snapshot), replay_file_attachments (score_id, blob_id, sha256, byte_size), score_performance_calculations (pp, star_rating, provenance tracking, recalculation batches), personal_bests (scope: user/beatmap/ruleset/playstyle/category), beatmap_leaderboard_user_bests (read model rebuilt from scores). **Missing**: fail_time_ms (parsed in multipart_parser and passed through command pipeline but NOT persisted to ScoreModel; ref: titanic `scores.failtime`), time elapsed (parsed as part of score data but not persisted; ref: bancho.py `scores.time_elapsed` ms, Ripple `scores.playtime` seconds), client_hash (parsed in multipart_parser but NOT persisted; only `client_version` string is saved; ref: bancho.py `scores.client_flags` stores anticheat flags separately), replay md5 (stable getscores row uses `has_replay` 1/0 flag not md5 value; Athena replay uses sha256 which suffices for stable response; ref: titanic `scores.replay_md5` is internal verification, not wire-visible), replay view counts per score (ref: titanic `scores.replay_views`; bancho.py tracks per-user in `stats.replay_views`), complete RX/AP family verification. Gaps feed #19 (score submit) and #20 (getscores). | Partial |
| User stats | `scores: stats projection` (read model rebuilt from scores) | total/ranked score, pp, accuracy, play count, playtime, max combo, total hits, grade counts, replay views | user stats packets, presence panels (depends on: `scores/performance.py` for pp) | No stats projection table. All facts missing. Reference evidence: bancho.py `stats` table (composite PK id/mode, mode 0-8 for vn/rx/ap; tscore, rscore, pp, acc, plays, playtime, max_combo, total_hits, replay_views, xh/x/sh/s/a grade counts), titanic `stats` table (same structure + b/c/d counts, peak_rank), Ripple `users_stats` (per-mode suffix columns + separate `users_stats_relax`). Feeds #18 (presence/UserStats) and new child work (user-stats spec in roadmap). | Missing |
| User rankings | `rankings: rank projection and history` | global rank, country rank, rank history | profile/ranking views (depends on: user stats projection) | No ranking projection table. All facts missing. Reference evidence: bancho.py and Ripple derive ranks from Redis ZSETs at runtime (not persisted in DB). Only titanic persists rank history in `profile_rank_history` (user_id, time, mode, global_rank, country_rank, score_rank). Split from former "User stats and rankings" row because primary owner differs. | Missing |
| Replays and media metadata | `scores/replay.py` (replay), `storage/blobs.py` (blob metadata) | replay object key/checksum, replay view counts, screenshot metadata, avatar metadata, beatmap asset metadata, seasonal asset metadata, update file metadata | replay download, screenshot upload/download, avatar/static endpoints, updater | **Covered**: replay_file_attachments (score_id, blob_id, sha256, byte_size), blobs (sha256, byte_size, content_type, storage_backend, storage_key). **Missing**: replay view counts (ref: bancho.py tracks per-user in `stats.replay_views`, titanic tracks per-score in `scores.replay_views`; different granularity), screenshot metadata (ref: titanic `screenshots` table id/user_id/created_at/hidden; bancho.py/Ripple file-based with no DB metadata), avatar metadata (ref: titanic `users.avatar_hash`/`avatar_last_changed`; others file-based). Gaps feed #21, #22, #23. | Partial |
| Static/media delivery | `storage: asset delivery routing` | screenshot id, screenshot owner, created-at checksum, hidden/expiry flags, avatar hash, avatar update time, beatmap background key, preview audio key, `.osu` object key, `.osz` object key, full/no-video sizes, content length, last-modified time, mirror URL, download-server routing | `/ss/*`, `/a/*`, `/mt/*`, `/thumb/*`, `/preview/*`, `/osu/*`, `/d/*`, `/bss/*`, `/s/*` | No delivery routing model. All facts missing. Reference evidence: no reference stores delivery routing in DB; all use filesystem/CDN. Titanic has `resource_mirrors` (url, type, server, priority) and `beatmapsets.download_server` for mirror routing. Feeds #21 and #23. | Missing |
| Release/update files | `release: update policy and artifact delivery` | release version, file hash, patch URL, full file URL, release timestamp, extra file md5, extra download key, Localisation language/file key | `/web/check-updates.php`, `/release/update*`, `/release/<file>`, root `/update*` and `/patches.php` aliases | No durable release/update model. Initial no-update/no-op policy documented in #34 audit. Reference evidence: only titanic has `releases` table (name PK, version, description, known_bugs, supported, recommended, preview, downloads, hashes jsonb, actions jsonb); bancho.py and Ripple have no release tables. All durable facts missing. Feeds #25. | Missing |
| Ratings/comments/favourites | `social: ratings, comments, favourites` | beatmap ratings by user, comments by target type/id (replay/map/song), favourite set relationships, read markers | `/web/osu-rate.php`, `/rating/ingame-rate.php`, `/rating/ingame-rate2.php`, `/web/osu-comment.php`, `/web/osu-addfavourite.php`, `/web/osu-getfavourites.php`, `/web/osu-markasread.php` | No durable ratings/comments/favourites model. All facts missing. Reference audit: comment `target_type` supports replay/map/song in all 3 references (bancho.py enum, titanic varchar, Ripple nullable FK columns); NOT beatmap-only. Owner assigned to independent `social` aggregate, not `beatmaps`. Feeds new child work (social content model). | Missing |
| Achievements and notifications | `achievements: unlock and badge model` | achievement definitions/unlocks, notifications, user badges/profile badges | score submit unlock flow, profile display, notification packets | No durable achievement/notification model. Reference evidence: bancho.py `achievements` (83 seeded, cond as Python lambda) + `user_achievements` (userid, achid), titanic `achievements` (user_id, name, category, filename, unlocked_at), Ripple `users_achievements` (user_id, achievement_id, time). Badges: bancho.py 2 columns on users, titanic `profile_badges` table, Ripple `badges`+`user_badges` tables. Notifications: only titanic has `notifications` (id, user_id, type, header, content, link, read). All facts missing. Feeds new child work. | Missing |
| Multiplayer and tournaments | `multiplayer: match and tournament audit` | match records, match events, pool definitions, pool maps, host/slot/team settings as durable audit where needed | multiplayer packet family, tournament packet family | No durable multiplayer model. Reference evidence: bancho.py does NOT persist match state (entirely in-memory); only `tourney_pools`/`tourney_pool_maps` are durable. Titanic persists `mp_matches` (id, bancho_id, name, creator_id, created_at, ended_at) and `mp_events` (match_id, time, type, data jsonb). Ripple has no match tables. All facts missing. Feeds #27. | Missing |

Row split note: "User stats and rankings" was split into "User stats" and "User
rankings" because primary owners differ. Stats is a read model projected from
scores domain. Rankings is an independent projection with its own rebuild
lifecycle and rank history storage. Both are listed in the roadmap as separate
specs (`user-stats` and `user-ranking`).

Use `Replays and media metadata` for ownership of stored object facts and audit
metadata. Use `Static/media delivery` for HTTP routing, cache behavior, mirrors,
and response headers over those objects.

### Behavior Cross-Reference

Which durable data areas does each stable behavior depend on?

| Behavior | Dependent areas | Cross-domain dependencies |
| --- | --- | --- |
| Login | Identity and login, Permissions and moderation, Client integrity, Chat and channels (autojoin) | Client integrity depends on `identity/authentication.py` for login validation context |
| Score submit | Scores and leaderboard, Beatmaps and beatmapsets, Client integrity, Replays and media metadata | Scores depends on `beatmaps/models.py` for beatmap lookup and eligibility |
| Getscores | Scores and leaderboard, Beatmaps and beatmapsets, User stats, Social graph | Leaderboard projection depends on `identity/friends.py` for friends category; scores read model rebuilt from scores domain |
| Replay download | Replays and media metadata, Scores and leaderboard | Replay attachment references score_id and blob_id |
| Static/media | Static/media delivery, Replays and media metadata, Beatmaps and beatmapsets | Delivery routing references blob metadata from `storage/blobs.py` |
| Moderation | Permissions and moderation, Identity and login, Chat and channels | Moderation audit depends on identity for actor/target; chat for channel-level restrictions |
| Multiplayer | Multiplayer and tournaments, Identity and login, Beatmaps and beatmapsets | Match state references user identity and beatmap metadata |

## GitHub Project Shape

Use a GitHub Project as the execution board for this matrix. Recommended fields:

| Field | Values |
| --- | --- |
| `Area` | `bancho-packet`, `bancho-struct`, `web-legacy`, `static-media`, `release-update`, `presence`, `chat`, `scores`, `beatmaps`, `multiplayer`, `spectator`, `moderation`, `client-integrity`, `ops` |
| `Stable surface` | Packet name or endpoint path. |
| `Reference status` | `needs-doc-audit`, `needs-traffic-capture`, `reference-confirmed` |
| `Reference implementation` | `bancho.py`, `lets`, `pep.py`, `deck`, `titanic`, `Lekuruu wiki`, or `observed-client`. |
| `Implementation status` | Same status labels as this document. |
| `Verification` | `none`, `unit`, `integration`, `fixture`, `real-client-probe` |
| `Priority` | `P0 core login/play`, `P1 normal gameplay`, `P2 social/multiplayer`, `P3 ops/polish` |

Recommended initial Project epics:

- Stable protocol inventory audit against documentation, real client traffic,
  `osuRipple/pep.py`, `osuTitanic/titanic`, and the bancho side of
  `osuAkatsuki/bancho.py`.
- Legacy `/web/*.php` endpoint inventory audit against traffic,
  `osuRipple/lets`, `osuTitanic/deck`, and the legacy web side of
  `osuAkatsuki/bancho.py`.
- Persistence inventory audit against `bancho.py` schemas, `titanic`
  migrations, and query usage in `lets` and `pep.py`.
- Request/response fixture extraction for each implemented endpoint.
- Bancho struct golden fixture extraction from Lekuruu `Types/*.md`.
- Match payload builder and golden fixtures for multiplayer packet implementation.
- Presence and user stats completion.
- Beatmap info, osu!direct, replay, and file-serving compatibility.
- Score, leaderboard, personal best, user stats, and rank projection completion.
- Multiplayer packet family.
- Spectator packet family.
- Moderation, restrictions, silence, and audit workflows.
- Real-client probe suite and golden fixture expansion.

Recommended dependency order:

1. Complete protocol, legacy web, and persistence inventory audits.
2. Extract struct and request/response golden fixtures from confirmed references.
3. Finish core presence, user stats, score, leaderboard, beatmap info, and file
   serving projections.
4. Implement multiplayer and spectator packet families after `Match`,
   `ScoreFrame`, and `ReplayFrameBundle` fixtures exist.
5. Add moderation, restrictions, release/update policy, and optional RX/AP
   compatibility once core stable gameplay behavior is fixture-backed.
6. Promote the real-client probe suite into CI after it can run deterministically
   against local services and seeded fixture data.

## Completion Rule

Do not call stable compatibility complete until all of these are true:

1. Every C2S enum row is either implemented, explicitly out of scope, or backed by
   a documented reason for deferral.
2. Every S2C enum row has a builder or an explicit reason it is not emitted.
3. Every Lekuruu `Types/*.md` struct is implemented, explicitly out of scope, or
   backed by a documented reason for deferral.
4. Every observed stable `/web/*.php`, static/media, and update/release request
   has a row in this document.
5. Every implemented stable surface has automated verification. Packet and
   wire-format surfaces require at least unit plus golden fixture coverage;
   HTTP endpoints require route integration plus response fixture coverage.
6. A real stable client probe has covered login, idle polling, chat, score submit,
   getscores, beatmap download/search scope, and reconnect behavior.

Promotion from `Partial` to `Implemented` requires explicit exit criteria in the
tracking issue. For example, getscores requires full header and row projection,
personal best handling, ranking status mapping, and fixture coverage; score
submit requires durable replay metadata, leaderboard reconciliation, stats/rank
projection, and real-client probe coverage for the response body.
