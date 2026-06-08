# Research & Design Decisions: blob-storage

## Summary
- **Feature**: `blob-storage`
- **Discovery Scope**: New Feature / Complex Integration
- **Key Findings**:
  - Existing Athena persistence follows typed domain models, repository Protocols, SQLAlchemy implementations, in-memory test doubles, Alembic migrations, and composition-root registration.
  - A small built storage abstraction fits the requirements better than adopting a framework-level attachment system because attachments are explicitly owned by downstream domain specs.
  - S3 can support SHA-256 integrity and key-prefix based object organization later, so the first slice should keep SHA-256 storage keys backend-neutral.

## Research Log

### Existing Athena Architecture
- **Context**: The feature introduces shared persistence and runtime registration, so it must align with existing project boundaries.
- **Sources Consulted**:
  - `src/osu_server/config.py`
  - `src/osu_server/composition/service_registry.py`
  - `src/osu_server/infrastructure/di/container.py`
  - `src/osu_server/repositories/interfaces/channel_repository.py`
  - `src/osu_server/repositories/sqlalchemy/channel_repository.py`
  - `src/osu_server/repositories/sqlalchemy/models/channel.py`
  - `alembic/versions/20260525_2100_create_channels_messages_tables.py`
  - `tests/README.md`
- **Findings**:
  - Configuration is centralized in `AppConfig` with pydantic-settings.
  - Runtime wiring is centralized in `register_services`.
  - Repository interfaces live in `repositories/interfaces`; SQLAlchemy and in-memory implementations are separate.
  - SQLAlchemy models inherit from `Base` and are imported through `repositories/sqlalchemy/models/__init__.py` for Alembic discovery.
  - Tests prefer typed in-memory implementations and typed fakes over untyped mocks.
- **Implications**:
  - Blob metadata should use `BlobRepository` Protocol plus SQLAlchemy and in-memory implementations.
  - Blob storage backend should be injected through the composition root.
  - Tests should use in-memory repository and tempdir or in-memory backend patterns.

### SHA-256 and Streaming Hashes
- **Context**: Requirements mandate content-addressed deduplication and write-time integrity.
- **Sources Consulted**:
  - [Python hashlib documentation](https://docs.python.org/3/library/hashlib.html)
- **Findings**:
  - Python's standard `hashlib` provides guaranteed SHA-256 support and supports incremental updates over bytes-like chunks.
  - Incremental hashing aligns with stream writes and avoids full-body memory loading for larger blobs.
- **Implications**:
  - The service can calculate SHA-256 and byte size while forwarding chunks to the backend staging write.
  - No third-party hashing library is required.

### Local Atomic Write Behavior
- **Context**: Partial blobs must not become readable after failed stream writes.
- **Sources Consulted**:
  - [Python os documentation](https://docs.python.org/3/library/os.html#os.replace)
  - [Python tempfile documentation](https://docs.python.org/3/library/tempfile.html)
- **Findings**:
  - Python standard-library filesystem primitives support temp-file based staging and replacement semantics suitable for same-filesystem finalization.
  - Temp files should be created inside the configured blob directory so finalization stays on the same filesystem.
- **Implications**:
  - Local backend should write chunks to a temporary staging file, then finalize to the SHA-256-derived storage key only after hashing and write completion.
  - Failed writes should clean up staging files and never publish a final key.

### S3 Forward Compatibility
- **Context**: S3 is out of implementation scope but must be a recognized backend choice.
- **Sources Consulted**:
  - [Amazon S3 object key naming documentation](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-keys.html)
  - [Amazon S3 object integrity documentation](https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html)
- **Findings**:
  - S3 object keys are flat identifiers with prefix conventions, so SHA-256 prefix partitioning maps naturally to later S3 keys.
  - S3 supports SHA-256 checksums as an object integrity option.
- **Implications**:
  - Storage keys should use safe ASCII hex path segments such as `sha256/ab/cd/<digest>`.
  - The interface should carry enough metadata for a future S3 adapter without changing consumers.
  - Selecting S3 in the first implementation should fail explicitly instead of falling back to Local.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Domain-owned attachments plus shared blob service | Shared service owns blob bodies and immutable metadata; each domain owns attachment records | Matches requirements, keeps foreign keys domain-specific, avoids polymorphic association risk | More attachment tables later | Selected |
| ActiveStorage-style polymorphic attachments | Shared blobs plus one generic attachment table | Flexible and familiar | Weak domain constraints in Python/SQLAlchemy, conflicts with requirement boundary | Rejected |
| Store file bodies in domain tables | Each domain stores raw bytes or text body directly | Simple for the first `.osu` use case | Duplicates storage logic, poor for replays/images, hard to migrate to S3 | Rejected |
| Adopt a generic storage library | Use an existing content-addressed filesystem package | Less code | Adds dependency without matching repository/attachment boundary; S3 still needs custom integration | Rejected for first slice |

## Design Decisions

### Decision: Build a Small Blob Storage Service
- **Context**: The current scope needs only blob metadata, local storage, deduplication, and future backend selection.
- **Alternatives Considered**:
  1. Adopt a storage framework or library.
  2. Implement storage separately inside `beatmap-mirror`.
  3. Build a small shared blob service.
- **Selected Approach**: Build a small shared `BlobStorageService` with repository and backend interfaces.
- **Rationale**: It matches current needs, follows Athena's existing service/repository patterns, and avoids introducing a dependency that would not solve domain attachments.
- **Trade-offs**: More local code to maintain, but fewer external abstractions and clearer boundaries.
- **Follow-up**: Re-evaluate adoption when S3 implementation is added if an SDK abstraction becomes necessary.

### Decision: Domain-Specific Attachments
- **Context**: The user explicitly preferred avoiding Python polymorphic association risk.
- **Alternatives Considered**:
  1. Shared polymorphic attachment table.
  2. Domain-specific attachment tables.
- **Selected Approach**: `blob-storage` owns only `blobs`; downstream specs own attachment tables.
- **Rationale**: Domain-specific tables preserve foreign keys, domain constraints, uploader/original filename semantics, and access rules.
- **Trade-offs**: More tables over time, but safer migrations and clearer ownership.
- **Follow-up**: Future specs must reference this rule in their brief/design before adding attachments.

### Decision: SHA-256 Storage Key
- **Context**: Deduplication, integrity, and future S3 compatibility require a stable content identity.
- **Alternatives Considered**:
  1. User filename based keys.
  2. Random UUID keys plus checksum metadata.
  3. SHA-256-derived keys.
- **Selected Approach**: Use SHA-256 as the unique blob identity and derive storage keys from it.
- **Rationale**: It satisfies deduplication and keeps paths independent of filenames or domains.
- **Trade-offs**: Content must be staged before final key is known; stream writes need a staging step.
- **Follow-up**: Add migration/repair tooling later if storage key and DB metadata ever diverge.

### Decision: Append-Only Initial Lifecycle
- **Context**: Deletion is risky because references are owned by future domain-specific tables.
- **Alternatives Considered**:
  1. Provide physical delete now.
  2. Provide reference-count deletion now.
  3. Defer delete and garbage collection.
- **Selected Approach**: Initial service is append-only with no physical delete API.
- **Rationale**: It prevents accidental removal of shared blobs before all attachment consumers exist.
- **Trade-offs**: Storage can grow until a future garbage collector is implemented.
- **Follow-up**: Create a later garbage collection spec after multiple attachment domains exist.

## Risks & Mitigations
- Concurrent duplicate writes may race on the same SHA-256. Mitigation: enforce a unique `sha256` constraint and treat conflict as "return existing blob".
- DB record creation can fail after local file finalization. Mitigation: finalize only after successful staging, use idempotent key naming, and allow a later cleanup job for orphan files.
- Local disk may be unavailable or not writable. Mitigation: validate backend configuration at startup and fail before accepting writes.
- S3 selection may be accidentally enabled early. Mitigation: recognize the S3 backend choice but raise an explicit unsupported-backend configuration error.
- Large files can pressure memory if callers use helper methods. Mitigation: make stream APIs primary and document helper methods as small-data/test conveniences.

## References
- [Python hashlib documentation](https://docs.python.org/3/library/hashlib.html) — Standard SHA-256 and incremental hashing support.
- [Python os.replace documentation](https://docs.python.org/3/library/os.html#os.replace) — Local finalization primitive.
- [Python tempfile documentation](https://docs.python.org/3/library/tempfile.html) — Temporary file staging support.
- [Amazon S3 object key naming documentation](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-keys.html) — Future backend key constraints.
- [Amazon S3 object integrity documentation](https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html) — Future checksum compatibility.
