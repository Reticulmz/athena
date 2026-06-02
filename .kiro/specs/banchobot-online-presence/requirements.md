# Requirements Document

## Introduction

stable クライアント利用者とゲーム内コマンドを使う管理者が、公式実装や Akatsuki と同じように BanchoBot を常時オンラインの system user として認識できるようにする。現在の athena は BanchoBot の command response を `user_id=1` / `BanchoBot` から送信しているが、ログイン時の presence や online roster には BanchoBot を公開していないため、メッセージ送信者とオンライン表示が一致しない。この feature は BanchoBot の online presence を bancho 互換の user-visible behavior として整える。

## Boundary Context

- **In scope**: BanchoBot をログイン時の presence / online roster に常時オンラインの system user として表示すること、BanchoBot の送信者 identity と roster identity を一致させること、通常ユーザーのオンライン一覧と共存させること。
- **Out of scope**: 新しい Bot command の追加、admin command の実装、WebUI 管理機能、BanchoBot の AI 会話機能、通常ユーザーとしての BanchoBot ログイン処理。
- **Adjacent expectations**: 既存の command response は BanchoBot identity を使い続ける。通常ユーザーの session lifecycle や packet delivery 対象は BanchoBot を人間の active session として扱わない。

## Requirements

### Requirement 1: BanchoBot の online presence 表示
**Objective:** As a stable クライアント利用者, I want BanchoBot がオンラインユーザーとして表示される, so that BanchoBot からのメッセージが既知のオンライン sender として認識できる

#### Acceptance Criteria
1. When a user successfully logs in, the athena bancho service shall expose BanchoBot as an online user in the initial online roster delivered to that client.
2. When a user successfully logs in, the athena bancho service shall provide BanchoBot presence information before the client needs to display a message sent by BanchoBot.
3. While at least one user is logged in, the athena bancho service shall keep BanchoBot visible as an online system user.
4. If no other human user is online besides the connecting user, then the athena bancho service shall still include BanchoBot in the connecting user's online roster.

### Requirement 2: BanchoBot identity の一貫性
**Objective:** As a ゲーム内コマンド利用者, I want command response の sender と online roster 上の BanchoBot が一致する, so that Bot からの応答を混乱なく識別できる

#### Acceptance Criteria
1. When BanchoBot appears in the online roster, the athena bancho service shall use the same user ID as BanchoBot command responses.
2. When BanchoBot appears in the online roster, the athena bancho service shall use the same display name as BanchoBot command responses.
3. When BanchoBot sends a channel message or private message, the athena bancho service shall make the message sender identity match the BanchoBot identity known to the receiving client.
4. The athena bancho service shall expose BanchoBot at most once in a single online roster for a client.

### Requirement 3: 通常オンラインユーザーとの共存
**Objective:** As a stable クライアント利用者, I want BanchoBot と通常ユーザーが同じオンライン一覧で自然に共存する, so that server roster が bancho 互換の表示になる

#### Acceptance Criteria
1. When a user logs in while other users are already online, the athena bancho service shall include BanchoBot and the relevant online users in the roster visible to the logging-in user.
2. When the online roster contains BanchoBot and human users, the athena bancho service shall not remove or hide human users because BanchoBot is present.
3. When a human user disconnects, the athena bancho service shall not make BanchoBot appear to disconnect as a result of that human user's lifecycle event.
4. While BanchoBot is visible as online, the athena bancho service shall not require BanchoBot to have user-visible login, polling, or logout activity.

### Requirement 4: 既存 command behavior の維持
**Objective:** As a ゲーム内コマンド利用者, I want BanchoBot のオンライン表示追加後も既存 command response が変わらない, so that online presence の修正が command UX を壊さない

#### Acceptance Criteria
1. When a user executes an existing command that produces a BanchoBot response, the athena bancho service shall continue to deliver the response from BanchoBot.
2. When a user executes a command in a channel, the athena bancho service shall preserve the existing channel response behavior while making BanchoBot identifiable as online.
3. When a user executes a command in a private message, the athena bancho service shall preserve the existing private response behavior while making BanchoBot identifiable as online.
4. Where this feature is included, the athena bancho service shall not add, remove, or rename commands solely as part of exposing BanchoBot online presence.
