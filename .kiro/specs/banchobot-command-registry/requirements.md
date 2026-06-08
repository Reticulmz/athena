# Requirements Document

## Introduction

BanchoBot command registry は、BanchoBot の既存コマンド体験を維持しながら、コマンドの追加・確認・保守をしやすくするための機能です。現在は `CommandService` がコマンド解析、実行ルーティング、応答先決定、個別コマンド処理を同じ場所に持っているため、今後コマンドが増えると開発者が挙動を把握しにくくなります。この spec では、プレイヤーに見える挙動を変えずに、BanchoBot コマンドを標準化された登録単位として扱える状態を目指します。

## Boundary Context

- **In scope**: 既存の `!roll`、`!help`、未登録コマンド応答、channel / PM の応答先、コマンド追加時の開発者体験、help 表示の整合性。
- **Out of scope**: 新しい player-visible command の追加、権限付き admin command、BanchoBot のオンラインプレゼンス、チャット配送方式、bancho packet format、session authorization の変更。
- **Adjacent expectations**: chat pipeline はプレイヤーの送信可否、配送、BanchoBot 応答の送信を引き続き担い、この feature は command invocation と response generation の期待値だけを定義します。

## Requirements

### Requirement 1: 既存 BanchoBot コマンド体験の維持

**Objective:** As a stable client player, I want existing BanchoBot commands to behave the same after the registry change, so that command usage does not regress.

#### Acceptance Criteria

1. When プレイヤーが `!roll` を channel 宛に送信した, the BanchoBot command feature shall BanchoBot の roll 結果を同じ channel 宛に返す。
2. When プレイヤーが `!roll` を BanchoBot への PM として送信した, the BanchoBot command feature shall BanchoBot の roll 結果を送信者宛の PM として返す。
3. When プレイヤーが `!help` を送信した, the BanchoBot command feature shall 利用可能な player-visible command の一覧を返す。
4. If プレイヤーが未登録の command name を送信した, then the BanchoBot command feature shall 利用可能な command の確認方法を含む unknown command response を返す。
5. When プレイヤーの chat message が command prefix で始まらない, the BanchoBot command feature shall BanchoBot command response を生成しない。

### Requirement 2: コマンド呼び出し規約の一貫性

**Objective:** As a BanchoBot command maintainer, I want command invocation rules to be consistent across commands, so that new commands can be added without changing user-facing parsing behavior.

#### Acceptance Criteria

1. When プレイヤーが登録済み command name を大文字小文字を混在させて送信した, the BanchoBot command feature shall canonical command name と同じ command として解決する。
2. When プレイヤーが command name の後に空白区切りの arguments を送信した, the BanchoBot command feature shall matched command に arguments を元の順序で利用可能にする。
3. When プレイヤーが command prefix だけ、または空の command name を送信した, the BanchoBot command feature shall BanchoBot command response を生成しない。
4. When matched command が response を返さない結果になった, the BanchoBot command feature shall BanchoBot command response を生成しない。

### Requirement 3: コマンド追加時の開発者体験

**Objective:** As an athena developer, I want BanchoBot commands to be added through a standard registration contract, so that command growth does not make the core command execution logic harder to read.

#### Acceptance Criteria

1. When 開発者が新しい BanchoBot command を追加する, the BanchoBot command feature shall command parsing と response target selection の挙動を変更せずに command を登録できる標準手段を提供する。
2. When 登録済み command が実行される, the BanchoBot command feature shall command 実装に sender identity、destination、command name、arguments を含む invocation context を利用可能にする。
3. When 開発者が既存 command の処理を確認する, the BanchoBot command feature shall 個別 command の user-facing behavior を core command execution flow から独立して確認できるようにする。

### Requirement 4: Help 表示と登録済みコマンドの整合性

**Objective:** As a stable client player, I want help output to reflect available BanchoBot commands, so that I can discover the commands I can use.

#### Acceptance Criteria

1. When `!help` が実行された, the BanchoBot command feature shall 登録済みの player-visible command を help output に含める。
2. When player-visible command が追加された, the BanchoBot command feature shall help output が追加された command を反映できるようにする。
3. Where command metadata is available, the BanchoBot command feature shall help output に player が command を識別するための command name を含める。

### Requirement 5: Feature boundary の維持

**Objective:** As an athena maintainer, I want the registry change to stay limited to BanchoBot command behavior, so that adjacent chat and protocol behavior remains stable.

#### Acceptance Criteria

1. Where this feature is implemented, the BanchoBot command feature shall 新しい player-visible command を追加しない。
2. Where this feature is implemented, the BanchoBot command feature shall chat message の authorization、session handling、channel membership、packet serialization の player-visible behavior を変更しない。
3. When BanchoBot command response が生成された, the BanchoBot command feature shall 既存の BanchoBot author identity と delivery target semantics を維持する。
