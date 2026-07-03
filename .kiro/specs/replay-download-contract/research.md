# Research & Design Decisions

## Summary

- **Feature**: `replay-download-contract`
- **Discovery Scope**: Extension
- **Key Findings**:
  - Replay download は Athena では未実装で、docs 上も `/web/osu-getreplay.php` の auth、request params、success bytes、failure branch が `unconfirmed` である。
  - Score submission は multipart の 2 個目の `score` field を `replay_data` としてそのまま blob storage に保存しており、本家 Bancho の replay download body と同じ payload shape かは確認が必要である。
  - 既存の `athena_cli.stable_verification` は fixture / evidence / report-safe diagnostic の置き場として利用できるが、replay download surface と blob diagnostic は未実装である。

## Research Log

### Replay download 現状

- **Context**: #35 が固定すべき route / auth / response contract を確認するため。
- **Sources Consulted**:
  - `docs/stable-compatibility-guide.md` Replay Download
  - `docs/stable-compatibility-matrix.md` Replay download rows
  - GitHub Issue #35 body
- **Findings**:
  - Endpoint candidates は `/web/osu-getreplay.php` と `lets` 由来の `/web/replays/<id>`。
  - Athena の current behavior は missing。
  - `deck` は missing / hidden / storage-missing replays で 404 を返す reference として docs に記録済み。
  - Auth method、request params、success response、auth failure response、malformed request response は未確認。
- **Implications**:
  - Route path と auth field presence は Target Stable Client traffic capture を必須 evidence にする。
  - Response branch は target traffic または reference-backed sanitized fixture で固定する。

### Replay blob 保存経路

- **Context**: Blob を `.osr` に rename しても読めないという観測の原因を分けるため。
- **Sources Consulted**:
  - `src/osu_server/infrastructure/parsers/multipart_parser.py`
  - `src/osu_server/services/commands/scores/process_submission.py`
  - `src/osu_server/services/commands/storage/blob_storage.py`
  - `src/osu_server/infrastructure/storage/local.py`
- **Findings**:
  - Multipart parser は 1 個目の `score` field を encrypted payload、2 個目を `replay_data` として扱う。
  - `ProcessScoreSubmissionUseCase` は `replay_data` の SHA-256 を計算し、bytes をそのまま `BlobStorageService.put_bytes()` へ渡す。
  - Blob storage は content-addressed key で保存し、`.osr` wrapper 生成や extension 付与はしない。
- **Implications**:
  - Replay Blob Integrity Check と target-client-compatible body check は別物として扱う。
  - #35 は Replay Download Body Assembly Decision を成果物に含め、#36 が raw blob bytes を返すべきか body assembly を実装すべきかを明示する。

### Replay Blob Diagnostic Procedure

- **Context**: Replay blob の保存状態と download body format mismatch を混同しないため。
- **Implementation Evidence**:
  - `athena_cli.stable_verification.replay_download.diagnose_replay_blob`
  - `tests/unit/athena_cli/stable_verification/test_replay_download.py`
- **Findings**:
  - Score existence、replay attachment existence、blob metadata existence、storage object existence、metadata size/hash と observed size/hash の照合を read-only protocol として固定した。
  - Diagnostic result は `integrity_pass`、`missing_score`、`missing_replay`、`missing_blob_metadata`、`missing_storage_object`、`storage_integrity_failure` を区別する。
  - Unit tests は integrity pass、missing replay、missing blob metadata、missing storage object、hash/size mismatch を確認している。
- **Redaction**:
  - Diagnostic summary は raw replay bytes、credential-like values、storage key、digest を出力しない。
  - `ReplayBlobMetadataRecord` と `ReplayBlobDiagnosticResult` は digest と storage key を `repr` から除外する。
- **Remaining Work**:
  - Local target score に対する dry-run result と target-client-compatible body validation は 3.2 の body decision で扱う。

### Replay Download Body Assembly Decision

- **Context**: Target success body は storage blob object と同一とは限らず、manual `.osr` rename failure だけでは storage corruption と判断できないため。
- **Implementation Evidence**:
  - `tests/fixtures/stable_compatibility/replay_download/body_assembly_decision.json`
  - `athena_cli.stable_verification.replay_download.build_replay_download_body_decision`
  - `tests/unit/athena_cli/stable_verification/test_replay_download.py`
- **Findings**:
  - Official target success response body kind は `lzma_compressed_replay_payload` で、complete `.osr` bytes でも ZIP archive でもない。
  - Stored blob bytes の target-body compatibility は raw blob artifact を repository に保存せず local-only で検証する必要があるため、current decision は `download_body_strategy=blocked` とする。
  - Blob integrity が pass し、target body compatibility が fail した場合は `download_body_format_mismatch` として扱い、#36 は `assemble_download_body` を実装する。
- **Handoff Impact**:
  - #36 は success 200 body を direct blob bytes として実装開始してはいけない。
  - #36 の success branch blocker は `target_body_validation_requires_local_raw_blob_artifact` である。

### User-provided replay download captures

- **Context**: Target route/auth と本家 Bancho success response body の shape を確認するため。
- **Sources Consulted**:
  - User-provided local capture artifact `flows (5)` (raw artifact not committed)
  - User-provided official Bancho capture artifact `flows (6)` (raw artifact not committed)
- **Findings**:
  - Local capture: `GET /web/osu-getreplay.php` with query keys `c`, `h`, `m`, `u`; auth-like fields are `h` and `u`; response is 404 with `text/plain; charset=utf-8` and 9-byte body.
  - Official Bancho capture: `GET /web/osu-getreplay.php` with query keys `c`, `h`, `m`, `u`; auth-like fields are `h` and `u`; response is 200 with `content-type: zip`, `content-disposition` present, and 90584-byte body.
  - Official 200 body is not a ZIP archive and does not parse as a complete `.osr` file. It decompresses as LZMA to replay-frame text-like payload, so the replay download response body appears to be LZMA-compressed replay payload rather than complete `.osr` container bytes.
  - The replay request User-Agent is `osu!`; exact client build and `osuver` are not visible in the replay download request.
  - Sanitized fixture metadata was recorded under `tests/fixtures/stable_compatibility/replay_download/`. The fixture uses only method, path, query key names, auth-like field names, observed header names, response status, body kind, byte size, and observation notes. Raw query values, raw body bytes, and safe-body hashes are not committed.
  - Header names were extracted by safe key-name scan rather than full raw-flow publication, so the fixture marks header completeness explicitly instead of implying that raw capture bytes are present in the repository.
- **Target Route Fixture Status**:

| Route | Target client traffic observed | Classification | Evidence fixture | Notes |
| --- | --- | --- | --- | --- |
| `/web/osu-getreplay.php` | yes | `primary_target_client_route` | `target_client_request_metadata.json` captures `local_athena_stable_replay_download_404` and `official_bancho_stable_replay_download_200` | Method `GET`, query keys `c`, `h`, `m`, `u`, and auth-like fields `h`, `u` are recorded without raw values. |
| `/web/replays/<id>` | no | `candidate_only_reference_backed` | `target_client_request_metadata.json` `target_route_contract.alias_route`; `reference_responses.json` `lets_replay_alias_success` and `lets_replay_alias_missing` | `lets` confirms the alias shape, but supplied Target Stable Client captures did not observe it. Keep candidate-only, not current target-client required. |

### Reference implementation replay download audit

- **Context**: Response branches can use target traffic or `bancho.py` / `deck` / `lets` reference evidence, while current target-client required route still needs target traffic.
- **Sources Consulted**:
  - `osuAkatsuki/bancho.py` commit `358d23a0d906ee08de96bafd9ca207071b061b43`, files `app/api/domains/osu.py`, `app/services/replays.py`
  - `osuTitanic/deck` commit `1534cd1e4068f0ed6a2d2245ef271131319e654c`, files `app/routes/__init__.py`, `app/routes/web/replays.py`
  - `osuripple/lets` commit `98e9e07faa48398fbccf17251650011e36bdf6e4`, files `lets.py`, `handlers/getReplayHandler.py`, `handlers/getFullReplayHandler.py`, `helpers/replayHelper.py`
- **Audit Summary**:

| Source | Route | Branch | Status | Header keys | Body kind | Contract status | Unresolved reason |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `bancho.py` | `/web/osu-getreplay.php` | success | 200 | not captured | `file_response_osr_path` | `reference_only_unresolved` | FileResponse runtime headers and full `.osr` body compatibility were not captured. |
| `bancho.py` | `/web/osu-getreplay.php` | auth_failure | 401 | not captured | `empty_body` | `confirmed_reference` | none |
| `bancho.py` | `/web/osu-getreplay.php` | missing_replay | 404 | not captured | `empty_body` | `confirmed_reference` | none |
| `deck` | `/web/osu-getreplay.php` | success | 200 | not captured | `raw_replay_payload` | `reference_only_unresolved` | Auth is optional in the reference and target body compatibility still needs body decision. |
| `deck` | `/web/osu-getreplay.php` | missing_replay | 404 | not captured | `empty_http_exception` | `confirmed_reference` | none |
| `deck` | `/web/osu-getreplay.php` | hidden_score | 404 | not captured | `empty_http_exception` | `confirmed_reference` | none |
| `deck` | `/web/osu-getreplay.php` | storage_missing | 404 | not captured | `empty_http_exception` | `confirmed_reference` | none |
| `lets` | `/web/osu-getreplay.php` | missing_replay | 200 | not captured | `empty_body` | `conflicting_reference_unresolved` | Differs from `bancho.py` and `deck` 404 behavior. |
| `lets` | `/web/replays/<id>` | alias success | 200 | `content-description`, `content-disposition`, `content-length`, `content-type` | `complete_osr_file` | `alias_candidate_reference` | none |
| `lets` | `/web/replays/<id>` | alias missing | 404 | not captured | `plain_text_replay_not_found` | `alias_candidate_reference` | none |

- **Implications**:
  - `/web/osu-getreplay.php` remains the target-client-confirmed primary route.
  - `/web/replays/<id>` is a reference-backed alias candidate only; it is not current target-client required because target traffic did not observe it.
  - Missing / hidden / storage-missing 404 is supported by `deck`; `lets` primary-route missing behavior disagrees and remains unresolved until task 2.3 chooses branch policy.

- **Capture Implications**:
  - The earlier `.osr`-as-success-body assumption is rejected.
  - #36 likely needs to return target-client-compatible LZMA replay payload bytes, not a complete `.osr` file, unless additional evidence contradicts this capture.
  - Target build metadata must account for the fact that exact build may be `not observed in replay download request`; such captures remain usable when the observation status is explicit.

### Replay download response contract table

- **Context**: #36 must distinguish implementation-ready response branches from unresolved branches after target traffic and reference audit.
- **Fixture**: `tests/fixtures/stable_compatibility/replay_download/response_contract.json`
- **Contract Summary**:

| Branch | Status label | Readiness for #36 | Selected status | Body kind | Byte size | Safe hash | Evidence | Blocker |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| success | unconfirmed | blocked | 200 | `lzma_compressed_replay_payload` | 90584 | not committed | target official Bancho capture; `bancho.py`; `deck` | `target_body_validation_requires_local_raw_blob_artifact` |
| auth_failure | confirmed | implementation-ready | 401 | `empty_body` | 0 | not committed | `bancho.py` | none |
| missing_replay | unconfirmed | unresolved | none | none | none | not committed | `bancho.py`; `deck`; `lets` | `conflicting_reference_evidence` |
| hidden_score | confirmed | implementation-ready | 404 | `empty_http_exception` | unknown | not committed | `deck` | none |
| storage_missing | confirmed | implementation-ready | 404 | `empty_http_exception` | unknown | not committed | `deck` | none |
| missing_score_id | unconfirmed | unresolved | none | none | none | none | none | `no_target_or_reference_evidence` |
| malformed_score_id | unconfirmed | unresolved | none | none | none | none | none | `no_target_or_reference_evidence` |
| missing_mode | unconfirmed | unresolved | none | none | none | none | none | `no_target_or_reference_evidence` |
| malformed_mode | unconfirmed | unresolved | none | none | none | none | none | `no_target_or_reference_evidence` |
| unknown_field | unconfirmed | unresolved | none | none | none | none | none | `no_target_or_reference_evidence` |

- **Implications**:
  - #36 may implement auth failure and reference-backed hidden/storage-missing branches from this contract.
  - Missing replay remains unresolved because `bancho.py`/`deck` 404 evidence conflicts with `lets` empty 200 evidence.
  - #36 must not treat success as ready while blocker `target_body_validation_requires_local_raw_blob_artifact` remains.
  - #36 must not invent malformed request behavior; missing/malformed score id, missing/malformed mode, and unknown field remain unconfirmed.

### Fixture と秘匿情報

- **Context**: OSS repository に replay download evidence を安全に残す形式を決めるため。
- **Sources Consulted**:
  - `tests/fixtures/stable_compatibility/score_submit/request_metadata.json`
  - `.kiro/specs/stable-compatibility-verification/design.md`
  - `src/athena_cli/stable_verification/models.py`
- **Findings**:
  - Stable verification は request metadata と response fixtures を分け、raw secret を report しない方針を持つ。
  - Existing `SecretProbeInput` は password、password hash、session token、raw replay、credential fields を repr から隠す。
- **Implications**:
  - Replay download fixture は raw query values、password hash、session token、raw replay bytes、complete `.osr` bytes を含めない。
  - Sanitized fixture schema は method、path、query key set、auth field presence、target build metadata、response status/header keys、body kind、safe hash、byte size に限定する。

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
| --- | --- | --- | --- | --- |
| Docs-only audit | docs と matrix だけ更新する | 最小変更 | fixture schema と leak guard が弱く、後続実装で再解釈されやすい | 不採用 |
| Stable verification extension | `athena_cli.stable_verification` に replay download evidence / fixture verifier / diagnostic を追加する | 既存 evidence model と secret guard に乗れる | #35 の範囲で CLI code が増える | 採用 |
| Production query service first | #36 用 query service を先に実装する | 後続実装へ直結 | #35 が endpoint 実装準備に寄りすぎる | 不採用 |

## Design Decisions

### Decision: route と auth は target traffic 必須にする

- **Context**: `/web/osu-getreplay.php` と `/web/replays/<id>` のどちらを target client が叩くか、auth field を送るかが未確認。
- **Alternatives Considered**:
  1. Reference implementation だけで決める。
  2. Target traffic を route/auth に必須とし、response branch は reference も許可する。
- **Selected Approach**: Route path、method、query key set、auth field presence は Target Stable Client traffic capture 必須にする。
- **Rationale**: Route/auth は client build 依存で、reference only だと壊しやすい。
- **Trade-offs**: #35 が real-client capture に依存するため、capture できない場合は #36 に進めない。
- **Follow-up**: Capture fixture には target build metadata を必須にする。

### Decision: success body は target-client-compatible replay download payload とする

- **Context**: 保存済み blob を `.osr` に rename しても読めない観測があり、本家 Bancho capture の 200 body も complete `.osr` ではなく LZMA-compressed replay payload として観測された。
- **Alternatives Considered**:
  1. Blob bytes をそのまま success body と仮定する。
  2. Complete `.osr` bytes を success body とする。
  3. Target client が replay download response として消費する payload bytes を success body とする。
- **Selected Approach**: Replay Download Response Body は storage blob object ではなく target-client-compatible replay download response bytes と定義する。
- **Rationale**: User-visible contract は storage object や manual `.osr` import ではなく in-client replay download workflow である。
- **Trade-offs**: Manual rename-to-`.osr` は validation method として不十分になるため、body kind と target-client compatibility を別 metadata として記録する。
- **Follow-up**: Raw replay bytes は repo に保存せず、sanitized metadata だけを残す。

### Decision: sanitized fixture だけを commit する

- **Context**: OSS repository で traffic evidence を共有する必要がある。
- **Alternatives Considered**:
  1. Raw capture / raw replay を fixture として保存する。
  2. Sanitized metadata のみ保存する。
- **Selected Approach**: Method、path、query keys、auth field categories、response status/header keys、body kind、size、safe hash だけを commit する。
- **Rationale**: Password hash、session token、raw replay は secret / sensitive artifact であり、OSS repo に置けない。
- **Trade-offs**: Complete binary replay regression はローカル検証に残り、repo fixture は metadata-level verification になる。
- **Follow-up**: Fixture validator で forbidden keys / value patterns を検出する。

## Risks & Mitigations

- Target client capture が取得できない — #36 を blocked のままにし、docs に `unconfirmed` と blocker を残す。
- Reference implementations disagree — `bancho.py`、`deck`、`lets` の差分を matrix に記録し、target traffic または明示 rationale なしに contract を固定しない。
- Sanitized fixture に credential-like value が混入する — fixture validator と tests で forbidden keys / raw value patterns を検出する。
- Blob integrity 診断が raw replay bytes を出す — diagnostic output schema を hash / size / existence のみに制限する。

## References

- `docs/stable-compatibility-guide.md` Replay Download
- `docs/stable-compatibility-matrix.md` Stable HTTP Endpoint Coverage
- `src/osu_server/infrastructure/parsers/multipart_parser.py`
- `src/osu_server/services/commands/scores/process_submission.py`
- `src/osu_server/services/commands/storage/blob_storage.py`
- `src/athena_cli/stable_verification/models.py`
- `tests/fixtures/stable_compatibility/replay_download/target_client_request_metadata.json`
- `tests/fixtures/stable_compatibility/replay_download/target_client_response_metadata.json`
- `tests/fixtures/stable_compatibility/replay_download/body_assembly_decision.json`
