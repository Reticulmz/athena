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
| `/web/replays/<id>` | no | `candidate_only_pending_reference_audit` | `target_client_request_metadata.json` `target_route_contract.alias_route` | Not observed in the supplied Target Stable Client captures. Keep as candidate-only until `lets` reference audit in task 2.2. |

- **Implications**:
  - The earlier `.osr`-as-success-body assumption is rejected.
  - #36 likely needs to return target-client-compatible LZMA replay payload bytes, not a complete `.osr` file, unless additional evidence contradicts this capture.
  - Target build metadata must account for the fact that exact build may be `not observed in replay download request`; such captures remain usable when the observation status is explicit.

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

- Target client capture が取得できない — #36 を blocked のままにし、docs に `未確認` と blocker を残す。
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
