# Brief: replay-download-response

## Problem

Stable client users need `/web/osu-getreplay.php` to return replay download responses that the client can actually consume. Issue #36 must only return success after the saved Replay blob is proven to be the correct response body, or after Athena has an explicit body assembly path.

## Current State

`replay-download-contract` fixed the route, request keys, auth fields, response evidence, alias boundary, and privacy constraints for Issue #35. The original blocker for #36 was `target_body_validation_requires_local_raw_blob_artifact`: Athena had to decide whether saved Replay blob bytes could be returned directly or whether the replay download body had to be assembled. A local metadata-only diagnostic for score 6 selected `download_body_strategy=direct_blob_bytes` without committing raw replay bytes, complete `.osr` bytes, credential values, or complete captured query values.

Confirmed inputs from the existing contract:

- Primary route: `GET /web/osu-getreplay.php`.
- Request keys: `c`, `h`, `m`, `u`.
- Success response: HTTP 200 with `lzma_compressed_replay_payload`, but raw body bytes are local-only.
- Auth failure: implementation-ready 401 with `empty_body`.
- Hidden score and storage-missing replay: implementation-ready 404 with `empty_http_exception`.
- Missing replay: unresolved reference conflict, so #36 may only use a documented provisional fallback.
- `/web/replays/<id>` is `candidate_only_reference_backed` and not required.

## Desired Outcome

Issue #36 has a runtime implementation of `/web/osu-getreplay.php` that:

- Resolves the body strategy before returning success responses.
- Uses `direct_blob_bytes` only when local validation proves the stored Replay blob is target-client-compatible.
- Uses `assemble_download_body` when blob integrity passes but the download response body differs from the stored blob shape.
- Returns implementation-ready failure branches without leaking storage or authorization internals.
- Treats missing replay as a provisional 404 empty fallback, not as target-confirmed evidence.
- Keeps replay view count and latest activity out of the response implementation.

## Approach

Use **Body Strategy First**.

The first implementation slice resolves `target_body_validation_requires_local_raw_blob_artifact` by running a local-only raw replay diagnostic against an actual stored Replay blob and target-body parser/client check. The selected plan returns stored blob bytes directly through thin transport parsing, query/use-case boundaries, blob read access, and focused tests.

This approach is preferred because it removes the highest-risk compatibility blocker before endpoint code can accidentally ship a response that downloads but cannot be replayed by the Stable client.

## Scope

- **In**: Primary `/web/osu-getreplay.php` route registration and handler.
- **In**: Query parsing for confirmed keys `c`, `h`, `m`, `u`.
- **In**: Legacy web authentication for replay download using the existing stable credential boundary.
- **In**: Score/replay/blob lookup through query/use-case and repository/storage boundaries.
- **In**: Success response body strategy selection: `direct_blob_bytes` or `assemble_download_body`.
- **In**: Auth failure 401 empty body.
- **In**: Hidden score 404 empty HTTP exception.
- **In**: Storage-missing replay 404 empty HTTP exception.
- **In**: Missing replay provisional 404 empty fallback.
- **In**: Focused tests for parser, auth/failure branches, body strategy, and transport boundary.
- **Out**: `/web/replays/<id>` alias implementation.
- **Out**: Replay view count, latest activity, self-view, and duplicate-view cooldown.
- **Out**: Score submission replay persistence changes unless body strategy diagnosis proves stored data is corrupt.
- **Out**: Raw capture, raw replay bytes, complete `.osr` bytes, password, password hash, or credential values in repository files.
- **Out**: Anti-cheat, replay validation policy, spectator replay frame parsing.
- **Out**: Resolving malformed `c` / `m` and unknown field target behavior beyond explicit fallback/blocking policy.

## Boundary Candidates

- Transport boundary: `transports/stable/web_legacy` adapts HTTP query/auth and returns legacy-compatible responses.
- Query/use-case boundary: replay download lookup resolves score visibility, replay attachment, blob metadata, and body strategy without exposing transport wire types.
- Storage boundary: blob bytes are read through storage abstractions, not SQLAlchemy sessions or backend implementation details.
- Compatibility boundary: Stable-only response status/body/header choices stay in stable compatibility logic or stable web legacy mappers.
- Evidence boundary: local-only target body validation can inform committed metadata and implementation choice, but raw replay artifacts remain outside the repository.

## Out of Boundary

- `/web/replays/<id>` remains a candidate alias until target traffic requires it.
- #37 owns replay view count and latest activity.
- Existing score submission replay storage is an input, not a target, unless integrity check proves stored bytes are wrong.
- Missing replay remains `provisional`, because reference evidence conflicts and target capture is impractical.
- Malformed request behavior remains unconfirmed unless separate evidence appears.

## Upstream / Downstream

- **Upstream**: `replay-download-contract` spec, Issue #35 evidence, Issue #36 body, stable compatibility guide/matrix, blob storage, score submission replay persistence, legacy web authentication, score/replay read models.
- **Downstream**: Issue #37 replay view count/latest activity, Stable client replay playback workflow, future `/web/replays/<id>` alias decision, stable verification coverage for replay download.

## Existing Spec Touchpoints

- **Extends**: `replay-download-contract` by consuming its confirmed contract and resolving the remaining body strategy blocker.
- **Adjacent**: `score-ingestion` owns replay upload and persistence; `blob-storage` owns blob storage primitives; `score-submission` owns submit response behavior; `stable-compatibility-verification` owns reusable compatibility verification vocabulary.

## Constraints

- Follow Athena layered architecture: transport adapters stay thin; runtime adapters must not import SQLAlchemy models, DB sessions, raw SQL, or storage backend implementation.
- Domain models remain standard dataclasses and must not import transport, SQLAlchemy, Valkey, taskiq, Starlette, or FastAPI.
- External Stable compatibility behavior must be evidence-backed. Unconfirmed branches must be documented as provisional or blocked, not target-confirmed.
- Raw replay bytes and credentials must not be committed. Local raw artifacts may be used only for diagnosis.
- Python docstrings for new or changed public Python classes/functions/methods must be Japanese with ASCII punctuation.
- Before implementation is considered complete, run focused tests plus the relevant quality checks.
