# Requirements Document

## Introduction

`replay-download-response` は Issue #36 の実装specである。目的は、Stable client が `GET /web/osu-getreplay.php` から取得した replay download response を実際に消費できるようにし、保存済み Replay blob と client-visible download body の違いを曖昧にしないことである。

このspecは、既存の `replay-download-contract` が固定した route、request key、auth field、response branch、body decision blocker を入力として扱う。最初に `target_body_validation_requires_local_raw_blob_artifact` を解消し、success response が `direct_blob_bytes` でよいのか、`assemble_download_body` が必要なのかを決めてから runtime endpoint を実装する。

## Boundary Context

- **In scope**: Primary route `GET /web/osu-getreplay.php`、confirmed query keys `c` / `h` / `m` / `u`、replay download success body strategy、auth failure、hidden score、storage-missing replay、missing replay provisional fallback、focused verification.
- **Out of scope**: `/web/replays/<id>` alias、replay view count、latest activity、self-view、duplicate-view cooldown、score submission replay persistence repair、raw capture / raw replay / complete `.osr` fixture commit、anti-cheat、replay validation policy、spectator replay frame parsing.
- **Adjacent expectations**: `replay-download-contract` owns evidence and blocker language; Issue #37 owns replay view count and latest activity; score submission owns replay upload and persistence unless this work proves stored replay bytes are corrupt.

## Requirements

### Requirement 1: Primary replay download route

**Objective:** Stable client 利用者として、Target Stable Client が使う primary route から replay を取得できることで、reference-only alias に依存せず replay download workflow を進めたい。

#### Acceptance Criteria

1. When Stable client sends `GET /web/osu-getreplay.php`, the Athena Replay Download Endpoint shall handle the request as the primary replay download route.
2. When Stable client sends confirmed query keys `c`, `h`, `m`, and `u`, the Athena Replay Download Endpoint shall interpret those keys as the replay download request contract.
3. If `/web/replays/<id>` is requested, then the Athena Replay Download Response Spec shall not treat that alias as required behavior for Issue #36.
4. If unconfirmed query fields or malformed `c` / `m` values are encountered, then the Athena Replay Download Endpoint shall handle them as documented fallback or blocked behavior without labeling them as target-confirmed contract.

### Requirement 2: Success body strategy gate

**Objective:** Stable compatibility 保守者として、success response body strategy が実装前に決まることで、download は成功しても Stable client が replay を消費できない状態を避けたい。

#### Acceptance Criteria

1. When Issue #36 implementation begins, the Athena Replay Download Response Spec shall require `target_body_validation_requires_local_raw_blob_artifact` to be resolved before success responses are considered complete.
2. When local body validation proves the stored Replay blob bytes are target-client-compatible response bytes, the Athena Replay Download Endpoint shall use `direct_blob_bytes` as the success body strategy.
3. When Replay blob integrity passes but target-client-compatible body validation fails, the Athena Replay Download Endpoint shall use `assemble_download_body` as the success body strategy.
4. If local body validation cannot be completed safely, then the Athena Replay Download Endpoint shall keep success response implementation blocked rather than returning guessed body bytes.
5. The Athena Replay Download Response Spec shall distinguish Replay Download Response Body from the stored Replay blob object.

### Requirement 3: Successful replay download response

**Objective:** Stable client 利用者として、visible score に保存済み replay がある場合に Stable client 互換の response を受け取れることで、download した replay を client workflow で再生したい。

#### Acceptance Criteria

1. When an authenticated request targets a visible score with an available replay body, the Athena Replay Download Endpoint shall return HTTP 200 with target-client-compatible replay download response bytes.
2. When the success response is returned, the Athena Replay Download Endpoint shall include replay download headers consistent with the confirmed success contract.
3. When the success response body is produced, the Athena Replay Download Endpoint shall not expose raw diagnostic metadata, credential values, or storage implementation details in the client-visible response.
4. While replay view count and latest activity are out of scope, the Athena Replay Download Endpoint shall keep success response status, headers, and body independent of those future state-update decisions.

### Requirement 4: Auth and unavailable replay responses

**Objective:** Stable client 利用者として、replay を取得できない場合も互換性のある失敗responseを受け取れることで、client workflow が曖昧な成功として進まないようにしたい。

#### Acceptance Criteria

1. If replay download authentication fails, then the Athena Replay Download Endpoint shall return HTTP 401 with `empty_body`.
2. If the requested score is hidden from replay download, then the Athena Replay Download Endpoint shall return HTTP 404 with `empty_http_exception`.
3. If the requested score has replay metadata but the stored replay object is unavailable, then the Athena Replay Download Endpoint shall return HTTP 404 with `empty_http_exception`.
4. If the requested score has no replay, then the Athena Replay Download Endpoint shall return a provisional HTTP 404 empty fallback and shall label that behavior as provisional rather than target-confirmed.
5. If unavailable replay responses are returned, then the Athena Replay Download Endpoint shall not reveal whether the underlying cause was authorization, score visibility, replay metadata, or storage internals beyond the documented response branch.

### Requirement 5: Privacy and artifact safety

**Objective:** OSS 保守者として、replay download 実装と検証が秘匿情報や raw replay payload を repository に残さないことで、安全に互換性作業を共有したい。

#### Acceptance Criteria

1. When replay download behavior is verified, the Athena Replay Download Response Spec shall keep raw replay bytes, complete `.osr` bytes, raw traffic captures, password values, password hashes, raw query values, and credential values out of repository-managed files.
2. When local-only artifacts are used to resolve body strategy, the Athena Replay Download Response Spec shall record only sanitized metadata or decision state in committed files.
3. If verification output includes credential-like values or raw replay payload bytes, then the Athena Replay Download Response Spec shall treat that output as invalid for commit.
4. The Athena Replay Download Endpoint shall not include secrets, raw credential values, raw query values, or local diagnostic artifact paths in client-visible responses.

### Requirement 6: Verification and implementation readiness

**Objective:** 実装担当者とreviewerとして、#36 の実装完了条件が明確であることで、未確認contractを実装済みと誤認せずにreviewしたい。

#### Acceptance Criteria

1. When requirements, design, and tasks are complete, the Athena Replay Download Response Spec shall identify the selected success body strategy and the evidence state behind that selection.
2. When the endpoint implementation is reviewed, the Athena Replay Download Response Spec shall require focused verification for request parsing, auth failure, hidden score, storage-missing replay, missing replay provisional fallback, and success body strategy.
3. If a branch remains unconfirmed by target or reference evidence, then the Athena Replay Download Response Spec shall require that branch to be marked provisional, blocked, or out of scope.
4. Where Issue #37 behavior is discussed, the Athena Replay Download Response Spec shall state that replay view count and latest activity are adjacent work and not Issue #36 readiness criteria.
