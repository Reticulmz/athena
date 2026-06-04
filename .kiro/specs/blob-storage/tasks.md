# Implementation Plan

- [ ] 1. Establish blob storage foundation
- [x] 1.1 Add blob storage configuration and validation
  - Add runtime settings for backend selection, Local storage location, and S3-reserved values.
  - Reject unknown backend values and make S3 selection explicit rather than silently falling back to Local.
  - Update typed test configuration factories so tests can construct valid blob storage settings without raw dictionaries.
  - Completed state: application configuration can represent Local and S3 choices, invalid values fail validation, and test factories produce valid Local defaults.
  - _Requirements: 3.3, 3.5, 4.1, 4.2, 4.3, 11.1_

- [x] 1.2 Define immutable blob domain behavior
  - Define the blob entity as immutable metadata for stored content, not as a domain attachment.
  - Enforce required content type, lowercase SHA-256 identity, non-negative byte size, storage backend, storage key, and creation time.
  - Ensure original filename, uploader identity, owner record, and access policy are absent from shared blob metadata.
  - Completed state: blob domain tests prove valid blobs can be created and invalid digest, size, or content type values are rejected.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.5, 7.1, 7.2, 9.4_

- [x] 1.3 Create shared blob metadata persistence schema
  - Add the `blobs` persistence model and migration for SHA-256, byte size, content type, storage backend, storage key, and creation time.
  - Enforce unique SHA-256 identity and non-negative byte size at the persistence boundary.
  - Register the model for migration discovery.
  - Completed state: migration creates the blob metadata structure with uniqueness and integrity constraints, and downgrade removes it cleanly.
  - _Requirements: 1.1, 1.2, 2.3, 7.1, 7.2, 8.1_

- [ ] 2. Implement blob metadata repositories
- [x] 2.1 Define the blob repository contract
  - Provide the repository contract for finding blobs by ID and SHA-256 and creating new immutable blob records.
  - Keep update and delete operations out of the contract.
  - Specify duplicate-create behavior so the service can resolve races by returning an existing blob.
  - Completed state: repository consumers can depend on one typed contract that exposes create and lookup only.
  - _Requirements: 1.1, 1.2, 2.2, 2.3, 6.2, 8.1, 8.3_

- [ ] 2.2 (P) Implement the in-memory blob repository
  - Store blob records in memory with lookups by ID and SHA-256.
  - Preserve append-only behavior by omitting update and delete operations.
  - Return or raise a deterministic duplicate result when the same SHA-256 is created twice.
  - Completed state: unit tests show the in-memory repository can create, retrieve, and reject duplicate SHA-256 records without untyped mocks.
  - _Requirements: 2.2, 2.3, 2.4, 8.1, 8.3_
  - _Boundary: InMemoryBlobRepository_
  - _Depends: 2.1_

- [ ] 2.3 (P) Implement the SQLAlchemy blob repository
  - Persist blob records through the existing async repository pattern.
  - Map persistence rows back into immutable blob domain entities.
  - Handle unique SHA-256 conflicts in a way the service can convert into a deduplicated result.
  - Completed state: integration tests prove persisted blobs can be created and retrieved by ID and SHA-256, and duplicate SHA-256 writes do not produce two records.
  - _Requirements: 1.1, 1.2, 2.2, 2.3, 6.2, 7.1, 7.2, 8.1, 8.3_
  - _Boundary: SQLAlchemyBlobRepository_
  - _Depends: 1.3, 2.1_

- [ ] 3. Implement physical storage backend contracts
- [ ] 3.1 Define storage backend contracts and errors
  - Define stream chunk, staged write, backend validation, read, existence, and failure contracts.
  - Add typed errors for invalid storage configuration, unsupported backend selection, missing blob content, and backend read/write failures.
  - Keep backend contracts independent from filenames, uploader identity, domain attachments, and authorization.
  - Completed state: backend implementations and service code can share one typed contract for staged writes and stream reads.
  - _Requirements: 3.1, 3.4, 4.4, 5.1, 5.4, 6.1, 6.4, 10.1, 10.3, 11.1, 11.2, 11.3_

- [ ] 3.2 Implement Local storage validation and stream writes
  - Validate that the configured Local storage root exists or can be created and is writable.
  - Stage incoming chunks under a temporary area and finalize only to SHA-256-derived storage keys.
  - Ensure failed writes never expose readable partial content.
  - Completed state: Local backend tests prove successful writes become readable only after finalization and failed staging leaves no final blob.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 5.1, 5.4, 11.1, 11.2_

- [ ] 3.3 Implement Local stream reads and existence checks
  - Stream existing Local blob content in chunks from the configured storage root.
  - Report missing storage keys as unavailable content rather than successful empty reads.
  - Keep read behavior based on backend storage keys instead of user-provided filenames.
  - Completed state: Local backend tests can read finalized content in chunks and receive a typed missing-content error for absent keys.
  - _Requirements: 2.5, 3.2, 3.4, 6.1, 6.2, 6.4, 11.3_

- [ ] 3.4 Add S3-reserved backend selection behavior
  - Recognize S3 as a configured backend choice without implementing S3 object reads or writes.
  - Preserve S3 configuration inputs for future implementation.
  - Return an unsupported-backend configuration error when S3 is selected in this slice.
  - Completed state: configuration or composition tests prove S3 is recognized but cannot silently run as Local.
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 11.1_

- [ ] 4. Implement blob storage service behavior
- [ ] 4.1 Implement stream writes, SHA-256 integrity, and deduplication
  - Accept sequential chunks, calculate SHA-256 and byte size while writing, and require an explicit content type.
  - Return a new blob when the digest is not present and return the existing blob when content is duplicated.
  - Discard staged content when the blob already exists or when writing fails.
  - Log deduplication outcomes and write failures with enough context for diagnostics.
  - Completed state: service tests prove new writes, duplicate writes, missing content type, and write failures produce the expected stored, deduplicated, or failed outcomes.
  - _Requirements: 1.1, 1.2, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 5.1, 5.2, 5.3, 5.4, 7.1, 7.2, 7.3, 8.3, 11.2, 11.4_

- [ ] 4.2 Implement small-data write helper parity
  - Provide the small-data write helper as a wrapper around the same stream write behavior.
  - Ensure helper calls produce the same SHA-256, byte size, deduplication, and content type validation results as equivalent stream writes.
  - Completed state: tests prove storing the same bytes through stream and helper paths resolves to the same blob identity.
  - _Requirements: 2.1, 2.3, 5.5, 7.1, 7.2_

- [ ] 4.3 Implement stream reads and small-data read helper
  - Resolve blob metadata before opening backend content.
  - Stream existing content in chunks and report missing metadata or missing backend content as unavailable.
  - Provide a full-body helper for tests and known-small callers.
  - Completed state: service tests prove stream reads return chunks, read helper returns the full body, and missing records or missing backend content fail without returning partial success.
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 11.3_

- [ ] 4.4 Enforce lifecycle, attachment, and access boundaries
  - Keep delete, garbage collection, reference counting, attachment creation, filename tracking, uploader tracking, and authorization out of the service surface.
  - Allow multiple external domain attachment records to reference the same blob by keeping blobs domain-neutral.
  - Document trusted-caller expectations in service tests by requiring callers to perform authorization before reads.
  - Completed state: public service surface exposes store/read behavior only, with no delete or attachment operation available.
  - _Requirements: 1.3, 8.1, 8.2, 8.3, 8.4, 9.1, 9.2, 9.3, 9.4, 9.5, 10.1, 10.2, 10.3_

- [ ] 5. Wire blob storage into application composition
- [ ] 5.1 Register blob repository, backend, and service in the composition root
  - Select in-memory metadata persistence for tests and SQLAlchemy persistence outside tests.
  - Select Local backend when configured and validate it before accepting storage operations.
  - Fail startup or first-use validation clearly when S3 is selected before implementation.
  - Completed state: DI integration tests can resolve the blob storage service with Local config and observe an unsupported-backend error with S3 config.
  - _Requirements: 3.3, 3.5, 4.1, 4.2, 4.3, 11.1_

- [ ] 5.2 Integrate diagnostics for configuration, writes, reads, and deduplication
  - Emit structured diagnostic information for invalid configuration, write failures, read failures, and deduplicated writes.
  - Avoid logging blob body content or user-provided filenames.
  - Completed state: tests or log-capture checks prove failure and deduplication paths produce observable diagnostics without leaking file bodies.
  - _Requirements: 11.1, 11.2, 11.3, 11.4_

- [ ] 6. Validate persistence, storage, and integration behavior
- [ ] 6.1 Complete domain and repository test coverage
  - Cover blob validation, immutable metadata, no attachment fields, in-memory repository behavior, and SQLAlchemy repository behavior.
  - Include duplicate SHA-256 and append-only expectations.
  - Completed state: domain and repository tests pass and cover blob creation, lookup, duplicate handling, and absence of update/delete behavior.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.2, 2.3, 2.4, 7.1, 7.2, 8.1, 9.4_

- [ ] 6.2 Complete backend and service test coverage
  - Cover Local validation, staging/finalization, missing storage keys, stream write/read behavior, helper parity, write-time integrity, and read-time non-rehash behavior.
  - Cover write failure and read failure responses.
  - Completed state: backend and service tests pass for chunked writes, chunked reads, duplicate writes, missing content, and helper parity.
  - _Requirements: 2.1, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 6.2, 6.3, 6.4, 7.1, 7.2, 7.3, 7.4, 11.2, 11.3, 11.4_

- [ ] 6.3 Complete composition and boundary regression tests
  - Cover Local and S3 backend selection, trusted-caller read expectations, no shared attachment table behavior, and absence of delete or garbage collection operations.
  - Ensure downstream attachment metadata remains outside shared blob records.
  - Completed state: integration tests prove composition resolves the service correctly and boundary regression tests fail if attachment, authorization, or delete concerns enter blob storage.
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 8.1, 8.2, 8.4, 9.1, 9.2, 9.3, 9.4, 9.5, 10.1, 10.2, 10.3, 11.1_

- [ ] 6.4 Run full quality validation for blob storage
  - Run the project quality checks and targeted test suites for blob storage.
  - Fix lint, type, import boundary, and test failures within this spec's ownership.
  - Completed state: quality checks and blob-storage tests pass, and failures outside this spec are documented rather than hidden.
  - _Requirements: 1.1, 2.1, 3.1, 4.1, 5.1, 6.1, 7.1, 8.1, 9.1, 10.1, 11.1_
