# Implementation Plan

- [ ] 1. Foundation: authorization refresh の共有モデルと contract
- [x] 1.1 session authorization snapshot と refresh outcome を定義する
  - `privileges` と `role_ids` を一つの認可 snapshot として扱えるようにする。
  - per-user refresh と per-role refresh の結果を `refreshed`、`no active session`、`failed` として区別できるようにする。
  - completed state は、domain tests が snapshot の immutable behavior、role ID 正規化、各 outcome の意味を検証していること。
  - _Requirements: 5.1, 5.5, 6.1_
  - _Boundary: SessionAuthorization_

- [ ] 1.2 active session の authorization-only update contract を定義する
  - session lifecycle contract とは別に、active session の認可情報だけを更新する contract を追加する。
  - token、user mapping、client metadata、logged-in state を保持する postcondition を contract test で表現する。
  - completed state は、session store protocol と既存 test doubles が authorization-only update を必須 contract として扱っていること。
  - _Requirements: 1.4, 4.1, 4.2, 5.3, 5.5, 6.3, 6.4_
  - _Boundary: SessionStore_

- [ ] 1.3 role 更新で影響を受ける user discovery contract を定義する
  - role permissions update 後に、その role を持つ users を列挙できる contract を追加する。
  - role mutation workflow 自体は追加せず、refresh service が使う read boundary として定義する。
  - completed state は、assigned users が deterministic に返る contract と、未割り当て role が空結果になる behavior が検証可能になっていること。
  - _Requirements: 2.1, 2.3, 2.4, 6.2_
  - _Boundary: RoleRepository_

- [ ] 2. Core implementations: state と role lookup の実装
- [ ] 2.1 (P) InMemory session store で authorization-only update を実装する
  - active user の session では `privileges` と `role_ids` だけを更新する。
  - offline user では session を作らず `no active session` として扱える結果を返す。
  - completed state は、同じ token で取得した session が更新後の認可情報を持ち、他の session fields と他 user の session が変わらないこと。
  - _Requirements: 1.4, 3.4, 4.1, 4.2, 5.3, 6.3, 6.4_
  - _Boundary: SessionStore InMemory_
  - _Depends: 1.1, 1.2_

- [ ] 2.2 (P) Valkey session store で atomic authorization update を実装する
  - current user-token mapping から active session を特定し、保存済み session の認可 fields だけを atomic に更新する。
  - token mapping、既存 TTL、非認可 fields を保持し、session が消えている場合は session を再作成しない。
  - completed state は、Valkey integration tests が token preservation、field preservation、offline user の no-op、連続 refresh の latest result を検証していること。
  - _Requirements: 1.4, 3.4, 4.1, 4.2, 5.3, 5.4, 6.3, 6.4_
  - _Boundary: SessionStore Valkey_
  - _Depends: 1.1, 1.2_

- [ ] 2.3 (P) RoleRepository で assigned user lookup を実装する
  - memory と SQLAlchemy の role repository が role ID から assigned users を返せるようにする。
  - unrelated role assignment を含めず、role update の affected user set を安定した順序で返す。
  - completed state は、repository tests が assigned users、unassigned role、unrelated assignments、複数 user の並びを検証していること。
  - _Requirements: 2.1, 2.3, 2.4, 6.2_
  - _Boundary: RoleRepository_
  - _Depends: 1.3_

- [ ] 2.4 (P) current role state から session authorization snapshot を計算する
  - role list から permission OR と role ID list を同じ snapshot として生成する。
  - login と refresh が同じ認可 snapshot を使えるよう、既存 permission behavior と client flag conversion を維持する。
  - completed state は、permission service tests が no-role、single-role、multi-role、role ordering、permission OR を snapshot として検証していること。
  - _Requirements: 1.5, 4.5, 5.1, 6.6_
  - _Boundary: PermissionService_
  - _Depends: 1.1_

- [ ] 3. Service orchestration and composition
- [ ] 3.1 login authorization calculation を共有 snapshot に揃える
  - successful login の session data と login response が共有 snapshot 由来の `privileges` と `role_ids` を使うようにする。
  - 既存の login result、token issuance、session replacement、login permissions packet behavior を変えない。
  - completed state は、auth service tests が login session と response の authorization が同じ snapshot から作られることを検証していること。
  - _Requirements: 4.5, 5.1, 6.6_
  - _Boundary: AuthService_
  - _Depends: 2.4_

- [ ] 3.2 user 単位の authorization refresh を実装する
  - active session がある user では現在の role-derived snapshot を session store へ適用する。
  - active session がない user では session を作らず、呼び出し元へ no active session outcome を返す。
  - role grant / revoke 後の状態を test setup で表現し、refresh 後の session authorization が最新状態になることを検証する。
  - completed state は、per-user refresh tests が refreshed と no active session を区別し、token を維持したまま subsequent authorization が変わることを検証していること。
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 4.1, 4.2, 4.4, 5.5, 6.1, 6.3, 6.4_
  - _Boundary: SessionAuthorizationService_
  - _Depends: 2.1, 2.2, 2.4_

- [ ] 3.3 refresh failure と repeated refresh の service behavior を実装する
  - role-derived snapshot を決定できない場合は existing session authorization を保存したまま failed outcome を返す。
  - 同じ role state への repeated refresh は duplicate session を作らず equivalent authorization を保つ。
  - sequential role changes では latest completed refresh が subsequent authorization decision を決めるようにする。
  - completed state は、service tests が compute failure preservation、store update failure、idempotent refresh、latest refresh result を検証していること。
  - _Requirements: 1.3, 5.2, 5.3, 5.4, 5.5, 6.1_
  - _Boundary: SessionAuthorizationService_
  - _Depends: 3.2_

- [ ] 3.4 role 単位の authorization refresh を実装する
  - role permissions update 後、assigned users だけを対象に user refresh を適用する。
  - affected active users、offline assigned users、unaffected active users の outcome を分けて扱う。
  - completed state は、role refresh tests が複数 affected sessions、unaffected session preservation、no active assigned users、permission removal を検証していること。
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 5.5, 6.2_
  - _Boundary: SessionAuthorizationService_
  - _Depends: 2.3, 3.3_

- [ ] 3.5 refresh service を composition へ登録する
  - application composition が refresh service と必要な collaborators を解決できるようにする。
  - test environment と non-test environment の既存 registration pattern を維持する。
  - completed state は、DI integration tests が refresh service を manual test-only wiring なしで resolve できること。
  - _Requirements: 6.6_
  - _Boundary: Composition_
  - _Depends: 3.4_

- [ ] 4. Bancho-facing integration behavior
- [ ] 4.1 Bancho C2S handler が action-time authorization を読むことを保護する
  - handler が login-time cached authorization ではなく、action ごとの session authorization を downstream service へ渡すことを検証する。
  - refreshed `privileges` と `role_ids` が channel message / join flow の authorization input に反映されることを検証する。
  - completed state は、transport unit tests が updated session authorization を次の C2S action で観測できること。
  - _Requirements: 2.5, 3.3, 3.5, 6.5_
  - _Boundary: BanchoHandlers_
  - _Depends: 3.5_

- [ ] 4.2 refreshed authorization を stable bancho の後続操作で検証する
  - 同じ session token のまま、role grant refresh 後に許可される channel action を検証する。
  - role permission removal refresh 後に拒否される channel action を検証する。
  - completed state は、chat / polling integration tests が再ログインなしの deny → allow → deny または同等の ACL transition を示していること。
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 6.5_
  - _Boundary: Bancho integration tests_
  - _Depends: 4.1_

- [ ] 4.3 session invalidation と authorization refresh の分離を検証する
  - refresh path が session deletion を呼ばず、logout / invalidation path が引き続き session deletion を担うことを検証する。
  - role assignment change や role permissions change を authentication failure として扱わないことを検証する。
  - completed state は、refresh 後も polling token が有効であり、EXIT / invalidation regression tests は既存どおり session を削除すること。
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 6.4_
  - _Boundary: Session lifecycle regression_
  - _Depends: 4.2_

- [ ] 5. Validation and regression gates
- [ ] 5.1 service / store / repository の focused validation を実行する
  - domain、session store、role repository、permission service、refresh service の unit / integration tests を実行する。
  - failure が出た場合は owning boundary の task へ戻り、test skip や broad suppression ではなく root cause を直す。
  - completed state は、direct grant / revoke、role permissions update、offline user、login-state preservation の focused tests が通過していること。
  - _Requirements: 6.1, 6.2, 6.3, 6.4_
  - _Boundary: Focused validation_
  - _Depends: 4.3_

- [ ] 5.2 stable bancho と login / polling の regression validation を実行する
  - chat E2E、polling E2E、login flow、transport handler regression を実行する。
  - existing login、session storage、polling、channel authorization coverage を弱めずに通過させる。
  - completed state は、refreshed authorization の bancho-facing tests と既存 login / polling regression tests が同時に通過していること。
  - _Requirements: 3.3, 3.4, 4.5, 6.5, 6.6_
  - _Boundary: Bancho regression validation_
  - _Depends: 5.1_

- [ ] 5.3 static, format, architecture checks を通過させる
  - ruff、ruff format check、basedpyright strict、import-linter を実行する。
  - 型エラーや lint failure は design boundary に沿って修正し、file-level suppression や test weakening は行わない。
  - completed state は、required quality gates が通過し、追加した refresh contracts が architecture rule に違反していないこと。
  - _Requirements: 6.6_
  - _Boundary: Quality gates_
  - _Depends: 5.2_
