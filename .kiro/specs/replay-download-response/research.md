# Research & Design Decisions

## Summary

- **Feature**: `replay-download-response`
- **Discovery Scope**: Extension
- **Key Findings**:
  - 既存の `replay-download-contract` は primary route、query keys、auth fields、failure branches、success body blocker を固定し、この spec で runtime endpoint を実装する。
  - Stable web legacy は route delegate、Dishka-resolved handler、thin transport exchange の形で既存実装があり、`/web/osu-getreplay.php` も同じ境界で追加できる。
  - Replay download success body は local metadata-only diagnostic により保存済み Replay blob を LZMA-Alone replay payload として検証し、`download_body_strategy=direct_blob_bytes` を選択した。

## Research Log

### Replay download contract input

- **Context**: Issue #36 が推測なしで runtime endpoint を実装できるか確認するため。
- **Sources Consulted**:
  - `.kiro/specs/replay-download-contract/research.md`
  - `.kiro/specs/replay-download-contract/design.md`
  - `tests/fixtures/stable_compatibility/replay_download/target_client_request_metadata.json`
  - `tests/fixtures/stable_compatibility/replay_download/target_client_response_metadata.json`
  - `tests/fixtures/stable_compatibility/replay_download/response_contract.json`
  - `tests/fixtures/stable_compatibility/replay_download/body_assembly_decision.json`
  - `docs/stable-compatibility-guide.md`
  - `docs/stable-compatibility-matrix.md`
- **Findings**:
  - Target captures confirm `GET /web/osu-getreplay.php` with query keys `c`, `h`, `m`, and `u`.
  - Auth-like fields are `h` and `u`; raw values are not committed.
  - Official target success response is HTTP 200 with `content-type: zip`, `content-disposition` present, and body kind `lzma_compressed_replay_payload`.
  - Success was originally blocked by `target_body_validation_requires_local_raw_blob_artifact`.
  - Follow-up local diagnostic for score id 6 confirmed replay attachment metadata, blob byte size, checksum metadata, and LZMA-Alone decompression without committing raw replay bytes or credential values.
  - Auth failure is implementation-ready as 401 `empty_body`.
  - Hidden score and storage-missing replay are implementation-ready as 404 `empty_http_exception`.
  - Missing replay has conflicting reference evidence and is only acceptable as a provisional 404 empty fallback for this spec.
- **Implications**:
  - The runtime design must treat success body strategy as a gate, not as an implementation detail.
  - `/web/replays/<id>` stays out of scope because target captures did not observe it.
  - Malformed request behavior must be a documented fallback and must not be described as target-confirmed.

### Stable web legacy integration

- **Context**: The endpoint must fit existing Starlette and Dishka boundaries.
- **Sources Consulted**:
  - `src/osu_server/transports/stable/web_legacy/getscores.py`
  - `src/osu_server/transports/stable/web_legacy/score_submit.py`
  - `src/osu_server/composition/application.py`
  - `src/osu_server/composition/endpoints.py`
  - `src/osu_server/composition/lifespan.py`
  - `src/osu_server/composition/providers/stable_web_legacy.py`
  - `src/osu_server/services/queries/identity/session_credentials.py`
- **Findings**:
  - Stable web routes are registered in `composition/application.py`.
  - App routes delegate through `composition/endpoints.py` to handler instances stored on `app.state`.
  - Lifespan eagerly resolves stable handlers to fail startup before serving requests.
  - Stable web providers construct handler dependencies in `StableWebLegacyProviderSet`.
  - Getscores authenticates legacy web requests through `SessionCredentialsQueryUseCase` and maps wire keys to `SessionCredentialsQueryInput`.
- **Implications**:
  - Replay download should add a route, delegate, provider, and lifespan eager resolution entry.
  - The handler should map query `u` and `h` to the existing stable credential boundary.
  - Runtime transport must not import SQLAlchemy models, DB sessions, raw SQL, or storage backend implementation.

### Replay lookup and storage read boundary

- **Context**: The endpoint must resolve score visibility, replay attachment, blob metadata, and storage bytes without crossing persistence boundaries.
- **Sources Consulted**:
  - `src/osu_server/repositories/sqlalchemy/models/score.py`
  - `src/osu_server/domain/scores/replay.py`
  - `src/osu_server/repositories/sqlalchemy/queries/personal_bests.py`
  - `src/osu_server/repositories/sqlalchemy/queries/beatmap_leaderboards.py`
  - `src/osu_server/repositories/interfaces/queries/scores.py`
  - `src/osu_server/repositories/interfaces/queries/blobs.py`
  - `src/osu_server/services/commands/storage/blob_storage.py`
- **Findings**:
  - Replay attachments are stored in `replay_file_attachments` through `ReplayModel` with `score_id`, `blob_id`, `checksum_sha256`, and `byte_size`.
  - Existing leaderboard query repositories use `ReplayModel` only to expose `has_replay`; there is no replay-download-specific read port.
  - `BlobStorageService` already exposes read methods, but it currently lives under command-side storage.
  - Query-side score visibility patterns already use score eligibility and leaderboard-visible user data.
- **Implications**:
  - Add a replay-download-specific query repository port rather than extending transport with SQLAlchemy access.
  - Introduce a small query-side blob byte reader protocol so query code depends on read semantics, not on command storage module placement.
  - Keep hidden score classification in the query/use-case boundary and map it to a stable response in transport.

### Body strategy gate

- **Context**: The user observed that stored blob bytes renamed to `.osr` cannot be loaded by the game, while official capture body is not complete `.osr`.
- **Sources Consulted**:
  - `tests/fixtures/stable_compatibility/replay_download/body_assembly_decision.json`
  - `src/athena_cli/stable_verification/replay_download.py`
  - `tests/unit/athena_cli/stable_verification/test_replay_download.py`
- **Findings**:
  - Current committed decision is `download_body_strategy=direct_blob_bytes`.
  - Evidence references include `local_capture:athena_replay_download_score_6_404_after_route` and `local_diagnostic:score_6_replay_blob_lzma_alone_pass`.
  - If local validation proves stored bytes are target-client-compatible, the runtime can use `direct_blob_bytes`.
  - If blob integrity passes but target body compatibility fails, the runtime must use `assemble_download_body`.
  - If safe validation cannot be done, success must remain blocked rather than returning guessed bytes.
- **Implications**:
  - The implementation task list must resolve body strategy before enabling success 200.
  - A runtime guard should make a blocked strategy incapable of returning HTTP 200.
  - Raw replay bytes, complete `.osr` bytes, parser output, and safe body hashes remain local-only unless proven safe to commit.

### Steering and project constraints

- **Context**: Design must align with project-level architecture and available steering docs.
- **Sources Consulted**:
  - `.kiro/steering/tech.md`
  - `AGENTS.md`
- **Findings**:
  - The repository has `tech.md`, `scaling.md`, and `roadmap.md`; default `product.md` and `structure.md` were not present.
  - The tech stack is Python 3.14+, Starlette, Dishka, SQLAlchemy 2.0 async, standard dataclass domain models, basedpyright strict mode, ruff, pytest, and import-linter.
  - Stable web legacy belongs under `transports/stable/web_legacy`; stable-only compatibility semantics belong under `domain/compatibility/stable` or stable mappers.
- **Implications**:
  - No new dependency is needed for this spec.
  - Runtime adapters stay thin; query logic and persistence reads live behind query ports.
  - Missing steering files are not blockers because AGENTS.md and `tech.md` provide enough architecture constraints for this extension.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
| --- | --- | --- | --- | --- |
| Transport-only endpoint | Handler authenticates, queries DB, reads storage, and formats response directly | Small file count | Violates transport boundary and duplicates visibility/storage decisions | Rejected |
| Query use-case plus replay download repository | Handler authenticates and delegates score/replay/body resolution to query service and ports | Preserves layered architecture and testability | Requires new read port and provider wiring | Selected |
| Direct blob bytes by default | Return stored replay blob bytes for success | Simple | Explicitly blocked by contract evidence and may produce client-unusable downloads | Rejected |
| Body strategy first | Resolve `direct_blob_bytes` vs `assemble_download_body` before success 200 is enabled | Matches evidence and prevents guessed success | Requires local-only diagnostic before full runtime readiness | Selected |

## Design Decisions

### Decision: success body strategy is an implementation gate

- **Context**: Stored blob shape and target replay download response body shape are not proven equivalent.
- **Alternatives Considered**:
  1. Return stored blob bytes and rely on later reports.
  2. Keep the endpoint completely absent until all evidence is present.
  3. Implement failure branches and parsing, but gate success 200 on explicit body strategy.
- **Selected Approach**: The query/use-case can represent `blocked`, `direct_blob_bytes`, or `assemble_download_body`, and a blocked strategy must never produce HTTP 200.
- **Rationale**: This allows implementation of confirmed failures without shipping a guessed success body.
- **Trade-offs**: Issue #36 is not complete while strategy remains blocked.
- **Follow-up**: First implementation task must run local-only validation and update committed decision metadata without committing raw payloads.

### Decision: replay lookup is a query workflow

- **Context**: Replay download is read-only and should not own replay view updates or latest activity.
- **Alternatives Considered**:
  1. Model it as a command because it reads blob bytes.
  2. Model it as a query and leave #37 state updates to a separate command workflow.
- **Selected Approach**: `ReplayDownloadQueryUseCase` owns read-only lookup, visibility classification, body strategy enforcement, and body byte production.
- **Rationale**: The observable response can be implemented without mutation, and #37 owns replay view count/latest activity.
- **Trade-offs**: If #37 later needs atomic read-plus-update behavior, it must compose with this query response path without changing response bytes.
- **Follow-up**: Revalidate if #37 proves the update affects status, headers, or body.

### Decision: missing replay uses provisional 404 empty fallback

- **Context**: `bancho.py` and `deck` use 404 while `lets` primary route returns empty 200.
- **Alternatives Considered**:
  1. Treat 404 as target-confirmed.
  2. Treat empty 200 as target-confirmed.
  3. Use 404 empty fallback and label it provisional.
- **Selected Approach**: Return 404 empty fallback for no replay while explicitly preserving `provisional_missing_replay` labeling in logs, docs, and tests.
- **Rationale**: 404 aligns with two references and avoids ambiguous successful download workflow.
- **Trade-offs**: This branch remains revalidation-sensitive because target capture is impractical.
- **Follow-up**: Update the contract if future target traffic proves a different response.

### Decision: query-side blob reader protocol avoids command dependency leakage

- **Context**: Existing byte read methods live on `BlobStorageService` under command-side storage.
- **Alternatives Considered**:
  1. Import `BlobStorageService` directly into replay download query code.
  2. Read from storage backend directly in transport.
  3. Define a read-only `BlobByteReader` protocol and bind the current implementation in composition.
- **Selected Approach**: Query code depends on a read-only protocol. Composition may initially adapt existing storage service to that protocol.
- **Rationale**: The stable query workflow remains independent of command module placement and low-level backend details.
- **Trade-offs**: Adds a small interface and provider binding.
- **Follow-up**: If storage read ownership is split later, only the provider binding should change.

## Risks & Mitigations

- Direct blob strategy regression - Keep the body strategy fixture, integration success smoke test, and raw-artifact non-commit policy aligned so Athena does not return guessed bytes if future replay storage changes.
- Content-Disposition exact value is not fixture-fixed - Use only non-secret deterministic filename values and treat exact filename as implementation detail unless later evidence fixes it.
- Missing replay target behavior is hard to capture - Return provisional 404 empty fallback and keep revalidation trigger documented.
- Transport may accidentally leak credentials or storage internals - Parser, logs, and responses must never include raw query values, password hashes, blob storage keys, raw replay bytes, or local artifact paths.
- Query implementation may overreach into mutation ownership - Keep replay view count and latest activity out of this spec and require #37 to compose separately.

## References

- `.kiro/specs/replay-download-contract/research.md`
- `.kiro/specs/replay-download-contract/design.md`
- `.kiro/specs/replay-download-response/requirements.md`
- `tests/fixtures/stable_compatibility/replay_download/target_client_request_metadata.json`
- `tests/fixtures/stable_compatibility/replay_download/target_client_response_metadata.json`
- `tests/fixtures/stable_compatibility/replay_download/response_contract.json`
- `tests/fixtures/stable_compatibility/replay_download/body_assembly_decision.json`
- `docs/stable-compatibility-guide.md`
- `docs/stable-compatibility-matrix.md`
- `src/osu_server/transports/stable/web_legacy/getscores.py`
- `src/osu_server/composition/application.py`
- `src/osu_server/composition/providers/stable_web_legacy.py`
