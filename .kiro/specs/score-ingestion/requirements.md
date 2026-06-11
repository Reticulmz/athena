# Requirements Document: Score Ingestion (Wave 1)

**Feature**: score-ingestion
**Wave**: 1 of 4
**Goal**: Stable client が vanilla play の score を submit でき、completed response を受け取れる

## Introduction

Athena に osu! stable client からの score 受付機能を実装します。Wave 1 では、score の受付、validation、保存、replay 保存までを実装し、PP 計算や leaderboard 更新は後続 wave に委譲します。

目標は「stable client が正しく動作する」ことであり、client が submit 後に completed response を受け取り、次の play に進めることです。

## Boundary Context

**In Scope**:
- Stable client からの `/web/osu-submit-modular-selector.php` POST request
- Multipart form data parsing (duplicate `score` field の order-preserving)
- Rijndael-256 decryption (PyO3 + Rust implementation)
- Score payload parsing (colon-separated data → domain object)
- Authorization (password + active session + payload identity match)
- Score validation (hit counts 整合性、ruleset-specific validation)
- Uniqueness check (online checksum + replay checksum)
- Score record 保存 (passed/failed 両方)
- Replay blob 保存
- Idempotent retry handling (submission fingerprint)
- Response format (completed / terminal reject / retryable)
- Beatmap eligibility check (Ranked/Approved/Loved/Qualified のみ)

**Out of Scope**:
- PP calculation (Wave 2)
- Beatmap leaderboard projection (Wave 3)
- User stats projection (Wave 3)
- User ranking projection (Wave 4)
- Relax/Autopilot playstyle (将来 feature)
- Anti-cheat detection (replay checksum uniqueness のみ Wave 1 で実装)
- Replay download endpoint
- `.osu` file fetch (Wave 2 で PP 計算時に必要)

**Adjacent Expectations**:
- `beatmap-mirror` は beatmap metadata と eligibility を提供する
- `blob-storage` は replay binary の保存を提供する
- Active session store は authorization に必要
- Legacy auth service は password 検証を提供する

## Requirements

### Requirement 1: Stable Submit Endpoint

**Objective**: As a stable client user, I want to submit scores through the legacy endpoint, so that my gameplay results are recorded.

#### Acceptance Criteria

1. When a stable client sends a POST request to `/web/osu-submit-modular-selector.php`, the Score Ingestion Feature shall process it as a stable score submission.
2. The Score Ingestion Feature shall support vanilla gameplay for `osu`, `taiko`, `catch`, and `mania` rulesets.
3. When a submission contains Relax or Autopilot mods, the Score Ingestion Feature shall reject it with a terminal reject response (Wave 1 scope limitation).
4. The Score Ingestion Feature shall preserve the `playstyle` schema dimension for future expansion.

---

### Requirement 2: Multipart Request Parsing

**Objective**: As a compatibility maintainer, I want the server to parse stable multipart requests correctly, so that real clients can submit without format mismatches.

#### Acceptance Criteria

1. When a submission contains duplicate `score` fields, the Score Ingestion Feature shall preserve field order and distinguish the encrypted score payload (first) from the replay binary (second).
2. When required fields (`score`, `iv`, `pass`, `x`, `ft`, `osuver`) are present, the Score Ingestion Feature shall extract them correctly.
3. When optional fields (`fs`, `bmk`, `sbk`, `c1`, `st`, `i`, `token`) are present, the Score Ingestion Feature shall preserve them for diagnostics without logging raw credential material.
4. When request size exceeds configured limits (total body size, replay size, text field size), the Score Ingestion Feature shall reject the submission with a terminal reject response.
5. When multipart parsing fails, the Score Ingestion Feature shall return a terminal reject response without creating a score record.

---

### Requirement 3: Score Payload Decryption

**Objective**: As a security-conscious operator, I want score payloads decrypted with the correct algorithm, so that submissions are authentic.

#### Acceptance Criteria

1. When a submission contains `osuver`, the Score Ingestion Feature shall use the key `osu!-scoreburgr---------{osuver}` for Rijndael-256 decryption.
2. When a submission lacks `osuver`, the Score Ingestion Feature shall use the legacy key for Rijndael-256 decryption.
3. When decryption succeeds, the Score Ingestion Feature shall validate the decrypted payload checksum.
4. When decryption fails or checksum mismatches, the Score Ingestion Feature shall reject the submission with a terminal reject response.
5. The Score Ingestion Feature shall implement Rijndael-256 decryption via PyO3 + Rust (block size 32 bytes, CBC mode, 32-byte IV).

---

### Requirement 4: Authorization

**Objective**: As an operator, I want submissions tied to authenticated users, so that forged requests cannot create scores.

#### Acceptance Criteria

1. When a submission contains a valid password-md5 credential for a user with an active bancho session, the Score Ingestion Feature shall authorize the request only if the decrypted payload identity matches that user.
2. When the password credential is invalid, the Score Ingestion Feature shall reject the submission with a terminal reject response.
3. When the user has no active bancho session, the Score Ingestion Feature shall reject the submission with a terminal reject response.
4. When the decrypted payload username or user ID does not match the authenticated user, the Score Ingestion Feature shall reject the submission with a terminal reject response.
5. The Score Ingestion Feature shall not log raw password-md5 material.

---

### Requirement 5: Score Validation

**Objective**: As a leaderboard viewer, I want server-side validation, so that client-reported values are trustworthy.

#### Acceptance Criteria

1. When a score is submitted, the Score Ingestion Feature shall validate hit counts against ruleset-specific expectations.
2. When a score is submitted, the Score Ingestion Feature shall calculate accuracy from hit counts, ruleset, and mods.
3. When a score is submitted, the Score Ingestion Feature shall calculate grade from score data and ruleset-specific rules.
4. When client-reported accuracy or grade differs from server-calculated values, the Score Ingestion Feature shall preserve the discrepancy for diagnostics.
5. When hit counts are internally inconsistent, the Score Ingestion Feature shall reject the submission with a terminal reject response.

---

### Requirement 6: Uniqueness Enforcement

**Objective**: As an operator, I want duplicate scores rejected, so that replay reuse and accidental duplicates are prevented.

#### Acceptance Criteria

1. When a submission's online checksum matches an existing score, the Score Ingestion Feature shall reject the submission with a terminal reject response.
2. When a submission's replay checksum matches an existing replay, the Score Ingestion Feature shall reject the submission with a terminal reject response (prevents replay reuse across users).
3. When a submission fingerprint matches an existing submission, the Score Ingestion Feature shall return the existing result snapshot without creating a new score.
4. The Score Ingestion Feature shall calculate submission fingerprint from user ID, beatmap checksum, submitted timestamp, and request hash.

---

### Requirement 7: Score Persistence

**Objective**: As a player, I want submitted scores stored reliably, so that my gameplay history is preserved.

#### Acceptance Criteria

1. When a validated score is submitted, the Score Ingestion Feature shall create a score record with user ID, beatmap ID, beatmap checksum, ruleset, playstyle, mods, hit counts, score value, max combo, accuracy, grade, passed flag, perfect flag, client version, and submitted timestamp.
2. When a score is failed (passed=false), the Score Ingestion Feature shall store it as a score record.
3. When a submission contains a replay binary, the Score Ingestion Feature shall store the replay in blob storage and record the attachment metadata.
4. When a submission lacks a replay binary, the Score Ingestion Feature shall create the score record without a replay attachment.
5. The Score Ingestion Feature shall record the beatmap's effective status at submission time.

---

### Requirement 8: Beatmap Eligibility

**Objective**: As an operator, I want scores accepted only for leaderboard-eligible beatmaps, so that storage is meaningful.

#### Acceptance Criteria

1. When a score is submitted for a Ranked or Approved beatmap, the Score Ingestion Feature shall accept it.
2. When a score is submitted for a Loved beatmap, the Score Ingestion Feature shall accept it.
3. When a score is submitted for a Qualified beatmap, the Score Ingestion Feature shall accept it.
4. When a score is submitted for a Pending, WIP, Graveyard, NotSubmitted, or Unknown beatmap, the Score Ingestion Feature shall reject it with a terminal reject response.
5. The Score Ingestion Feature shall query beatmap metadata and eligibility from the beatmap mirror service.

---

### Requirement 9: Idempotent Retry Handling

**Objective**: As a stable client user, I want retries to produce consistent results, so that network errors do not create duplicate scores.

#### Acceptance Criteria

1. When the same submission is received multiple times (same fingerprint), the Score Ingestion Feature shall identify it as a retry.
2. When a retry is received after processing completed, the Score Ingestion Feature shall return the same result snapshot without creating a new score.
3. When a retry is received while processing is still in progress, the Score Ingestion Feature shall return an accepted_pending response.
4. The Score Ingestion Feature shall store submission state and result snapshot for retry handling.

---

### Requirement 10: Response Format

**Objective**: As a stable client user, I want clear submission results, so that I know whether my score was accepted.

#### Acceptance Criteria

1. When a score is successfully stored, the Score Ingestion Feature shall return a completed response with chart placeholder data (PP fields omitted or zero).
2. When authorization fails, decryption fails, validation fails, or uniqueness is violated, the Score Ingestion Feature shall return a terminal reject response.
3. When a temporary error occurs (storage unavailable, worker queue full), the Score Ingestion Feature shall return a retryable response.
4. The Score Ingestion Feature shall not expose internal diagnostics, credential material, or storage identifiers in client responses.
5. The Score Ingestion Feature shall format responses according to stable client expectations (chart text format).

---

### Requirement 11: Security and Privacy

**Objective**: As an operator, I want submissions diagnosable without leaking secrets, so that production issues can be investigated safely.

#### Acceptance Criteria

1. When authorization fails, the Score Ingestion Feature shall log a non-secret failure reason without raw password-md5.
2. When parsing, validation, or storage fails, the Score Ingestion Feature shall record the failure category for diagnostics.
3. When optional opaque fields are present, the Score Ingestion Feature shall store SHA-256 hashes for audit without logging raw values.
4. The Score Ingestion Feature shall not persist or log raw password-md5, raw token, or raw encrypted payload.
5. The Score Ingestion Feature shall record submission fingerprint, failure category, and result snapshot for operational observability.

---

### Requirement 12: Failed Play Handling

**Objective**: As a player, I want failed plays recorded, so that my play history is complete.

#### Acceptance Criteria

1. When a failed gameplay result is submitted (passed=false), the Score Ingestion Feature shall store it as a score record.
2. When a failed play includes replay data, the Score Ingestion Feature shall store the replay.
3. The Score Ingestion Feature shall store the `x` field (exit/quit classification) and `ft` field (fail time in milliseconds) for failed plays.
4. The Score Ingestion Feature shall exclude failed plays from future leaderboard and PP calculations (out of Wave 1 scope, but schema should support it).

---

## Wave 1 Constraints

- **No PP calculation**: Scores are stored without PP values. Wave 2 will add PP.
- **No leaderboard projection**: Scores are not reflected in leaderboards. Wave 3 will add projections.
- **No user stats update**: Play count, ranked score, and rank are not updated. Wave 3-4 will add stats.
- **Vanilla playstyle only**: Relax/Autopilot submissions are rejected. Future feature will add RX/AP support.
- **Completed response without PP**: Client receives success response with placeholder chart data.

## Compatibility Evidence

Refer to research.md for:
- bancho.py/Akatsuki score submission implementation
- osuRipple/lets submitModularHandler
- osuTitanic/deck scoring route
- Duplicate `score` field handling (first = payload, second = replay)
- AES key selection with `osuver`
- Colon-separated score data format
