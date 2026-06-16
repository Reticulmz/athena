# Implementation Plan

- [x] 1. Foundation: Performance Calculation の基盤を定義する
- [x] 1.1 Performance domain model と policy を定義する
  - Performance Calculation の状態を `queued`, `fetching_file`, `calculating`, `completed`, `unavailable`, `superseded` として扱えるようにする
  - Ranked / Approved の passed vanilla score だけを Wave 2 の ranked PP 対象にし、Loved / Qualified / failed / Relax / Autopilot を対象外にする
  - Formula Profile を playstyle ごとに 1 つだけ解決し、user flag や user subset で ranked PP を分岐しない
  - 完了時には state invariant、eligibility decision、Formula Profile decision を unit test で観測できる
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 4.1, 4.2, 4.3, 4.4, 4.5, 5.3, 5.5, 9.6, 12.1, 12.5, 15.4, 15.5_

- [x] 1.2 Performance と recalculation の永続 schema を追加する
  - current Performance Calculation が score ごとに 1 件だけになる制約を追加する
  - PP、star rating、calculator version、Formula Profile、beatmap file attachment identity、calculated timestamp を保存できるようにする
  - recalculation batch と work item が filters、reason counts、target provenance、progress、claim state を保持できるようにする
  - 完了時には migration 適用後の DB に performance / recalculation tables、constraints、indexes が作成される
  - _Requirements: 5.1, 5.2, 5.3, 11.1, 11.2, 13.1_

- [x] 1.3 Runtime configuration と test double を整える
  - bounded wait、Formula Profile、worker chunk size、claim timeout を実行時設定として扱う
  - 設定ファイル変更が必要な場合は実装時に明示承認を得てから追加する
  - in-memory state が performance row、batch、work item、claim、current replacement を test で再現できるようにする
  - 完了時には app / worker / test composition が performance subsystem の既定値で起動できる
  - _Requirements: 6.1, 10.3, 10.4, 10.5, 10.6, 11.3, 11.4, 12.1_

- [x] 2. Persistence: current PP と recalculation work を保存・検索できるようにする
- [x] 2.1 (P) Performance Calculation の command persistence を実装する
  - calculation request の作成、既存 current row の再利用、pending claim、completed / unavailable finalization を原子的に扱う
  - stale provenance や profile mismatch の replacement は、finalization まで既存 current PP を維持する
  - duplicate request や temporary claim conflict は unavailable にせず、retry または no-op として収束させる
  - 完了時には複数 worker が同じ score を処理しても current row が 1 件に収束する contract test が通る
  - _Requirements: 2.5, 2.6, 5.1, 5.2, 5.3, 8.1, 8.2, 8.3, 8.4, 8.5, 12.3, 12.4_
  - _Boundary: ScorePerformanceCommandRepository_
  - _Depends: 1.2, 1.3_

- [x] 2.2 (P) Performance read model と candidate selection を実装する
  - stable response は current Performance Calculation だけを読めるようにする
  - uncalculated、stale、calculator version mismatch、Formula Profile mismatch、explicit unavailable を candidate reason として集計する
  - score id、beatmap id、user id、ruleset、limit の filter を candidate selection に反映する
  - 完了時には dry-run 用 reason breakdown と candidate count が query result として取得できる
  - _Requirements: 5.4, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 10.1, 10.3, 10.4, 10.6, 14.2_
  - _Boundary: ScorePerformanceQueryRepository_
  - _Depends: 1.2, 1.3_

- [x] 2.3 Recalculation batch persistence を実装する
  - execution mode で batch と work item を 1 つの durable work set として作成する
  - pending または stale claimed work を bounded chunk で claim できるようにする
  - worker 停止や wake-up signal loss 後も未完了 work が再発見できるようにする
  - 完了時には batch progress、completed count、unavailable count、last error が operator-visible に更新される
  - _Requirements: 10.2, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 12.2_

- [ ] 3. Calculation dependencies: `.osu` file、calculator、completion signal を隔離する
- [x] 3.1 (P) PP calculation 用 `.osu` file provider を実装する
  - beatmap-mirror に `require_osu_file=True` で問い合わせ、fetch 中の file は pending input として扱う
  - attachment が利用可能な場合だけ blob-storage から `.osu` bytes を読む
  - attachment id と checksum を provenance として返す
  - 完了時には missing / pending / unusable file の各状態が fetching continuation または unavailable reason として観測できる
  - _Requirements: 2.2, 2.5, 2.6, 5.2, 15.3_
  - _Boundary: PerformanceBeatmapFileProvider_
  - _Depends: 1.1_

- [x] 3.2 (P) rosu calculator adapter を実装する
  - 承認済みの `rosu-pp-py` を infrastructure adapter 内だけで使う
  - server-validated Score data と `.osu` bytes から PP と star rating を計算し、replay bytes を要求しない
  - calculator version を package metadata から記録し、calculator failure を typed unavailable reason に変換する
  - 完了時には replay が存在する score と存在しない score のどちらも同じ server Score input から計算できる
  - _Requirements: 2.1, 2.3, 2.4, 13.1, 14.1, 14.3, 14.4, 14.5, 15.3_
  - _Boundary: RosuPerformanceCalculator_
  - _Depends: 1.1_

- [x] 3.3 (P) Performance Completion Signal を実装する
  - terminal state 到達時に score-scoped signal を publish できるようにする
  - signal payload には PP を持たせず、waiter は必ず DB を再読込する
  - signal loss、delay、missing があっても timeout 前の final current-state check へ進める
  - 完了時には in-memory と Valkey-backed の wait / notify behavior が同じ contract test で確認できる
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_
  - _Boundary: PerformanceCompletionSignal_
  - _Depends: 1.3_

- [ ] 4. Core commands: calculation request と worker execution を実装する
- [x] 4.1 Request Performance Calculation workflow を実装する
  - accepted eligible score に current calculation row を作成または再利用する
  - completed / unavailable row の provenance が active calculator version と Formula Profile に一致する場合は no-op にする
  - pending row が存在する場合は duplicate row を作らず worker wake-up だけを許可する
  - 完了時には out-of-scope score が score accepted のまま PP row なしで終わる
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 3.1, 8.1, 8.2, 8.3, 8.4, 8.5, 12.2, 14.2, 15.4, 15.5_
  - _Depends: 2.1_

- [x] 4.2 Execute Performance Calculation workflow を実装する
  - pending calculation を claim し、file provider、calculator、repository finalization を順に実行する
  - `.osu` file が一時的に不足する場合は pending state を維持し、永続的に使えない場合だけ unavailable にする
  - completed / unavailable の terminal state commit 後に completion signal を publish する
  - 完了時には PP、stars、calculator version、Formula Profile、beatmap file provenance が current row に保存される
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 4.2, 4.3, 4.4, 5.2, 13.1, 14.1, 14.3, 14.4, 14.5, 15.3_
  - _Depends: 2.1, 3.1, 3.2, 3.3_

- [x] 4.3 score performance job adapters を実装する
  - calculation job と recalculation batch job は primitive id payload だけを受け取る
  - taskiq state から use-case を解決し、runtime dependency missing は observable failure として log / raise する
  - duplicate job execution は use-case の idempotency に委ねる
  - 完了時には job adapter が SQLAlchemy、Valkey、calculator、repository construction を直接扱っていない
  - _Requirements: 8.4, 10.2, 11.3, 11.4, 11.5_
  - _Depends: 4.1, 4.2_

- [x] 4.4 App / worker composition を統合する
  - app side は accepted score 後に durable calculation request を作り、commit 後に worker を wake できるようにする
  - worker side は calculation use-case を taskiq state に登録し、batch use-case は 6.2 実装時に同じ runtime state 境界へ登録できるようにする
  - job registration は既存 taskiq registry pattern に従う
  - 完了時には app process と worker process が performance dependencies を解決して起動できる
  - _Requirements: 3.1, 6.1, 8.4, 10.2, 11.5_
  - _Depends: 4.3_

- [ ] 5. Stable submit integration: accepted score response に PP state を合成する
- [x] 5.1 PerformanceResponseQuery を実装する
  - bounded wait 中は completion signal を待ち、signal 後に current Performance Calculation を再読込する
  - signal timeout 時にも final current-state check を行う
  - completed は stable-safe integer PP、pending は retryable、unavailable / out-of-scope は accepted `pp:0` として返す
  - 完了時には signal が失われた場合でも DB state に基づく retryable response または completed response が返る
  - _Requirements: 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 5.4, 6.1, 6.2, 6.3, 6.4, 6.5, 13.2, 13.3, 13.4_
  - _Depends: 2.2, 3.3_

- [x] 5.2 Score submission workflow に performance response を統合する
  - newly accepted eligible score は calculation request を発行してから bounded wait に入る
  - retried submission fingerprint は既存 accepted Score と current Performance Calculation から response を再構築する
  - PP を submission result snapshot の canonical value として保存しない
  - 完了時には duplicate online checksum と duplicate replay checksum の terminal reject behavior が変わっていない
  - _Requirements: 1.5, 3.1, 3.5, 3.6, 3.7, 7.1, 7.2, 7.3, 7.4, 7.5_
  - _Depends: 4.1, 5.1_

- [x] 5.3 Stable submit mapper の PP formatting を更新する
  - completed current PP は stable chart の `pp` field に nearest integer として出力する
  - unavailable、pending timeout 後の retry、out-of-scope は existing response semantics に合わせる
  - calculator diagnostics と unavailable reason を stable client response に出さない
  - 完了時には stable response body が PP あり / `pp:0` / `error: yes` の 3 状態を既存形式で表現できる
  - _Requirements: 3.3, 3.4, 3.7, 13.2, 13.3, 13.4, 14.5_
  - _Depends: 5.2_

- [ ] 6. Recalculation operations: CLI から durable work を作成・処理できるようにする
- [x] 6.1 Recalculation batch creation workflow を実装する
  - dry-run は candidate count と reason breakdown だけを返し、durable work を作らない
  - execute mode は filters、target calculator version、target Formula Profile、reason counts を保存した batch と work items を作る
  - no narrow filter の profile migration は explicit full-scope flag を必須にし、unavailable inclusion は explicit option を必須にする
  - 完了時には `--limit` が optional cap として機能し、full-scope 実行の必須安全条件にはならない
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 11.1, 11.2, 12.2, 14.2_
  - _Depends: 2.2, 2.3_

- [x] 6.2 Recalculation batch processing workflow を実装する
  - pending または stale work item を bounded chunk で claim する
  - each work item は Request Performance Calculation workflow を通して replacement calculation を作成する
  - replacement が completed または unavailable の terminal state になるまで old current PP を維持する
  - worker side は batch use-case を taskiq state に登録する
  - 完了時には worker 停止後も stale work が後続 worker に再claimされ、batch progress が進む
  - _Requirements: 8.5, 11.3, 11.4, 11.5, 11.6, 12.3, 12.4_
  - _Depends: 4.1, 6.1_

- [ ] 6.3 PP recalculation CLI を追加する
  - operator command は dry-run を既定にし、execution は explicit flag で durable work を作る
  - score id、beatmap id、user id、ruleset、limit、all、include-unavailable を validation する
  - CLI process は calculator を import せず、raw SQL も実行しない
  - 完了時には dry-run summary または batch id と candidate breakdown が operator に表示される
  - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 11.2, 14.5_
  - _Depends: 6.1_

- [ ] 7. End-to-end validation と scope boundary を固める
- [ ] 7.1 Stable submit の PP response scenarios を検証する
  - Ranked / Approved passed score は bounded wait 内完了で PP 付き completed response を返す
  - bounded wait 内に終わらない場合は retryable response を返し、後続 retry で current PP を返す
  - unavailable calculation は accepted completed response と `pp:0` に収束する
  - 完了時には same submission fingerprint retry が duplicate PP row を作らず既存 score response を返す
  - _Requirements: 1.1, 1.2, 1.5, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 6.1, 6.2, 6.3, 6.4, 6.5, 7.1, 7.2, 7.3, 7.4, 7.5, 13.2, 13.3, 13.4_
  - _Depends: 5.3_

- [ ] 7.2 Worker と recalculation の recovery scenarios を検証する
  - duplicate calculation request と duplicate worker claim が one current result に収束する
  - calculator version mismatch と Formula Profile mismatch が recalculation candidate になる
  - large batch が bounded chunk で進み、lost wake-up や stale claim 後も再開できる
  - 完了時には profile migration run が CLI execute から batch processing まで durable に処理される
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 12.2, 12.3, 12.4, 14.2_
  - _Depends: 6.2, 6.3_

- [ ] 7.3 Future scope boundary regressions を検証する
  - Loved / Qualified / failed score は Score として保存されても Performance Calculation row を作らない
  - leaderboard projection、user stats、user rank projection を更新しない
  - replay file parsing を PP calculation input として使わない
  - 完了時には Loved PP、Relax PP、Autopilot PP が未実装 scope として明確に残る
  - _Requirements: 1.3, 1.4, 2.3, 2.4, 9.6, 12.5, 15.1, 15.2, 15.3, 15.4, 15.5_
  - _Depends: 7.1, 7.2_

- [ ] 7.4 Quality gates と architecture boundaries を確認する
  - unit、integration、E2E coverage が performance domain、repositories、worker、stable submit、CLI を通る
  - type checking、lint、format、import boundary checks が新しい performance subsystem を含めて通る
  - implementation review で stable client と worker の externally observable behavior が保持されていることを確認する
  - 完了時には project test gate と quality gate が成功し、未検証項目が残っていない
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 6.2, 6.3, 6.4, 6.5, 7.1, 7.2, 7.3, 7.4, 7.5, 8.1, 8.2, 8.3, 8.4, 8.5, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 12.1, 12.2, 12.3, 12.4, 12.5, 13.1, 13.2, 13.3, 13.4, 14.1, 14.2, 14.3, 14.4, 14.5, 15.1, 15.2, 15.3, 15.4, 15.5_
  - _Depends: 7.3_
