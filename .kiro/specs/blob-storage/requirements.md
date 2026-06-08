# Requirements Document

## Introduction

Athena needs a reusable blob storage capability for file-like content such as `.osu` beatmap files, future score replays, screenshots, and uploaded images. The feature must provide stable storage semantics before `beatmap-mirror` depends on it, while keeping domain-specific attachment rules outside the shared blob layer.

This specification defines the behavior expected from the shared Blob Storage Service: content-addressed storage, immutable blob metadata, Local storage support, S3-ready configuration expectations, stream-oriented reads and writes, deduplication, and explicit boundaries around attachments, authorization, deletion, and garbage collection.

## Boundary Context

- **In scope**:
  - Shared blob records for immutable file bodies
  - Local storage as the first usable backend
  - S3-ready backend selection and configuration validation
  - SHA-256 based content addressing and deduplication
  - Stream-oriented write and read behavior
  - Small-data helper behavior for callers and tests
  - Required content type handling
  - Append-only blob lifecycle

- **Out of scope**:
  - Domain-specific attachment tables
  - Polymorphic attachment records
  - Access control decisions for blob consumers
  - Physical blob deletion
  - Garbage collection of unreferenced blobs
  - Full S3 backend implementation
  - WebUI upload flows
  - Beatmap, replay, screenshot, or image domain behavior

- **Adjacent expectations**:
  - Domain features define their own attachment records and store domain metadata such as original filename, uploader identity, owning record, and access rules.
  - `beatmap-mirror` uses this feature for `.osu` file bodies but owns beatmap metadata and beatmap-file attachment records.
  - Future replay, screenshot, and image-upload features may reference shared blobs through their own domain-specific attachment records.

## Requirements

### Requirement 1: Blob Record Creation

**Objective:** As a feature developer, I want file bodies to be stored as immutable blobs, so that multiple domains can safely reference the same stored content.

#### Acceptance Criteria

1. When a caller stores new content, the Blob Storage Service shall create a blob record that identifies the stored content by SHA-256, byte size, content type, storage backend, storage key, and creation time.
2. The Blob Storage Service shall treat blob records as immutable after creation.
3. The Blob Storage Service shall not store domain-specific attachment metadata such as original filename, uploader identity, owning domain record, or access policy in the shared blob record.
4. The Blob Storage Service shall reject blob creation requests that do not provide a content type.
5. When a caller cannot determine a specific content type, the Blob Storage Service shall accept `application/octet-stream` as an explicit content type.

### Requirement 2: Content Addressing and Deduplication

**Objective:** As a storage operator, I want identical content to resolve to one shared blob, so that storage usage and references remain consistent.

#### Acceptance Criteria

1. When a caller stores content, the Blob Storage Service shall calculate the SHA-256 digest from the content bytes being stored.
2. When the calculated SHA-256 digest does not already exist, the Blob Storage Service shall store the content and return the newly created blob.
3. When the calculated SHA-256 digest already exists, the Blob Storage Service shall return the existing blob without creating a duplicate blob record.
4. When duplicate content is stored with a different original filename or uploader, the Blob Storage Service shall still return the existing shared blob and leave filename and uploader tracking to the caller's domain attachment record.
5. The Blob Storage Service shall derive storage identity from content, not from user-provided filenames.

### Requirement 3: Local Storage Backend

**Objective:** As a developer, I want a Local storage backend to be available first, so that dependent features can store and read blobs before external object storage is implemented.

#### Acceptance Criteria

1. Where the Local storage backend is selected, the Blob Storage Service shall store blob content in the configured local storage location.
2. When content is stored through the Local storage backend, the Blob Storage Service shall make the content readable by its returned blob identity after the write completes.
3. If the configured local storage location is unavailable or not writable, the Blob Storage Service shall report a storage configuration error before accepting blob writes.
4. The Blob Storage Service shall not use user-provided filenames as local storage paths.
5. The Blob Storage Service shall make Local storage usable in development, production, and tests when configured for those environments.

### Requirement 4: S3-Ready Backend Selection

**Objective:** As an operator, I want the blob storage configuration to reserve a future S3 backend, so that deployment can move to object storage without changing blob consumers.

#### Acceptance Criteria

1. Where backend selection is configured, the Blob Storage Service shall recognize Local and S3 as storage backend choices.
2. Where the S3 backend is selected before S3 support is implemented, the Blob Storage Service shall report that the backend is unavailable rather than silently falling back to another backend.
3. Where S3 configuration values are provided, the Blob Storage Service shall preserve them as configuration inputs for the future S3 backend.
4. The Blob Storage Service shall expose the same caller-facing storage behavior regardless of whether the selected backend is Local or a future S3 backend.

### Requirement 5: Stream-Oriented Writes

**Objective:** As a feature developer, I want to write blob content as a stream, so that large replay or image files do not need to be fully loaded into memory.

#### Acceptance Criteria

1. When a caller writes content as a stream, the Blob Storage Service shall accept sequential chunks and store them as one blob.
2. While a stream write is in progress, the Blob Storage Service shall calculate the SHA-256 digest and byte size from the received chunks.
3. When a stream write completes successfully, the Blob Storage Service shall return the stored or deduplicated blob.
4. If a stream write fails before completion, the Blob Storage Service shall not expose a readable partial blob.
5. The Blob Storage Service shall provide a small-data write helper that behaves the same as stream write for equivalent bytes.

### Requirement 6: Stream-Oriented Reads

**Objective:** As a feature developer, I want to read blob content as a stream, so that callers can consume large files without loading the entire file body at once.

#### Acceptance Criteria

1. When a caller requests an existing blob as a stream, the Blob Storage Service shall provide the blob content in sequential chunks.
2. When a caller requests a missing blob, the Blob Storage Service shall report that the blob content is unavailable.
3. The Blob Storage Service shall provide a small-data read helper for callers that explicitly need the full blob body.
4. The Blob Storage Service shall keep stream read behavior independent of the selected storage backend.

### Requirement 7: Write-Time Integrity

**Objective:** As an operator, I want blob integrity to be established when content is written, so that stored metadata matches the actual bytes accepted by the service.

#### Acceptance Criteria

1. When content is written, the Blob Storage Service shall record the SHA-256 digest calculated from the accepted bytes.
2. When content is written, the Blob Storage Service shall record the byte size calculated from the accepted bytes.
3. If the service cannot complete integrity calculation during write, the Blob Storage Service shall fail the write and avoid returning a blob.
4. The Blob Storage Service shall not require SHA-256 recalculation during every read.

### Requirement 8: Append-Only Lifecycle

**Objective:** As an operator, I want the initial blob storage lifecycle to avoid destructive deletion, so that shared blobs are not removed while future domain attachments may still reference them.

#### Acceptance Criteria

1. The Blob Storage Service shall not provide a caller-facing operation that physically deletes blob content in the initial feature.
2. When a caller needs to stop using a blob, the Blob Storage Service shall expect the caller's domain feature to remove or update its own attachment record.
3. The Blob Storage Service shall keep existing blob content readable after another caller stores duplicate content.
4. The Blob Storage Service shall leave unreferenced blob cleanup to a future garbage collection capability.

### Requirement 9: Attachment Boundary

**Objective:** As a domain feature owner, I want attachment ownership to stay in each domain, so that each feature can enforce its own relationships, metadata, and access rules.

#### Acceptance Criteria

1. The Blob Storage Service shall not provide polymorphic attachment records.
2. The Blob Storage Service shall not require all blob consumers to share one generic attachment table.
3. Where a domain feature attaches a blob to a domain record, that domain feature shall own the attachment record and domain-specific metadata.
4. Where a domain feature needs original filename or uploader tracking, that domain feature shall store those values outside the shared blob record.
5. The Blob Storage Service shall allow multiple domain attachment records to reference the same blob.

### Requirement 10: Access Responsibility Boundary

**Objective:** As an API or domain feature owner, I want blob access decisions to stay with the consuming feature, so that public and private file types can apply different authorization rules.

#### Acceptance Criteria

1. The Blob Storage Service shall not decide whether an end user is authorized to read a blob.
2. When a consuming feature streams a blob to a user, that consuming feature shall determine access before reading or returning blob content.
3. The Blob Storage Service shall provide stored content only to trusted application callers that already passed their own access decision.

### Requirement 11: Observability and Error Reporting

**Objective:** As an operator, I want storage failures and configuration problems to be visible, so that blob-dependent features can be diagnosed safely.

#### Acceptance Criteria

1. If blob storage configuration is invalid, the Blob Storage Service shall report a configuration error before accepting storage operations.
2. If a blob write fails, the Blob Storage Service shall report the failure without returning a successful blob result.
3. If a blob read fails, the Blob Storage Service shall report the failure without returning corrupt or partial content as a successful read.
4. When deduplication returns an existing blob, the Blob Storage Service shall make that outcome observable to application diagnostics.
