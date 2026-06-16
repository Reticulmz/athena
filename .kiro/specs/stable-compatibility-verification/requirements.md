# Requirements Document

## Introduction

Stable Compatibility Verification は、Athena が既に実装している stable client 向け surface について、stable client から観測できる request / response 互換性の証拠を棚卸しし、継続的に確認できる状態にするための検証機能である。

この feature は既存の unit / integration / e2e test を置き換えない。既存テストを evidence として関連付けたうえで、常時 CI で守る軽量な contract / golden fixture と、AI エージェントまたは開発者が任意実行する headless stable client probe を分離する。最初の優先範囲は score submit response と getscores であり、Stable Surface 全体の棚卸しは registration、bancho login、polling、chat、getscores、score submit を含む。

## Boundary Context

- **In scope**: 現状実装済み Stable Surface の一覧化、surface ごとの Stable Compatibility Evidence 対応付け、score submit response の golden 検証、getscores の stable response 検証、任意の headless stable client probe、development / test 限定の `athena dev stable-verify` 実行体験。
- **Out of scope**: Stable Surface の新規 gameplay 機能追加、未実装 leaderboard projection の完成、user stats / global ranking 集計の新規実装、production 環境に対する probe 実行、Athena server / worker の起動停止管理。
- **Adjacent expectations**: score submit や getscores が参照する永続 score、PP、beatmap、session、user 情報は既存実装または別 spec の責務として扱う。この feature は、それらの値が stable client へ返る observable response contract として妥当かを検証する。

## Requirements

### Requirement 1: Stable Surface 棚卸し

**Objective:** As a 開発者, I want 実装済み Stable Surface と検証証拠の対応を一覧できる, so that stable 互換性の未検証箇所を判断できる

#### Acceptance Criteria

1. When Stable Compatibility Verification の対象一覧が生成される, the Stable Compatibility Verification shall 現状実装済み Stable Surface を surface 単位で列挙する
2. The Stable Compatibility Verification shall registration、bancho login、polling、chat、getscores、score submit を対象 surface として含める
3. If surface が Athena に未実装である, then the Stable Compatibility Verification shall その surface を検証失敗ではなく scope 外として表示する
4. If 実装済み surface に対応する evidence が存在しない, then the Stable Compatibility Verification shall その surface を verification gap として表示する

### Requirement 2: Stable Compatibility Evidence 分類

**Objective:** As a 開発者, I want 互換性証拠の種類と信頼範囲を区別できる, so that CI で守る契約と任意 probe の役割を混同しない

#### Acceptance Criteria

1. When evidence が surface に関連付けられる, the Stable Compatibility Verification shall evidence の種類を automated test、golden fixture、headless probe のいずれかとして分類する
2. The Stable Compatibility Verification shall 常時 CI で必須とする evidence と任意実行の evidence を区別して表示する
3. If headless probe evidence が存在しない, then the Stable Compatibility Verification shall mandatory evidence の結果を optional probe 不在として失敗扱いにしない
4. Where evidence が既存テストから得られる, the Stable Compatibility Verification shall 既存テストを置き換えずに evidence として参照する

### Requirement 3: 既存テスト保護

**Objective:** As a 保守者, I want 既存の stable 関連テストを維持したまま互換性証拠を追加できる, so that regressions を検出する既存保証を失わない

#### Acceptance Criteria

1. The Stable Compatibility Verification shall 既存の unit、integration、e2e test を削除または置換することを要求しない
2. When 既存テストが stable request / response contract を検証している, the Stable Compatibility Verification shall そのテストを surface evidence として扱う
3. If 新しい evidence が既存テストと同じ surface を検証する, then the Stable Compatibility Verification shall 既存テストの目的と新しい evidence の目的を区別できる説明を提供する

### Requirement 4: Score Submit Response 互換性

**Objective:** As a 開発者, I want score submit response が stable client 互換の chart response として検証される, so that pp だけでなく score 関連値の欠落を検出できる

#### Acceptance Criteria

1. When score submit verification が実行される, the Stable Compatibility Verification shall stable modular score submit request として観測される multipart 形状を検証する
2. When score submit response が生成される, the Stable Compatibility Verification shall stable client が parse できる chart response 形式であることを検証する
3. The Stable Compatibility Verification shall score submit response の online score identifier、map play count、map pass count、chartId、chartUrl、chartName、achieved、rank、rankBefore、rankedScore、rankedScoreBefore、totalScore、maxCombo、accuracy、pp を検証対象に含める
4. The Stable Compatibility Verification shall score submit chart の achieved field と achievement notification を別の stable response contract として区別する
5. If score submit response field が未実装の user stats または leaderboard projection に依存する, then the Stable Compatibility Verification shall その field を暗黙に成功扱いせず、known gap または unavailable として表示する

### Requirement 5: Getscores 互換性

**Objective:** As a 開発者, I want getscores response が stable client 互換として検証される, so that leaderboard 表示の破壊的変更を検出できる

#### Acceptance Criteria

1. When getscores verification が実行される, the Stable Compatibility Verification shall stable client が送る getscores query shape を検証する
2. When getscores response が返る, the Stable Compatibility Verification shall stable client が parse できる response 形式であることを検証する
3. The Stable Compatibility Verification shall beatmap status、chart header、score row、personal best、empty leaderboard の各 observable case を検証対象として扱う
4. If getscores response が leaderboard または personal best data を返せない, then the Stable Compatibility Verification shall その状態を空結果、unavailable、または verification gap として区別して表示する
5. Where headless stable client probe が利用可能である, the Stable Compatibility Verification shall local Athena target に対して getscores request / parse の互換性を確認できる

### Requirement 6: Development Verification Command

**Objective:** As a AI エージェントまたは開発者, I want 起動済みローカル Athena に対して stable 互換性 probe を実行できる, so that 実装確認を stable client 視点に近づけられる

#### Acceptance Criteria

1. When `athena dev stable-verify` が development または test 環境で実行される, the Athena CLI shall 指定された local target に対して選択された Stable Surface の検証を実行する
2. The Athena CLI shall 検証対象を単一 surface または全対象 surface から選択できる
3. The Athena CLI shall 起動済み Athena server に接続するだけで、server または worker の起動停止を所有しない
4. If local target が到達不能である, then the Athena CLI shall connection failure を surface result として表示する
5. If required target information が不足している, then the Athena CLI shall network request を送る前に不足情報を表示して終了する

### Requirement 7: Local Target と Stable Host Identity

**Objective:** As a 開発者, I want 接続先 URL と stable client 視点の Host identity を分けて指定できる, so that localhost 実行でも stable 互換 routing を検証できる

#### Acceptance Criteria

1. When verification command が local target に接続する, the Athena CLI shall 実接続先 URL と stable Host identity を区別して扱う
2. When stable Host identity が指定される, the Athena CLI shall stable client から観測される Host / server identity としてその値を request に反映する
3. If stable Host identity が指定されない, then the Athena CLI shall 選択された Athena configuration の domain を stable Host identity として扱う
4. If 実接続先 URL と stable Host identity が異なる, then the Athena CLI shall その差分を検証開始時に表示する

### Requirement 8: Production Guardrails と秘匿情報保護

**Objective:** As a 運用者, I want stable verification が production や secret leakage を避ける, so that 検証機能が運用リスクにならない

#### Acceptance Criteria

1. If verification command が production 環境で実行される, then the Athena CLI shall stable probe request を送信する前に実行を拒否する
2. The Stable Compatibility Verification shall report に password、password hash、session token、replay raw payload、credential field を出力しない
3. If verification failure が発生する, then the Stable Compatibility Verification shall secret を含まない request context と response summary を diagnostic として表示する
4. The Stable Compatibility Verification shall production user data の作成、更新、削除を要求しない

### Requirement 9: Verification Result Reporting

**Objective:** As a 開発者, I want 検証結果を surface ごとに読み取れる, so that 次に直すべき互換性 gap を判断できる

#### Acceptance Criteria

1. When verification run が完了する, the Stable Compatibility Verification shall requested surface ごとの pass、fail、skip、known gap、unavailable のいずれかの result を表示する
2. The Stable Compatibility Verification shall 各 result に evidence type と対象 surface を含める
3. If mandatory evidence が失敗する, then the Stable Compatibility Verification shall run 全体を failed として扱う
4. If optional headless probe が skipped または unavailable である, then the Stable Compatibility Verification shall mandatory evidence が成功している限り run 全体を failed として扱わない
5. When output が機械処理向けに要求される, the Stable Compatibility Verification shall surface、result、evidence type、diagnostic summary を含む structured output を提供する
