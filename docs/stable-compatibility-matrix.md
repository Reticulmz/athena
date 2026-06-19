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

| Status | Meaning |
| --- | --- |
| `Implemented` | The surface has a runtime implementation and at least basic verification. |
| `Partial` | The surface exists but key stable behavior is known to be missing. |
| `Builder` | S2C packet builder exists, but runtime emission may still be incomplete. |
| `Declared` | Packet ID exists in the enum, but payload parsing/building or runtime behavior is missing. |
| `Missing` | No meaningful implementation exists yet. |
| `Candidate` | Likely stable surface that needs confirmation from docs, traffic, or reference code. |
| `Out of scope` | Known surface intentionally excluded from the current stable scope. |

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
| 97 | `PRESENCE_REQUEST` | Missing | Targeted presence response missing. Audit: classification=required; evidence=guide lists this row in Status And Presence targeted presence responses, but dispatcher only marks this quiet and no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Status And Presence, `src/osu_server/transports/stable/bancho/dispatch.py`, `src/osu_server/transports/stable/bancho/protocol/enums.py`; verification=none; payload=confirmed:IntList player ids, 256 max; fixture blocker=none. |
| 98 | `PRESENCE_REQUEST_ALL` | Missing | Full presence response missing. Audit: classification=required; evidence=guide lists this row in Status And Presence full presence response, but no `@handles` registration exists; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Status And Presence, `src/osu_server/transports/stable/bancho/protocol/enums.py`, `src/osu_server/transports/stable/bancho/handlers/`; verification=none; payload=confirmed:empty; fixture blocker=none. |
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
| 96 | `USER_PRESENCE_BUNDLE` | Builder | Presence bundle builder exists. Audit: classification=required; builder=implemented:user_presence_bundle; runtime=emitted:login-roster-bundle; evidence=login roster builds the online id bundle and login response emits it; source=`docs/stable-compatibility-guide.md` Bancho Packet Payload Reference and Status And Presence, `src/osu_server/transports/stable/bancho/protocol/s2c/login.py`, `src/osu_server/transports/stable/bancho/workflows/presence_roster.py`, `tests/integration/test_chat_e2e.py`; verification=integration; fixture blocker=none. |
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
| `Status` | Missing | `STATUS_CHANGE`, `USER_STATS` | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types and Bancho Struct Field Reference; dependencies=C2S `STATUS_CHANGE`, nested S2C `USER_STATS`; confirmed=guide lists stable enum values 0..13; missing=canonical enum type and golden value coverage; fixture priority=p1; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `Status` values; fixture blocker=#17: stable status enum golden values are needed before canonical enum and stats/status fixtures. |
| `Mode` | Missing | `STATUS_CHANGE`, `USER_STATS`, `USER_PRESENCE`, score modes | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types and Bancho Struct Field Reference; dependencies=C2S `STATUS_CHANGE`, nested S2C `USER_STATS`, S2C `USER_PRESENCE`, nonpacket score mode mapping; confirmed=guide lists stable play mode values 0..3; missing=canonical enum type and converted-mode policy evidence; fixture priority=p1; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `Mode` values; fixture blocker=#17: play mode enum bytes and converted-mode policy fixtures are needed before presence/stats fixture completion. |
| `Mods` | Missing | `STATUS_CHANGE`, score submit, `MATCH`, leaderboard family policy | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types and Bancho Struct Field Reference; dependencies=C2S `STATUS_CHANGE`, `MATCH_CHANGE_MODS`, nested C2S/S2C `MATCH`, nonpacket score submit and leaderboard compatibility; confirmed=guide lists stable bitmask values including ScoreV2 and key mods; missing=canonical bitmask type, conversion tests, and Relax2/Autopilot naming policy evidence; fixture priority=p1; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `Mods` bitmask; fixture blocker=#17: stable mod bitmask and Relax2/Autopilot evidence fixtures are needed before match and score-family compatibility work. |
| `Grade` | Missing | score submit, getscores, `BEATMAP_INFO_REPLY` | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types and Bancho Struct Field Reference; dependencies=nested `BeatmapInfo`, S2C `BEATMAP_INFO_REPLY`, nonpacket score submit and getscores display; confirmed=guide lists stable grade values 0..9; missing=canonical enum type and score/beatmap mapping evidence; fixture priority=p1; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `Grade` values; fixture blocker=#17: grade enum and beatmap-info grade bytes are needed before score and beatmap-info fixtures. |
| `ButtonState` | Missing | `SEND_FRAMES`, `SPECTATE_FRAMES` | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types and Bancho Struct Field Reference; dependencies=nested `ReplayFrame`, C2S `SEND_FRAMES`, S2C `SPECTATE_FRAMES`; confirmed=guide lists replay input bitmask values; missing=canonical bitmask type and replay fixture evidence; fixture priority=p0; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `ButtonState` bitmask; fixture blocker=#17: replay input bitmask bytes directly block `ReplayFrame` and `ReplayFrameBundle` golden fixtures. |
| `PresenceFilter` | Missing | `RECEIVE_UPDATES` | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types, Bancho Struct Field Reference, Bancho Packet Payload Reference, and Status And Presence; dependencies=C2S `RECEIVE_UPDATES`; confirmed=guide lists receive-update filter values 0..2; missing=canonical enum type and filter behavior fixture/traffic evidence; fixture priority=p1; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `PresenceFilter` values and Bancho Packet Payload Reference `RECEIVE_UPDATES`; fixture blocker=#17: receive-updates filter bytes and traffic evidence are needed before presence filter behavior can be finalized. |
| `QuitState` | Missing | `USER_QUIT` | Audit: classification=needs reference evidence; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types, Bancho Struct Field Reference, and Bancho Packet Payload Reference, `docs/stable-compatibility-matrix.md` S2C `USER_QUIT` row; dependencies=S2C `USER_QUIT`; confirmed=guide lists modern quit state values 0..2; missing=canonical enum type plus reference evidence for old 4-byte user id form vs modern user id plus `QuitState`; fixture priority=p1; exact source gap=reference implementation or traffic evidence must choose old 4-byte `USER_QUIT` form vs modern `UserId` plus `QuitState`; next-audit=needs-reference-implementation-audit; fixture blocker=#17: `USER_QUIT` fixture extraction must wait for the selected stable-client quit payload source. |
| `ReplayAction` | Missing | `SEND_FRAMES`, `SPECTATE_FRAMES` | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types and Bancho Struct Field Reference; dependencies=nested `ReplayFrameBundle`, C2S `SEND_FRAMES`, S2C `SPECTATE_FRAMES`; confirmed=guide lists replay action values 0..8; missing=canonical enum type and spectator fixture evidence; fixture priority=p0; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `ReplayAction` values; fixture blocker=#17: replay action bytes directly block `ReplayFrameBundle` golden fixtures. |
| `ReplayFrame` | Missing | `SEND_FRAMES`, `SPECTATE_FRAMES` | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types and Bancho Struct Field Reference; dependencies=nested `ReplayFrameBundle`, C2S `SEND_FRAMES`, S2C `SPECTATE_FRAMES`; confirmed=guide lists ButtonState, legacy byte, mouse_x, mouse_y, and time layout; missing=transport wire type and replay frame golden bytes; fixture priority=p0; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `ReplayFrame` layout; fixture blocker=#17: replay frame encode/decode bytes directly block C2S `SEND_FRAMES` and S2C `SPECTATE_FRAMES` fixtures. |
| `ScoreFrame` | Missing | C2S 47 `MATCH_SCORE_UPDATE`, S2C 48 `MATCH_SCORE_UPDATE`, `SPECTATE_FRAMES` | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types, Bancho Struct Field Reference, Bancho Packet Payload Reference, and Fixture Extraction Backlog, `docs/stable-compatibility-matrix.md` C2S 47 and S2C 48 rows; dependencies=C2S `MATCH_SCORE_UPDATE`, S2C `MATCH_SCORE_UPDATE`, optional nested `ReplayFrameBundle` in C2S `SEND_FRAMES` and S2C `SPECTATE_FRAMES`; confirmed=guide documents 28-byte client and 45-byte server shape difference; missing=transport wire type, optional ScoreV2 tail handling evidence, and client/server golden bytes; fixture priority=p0; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `ScoreFrame` layout and Fixture Extraction Backlog; fixture blocker=#17: client/server score frame golden bytes are a first extraction input before match score and spectator frame implementation. |
| `ReplayFrameBundle` | Missing | C2S `SEND_FRAMES`, S2C `SPECTATE_FRAMES` | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types, Bancho Struct Field Reference, Bancho Packet Payload Reference, and Fixture Extraction Backlog, `docs/stable-compatibility-matrix.md` C2S `SEND_FRAMES` and S2C `SPECTATE_FRAMES` rows; dependencies=C2S `SEND_FRAMES`, S2C `SPECTATE_FRAMES`, nested `ReplayFrame`, `ReplayAction`, optional `ScoreFrame`; confirmed=guide lists extra/frame_count/frames/action/optional-score/sequence layout; missing=transport wire type and spectator frame bundle golden bytes; fixture priority=p0; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `ReplayFrameBundle` layout and Fixture Extraction Backlog; fixture blocker=#17: spectator frame bundle bytes are a first extraction input before C2S `SEND_FRAMES` and S2C `SPECTATE_FRAMES` work. |
| `BeatmapInfo` | Missing | S2C `BEATMAP_INFO_REPLY`, `/web/osu-getbeatmapinfo.php` | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types, Bancho Struct Field Reference, Bancho Packet Payload Reference, Beatmap Info Packet Flow, and Fixture Extraction Backlog; dependencies=nested S2C `BEATMAP_INFO_REPLY`, nonpacket `/web/osu-getbeatmapinfo.php`; confirmed=guide lists request_index/ids/thread/ranked/grades/md5 layout; missing=transport wire type and beatmap info response fixture evidence; fixture priority=p1; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `BeatmapInfo` layout and Beatmap Info Packet Flow; fixture blocker=#17: beatmap info row bytes are needed before S2C `BEATMAP_INFO_REPLY` and web beatmap-info response implementation. |
| `BeatmapInfoRequest` | Missing | C2S `BEATMAP_INFO` | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types, Bancho Struct Field Reference, Bancho Packet Payload Reference, Beatmap Info Packet Flow, and Fixture Extraction Backlog, `docs/stable-compatibility-matrix.md` C2S `BEATMAP_INFO` row; dependencies=C2S `BEATMAP_INFO`, nested `String` and id list primitives; confirmed=guide lists filename count, filenames, id count, and beatmap id list layout; missing=transport wire type and golden request bytes; fixture priority=p1; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `BeatmapInfoRequest` layout and Bancho Packet Payload Reference `BEATMAP_INFO`; fixture blocker=#17: beatmap info request bytes are needed before C2S `BEATMAP_INFO` parser work. |
| `BeatmapInfoReply` | Missing | S2C `BEATMAP_INFO_REPLY` | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types, Bancho Struct Field Reference, Bancho Packet Payload Reference, Beatmap Info Packet Flow, and Fixture Extraction Backlog, `docs/stable-compatibility-matrix.md` S2C `BEATMAP_INFO_REPLY` row; dependencies=S2C `BEATMAP_INFO_REPLY`, nested `BeatmapInfo`; confirmed=guide lists count plus `BeatmapInfo[count]` layout; missing=transport wire type and golden response bytes; fixture priority=p1; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `BeatmapInfoReply` layout and Bancho Packet Payload Reference `BEATMAP_INFO_REPLY`; fixture blocker=#17: beatmap info reply bytes are needed before S2C `BEATMAP_INFO_REPLY` builder work. |
| `UserPresence` | Partial | `USER_PRESENCE`, login presence roster | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types, Bancho Struct Field Reference, Bancho Packet Payload Reference, and Status And Presence, `src/osu_server/transports/stable/bancho/protocol/s2c/login.py`, `tests/unit/transports/bancho/protocol/test_s2c_login.py`, `tests/integration/test_login_flow.py`; dependencies=S2C `USER_PRESENCE`, login presence roster; confirmed=builder-local layout packs `permissions \| (mode << 5)`; missing=canonical public transport type, golden bytes, and targeted presence behavior evidence; fixture priority=p1; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `UserPresence` layout, Status And Presence, and `tests/unit/transports/bancho/protocol/test_s2c_login.py`; fixture blocker=#17: UserPresence golden encode bytes are needed before canonical presence type and targeted presence behavior work. |
| `UserPresenceBundle` | Partial | `USER_PRESENCE_BUNDLE`, login online user list | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types, Bancho Struct Field Reference, Bancho Packet Payload Reference, and Status And Presence, `src/osu_server/transports/stable/bancho/protocol/s2c/login.py`, `tests/unit/transports/bancho/protocol/test_s2c_login.py`, `tests/integration/test_chat_e2e.py`; dependencies=S2C `USER_PRESENCE_BUNDLE`, login online user list, nested `IntList`; confirmed=builder emits IntList-compatible online user id bundle; missing=canonical struct name/type and golden bytes; fixture priority=p1; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `UserPresenceBundle` layout and `tests/unit/transports/bancho/protocol/test_s2c_login.py`; fixture blocker=#17: online user bundle golden bytes are needed before canonical bundle naming and presence bundle fixtures. |
| `UserStats` | Partial | `USER_STATS`, login stats, requested stats | Audit: classification=required; source=`docs/stable-compatibility-guide.md` Bancho Primitive Types, Bancho Struct Field Reference, Bancho Packet Payload Reference, and Status And Presence, `src/osu_server/transports/stable/bancho/protocol/s2c/login.py`, `src/osu_server/transports/stable/bancho/workflows/presence_roster.py`, `tests/unit/transports/bancho/protocol/test_s2c_login.py`; dependencies=S2C `USER_STATS`, C2S `STATS_REQUEST`, login stats fanout, nested `StatusUpdate`; confirmed=builder-local flat layout exists; missing=canonical public transport type, stat projection behavior, requested-stats runtime, and golden bytes; fixture priority=p1; exact source=`docs/stable-compatibility-guide.md` Bancho Struct Field Reference `UserStats` layout, Status And Presence, and `tests/unit/transports/bancho/protocol/test_s2c_login.py`; fixture blocker=#17: user stats golden bytes are needed before canonical stats type and requested-stats runtime work. |
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
| S2C 11 `USER_STATS` | S2C packet | required | Builder | `docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, Bancho Struct Field Reference, and Status And Presence; `tests/unit/transports/bancho/protocol/test_s2c_login.py` | `UserStats` golden encode bytes and stat-projection fixtures are needed before expanding stat fanout beyond login placeholders. |
| S2C 15 `SPECTATE_FRAMES` | S2C packet | required | Missing | `docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, Bancho Struct Field Reference, Spectator, and Fixture Extraction Backlog | `ReplayFrameBundle` golden encode/decode bytes are needed before spectator frame builder work. |
| S2C 26 `MATCH_UPDATE` | S2C packet | required | Missing | `docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, Bancho Struct Field Reference, Multiplayer, and Fixture Extraction Backlog | `Match` golden encode/decode bytes are needed before multiplayer match-update builder work. |
| S2C 27 `NEW_MATCH` | S2C packet | required | Missing | `docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, Bancho Struct Field Reference, Multiplayer, and Fixture Extraction Backlog | `Match` golden encode/decode bytes are needed before multiplayer new-match builder work. |
| S2C 36 `MATCH_JOIN_SUCCESS` | S2C packet | required | Missing | `docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, Bancho Struct Field Reference, Multiplayer, and Fixture Extraction Backlog | `Match` golden encode/decode bytes are needed before multiplayer join-success builder work. |
| S2C 46 `MATCH_START` | S2C packet | required | Missing | `docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, Bancho Struct Field Reference, Multiplayer, and Fixture Extraction Backlog; `tests/unit/transports/bancho/protocol/test_enums.py` | `Match` golden bytes and S2C 46 enum-correction fixture bytes are needed before multiplayer match-start builder work. |
| S2C 48 `MATCH_SCORE_UPDATE` | S2C packet | required | Missing | `docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, Bancho Struct Field Reference, Multiplayer, and Fixture Extraction Backlog | 45-byte server `ScoreFrame` golden bytes are needed before multiplayer score-update builder work. |
| S2C 69 `BEATMAP_INFO_REPLY` | S2C packet | required | Missing | `docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, Bancho Struct Field Reference, and Fixture Extraction Backlog | `BeatmapInfoReply` golden response bytes are needed before beatmap-info reply builder work. |
| S2C 83 `USER_PRESENCE` | S2C packet | required | Builder | `docs/stable-compatibility-guide.md` Bancho Packet Payload Reference, Bancho Struct Field Reference, and Status And Presence; `tests/integration/test_login_flow.py` | `UserPresence` golden encode bytes and presence request/filter fixtures are needed before completing presence fanout. |
| `Status` | Bancho struct | required | Missing | `docs/stable-compatibility-guide.md` Bancho Struct Field Reference `Status` values | Stable status enum golden values are needed before canonical enum and stats/status fixtures. |
| `Mode` | Bancho struct | required | Missing | `docs/stable-compatibility-guide.md` Bancho Struct Field Reference `Mode` values | Play mode enum bytes and converted-mode policy fixtures are needed before presence/stats fixture completion. |
| `Mods` | Bancho struct | required | Missing | `docs/stable-compatibility-guide.md` Bancho Struct Field Reference `Mods` bitmask | Stable mod bitmask and Relax2/Autopilot evidence fixtures are needed before match and score-family compatibility work. |
| `Grade` | Bancho struct | required | Missing | `docs/stable-compatibility-guide.md` Bancho Struct Field Reference `Grade` values | Grade enum and beatmap-info grade bytes are needed before score and beatmap-info fixtures. |
| `ButtonState` | Bancho struct | required | Missing | `docs/stable-compatibility-guide.md` Bancho Struct Field Reference `ButtonState` bitmask | Replay input bitmask bytes directly block `ReplayFrame` and `ReplayFrameBundle` golden fixtures. |
| `PresenceFilter` | Bancho struct | required | Missing | `docs/stable-compatibility-guide.md` Bancho Struct Field Reference `PresenceFilter` values and Bancho Packet Payload Reference `RECEIVE_UPDATES` | Receive-updates filter bytes and traffic evidence are needed before presence filter behavior can be finalized. |
| `ReplayAction` | Bancho struct | required | Missing | `docs/stable-compatibility-guide.md` Bancho Struct Field Reference `ReplayAction` values | Replay action bytes directly block `ReplayFrameBundle` golden fixtures. |
| `ReplayFrame` | Bancho struct | required | Missing | `docs/stable-compatibility-guide.md` Bancho Struct Field Reference `ReplayFrame` layout | Replay frame encode/decode bytes directly block C2S `SEND_FRAMES` and S2C `SPECTATE_FRAMES` fixtures. |
| `ScoreFrame` | Bancho struct | required | Missing | `docs/stable-compatibility-guide.md` Bancho Struct Field Reference `ScoreFrame` layout and Fixture Extraction Backlog | Client/server score frame golden bytes are a first extraction input before match score and spectator frame implementation. |
| `ReplayFrameBundle` | Bancho struct | required | Missing | `docs/stable-compatibility-guide.md` Bancho Struct Field Reference `ReplayFrameBundle` layout and Fixture Extraction Backlog | Spectator frame bundle bytes are a first extraction input before C2S `SEND_FRAMES` and S2C `SPECTATE_FRAMES` work. |
| `BeatmapInfo` | Bancho struct | required | Missing | `docs/stable-compatibility-guide.md` Bancho Struct Field Reference `BeatmapInfo` layout and Beatmap Info Packet Flow | Beatmap info row bytes are needed before S2C `BEATMAP_INFO_REPLY` and web beatmap-info response implementation. |
| `BeatmapInfoRequest` | Bancho struct | required | Missing | `docs/stable-compatibility-guide.md` Bancho Struct Field Reference `BeatmapInfoRequest` layout and Bancho Packet Payload Reference `BEATMAP_INFO` | Beatmap info request bytes are needed before C2S `BEATMAP_INFO` parser work. |
| `BeatmapInfoReply` | Bancho struct | required | Missing | `docs/stable-compatibility-guide.md` Bancho Struct Field Reference `BeatmapInfoReply` layout and Bancho Packet Payload Reference `BEATMAP_INFO_REPLY` | Beatmap info reply bytes are needed before S2C `BEATMAP_INFO_REPLY` builder work. |
| `UserPresence` | Bancho struct | required | Partial | `docs/stable-compatibility-guide.md` Bancho Struct Field Reference `UserPresence` layout, Status And Presence, and `tests/unit/transports/bancho/protocol/test_s2c_login.py` | `UserPresence` golden encode bytes are needed before canonical presence type and targeted presence behavior work. |
| `UserPresenceBundle` | Bancho struct | required | Partial | `docs/stable-compatibility-guide.md` Bancho Struct Field Reference `UserPresenceBundle` layout and `tests/unit/transports/bancho/protocol/test_s2c_login.py` | Online user bundle golden bytes are needed before canonical bundle naming and presence bundle fixtures. |
| `UserStats` | Bancho struct | required | Partial | `docs/stable-compatibility-guide.md` Bancho Struct Field Reference `UserStats` layout, Status And Presence, and `tests/unit/transports/bancho/protocol/test_s2c_login.py` | User stats golden bytes are needed before canonical stats type and requested-stats runtime work. |
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

| Method | Endpoint | Status | Notes |
| --- | --- | --- | --- |
| `POST` | `/` on `c.$DOMAIN`, `c<int>.$DOMAIN`, `ce.$DOMAIN` | Implemented | Bancho login and packet polling entrypoint. |
| `POST` | `/` on `cho.$DOMAIN`, `mahbahowc.$DOMAIN`, `server.$DOMAIN` | Candidate | Bancho host aliases observed in `osuTitanic/titanic`; not currently routed by Athena. |
| `POST` | `/users` on `osu.$DOMAIN` | Implemented | Stable registration endpoint. |
| `POST` | `/web/users` local fallback | Implemented | Development fallback route for registration. |
| `GET` | `/web/bancho_connect.php` | Partial | Reachability handshake only; credential validation is delegated to login. |
| `GET` | `/web/osu-osz2-getscores.php` | Partial | Stable response mapping exists; full score rows depend on leaderboard projections. |
| `POST` | `/web/osu-submit-modular-selector.php` | Partial | Score submission exists; rank/stat projection fields are incomplete. |
| `POST` | `/web/osu-submit-modular.php` | Candidate | Legacy score submit variant in `lets` and `deck`; decide whether target clients need it. |
| `POST` | `/web/osu-submit.php`, `/web/osu-submit-new.php` | Candidate | Older score submit variants in `deck`; likely legacy-only but should be explicitly scoped. |
| `POST` | `/web/osu-session.php` | Candidate | Listed as unhandled in `bancho.py`; verify whether target clients still call it. |
| `GET` | `/web/osu-getscores.php` through `/web/osu-getscores6.php` | Candidate | Older getscores variants in `deck`; decide target client build coverage. |
| `GET` | `/web/osu-getreplay.php` | Missing | Replay download flow missing. |
| `GET` | `/web/replays/<id>` | Candidate | Full replay route in `lets`; verify client usage. |
| `GET` | `/web/check-updates.php` | Missing | Stable update compatibility route in `lets`, `deck`, and `bancho.py`; initial Athena policy is no-update/no-op. Audit: stable_compatibility_route_classification=required-no-update; response_shape=[]; evidence_source=deck [] + bancho.py empty body + user-confirmed current osu!stable --devserver behavior (TargetUsr, issue #34 spec discussion, 2026-06-20 JST); stable_operational_dependency=none; stable_fixture_requirement=check_updates_no_update_json_array. Proxying to `osu.ppy.sh` remains a separate future ppy proxying decision requirement (`proxy-decision-required`), not the initial implementation default. |
| `GET` | `/release/update`, `/update` | Missing | Stable release manifest route and root alias; initial Athena policy is no-update/no-op. Audit: stable_compatibility_route_classification=required-no-update; response_shape=empty body; evidence_source=stable-compatibility-guide `/release/update` empty string + research decision; stable_operational_dependency=none; stable_fixture_requirement=release_no_update_empty. The hosted update metadata or artifact distribution behavior is outside initial no-update policy. |
| `GET` | `/release/update.php`, `/update.php` | Missing | Stable release file-check manifest route and root alias; initial Athena policy is no-update/no-op. Audit: stable_compatibility_route_classification=required-no-update; response_shape=0; evidence_source=stable-compatibility-guide `/release/update.php` `0` + research decision; stable_operational_dependency=none; stable_fixture_requirement=release_update_php_zero. The hosted update metadata or artifact distribution behavior is outside initial no-update policy. |
| `GET` | `/release/update2.php`, `/update2.php` | Missing | Stable release secondary manifest route and root alias; initial Athena policy is no-update/no-op. Audit: stable_compatibility_route_classification=required-no-update; response_shape=empty body; evidence_source=stable-compatibility-guide `/release/update2.php` empty string + research decision; stable_operational_dependency=none; stable_fixture_requirement=release_no_update_empty. The hosted update metadata or artifact distribution behavior is outside initial no-update policy. |
| `GET` | `/release/patches.php`, `/patches.php` | Missing | Stable release patch manifest route and root alias; initial Athena policy is no-update/no-op. Audit: stable_compatibility_route_classification=required-no-update; response_shape=empty body; evidence_source=stable-compatibility-guide `/release/patches.php` empty string + research decision; stable_operational_dependency=none; stable_fixture_requirement=release_no_update_empty. The hosted update metadata or artifact distribution behavior is outside initial no-update policy. |
| `GET` | `/release/<filename>` | Candidate | Release file route in `deck`; stable-compatibility-guide records release, patch, or extra file bytes with content headers. Audit: stable_compatibility_route_classification=deferred; response_shape=deferred; evidence_source=stable-compatibility-guide `/release/<filename>` file bytes + research decision; stable_operational_dependency=hosted-artifact-decision-required; stable_fixture_requirement=deferred. File bytes serving is not `required-no-update` and is not an initial implementation default. |
| `GET` | `/release/filter.txt` | Candidate | Filter route in `deck`; stable-compatibility-guide records proxying `https://m1.ppy.sh/release/filter.txt`. Audit: stable_compatibility_route_classification=deferred; response_shape=deferred; evidence_source=stable-compatibility-guide `/release/filter.txt` proxy + research decision; stable_operational_dependency=proxy-decision-required; stable_fixture_requirement=deferred. External proxy route behavior is not `required-no-update` and is not an initial implementation default. |
| `GET` | `/release/Localisation/<filename>` | Candidate | Localisation route in `deck`; stable-compatibility-guide records proxying `https://m1.ppy.sh/release/Localisation/<filename>?<version>`. Audit: stable_compatibility_route_classification=deferred; response_shape=deferred; evidence_source=stable-compatibility-guide `/release/Localisation/<filename>` proxy + research decision; stable_operational_dependency=proxy-decision-required; stable_fixture_requirement=deferred. External proxy route behavior is not `required-no-update` and is not an initial implementation default. |
| `GET` | `/release/<language>/<filename>` | Candidate | Localisation DLL route in `deck`; stable-compatibility-guide records stored Localisation DLL bytes. Audit: stable_compatibility_route_classification=deferred; response_shape=deferred; evidence_source=stable-compatibility-guide `/release/<language>/<filename>` stored DLL bytes + research decision; stable_operational_dependency=hosted-artifact-decision-required; stable_fixture_requirement=deferred. File bytes serving is not `required-no-update` and is not an initial implementation default. |
| `GET` | `/web/osu-search.php`, `/web/osu-search-set.php` | Missing | osu!direct search and set details missing. |
| `GET` | `/d/<set>`, `/s/<set>`, `/bss/<set>`, `/osu/<map>`, `/web/maps/<file>`, `b.$DOMAIN/<path>`, `s.$DOMAIN/<path>`, `d.$DOMAIN/d/<set>` | Candidate | Beatmap download and `.osu` file routes from references. |
| `GET` | `/mt/*`, `/thumb/*`, `/images/map-thumb/*`, `/preview/*`, `/mp3/preview/*` | Candidate | Beatmap thumbnails and preview media routes from `deck`. |
| `POST` | `/web/osu-getbeatmapinfo.php` | Missing | Legacy web beatmap info endpoint in `deck`; separate from Bancho packet 68/69. |
| `GET` | `/web/osu-gethashes.php`, `/web/osu-osz2-getfileinfo.php`, `/web/osu-osz2-getrawheader.php`, `/web/osu-osz2-getfilecontents.php`, `/web/osu-magnet.php` | Candidate | osz2/hash/file-content helper endpoints in `deck`. |
| `POST` | `/web/osu-screenshot.php`, `/web/osu-ss.php` | Missing | Screenshot upload flow missing. |
| `GET` | `/ss/`, `/ss/<id>`, `/ss/<id>/<checksum>`, `/ss/<id>.<extension>` | Candidate | Screenshot serving routes from `deck` and `bancho.py`. |
| `GET` | `/a/`, `/a/<filename>`, `/forum/download.php`, `/assets/menu-content.json`, `/menu-content.json` | Candidate | Avatar and menu/static routes from `deck` and `titanic`. |
| `POST` | `/web/osu-error.php` | Candidate | Client error report route in `lets` and `deck`. |
| `GET` | `/web/osu-rate.php`, `/rating/ingame-rate.php`, `/rating/ingame-rate2.php` | Candidate | Beatmap rating routes from references. |
| `POST` | `/web/osu-comment.php` | Candidate | Beatmap/replay/comment route from references. |
| `GET` | `/web/osu-addfavourite.php`, `/web/osu-getfavourites.php` | Candidate | Favourite mutation/list routes from references. |
| `GET` | `/web/osu-stat.php`, `/web/osu-statoth.php` | Candidate | User stats lookup routes from `deck`. |
| `GET` | `/web/osu-getstatus.php` | Candidate | Beatmap checksum/status route from `deck`; request and response shape are documented in the guide. |
| `GET` | `/web/osu-getfriends.php` | Missing | Friend relationships exist through packets, but web route is absent. |
| `GET` | `/web/osu-markasread.php`, `/web/osu-checktweets.php`, `/web/lastfm.php` | Candidate | Compatibility no-op or social/status routes in references. |
| `GET` | `/web/osu-getseasonal.php` | Missing | Seasonal asset JSON route missing. |
| `GET` | `/web/osu-login.php` | Candidate | Web login route in `deck`; verify stable client usage. |
| `GET` | `/web/osu-title-image.php`, `/menu-content.json` | Candidate | Title/menu asset routes from `deck`. |
| `GET` | `/web/coins.php` | Candidate | Client-side currency route in `deck`; likely optional/private-server-specific. |
| `POST` | `/web/osu-benchmark.php` | Candidate | Client benchmark diagnostics route in `deck`; likely optional/private-server-specific. |
| `POST` | `/difficulty-rating` | Candidate | Present in `bancho.py`; verify whether stable clients or tooling rely on it. |
| mixed | beatmap submission endpoints under `/web/osu-bmsubmit-*` and `/web/osu-osz2-bmsubmit-*` | Candidate | Beatmap submission/upload routes in `deck`; likely out of initial server scope but should be explicit. |

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

### Deck Web Routes

| Method | Endpoint | Area |
| --- | --- | --- |
| `GET` | `/web/bancho_connect.php` | connection |
| `GET` | `/web/check-updates.php` | update |
| `POST` | `/web/osu-error.php` | diagnostics |
| `POST` | `/web/osu-screenshot.php` | screenshots |
| `POST` | `/web/osu-ss.php` | screenshots/monitor |
| `GET` | `/web/osu-osz2-getscores.php` | leaderboards |
| `GET` | `/web/osu-getscores6.php` | legacy leaderboards |
| `GET` | `/web/osu-getscores5.php` | legacy leaderboards |
| `GET` | `/web/osu-getscores4.php` | legacy leaderboards |
| `GET` | `/web/osu-getscores3.php` | legacy leaderboards |
| `GET` | `/web/osu-getscores2.php` | legacy leaderboards |
| `GET` | `/web/osu-getscores.php` | legacy leaderboards |
| `POST` | `/web/osu-submit-modular-selector.php` | score submit |
| `POST` | `/web/osu-submit-modular.php` | score submit |
| `POST` | `/web/osu-submit.php` | legacy score submit |
| `POST` | `/web/osu-submit-new.php` | legacy score submit |
| `GET` | `/web/osu-getreplay.php` | replays |
| `GET` | `/web/osu-search.php` | osu!direct |
| `GET` | `/web/osu-search-set.php` | osu!direct |
| `POST` | `/web/osu-getbeatmapinfo.php` | beatmaps |
| `GET` | `/web/osu-getstatus.php` | beatmaps |
| `GET` | `/web/maps/{query}` | beatmap files |
| `GET` | `/web/osu-gethashes.php` | osz2 |
| `GET` | `/web/osu-osz2-getfileinfo.php` | osz2 |
| `GET` | `/web/osu-osz2-getrawheader.php` | osz2 |
| `GET` | `/web/osu-osz2-getfilecontents.php` | osz2 |
| `GET` | `/web/osu-magnet.php` | osz2 |
| `GET` | `/web/osu-getfriends.php` | social |
| `GET` | `/web/osu-addfavourite.php` | favourites |
| `GET` | `/web/osu-getfavourites.php` | favourites |
| `GET` | `/web/osu-rate.php` | ratings |
| `POST` | `/web/osu-comment.php` | comments |
| `GET` | `/web/osu-stat.php` | stats |
| `GET` | `/web/osu-statoth.php` | stats |
| `GET` | `/web/osu-markasread.php` | social |
| `GET` | `/web/osu-checktweets.php` | social |
| `GET` | `/web/osu-getseasonal.php` | seasonal |
| `GET` | `/web/osu-login.php` | login |
| `GET` | `/web/osu-title-image.php` | menu |
| `GET` | `/web/coins.php` | optional/private-server |
| `POST` | `/web/osu-benchmark.php` | diagnostics |
| `GET` | `/web/osu-osz2-bmsubmit-getid.php` | beatmap submission |
| `POST` | `/web/osu-osz2-bmsubmit-upload.php` | beatmap submission |
| `POST` | `/web/osu-osz2-bmsubmit-post.php` | beatmap submission |
| `GET` | `/web/osu-get-beatmap-topic.php` | beatmap submission |
| `POST` | `/web/osu-bmsubmit-getid5.php` | legacy beatmap submission |
| `POST` | `/web/osu-bmsubmit-getid4.php` | legacy beatmap submission |
| `POST` | `/web/osu-bmsubmit-getid3.php` | legacy beatmap submission |
| `POST` | `/web/osu-bmsubmit-getid2.php` | legacy beatmap submission |
| `POST` | `/web/osu-bmsubmit-getid.php` | legacy beatmap submission |
| `POST` | `/web/osu-bmsubmit-upload.php` | legacy beatmap submission |
| `GET` | `/web/osu-bmsubmit-novideo.php` | legacy beatmap submission |
| `POST` | `/web/osu-bmsubmit-post3.php` | legacy beatmap submission |
| `POST` | `/web/osu-bmsubmit-post2.php` | legacy beatmap submission |
| `POST` | `/web/osu-bmsubmit-post.php` | legacy beatmap submission |

### Static, Release, Rating, And Host Routes

| Method | Endpoint | Area |
| --- | --- | --- |
| `GET` | `/a/` | avatars |
| `GET` | `/a/{filename}` | avatars |
| `GET` | `/forum/download.php` | avatars |
| `GET` | `/mt/{filename}` | beatmap thumbnails |
| `GET` | `/thumb/{filename}` | beatmap thumbnails |
| `GET` | `/images/map-thumb/{filename}` | beatmap thumbnails |
| `GET` | `/preview/{filename}` | preview audio |
| `GET` | `/mp3/preview/{filename}` | preview audio |
| `GET` | `/d/{filename}` | beatmap downloads |
| `GET` | `/bss/{filename}` | beatmap downloads |
| `GET` | `/osu/{query}` | beatmap files |
| `GET` | `/ss/` | screenshots |
| `GET` | `/ss/{id}` | screenshots |
| `GET` | `/ss/{id}/{checksum}` | screenshots |
| `GET` | `/assets/menu-content.json` | menu |
| `GET` | `/menu-content.json` | menu host rewrite |
| `GET` | `/release/update` | update |
| `GET` | `/release/patches.php` | update |
| `GET` | `/release/update.php` | update |
| `GET` | `/release/update2.php` | update |
| `GET` | `/update` | root update alias |
| `GET` | `/update.php` | root update alias |
| `GET` | `/update2.php` | root update alias |
| `GET` | `/patches.php` | root update alias |
| `GET` | `/release/{filename}` | release files |
| `GET` | `/release/filter.txt` | release files |
| `GET` | `/release/Localisation/{filename}` | release files |
| `GET` | `/release/{language}/{filename}` | release files |
| `GET` | `/rating/ingame-rate.php` | ratings |
| `GET` | `/rating/ingame-rate2.php` | ratings |
| `GET` | `a.$DOMAIN/*` | avatar host rewrite to `/a{uri}` |
| `GET` | `a.$DOMAIN/avatar/*` | external avatar host variant |
| `GET` | `a.$DOMAIN/ss/*.jpg` | external screenshot host variant |
| `GET` | `b.$DOMAIN/d/*` | beatmap download host |
| `GET` | `b.$DOMAIN/mt/*` | beatmap thumbnail host |
| `GET` | `b.$DOMAIN/thumb/*` | beatmap thumbnail host |
| `GET` | `b.$DOMAIN/images/map-thumb/*` | beatmap thumbnail host |
| `GET` | `b.$DOMAIN/preview/*` | preview audio host |
| `GET` | `b.$DOMAIN/mp3/preview/*` | preview audio host |
| `GET` | `d.$DOMAIN/d/*` | beatmap download host |
| `GET` | `d.osu.$DOMAIN/d/*` | beatmap download host |
| `GET` | `s.$DOMAIN/images/map-thumb/*` | static host |
| `GET` | `s.$DOMAIN/images/*` | static image host |
| `GET` | `s.$DOMAIN/a/*` | static avatar host |
| `GET` | `s.$DOMAIN/thumb/*` | static thumbnail host |
| `GET` | `s.$DOMAIN/mt/*` | static thumbnail host |
| `GET` | `s.$DOMAIN/preview/*` | static preview host |
| `GET` | `s.$DOMAIN/mp3/preview/*` | static preview host |

### Lets Route Aliases

| Method | Endpoint | Area |
| --- | --- | --- |
| `GET` | `/d/{filename}` | beatmap downloads |
| `GET` | `/s/{filename}` | beatmap downloads |
| `GET` | `/web/replays/{id}` | replay download |
| `GET` | `/ss/{filename}` | screenshots |
| `GET` | `/p/changelog` | public web redirect/content |
| `GET` | `/p/verify` | verification redirect |
| `GET` | `/u/{user}` | profile redirect |

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
| Identity and login | `domain/identity` user/session aggregates | user id, username/safe name, password hash, email, country, activation, latest activity, preferred mode, play style, supporter/donor state | Bancho login, registration, profile/user lookup | Core user/login data exists; activation/supporter/profile projection coverage is incomplete. | Partial |
| Permissions and moderation | `domain/identity` authorization plus moderation aggregate | role/group membership, Bancho permissions, silence end, restricted/banned state, infringement/report/audit logs | login replies, channel access, chat, restrictions, admin actions | Role/permission language exists; moderation audit and infringement history are incomplete. | Partial |
| Client integrity | stable compatibility client-integrity aggregate | client hashes, executable/path hashes, adapters, unique id, disk signature, verified hardware exceptions, login history | login validation, multi-account policy, score submit validation | No durable integrity model yet. | Missing |
| Social graph | identity relationship aggregate | friends, blocks, friend-only DMs, direct messages/read state | friend packets, private messages, DM privacy | Friend and DM preference support exists; blocks and read-state persistence are incomplete. | Partial |
| Chat and channels | `domain/chat` channel/message aggregates | channel definitions, read/write permissions, autojoin channels, persisted messages, chat filters | login channel list, channel join/leave, public/private chat | Channel/chat flows exist; persisted history and moderation filters are incomplete. | Partial |
| Beatmaps and beatmapsets | `domain/beatmaps` beatmap/beatmapset aggregates | beatmap id, set id, md5, filename, status, metadata, mode, difficulty stats, play/pass counts, mirrors/resources, favourites, ratings, comments | getscores, beatmap info packet, osu!direct, downloads, comments | Metadata and mirror boundaries exist; osu!direct, ratings, comments, and full file serving are incomplete. | Partial |
| Scores and leaderboard | `domain/scores` score plus leaderboard read model | score id, user id, beatmap id/md5, score checksum, client version/hash, mode, mods, hit counts, grade, combo, pp, accuracy, status, submitted time, replay md5, fail time, leaderboard family for vanilla/Relax/Autopilot where enabled | score submit, getscores, rankings, user stats, replay download, Akatsuki-compatible RX/AP boards | Submission path exists; complete rows, ranking projections, and RX/AP family separation are incomplete. | Partial |
| User stats and rankings | scores/stat projection read model | total/ranked score, pp, accuracy, play count, playtime, max combo, total hits, grade counts, rank, country rank, rank history | user stats packets, presence panels, profile/ranking views | Placeholder stats exist; rank/country-rank/history projections are incomplete. | Partial |
| Replays and media metadata | `domain/scores` replay plus `domain/storage` blob metadata | replay object key/checksum, replay view counts, screenshot metadata, avatar metadata, beatmap asset metadata, seasonal asset metadata, update file metadata | replay download, screenshot upload/download, avatar/static endpoints, updater | Object metadata model and endpoint coverage are missing. | Missing |
| Static/media delivery | `domain/storage` asset delivery read model | screenshot id, screenshot owner, created-at checksum, hidden/expiry flags, avatar hash, avatar update time, beatmap background key, preview audio key, `.osu` object key, `.osz` object key, full/no-video sizes, content length, last-modified time, mirror URL, download-server routing | `/ss/*`, `/a/*`, `/mt/*`, `/thumb/*`, `/preview/*`, `/osu/*`, `/d/*`, `/bss/*`, `/s/*` | Delivery routing, cache headers, and object lookup projections are missing. | Missing |
| Release/update files | release/update asset aggregate | release version, file hash, patch URL, full file URL, release timestamp, extra file md5, extra download key, Localisation language/file key | `/web/check-updates.php`, `/release/update*`, `/release/<file>`, root `/update*` and `/patches.php` aliases | Initial no-update/no-op policy is documented; hosted/proxy update storage is missing. | Missing |
| Ratings/comments/favourites | beatmap social aggregate | beatmap ratings by user, comments by target type/id, favourite set relationships, read markers | `/web/osu-rate.php`, `/rating/ingame-rate.php`, `/rating/ingame-rate2.php`, `/web/osu-comment.php`, `/web/osu-addfavourite.php`, `/web/osu-getfavourites.php`, `/web/osu-markasread.php` | Durable ratings/comments/favourites/read markers are missing. | Missing |
| Achievements and notifications | achievement/notification aggregates | achievement definitions/unlocks, notifications, user badges/profile badges | score submit unlock flow, profile display, notification packets | Achievement and notification models are missing. | Missing |
| Multiplayer and tournaments | multiplayer match/tournament aggregates | match records, match events, pool definitions, pool maps, host/slot/team settings as durable audit where needed | multiplayer packet family, tournament packet family | Runtime and durable multiplayer models are missing. | Missing |

Use `Replays and media metadata` for ownership of stored object facts and audit
metadata. Use `Static/media delivery` for HTTP routing, cache behavior, mirrors,
and response headers over those objects.

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
