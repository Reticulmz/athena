# Requirements Document

## Introduction

athena の chat job refactor は、worker job に混在している queue adapter、Chat のユースケース判断、永続化処理の責務を整理し、後続 worker job 実装の標準を確立する。Chat は public chat と private chat を内包する上位概念であり、永続化は単なる DB 書き込みではなく chat history として扱う。

## Boundary Context

- **In scope**: ChatService が public chat と private chat の送信成功・拒否・履歴化に関する一貫した振る舞いを提供すること。worker job は成功済み chat event を受けて履歴化を依頼すること。永続化失敗や job 実行不能が運用者に観測可能であること。
- **Out of scope**: 新しい外部 chat history API、WebUI、Lazer API、IRC/Bot API、モデレーション機能、既存 packet format の変更。
- **Adjacent expectations**: ChannelService は channel の場・参加状態・権限に関する判断を提供し、CommandService は chat text に埋め込まれた command を扱う。これらは ChatService に吸収せず、ChatService から利用される隣接能力として扱う。

## Requirements

### Requirement 1: Chat 概念の一貫性
**Objective:** As a 開発者, I want public chat と private chat を同一の Chat 概念として扱える, so that 後続実装で service 境界が分裂しない

#### Acceptance Criteria
1. The Chat Service shall public chat と private chat を Chat の subtype として扱う一貫した操作を提供する
2. The Chat Service shall channel 宛て chat と user 宛て chat の違いを宛先種別として扱う
3. The Chat Service shall private chat を Chat Service の外側にある独立した message delivery 概念として扱わない
4. Where channel 管理が必要な場合, the Chat Service shall Channel Service の判断結果を利用する
5. Where chat text が command を表す場合, the Chat Service shall Command Service の判断結果を利用する

### Requirement 2: 成功済み chat のみ履歴化対象にする
**Objective:** As a 運用者, I want 配送に成功した chat だけが履歴化される, so that chat history が実際のユーザー体験と一致する

#### Acceptance Criteria
1. When public chat が有効に配送された, the Chat Service shall その public chat を履歴化対象として扱う
2. When private chat が有効に配送された, the Chat Service shall その private chat を履歴化対象として扱う
3. If chat が無効入力として拒否された, then the Chat Service shall その chat を履歴化対象にしない
4. If chat が silence、rate limit、権限不足、未参加、または宛先不存在で拒否された, then the Chat Service shall その chat を履歴化対象にしない
5. If command として処理された入力が通常 chat として配送されない, then the Chat Service shall その入力を chat history の履歴化対象にしない

### Requirement 3: Worker job の観測可能性
**Objective:** As a 運用者, I want worker job の失敗や実行不能状態を観測できる, so that chat history 欠落の原因を調査できる

#### Acceptance Criteria
1. When chat persistence job が登録されていない, the system shall 運用者が検知できる失敗として扱う
2. If chat persistence job が必要な実行状態を取得できない, then the system shall 運用者が原因を特定できる情報を記録する
3. If public chat の履歴化対象が保存時に解決不能になった, then the system shall silent success として扱わず観測可能な結果を残す
4. If private chat の履歴化が失敗した, then the system shall silent success として扱わず観測可能な結果を残す
5. The system shall chat persistence job の失敗を chat delivery 成功そのものと区別して観測可能にする

### Requirement 4: Queue adapter と Chat ユースケースの分離
**Objective:** As a 開発者, I want worker job を queue payload の変換に限定できる, so that business rule と永続化判断が job handler に混在しない

#### Acceptance Criteria
1. When worker job が chat persistence payload を受け取った, the system shall chat 履歴化の判断を Chat Service に委譲する
2. The system shall worker job に chat 配送、channel 権限判定、membership 判定、command 判定を再実行させない
3. The system shall worker job に永続化実装の詳細を持たせない
4. The system shall worker job が queue 由来の入力を Chat Service の入力へ変換する責務に限定されていることを検証可能にする
5. The system shall 後続 worker job でも queue adapter と use-case 判断の分離を同じ基準で検証可能にする

### Requirement 5: Chat history 永続化の抽象化
**Objective:** As a 開発者, I want chat history 永続化を抽象化された契約として扱える, so that Chat Service が保存方式の詳細に依存しない

#### Acceptance Criteria
1. The Chat Service shall chat history の保存方式に依存せずに public chat の履歴化を依頼できる
2. The Chat Service shall chat history の保存方式に依存せずに private chat の履歴化を依頼できる
3. If public chat の保存先が channel を解決できない, then the Chat Service shall その結果を履歴化失敗として扱える
4. If chat history の保存が失敗した, then the Chat Service shall 成功として扱わない
5. The system shall chat history の永続化契約を public chat と private chat の両方で検証可能にする

### Requirement 6: 後続実装の境界標準
**Objective:** As a テックリード, I want chat persistence job を worker job 設計の前例にする, so that PP 計算や leaderboard 更新などの後続 job が同じ境界を守る

#### Acceptance Criteria
1. The system shall worker job が framework integration、queue adapter、use-case、永続化契約を混在させない基準を持つ
2. The system shall worker job が外部 protocol transport と混同されない境界を持つ
3. The system shall task queue framework に関する仕組みと application-specific な job behavior を区別する
4. The system shall layer boundary 違反を品質ゲートで検知できる
5. When 後続 worker job が追加される, the system shall chat persistence job と同じ責務分離基準で検証できる
