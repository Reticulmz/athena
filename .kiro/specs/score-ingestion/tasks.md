# 実装計画: Score Ingestion (Wave 1)

## Phase 1: Foundation

- [x] 1. PyO3 Crypto Module
- [x] 1.1 Rust workspaceとPyO3 bindingsをセットアップ
  - `athena-crypto/` ディレクトリを作成
  - `Cargo.toml`: `simple-rijndael` 依存追加、PyO3有効化
  - `pyproject.toml`: maturin build設定
  - `src/lib.rs`: PyO3モジュールエントリポイント
  - `maturin develop`でPython側からimport可能になる
  - _Requirements: 3.5_
  - _Boundary: athena-crypto Rust module_

- [x] 1.2 Rijndael-256 decryption関数を実装
  - `simple-rijndael`の`RijndaelCbc`を使用
  - Key selection logic（osuverベース）
  - CBC mode decryption (block_size=32, IV=32)
  - Checksum validation
  - PyO3経由でPythonから呼び出し可能
  - _Requirements: 3.1, 3.2, 3.3, 3.4_
  - _Boundary: athena-crypto Rust module_

- [x] 2. Python Service Layer
- [x] 2.1 ScoreCryptoServiceを実装
  - `DecryptedPayload` dataclass
  - `decrypt_score_payload()` function
  - athena_crypto wrapper with error handling
  - _Requirements: 3.1-3.5_
  - _Boundary: osu_server.services.score_crypto_

- [x] 3. Test Infrastructure
- [x] 3.1 (P) Test fixturesとfactoriesをセットアップ
  - `tests/factories/score_factory.py`: Valid score data生成
  - `tests/factories/multipart_factory.py`: Multipart request生成
  - `tests/factories/crypto_factory.py`: Encrypted payload生成
  - Golden files: `tests/fixtures/golden/` (test-account stable client samples)
  - _Requirements: All (test support)_
  - _Boundary: Test infrastructure_

## Phase 2: Domain Layer (TDD)

- [x] 4. Domain Models
- [x] 4.1 (P) Score dataclassを実装
  - `domain/score/score.py`
  - `@dataclass(slots=True)` with all fields
  - Ruleset, Playstyle, Grade enums
  - Unit test: field validation
  - _Requirements: 7.1_
  - _Boundary: domain/score/score.py_

- [x] 4.2 (P) ScoreSubmission dataclassを実装
  - `domain/score/submission.py`
  - Fingerprint, state, result_snapshot fields
  - Unit test: state transitions
  - _Requirements: 9.1, 9.2_
  - _Boundary: domain/score/submission.py_

- [x] 4.3 (P) Replay dataclassを実装
  - `domain/score/replay.py`
  - blob_key, checksum_sha256, byte_size fields
  - Unit test: checksum validation
  - _Requirements: 7.3, 7.4_
  - _Boundary: domain/score/replay.py_

- [x] 5. Score Payload Parser
- [x] 5.1 ScorePayloadParserを実装
  - `domain/score/payload_parser.py`
  - Colon-separated parsing
  - Field type conversion
  - ParsedScore dataclass
  - Unit test: valid payload parsing
  - Unit test: invalid format error handling
  - _Requirements: 5.1, 5.2_
  - _Boundary: domain/score/payload_parser.py_

- [x] 6. Score Validator
- [x] 6.1 ScoreValidatorを実装
  - `domain/score/validator.py`
  - Hit counts validation per ruleset
  - Accuracy calculation (server-side)
  - Grade calculation (server-side)
  - Unit test: osu ruleset validation
  - Unit test: taiko/catch/mania validation
  - Unit test: inconsistent hit counts rejection
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_
  - _Boundary: domain/score/validator.py_

- [x] 7. Repository Interfaces
- [x] 7.1 (P) ScoreRepository Protocolを定義
  - `repositories/interfaces/score_repository.py`
  - `create()`, `exists_by_online_checksum()`, `get_by_id()` methods
  - _Requirements: 6.1, 7.1_
  - _Boundary: repositories/interfaces/_

- [x] 7.2 (P) ScoreSubmissionRepository Protocolを定義
  - `repositories/interfaces/submission_repository.py`
  - `create()`, `get_by_fingerprint()`, `update_state()` methods
  - _Requirements: 6.3, 9.1_
  - _Boundary: repositories/interfaces/_

- [x] 7.3 (P) ReplayRepository Protocolを定義
  - `repositories/interfaces/replay_repository.py`
  - `create()`, `exists_by_checksum()` methods
  - _Requirements: 6.2, 7.3_
  - _Boundary: repositories/interfaces/_

- [x] 8. In-Memory Repository Implementations
- [x] 8.1 (P) InMemoryScoreRepositoryを実装
  - `repositories/memory/score_repository.py`
  - Dict-based storage
  - Unique constraint emulation
  - Unit test: CRUD operations
  - Unit test: duplicate online_checksum rejection
  - _Requirements: 6.1, 7.1_
  - _Boundary: repositories/memory/_

- [x] 8.2 (P) InMemoryScoreSubmissionRepositoryを実装
  - `repositories/memory/submission_repository.py`
  - Dict-based storage
  - Fingerprint uniqueness
  - Unit test: idempotent retrieval
  - _Requirements: 6.3, 9.1_
  - _Boundary: repositories/memory/_

- [x] 8.3 (P) InMemoryReplayRepositoryを実装
  - `repositories/memory/replay_repository.py`
  - Dict-based storage
  - Checksum uniqueness
  - Unit test: duplicate checksum rejection
  - _Requirements: 6.2, 7.3_
  - _Boundary: repositories/memory/_

## Phase 3: Infrastructure Layer (TDD)

- [x] 9. Multipart Parser
- [x] 9.1 MultipartParserを実装
  - `infrastructure/parsers/multipart_parser.py`
  - Duplicate `score` field handling (1st=payload, 2nd=replay)
  - Required fields extraction
  - Optional fields preservation
  - Size limit validation
  - ParsedSubmission dataclass
  - Unit test: valid multipart parsing
  - Unit test: duplicate field order preservation
  - Unit test: size limit rejection
  - Unit test: missing required field error
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_
  - _Boundary: infrastructure/parsers/_

- [x] 10. Score Crypto Service
- [x] 10.1 ScoreCryptoServiceを実装
  - `infrastructure/crypto/score_crypto.py`
  - Key selection (osuver-based)
  - `athena_crypto` Rust moduleをimport
  - Decryption wrapper
  - Checksum validation
  - DecryptedPayload dataclass
  - Unit test: decryption with osuver key
  - Unit test: decryption with legacy key
  - Unit test: decryption failure handling
  - Unit test: checksum mismatch rejection
  - _Requirements: 3.1, 3.2, 3.3, 3.4_
  - _Boundary: infrastructure/crypto/_
  - _Depends: 1.2_

- [x] 11. Score Authorization Service
- [x] 11.1 ScoreAuthorizationServiceを実装
  - `infrastructure/auth/score_authorization.py`
  - Password verification (mock legacy auth service)
  - Active session check (mock Valkey)
  - Payload identity match verification
  - AuthorizationContext dataclass
  - Unit test: valid authorization
  - Unit test: invalid password rejection
  - Unit test: no active session rejection
  - Unit test: payload identity mismatch rejection
  - Unit test: no raw credentials logged
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 11.1_
  - _Boundary: infrastructure/auth/_

- [x] 12. Beatmap Eligibility Service
- [x] 12.1 BeatmapEligibilityServiceを実装
  - `infrastructure/beatmap/eligibility_service.py`
  - Beatmap metadata取得 (mock beatmap mirror)
  - Status check (Ranked/Approved/Loved/Qualified accept)
  - EligibilityResult dataclass
  - Unit test: eligible status acceptance
  - Unit test: ineligible status rejection
  - Unit test: unknown beatmap rejection
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_
  - _Boundary: infrastructure/beatmap/_

## Phase 4: Service Layer (TDD)

- [x] 13. Score Submission Service
- [x] 13.1 ScoreSubmissionServiceを実装
  - `services/score_submission_service.py`
  - Use-case orchestration: decrypt → parse → authorize → validate → persist
  - Submission fingerprint生成
  - Idempotent retry handling
  - SubmissionResult dataclass
  - Unit test (in-memory repos): happy path (valid submission → score created)
  - Unit test: failed play handling
  - Unit test: replay attachment
  - Unit test: online checksum duplicate rejection
  - Unit test: replay checksum duplicate rejection
  - Unit test: submission fingerprint idempotency
  - Unit test: authorization failure → terminal reject
  - Unit test: beatmap ineligibility → terminal reject
  - Unit test: validation failure → terminal reject
  - Unit test: security logging (no raw credentials)
  - _Requirements: 1.1, 4.1, 5.1, 6.1, 6.2, 6.3, 6.4, 7.1, 7.2, 7.3, 7.4, 7.5, 8.1, 9.1, 9.2, 9.3, 9.4, 10.1, 11.1, 11.2, 11.3, 11.4, 11.5, 12.1, 12.2, 12.3, 12.4_
  - _Boundary: services/_
  - _Depends: 5.1, 6.1, 10.1, 11.1, 12.1_

## Phase 5: Repository Layer (SQLAlchemy)

- [ ] 14. Database Schema & SQLAlchemy Repository Implementations
- [x] 14.1 Alembic migrationを作成
  - `scores` table: online_checksum unique constraint
  - `score_submissions` table: fingerprint unique constraint
  - `replays` table: checksum_sha256 unique constraint
  - Indexes: user_id, beatmap_id, submitted_at
  - Migration file生成: `alembic revision --autogenerate`
  - _Requirements: 6.1, 6.2, 6.3, 7.1_
  - _Boundary: Database schema_

- [x] 14.2 (P) SQLAlchemyScoreRepositoryを実装
  - `repositories/sqlalchemy/score_repository.py`
  - SQLAlchemy async operations
  - Unique constraint handling
  - Integration test (real PostgreSQL testcontainer): CRUD operations
  - Integration test: unique constraint violation
  - _Requirements: 6.1, 7.1_
  - _Boundary: repositories/sqlalchemy/_
  - _Depends: 14.1_

- [x] 14.3 (P) SQLAlchemyScoreSubmissionRepositoryを実装
  - `repositories/sqlalchemy/submission_repository.py`
  - SQLAlchemy async operations
  - Fingerprint uniqueness
  - Integration test (real PostgreSQL): idempotent retrieval
  - _Requirements: 6.3, 9.1_
  - _Boundary: repositories/sqlalchemy/_
  - _Depends: 14.1_

- [ ] 14.4 (P) SQLAlchemyReplayRepositoryを実装
  - `repositories/sqlalchemy/replay_repository.py`
  - SQLAlchemy async operations
  - Checksum uniqueness
  - Integration test (real PostgreSQL): duplicate rejection
  - _Requirements: 6.2, 7.3_
  - _Boundary: repositories/sqlalchemy/_
  - _Depends: 14.1_

- [ ] 15. Service Layer Integration Test
- [ ] 15.1 ScoreSubmissionServiceをreal DBでテスト
  - `tests/integration/test_score_submission_integration.py`
  - E2E flow: multipart → decrypt → validate → persist → response
  - Database transaction handling
  - Concurrent submission handling
  - _Requirements: All_
  - _Depends: 13.1, 14.2, 14.3, 14.4_

## Phase 6: Transport Layer

- [ ] 16. Score Submit Endpoint
- [ ] 16.1 ScoreSubmitHandlerを実装
  - `transports/web_legacy/routes/score_submit.py`
  - POST `/web/osu-submit-modular-selector.php` handler
  - Multipart request受信
  - MultipartParserに委譲
  - ScoreSubmissionServiceを呼び出し
  - Response生成 (completed/terminal_reject/retryable)
  - E2E test: POST with real multipart data
  - E2E test: completed response format verification
  - E2E test: terminal reject response format
  - _Requirements: 1.1, 1.2, 2.1, 10.1, 10.2, 10.3, 10.4, 10.5_
  - _Boundary: transports/web_legacy/_
  - _Depends: 9.1, 13.1_

## Phase 7: Final Integration & Edge Cases

- [ ] 17. Playstyle Validation
- [ ] 17.1 Relax/Autopilot rejectionを実装
  - ScoreSubmissionServiceにplaystyle check追加
  - Unit test: RX mod → terminal reject
  - Unit test: AP mod → terminal reject
  - Unit test: vanilla mod → accept
  - _Requirements: 1.3, 1.4_
  - _Boundary: services/_
  - _Depends: 13.1_

- [ ] 18. Security & Privacy Verification
- [ ] 18.1 機密情報loggingをverify
  - Log output検証: password-md5がSHA-256 hashのみ
  - Log output検証: encrypted payloadが出力されない
  - Log output検証: opaque fieldsがSHA-256 hashのみ
  - Failure category logging検証
  - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_
  - _Depends: 16.1_

- [ ] 19. Performance Metrics Setup
- [ ] 19.1 Observability metricsを追加
  - Endpoint latency metrics (P50, P95, P99)
  - Database query latency
  - Decrypt operation latency
  - Beatmap mirror call latency
  - Logging infrastructure integration
  - _Requirements: All (observability)_
  - _Depends: 16.1_
