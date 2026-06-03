# Requirements Document

## Introduction

サーバー管理者が、BanchoBot の表示名をデプロイ環境ごとに設定できるようにします。未設定時は既存の表示名 `BanchoBot` を維持し、`user_id=1` は osu! bancho protocol 上の予約 ID として固定します。

この機能は BanchoBot のユーザー可視な表示名を設定可能にするものであり、BanchoBot を通常ユーザーとしてログイン可能にするものではありません。

## Boundary Context

- **In scope**: BanchoBot の表示名設定、表示名バリデーション、`user_id=1` の予約、BanchoBot system user record の表示名同期、BanchoBot 名の通常ユーザー登録からの保護。
- **Out of scope**: BanchoBot の user_id 設定、email/password_hash/country など表示名以外の属性設定、実行中の動的設定反映、過去に使った Bot 名の履歴予約、内部ログイベント名やコード上の概念名の変更。
- **Adjacent expectations**: BanchoBot の発言履歴や将来の表示 API は、`user_id=1` の system user record を参照する場合、現在設定中の BanchoBot 表示名に追従して表示されます。

## Requirements

### Requirement 1: BanchoBot 表示名設定

**Objective:** As a サーバー管理者, I want BanchoBot の表示名を設定できる, so that デプロイ環境ごとに Bot の見え方を調整できる

#### Acceptance Criteria

1. When BanchoBot 表示名が設定されていない, the athena server shall BanchoBot の表示名として `BanchoBot` を使用する
2. When BanchoBot 表示名が設定されている, the athena server shall BanchoBot として表示されるすべてのユーザー可視箇所で設定済み表示名を使用する
3. While athena server が起動中である, the athena server shall 起動時に読み込まれた BanchoBot 表示名を維持する
4. The athena server shall BanchoBot の user_id を常に `1` として扱う
5. The athena server shall BanchoBot の user_id を管理者設定の対象にしない

### Requirement 2: BanchoBot 表示名バリデーション

**Objective:** As a サーバー管理者, I want 不正な BanchoBot 表示名を起動前に検出したい, so that 意図しない Bot 表示名でサービスが稼働しない

#### Acceptance Criteria

1. When BanchoBot 表示名が 2 文字以上 15 文字以下である, the athena server shall 表示名の長さを有効として扱う
2. If BanchoBot 表示名が 2 文字未満または 15 文字超である, then the athena server shall 起動を失敗させる
3. When BanchoBot 表示名が英数字、スペース、アンダースコア、ハイフンのみで構成される, the athena server shall 表示名の文字種を有効として扱う
4. If BanchoBot 表示名に許可されない文字が含まれる, then the athena server shall 起動を失敗させる
5. If BanchoBot 表示名が既存の通常ユーザー名と同じ safe_username に正規化される, then the athena server shall 起動を失敗させる
6. If BanchoBot 表示名が不正である, then the athena server shall デフォルト表示名へフォールバックしない

### Requirement 3: BanchoBot 名の予約

**Objective:** As a サーバー管理者, I want BanchoBot の表示名を通常ユーザーが取得できないようにしたい, so that Bot なりすましや名前衝突を防げる

#### Acceptance Criteria

1. When athena server が起動する, the athena server shall `BanchoBot` を通常ユーザー登録で使用不可な予約名として扱う
2. When athena server が起動する and BanchoBot 表示名が `BanchoBot` 以外に設定されている, the athena server shall 設定済み BanchoBot 表示名を通常ユーザー登録で使用不可な予約名として扱う
3. When 通常ユーザー登録で BanchoBot の予約名と同じ safe_username になる username が送信される, the athena server shall その登録を拒否する
4. The athena server shall BanchoBot 名の比較と予約に通常ユーザー名と同じ safe_username 正規化を使用する
5. The athena server shall 過去に設定されていた BanchoBot 表示名を自動的に予約し続けない

### Requirement 4: BanchoBot system user record

**Objective:** As a サーバー管理者, I want BanchoBot を永続化参照可能な system user record として扱いたい, so that Bot 発言の履歴や外部キー参照を一貫して扱える

#### Acceptance Criteria

1. When athena server が起動する, the athena server shall `users.id=1` を BanchoBot の system user record として扱う
2. If `users.id=1` が BanchoBot 以外の通常ユーザーとして存在する, then the athena server shall 起動を失敗させる
3. When BanchoBot system user record が存在しない, the athena server shall `user_id=1` の BanchoBot system user record を利用可能な状態にする
4. When BanchoBot system user record の username または safe_username が設定済み BanchoBot 表示名と一致しない, the athena server shall BanchoBot system user record を設定済み表示名に同期する
5. The athena server shall `user_id=1` を通常ユーザー登録や通常ユーザー作成で割り当てない
6. The athena server shall BanchoBot system user record を通常ログイン、通常登録、通常セッション作成の対象にしない
7. The athena server shall BanchoBot の設定対象を表示名に限定する

### Requirement 5: BanchoBot 表示の一貫性

**Objective:** As a bancho client 利用者, I want BanchoBot がすべての場所で同じ名前に見える, so that Bot の識別が一貫する

#### Acceptance Criteria

1. When ログイン応答に BanchoBot が含まれる, the athena server shall BanchoBot の表示名として設定済み表示名を返す
2. When BanchoBot が private message を送信する, the athena server shall 送信者名として設定済み表示名を使用する
3. When BanchoBot がコマンド応答を送信する, the athena server shall Bot 表示名として設定済み表示名を使用する
4. Where BanchoBot の発言履歴が `user_id=1` から表示される, the athena server shall 現在設定中の BanchoBot 表示名で表示できる状態を提供する
5. The athena server shall 内部ログイベント名やコード上の概念名としての BanchoBot 名称変更を要求しない
