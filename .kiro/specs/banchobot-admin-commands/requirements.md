# Requirements Document

## Introduction

BanchoBot admin command foundation は、既存の `!help` と `!roll` の体験を維持しながら、将来の管理用コマンドを `Privileges` ベースで安全に追加できるようにするための機能です。現在の BanchoBot コマンドは一般公開コマンドのみを前提としているため、`!role`、`!ban`、`!silence`、Beatmap のランク状態変更などの管理操作を追加する前に、実行者の権限に応じた発見、詳細ヘルプ、実行可否判定を標準化します。

## Boundary Context

- **In scope**: BanchoBot コマンド登録時の必要 `Privileges` 指定、コマンドごとの実行可能宛先指定、権限に応じた `!help` 表示、権限不足と未登録コマンドの同一応答、共通の詳細ヘルプ表示、channel / PM 両方での同一権限判定、既存 `!help` / `!roll` の後方互換。
- **Out of scope**: `!role`、`!ban`、`!silence`、Beatmap rank 変更などの具体的な管理コマンド実装、新しい player-visible 管理コマンドの追加、新しい privilege 定義の追加、対象ユーザーとの role position 比較、authorization refresh を実行するコマンド、監査ログ基盤、通常実行時の引数バリデーション共通化。
- **Adjacent expectations**: 通常チャットとして拒否される状態ではコマンドも実行されない。コマンド権限は実行時点のセッション権限スナップショットに基づく。将来の管理コマンドは、必要に応じて role position ルールや監査ログ基盤を別 spec で定義する。権限付き・宛先制約付き command behavior は、product に露出しない test-only registered command で検証できるようにする。

## Requirements

### Requirement 1: 権限付きコマンド登録

**Objective:** As an athena developer, I want BanchoBot commands to declare required privileges through a standard registration contract, so that future admin commands can be added without changing command dispatch behavior.

#### Acceptance Criteria

1. When 開発者が BanchoBot command を登録する, the BanchoBot command feature shall command name、description、usage、arguments、既存 `Privileges` に基づく required privileges、allowed destinations を command metadata として扱えるようにする。
2. When 開発者が required privileges を指定せずに command を登録する, the BanchoBot command feature shall その command を全ユーザーが実行可能な公開 command として扱う。
3. When 開発者が required privileges を指定して command を登録する, the BanchoBot command feature shall 実行者が必要な `Privileges` を満たす場合のみその command を実行可能として扱う。
4. When command metadata に複数の `Privileges` が指定されている, the BanchoBot command feature shall 実行者が指定された全 privilege を持つ場合のみその command を実行可能として扱う。
5. When 実行者が `ADMIN` privilege を持つ, the BanchoBot command feature shall command metadata に指定された required privileges を満たしたものとして扱う。
6. When 開発者が allowed destinations を指定せずに command を登録する, the BanchoBot command feature shall その command を channel と PM の両方で実行可能として扱う。
7. The BanchoBot command feature shall command の入口権限を `Privileges` に基づいて判定し、role id、role name、対象ユーザーとの role position 比較を入口権限判定に含めない。

### Requirement 2: 権限に応じた実行可否

**Objective:** As a BanchoBot operator, I want admin commands to be executable only by users with sufficient privileges, so that privileged operations are not exposed to normal users.

#### Acceptance Criteria

1. When ユーザーが required privileges を満たす command を channel で実行する, the BanchoBot command feature shall 既存の channel response target semantics に従って command response を返す。
2. When ユーザーが required privileges を満たす command を BanchoBot への PM で実行する, the BanchoBot command feature shall 既存の PM response target semantics に従って command response を返す。
3. When ユーザーが required privileges を満たさない registered command を実行する, the BanchoBot command feature shall `Unknown command. Type !help for available commands.` を返す。
4. If ユーザーが未登録 command を実行した, then the BanchoBot command feature shall `Unknown command. Type !help for available commands.` を返す。
5. When command authorization is evaluated, the BanchoBot command feature shall 実行時点のセッション権限スナップショットを使用する。
6. When required privileges を満たすユーザーが allowed destinations に含まれない public channel で command を実行する, the BanchoBot command feature shall public channel に `Unknown command. Type !help for available commands.` を返し、実行者本人へ正しい実行場所を PM で案内する。
7. When required privileges を満たすユーザーが allowed destinations に含まれない PM で command を実行する, the BanchoBot command feature shall 実行者本人へ正しい実行場所を PM で案内する。
8. When required privileges を満たさないユーザーが allowed destinations に含まれない場所で command を実行する, the BanchoBot command feature shall `Unknown command. Type !help for available commands.` を返し、実行場所の案内を返さない。
9. While ユーザーの chat message が silence、rate limit、送信先 channel の送信可否など通常チャット条件で拒否される, the BanchoBot command feature shall その message に含まれる command を実行しない。

### Requirement 3: 権限に応じた command discovery

**Objective:** As a stable client user, I want `!help` to show only commands I can execute, so that command discovery reflects my current privileges without exposing admin command names.

#### Acceptance Criteria

1. When ユーザーが `!help` を実行する, the BanchoBot command feature shall 実行者が現在の実行場所で実行可能な command names の短い一覧を返す。
2. When ユーザーが required privileges を満たさない command が登録されている状態で `!help` を実行する, the BanchoBot command feature shall その command name を `!help` の一覧に含めない。
3. When ユーザーが現在の実行場所では実行できない command が登録されている状態で `!help` を実行する, the BanchoBot command feature shall その command name を `!help` の一覧に含めない。
4. When `!help` の一覧が生成される, the BanchoBot command feature shall 権限と現在の実行場所を満たす registered command を command registry の登録順で表示する。
5. When ユーザーが `!help --all` を実行する, the BanchoBot command feature shall 実行者が現在の実行場所で実行可能な command names と description の一覧を返す。
6. When ユーザーが `!help --help` を実行する, the BanchoBot command feature shall `!help` command 自身の使い方と利用可能な help options を返す。
7. When 権限を持つユーザーが public channel で `!help` を実行する, the BanchoBot command feature shall PM-only command names を `!help` の一覧に含めない。
8. The BanchoBot command feature shall `!help` command を全ユーザーが実行可能な公開 command として扱う。

### Requirement 4: 共通詳細ヘルプ

**Objective:** As a BanchoBot command user, I want each command to expose usage and argument information consistently, so that I can discover how to use a command without reading external documentation.

#### Acceptance Criteria

1. When ユーザーが実行可能な command に対して `!<command> --help` を実行する, the BanchoBot command feature shall その command の command name、usage、arguments を返す。
2. When ユーザーが required privileges を満たさない command に対して `!<command> --help` を実行する, the BanchoBot command feature shall `Unknown command. Type !help for available commands.` を返す。
3. When command detail help displays arguments, the BanchoBot command feature shall 各 argument の name、required status、description を表示できるようにする。
4. When command help content is displayed in chat, the BanchoBot command feature shall required privileges を表示しない。
5. When `--help` が command name 直後の first argument として渡される, the BanchoBot command feature shall 共通詳細ヘルプ要求として扱う。
6. When `--help` が command name 直後以外の位置に渡される, the BanchoBot command feature shall その argument を command handler に通常 argument として渡す。
7. When `--all` が `!help` の command name 直後の first argument として渡される, the BanchoBot command feature shall 概要付き command 一覧要求として扱う。

### Requirement 5: 既存 command 互換性

**Objective:** As a stable client user, I want existing BanchoBot commands to keep their current behavior, so that adding the admin foundation does not regress normal chat workflows.

#### Acceptance Criteria

1. When ユーザーが `!roll` を実行する, the BanchoBot command feature shall 既存の `!roll` 実行結果と response target semantics を維持する。
2. When ユーザーが `!help` を実行する, the BanchoBot command feature shall 既存の command name 一覧形式を維持しつつ権限に応じて一覧を絞り込む。
3. When ユーザーが command prefix で始まらない message を送信する, the BanchoBot command feature shall BanchoBot command response を生成しない。
4. When ユーザーが command prefix だけ、または空の command name を送信する, the BanchoBot command feature shall BanchoBot command response を生成しない。
5. When registered command handler が response を返さない, the BanchoBot command feature shall BanchoBot command response を生成しない。
6. The BanchoBot command feature shall not add new player-visible admin commands as part of this feature.

### Requirement 6: 引数エラー処理の境界

**Objective:** As a BanchoBot command maintainer, I want common help metadata to be reusable without forcing one validation model on all commands, so that each future admin command can define its own business-specific argument behavior.

#### Acceptance Criteria

1. Where command-specific argument validation is needed, the BanchoBot command feature shall allow the command handler to decide the user-visible validation response.
2. Where command handler chooses to show usage after an argument error, the BanchoBot command feature shall make the registered usage and argument help information available for that response.
3. The BanchoBot command feature shall not require all registered commands to use a shared argument validation error format.
