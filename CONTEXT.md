# Athena Domain Glossary

## Identity and Authorization Context

### Role
A named authorization bundle assigned to a user. A role grants server-side privileges and is not itself exposed as a stable client permission.
_Avoid_: Permission group, client role

### Privilege
A server-side authorization capability used by Athena to permit protected operations. Privileges are the source of truth for internal authorization decisions.
_Avoid_: Permission, client permission

### Supporter Entitlement
User に付与される Supporter 特典の有効状態。有効期間を持ち、期限切れの entitlement は active と扱わない。Payment、subscription、stable client compatibility flag そのものではなく、community perks や Web display perks の入力として扱う。
_Avoid_: Supporter role, Stripe subscription, payment record, osu!direct access

### Email Verification
User が登録済み email address を操作できることの確認。Login authentication とは別の durable account state であり、Verified play access や `Privileges.VERIFIED` の入力として扱う。
_Avoid_: Login authentication, password check, supporter verification

### Email Verification Code
Email Verification を完了するために User が BanchoBot へ提示する8文字の英数字 code。紛らわしい文字を避け、表示は大文字に統一し、入力時は大小文字を区別せず、最新の有効 code だけを受け付ける。一時 credential として TTL 付き state に置き、durable account state の source of truth にはしない。
_Avoid_: Password, login token, supporter code

### Email Verification Link
Email Verification を WebUI で完了するための one-time link。Email Verification Code とは別の長い token を使い、成功時は同じ Email Verification を完了させて active session authorization refresh を要求する。
_Avoid_: BanchoBot code, reusable login link, password reset link

### Limited Bancho Session
Email Verification が未完了の User に与える制限付き stable session。BanchoBot verification guidance と verification command だけを許可し、play access、public chat、score submission、osu!direct Access、beatmap warmup には使わない。
_Avoid_: Full login, guest session, unverified play access

### Verified Play Access
Email Verification 完了後に User が stable gameplay workflows を利用できる状態。`Privileges.VERIFIED` は Role ではなく Email Verification から派生し、session authorization refresh によって active session へ反映され、stable client の再ログインを要求しない。
_Avoid_: Login success, supporter access, unrestricted flag

### Limited Session Packet Gate
Limited Bancho Session で受け取った gameplay-capable packet を通常 side effect に流さないための gate。`STATUS_CHANGE` は decode しても presence broadcast、gameplay state update、beatmap warmup を行わない。
_Avoid_: Packet drop as authentication, hidden play access, warmup trigger

### Bancho Client Permission
A stable client-visible compatibility flag derived for Bancho login and presence packets. The Supporter flag may be emitted as an osu!direct compatibility unlock and does not prove that the user has a Supporter Entitlement.
_Avoid_: Privilege, internal permission, ClientPermissions

### Stable Presence Roster
Stable client が user id と username を解決するために受け取る client-visible な online identity 集合。Login 時の snapshot と接続状態の変化に追随し、Active session と明示的な system presence を入力にするが、Friend Relationship や durable user list の source of truth ではない。
_Avoid_: Friend list, all users list, session store

### osu!direct Access
Stable client が Athena 経由で beatmap search や download を利用できる compatibility feature。Client 側の unlock には Bancho Client Permission の Supporter flag が必要だが、Server policy によりログイン成功ユーザーへ開放される機能であり、Supporter Entitlement の有無を意味しない。
_Avoid_: Paid Supporter perk, billing entitlement, supporter-only access

### Server Policy
Athena instance 全体に適用される operator-controlled behavior setting。User entitlement ではなく、self-host instance の運用方針を表す。
_Avoid_: User preference, billing entitlement, role permission

### Session Authorization Snapshot
A point-in-time authorization view for an active session, containing the user's current privileges and role membership. It is refreshed from role state and then used by authorization-sensitive actions.
_Avoid_: Session permissions, cached roles

### Password Safety Check
A synchronous identity gate that rejects passwords disallowed by Athena policy or known compromised-password evidence before account creation or password change succeeds.
_Avoid_: Post-registration password audit, HIBP as domain term

### Self-Service Password Change
A password change requested by an authenticated user for their own identity. It requires current-password proof and the new password must pass the Password Safety Check.
_Avoid_: Password reset, admin password change

### Administrative Password Reset
A password reset requested by an authorized operator or development tool for another user's identity. It does not require the user's current password, but it must be protected by an operator authorization boundary.
_Avoid_: Self-service password change, public password update

### Friend Relationship
User が別の friendable user identity を friend として追加している片方向の social relationship。Target の online state とは独立して存在し、Stable friends list と Friends Leaderboard Eligible Set の friend target 部分の source of truth になる。
_Avoid_: Mutual friend, follower, symmetric friendship

### Friendable User Identity
Friend Relationship の target になれる user identity。通常 User と明示的に friend 追加可能な system user を含むが、自動 friend 追加を意味しない。
_Avoid_: Online user, all system users, implicit friend

### Friend-Only DM
User が friend 以外の player-originated private message を拒否する social privacy setting。受信者が有効にしている場合、受信者が送信者を friend に追加しているときだけ private message を受け付け、system response はこの制限の対象にしない。
_Avoid_: Block list, mutual friend requirement, global DM disable

### ModCombination
A canonical score mod value object. Stable bitmasks, lazer payloads, and first-party API payloads are converted into ModCombination before reaching score use-cases, while persistence may store the canonical bitmask integer.
_Avoid_: Raw mods int at use-case boundary, stable bitmask as domain model

## Web Surface Context

### Athena Web App
Athena が公式に提供する first-party web surface。Public、User、Admin、Ops workflows を統合して扱うが、authorization や domain state の source of truth ではない。
_Avoid_: Admin panel, separate WebUI, external frontend

### Public API
Athena 外部の client や integration が利用できる公開 API surface。Documented contract と versioning の対象であり、Athena Web App 専用の都合を混ぜない。
_Avoid_: Web App API, internal route, admin endpoint

### Public API Version
Public API contract の破壊的変更境界。URL path で表し、同一 version 内では additive change を基本にする。
_Avoid_: Feature flag, API Token Scope, Web App route

### Public API Deprecation
Public API version または endpoint を将来削除・置換するための移行状態。外部 integration が移行できる期間と終了日を持ち、即時削除の同義ではない。
_Avoid_: Breaking change, feature flag, internal cleanup

### Web App API
Athena Web App が利用する first-party API surface。外部互換性の保証対象ではないが、browser から観測・再実行される前提で扱い、隠されていることを security boundary にしない。
_Avoid_: Hidden API, private security boundary, public API

### Admin/Ops API
Athena の管理・運用 workflows に使う privileged API surface。Public API や通常 User workflow とは別の authorization、audit、operator intent を要求する。
_Avoid_: Public API, normal user endpoint, hidden admin panel

### Integration
Athena 外部から Public API を利用する Bot、外部 tool、automation などの first-class actor。User とは別の責任主体であり、API Token Owner、audit、rate limit、停止・移譲の単位になり得る。
_Avoid_: API token label, User alias, request IP

### Integration Status
Integration 全体の利用可否を表す状態。`disabled` の Integration は、その Integration-owned API Token が個別に active でも Public API authentication で拒否される。
_Avoid_: API Token status, membership level, rate limit state

### Integration Disable Source
Integration が disabled になった理由の分類。Owner による自主停止と admin/operator による停止を区別し、再有効化条件、audit、UI 表示の判断材料にする。
_Avoid_: API Token status, deletion reason, rate limit state

### Integration Membership Level
User が Integration を管理する権限段階。初期は `owner` と `maintainer` の2段階とし、User の Role や Privilege とは別の Integration-local authority として扱う。
_Avoid_: Role, Privilege, API Token Scope

### Integration Sensitive Operation
Integration の外部 automation 権限や管理主体に影響する操作。削除、移譲、membership 変更、API token 発行・revoke を含み、通常の Integration 利用とは別の security-sensitive workflow として扱う。
_Avoid_: Normal API request, integration usage, public API read

### Web App Session
Athena Web App 上の authenticated browser session。Stable Bancho Session や API token とは別の user-facing session であり、Web App API の authorization input になるが、durable user state や audit record の source of truth ではない。
_Avoid_: Stable session, OAuth token, API key

### API Token
User または integration が Public API access に使う long-lived credential。Web App API の authentication には使わない。Public API では `Authorization: Bearer` で提示し、query parameter では受け付けない。Raw token は発行時に一度だけ表示し、Athena は token hash、display prefix、key id、scope、expiration、usage metadata だけを durable state として保持する。
_Avoid_: Web App Session, password, raw bearer token storage

### API Token Display Prefix
API Token を UI や管理画面で人間が識別するための短い non-secret prefix。Authentication lookup の安定性を担わず、単独では authentication proof にならない。
_Avoid_: Raw token, token secret, lookup key

### API Token Key ID
API Token authentication で候補 token record を絞り込むための non-secret identifier。Raw token から取り出せるが、単独では authentication proof にならず、最終的な authentication は token hash verification で成立する。
_Avoid_: Raw token, token secret, display prefix

### Raw API Token Format
User または integration に発行時だけ表示される API Token の文字列表現。Token type、API Token Key ID、secret を含む構造化文字列とし、Athena は raw value を durable state として保存しない。
_Avoid_: Stored credential, display prefix only, opaque database id

### API Token Secret
Raw API Token に含まれる authentication secret。Server が CSPRNG で生成する 256-bit 以上の URL-safe random value であり、User や integration が指定する値ではない。
_Avoid_: User password, display prefix, key id

### API Token Secret Disclosure
API Token Secret を発行者へ一度だけ開示する操作。Safe retry や Idempotency replay で再実行されるものではなく、失われた場合は token rotation で扱う。
_Avoid_: Raw token redisplay, idempotency replay, token metadata

### API Token Hash
API Token authentication のために保存する secret verification value。Password hash ではなく、server-side key または pepper を使った keyed hash / HMAC として扱い、raw token や raw secret は保存しない。
_Avoid_: Password hash, raw token, display prefix

### API Token Hash Key Version
API Token Hash の検証に使う server-side key または pepper の version。Token record に `hash_key_version` として保存し、将来の HMAC key rotation 時にどの key で検証するかを判断する。
_Avoid_: API Token Key ID, API Token Scope, raw secret

### API Token Hash Key Ring
API Token Hash の生成・検証に使う server-side key または pepper の集合。Database には保存せず、AppConfig、environment variable、secret manager などの runtime secret source から供給する。
_Avoid_: Database credential record, API Token Hash, raw token

### API Token Hash Key Rotation
API Token Hash Key Ring の active key を切り替える運用。新規 API Token 発行には active key を使い、既存 API Token は token record の `hash_key_version` に対応する key で検証し続ける。
_Avoid_: Immediate token revocation, password reset, API Token Rotation

### API Token Hash Key Retirement
古い API Token Hash key を verification 対象から外すための移行状態。対象 `hash_key_version` の token は期限付きの forced rotation 対象になり、期限後は Public API authentication で拒否される。
_Avoid_: Immediate token revocation, normal expiration, API Token Rotation

### API Token Owner
API Token の責任主体。User または Integration を表現でき、初期運用で User-owned token だけを有効にしても、token identity を User 固定の概念として扱わない。
_Avoid_: Token presenter, request IP, Role

### API Token Expiration
API Token が Public API authentication に使える期限。期限切れ token は revoke 済み token と同様に authentication で拒否され、長期 credential を永久に有効なものとして扱わない。
_Avoid_: Token revocation, session timeout, Integration disabled state

### API Token Rotation
既存 API Token を置き換える運用。Raw token の再表示や既存 record の再生成ではなく、新しい API Token を発行し、旧 API Token を明示 revoke することで扱う。
_Avoid_: Raw token redisplay, in-place token regeneration, password reset

### API Token Usage Metadata
API Token の利用状況を表示・監査補助するための metadata。`last_used_at` などを含むが、authentication や authorization の source of truth ではなく、短い反映遅延を許容する。
_Avoid_: Token validity, Security/Audit Event, rate limit counter

### API Token Validity Failure
API Token 自体が Public API authentication に使えない failure。Public API では authentication failure として扱い、invalid、expired、revoked、retired hash key などの reason は permission failure とは別の error code で区別する。
_Avoid_: API Token Scope failure, rate limit, CSRF failure

### API Token Permission Failure
API Token は valid だが requested operation に必要な scope を持たない authorization failure。Public API error code では `insufficient_scope` として扱い、invalid / expired / revoked token と混同しない。
_Avoid_: Invalid token, expired token, revoked token

### API Token Scope
API Token に許可する API access の範囲。初期は `read`、`write`、`admin` の粗い scope から始め、公開 API や運用 workflow が固まってから必要に応じて細分化する。
_Avoid_: Role, Privilege, endpoint-specific permission

### Public API Rate Limit
Public API request の利用量を制御する abuse protection。API Token、owner user/integration、request IP の複数軸で評価し、単一の identity signal だけに依存しない。
_Avoid_: Authorization, API Token Scope, Web App CSRF Gate

### Public API Rate Limit Failure
Public API request が許容された利用量を超えた failure。Token validity failure や permission failure ではなく、外部 integration が backoff して再試行すべき throttling として扱う。
_Avoid_: API Token revocation, insufficient scope, authentication failure

### Public API Error Response
Public API failure を integration が安定して判定するための machine-readable response。HTTP status に加えて error code と request_id を含み、human-readable message は補助情報として扱う。
_Avoid_: Web App validation message, application log, exception text

### Public API Idempotency
Authenticated actor による state-changing Public API request を外部 integration が安全に retry するための重複防止 contract。同じ mutation intent が複数回送られても、二重の side effect を作らないことを目的にする。
_Avoid_: Request ID, CSRF token, rate limit

### Public API Idempotency Replay
完了済みの Public API Idempotency Record に対して同じ mutation intent が再送された状態。新しい side effect を作らず、記録済み outcome を再利用する。
_Avoid_: New mutation execution, idempotency conflict, in-progress retry

### Public API Replay Header
Public API Idempotency Replay で記録済み outcome の一部として再利用できる response header。Mutation result の contract に属する header だけを対象にし、request context に属する値は含めない。
_Avoid_: Request-specific header, hop-by-hop header, request id

### Public API Idempotency Outcome
Public API Idempotency Record に保存される retry-stable な結果。成功した mutation と、同じ mutation intent なら再送時も同じ caller-side rejection と見なせる失敗を含む。Server-side transient failure や timeout は final outcome として扱わない。
_Avoid_: Transient server failure, timeout, raw exception

### Public API Idempotency Conflict
同じ Idempotency Key が異なる mutation intent に再利用された状態。安全な retry ではなく caller 側の key reuse accident として扱う。
_Avoid_: Retried request, rate limit, duplicate side effect

### Public API Idempotency In-Progress
同じ Idempotency Key と同じ request fingerprint の mutation がまだ outcome 確定前に再送された状態。Completed retry の replay ではなく、caller に後続 retry を促す transient state として扱う。
_Avoid_: Idempotency conflict, completed retry, rate limit

### Public API Request Fingerprint
Public API Idempotency が同じ mutation intent かを比較するための non-secret digest。Raw request body や secret payload ではなく、正規化された request intent から導出する。
_Avoid_: Raw request body, API token, audit payload

### Public API Idempotency Record
Public API Idempotency のために Idempotency Key、mutation intent、outcome を結びつける durable record。Safe retry に同じ outcome を返し、異なる intent の再利用を conflict として判定するための source of truth になる。
_Avoid_: Rate limit counter, request log, transient cache

### Public API Idempotency Record Retention
Public API Idempotency Record が retry / deduplication guarantee の対象として保持される期間。Retention 期限を過ぎた record は pruning 対象になり、その後の同じ key は過去 request の deduplication guarantee を持たない。
_Avoid_: Permanent audit retention, rate limit window, API token expiration

### Web App CSRF Gate
Web App Session cookie を使う state-changing Web App API request が、Athena Web App から発生した user intent を伴うことを確認する security gate。Web App Session に紐づく token を要求し、SameSite cookie の挙動だけを source of truth にしない。
_Avoid_: SameSite-only protection, hidden route protection, authorization check

### Web App Sudo Mode
Web App Session が短時間だけ recent authentication proof を持つ状態。Password/email 変更、2FA 設定、moderation mutation、Admin/Ops mutation、Billing 操作、API token 発行・削除などの sensitive operation に使い、通常の閲覧や低リスク profile edit には要求しない。
_Avoid_: Always re-login, CSRF check, normal authorization

### Operator Intent Confirmation
破壊的または高影響な moderation / Admin / Ops operation について、operator が対象と操作内容を意図していることを追加確認する gate。Web App Sudo Mode、CSRF check、通常 authorization の代わりにはしない。
_Avoid_: Re-authentication, CSRF check, privilege check

### Security/Audit Event
Security-sensitive workflow や operator action の durable record。Actor、target、operation、reason、request/session context、outcome を後から追跡するための記録であり、成功した操作だけでなく権限不足、Web App Sudo Mode 不足、CSRF failure、Operator Intent Confirmation failure などの失敗した試行も扱う。Retention policy の対象であり、永久保存の同義ではない。Secret、raw token、password、支払いカード情報、payload 全文は保存しない。通常の application log や metrics の代わりにはしない。
_Avoid_: Application log, debug log, metrics event

## Event Boundary Context

### Local Event
同一 process 内で完結する一時的な通知。外部 replica や worker が受け取る必要はなく、失われても durable state の source of truth は壊れない。
_Avoid_: EventBus event, distributed event

Production-critical workflow の source of truth にはしない。

### Distributed Event
複数 process や複数 runtime family に届ける必要がある一時的な通知。通知の source of truth ではなく、受信者が現在状態を再取得するきっかけとして扱う。
_Avoid_: durable work, task result

DB-backed event log ではなく、non-durable な通知として扱う。

### Disconnect Notification
User が active session から離れたことを他 runtime に知らせる Distributed Event。Presence や channel membership の source of truth ではなく、miss しても TTL や heartbeat により最終的に回復する。
_Avoid_: presence truth, membership cleanup guarantee

### Durable Work
失われると user-visible state や永続 state が欠落する作業単位。未処理 work の source of truth を持ち、retry や重複実行に耐える前提で扱う。
_Avoid_: pub/sub notification, fire-and-forget event

Queue は実行 signal であり、production-critical work の source of truth ではない。
Production-critical Durable Work は DB-backed work item や state machine を source of truth にする。

### Chat Persistence Work
受け付けた chat message を chat history に反映する Durable Work。Realtime delivery とは別の結果であり、retry や重複実行でも同じ履歴状態へ収束する。
_Avoid_: chat event, pub/sub message, listener side effect

## Score Submission Context

### Stable Surface
Athena が stable client に対して公開している外部観測可能な endpoint、packet flow、response contract の集合。内部 package や test suite の構造ではなく、stable client から見える互換対象を指す。
_Avoid_: Stable transport package, test scope, implementation module

---

### Score Submission
Client からの score submit request を記録する entity。Network error や processing delay による retry を検出し、idempotent response を保証する。

- **Fingerprint**: Submission の canonical identifier。User ID + beatmap checksum + submitted timestamp + request hash で構成。Global unique constraint。
- **State**: `received` → `processing` → `completed` / `terminal_rejected`
- **Result Snapshot**: Completed submission の response data。Retry 時に同じ response を再生成するために保存。

**関係性**:
- 1つの Score Submission は 0 または 1 つの Score を生成する
- Validation に失敗した submission は score を生成せず、failure category だけ記録する
- Performance Calculation は Result Snapshot に焼き込まず、retry response 作成時に current Performance Calculation から合成する

---

### Score
Validated された gameplay result の canonical record。Leaderboard、stats、rank calculation の source of truth。

**Identity**:
- **Online Checksum**: Score payload 自体の checksum (client が生成)。Global unique constraint。同じ gameplay result の重複送信を防ぐ。
- **Replay Checksum**: Replay blob の SHA-256。Global unique constraint。Replay 使い回し攻撃を防ぐ。

**Attributes**:
- User ID, beatmap ID, beatmap checksum
- Ruleset (osu, taiko, catch, mania)
- Playstyle (vanilla, relax, autopilot)
- Mods (`ModCombination`; persistence stores the canonical bitmask integer)
- Hit counts (n300, n100, n50, miss, geki, katu)
- Score value, max combo, accuracy, grade
- Passed (true/false) — failed play も score として保存
- Perfect (full combo flag)
- Client version, client flags
- Submitted timestamp

**Uniqueness Rules**:
1. Online checksum が一致 → Reject (同じ gameplay result の重複)
2. Replay checksum が一致 → Reject (replay 使い回し攻撃)

**関係性**:
- 1つの Score は 0 または 1 つの Replay を持つ
- Failed play (passed=false) は score として保存するが、leaderboard/PP/stats から除外

---

### Beatmap File Warmup
Stable client が beatmap を参照した段階で、その後の score submission や Performance Calculation に必要な Beatmap File を事前準備対象にすること。Response の source of truth ではなく、後続処理の待ち時間と retry を減らすための準備状態として扱う。
_Avoid_: Beatmap metadata lookup, synchronous file fetch, PP calculation

**関係性**:
- Beatmap File Warmup は Score を生成しない
- Beatmap File Warmup は Performance Calculation の代わりに PP を計算しない
- Beatmap File がまだ unavailable でも、stable response は各入口の互換形式を維持する

---

### Stable Compatibility Evidence
Stable client または stable client emulator から観測できる request / response contract。Athena の stable transport 互換性を判断する根拠であり、内部実装の都合より優先する。
_Avoid_: Implementation preference, guessed compatibility, test-only assumption

---

### Beatmap Leaderboard
1つの Beatmap に対する Personal Best の順位付き一覧。Score の source of truth ではなく、Score と current Performance Calculation から stable client や Web 表示向けに導かれる view。
_Avoid_: User stats, global ranking, beatmap ranking, score ingestion result

**Policy**:
- 初期 Beatmap Leaderboard は vanilla Playstyle のみを対象にする
- Ranked / Approved / Loved / Qualified の Beatmap に leaderboard を表示できる
- PP 表示は Ranked / Approved の current Performance Calculation がある Score に限定し、PP 未計算であることは Beatmap Leaderboard row の表示可否を変えない
- Failed Score は Beatmap Leaderboard と Personal Best の対象にしない
- Beatmap Leaderboard eligibility は Score submission 時点の Beatmap status と Beatmap checksum で決まり、後から Beatmap が昇格しても昇格前に対象外だった Score は Personal Best 候補にしない
- Leaderboard Visible User の Score だけを Beatmap Leaderboard と Personal Best の対象にする
- Viewer が Leaderboard Visible User ではないことは public Beatmap Leaderboard rows の可視性を変えないが、Viewer 自身の Personal Best は表示対象にしない
- Stable response は最大 50 件の Beatmap Leaderboard rows を返し、score count は filter 後の全候補数ではなく返した row 件数を表す。Personal Best row は別枠で返し、top 50 rows に含まれない場合でも表示対象にできる。Personal Best が top 50 rows に含まれる場合も、Personal Best row と Beatmap Leaderboard row の両方に同じ Score を表示でき、Beatmap Leaderboard rows から除外しない。Personal Best row は score count に含めない

### Leaderboard Eligible Score
Beatmap Leaderboard rows と Personal Best の候補にできる Score。Score submission 時点で Beatmap が leaderboard を表示できる状態であり、Score の beatmap checksum が current Beatmap checksum と一致し、Failed Score ではなく、表示時点でも Beatmap と Score owner が Beatmap Leaderboard の公開条件を満たす必要がある。
_Avoid_: Stored score, all passed score, post-promotion score backfill

### Leaderboard Visible User
Beatmap Leaderboard rows と Personal Best に自身の Score を表示できる User。通常の競技参加者として扱える authorization state を持ち、NORMAL と UNRESTRICTED privileges を満たす。Viewer と Score owner は別の役割であり、public rows は Score owner の可視性で決まる。
_Avoid_: Online user, friend target, viewer access, score owner without visibility

### Beatmap Leaderboard Rank
Beatmap Leaderboard 内の順位。Score が高い Personal Best ほど上位になり、最高 score を 1 位として表示する。同点の場合は Athena が submission を受理した時刻が早い Score を上位にし、それでも同じ場合は Score ID の昇順で順序を決定する。Stable response の Beatmap Leaderboard row rank は返却 rows 内の表示順位として `1..n` を使い、Personal Best row rank は top 50 外でも現在の Leaderboard Scope 全体での順位を使う。
_Avoid_: User rank, global rank, PP rank

### Leaderboard Scope
Beatmap Leaderboard の候補集合を定める範囲。Beatmap、Ruleset、Playstyle、Leaderboard Category と、category 固有の selector から成り、Selected Mods では Leaderboard Mod Filter が selector になる。
_Avoid_: Database key, raw category, score row

### Personal Best
1人の User が特定の Leaderboard Scope で持つ最高 score の代表 Score。Beatmap Leaderboard の順位付け対象になり、表示 rank は現在の Leaderboard Scope 内順位として扱う。Selected Mods では Leaderboard Mod Filter 内の自己ベストになる。Viewer 自身が Leaderboard Visible User ではない場合、その Viewer の Personal Best は表示対象にしない。
_Avoid_: Performance Best, score history, latest score, best attempt

### Performance Best
User Profile、Top Plays、User Stats、User Ranking に反映する PP 優先の代表 Score。Beatmap Leaderboard の Personal Best とは別の選択軸として扱う。
_Avoid_: Personal Best, beatmap leaderboard row, latest score

### Beatmap Performance Best
1人の User が特定の Beatmap / Ruleset / Playstyle で持つ PP 優先の代表 Score。User Profile、Top Plays、User Stats、User Ranking の譜面別 source になり、Beatmap Leaderboard の順位付けには使わない。
_Avoid_: Personal Best, leaderboard best, score-priority best

### Score Submit Personal Best Delta
Stable score submit response で返す、提出前 Personal Best と提出後 Personal Best の比較値。Stable score submit は Leaderboard Category を入力に持たないため、Global / all-mods の score-priority Personal Best だけを比較対象にする。同一 submission の idempotency replay では保存済みの比較結果を返し、Personal Best を再評価しない。Rank は placement projection、total score などは User Stats として別に扱う。
_Avoid_: User stats, raw submitted score, leaderboard rank, category-specific getscores Personal Best

### Leaderboard Category
Stable client が選択する Beatmap Leaderboard の表示種別。Global、Country、Selected Mods、Friends の4種を扱う。Global / Country / Friends は mods で候補を絞らず、Country は閲覧者の国を既定値として Score owner の国で絞る。閲覧者の country が未設定または `XX` の場合、Country は候補なしとして扱う。Selected Mods は Leaderboard Mod Filter で Beatmap Leaderboard rows と Personal Best の候補を絞る。
_Avoid_: User rank category, playstyle, score status

### Stable Local Leaderboard Type
Stable client の `Local` leaderboard selection。Athena の Beatmap Leaderboard では独立した Leaderboard Category にせず、Global と同じ候補集合として扱う。
_Avoid_: Server-local scores, offline client scores, separate local category

### Stable Song Select Leaderboard Request
Stable client が song select/editor context から送る Beatmap Leaderboard request。Beatmap の availability と header を解決するための request として扱い、Beatmap Leaderboard rows と Personal Best は表示対象にしない。
_Avoid_: Score row listing request, gameplay result lookup

### Leaderboard Mod Filter
Selected Mods category で Beatmap Leaderboard rows と Personal Best の候補を絞る mod matching rule。NC と DT、PF と SD は filter matching では同じ候補集合に入れるが、Score row の displayed mods は元の Score mods を保持する。NoMod filter は gameplay-affecting mod がない Score を候補にし、SD / PF / MR などの preference-only mod は NoMod 候補から除外しない。NC は DT 系 gameplay mod として扱い、NoMod 候補には含めない。SD または PF を明示選択した場合は、SD/PF 系の Score だけを候補にする。複数 mod filter は選択された gameplay-affecting mod をすべて要求し、未選択の gameplay-affecting mod を含む Score を候補から外す。
_Avoid_: Raw bitmask equality, rewriting score mods for display

### Friends Leaderboard Eligible Set
Friends category の Beatmap Leaderboard で score row 候補になる user identity 集合。Viewer 自身と viewer の Friend Relationship targets から成り、reverse Friend Relationship は含めない。
_Avoid_: Stable friends list, mutual friends, public social graph

### User Stats
1人の User の競技結果を ruleset / playstyle / category ごとに集約した表示用統計。Beatmap Leaderboard とは別の projection として扱う。
_Avoid_: Beatmap leaderboard, user rank, score row

---

### Performance Calculation
PP-eligible Score に PP と star rating を付与した結果。Ranked / Approved の passed score の競技的な強さを表し、ranked leaderboard や ranked stats が参照する performance source になる。
_Avoid_: PPだけ, calculator response

**関係性**:
- 1つの Score は 0 または 1 つの current Performance Calculation を持つ
- 1つの Score は複数の historical Performance Calculation を持てる
- Score 自体は gameplay result の source of truth であり、PP は Score へ直接混ぜない
- Performance Calculation は Score の gameplay result と Beatmap File から導かれ、Replay を正本入力にしない
- 同じ Score に対する重複 calculation request は current state と provenance を見て冪等に収束させる

**State**:
- `queued`, `fetching_file`, `calculating` — PP result がまだ確定していない
- `completed` — PP result が確定している
- `unavailable` — PP result が恒久的に得られない
- `superseded` — PP Recalculation により current ではなくなった historical record

### Performance Provenance
Performance Calculation の由来を説明する記録。どの calculator profile、calculator version、beatmap file attachment から計算されたかを表す。
_Avoid_: Debug metadata, calculator log

### Performance Unavailable
PP-eligible Score に対する Performance Calculation が恒久的に得られない状態。Score は accepted のまま保持し、stable client retry は止め、operator が原因を調査できるようにする。
_Avoid_: Score reject, retry pending, pp zero score

### Performance Completion Signal
Performance Calculation の完了または利用不可確定を app に知らせる一時的な通知。待機を効率化するための signal であり、performance value の source of truth ではない。
_Avoid_: Task result, canonical PP result

### Formula Profile
Athena が採用する PP 計算ポリシーの名前。Playstyle ごとに分離し、同じ calculator version でも profile が変われば PP Recalculation の対象になる。
_Avoid_: Calculator version, mode name

**Policy**:
- 同じ playstyle の ranked PP は同じ Formula Profile に収束させる
- User flag や user subset で Formula Profile を分岐させない

### PP Recalculation
既存 Score の Performance Calculation を再生成する操作。保存済み provenance が現在の calculator version / formula profile と異なる場合、または beatmap file や保存済み score data が変化した場合に、古い performance value を置き換えるために使う。
_Avoid_: Backfill, stats rebuild

### Performance Recalculation Batch
PP Recalculation の対象 work を durable に束ねる単位。Queue signal ではなく DB 上の batch / work item が未処理 work の source of truth になる。
_Avoid_: Task queue as source of truth, one-shot CLI loop

---

### Replay
Score に付随する replay data。Score の証跡、重複検出、将来の verification / audit に使う。

- **Blob Key**: Storage backend での識別子
- **SHA-256 Checksum**: Replay bytes のハッシュ。Global unique constraint。
- **Byte Size**: Replay サイズ (safety limit で制限)

**Uniqueness Constraint**:
- Replay checksum は全 user、全 beatmap で unique
- 同じ replay を複数の score で使い回すことは不可能 (正規 play ではありえない)

**関係性**:
- 1つの Replay は exactly 1つの Score に属する
- Score は replay なしで存在可能 (client が replay を送らない場合)
- Replay は Performance Calculation の正本入力ではない

---

### Playstyle
Score の mod category axis。Leaderboard と stats を分離するための次元。

**Values**:
- `vanilla` (0) — 通常 play。Wave 1 で実装。
- `relax` (1) — Relax mod。将来実装予定。
- `autopilot` (2) — Autopilot mod。将来実装予定。

**Policy**:
- Wave 1 では vanilla のみ受け付ける
- Relax/Autopilot mod を含む submission は terminal reject
- Schema には playstyle column を用意し、将来の拡張に備える

**本家との差異**:
- osu! 公式: RX/AP score は保存しない
- Athena: Akatsuki と同様、RX/AP score も保存し、別 leaderboard で管理

---

### Beatmap Eligibility
Score を受け付ける条件。本家 osu! と同じ基準。

**Eligible Status** (leaderboard が存在):
- Ranked — Ranked PP 付与、global/country rank に反映
- Approved — Ranked と同じ扱い
- Loved — Leaderboard のみ。PP なし、rank なし。
- Qualified — Leaderboard のみ。PP なし。(Ranked 候補)

**Ineligible Status**:
- Pending, WIP, Graveyard, NotSubmitted — Score を受け付けない (terminal reject)
- Unknown (beatmap が mirror に存在しない) — Terminal reject

**Rationale**:
- Leaderboard が存在しない beatmap の score は意味がない
- Beatmap metadata がなければ ruleset や difficulty も不明
- Loved / Qualified / failed score は Score として保存できるが、Wave 2 では Performance Calculation を持たない

---

### Terminal Reject
Score submission が永続的に失敗する条件。Client は retry すべきでない。

**Terminal Reject Conditions**:
1. **Transport validation failure**: Multipart parsing 失敗、required field 欠損
2. **Crypto validation failure**: Decryption 失敗、payload checksum 不一致
3. **Authorization failure**: Password 不一致、active session なし、payload identity mismatch
4. **Uniqueness violation**: Online checksum 重複、replay checksum 重複
5. **Beatmap ineligibility**: Unknown beatmap、ineligible status
6. **Playstyle not supported**: Wave 1 では relax/autopilot を reject
7. **Score validation failure**: Hit counts 不整合、ruleset-specific validation 失敗

**Retryable Conditions** (Wave 1 scope 外):
- Beatmap file 取得中 (processing pending)
- Worker queue 過負荷
- Temporary storage/DB error
- Performance Calculation が bounded wait 内に完了していない

---

## Reference Implementations

Athena の設計は以下の既存実装を参考にしています:

### bancho.py (Akatsuki)
- Python + FastAPI
- Single process architecture
- Score table with `mode` column (vanilla/RX/AP を packed integer で表現)
- Repository pattern (直接 SQLAlchemy import)

### osuRipple/lets
- Python + Cython
- Score table with `play_mode` と relax flag
- Checksum + lock による duplicate 防止

### osuTitanic/deck
- Python + FastAPI (modern)
- rosu-pp-py 使用
- Helper pattern で validation と calculation を分離

### Pure-Peace/peace (参考、実験的実装)
- **Rust** implementation
- Clean architecture with **clear layer separation**
- Score/leaderboard/stats を **mode/playstyle ごとに物理分割**
- Entity-based design (scores_standard, leaderboard_standard, user_stats_standard)
- 型安全、明確な境界を持つ設計

**Note**: 実験的実装のため参考程度。Athena は table 物理分割は採用せず、axis column で統一します。

---

## Architectural Boundaries

### Wave 1: Score Ingestion
**Responsibility**: Stable client からの score 受付、validation、保存、replay 保存。

**In Scope**:
- Multipart parsing (duplicate `score` field の order-preserving)
- Rijndael 256-bit decryption (特殊仕様: Rijndael-256 / block_size=32 / CBC / 32-byte IV)
- Score payload parsing (colon-separated → domain object)
- Authorization (password + active session + payload identity)
- Score validation (hit counts 整合性、ruleset-specific)
- Replay uniqueness check
- Completed response (PP なし、chart placeholder)

**Crypto Implementation Note**:
- osu! の Rijndael 実装は標準 AES-256 と異なる
- Rijndael-256 (key size 256-bit, **block size 256-bit = 32 bytes**)
- Mode: CBC
- IV: 32-byte (block size と同じ)
- Standard AES-256 は block size 128-bit なので、cryptography library では対応不可
- 対応ライブラリを調査するか、PyO3 + Rust の rijndael crate を使う必要あり

**Out of Scope**:
- PP calculation (Wave 2)
- Leaderboard projection (Wave 3)
- User stats projection (Wave 3)
- User ranking projection (Wave 4)

**Dependencies**:
- Beatmap mirror (beatmap metadata と eligibility)
- Blob storage (replay 保存)
- Active session store (authorization)
- Score authorization command service (password + active session 検証)

---

## Future Waves

### Wave 2: score-pp-calculation
**Goal**: Ranked / Approved の passed Score に PP と star rating を付与する。

**Scope**:
- rosu-pp-py による ranked PP と star rating 計算
- Performance provenance (calculator version, formula profile, beatmap file attachment)
- .osu file dependency と bounded wait
- Completed response with PP included

**Dependencies**: score-ingestion (Wave 1), beatmap-mirror

**Out of Scope**: Leaderboard への反映、user stats への反映

---

### Wave 3: beatmap-leaderboards & user-stats
**Goal**: Beatmap leaderboard と user stats を stable client と Web に表示する。

**beatmap-leaderboards Scope**:
- Beatmap leaderboard projection table
- Personal best tracking と replacement logic
- Getscores score rows provider
- Score descending ordering、PP display

**user-stats Scope**:
- User stats per ruleset/playstyle/category
- Play count, play time, ranked score, weighted PP, accuracy
- Grade counts、hit totals
- Stats update worker job

**Dependencies**: score-ingestion (Wave 1), score-pp-calculation (Wave 2)

**Out of Scope**: Global/country rank (Wave 4 で実装)

---

### Wave 4: user-ranking
**Goal**: Global/country rank を時系列で tracking し、user profile と ranking graph に表示する。

**Scope**:
- User rank projection table (current snapshot)
- Rank 時系列履歴 table (daily/hourly snapshots)
- Rank rebuild worker job (window function による bulk calculation)
- Ranking graph API (time series data)
- Login packet と Web ranking API への rank 提供

**Dependencies**: user-stats (Wave 3)

**Design Considerations**:
- Snapshot frequency (hourly? daily?)
- Historical data retention policy
- Rebuild strategy (incremental vs full rebuild)
- Tie-break ordering (PP → ranked score → user ID)
