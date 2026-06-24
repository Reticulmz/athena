# Brief: persistence-inventory-audit

## Problem

Issue #16 (互換性インベントリ監査) の5つのサブタスクのうち4つ (#32-#35) は完了しているが、
最後の #36 (Persistence inventory を domain owner ごとに監査する) が残っている。
#36 が完了しないと #16 がクローズできず、#17 (fixture 抽出) 以降の全実装 Issue がブロックされたままになる。

## Current State

`docs/stable-compatibility-matrix.md` の Persistence Inventory Coverage テーブルに13行の durable data 領域がある。
各行には Area, Domain owner, Durable data, Primary consumers, Current gap, Status が記録されているが、
既存 Athena コードとの照合が不十分で、owner が未確定または不正確な行がある。

既存の永続化資産:
- **テーブル/モデル**: user, role, channel, blob, beatmap, beatmap_leaderboard, score, score_performance, personal_best, friend, replay_file_attachments
- **Migration**: 12本 (20260522 - 20260618)
- **Domain modules**: identity, chat, beatmaps, scores, storage, compatibility, events

完全に Missing の領域: client integrity, static/media delivery, release/update files, ratings/comments/favourites, achievements/notifications, multiplayer/tournaments

## Desired Outcome

- Persistence Inventory テーブルの全行に正確な Athena domain owner と最新 status が記録されている
- Missing/Partial 行のギャップが、既存 epic へのリンクまたは新規 child work として明示されている
- durable facts が behavior 別 (login, score submit, getscores, replay download, static/media, moderation, multiplayer) にクロスリファレンスされている
- reference schema は discovery evidence としてのみ使用されている

## Approach

兄弟監査 (#32-#35) と同じパターンで進める:
1. 既存コード (models, repositories, migrations) を網羅的に読み取り、各行の実装状態を正確に把握
2. テーブル各行の domain owner をモジュール単位で確定
3. dual-owner 行 (User stats/rankings, Replays/media metadata) の分割を検討
4. gap を behavior グループ別にクロスリファレンスし、既存 Issue とのマッピングまたは新規 child work の特定
5. `docs/stable-compatibility-matrix.md` の Persistence Inventory Coverage セクションを更新

## Grill 決定事項

以下は discovery grill session で確定した方針:

| # | 論点 | 決定 |
|---|------|------|
| 1 | Owner 粒度 | モジュール単位 (e.g. `identity/friends.py`) |
| 2 | Missing 領域の owner | 仮 owner を「domain名: 責務」形式で割り当て (ファイル名は書かない) |
| 3 | Ratings/comments/favourites | 監査中に comment target type を reference から検証してから決定 |
| 4 | User stats/rankings | stats は scores 投影、rankings は将来独立。テーブル行を分割 |
| 5 | Gap-to-issue マッピング | 既存 Issue リンク + durable fact 単位で gap 記述。Issue 作成はしない |
| 6 | テーブル行の追加/分割 | User stats/rankings 分割 + Replays/media metadata 分割を検討 |
| 7 | Volatile/Durable 境界 | latest activity は durable (throttled write) と注記 |
| 8 | Aggregate vs read model | 分けない。read model は gap 列に注記 |
| 9 | Cross-domain 依存 | Primary consumers 列に cross-domain 参照を明記 |

## Scope

- **In**: Persistence Inventory テーブル全行の status/owner/gap 更新、behavior 別クロスリファレンスセクション追加、行の分割 (justified cases)、既存 Issue リンク、新規 child work の特定、matrix ドキュメント更新
- **Out**: 実際のスキーマ設計や migration 作成、reference schema のコピー、新テーブルの実装、新規 GitHub Issue の作成

## Boundary Candidates

- docs 更新 (matrix テーブルの行更新 + behavior クロスリファレンス追加)
- domain owner 確定 (既存コードとの照合)
- gap-to-issue マッピング (既存 epic/issue へのリンク)

## Out of Boundary

- テーブル/migration の新規作成
- reference implementation のスキーマコピー
- 実装作業そのもの
- 新規 GitHub Issue の作成

## Upstream / Downstream

- **Upstream**: 完了済みの #32 (legacy web), #33 (bancho packet/struct), #34 (release/update), #35 (static/media) 監査結果
- **Downstream**: #16 クローズ -> #17 (fixture 抽出), #18 (Presence/UserStats), #19 (Score submit) 等の全実装 Issue がアンブロック

## Existing Spec Touchpoints

- **Extends**: stable-compatibility-verification (上位 spec)
- **Adjacent**: legacy-web-endpoint-inventory-audit, bancho-packet-struct-inventory-audit, stable-static-media-inventory, release-update-route-policy-inventory-audit (兄弟 spec パターン)

## Constraints

- reference schema は discovery evidence としてのみ使用し、Athena のスキーマテンプレートにしない (Persistence Reference Policy)
- domain owner は既存の `src/osu_server/domain/` モジュール構造に合わせる
- 未実装領域の仮 owner は「domain名: 責務」形式とし、ファイル名は確定しない
- comment target type は reference 実装で検証してから帰属を決定する
