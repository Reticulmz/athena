# Implementation Plan

- [ ] 1. Beatmap Leaderboard の基盤語彙と永続 schema を作る
- [x] 1.1 Leaderboard scope、rank、mod filter の domain policy を定義する
  - score 降順、submitted_at 昇順、score_id 昇順で candidate の優劣を判定できるようにする
  - all-mods、NoMod、Selected Mods の filter key を区別し、NC/DT と PF/SD を canonical key に正規化する
  - Mirror selected filter は unsupported として扱い、score 表示用 mods は source Score の値を保持する
  - 完了時には rank ordering、tie-break、NoMod、NC/DT、PF/SD、Mirror unsupported の unit tests が通る
  - _Requirements: 2.1, 2.2, 2.6, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 9.4_

- [x] 1.2 Leaderboard visible user policy と Friends eligible user set を固める
  - public leaderboard visibility は NORMAL と UNRESTRICTED の両方を直接要求し、ADMIN bypass を使わない
  - Friends leaderboard 用 eligible user set は viewer ID と current friend target IDs を返す
  - stable login 用 friends list は target-only のまま維持する
  - 完了時には viewer-only、viewer plus friends、reverse-only exclusion、restricted viewer PB suppression の tests が通る
  - _Requirements: 3.7, 4.3, 4.4, 4.6, 6.3, 6.4, 6.5, 6.6, 6.7_

- [x] 1.3 Leaderboard projection と score eligibility の schema migration を追加する
  - Score に submission-time leaderboard eligibility evidence を保存できるようにする
  - user/beatmap/ruleset/playstyle/mod filter scope ごとの score-priority projection を保存できるようにする
  - all-mods と NoMod を区別できる uniqueness と ordering indexes を用意する
  - 完了時には migration 適用後に projection table、score eligibility column、constraints、indexes が検証できる
  - _Requirements: 2.1, 2.2, 2.6, 5.7, 6.1, 6.2, 7.2, 10.5_

- [x] 1.4 Legacy Personal Best migration path を安全に置き換える
  - 既存の valid Personal Best rows を all-mods projection へ移せるようにする
  - source Score が存在しない legacy rows は移行せず、diagnostics として観測できるようにする
  - Selected Mods projection は source Score から rebuild/backfill する前提にする
  - 完了時には old projection から new projection への migration tests が source-missing skip を確認できる
  - _Requirements: 2.1, 3.1, 3.4, 6.2, 7.2, 10.5_

- [ ] 2. Projection persistence を command/query 境界で実装する
- [x] 2.1 Beatmap Leaderboard command repository contract と in-memory behavior を実装する
  - candidate が current row より高 rank の場合だけ replacement する
  - same score and submitted_at では lower score_id を上位として扱う
  - explicit projection slice replacement は empty rows でも stale rows を削除できるようにする
  - in-memory state が commit/rollback 付きで projection rows と slice replacement を保持できるようにする
  - 完了時には command repository contract tests が upsert、tie-break、multi-key score、empty slice replacement を in-memory 実装で確認できる
  - _Requirements: 2.1, 2.2, 2.6, 5.7, 8.1, 8.2, 8.3, 10.5_
  - _Boundary: Beatmap leaderboard command repo_
  - _Depends: 1.1, 1.3_

- [x] 2.2 SQLAlchemy command persistence を projection schema に接続する
  - command repository は Unit of Work-owned session だけを使い、直接 commit/rollback しない
  - projection natural key と rank key copy を使って concurrent upsert を DB constraint で収束させる
  - explicit projection slice replacement は user slice と beatmap slice の両方で stale rows を削除する
  - 完了時には SQLAlchemy command repository tests が in-memory contract と同じ結果を確認できる
  - _Requirements: 2.1, 2.2, 2.6, 5.7, 8.1, 8.2, 8.3, 10.5_
  - _Depends: 2.1_

- [x] 2.3 (P) Beatmap Leaderboard query repository contract と in-memory behavior を実装する
  - top rows は projection から current Beatmap、checksum、passed、submission eligibility、owner visibility を適用して読む
  - PB rank は rows と同じ filtered candidate ordering から actual rank を計算する
  - Country と Friends は read-time filter とし、Selected Mods は mod filter key を使う
  - 完了時には top 50、PB outside top 50、Country/Friends filter、visibility、checksum の in-memory repository contract tests が通る
  - _Requirements: 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 5.1, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 7.1, 7.3, 7.4, 7.6, 8.5, 10.4_
  - _Boundary: Beatmap leaderboard query repo_
  - _Depends: 1.1, 1.2, 1.3_

- [x] 2.4 SQLAlchemy query persistence と PP enrichment を実装する
  - query repository は projection、Score、Beatmap、User/Role、Replay、current Performance Calculation を read-only に join する
  - rows と PB rank は同じ filtered candidate ordering を使い、rank と display order が diverge しない
  - PP は current Ranked / Approved row の enrichment として返し、missing PP や Loved / Qualified で row を隠さない
  - 完了時には SQLAlchemy query repository tests が window rank、current filters、nullable PP、projection-based SQL を確認できる
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
  - score の actual mods から all matching projection scopes を更新する
  - idempotency retry は保存済み submit result を返し、projection や PB delta を再計算しない
  - 完了時には eligible submit、lower score submit、ineligible submit、same fingerprint retry の command tests が通る
  - _Requirements: 2.1, 2.2, 2.6, 5.7, 8.1, 8.2, 8.3, 8.4_
  - _Depends: 2.2, 3.1_

- [x] 3.3 Rebuild command workflow を実装する
  - user slice と beatmapset slice を source Score から再計算できるようにする
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
  - Global/Country/Friends PB は all-mods scope、Selected Mods PB は selected mod filter scope で解決する
  - authenticated visible viewer の PB は top rows と別枠で返し、top 50 内なら重複表示を許可する
  - non-visible viewer は PB だけ suppress し、public rows は返せるようにする
  - 完了時には PB outside top 50、PB duplicated in rows、Country/Friends viewer guards、non-visible viewer behavior の query tests が通る
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 6.7, 8.5_
  - _Depends: 4.1_

- [ ] 4.3 Current filters と PP display enrichment を read path に固定する
  - current Beatmap status、current checksum、score owner visibility、score eligibility を rows と PB rank の両方に適用する
  - current PP がある Ranked / Approved rows だけ PP を expose し、PP availability は rank や visibility に影響させない
  - Loved / Qualified rows は PP がなくても表示できる
  - 完了時には pending rebuild 中の stale projection が public response から隠れる tests が通る
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 7.1, 7.3, 7.4, 7.6, 9.1, 9.2, 9.3, 9.4, 10.4_
  - _Depends: 4.2_

- [ ] 5. Stable getscores compatibility surface を更新する
- [ ] 5.1 Stable getscores request mapping を leaderboard category に変換する
  - `v=1` は Global、`v=2` は Selected Mods、`v=3` は Friends、`v=4` は Country として扱う
  - unsupported `v` は Global fallback せず header-only empty listing にする
  - selected `mods` は stable bitmask から domain mod combination へ変換して filter policy に渡す
  - 完了時には category mapper tests と stable verification fixture が Local、Selected Mods、Friends、Country、unsupported、Mirror selected を確認できる
  - _Requirements: 1.3, 1.4, 1.6, 5.1, 5.8_
  - _Depends: 1.1, 4.1_

- [ ] 5.2 Stable getscores formatter を rows/PB 分離 contract に更新する
  - score count は returned rows count だけにし、PB row は count に含めない
  - PB row は rows とは別に出力し、top rows 内に同じ Score があっても dedupe しない
  - header-only listing は empty PB と empty rows を stable-compatible に出力する
  - 完了時には formatter tests が count、PB duplicate、PB outside rows、unavailable、update-available を区別できる
  - _Requirements: 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 7.5_
  - _Depends: 4.2_

- [ ] 5.3 Stable getscores handler を new leaderboard query result に接続する
  - existing header resolution behavior を維持しつつ supported category では top rows と PB を返す
  - parse errors、not submitted、update available の existing short responses を変えない
  - old Personal Best fallback row behavior を削除し、query result を formatter に渡す
  - 完了時には stable endpoint integration tests が rows plus separate PB と compatible empty responses を確認できる
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.3, 2.5, 3.1, 7.5_
  - _Depends: 5.1, 5.2_

- [ ] 6. Runtime composition と background jobs を接続する
- [ ] 6.1 App/test composition に leaderboard repositories と queries を登録する
  - production graph が SQLAlchemy query repository と leaderboard query use-case を解決できるようにする
  - test graph が in-memory repositories と self-inclusive friend query contract を使えるようにする
  - package exports と provider wiring が import boundary に合うようにする
  - 完了時には composition tests で getscores handler と leaderboard query dependencies が解決できる
  - _Requirements: 1.1, 3.1, 4.3, 8.5, 9.1_
  - _Depends: 2.4, 4.3, 5.3_

- [ ] 6.2 Worker job adapters と taskiq registration を追加する
  - user visibility change と beatmapset status/checksum change から rebuild job を primitive payload で実行できるようにする
  - job adapter は use-case resolution と payload validation だけを行い、repository construction や SQLAlchemy access を直接行わない
  - missing target は no-op success、persistence failure は observable failure として扱う
  - 完了時には job tests が duplicate job execution と no-op target behavior を確認できる
  - _Requirements: 10.1, 10.2, 10.3, 10.5_
  - _Depends: 3.3_

- [ ] 6.3 Submission、visibility、Beatmap change integration points から rebuild/update を呼び出す
  - score submission は accepted score path の中で projection update と submit snapshot を同じ durable boundary に収める
  - user visibility、Beatmap status、Beatmap checksum change は public reads を block せず rebuild job を enqueue できる
  - pending rebuild 中でも read-time filters が public correctness を保つ
  - 完了時には submit integration と reconciliation integration tests が stale projection hidden and later corrected を確認できる
  - _Requirements: 7.3, 7.4, 7.6, 8.1, 8.2, 8.3, 8.4, 10.1, 10.2, 10.3, 10.4, 10.5_
  - _Depends: 3.2, 3.3, 6.1, 6.2_

- [ ] 7. End-to-end scenarios と future boundary を検証する
- [ ] 7.1 Stable getscores category scenarios を end-to-end で検証する
  - Global/Local、Country、Friends、Selected Mods が expected rows、PB、rank、count を返す
  - Friends は viewer 自身を含み、reverse-only relationship を含めない
  - NoMod、NC/DT、PF/SD、Mirror selected の stable-visible behavior が確認できる
  - 完了時には stable endpoint tests が top 50 limit、PB outside top 50、category-specific empty results を通す
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 4.1, 4.2, 4.3, 4.4, 4.5, 4.8, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.8_
  - _Depends: 6.3_

- [ ] 7.2 Submit and reconciliation scenarios を end-to-end で検証する
  - accepted eligible score は Global all-mods submit PB delta と projection rows を更新する
  - same fingerprint retry は saved snapshot を返し、PB delta と projection を再計算しない
  - Beatmap status、checksum、user visibility の変更後、pending rebuild 中も public output が current filters に従う
  - 完了時には submit/retry/rebuild integration tests が repeated rebuild convergence を確認できる
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 8.1, 8.2, 8.3, 8.4, 10.1, 10.2, 10.3, 10.4, 10.5_
  - _Depends: 6.3_

- [ ] 7.3 PP and stats boundary regressions を検証する
  - current Performance Calculation は display enrichment としてだけ使われ、leaderboard rank には使われない
  - Loved / Qualified や missing PP の rows は score eligibility 条件を満たせば表示される
  - PP-priority Performance Best、User Stats、User Ranking の projection は作成または更新しない
  - 完了時には future user-stats boundary tests が Beatmap Leaderboard Personal Best と PP-priority best の分離を確認できる
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_
  - _Depends: 4.3, 7.1_

- [ ] 7.4 Quality gates と architecture boundaries を確認する
  - unit、repository contract、integration tests が domain、persistence、query、command、stable transport、jobs を通る
  - basedpyright、ruff、ruff format、import-linter が新しい leaderboard subsystem を含めて通る
  - implementation review で stable client と worker の observable behavior が design と一致していることを確認する
  - 完了時には relevant test gate と quality gate が成功し、未検証項目が残っていない
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 8.1, 8.2, 8.3, 8.4, 8.5, 9.1, 9.2, 9.3, 9.4, 9.5, 10.1, 10.2, 10.3, 10.4, 10.5_
  - _Depends: 7.1, 7.2, 7.3_
