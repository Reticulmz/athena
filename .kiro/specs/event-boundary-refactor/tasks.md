# Implementation Plan

- [x] 1. 基盤: 境界テストと安全柵を整える
- [x] 1.1 Local Event の既存挙動をテストで固定する
  - 同一 process 内の fanout として現在の delivery 挙動を捕捉する。
  - handler の呼び出し順が登録順のまま維持されることを検証する。
  - 1 つの local handler が失敗してもログに記録され、後続 handler の実行を止めないことを検証する。
  - 完了時には、local delivery が worker や別 replica への通知保証ではないことをテストから読み取れる。
  - _Requirements: 1.3, 2.1, 2.2, 2.3, 6.5_

- [x] 1.2 Distributed Event の contract test を追加する
  - distributed notification envelope が identity、type、発生時刻、schema version、primitive payload を持つことを検証する。
  - domain dataclass を暗黙 serialize せず、明示 mapper を通じて payload と event を往復できることを検証する。
  - missed delivery が durable source of truth ではない non-durable notification として扱われることを検証する。
  - 完了時には、concrete transport runtime なしで publisher / subscriber port の契約を検証できる。
  - _Requirements: 1.2, 4.1, 4.2, 4.3, 4.4, 5.2, 5.3, 6.5_

- [x] 1.3 event 分類の boundary regression test を追加する
  - migration 後に旧 EventBus 名を production code が import していないことを検出する。
  - chat send workflow が persistence のために Local Event や chat message domain event へ依存していないことを検出する。
  - local listener が channel / private chat persistence event を購読していないことを検出する。
  - Distributed Event contract が Chat Persistence Work の source of truth として使われていないことを検出する。
  - 完了時には、Local Event、Distributed Event、Durable Work の境界が再混在した場合にテストが失敗する。
  - _Requirements: 1.4, 1.5, 2.4, 4.5, 5.4, 5.5, 6.4, 6.5_

- [x] 2. Core messaging contracts
- [x] 2.1 Local Event 境界を実装する
  - local-only event bus contract と in-memory implementation を messaging 境界に導入する。
  - fire-and-forget local handler semantics、例外分離、登録順 invocation を維持する。
  - `UserDisconnected` を durable event にせず、local lifecycle event として使える状態を維持する。
  - 完了時には、1.1 の Local Event テストが local-only 名称と挙動で通る。
  - _Requirements: 1.3, 2.1, 2.2, 2.3, 5.1, 6.2_

- [x] 2.2 (P) Distributed Event contract を実装する
  - non-durable envelope、mapper、publisher、subscriber contract を追加する。
  - contract surface とテストで primitive payload shape を保証する。
  - Valkey Pub/Sub adapter、subscriber loop、replay behavior、persistence layer は追加しない。
  - 完了時には、1.2 の Distributed Event テストが外部 transport を起動せずに通る。
  - _Requirements: 1.2, 4.1, 4.2, 4.3, 4.4, 5.2, 5.3_
  - _Boundary: Distributed Event Contract_
  - _Depends: 1.2_

- [x] 3. Chat Persistence Work boundary
- [x] 3.1 (P) Chat Persistence Work の publish contract を定義する
  - channel / private chat persistence work value を domain event ではなく Durable Work input として導入する。
  - accepted chat send workflow が使う service-facing publisher contract を定義する。
  - accepted / rejected message case を typed fake publisher で検証する。
  - 完了時には、taskiq なしで exact channel/private work input と no-work outcome を観測できる。
  - _Requirements: 1.1, 2.4, 3.1, 3.2, 3.3, 3.4, 4.5_
  - _Boundary: ChatPersistenceWorkPublisher_
  - _Depends: 1.3_

- [x] 3.2 (P) transitional task publisher adapter を追加する
  - channel work を既存 channel persistence task へ、既存 enqueue argument order のまま mapping する。
  - private work を既存 private persistence task へ、既存 enqueue argument order のまま mapping する。
  - task registration が見つからない場合と enqueue failure を、accepted chat delivery response を変えずに log する。
  - 完了時には、adapter test が既存 task name と payload order の維持を証明する。
  - _Requirements: 3.5, 6.3_
  - _Boundary: TaskiqChatPersistenceWorkPublisher_
  - _Depends: 3.1_

- [x] 3.3 (P) accepted chat send workflow を Durable Work publication へ移す
  - channel message は validation、delivery resolution、rate limiting が成功した後だけ persistence work を publish する。
  - private message は validation、rate limiting、target resolution が成功した後だけ persistence work を publish する。
  - stable chat delivery result と command response behavior を維持しつつ、local event persistence trigger を取り除く。
  - 完了時には、use-case tests が accepted message の work publication と rejected / missing-target の no-work を示す。
  - _Requirements: 1.1, 1.5, 2.4, 3.1, 3.2, 3.3, 3.4, 6.1_
  - _Boundary: Send Chat Use-cases_
  - _Depends: 3.1_

- [x] 4. Stable local listener cleanup
- [x] 4.1 stable listener に local disconnect behavior だけを残す
  - stable local listener registration から channel / private chat persistence subscription を取り除く。
  - channel membership cleanup は best-effort な local `UserDisconnected` cleanup として維持する。
  - stable client 向け USER_QUIT packet fanout behavior を維持する。
  - 完了時には、listener tests が disconnect cleanup の維持と、chat persistence enqueue が local listener に残っていないことを示す。
  - _Requirements: 2.4, 5.1, 5.4, 5.5, 6.2_

- [x] 4.2 obsolete な chat persistence event usage を撤去する
  - production code が依存しなくなった channel / private chat persistence event value を削除または退役させる。
  - domain / service tests では chat history persistence を Durable Work publication 経由で検証する。
  - `UserDisconnected` は local lifecycle event として残す。
  - 完了時には、production code に chat message domain event を persistence 起動境界として使う依存が残らない。
  - _Requirements: 1.4, 1.5, 2.4, 4.5, 6.4, 6.5_

- [x] 5. Composition and runtime wiring
- [x] 5.1 local-event call site を local-only 境界へ移行する
  - lifecycle handler、listener group、provider wiring、関連 tests を Local Event 境界へ更新する。
  - consumer migration 後に曖昧な production event bus surface を取り除く。
  - stable EXIT、PONG、session deletion、USER_QUIT の observable behavior を維持する。
  - 完了時には、provider / lifecycle tests が old production import なしで local-only event bus を resolve し、実行できる。
  - _Requirements: 1.3, 2.1, 2.2, 2.3, 5.1, 6.2, 6.4, 6.5_
  - _Depends: 2.1, 4.1_

- [x] 5.2 Chat Persistence Work を app graph に wire する
  - service-facing chat persistence publisher を app container で transitional task publisher へ bind する。
  - stable local listener setup から不要になった broker dependency を取り除く。
  - public container factory signature を変えず、test-environment branching も追加しない。
  - 完了時には、composition tests が publisher 付きの chat send use-case を resolve し、既存 task registration を維持していることを示す。
  - _Requirements: 3.1, 3.2, 3.5, 6.1, 6.3, 6.4, 6.5_
  - _Depends: 3.2, 3.3, 4.1_

- [x] 5.3 provider replacement と dependency resolution tests を更新する
  - old event bus override を Local Event override に置き換える。
  - chat persistence publisher の明示的な test override coverage を追加する。
  - app / worker graph construction が production branching なしで成功することを検証する。
  - 完了時には、composition test suite が stale provider import と publisher binding 不足を検出できる。
  - _Requirements: 6.4, 6.5_
  - _Depends: 5.1, 5.2_

- [x] 6. Compatibility and final validation
- [x] 6.1 (P) chat pipeline compatibility を検証する
  - persistence を Durable Work publication へ移した後も、channel chat が同じ stable packet behavior で delivery されることを検証する。
  - private chat が target resolution と既存 delivery outcome を維持することを検証する。
  - 既存 chat persistence task name と enqueue payload order が変わっていないことを検証する。
  - 完了時には、accepted channel/private message と no-work rejection case の integration tests が通る。
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 6.1, 6.3, 6.5_
  - _Boundary: Chat Pipeline Compatibility_
  - _Depends: 5.2, 5.3_

- [x] 6.2 (P) stable lifecycle compatibility を検証する
  - stable PONG / EXIT workflow が既存の observable behavior を保つことを検証する。
  - EXIT が session を削除し、他 online user 向けに USER_QUIT を enqueue することを検証する。
  - disconnect notification が best-effort のままで、membership recovery truth として扱われないことを検証する。
  - 完了時には、lifecycle / C2S pipeline tests が Local Event naming で通る。
  - _Requirements: 5.1, 5.4, 5.5, 6.2, 6.5_
  - _Boundary: Stable Local Listeners_
  - _Depends: 5.1, 5.3_

- [x] 6.3 boundary と quality gate を実行する
  - messaging、chat、stable lifecycle、jobs、composition の affected unit / integration tests を実行する。
  - design で要求された lint、type、import-boundary checks を実行する。
  - production code が旧 EventBus 名を import していないこと、Distributed Event を durable work として使っていないことを確認する。
  - 完了時には、targeted tests と quality / import checks が clean になるか、残る失敗が root cause 付きで明示される。
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 4.1, 4.2, 4.3, 4.4, 4.5, 6.4, 6.5_
  - _Depends: 6.1, 6.2_
