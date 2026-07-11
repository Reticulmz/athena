# Research

## 互換実装メモ

- 公式 Bancho server 実装は公開されていないため、公開されている公式 osu-web と互換実装を stable compatibility evidence として扱う。
- `ppy/osu-web` の `BeatmapScores` は beatmap score listing の既定 sort を `score_desc` にし、limit を既定 50 にして user ごとに dedupe する。`userBest()` は top rows に viewer の score が含まれていなければ、同じ base params に viewer の user id と size 1 を加えて別取得するため、Personal Best は top 50 rows の外でも返せる。
- `ppy/osu-web` の `BeatmapsController::beatmapScores()` は `scores` と `user_score` / `userScore` を別 field として返す。`BeatmapScores::userBest()` は top rows に viewer score がある場合に `result[$userId]` を返すだけで、`scores` 側から除外しないため、同じ score が top rows と user score の両方に現れる構造になっている。
- `ppy/osu-web` の `ScoreSearchParams` は `score_desc` と `pp_desc` を別 sort として扱い、friends type では friend ids に viewer 自身を含める。`score_desc` は `score desc -> id asc` 相当で、rank 計算側も同 score では `id < beforeScore.id` を上位として扱う。
- `ppy/osu-web` の `beatmap_leaders` table は `score_id` primary key と `beatmap_id` / `ruleset_id` / `user_id` だけを持つ軽い projection で、`score` や hit counts の表示 snapshot は持たない。用途は Beatmap / Ruleset ごとの首位 score であり、`BeatmapLeader::sync()` は `ScoreSearch` の `sort = score_desc` / `limit = 1` から score を選び直す。Athena の `beatmap_leaderboard_user_bests` も Global submit delta、replacement、reconciliationに限定した軽いprojectionとし、public top 50とPersonal Best rankはsource Scoresから導く。
- `ppy/osu-web` の `ScoreSearch` は mods filter に implied mods を使う。`Mods::IMPLIED_MODS` は `NC => DT` と `PF => SD` を含み、filter matching と displayed mods を分ける根拠になる。NoMod filter では excluded mod 集合から `CL` / `PF` / `SD` / `MR` を外しており、preference-only mod を NoMod 候補から除外しない根拠になる。`addModsFilter()` は NoMod subquery と selected-mods subquery を `shouldMatch(1)` で OR するため、preference-only mod を含む score は NoMod filter と explicit preference filter の両方に入り得る。
- `osuAkatsuki/bancho.py` は stable getscores で `LIMIT 50` を使い、vanilla の scoring metric は score を使う。Friends は `player.friends | {player.id}` を使う。row ordering は `ORDER BY _score DESC` のみで、同 score の deterministic tie-break は明示されていない。
- `osuAkatsuki/bancho.py` の stable getscores response は `personal_best_score_row` を先に append し、その後 `score_rows` をそのまま enumerate して append する。PB が top 50 rows に含まれていても除外処理はない。
- `osuAkatsuki/bancho.py` の scores table は raw `mods` と `score` / `pp` / `play_time` などを score record に持ち、`scores_score_index` / `scores_pp_index` / `scores_mods_index` などを張る。Dedicated best projection table は確認できず、leaderboard reads は score rows と indexes から組み立てる方針に見える。Mods leaderboard は raw mods equality で絞るため、NC/DT や PF/SD の implied matching については `ppy/osu-web` のほうを優先根拠にする。
- restricted / non-default user の扱いは公開実装間で差がある。`osuAkatsuki/bancho.py` は submit 時の best status 計算では restricted を見ず、getscores / placement で現在の通常 user privilege を条件にして公開表示から外す。user privilege が戻ると read 条件上は再び候補になり得る。`ppy/osu-web` は score listing / score index 対象で `ranked` score かつ `user->default()` を要求し、公開検索側に non-default user の score を入れない。いずれも score 自体に「restricted 中に提出されたため永久に leaderboard 不可」という専用状態を置く公開根拠は確認できない。
- Viewer 自身が restricted / non-default の場合の public row visibility は、公開実装上は score owner visibility と分離されている。`ppy/osu-web` の `BeatmapScores` / `ScoreSearch` は viewer を country / friend / userBest の条件として使うが、public rows は listing / indexable な score owner から導く。`userBest()` は同じ base params に viewer の user id を加えて検索するため、viewer 自身が listing / index 対象外なら Personal Best は返らない方向になる。`osuAkatsuki/bancho.py` は rows で `u.priv & 1 OR u.id = :user_id` と viewer 自身だけを例外的に含めるため、Athena では official web 実装の分離を優先根拠にする。
- `ppy/osu-web` の `Solo\Score::extractParams()` は score 作成時に `passed && beatmap->approved > 0` から score の `ranked` flag を固定し、`scopeForListing()` / `scopeIndexable()` は `ranked = true` を要求する。後から Beatmap が Ranked / Approved / Loved / Qualified に昇格しても、昇格前に `ranked = false` で保存された score が自動で listing / index 対象へ戻る根拠は確認できない。
- `ppy/osu-web` には `RemoveBeatmapsetSoloScores` job があり、Beatmapset の scoreable state 変更時または Ranked への遷移時に既存 solo score の `ranked` を `false` に更新し、BeatmapLeader を削除する。Qualified から Ranked への昇格でも既存 leaderboard score を無効化する根拠になる。
- `ppy/osu-web` の `RemoveBeatmapsetBestScores` job は Beatmapset 内の legacy best score rows を削除する。Athena では score 原本を削除せず、projection / eligibility を無効化する方針に寄せる。
- `osuAkatsuki/bancho.py` は stable getscores で `bmap.status < RankedStatus.Ranked` の場合に score rows を返さず、leaderboard に出す score は `scores.status = BEST` のみを読む。score submission 側の `calculate_status()` は beatmap の ranked status を見ずに `BEST` を付けるため、status 変更時の永続的な無効化については `ppy/osu-web` のほうを優先根拠にする。

## 決定への反映

- Selected Mods の Personal Best は Global の Personal Best とは別に、Leaderboard Mod Filter 内の自己ベストとして導く。
- Global / Country / Friends / Selected Mods の Personal Best は current checksum の eligible source Scores から read-time に解決する。Selected Mods の場合だけ source Score の actual mods を canonicalize した predicate と request key の一致を要求する。
- Country / Friends の Personal Best は viewer 自身がその Leaderboard Category の eligible set に入る場合だけ返す。Country では viewer country が有効で、viewer 自身の current country がその country に一致する必要がある。Friends は viewer 自身を Friends Leaderboard Eligible Set に含めるため、viewer が Leaderboard Visible User なら自分の Personal Best を返せる。
- Viewer 自身が Leaderboard Visible User ではない場合、Friends category でも public rows は返せるが viewer Personal Best は返さない。Friends Leaderboard Eligible Set に self を含めることと、viewer 自身の Score を Personal Best として表示できることは別条件として扱う。
- Stable getscores request の viewer identity が未認証または不明な場合、Global rows は返せるが Country rows、Friends rows、Personal Best は返さない。Country / Friends / Personal Best は viewer identity に依存する scope として扱う。
- Stable getscores request の `v` が不明または未対応 Leaderboard Category の場合、Global に fallback しない。`Local` だけは Global と同じ候補集合として扱い、それ以外の未対応値は header only / empty leaderboard として返す。
- Personal Best row は stable response の Beatmap Leaderboard rows とは別枠で返す。Viewer の Personal Best が top 50 rows に含まれない場合でも、該当 Leaderboard Scope の Personal Best として返せる。top 50 rows に含まれる場合も、Personal Best row と Beatmap Leaderboard row の両方に同じ Score を表示し、read 側で Beatmap Leaderboard rows から除外しない。stable response の score count は filter 後の全候補数ではなく返却 leaderboard rows の件数だけを表し、Personal Best row は含めない。
- Personal Best row の rank は表示中の Leaderboard Scope 内順位として扱う。Friends では Friends Leaderboard Eligible Set 内、Country では viewer country 内、Selected Mods では Leaderboard Mod Filter 内の順位を返す。
- Beatmap Leaderboard row の rank は stable response で返す rows 内の表示順位として `1..len(rows)` を振る。Personal Best row の rank は top 50 外でも現在の Leaderboard Scope 全体での実順位を計算する。
- Personal Best row の実順位は Beatmap Leaderboard rows の取得件数や stable response の score count とは独立して、同じ Leaderboard Scope と `score desc -> submitted_at asc -> score_id asc` order で計算する。実装では window function または同等の rank query を使い、top 50 外の Personal Best でも正しい scope rank を返す。
- Beatmap Leaderboard の順位計算と projection replacement の tie-break は全 scope で `score desc -> submitted_at asc -> score_id asc` に統一する。`submitted_at` は stable client payload 内の timestamp ではなく、Athena が submission を受理した server-side submission time として扱う。公開実装は `score_id asc` 寄せまたは tie-break 未明示だが、Athena では server-side submission time を先着の意味として使い、`score_id` は同時刻や移行データの最終 fallback にする。
- Score Submit Personal Best Delta は stable score submit request が Leaderboard Category を入力に持たないため、Global / all-mods の score-priority Personal Best だけを対象にする。Country / Friends / Selected Mods の Personal Best は stable getscores の read 時に Leaderboard Scope から解決する。現行コードも `SubmitScoreCommand.personal_best_category = LeaderboardCategory.GLOBAL` を既定値にしており、stable submit mapper から category を渡していない。
- 同一 submission fingerprint の retry は idempotency replay として保存済み submission snapshot から結果を返し、`beatmap_leaderboard_user_bests` の upsert や Score Submit Personal Best Delta の再計算を再実行しない。projection 欠落、schema migration、visibility 変更、beatmap 更新などによる補正は rebuild job の責任にする。
- Beatmap Leaderboard rows は score 順の表示であり、current Performance Calculation が未完了でも表示対象にする。PP は Ranked / Approved score に current Performance Calculation がある場合だけ表示できる enrichment として扱う。stable getscores の score row 形式には PP field がないため、stable row 表示は PP 欠落に依存しない。
- Score row の displayed mods は Score に保存された実modsを使う。filter matching 用の normalized key は displayed mods を書き換えない。
- Selected Mods の NoMod filter は osu-web 寄せで、gameplay-affecting mod がない Score を候補にする。PF / SD などの preference-only mod は displayed mods として保持するが、NoMod 候補からは除外しない。
- NoMod filter から除外しない preference-only mods は初期実装では SD / PF / MR とし、NC は DT 系 gameplay mod として扱う。osu-web の `ScoreSearch::addModsFilter()` は NoMod 除外対象から CL / PF / SD / MR を外す一方、NC は implied DT として selected mods matching に残るため、Athena でも NoMod に NC score を混ぜない。
- MR は stable supported mods に含まれるが、beatmap-leaderboards 初期 scope では explicit MR filter を実装対象外にする。NoMod candidate 判定では preference-only mod として扱い、MR を含む score を NoMod から除外しない。
- Selected Mods で SD または PF を明示選択した場合は、NoMod とは異なり SD/PF 系の Score だけを候補にする。SD score と PF score は同じ Leaderboard Mod Filter に属するが、displayed mods は実 Score mods を保持する。
- Selected Mods の複数 mod filter は osu-web 寄せで、選択された gameplay-affecting mod をすべて要求し、未選択の gameplay-affecting mod を含む Score を候補から外す。例: `HD+DT` は HD を含み、DT/NC 系を含み、他の gameplay-affecting mod を含まない Score を候補にする。
- マイグレーションは許容されるため、既存 `personal_bests` の category だけに意味を押し込まず、公開readの正本を `scores`、submit delta/reconciliation用の派生状態をGlobal-only projectionとして分離する。
- 既存 `personal_bests` は score 優先のGlobal all-mods projection `beatmap_leaderboard_user_bests` にリネーム/再構成する。旧 `personal_bests` table は互換用に残さず、PP優先の譜面別代表Scoreは `beatmap_performance_bests` として別projectionにする。
- 既存の有効なGlobal rowはcurrent Beatmap checksumと一致するsource Scoreに限って移行し、Selected Modsの重複rowはforward migrationで削除する。
- Migration 時は旧 `personal_bests.ranking_value` だけに依存せず、旧 row の `score_id` から `scores.score` / `scores.submitted_at` / `scores.id` を join して新 `beatmap_leaderboard_user_bests` の ranking keys を埋める。旧 `ranking_value` は score と一致するかの検証/補助に留める。
- Migration / backfill 中に source score が存在しない旧 `personal_bests` row は新 projection に移行しない。Projection は source score から導く view なので、source がない代表 row は温存せず、必要に応じて migration log / metric に件数を出す。
- `beatmap_leaderboard_user_bests` は Beatmap / Ruleset / Playstyle / User ごとのGlobal all-mods score-priority projectionとして扱い、mod filter dimensionを持たない。`beatmap_checksum`はその1行が表すcurrent revisionを示す非`NULL`の置換可能なfreshness属性とする。
- `beatmap_leaderboard_user_bests` のuniquenessは `beatmap_id, ruleset, playstyle, user_id` で定義し、checksum更新時も同じnatural identityの行を置き換える。`score_id`にも一意制約を置いて1 source Scoreから複数projection rowが作られないようにする。
- Selected Modsのcanonical integer keyはsource Scoreのactual modsからquery時に導く。NCとDT、PFとSDを同じkeyへ正規化し、NoMod互換を含む複数一致を追加columnやprojection rowなしで表現する。
- Generated keysはscore自身のcanonical keyと、NoMod条件を満たす場合の`0`だけを生成する。HD+DT scoreからHD単独やDT単独のsubset keyは生成しない。
- Public Global / Country / Friends readsはmods predicateを持たず、Selected Modsの場合だけactual modsへのcanonical bitwise predicateで絞る。Displayed modsは常にsource Scoreの実値を使う。
- 1つのscore submissionはGlobal all-mods projectionを最大1行だけupsertする。Selected Mods、Country、Friendsの代表Scoreは永続化せず、source Scoresからread-timeに導出する。
- Downgradeではnullable `mod_filter_key` を持つ旧schemaを復元し、current-checksum eligible source Scoresと同じcanonical SQLAlchemy式からlegacy Global/Selected Mods rowsを再構築する。
- `beatmap_leaderboard_user_bests` は `score_id` に加えて ranking keys として `score` / `submitted_at` / `score_id` を projection 側にも保持する。Score 原本の source of truth は `scores` のままだが、Global submit delta、upsert replacement、reconciliationを同じ `score desc -> submitted_at asc -> score_id asc` で実行するため、projection に並び替え key を持たせる。Public top rowsとPersonal Best rankはsource Scoresから導き、表示用 hit counts、username、country などの snapshot は持たせない。
- Beatmap Leaderboard rowsのread queryはeligible source Scoresを起点にし、Beatmap、User/Role、Replay、current Performance Calculationをjoinしてuser bestとrankをwindow functionで導出する。Global projectionの欠落や遅延はpublic outputへ影響させない。
- Selected ModsのNoModはcanonical modsからgameplay-affecting bitsがないことをquery時に判定し、Global projectionとは別rowを作らない。
- `beatmap_leaderboard_user_bests` の既存 entry は、同じ scope の候補 Score が score 優先順で既存 entry を上回る場合だけ置き換える。score が同点の場合は Beatmap Leaderboard Rank の tie-break を使い、server-side submission time が早い Score、次に Score ID 昇順を優先する。
- `beatmap_leaderboard_user_bests` は score submission 成功時に score 原本保存と同じ Unit of Work 内で upsert する。worker job は user visibility、beatmap status、checksum 変更、schema migration、projection 欠損などの rebuild / 補正に使い、通常 submit の即時反映を worker completion に依存させない。現行 `personal_bests` も score 作成後、同じ command transaction 内で `upsert_if_better` してから commit している。
- 通常 submit path の projection upsert は current Beatmap status、current checksum、passed、submission-time eligibility を満たす score に限定する。User visibility は hidden projection を許容するが、beatmap/checksum/failed の競技条件を満たさない score は `beatmap_leaderboard_user_bests` に入れない。
- 1つの score submission はGlobal all-mods entryだけを更新対象にする。Country、Friends、Selected Modsは専用projectionを持たず、read時にsource Scoresへviewer/filter条件を適用する。
- Country Leaderboard は Score owner の現在 country で read-time filter する。Score submission 時点の country snapshot は持たず、country 変更時も Beatmap Leaderboard projection rebuild は不要とする。
- Country Leaderboard で viewer country が未設定または `XX` の場合、Country rows と Personal Best は候補なしとして返す。`XX` を国別ランキングの国コードとして扱わない。
- Friends Leaderboard は viewer の現在 Friend Relationship targets と viewer 自身で構成する Friends Leaderboard Eligible Set により read-time filter する。Friend 追加/削除時に Beatmap Leaderboard projection rebuild は不要とする。
- Restricted などで Leaderboard Visible User ではなくなった user の entry は削除しない。Beatmap Leaderboard rows と Personal Best は read 時に現在の user visibility で絞り、制限解除時に過去の正当な score を再表示できるようにする。
- Leaderboard Visible User ではない状態で提出された score は score record として保存し、`beatmap_leaderboard_user_bests` の hidden projection も通常通り upsert できる。ただし、その user が Leaderboard Visible User ではない間は read-time visibility filter により Beatmap Leaderboard rows、Personal Best、Beatmap Leaderboard Rank の表示対象にはしない。制限解除などで user visibility が戻った場合は、既存 projection と rebuild job により過去の保存済み score も候補に戻せる。
- Viewer 自身が Leaderboard Visible User ではない場合でも、認証済みで stable getscores を叩けるなら public Beatmap Leaderboard rows は表示する。ただし Viewer 自身の Personal Best は Leaderboard Visible User の Score ではないため返さない。
- Admin / moderator などの operator が非表示 Score を調査する内部表示は public Beatmap Leaderboard とは別 surface とし、beatmap-leaderboards の初期 scope には含めない。将来 spec として roadmap の `operator-leaderboard-inspection` に残す。
- User visibility が変わった場合、全 leaderboard を同期的に再計算しない。対象 user の Beatmap Leaderboard projection rebuild を worker job として投げ、read 時の visibility filter と組み合わせて整合性を回復する。
- Beatmap Leaderboard projection rebuild は user visibility、beatmap status、checksum 変更などの運用イベントごとに対象 user または対象 beatmapset 単位の差分 worker job として積む。通常 path で全件同期 rebuild は行わない。schema migration や大規模補正に必要な full backfill は別の管理用 batch 経路に分ける。
- Rebuild worker は `jobs/` 配下の薄い taskiq adapter から起動し、`services/commands/scores/leaderboards/...` の command use-case に委譲する。task payload は primitive のみを受け取り、`user_id`、`beatmapset_id`、`reason` などの最小情報にする。既存の score performance job と同じ adapter/use-case 分離を維持する。
- Rebuild job は idempotent にし、同じ `user_id` / `beatmapset_id` / reason が重複投入されても、score 原本と current Beatmap/User state から同じ final projection へ収束すれば成功扱いにする。
- Projection rebuildはscore原本からcurrent checksumのGlobal候補を再評価し、同一 `beatmap_id, ruleset, playstyle, user_id` 内で `score desc -> submitted_at asc -> score_id asc` の先頭scoreを選び直す。勝者の`beatmap_checksum`をfreshness属性として同じnatural identityの行へ保存し、候補が存在しない場合はprojection rowを削除してscore原本は保持する。
- Beatmap Leaderboard read pathはprojectionを参照せず、current Beatmap status、current checksum、Score owner visibility、passed / submission-time eligibilityをsource Scoresへ直接適用する。
- `beatmap_performance_bests` は `user-stats` 側の PP 優先 projection とし、Beatmap / Ruleset / Playstyle / User ごとに、PP が既存 entry を上回る場合だけ置き換える。PP 同点時の tie-break は `pp desc -> submitted_at asc -> score_id asc` とし、Beatmap Leaderboard の順位付けには使わない。
- `beatmap_performance_bests` も failed score は候補外にし、PP が存在する passed score だけを対象にする。PP 優先 projection の ownership は user-stats 側だが、Beatmap Leaderboard の Personal Best と同様に failed score を代表 score にしない。
- `beatmap_performance_bests` は current Performance Calculation の PP を入力にする。Calculator 更新や performance recalculation により PP が変わった場合は、user-stats 側の rebuild / replace workflow が `beatmap_performance_bests` を更新する。beatmap-leaderboards ではこの projection を実装せず、dependency / roadmap として扱う。
- beatmap-leaderboards spec は `beatmap_performance_bests` table creation / repository / rebuild workflow を scope に含めない。名前、選択軸、Beatmap Leaderboard の Personal Best との境界だけを固定し、実装は user-stats spec に委譲する。
- Score submission 時点で Beatmap が Leaderboard-visible status ではない場合、score record は保存できるが Beatmap Leaderboard projection には採用しない。後から Beatmap が Ranked / Approved / Loved / Qualified に昇格しても、昇格前に提出された score は projection rebuild で自動採用しない。
- Score の `beatmap_status_at_submission` は submission-time eligibility の監査と、昇格前 score を後から採用しない判断に使う。Projection / read eligibility は submission-time eligible evidence に加えて current Beatmap status と current checksum を見る。downgrade の即時非表示は current Beatmap status filter に依存し、submission-time status だけでは判断しない。
- Design phase では `scores.leaderboard_eligible_at_submission` のような boolean snapshot 追加を検討する。`beatmap_status_at_submission` だけに submission-time eligibility を推論させると status enum の意味変更や legacy migration に弱いため、提出時点の eligibility decision を明示しておく方が長期的に安全。既存 score の backfill ルールは design / migration で別途定義する。
- Failed Score は score record として保存できるが、`leaderboard_eligible_at_submission = false` 相当として扱い、Beatmap Leaderboard rows、Personal Best、Beatmap Leaderboard projection の候補にしない。Projection 対象は passed score に限定する。
- Beatmap が Leaderboard-visible status から外れた場合、score record は削除せず、read-time beatmap status filter で即時に非表示にし、関連する Beatmap Leaderboard projection rebuild を worker job として投げて削除/補正する。互換上の「既存 score 無効化」は score 原本削除ではなく、leaderboard eligibility / projection から外すこととして扱う。
- Beatmap file checksum が変わった場合、更新前 checksum で提出された score record は保存したまま、current Beatmap checksum と一致しないため Beatmap Leaderboard projection には採用しない。stable getscores は古い checksum の request を update available として扱い、更新後の leaderboard は更新後 checksum で提出された score から始める。
- Beatmap checksum change に伴う projection rebuild は、更新後 current checksum と一致する score だけを候補にする。旧 checksum score を指す `beatmap_leaderboard_user_bests` row は削除または別候補に置き換え、旧 score 原本は保存する。

---

# Gap Analysis 2026-06-18

## 前提

- `requirements.md` は生成済みだが未承認である。Gap analysis は設計フェーズの材料として進め、requirements の修正が必要になり得る点は `Research Needed` として残す。
- 調査対象は stable getscores、score submission、Personal Best、Score / Beatmap / Performance / Friend / User visibility の既存実装である。
- 外部依存の新規調査は不要と判断した。既存 `research.md` に公式 osu-web / Akatsuki の互換実装調査がすでにあるため、今回の分析は local brownfield gap に集中した。

## Current State Investigation

### 既存 assets

- `src/osu_server/services/queries/scores/beatmap_score_listing.py`
  - stable getscores 用の read-only query use-case。
  - 現状は Beatmap / BeatmapSet header resolution と Global Personal Best の取得だけを行う。
  - Score rows provider、category-specific candidate selection、top 50、row rank は未実装。
  - `_DISPLAYABLE_STATUSES` は Pending / WIP / Graveyard も header 表示対象に含めるため、Leaderboard-visible status と header-displayable status を分ける必要がある。
- `src/osu_server/transports/stable/web_legacy/getscores.py`
  - stable legacy endpoint handler と formatter。
  - 現状は Personal Best を personal-best line と score rows line の両方へ出し、score count も Personal Best 有無で `0/1` にしている。
  - Requirements では score count は Beatmap Leaderboard rows 件数で、Personal Best row は別枠なので formatter contract の変更が必要。
- `src/osu_server/transports/stable/web_legacy/mappers/getscores.py`
  - `m`, `mods`, `v`, `vv`, `s` を parse して domain request に残す。
  - 現状はこれらを row selection に使っていない。Local / Global / Country / Selected Mods / Friends の stable `v` mapping が必要。
- `src/osu_server/domain/scores/personal_best.py`
  - `LeaderboardCategory` と `PersonalBestScope` がある。
  - Scope は `user_id, beatmap_id, ruleset, playstyle, category` だけで、Selected Mods の normalized filter、all-mods と NoMod の区別、country/friend read-time selector を表現できない。
  - `score_beats_personal_best()` は ranking value の大小だけを見るため、`score desc -> submitted_at asc -> score_id asc` tie-break を表現できない。
- `src/osu_server/repositories/sqlalchemy/models/personal_best.py` / `alembic/versions/20260617_0101_add_personal_bests.py`
  - `personal_bests` table は category 付き projection として存在する。
  - `ranking_value` は score の単一値で、ranking keys (`score`, `submitted_at`, `score_id`) や `mod_filter_key` を持たない。
  - Requirements / prior research の `beatmap_leaderboard_user_bests` には schema migration が必要。
- `src/osu_server/services/commands/scores/submit_score.py`
  - Score, Replay, Personal Best update, submission snapshot を同じ Unit of Work 内で commit するパターンがある。
  - Idempotency replay は保存済み `result_snapshot` を返し、Personal Best delta を再計算しないため Requirement 8 と相性が良い。
  - 現状の upsert は Global category の単一 Personal Best だけで、mod filter entries の複数 upsert はない。
- `src/osu_server/services/commands/scores/process_submission.py`
  - Beatmap eligibility / pass/fail を見て `include_personal_best_delta` と `update_personal_best` を決める。
  - `parsed.passed and eligibility.has_leaderboard` の場合だけ Personal Best を更新するので failed score 除外は既存方針と合う。
  - Beatmap が ineligible の場合は score 自体を terminal reject しており、「保存済みだが leaderboard 非対象」の score を扱う requirements とは差分がある。
- `src/osu_server/domain/beatmaps/models.py` / `src/osu_server/services/queries/beatmaps/mirror/eligibility_service.py`
  - Beatmap eligibility は Ranked / Approved / Loved / Qualified を score accepting + leaderboard ありとして扱う。
  - failed score は accepted だが `failed_scores_have_leaderboard=False` として扱う土台がある。
  - `scores.beatmap_status_at_submission` はあるが、explicit な `leaderboard_eligible_at_submission` はない。
- `src/osu_server/domain/scores/mods.py` / `src/osu_server/domain/compatibility/stable/mods.py`
  - Stable bitmask と canonical `ModCombination` の往復はある。
  - Leaderboard Mod Filter policy、NC=>DT / PF=>SD implied matching、NoMod preference-only allowance は未実装。
- `src/osu_server/services/queries/identity/friend_relationships.py`
  - Friend relationship query use-cases は存在する。
  - `GetFriendEligibleUserIdsQuery` は名前上 Friends leaderboard source だが、現状は viewer 自身を含めず friend targets だけを返す。
- `src/osu_server/repositories/sqlalchemy/models/user.py` / `role.py` / `services/queries/identity/permission_service.py`
  - User country は `users.country` にある。
  - Role-derived privileges の計算はある。
  - Leaderboard Visible User を query-side score listing で効率よく判定する dedicated port/policy はない。
- `src/osu_server/repositories/sqlalchemy/models/score_performance.py` / `repositories/sqlalchemy/queries/score_performance.py`
  - Current Performance Calculation は `is_current=true` で取得できる。
  - Leaderboard row への PP enrichment は未接続だが、join 可能な data source はある。
- `src/osu_server/jobs/score_performance.py`
  - taskiq adapter -> command use-case へ委譲する薄い worker pattern がある。
  - Beatmap Leaderboard reconciliation job は未実装だが、pattern は再利用できる。

### 既存テスト資産

- `tests/unit/services/queries/scores/test_legacy_getscores.py`
  - header resolution と Global Personal Best attach を検証している。
  - category / rows / selected mods / country / friends は未検証。
- `tests/unit/transports/web_legacy/test_getscores_formatter.py`
  - 現在は Personal Best を fallback score row として count=1 にする前提がある。Requirements に合わせて更新が必要。
- `tests/integration/test_getscores_endpoint.py`
  - PB projection があると personal-best row と score rows line に同じ row が出ることを検証している。
  - top 50 rows と PB 別枠の新 contract に更新が必要。
- `tests/unit/repositories/test_personal_best_*`
  - current projection の upsert/query contract を検証している。
  - New projection の scope/tie-break/mod filter/backfill contract へ置き換えまたは新設が必要。
- `tests/unit/domain/scores/test_mods.py` と stable mod mapper tests
  - raw bitmask mapping の土台はあるが Leaderboard Mod Filter 専用 policy tests はない。

## Requirement-to-Asset Map

| Requirement | Existing assets | Gap |
| --- | --- | --- |
| R1 Availability and categories | `GetscoresQueryParser`, `BeatmapScoreListingQuery`, `GetscoresStatusMapper` | Missing: stable `v` -> category mapping, Local=Global, unsupported category empty header behavior, non-vanilla empty rows, song select rows/PB suppression beyond current PB suppression. |
| R2 Row selection/order/count | `personal_bests` projection, score model, formatter | Missing: Beatmap Leaderboard rows, top 50, score desc/submitted_at/score_id ordering, count excluding PB, per-user representative selection with tie-break. |
| R3 Personal Best rows | `PersonalBestQueryRepository`, formatter PB line | Constraint: existing PB scope lacks mod filter and visibility/current filters. Missing: category-specific PB rank, top 50 outside rank, PB visibility for non-visible viewer, duplicate PB + row semantics with correct count. |
| R4 Country/Friends | `users.country`, `FriendRelationshipQueryRepository` | Missing: Country/Friends candidate filtering, self-included Friends set, reverse-only exclusion tests, Country `XX` empty behavior, current-country/current-friend read-time filtering. |
| R5 Selected Mods | `Mod`, `ModCombination`, stable raw bitmask mapper | Missing: normalized Leaderboard Mod Filter policy, implied NC/DT and PF/SD matching, NoMod preference-only handling, explicit MR unsupported behavior, multiple gameplay mod filter semantics. |
| R6 Score eligibility/user visibility | Score `passed`, roles/privileges | Missing: Leaderboard Visible User query/policy at listing time, hidden projection/read-time filter, explicit handling of stored but leaderboard-ineligible scores, visibility change reconciliation. |
| R7 Status/checksum freshness | Beatmap effective status, score checksum, update-available path | Constraint: current getscores header can display Pending/WIP/Graveyard and may still fetch PB. Missing: current checksum filter on rows/PB, submission-time eligibility snapshot, old checksum score exclusion, promotion/downgrade reconciliation trigger. |
| R8 Submit PB delta | `SubmitScoreUseCase`, submission snapshot idempotency | Partially present for Global all-mods. Missing: new projection scope, tie-break replacement, multiple mod-scope upserts, explicit no-recalc on retry after projection model migration. |
| R9 Performance display/stats boundary | Current Performance Calculation query | Missing: leaderboard row enrichment with PP, Ranked/Approved-only PP display policy, explicit separation from future `beatmap_performance_bests`. |
| R10 Operational reconciliation | score performance taskiq job pattern | Missing: leaderboard reconciliation command use-cases, job adapters, work selection, idempotent rebuild, event triggers on user visibility/beatmap status/checksum changes. |

## Key Gaps And Constraints

### Data model gaps

- Existing `personal_bests` is too narrow for Beatmap Leaderboard requirements. It cannot distinguish all-mods from NoMod, cannot normalize NC/DT or PF/SD, and cannot compute deterministic tie-break without joining source Score.
- `Score` lacks an explicit `leaderboard_eligible_at_submission` style snapshot. `beatmap_status_at_submission` exists, but design should avoid inferring a durable eligibility decision only from status text.
- `scores` indexes are currently `user_id`, `beatmap_id`, `submitted_at` only. Backfill/rebuild and direct candidate scans would need more selective access paths or a projection-first read model.
- User visibility is derived from roles, not stored on users. Query design must decide whether leaderboard reads join roles/permissions directly, use a query-side authorization projection, or ask a permission use-case outside SQL.

### Query/read path gaps

- `BeatmapScoreListingQueryRepository` only resolves beatmap identity and beatmapset; it does not list scores.
- `PersonalBestQueryRepository` returns a stable-specific `GetscoresPersonalBest`, which couples repository contract to stable compatibility shape. Full Beatmap Leaderboard rows should likely use a domain/query result type and let stable/Web mappers adapt it.
- Current formatter assumes one optional score row, not a separate `personal_best` plus `rows` collection.

### Command/rebuild gaps

- Submit path has a good same-UoW persistence pattern but only updates one Global projection.
- Rebuild/backfill requires command-side candidate selection and replace/delete operations not present in current repositories.
- No job adapter exists for leaderboard reconciliation. Score performance jobs provide the closest local pattern.
- Beatmap metadata/status changes currently do not publish durable leaderboard reconciliation work. Beatmap rank management is a future spec, so trigger integration remains partially unknown.

### Compatibility/test gaps

- Stable `v` numeric mapping is parsed but not interpreted. Design must pin the mapping for Global / Local / Country / Selected Mods / Friends and unsupported values.
- Existing formatter tests encode MVP assumptions that conflict with requirements (`score_count=1` when only PB exists).
- No tests exist for NC/DT, PF/SD, NoMod preference-only, top 50, PB outside top 50, country/friend visibility, or user visibility filtering.

## Implementation Approach Options

### Option A: Extend Existing Components

Extend `personal_bests`, `BeatmapScoreListingQuery`, `PersonalBestQueryRepository`, and `format_getscores_header_response` in place.

**Pros**
- Smaller initial file count and fewer dependency wiring changes.
- Reuses existing submit-time Personal Best upsert pattern.
- Fastest path to a minimally functional Global leaderboard.

**Cons**
- Existing names and contracts would become misleading: `personal_bests` would need to carry Beatmap Leaderboard row projection semantics.
- `PersonalBestQueryRepository` is stable-wire-shaped, making Web reuse awkward.
- Category and mod semantics would be bolted onto fields not designed for them.
- Higher risk of retaining the current score_count/PB fallback assumptions.

**Fit**
- Acceptable only for a temporary spike. Not recommended for final implementation because requirements intentionally separated Beatmap Leaderboard Personal Best from Performance Best and require elegant DB design.

### Option B: Create Dedicated Leaderboard Components

Create dedicated Beatmap Leaderboard domain/query/command language and migrate current `personal_bests` into a new score-priority projection.

Candidate components:
- `domain/scores/leaderboards.py` or equivalent for `LeaderboardScope`, `LeaderboardCategory`, `LeaderboardModFilter`, rank ordering, visibility policy inputs.
- `domain/compatibility/stable/leaderboard_mods.py` or similar for stable selected-mod filter normalization.
- command repository for Beatmap Leaderboard user-best upsert/rebuild/delete.
- query repository for Beatmap Leaderboard rows + Personal Best rank in one read model.
- stable getscores result type that contains `header`, `personal_best`, and `rows` separately.
- taskiq adapter and command use-case for reconciliation.

**Pros**
- Cleanest separation of score source, score-priority leaderboard projection, and PP-priority stats.
- Directly supports mod filter keys, all-mods vs NoMod, tie-break keys, and future Web reuse.
- Keeps stable transport as formatter/adapter instead of repository shape owner.
- Allows migration to preserve current data while correcting semantics.

**Cons**
- More schema and repository work upfront.
- Requires broad test updates across command repositories, query repositories, stable formatter, and integration tests.
- Requires careful composition provider wiring and migration/backfill strategy.

**Fit**
- Best fit for the approved requirements and the project's architecture rules.

### Option C: Hybrid Phased Implementation

Use dedicated new domain/query/command contracts, but migrate incrementally:
1. Replace `personal_bests` with score-priority all-mods `beatmap_leaderboard_user_bests`.
2. Implement Global + stable formatter rows first.
3. Add Selected Mods candidate key generation and backfill.
4. Add Country/Friends read-time filters and reconciliation jobs.

**Pros**
- Keeps final architecture close to Option B while reducing implementation risk per phase.
- Lets existing submit idempotency/PB delta behavior remain stable during migration.
- Gives focused test phases.

**Cons**
- Requires strict task boundaries to avoid shipping partial category behavior behind the same endpoint.
- Temporary code paths may exist during migration unless tasks explicitly remove old `personal_bests` semantics.

**Fit**
- Recommended execution style if design chooses Option B as target architecture.

## Effort And Risk

- **Effort: XL (2+ weeks)**
  Requirements touch schema migration, command-side submit updates, query-side row listing, stable response formatting, mod semantics, user/friend/country visibility, and worker reconciliation.
- **Risk: Medium-High**
  Core technical patterns are known in the repository, but compatibility semantics and migration/backfill correctness are sensitive. Main risks are incorrect stable wire shape, hidden user leakage, wrong mod filter equivalence, and projection drift after status/checksum changes.

## Recommendations For Design Phase

- Prefer Option B as target architecture, executed with Option C phasing.
- Rename/restructure current `personal_bests` into a Beatmap Leaderboard score-priority projection instead of extending it as-is.
- Introduce explicit rank ordering value object/policy using `score desc -> submitted_at asc -> score_id asc`; use it in submit replacement, rebuild selection, top rows, and PB rank.
- Add explicit submission-time leaderboard eligibility evidence to Score persistence, rather than deriving it only from `beatmap_status_at_submission`.
- Keep Country and Friends as read-time filters over all-mods projection; do not create country/friend-specific projection rows.
- Implement Leaderboard Mod Filter policy separately from raw stable mod bitmask mapping.
- Keep stable getscores formatting local to stable transport, but make the query result transport-neutral enough for future Web use.
- Base leaderboard reconciliation job design on the existing score performance taskiq adapter + command use-case pattern.
- Apply read-time filters even when projection exists: current Beatmap status, current checksum, passed/submission eligibility, and score owner visibility.

## Research Needed

- Confirm stable `v` numeric values for Global / Local / Country / Selected Mods / Friends against the existing client/protocol fixture before design locks the mapper.
- Decide whether beatmap-ineligible passed scores should be saved by score-ingestion for future audit/history, because current score-ingestion rejects them before score persistence while requirements allow stored leaderboard-ineligible records.
- Decide the exact Leaderboard Visible User policy implementation: `NORMAL | UNRESTRICTED` with or without `ADMIN` bypass from `has_privilege()`.
- Define how Beatmap status/checksum changes will trigger reconciliation before `beatmap-rank-management` exists; this may be a best-effort command hook from beatmap metadata writes initially.
- Decide PostgreSQL uniqueness strategy for all-mods `NULL` and Selected Mods non-NULL keys (`NULLS NOT DISTINCT` vs expression index) in design.
- Define migration behavior for existing `personal_bests` rows whose source Score is missing or whose source Score fails new eligibility filters.

---

# Design Discovery 2026-06-18

## Summary

- **Feature**: `beatmap-leaderboards`
- **Discovery Scope**: Complex Integration
- **Key Findings**:
  - `personal_bests` を延命すると all-mods、NoMod、Selected Mods、tie-break、PP-priority stats 境界が混ざるため、score-priority 専用 projection へ再設計する。
  - stable `getscores` の Local は Athena fixture で `v=1` と確認済みであり、Ripple LETS 実装では `v=2` が mods、`v=3` が friends、`v=4` が country として扱われる。Athena はこの mapping を stable compatibility mapper に閉じ込め、fixture で固定する。
  - Public leaderboard correctness は projection rebuild 完了に依存させず、read-time に current Beatmap status、current checksum、score owner visibility、score eligibility を必ず再評価する。

## Research Log

### Existing Architecture Integration

- **Context**: Requirements 1-10 は stable getscores、score submit、PP calculation、friend relationships、user visibility、Beatmap metadata を横断する。
- **Sources Consulted**:
  - `src/osu_server/services/queries/scores/beatmap_score_listing.py`
  - `src/osu_server/services/commands/scores/submit_score.py`
  - `src/osu_server/services/commands/scores/process_submission.py`
  - `src/osu_server/repositories/interfaces/unit_of_work.py`
  - `src/osu_server/repositories/sqlalchemy/models/personal_best.py`
  - `src/osu_server/repositories/sqlalchemy/models/score.py`
  - `src/osu_server/jobs/score_performance.py`
  - `.kiro/specs/friend-relationships/design.md`
  - `.kiro/specs/score-pp-calculation/design.md`
- **Findings**:
  - Existing getscores query is header-first and does not own row listing.
  - Existing submit command already persists Score, Replay, PB update, and submit snapshot inside one Unit of Work.
  - Friend Relationships intentionally exposes only viewer-owned eligible friend user IDs; score row generation is downstream.
  - Score PP Calculation owns `score_performance_calculations`; leaderboard may read current PP but must not own PP recalculation.
- **Implications**:
  - Beatmap Leaderboard needs its own command/query repository ports and should not stretch `PersonalBestQueryRepository` further.
  - Submit-time projection update should reuse the Unit of Work pattern.
  - Friends and Country are read-time filters, not projection dimensions.

### Stable Compatibility Evidence

- **Context**: Stable `v` mapping is needed for category selection, but requirements intentionally describe category behavior rather than raw wire values.
- **Sources Consulted**:
  - `src/athena_cli/stable_verification/getscores.py`
  - `tests/unit/athena_cli/stable_verification/test_getscores.py`
  - [`osuripple/lets handlers/getScoresHandler.pyx`](https://github.com/osuripple/lets/blob/98e9e07faa48398fbccf17251650011e36bdf6e4/handlers/getScoresHandler.pyx)
- **Findings**:
  - Athena stable verification currently maps probe case `leaderboard_type = "local"` to `v=1` and `vv=4`.
  - Ripple LETS treats scoreboard type `2` as mods, `3` as friends, and `4` as country; other values fall through to normal leaderboard behavior.
  - Some legacy private server behavior gates friends/mods with donor-specific rules. That is not adopted because Athena requirements make Friends and Selected Mods supported categories for authenticated viewers.
- **Implications**:
  - Stable mapper should own `v=1` Local -> Global, `v=2` Selected Mods, `v=3` Friends, `v=4` Country.
  - The mapper and stable verification fixtures must be expanded before implementation is considered complete.

### Data Ownership And Projection Shape

- **Context**: The user explicitly prefers an elegant database design over adding tables as temporary workarounds.
- **Sources Consulted**:
  - Existing `personal_bests` model and migration.
  - Score model, current score indexes, and score performance model.
  - Gap analysis above.
- **Findings**:
  - Public Global/Country/Friends/Selected Mods reads can derive one user best per scope directly from indexed source Scores with a window function.
  - `beatmap_performance_bests` belongs to future user-stats, because its ranking key is PP and it is not a Beatmap Leaderboard row source.
  - Selected Mods compatibility belongs in a read-time policy over each Score's actual mods; storing derived keys or one projection row per key creates redundant state and divergent update paths.
- **Implications**:
  - Public reads use source Scores as the source of truth and apply the Selected Mods canonical mods predicate only for that category.
  - `beatmap_leaderboard_user_bests` stores only the Global all-mods representative needed by submit PB delta and reconciliation.
  - Projection uniqueness is `beatmap_id, ruleset, playstyle, user_id`; current Beatmap checksum is a non-null replaceable freshness attribute, and `score_id` is globally unique inside the table.

### Read-Time Correctness And Reconciliation

- **Context**: Requirements 6, 7, and 10 require public output to remain correct while async rebuild is pending.
- **Sources Consulted**:
  - Score Performance taskiq adapter and worker wiring.
  - Horizontal scaling steering memo.
  - Beatmap eligibility service.
- **Findings**:
  - Worker jobs are suitable for projection rebuild but must be idempotent.
  - User visibility and country/friend changes are current-state reads and should not require synchronous projection mutation.
  - Beatmap status and checksum changes can leave stale Global projection rows, but public reads can remain correct by querying source Scores directly.
- **Implications**:
  - Rebuild jobs converge only the Global projection used by submit-time comparison.
  - Public queries apply all eligibility, checksum, visibility, viewer, and Selected Mods predicates directly to source Scores.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
| --- | --- | --- | --- | --- |
| Extend `personal_bests` | Add mod and rank fields to the current PB table | Smallest initial diff | Keeps misleading name and stable-shaped query contract | Rejected for final design |
| Per-scope leaderboard projection | Store Global and Selected Mods representatives separately | Simple reads after convergence | Duplicates `score_id`, fans out writes, and makes stale projection correctness complex | Rejected |
| Source-score public reads plus Global-only projection | Rank indexed source Scores at read time and keep one Global representative for submit delta | One Score row represents every mod scope; public output is projection-independent | Requires window queries and a read-time mods predicate after indexed Beatmap narrowing | Selected target architecture |

## Design Decisions

### Decision: Use Source Scores For Public Reads And A Global-Only Submit Projection

- **Context**: Beatmap Leaderboard Personal Best is score-priority, while profile/ranking best is PP-priority.
- **Alternatives Considered**:
  1. Keep `personal_bests` and add fields.
  2. Store one projection row for every Global/Selected Mods scope.
  3. Rank source Scores for public reads and keep only the Global submit projection.
- **Selected Approach**: Public rows/PB use source Scores; `beatmap_leaderboard_user_bests` stores one Global all-mods representative per user/current Beatmap checksum; `beatmap_performance_bests` remains owned by user-stats.
- **Rationale**: One Score row can participate in all compatible mod scopes without storing derived keys or duplicate projection rows, while submit PB delta still has a transactional comparison point.
- **Trade-offs**: Read queries are more sophisticated, but the Beatmap candidate partial index narrows rows before the bitwise predicate and projection drift cannot corrupt public output.
- **Follow-up**: Migration must skip source-missing rows, collapse Selected Mods duplicates, and reconstruct legacy scopes on downgrade.

### Decision: Keep Country And Friends As Read-Time Filters

- **Context**: Country and friend relationships are current viewer context and can change independently of score submission.
- **Alternatives Considered**:
  1. Store country/friends-specific projection rows.
  2. Filter Global projection rows at read time.
  3. Filter eligible source Scores at read time.
- **Selected Approach**: Country and Friends query paths filter eligible source Scores by current country or current friend target set without applying a mods predicate.
- **Rationale**: Avoids stale country/friend snapshots and rebuild storms.
- **Trade-offs**: Query joins are heavier, but one window query derives the representative row and actual PB rank from the same candidate set.
- **Follow-up**: Add indexes and query tests for Country/Friends filters.

### Decision: Projection Rebuild Is Corrective, Reads Are Authoritative For Public Filtering

- **Context**: Beatmap status, checksum, and user visibility can change while rebuild jobs are pending.
- **Alternatives Considered**:
  1. Block public reads until rebuild completes.
  2. Return projection state directly.
  3. Revalidate current predicates on every read.
- **Selected Approach**: Rebuild the Global projection asynchronously while public reads rank source Scores independently.
- **Rationale**: Keeps public output correct without coupling stable getscores latency to worker completion or projection freshness.
- **Trade-offs**: Submit PB delta and public PB use different persistence paths that must share the same rank ordering policy.
- **Follow-up**: Integration tests must verify stale Global projection does not affect public rows and rebuild later converges.

### Decision: Score Storage And Leaderboard Adoption Are Separate

- **Context**: The user preference is to keep stored Score records even when they are not public leaderboard candidates.
- **Alternatives Considered**:
  1. Reject every leaderboard-ineligible score before persistence.
  2. Store accepted Score records and mark leaderboard adoption explicitly.
- **Selected Approach**: Add `scores.leaderboard_eligible_at_submission`; projection, rows, PB, and submit PB delta require it to be true.
- **Rationale**: This preserves audit/history value while preventing pre-promotion, failed, old-checksum, or otherwise ineligible scores from entering public competition.
- **Trade-offs**: Score submission must carry one more durable eligibility snapshot.
- **Follow-up**: Submit tests must cover stored-but-ineligible scores that never update `beatmap_leaderboard_user_bests`.

### Decision: Stable Wire Mapping Lives In Compatibility Mapper

- **Context**: Stable `v` values are compatibility input, not core leaderboard domain language.
- **Alternatives Considered**:
  1. Store raw `v` values in query/use-case inputs.
  2. Map to domain category at stable transport boundary.
- **Selected Approach**: Stable mapper converts raw getscores fields into `LeaderboardCategory` and `LeaderboardModFilter`.
- **Rationale**: Web and future first-party surfaces can use the same query use-case without stable wire values.
- **Trade-offs**: The mapper needs explicit compatibility fixtures.
- **Follow-up**: Expand stable verification cases for `v=2`, `v=3`, and `v=4`.

### Decision: Make Friends Leaderboard Eligible User IDs Self-Inclusive

- **Context**: Friends leaderboard requirements include the viewer and the viewer's current friend targets, while the existing friend query implementation currently returns target IDs only.
- **Alternatives Considered**:
  1. Let Beatmap Leaderboard query union the viewer ID locally.
  2. Update `GetFriendEligibleUserIdsQuery` to expose the exact self-inclusive leaderboard contract.
- **Selected Approach**: `GetFriendEligibleUserIdsQuery` becomes the self-inclusive contract for leaderboard consumers; `ListFriendIdsQuery` remains target-only for stable login friends list.
- **Rationale**: This keeps friend relationship semantics in the identity query boundary and prevents every future Friends leaderboard consumer from reimplementing self-inclusion and reverse-edge exclusion.
- **Trade-offs**: Beatmap Leaderboards must update an adjacent query use-case and its tests before consuming it.
- **Follow-up**: Add tests for viewer-only, viewer plus friends, and reverse-only exclusion.

### Decision: Rebuild Replaces Explicit Projection Slices

- **Context**: Reconciliation must converge even when a user or beatmap slice no longer has eligible source scores.
- **Alternatives Considered**:
  1. Infer the slice from rebuilt rows.
  2. Pass an explicit projection slice and replacement rows separately.
- **Selected Approach**: Command repository replacement takes `BeatmapLeaderboardProjectionSlice` and a row tuple, deleting existing rows inside the slice before inserting rebuilt rows.
- **Rationale**: Empty candidate sets become expressible and stale projection rows are removed deterministically.
- **Trade-offs**: Rebuild commands must resolve affected Beatmap IDs before repository replacement.
- **Follow-up**: Repository contract tests must cover empty replacement deleting stale rows.

## Risks & Mitigations

- Wrong stable category mapping could show incorrect rows. Mitigation: add golden fixtures and compatibility tests before implementation completion.
- Projection upsert and rebuild could diverge. Mitigation: centralize rank key comparison policy and reuse it in both command paths.
- Hidden users could leak through joins. Mitigation: define bypass-free `LeaderboardVisibleUserPolicy` and test restricted/admin edge cases.
- Stale Global projection rows could remain after update. Mitigation: public reads use current-checksum source Scores and beatmapset rebuild later converges submit projection state.
- Migration could preserve invalid legacy PB rows. Mitigation: migrate only rows with an existing source score that passes conservative eligibility rules.

## References

- `.claude/rules/architecture.md` — Layering, compatibility evidence, command/query and job boundaries.
- `.kiro/steering/tech.md` — PostgreSQL, SQLAlchemy async, Unit of Work, taskiq, Dishka, strict type policy.
- `.kiro/steering/scaling.md` — Idempotent worker jobs and read-time recovery expectation.
- `.kiro/specs/friend-relationships/design.md` — Friends leaderboard eligible user set boundary.
- `.kiro/specs/score-pp-calculation/design.md` — Current PP source and stats boundary.
- [`osuripple/lets handlers/getScoresHandler.pyx`](https://github.com/osuripple/lets/blob/98e9e07faa48398fbccf17251650011e36bdf6e4/handlers/getScoresHandler.pyx) — Legacy getscores category handling reference.
