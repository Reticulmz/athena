# Implementation Plan

- [ ] 1. Stable verification の基盤語彙と catalog を用意する
- [ ] 1.1 Verification result の共通語彙を定義する
  - Stable Surface、evidence type、mandatory / optional scope、result status、target、surface result、run result を同じ語彙で扱えるようにする
  - Mandatory evidence failure は run failure になり、optional unavailable / skip は run failure にならない集約規則を持たせる
  - Secret を保持する入力値と report 可能な diagnostic summary を分ける
  - 完了時には unit test から pass、fail、skip、known_gap、unavailable の各 status と aggregate failure 判定を確認できる
  - _Requirements: 1.3, 2.1, 2.2, 2.3, 9.1, 9.2, 9.3, 9.4_

- [ ] 1.2 Stable Surface inventory と evidence catalog を作る
  - registration、bancho login、polling、chat、getscores、score submit を surface catalog に含める
  - 実装済み surface、scope 外 surface、evidence gap を区別できる catalog entry を用意する
  - 既存の stable 関連 tests / fixtures を置き換えず、surface evidence として参照する
  - 同じ surface に複数 evidence がある場合に purpose の違いを catalog から読み取れるようにする
  - 完了時には catalog test で全 required surface、mandatory / optional 分類、既存 evidence reference、known gap が確認できる
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.4, 3.1, 3.2, 3.3_

- [ ] 2. Response parsing と probe 周辺の core component を実装する
- [ ] 2.1 Stable response parser を実装する
  - Score submit completed response の chart line を parse し、beatmap metadata、beatmap chart、overall chart を区別する
  - `achieved` field と `achievements-new` notification を別 contract として分類する
  - Getscores の short response、header response、empty leaderboard、malformed body を分類する
  - 不正 format は未処理例外ではなく parse failure result として扱う
  - 完了時には parser tests で score submit required fields と getscores fixture body が typed result に変換される
  - _Requirements: 4.2, 4.3, 4.4, 5.2, 5.3, 5.4_

- [ ] 2.2 (P) Stable HTTP probe client を実装する
  - 実接続先 URL と stable Host identity を別々に保持する
  - Web legacy request では `osu.<host identity>` を stable Host として送れるようにする
  - Connection refused、timeout、HTTP client error を unavailable result 用 diagnostic に変換する
  - Diagnostic には method、path、status code、response byte size、sanitized error だけを含める
  - 完了時には fake HTTP transport の test で Host header、target URL、connection failure result が確認できる
  - _Requirements: 6.4, 6.5, 7.1, 7.2, 7.4, 8.3_
  - _Boundary: Stable Probe Client_

- [ ] 2.3 (P) Redacted reporter を実装する
  - Text output は surface ごとの status、evidence type、scope、diagnostic summary を表示する
  - Structured output は surface、status、evidence type、scope、diagnostic summary、reference を含む
  - 実接続先 URL と stable Host identity が異なる場合は検証開始時の summary に差分を表示する
  - Password、password hash、session token、raw replay、credential field を redaction 対象にする
  - 完了時には reporter tests で text / JSON output と secret redaction が確認できる
  - _Requirements: 7.4, 8.2, 8.3, 9.1, 9.2, 9.5_
  - _Boundary: Reporter_

- [ ] 2.4 (P) Optional osu.py probe adapter を実装する
  - `osu` package は lazy import し、未導入時は optional result として skip または unavailable にする
  - Getscores / leaderboard probe だけを扱い、score submit には使わない
  - Version、executable hash、credentials など外部 network 回避に必要な prerequisites が不足する場合は実 request を送らない
  - Optional probe unavailable は mandatory evidence が成功している限り run failure にしない
  - 完了時には fake adapter tests で installed / missing / prerequisites missing の各 result が確認できる
  - _Requirements: 5.5, 9.4_
  - _Boundary: OsuPyProbe_

- [ ] 3. Mandatory evidence verifier を追加する
- [ ] 3.1 (P) Score submit golden verification を追加する
  - Stable modular score submit request の report-safe metadata を検証する
  - Completed response fixture と mapper-generated completed response を chart parser で検証する
  - online score identifier、map play count、map pass count、chart metadata、rank、rankBefore、rankedScore、rankedScoreBefore、totalScore、maxCombo、accuracy、pp を coverage に含める
  - user-stats / leaderboard projection 由来の未実装値は known gap または unavailable として表示する
  - 完了時には score submit verifier tests で required chart fields、failed response、secret-free response が確認できる
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 8.2_
  - _Boundary: ScoreSubmitVerifier_
  - _Depends: 2.1_

- [ ] 3.2 (P) Getscores fixture と local probe verification を追加する
  - Existing getscores fixtures を mandatory evidence として parse する
  - Stable client query shape を probe case として表現し、checksum、filename、beatmapset hint、mode、mods、leaderboard type、request version を検証対象にする
  - Unavailable、update available、header、empty leaderboard、score row / personal best gap を区別して result にする
  - Optional headless probe は local target と credentials が揃う場合だけ実行する
  - 完了時には getscores verifier tests で fixture parse、query shape、known gap、optional probe skip が確認できる
  - _Requirements: 2.3, 5.1, 5.2, 5.3, 5.4, 5.5, 9.4_
  - _Boundary: GetscoresVerifier_
  - _Depends: 2.1, 2.2, 2.4_

- [ ] 4. Runner と CLI command を統合する
- [ ] 4.1 Verification runner を実装する
  - 単一 surface と all surfaces の selection を扱う
  - Mandatory evidence と optional evidence を同じ run result に集約する
  - CLI live probe 用 request では target 情報を必須にし、fixture-only 検証は pytest 側で verifier を直接実行する
  - Connection failure、parse failure、known gap、optional unavailable を aggregate status に反映する
  - 完了時には runner tests で selected surfaces、mandatory failure、optional unavailable、missing target validation が確認できる
  - _Requirements: 2.2, 2.3, 6.1, 6.2, 6.4, 6.5, 9.1, 9.3, 9.4_
  - _Depends: 1.2, 2.2, 2.3, 2.4, 3.1, 3.2_

- [ ] 4.2 `athena dev stable-verify` command を追加する
  - `--env`、`--base-url`、`--host`、`--surface`、`--json`、`--timeout` を受け取る
  - CLI 実行では `--base-url` を必須にし、指定がない場合は network request 前に usage error を返す
  - `--host` 未指定時は selected environment の domain を stable Host identity として使う
  - Production environment は target validation や network request より前に拒否する
  - Server / worker の起動停止は行わず、起動済み local Athena に接続するだけにする
  - 完了時には CLI から selected surface の verification report を text または JSON で確認できる
  - _Requirements: 6.1, 6.2, 6.3, 6.5, 7.1, 7.2, 7.3, 7.4, 8.1, 8.4, 9.5_
  - _Depends: 4.1_

- [ ] 5. Stable verification の regression coverage を固める
- [ ] 5.1 CLI integration tests を追加する
  - Production rejection が probe client construction より前に起きることを検証する
  - Missing `--base-url` が network request 前の usage error になることを検証する
  - `--host` override と config domain fallback を検証する
  - Unreachable local target が unavailable surface result として表示されることを検証する
  - `--json` output に surface、status、evidence type、scope、diagnostic summary が含まれることを検証する
  - 完了時には Typer runner の integration tests で dev command の主要 branch が確認できる
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 7.1, 7.2, 7.3, 7.4, 8.1, 9.1, 9.5_
  - _Depends: 4.2_

- [ ] 5.2 Stable contract tests を mandatory evidence として強化する
  - Existing getscores fixture tests が evidence catalog と矛盾しないことを検証する
  - Score submit mapper tests で beatmap chart と overall chart の required fields を検証する
  - Score submit response に raw error reason、credential、replay raw payload が漏れないことを検証する
  - Getscores endpoint tests で `osu.<domain>` Host routing と path fallback 不在を維持する
  - 完了時には既存 stable tests と新規 verification tests が同じ response contract を確認していることが test output から分かる
  - _Requirements: 3.1, 3.2, 4.2, 4.3, 4.4, 5.2, 5.3, 8.2_
  - _Depends: 3.1, 3.2_

- [ ] 5.3 Focused checks と品質 gate を実行する
  - Stable verification unit tests、CLI integration tests、score submit mapper tests、getscores fixture / endpoint tests を実行する
  - Ruff、basedpyright、import-linter の relevant quality checks を実行する
  - Failure が出た場合は implementation または task split の問題として修正してから再実行する
  - 完了時には実行した command と pass / fail 結果を実装報告に含められる
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 6.2, 6.3, 6.4, 6.5, 7.1, 7.2, 7.3, 7.4, 8.1, 8.2, 8.3, 8.4, 9.1, 9.2, 9.3, 9.4, 9.5_
  - _Depends: 5.1, 5.2_
