# 要件定義

## はじめに

Persistence Inventory Audit は、GitHub Issue #36「[stable-compat] Persistence inventory を domain owner ごとに監査する」に基づき、`docs/stable-compatibility-matrix.md` の Persistence Inventory Coverage テーブル全行を既存 Athena コードと照合し、domain owner をモジュール単位で確定、gap を behavior 別にクロスリファレンスするための spec である。

この監査は GitHub Issue #16 の互換性インベントリ監査の最後の子 task であり、スキーマ設計や migration 作成そのものではなく、次の fixture 抽出 (#17) および実装 Issue (#18-#30) が推測なしで着手できる状態を作る。

## 境界コンテキスト

- **対象範囲**: Persistence Inventory Coverage テーブル全行の status / domain owner / gap 更新、domain owner のモジュール単位での確定、behavior 別クロスリファレンスセクションの追加、justified な行分割、既存 Issue へのリンク、新規 child work の特定、matrix ドキュメント更新。
- **対象外**: テーブル / migration の新規作成、reference schema のコピー、新テーブルの実装、新規 GitHub Issue の作成、runtime behavior の実装。
- **隣接する期待値**: 完了済みの兄弟監査 (#32 legacy web, #33 bancho packet/struct, #34 release/update, #35 static/media) の分類結果を前提として参照する。durable fact の gap が既存 epic (#17-#30) に属する場合はリンクし、属さない場合は新規 child work として記述するが Issue 作成はしない。

## 要件

### 要件 1: 監査対象の完全性

**目的:** Stable compatibility 保守者が Persistence Inventory Coverage テーブルの全行を漏れなく監査対象として確認でき、未照合の durable data 領域が残らないようにする。

#### 受け入れ基準

1. Persistence Inventory Audit 実行時、`docs/stable-compatibility-matrix.md` の Persistence Inventory Coverage テーブルに存在する全行を監査対象として扱う
2. Persistence Inventory Audit 実行時、`docs/stable-compatibility-guide.md` の Persistence Reference Policy テーブルに記載された durable fact 領域との照合を行う
3. Persistence Inventory Coverage テーブルの行と Persistence Reference Policy テーブルの行に差分がある場合、その差分を evidence gap として記録する
4. 既存 Athena コードに Persistence Inventory Coverage テーブルに未記載の durable data が存在する場合、その durable data を新行候補として記録する

### 要件 2: Domain owner の確定

**目的:** 実装エージェントが各 durable data 領域の責任モジュールを迷わず特定でき、owner が未確定のまま実装に着手しないようにする。

#### 受け入れ基準

1. 既存 domain module に対応する durable data 領域を監査するとき、domain owner をモジュール単位で記録する (例: `identity/friends.py`, `scores/leaderboards.py`)
2. 既存 domain module が存在しない durable data 領域を監査するとき、仮 owner を「domain 名: 責務」形式で記録する (例: `integrity: client hash validation`)
3. 仮 owner を記録するとき、具体的なファイル名やモジュールパスを確定しない
4. While 1つの durable data 領域が複数の domain module にまたがるとき、primary owner と cross-domain 依存先を区別して記録する

### 要件 3: Status 更新の正確性

**目的:** Stable compatibility planner がテーブルの status 列から各領域の実装進捗を正確に読め、Partial と Missing の判断根拠が追跡可能であるようにする。

#### 受け入れ基準

1. durable data 領域を監査するとき、既存の Athena テーブル / モデル / migration と照合してから status を更新する
2. 既存テーブルが durable data 領域の一部をカバーしている場合、status を `Partial` として記録し、カバー済みとカバー外の fact を gap 列に区別して記載する
3. 既存テーブルが durable data 領域のいずれもカバーしていない場合、status を `Missing` として記録する
4. 既存テーブルが durable data 領域の全 fact をカバーしている場合、status を `Implemented` として記録する
5. While status を `Partial` から `Implemented` へ変更する場合、全 fact のカバレッジ根拠を gap 列に示す

### 要件 4: Gap 記述の完全性

**目的:** Roadmap 管理者が各 durable data 領域の不足を durable fact 単位で読め、後続 Issue 作成や実装計画がコピー可能な粒度で記述されているようにする。

#### 受け入れ基準

1. durable data 領域に gap がある場合、不足する durable fact を個別に列挙する
2. 不足する durable fact を記述するとき、その fact が必要な stable behavior (例: login, score submit, getscores) を併記する
3. 不足する durable fact が既存の open Issue (#17-#30) に属する場合、該当 Issue 番号をリンクとして記録する
4. 不足する durable fact が既存 Issue にマッピングできない場合、新規 child work として記述し、必要な epic または task の概要を示す
5. gap を記述するとき、durable data と volatile state (Valkey / runtime) の区別を明示する
6. If latest activity のように更新頻度が高い durable fact がある場合、`durable, throttled write` のように永続化方針の注記を付与する

### 要件 5: Behavior 別クロスリファレンス

**目的:** Stable compatibility implementer が特定の stable behavior (例: login) を実装する際に、その behavior が依存する全 durable data 領域を横断的に確認できるようにする。

#### 受け入れ基準

1. Persistence Inventory Audit が完了するとき、behavior 別クロスリファレンスセクションを Persistence Inventory Coverage セクション内に追加する
2. behavior グループは login, score submit, getscores, replay download, static/media, moderation, multiplayer を最低限含む
3. 各 behavior グループに、その behavior が依存する durable data 領域 (テーブル行の Area) を列挙する
4. 各 behavior グループに、cross-domain 依存がある場合はその依存関係を明示する (例: friend leaderboard は identity/friends と scores/leaderboards に依存)

### 要件 6: テーブル行の分割基準

**目的:** Docs consumer がテーブル行の分割理由を追跡でき、分割が owner の正確性を高める justified case に限定されるようにする。

#### 受け入れ基準

1. 1つのテーブル行に primary owner が異なる2つ以上の durable data group が含まれる場合、その行を分割候補として評価する
2. テーブル行を分割するとき、分割理由を記録する
3. テーブル行を分割するとき、既存の兄弟監査 (#32-#35) が参照している Area 名との互換性を確認する
4. If read model と aggregate で owner が異なる場合でも、テーブル行を分割せず gap 列に `read model rebuilt from [source]` の注記を付与する

### 要件 7: Evidence source の制約

**目的:** Compatibility 保守者が durable data の owner や status を確認可能な source に基づいて判断でき、undocumented guess による誤分類を避けられるようにする。

#### 受け入れ基準

1. domain owner を確定するとき、既存の `src/osu_server/domain/` モジュール構造、既存テーブル / モデル、または roadmap.md の spec 割り当てを evidence source として使用する
2. status を更新するとき、既存の alembic migration、SQLAlchemy モデル、または repository 実装を evidence source として使用する
3. reference schema (bancho.py, lets, pep.py, deck, titanic) は durable fact の discovery evidence としてのみ使用し、Athena の domain owner や status の直接根拠として使用しない
4. If comment target type のように帰属が曖昧な durable fact がある場合、reference 実装で target type を検証してから domain owner を確定する

### 要件 8: Matrix docs への反映

**目的:** Stable compatibility 保守者が監査結果を既存 docs から読め、GitHub Issue #16 と #36 の進捗を同じ source of truth で追跡できるようにする。

#### 受け入れ基準

1. Persistence Inventory Audit が完了するとき、`docs/stable-compatibility-matrix.md` の Persistence Inventory Coverage テーブルに domain owner、gap、status の更新を反映する
2. テーブル行の分割が発生した場合、分割後の行を Persistence Inventory Coverage テーブルに反映する
3. behavior 別クロスリファレンスセクションを Persistence Inventory Coverage セクション直後に追加する
4. matrix と guide の Persistence Reference Policy テーブルに矛盾がある場合、その矛盾を unresolved evidence gap として示す

### 要件 9: Audit-only 境界

**目的:** Spec reviewer がこの spec が監査と docs 更新だけを要求していることを確認でき、implementation work と schema design work が混ざらないようにする。

#### 受け入れ基準

1. Persistence Inventory Audit はテーブルまたは migration の新規作成を要求しない
2. Persistence Inventory Audit は reference implementation のスキーマコピーを要求しない
3. Persistence Inventory Audit は新規 GitHub Issue の作成を要求しない
4. audit result が missing durable data を特定した場合、その不足を gap 記述または follow-up checklist として記録し、schema design complete として扱わない
5. audit result が新規 child work を特定した場合、必要な epic または task の概要を記述するが、Issue 作成 complete として扱わない
