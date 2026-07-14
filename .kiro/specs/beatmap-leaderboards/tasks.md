# Implementation Plan

- [ ] 1. Beatmap Leaderboard の基盤語彙と永続 schema を作る
- [x] 1.1 Leaderboard scope、rank、mod filter の domain policy を定義する
  - score 降順、submitted_at 昇順、score_id 昇順で candidate の優劣を判定できるようにする
  - Selected Modsはrequestと保存済みraw bitflagの完全一致とし、NC/DT、PF/SD、NoModをquery-time正規化しない
  - Mirror selected filterを通常のraw bitflagとして扱い、score表示用modsはsource Scoreの値を保持する
  - 完了時にはrank ordering、tie-break、NoMod、DT/NC分離、SD/PF分離、Mirror exact matchのunit testsが通る
  - _Requirements: 2.1, 2.2, 2.6, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 9.4_

- [x] 1.2 Leaderboard visible user policy と Friends eligible user set を固める
  - public leaderboard visibility は NORMAL と UNRESTRICTED の両方を直接要求し、ADMIN bypass を使わない
  - Friends leaderboard 用 eligible user set は viewer ID と current friend target IDs を返す
  - stable login 用 friends list は target-only のまま維持する
  - 完了時には viewer-only、viewer plus friends、reverse-only exclusion、restricted viewer PB suppression の tests が通る
  - _Requirements: 3.7, 4.3, 4.4, 4.6, 6.3, 6.4, 6.5, 6.6, 6.7_

- [x] 1.3 Leaderboard projection と score eligibility の schema migration を追加する
  - Score に submission-time leaderboard eligibility evidence を保存できるようにする
  - beatmap/ruleset/playstyle/user/raw modsのnatural identityごとに1行のscore-priority projectionを保存し、current checksumを置換可能なfreshness属性として保持する
  - `score_id` uniquenessをschema migrationで保証し、Score candidate indexは0500でconcurrent作成して0700で定義とvalidityを再検証し、Global/Selected Mods ranking indexも0700でconcurrent作成する
  - 完了時には migration 適用後に projection table、score eligibility column、constraints、indexes が検証できる
  - _Requirements: 2.1, 2.2, 2.6, 5.7, 6.1, 6.2, 7.2, 10.5_

- [x] 1.4 Legacy Personal Best migration path を安全に置き換える
  - 既存のvalid Personal Best rowsを初期Global projectionへ移し、後続migrationでraw Mod別projectionへ再構築できるようにする
  - source Score が存在しない legacy rows は移行せず、diagnostics として観測できるようにする
  - forward migrationではSelected Mods重複rowを削除し、downgradeではsource ScoreからGlobal/Selected Mods rowを再構築する
  - 完了時にはold/new schemaのPostgreSQL round-trip testsがsource-missing skip、stale-checksum Global rowの置換、legacy projection復元を確認できる
  - _Requirements: 2.1, 3.1, 3.4, 6.2, 7.2, 10.5_

- [x] 1.5 Closed-set persistence とclaim lifecycleをEnum migrationへ統合する
  - Score、Beatmap fetch、Score Submission、Score Performance、Blobなどの閉集合値をdomain EnumとSQLAlchemy非native Enumで一致させ、文字列+名前付きCHECKとして保存する
  - persistence columnは原則`NOT NULL`とし、calculation claimは処理中state、recalculation work item claimは`claimed` stateに限定し、それ以外ではpairを`NULL`へ戻す
  - Alembic data migrationはSQLAlchemy式を使い、PostgreSQL `USING`だけ最小のtextual DDL fragmentとして理由を記録する
  - 完了時にはout-of-set validation、Enum bind、read-time mod predicate、window rank、upgrade/downgrade round-tripの実PostgreSQL testsが通る
  - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8, 11.9, 11.10_

- [x] 1.6 Raw Mod別projection migrationを追加する
  - `mods NOT NULL`と非負CHECKを追加し、natural keyをbeatmap/ruleset/playstyle/user/modsへ拡張する
  - current-checksum eligible source Scoresから同一user・同一Modのwinnerを再構築する
  - schema/data移行とrank index DDLを分離し、後続migrationのautocommit blockでGlobal/Selected Mods indexをconcurrent作成する
  - downgradeではuserごとのGlobal all-mods winnerへ戻し、再upgradeでraw Mod別行へ復元する
  - 完了時には実PostgreSQL round-tripがNoMod、DT、NC|DT、SD、PF|SD、Mirrorと同一Mod重複の収束を確認できる
  - _Requirements: 5.1-5.8, 11.4, 11.5, 11.8, 11.9, 11.10_

- [ ] 2. Projection persistence を command/query 境界で実装する
- [x] 2.1 Beatmap Leaderboard command repository contract と in-memory behavior を実装する
  - candidateが同一raw Mod scopeのcurrent rowより高rankの場合だけreplacementする
  - same score and submitted_at では lower score_id を上位として扱う
  - explicit projection slice replacement は empty rows でも stale rows を削除できるようにする
  - in-memory state が commit/rollback 付きで projection rows と slice replacement を保持できるようにする
  - Global best readは全Mod scopeからuserの最高行を選び、完了時にはupsert、tie-break、score_id uniqueness、checksum replacement、empty slice replacementを確認できる
  - _Requirements: 2.1, 2.2, 2.6, 5.7, 8.1, 8.2, 8.3, 10.5_
  - _Boundary: Beatmap leaderboard command repo_
  - _Depends: 1.1, 1.3_

- [x] 2.2 SQLAlchemy command persistence を projection schema に接続する
  - command repository は Unit of Work-owned session だけを使い、直接 commit/rollback しない
  - raw Modを含むprojection natural keyとrank key copyを使ってconcurrent upsertをDB constraintで収束させる
  - explicit projection slice replacement は user slice と beatmap slice の両方で stale rows を削除する
  - 完了時には SQLAlchemy command repository tests が in-memory contract と同じ結果を確認できる
  - _Requirements: 2.1, 2.2, 2.6, 5.7, 8.1, 8.2, 8.3, 10.5_
  - _Depends: 2.1_

- [x] 2.3 (P) Beatmap Leaderboard query repository contract と in-memory behavior を実装する
  - top rowsはMod別projectionを起点にsource Score表示情報、current Beatmap、checksum、owner visibilityを適用して読む
  - PB rank は rows と同じ filtered candidate ordering から actual rank を計算する
  - CountryとFriendsはread-time user filterとし、Selected Modsだけprojection modsへのraw bitflag完全一致を使う
  - 完了時には top 50、PB outside top 50、Country/Friends filter、visibility、checksum の in-memory repository contract tests が通る
  - _Requirements: 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 5.1, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 7.1, 7.3, 7.4, 7.6, 8.5, 10.4_
  - _Boundary: Beatmap leaderboard query repo_
  - _Depends: 1.1, 1.2, 1.3_

- [x] 2.4 SQLAlchemy query persistence と PP enrichment を実装する
  - query repositoryはMod別projectionを起点にScore、Beatmap、User/Role、Replay、current Performance Calculationをread-onlyにjoinする
  - rows と PB rank は同じ filtered candidate ordering を使い、rank と display order が diverge しない
  - PP は current Ranked / Approved row の enrichment として返し、missing PP や Loved / Qualified で row を隠さない
  - 完了時にはSQLAlchemy query repository testsがwindow rank、current filters、nullable PP、projection起点SQL、Selected Mods exact mods filterを確認できる
  - _Requirements: 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 5.1, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 7.1, 7.3, 7.4, 7.6, 8.5, 9.1, 9.2, 9.3, 9.4, 10.4_
  - _Depends: 2.3_

- [x] 2.5 Unit of Work と package exports に projection persistence を接続する
  - command Unit of Work から leaderboard command repository を取得できるようにする
  - SQLAlchemy Unit of Work から leaderboard command repository を取得できるようにする
  - old Personal Best command repository 依存を leaderboard update path から取り除く
  - 完了時には Unit of Work contract tests で leaderboard repository の commit/rollback が確認できる
  - _Requirements: 2.1, 2.2, 2.6, 8.1, 8.2, 8.3, 8.4, 10.5_
  - _Depends: 2.2_

- [ ] 3. Score submission と rebuild の command workflows を実装する
- [x] 3.1 Score submit 時の leaderboard eligibility evidence を保存する
  - accepted Score は保存対象のまま、leaderboard adoption eligibility を別 evidence として持つ
  - failed score と submission-time ineligible score は projection、PB、submit PB delta に採用しない
  - pre-promotion score は後から Beatmap が promoted されても projection 候補にしない
  - 完了時には stored-but-ineligible score が durable Score として残り、leaderboard result には出ない tests が通る
  - _Requirements: 6.1, 6.2, 7.2, 8.3_
  - _Depends: 1.3, 2.5_

- [x] 3.2 Submit leaderboard updater を score submission transaction に統合する
  - accepted eligible score は previous Global all-mods best と比較して submit PB delta を作る
  - accepted scoreは同一raw Mod scopeのprojection rowをupsertし、その後全Mod行からGlobal all-mods bestを再選択する
  - Global専用rowは作らず、1つのscore_idをGlobal用とSelected Mods用に重複保存しない
  - idempotency retry は保存済み submit result を返し、projection や PB delta を再計算しない
  - 完了時には eligible submit、lower score submit、ineligible submit、same fingerprint retry の command tests が通る
  - _Requirements: 2.1, 2.2, 2.6, 5.7, 8.1, 8.2, 8.3, 8.4_
  - _Depends: 2.2, 3.1_

- [x] 3.3 Rebuild command workflow を実装する
  - user sliceとbeatmapset sliceのraw Mod別projectionをcurrent-checksum source Scoreから再計算できるようにする
  - explicit projection slice replacement により eligible source がない場合も stale projection rows を消す
  - repeated rebuild は同じ public leaderboard result に収束する
  - 完了時には user rebuild、beatmapset rebuild、empty candidate rebuild、duplicate rebuild の service tests が通る
  - _Requirements: 7.3, 7.4, 7.6, 10.1, 10.2, 10.3, 10.4, 10.5_
  - _Depends: 2.2, 3.1_

- [ ] 4. Beatmap Leaderboard read workflow を実装する
- [x] 4.1 Beatmap header resolution と category guards を leaderboard query に統合する
  - Ranked、Approved、Loved、Qualified の vanilla Beatmap だけ rows/PB を返す
  - unsupported category、non-vanilla、song select/editor、unauthenticated viewer-dependent category は compatible empty listing にする
  - outdated checksum は update-available response にして rows/PB を返さない
  - 完了時には availability、Local-to-Global、unsupported、non-vanilla、song select、outdated checksum の query tests が通る
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 4.8, 7.1, 7.5_
  - _Depends: 2.4_

- [x] 4.2 Viewer-dependent scopes と Personal Best resolution を実装する
  - Global/Country/Friends PBはmods predicateなし、Selected Mods PBだけprojection mods完全一致で解決する
  - authenticated visible viewer の PB は top rows と別枠で返し、top 50 内なら重複表示を許可する
  - non-visible viewer は PB だけ suppress し、public rows は返せるようにする
  - 完了時には PB outside top 50、PB duplicated in rows、Country/Friends viewer guards、non-visible viewer behavior の query tests が通る
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 6.7, 8.5_
  - _Depends: 4.1_

- [x] 4.3 Current filters と PP display enrichment を read path に固定する
  - current Beatmap status、current checksum、score owner visibility、score eligibility を rows と PB rank の両方に適用する
  - current PP がある Ranked / Approved rows だけ PP を expose し、PP availability は rank や visibility に影響させない
  - Loved / Qualified rows は PP がなくても表示できる
  - current checksumやvisibilityでstale projection rowを公開せず、rebuild後にprojectionがsource Scoreへ収束するtestsが通る
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 7.1, 7.3, 7.4, 7.6, 9.1, 9.2, 9.3, 9.4, 10.4_
  - _Depends: 4.2_

- [ ] 5. Stable getscores compatibility surface を更新する
- [x] 5.1 Stable getscores request mapping を leaderboard category に変換する
  - `v=1` は Global、`v=2` は Selected Mods、`v=3` は Friends、`v=4` は Country として扱う
  - unsupported `v` は Global fallback せず header-only empty listing にする
  - selected `mods`はstable raw bitmaskを正規化せずdomain ModCombinationへ変換する
  - 完了時にはcategory mapper testsとstable verification fixtureがLocal、Selected Mods、Friends、Country、unsupported、Mirror exact matchを確認できる
  - _Requirements: 1.3, 1.4, 1.6, 5.1, 5.8_
  - _Depends: 1.1, 4.1_

- [x] 5.2 Stable getscores formatter を rows/PB 分離 contract に更新する
  - score count は returned rows count だけにし、PB row は count に含めない
  - PB row は rows とは別に出力し、top rows 内に同じ Score があっても dedupe しない
  - header-only listing は empty PB と empty rows を stable-compatible に出力する
  - 完了時には formatter tests が count、PB duplicate、PB outside rows、unavailable、update-available を区別できる
  - _Requirements: 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 7.5_
  - _Depends: 4.2_

- [x] 5.3 Stable getscores handler を new leaderboard query result に接続する
  - existing header resolution behavior を維持しつつ supported category では top rows と PB を返す
  - parse errors、not submitted、update available の existing short responses を変えない
  - old Personal Best fallback row behavior を削除し、query result を formatter に渡す
  - 完了時には stable endpoint integration tests が rows plus separate PB と compatible empty responses を確認できる
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.3, 2.5, 3.1, 7.5_
  - _Depends: 5.1, 5.2_

- [ ] 6. Runtime composition と background jobs を接続する
- [x] 6.1 App/test composition に leaderboard repositories と queries を登録する
  - production graph が SQLAlchemy query repository と leaderboard query use-case を解決できるようにする
  - test graph が in-memory repositories と self-inclusive friend query contract を使えるようにする
  - package exports と provider wiring が import boundary に合うようにする
  - 完了時には composition tests で getscores handler と leaderboard query dependencies が解決できる
  - _Requirements: 1.1, 3.1, 4.3, 8.5, 9.1_
  - _Depends: 2.4, 4.3, 5.3_

- [x] 6.2 Worker job adapters と taskiq registration を追加する
  - user visibility change と beatmapset status/checksum change から rebuild job を primitive payload で実行できるようにする
  - job adapter は use-case resolution と payload validation だけを行い、repository construction や SQLAlchemy access を直接行わない
  - missing target は no-op success、persistence failure は observable failure として扱う
  - 完了時には job tests が duplicate job execution と no-op target behavior を確認できる
  - _Requirements: 10.1, 10.2, 10.3, 10.5_
  - _Depends: 3.3_

- [x] 6.3 Submission、visibility、Beatmap change integration points から rebuild/update を呼び出す
  - score submissionはaccepted score pathの中でraw Mod別projection update、Global PB delta、submit snapshotを同じdurable boundaryに収める
  - user visibility、Beatmap status、Beatmap checksum change は public reads を block せず rebuild job を enqueue できる
  - pending rebuild中でもcurrent status、checksum、visibility filterでstale rowを公開しない
  - 完了時にはsubmit integrationとreconciliation integration testsがMod別projection更新と後続収束を確認できる
  - _Requirements: 7.3, 7.4, 7.6, 8.1, 8.2, 8.3, 8.4, 10.1, 10.2, 10.3, 10.4, 10.5_
  - _Depends: 3.2, 3.3, 6.1, 6.2_

- [ ] 7. End-to-end scenarios と future boundary を検証する
- [x] 7.1 Stable getscores category scenarios を end-to-end で検証する
  - Global/Local、Country、Friends、Selected Mods が expected rows、PB、rank、count を返す
  - Friends は viewer 自身を含み、reverse-only relationship を含めない
  - NoMod exact、DTとNC|DTの分離、SDとPF|SDの分離、Mirror exactのstable-visible behaviorが確認できる
  - 完了時には stable endpoint tests が top 50 limit、PB outside top 50、category-specific empty results を通す
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 4.1, 4.2, 4.3, 4.4, 4.5, 4.8, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.8_
  - _Depends: 6.3_

- [x] 7.2 Submit and reconciliation scenarios を end-to-end で検証する
  - accepted eligible scoreはGlobal all-mods submit PB deltaと同一raw Mod scopeのprojection 1行を更新する
  - same fingerprint retry は saved snapshot を返し、PB delta と projection を再計算しない
  - Beatmap status、checksum、user visibility の変更後、pending rebuild 中も public output が current filters に従う
  - 完了時には submit/retry/rebuild integration tests が repeated rebuild convergence を確認できる
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 8.1, 8.2, 8.3, 8.4, 10.1, 10.2, 10.3, 10.4, 10.5_
  - _Depends: 6.3_

- [x] 7.3 PP and stats boundary regressions を検証する
  - current Performance Calculation は display enrichment としてだけ使われ、leaderboard rank には使われない
  - Loved / Qualified や missing PP の rows は score eligibility 条件を満たせば表示される
  - PP-priority Performance Best、User Stats、User Ranking の projection は作成または更新しない
  - 完了時には future user-stats boundary tests が Beatmap Leaderboard Personal Best と PP-priority best の分離を確認できる
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_
  - _Depends: 4.3, 7.1_

- [x] 7.4 Quality gates と architecture boundaries を確認する
  - unit、repository contract、integration tests が domain、persistence、query、command、stable transport、jobs を通る
  - basedpyright、ruff、ruff format、import-linter が新しい leaderboard subsystem を含めて通る
  - implementation review で stable client と worker の observable behavior が design と一致していることを確認する
  - 完了時には relevant test gate と quality gate が成功し、未検証項目が残っていない
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 8.1, 8.2, 8.3, 8.4, 8.5, 9.1, 9.2, 9.3, 9.4, 9.5, 10.1, 10.2, 10.3, 10.4, 10.5_
  - _Depends: 7.1, 7.2, 7.3_

## Implementation Notes

- 6.3: rebuild wake boundary は `services.commands.leaderboard_rebuild_wake` に置き、beatmaps/identity command から score command package を runtime import しない。
