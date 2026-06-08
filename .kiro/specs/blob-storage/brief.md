# Brief: blob-storage

## Problem
Athena needs a reusable way to store binary or file-like content before implementing beatmap mirroring, score replays, screenshots, and future image uploads. Without a shared blob storage boundary, each feature would create its own filesystem or database storage rules, making deduplication, integrity checks, backend migration, and attachment ownership inconsistent.

## Current State
The project has PostgreSQL via SQLAlchemy repositories, Alembic migrations, taskiq jobs, and typed configuration through `AppConfig`, but it does not yet have a generic blob storage service. `beatmap-mirror` will need to store `.osu` files, and later features are expected to store replay files and uploaded images.

## Desired Outcome
Athena has a content-addressed blob storage service that stores file bodies outside normal domain tables, records immutable blob metadata in the database, supports Local storage initially, and leaves room for S3 without changing consumers. Features attach blobs through their own domain-specific attachment tables instead of using a polymorphic association.

## Approach
Implement `blob-storage` as a small shared infrastructure capability. The initial implementation provides a Local backend, stream-based read/write APIs, SHA-256 based deduplication, write-time integrity calculation, and a `blobs` table for immutable blob metadata. S3 is designed through interface and configuration, but does not need a full backend implementation in the first slice.

## Scope
- **In**: Local backend implementation, storage backend interface, S3-ready interface/config design, `blobs` table, SHA-256 content addressing, deduplication, stream write/read APIs, `put_bytes` / `read_bytes` helpers for small data and tests, write-time SHA-256 and byte-size calculation, required `content_type`, append-only behavior.
- **Out**: Domain-specific attachment tables, polymorphic attachment records, blob access control, physical deletion, garbage collection, S3 backend implementation, WebUI upload flows, beatmap metadata, score replay domain behavior, screenshot domain behavior.

## Boundary Candidates
- Blob storage service owns immutable blob records and physical storage backend operations.
- Domain specs own attachment tables and domain-specific metadata such as `original_filename`, `uploaded_by_user_id`, record foreign keys, and access rules.
- API and domain services own authorization before streaming blobs to callers.

## Out of Boundary
- Do not store `.osu` body, replay body, or image body directly in domain tables.
- Do not implement Python/SQLAlchemy polymorphic attachments for the first storage design.
- Do not let blob storage decide whether a user can access a blob.
- Do not physically delete blobs in the initial implementation.

## Upstream / Downstream
- **Upstream**: Existing `AppConfig`, SQLAlchemy async repository pattern, Alembic migrations, test fake/in-memory conventions.
- **Downstream**: `beatmap-mirror` stores `.osu` files through this service; future `score-submission` or replay features store replay files; future screenshot or image upload features store image blobs; future garbage collection can remove unreferenced blobs.

## Existing Spec Touchpoints
- **Extends**: None.
- **Adjacent**: `beatmap-mirror` depends on this spec for `.osu` file storage. `score-submission` and future screenshot/image upload specs should define their own attachment tables that reference `blobs`.

## Constraints
- Use Python 3.14+, SQLAlchemy 2.0 async, Alembic, repository pattern, and `AppConfig` settings consistent with existing steering.
- Local backend is required in the first implementation.
- S3 support is limited to interface, configuration names, and design in the first implementation.
- `sha256` must be unique and used for content-addressed deduplication.
- Storage paths must be derived from SHA-256, not from user-provided filenames.
- `content_type` is required; unknown content must be explicitly stored as `application/octet-stream`.
- Integrity is verified during write only. Read-time verification is out of scope except for future maintenance tooling.
- `original_filename` and `uploaded_by_user_id` belong to domain-specific attachment tables, not the shared `blobs` table.
