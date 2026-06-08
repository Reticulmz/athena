# Requirements Document

## Introduction

Athena には stable 互換の beatmap 情報 endpoint が必要である。osu! stable クライアントは、スコア送信や leaderboard 実装より前の選曲画面で beatmap の識別子、rank 状態、mode 別 grade を問い合わせる。既存の beatmap-mirror は metadata 解決、source freshness、fetch state を扱うが、web legacy transport はまだ `/web/osu-getbeatmapinfo.php` を公開していない。

この仕様は Beatmap Info Endpoint のユーザー観測可能な振る舞いを定義する。対象は osu web domain 上の認証付き stable client access、batch beatmap info lookup、beatmap mirror 経由の cache-first metadata resolution、短い bounded wait、stable 互換 response formatting、未解決 map の保守的な扱い、実 stable client request fixture による validation である。

## Boundary Context

- **In scope**:
  - osu web domain 上の stable client 向け `POST /web/osu-getbeatmapinfo.php`。
  - この endpoint が期待する legacy request credentials による stable client authentication。
  - filenames と beatmap ids の batch beatmap info lookup。
  - checksum/md5、明示的 beatmap id、filename fallback の順の lookup candidate priority。
  - 既存 beatmap mirror 振る舞いによる metadata-only beatmap / beatmapset resolution。
  - missing metadata に対する短い bounded wait と cache recheck。
  - request index、beatmap id、beatmapset id、md5、stable status、4 mode grades を含む stable-compatible response line。
  - unresolved、pending、unknown、not-submitted beatmaps の response body からの省略。
  - compatibility testing で採取した real stable client request による fixture-backed validation。

- **Out of scope**:
  - `/web/osu-osz2-getscores.php` と leaderboard response formatting。
  - osu!direct search、beatmapset download、`.osz` archive proxy、mirror search UX。
  - score submission、score persistence、PP calculation、leaderboard updates。
  - PP 計算用の `.osu` file fetch または `.osu` file body availability。
  - Beatmap upload implementation、upload id allocation、upload storage、upload permission workflows。
  - WebUI screens、WebUI configuration editing、BanchoBot refresh commands、rank-management approval workflows。
  - future local upload identity models のための database schema changes。

- **Adjacent expectations**:
  - `beatmap-mirror` は beatmap / beatmapset metadata resolution、fetch state、source status、local override semantics を提供する。
  - future score / leaderboard features は personal best grades を提供できる。それまではこの endpoint は neutral grades を返せる。
  - future local upload / rank-management features は local-source または local-override states を公開できる。この endpoint はそれらの effective status を stable-compatible values に map し、stable client には internal origin を露出しない。
  - Internal APIs と future WebUI-facing APIs は source、verification、policy、override provenance を公開できるが、stable client response は legacy-compatible のままにする。

## Requirements

### Requirement 1: Stable Beatmap Info Endpoint Scope

**Objective:** As a stable client user, I want 選曲画面から Athena に beatmap 情報を問い合わせられること, so that gameplay 前に client が server-known beatmap status を表示できる。

#### Acceptance Criteria

1. When stable client が osu web domain 上の `/web/osu-getbeatmapinfo.php` に beatmap info request を送信する, the Beatmap Info Endpoint shall その request を web legacy beatmap information request として処理する。
2. If beatmap info request が osu web domain 以外に送信される, then the Beatmap Info Endpoint shall この feature のための path-based fallback route を要求しない。
3. The Beatmap Info Endpoint shall この feature を beatmap information lookup と stable-compatible response formatting に限定する。
4. The Beatmap Info Endpoint shall leaderboard score lists、osu!direct search、beatmapset download、score submission、PP calculation、beatmap upload behavior を提供しない。

### Requirement 2: Legacy Authentication

**Objective:** As an operator, I want beatmap info requests が他の stable web requests と同じ user identity expectations を要求すること, so that anonymous clients が user-specific beatmap grades を照会できない。

#### Acceptance Criteria

1. When beatmap info request が valid legacy user credentials と active bancho session を含む, the Beatmap Info Endpoint shall request を authorize する。
2. If request credentials が missing または invalid である, then the Beatmap Info Endpoint shall request を authentication failure として reject する。
3. If user に active bancho session がない, then the Beatmap Info Endpoint shall request を authentication failure として reject する。
4. While request が unauthorized である, the Beatmap Info Endpoint shall response body に beatmap status、grade、lookup diagnostics を disclose しない。

### Requirement 3: Stable Client Request Parsing

**Objective:** As a stable client compatibility maintainer, I want endpoint が real clients の request shapes を受け入れること, so that parser assumptions が song selection behavior を壊さない。

#### Acceptance Criteria

1. When request が filename batch entries を含む, the Beatmap Info Endpoint shall 各 filename entry を original request index とともに preserve する。
2. When request が beatmap id batch entries を含む, the Beatmap Info Endpoint shall 各 id entry を id-based lookup entry として preserve する。
3. If request が zero lookup entries を含む, then the Beatmap Info Endpoint shall successful empty response body を返す。
4. If request が 100 を超える total lookup entries を含む, then the Beatmap Info Endpoint shall successful empty response body を返し、rejected batch size を operators に observable にする。
5. If request body が supported stable client beatmap info request として parse できない, then the Beatmap Info Endpoint shall successful empty response body を返し、parse failure を operators に observable にする。
6. The Beatmap Info Endpoint shall compatibility testing で採取した real stable client request fixtures に対して validate される。

### Requirement 4: Lookup Candidate Priority

**Objective:** As a stable client user, I want 各 requested beatmap が正しい server beatmap に resolve されること, so that renamed files や incomplete request data が incorrect status results を引き起こさない。

#### Acceptance Criteria

1. When filename entry が recognizable checksum/md5 を含む, the Beatmap Info Endpoint shall その entry では checksum lookup を優先する。
2. When lookup entry が explicit beatmap id を含み checksum lookup が利用できない, the Beatmap Info Endpoint shall その entry では beatmap id lookup を使う。
3. When checksum と explicit beatmap id lookup candidates が利用できない, the Beatmap Info Endpoint shall filename lookup を fallback として使う。
4. If filename entry から supported lookup candidate を得られない, then the Beatmap Info Endpoint shall その entry を response から omit し、unparsable entry を operators に observable にする。
5. The Beatmap Info Endpoint shall request shape が explicit beatmap ids として識別していない限り、ambiguous filename fragments を beatmap ids として扱わない。

### Requirement 5: Cache-First Metadata Resolution

**Objective:** As a stable client user, I want known beatmaps が素早く resolve されること, so that song selection を開く操作が external beatmap sources に依存しない。

#### Acceptance Criteria

1. When requested beatmap が already known and usable である, the Beatmap Info Endpoint shall external source lookup を待たずに cached beatmap information を返す。
2. When requested beatmap が checksum または id で unknown である, the Beatmap Info Endpoint shall その lookup target の metadata resolution を request する。
3. While metadata resolution が pending である, the Beatmap Info Endpoint shall response 前に configured bounded wait behavior の範囲内だけ待つ。
4. If metadata resolution が bounded wait 内に完了する, then the Beatmap Info Endpoint shall stable response output に eligible な resolved beatmap を含める。
5. If metadata resolution が bounded wait 後も pending のままである, then the Beatmap Info Endpoint shall その beatmap を response から omit する。
6. The Beatmap Info Endpoint shall metadata resolution のみを request し、beatmap info responses のために `.osu` file body fetch を request しない。

### Requirement 6: Beatmapset Snapshot Reuse

**Objective:** As a stable client user, I want 同じ beatmapset の batch lookups が一度の metadata fetch を活用すること, so that multiple difficulties が consistent に resolve される。

#### Acceptance Criteria

1. When ある lookup の metadata resolution が multiple beatmaps を含む beatmapset を返す, the Beatmap Info Endpoint shall 同じ batch 内の後続 lookups が newly known beatmapset metadata を利用できるようにする。
2. When bounded wait が batch に対して完了する, the Beatmap Info Endpoint shall response lines を format する前に known metadata を recheck する。
3. When 1 つの batch 内の複数 entries が同じ resolved beatmapset を参照する, the Beatmap Info Endpoint shall resolved entries に consistent beatmapset ids と statuses を返す。
4. The Beatmap Info Endpoint shall 各 response line に original request entry を識別できる stable-compatible index value を含める。

### Requirement 7: NotSubmitted and Unresolved Behavior

**Objective:** As a stable client user, I want Athena が server-known maps として識別できない maps が response に出ないこと, so that client が misleading metadata ではなく unavailable として扱える。

#### Acceptance Criteria

1. If official metadata lookup が requested checksum を not submitted と確認する, then the Beatmap Info Endpoint shall その beatmap を response から omit する。
2. If requested beatmap が unknown status、pending metadata、failed metadata、または usable metadata なしである, then the Beatmap Info Endpoint shall その beatmap を response から omit する。
3. When checksum に対する not-submitted result が known である, the Beatmap Info Endpoint shall stable response においてその result を source failure として扱わない。
4. When not-submitted result が adjacent beatmap metadata behavior によって後で refreshable になる, the Beatmap Info Endpoint shall known になった refreshed result を利用する。

### Requirement 8: Stable-Compatible Response Format

**Objective:** As a stable client user, I want beatmap info responses が client の理解できる format で返ること, so that song selection が returned data を requested maps に関連付けられる。

#### Acceptance Criteria

1. When filename-based lookup が resolve される, the Beatmap Info Endpoint shall original filename request index を含む response line を返す。
2. When id-based lookup が resolve される, the Beatmap Info Endpoint shall stable-compatible id lookup index value を使う response line を返す。
3. When beatmap response line が返される, the Beatmap Info Endpoint shall beatmap id、beatmapset id、md5、stable-compatible status、four per-mode grade values を含める。
4. When batch 内で multiple beatmaps が resolve される, the Beatmap Info Endpoint shall response line order に依存せず client が各 line を requested entry に関連付けられる index values を返す。
5. The Beatmap Info Endpoint shall placeholder beatmap data を返すのではなく unresolved entries の response lines を omit する。
6. The Beatmap Info Endpoint shall stable client response lines に internal source、verification、local policy、override provenance fields を含めない。

### Requirement 9: Stable Status Mapping

**Objective:** As a stable client user, I want Athena の internal beatmap states が stable-compatible statuses として表示されること, so that client が familiar ranked、loved、qualified、pending、unavailable states を表示できる。

#### Acceptance Criteria

1. When resolved beatmap が stable の supported effective status を持つ, the Beatmap Info Endpoint shall その effective status を stable-compatible status value に map する。
2. When resolved beatmap が stable clients に対して Loved のように振る舞う effective local status を持つ, the Beatmap Info Endpoint shall それを stable-compatible Loved status value に map する。
3. When resolved beatmap が scoring に対して Ranked のように振る舞う effective local status を持つ, the Beatmap Info Endpoint shall それを stable-compatible Ranked status value に map する。
4. When resolved beatmap が stable clients に表示可能な effective pending-like status を持つ, the Beatmap Info Endpoint shall それを stable-compatible pending-like status value に map する。
5. If resolved beatmap が stable に submitted として visible にすべきでない effective status を持つ, then the Beatmap Info Endpoint shall その beatmap を response から omit する。

### Requirement 10: Grade Projection

**Objective:** As a stable client user, I want beatmap info responses が available な場合に existing grades を含むこと, so that song selection が personal completion state を表示できる。

#### Acceptance Criteria

1. When authenticated user と resolved beatmap に対する personal best grade data が available である, the Beatmap Info Endpoint shall supported game mode ごとの user grade を含める。
2. If personal best grade data が unavailable である, then the Beatmap Info Endpoint shall supported game modes すべてに neutral grade values を含める。
3. While score and leaderboard persistence が unavailable である, the Beatmap Info Endpoint shall beatmap status resolution を block せず neutral grade values を返す。
4. The Beatmap Info Endpoint shall beatmap info grades を生成する間に scores を create、update、recalculate しない。

### Requirement 11: Batch Fetch Idempotency and Load Boundaries

**Objective:** As an operator, I want large but valid song selection requests が duplicate または conflicting metadata work を避けること, so that client batches が upstream sources を overload しない。

#### Acceptance Criteria

1. When 1 つの request 内の multiple entries が同じ target の metadata fetch を必要とする, the Beatmap Info Endpoint shall その target について duplicate conflicting results を expose しない。
2. When unknown entries が 100-entry batch limit 内にある, the Beatmap Info Endpoint shall unknown entries すべてに対する metadata fetch requests を allow する。
3. If lookup target に対する metadata fetch が already pending である, then the Beatmap Info Endpoint shall pending fetch を new conflicting fetch が必要な状態ではなく existing work として扱う。
4. The Beatmap Info Endpoint shall unusually large rejected batches と repeated unresolved lookup patterns を operators に observable にする。

### Requirement 12: Future Local Upload Compatibility

**Objective:** As an operator planning future beatmap upload support, I want beatmap info responses が later local-source beatmaps と互換であること, so that upload support が同じ stable client endpoint を再利用できる。

#### Acceptance Criteria

1. Where future local-source beatmaps が adjacent beatmap behavior によって resolve される, the Beatmap Info Endpoint shall other beatmaps と同じ stable-compatible response format でそれらを返せる。
2. Where future local-source beatmaps が operator-selected default status policy を使う, the Beatmap Info Endpoint shall adjacent policy resolution 後の effective status を反映する。
3. Where future local-source beatmaps が source または policy provenance を expose する, the Beatmap Info Endpoint shall stable client response にその provenance を含めない。
4. The Beatmap Info Endpoint shall local upload id allocation、upload storage、upload permissions、upload lifecycle behavior を定義しない。

### Requirement 13: Compatibility Research and Validation Evidence

**Objective:** As a maintainer, I want endpoint behavior が real client と reference-server behavior に基づくこと, so that compatibility assumptions を testable にできる。

#### Acceptance Criteria

1. The Beatmap Info Endpoint shall real stable client request fixtures に基づく request parsing と response formatting の validation coverage を持つ。
2. Where real stable client fixtures が early implementation 中に unavailable である, the Beatmap Info Endpoint shall provisional reference-server fixtures と real client fixtures を区別する。
3. The Beatmap Info Endpoint shall batch shape、response fields、id lookup behavior、grade behavior を判断するために使った reference implementations を document する。
4. When future stable client fixture evidence が provisional behavior と矛盾する, the Beatmap Info Endpoint shall compatibility requirements では real stable client behavior を優先する。
