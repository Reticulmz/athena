# Implementation Plan

- [ ] 1. Foundation: HIBP 設定と診断安全性の下地
- [ ] 1.1 HIBP wait cap と range evidence freshness cap を設定として扱えるようにする
  - HIBP 外部待機上限は既定値 1.0 秒として読み込まれる。
  - HIBP range cache TTL は既定値 86,400 秒として読み込まれる。
  - timeout は 0 以下または 1.0 秒超の値を validation error として拒否する。
  - TTL は 0 以下または 86,400 秒超の値を validation error として拒否する。
  - typed config factory から新しい設定値を明示的に指定できる。
  - 完了時には config default、valid stricter value、invalid value の focused tests が通る。
  - _Requirements: 2.2, 2.4_
  - _Boundary: AppConfig_

- [ ] 1.2 (P) password-derived evidence をログ防御リストで確実にマスクする
  - SHA-1 全体、prefix、suffix、HIBP response body、cache key、verdict 名の accidental logging を mask 対象にする。
  - 既存の password、password_hash、password_md5 mask behavior は維持する。
  - 完了時には sensitive field masking tests が新旧 key の両方で通る。
  - _Requirements: 5.2, 5.4, 5.5_
  - _Boundary: SafeDiagnostics_

- [ ] 2. Core: HIBP range evidence の取得、保存、判定
- [ ] 2.1 HIBP range provider が外部 request contract を満たすようにする
  - HIBP range request は SHA-1 prefix のみを使い、password や suffix を送信しない。
  - request は configured timeout と fixed User-Agent header を必ず含む。
  - timeout、non-success HTTP、HTTP client failure は typed unavailable/timeout status として返る。
  - provider は suffix matching や cache storage を行わない。
  - 完了時には network call なしの provider unit tests が URL、timeout、User-Agent、failure status を検証する。
  - _Requirements: 2.4, 3.1, 5.1, 5.2, 5.5_
  - _Boundary: HTTPHIBPRangeProvider_

- [ ] 2.2 (P) Valkey に HIBP range evidence を TTL 付きで保存できるようにする
  - cache hit、miss、unavailable を typed status として返す。
  - successful range response body は configured TTL 付きで保存され、stale evidence は Valkey expiry に任せる。
  - cached bytes は UTF-8 text として読み戻される。
  - cache key と response body は log や diagnostics に出さない。
  - 完了時には typed fake tests が hit、miss、set with expiry、decode、read/write unavailable を検証する。
  - _Depends: 1.1_
  - _Requirements: 2.1, 2.2, 2.3, 3.2, 3.3, 5.2_
  - _Boundary: ValkeyHIBPRangeCache_

- [ ] 2.3 Cached HIBP client が cache-first 判定と fail-open を統合する
  - password から SHA-1 prefix/suffix を request-local memory 内で導出する。
  - fresh cache hit では external provider を呼ばずに suffix matching する。
  - cache miss または cache read unavailable では provider を試し、成功 evidence は current decision に使う。
  - cache write unavailable でも current evidence を捨てず、provider timeout/unavailable では external compromised-password portion のみ fail-open する。
  - diagnostics は safe category のみを出し、password-derived data と per-password verdict を出さない。
  - 完了時には cache hit no-provider、cache miss store、timeout/unavailable fail-open、write failure current evidence、suffix matching、safe diagnostics の unit tests が通る。
  - _Depends: 2.1, 2.2_
  - _Requirements: 1.4, 2.1, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 5.1, 5.2, 5.3_
  - _Boundary: CachedHIBPClient_

- [ ] 3. Integration: production graph と identity workflow への接続
- [ ] 3.1 Production provider graph で cached HIBP dependency を構成する
  - production graph は range cache、range provider、cached HIBP client を app-scope runtime dependencies から構成する。
  - provider graph は config の timeout と TTL を cached HIBP behavior に渡す。
  - explicit test override は service-facing HIBP replacement のまま維持し、production HIBP dependencies を要求しない。
  - 完了時には app provider graph tests が cached HIBP dependency と test override behavior を検証する。
  - _Depends: 1.1, 2.1, 2.2, 2.3_
  - _Requirements: 2.1, 2.2, 2.4, 3.2, 3.3, 4.4_
  - _Boundary: InfrastructureProviderSet_

- [ ] 3.2 Registration と password operation scope の observable behavior を保つ
  - account-creating registration と validation-only registration は同じ Password Safety Check outcome を使う。
  - local password policy、custom banned list、compromised evidence match は generic password validation error として reject される。
  - external evidence fail-open 時は local rules が通る場合のみ registration response を provider failure detail なしで継続する。
  - worker job、task payload、post-registration audit は Password Safety Check の source of truth にならない。
  - Administrative Password Reset/dev tooling は current-password proof と external evidence availability を要求せず、既存 tooling name を変えない。
  - 現行の internal change-password command は public Self-Service Password Change API として扱わず、将来 public API を追加する場合だけ current-password proof を別 spec で扱う。
  - 完了時には registration/auth/admin reset regression tests が上記の user-visible behavior と boundary を検証する。
  - _Depends: 3.1_
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 3.4, 4.1, 4.2, 4.3, 4.4, 4.5, 5.3, 5.4, 5.5_
  - _Boundary: AuthService, PasswordService, Administrative Password Reset_

- [ ] 4. Focused feature tests と品質ゲートを通す
  - config、logging、HIBP provider、range cache、cached client、composition、registration の focused tests を実行する。
  - type safety、ruff、import-linter の feature-relevant quality checks を実行し、失敗は owning boundary で直す。
  - 完了時には focused test set と quality checks が pass し、password-derived data が diagnostics、cache verdict、worker payload に現れないことを確認できる。
  - _Depends: 3.2_
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4, 5.5_
  - _Boundary: Validation_
