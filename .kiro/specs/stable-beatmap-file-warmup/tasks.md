# Implementation Plan

- [ ] 1. Foundation: Beatmap File Warmup の command boundary を定義する
- [x] 1.1 Warmup request / result と identity policy を実装する
  - stable の 3 entrance を識別できる authenticated warmup request と diagnostics 用 outcome を typed contract として扱う
  - beatmap id は正の値だけを、checksum は normalized 32 hex だけを resolver input として受け付ける
  - beatmap id と checksum が両方ある場合は beatmap id を優先し、identity がない場合や malformed の場合は fetch work を作らず skip outcome にする
  - 完了時には malformed identity と no identity の unit test が resolver 呼び出しなしの skip outcome と diagnostics を観測できる
  - _Requirements: 1.1, 1.3, 1.4, 1.5, 5.2, 5.3, 6.5_

- [x] 1.2 Warmup resolver orchestration と structured diagnostics を実装する
  - resolver には Beatmap File を要求し、stable request handling では file body download を待たない
  - Beatmap File が利用可能な場合は already available、既知 beatmap の file が未準備の場合は requested、checksum-only で beatmap が未解決の場合は metadata pending として扱う
  - resolver failure は stable transport へ例外を漏らさず failed outcome として返し、credential、raw payload、replay bytes を含まない structured log に残す
  - warmup use-case は PP、score state、leaderboard projection、Performance Calculation readiness の source of truth を更新しない
  - 完了時には resolver options、outcome mapping、exception-to-failed、already available no-op が unit test で観測できる
  - _Requirements: 1.1, 1.2, 1.3, 1.5, 4.2, 5.3, 5.4, 6.1, 6.2, 6.3, 6.4, 6.6, 7.4_

- [ ] 2. Core integrations: stable の 3 入口から warmup を発火する
- [x] 2.1 (P) getscores warmup side effect を追加する
  - 認証成功と parse 成功の後だけ warmup を呼び、auth failure と parse failure では fetch work を発火しない
  - known-header response では解決済み beatmap id を優先し、それ以外の parseable request では usable checksum を warmup input にする
  - unavailable、update-available、known-header の response body と status mapping は既存形式のまま維持する
  - warmup failure は getscores outcome を変えず、operator-visible diagnostics だけに残す
  - 完了時には getscores の既存 response bytes が warmup の成功、skip、failure によって変化しない unit / integration test が通る
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 5.1, 5.4, 5.5, 6.1, 6.5, 6.6, 7.1, 7.5_
  - _Boundary: Stable web legacy getscores_
  - _Depends: 1.2_

- [x] 2.2 (P) STATUS_CHANGE warmup handler を追加する
  - authenticated polling session から渡された user id だけを warmup request の user context として扱う
  - STATUS_CHANGE payload は既存 packet type として decode し、beatmap id が正なら id を優先、id が使えない場合だけ 32 hex checksum を fallback identity にする
  - beatmap identity がない payload、malformed payload、warmup failure は client disconnect の原因にせず diagnostics に残す
  - presence state、status broadcast、online projection はこの handler では実装しない
  - 完了時には id path、checksum fallback、no identity、decode failure、repeated reference の unit test が conflicting fetch outcome なしで通る
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 5.1, 5.2, 5.3, 5.5, 6.2, 6.5, 6.6, 7.2, 7.5_
  - _Boundary: Stable bancho status handler_
  - _Depends: 1.2_

- [ ] 2.3 (P) score submit fallback warmup を追加する
  - fallback は認証、beatmap resolution、eligibility、empty replay、hit validation の通過後、replay blob storage より前に実行する
  - resolved beatmap id と parsed checksum を warmup input に渡し、warmup result は score submission outcome の選択に使わない
  - terminal reject、accepted score、retryable replay storage failure、duplicate online checksum、duplicate replay checksum の既存 behavior を維持する
  - warmup failure は score submit response を変えず、fallback entrance と beatmap identity を diagnostics に残す
  - 完了時には accepted path と replay storage retryable path のどちらでも fallback warmup が先に観測される regression test が通る
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.4, 5.5, 6.3, 6.6, 7.3, 7.4, 7.5_
  - _Boundary: Score submission command_
  - _Depends: 1.2_

- [ ] 3. Runtime wiring: DI graph と dispatcher registration を統合する
- [ ] 3.1 Warmup use-case と stable handler dependencies を composition graph に接続する
  - beatmap app graph は existing BeatmapMirrorService を warmup resolver として提供する
  - stable web legacy graph は getscores handler に warmup use-case を渡す
  - stable bancho graph は STATUS_CHANGE handler を構築し、既存 packet dispatcher に登録する
  - score submission graph は fallback warmup dependency を score submission workflow に渡す
  - worker graph、task name、queue、schema、blob provider は追加・変更しない
  - 完了時には app / test composition が warmup use-case、getscores handler、STATUS_CHANGE handler、score submission workflow を解決できる
  - _Requirements: 1.1, 1.5, 2.1, 3.1, 4.1, 7.1, 7.2, 7.3, 7.4, 7.5_
  - _Depends: 2.1, 2.2, 2.3_

- [ ] 4. Validation: compatibility、diagnostics、quality gates を固定する
- [ ] 4.1 (P) getscores compatibility と diagnostics を integration test で検証する
  - authenticated known-header request は warmup requested diagnostics を出しつつ response body を byte-for-byte 維持する
  - auth failure、parse failure、malformed identity は fetch work を発火せず、credential や raw query string を log に含めない
  - unavailable と update-available の短い response は warmup success / failure によって変化しない
  - 完了時には getscores の auth、parse、status mapping、response body compatibility が warmup 有無に関係なく通る
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 5.1, 5.4, 5.5, 6.1, 6.5, 6.6, 7.1, 7.5_
  - _Boundary: Stable web legacy integration tests_
  - _Depends: 3.1_

- [ ] 4.2 (P) STATUS_CHANGE と existing fetch queue の E2E behavior を検証する
  - authenticated polling の STATUS_CHANGE packet は beatmap id または checksum から warmup を要求する
  - repeated STATUS_CHANGE は existing fetch pending idempotency に収束し、conflicting warmup outcome を作らない
  - file already available の beatmap は no-op skip reason を diagnostics に出し、file unavailable の known beatmap は existing file fetch task へ接続される
  - 完了時には polling response behavior と packet dispatch for other stable packets が STATUS_CHANGE handler 追加後も維持される
  - _Requirements: 1.1, 1.2, 1.3, 3.1, 3.2, 3.3, 3.4, 3.5, 5.1, 5.3, 5.5, 6.2, 6.4, 6.5, 6.6, 7.2, 7.5_
  - _Boundary: Stable bancho and beatmap fetch E2E tests_
  - _Depends: 3.1_

- [ ] 4.3 (P) score submit fallback の outcome regression を検証する
  - terminal reject は warmup failure や file pending によって retryable response へ変換されない
  - accepted score は Beatmap File pending だけを理由に reject されず、fallback diagnostics を残して既存 response shape を返す
  - duplicate online checksum と duplicate replay checksum の reject / idempotency behavior は fallback warmup に参加しない
  - 完了時には score submit accepted、retryable replay storage failure、terminal reject、duplicate checks の regression tests がすべて通る
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.4, 5.5, 6.3, 6.6, 7.3, 7.4, 7.5_
  - _Boundary: Score submission tests_
  - _Depends: 3.1_

- [ ] 4.4 Quality gates と architecture boundary を確認する
  - unit、integration、E2E coverage が warmup use-case、stable web legacy、stable bancho、score submit fallback、composition graph を通る
  - type checking、lint、format、import boundary checks が新しい warmup boundary を含めて通る
  - implementation review で stable response body、packet behavior、worker task names、score submission semantics が変わっていないことを確認する
  - 完了時には relevant test gate と quality gate が成功し、未検証項目が残っていない
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 7.1, 7.2, 7.3, 7.4, 7.5_
  - _Depends: 4.1, 4.2, 4.3_
