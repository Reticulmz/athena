# Requirements Document

## Introduction

Athena の公開登録では、漏洩済みパスワードを拒否する Password Safety Check を同期ガードとして維持しながら、外部 compromised-password evidence の待ち時間が登録体験を悪化させないようにする。利用者には従来通り、危険なパスワードは登録成功前に拒否され、外部 evidence が遅延または利用不能な場合でもローカル password policy と custom banned-password list は維持される。

## Boundary Context

- **In scope**: 公開 account registration の Password Safety Check、将来の Self-Service Password Change に同じ安全性を適用する要件、fresh compromised-password evidence の 24時間再利用、外部 evidence 待機の 1.0秒上限、fail-open 時の operator diagnostics、credential-derived data の非露出。
- **Out of scope**: Worker-side post-registration password audit、Administrative Password Reset / dev CLI の rename または外部 evidence 依存化、同一 evidence request の分散集約、WebUI password change の具体的な公開 interface 設計。
- **Adjacent expectations**: Administrative Password Reset と Self-Service Password Change は別の identity operation として扱う。WebUI が将来 Self-Service Password Change を提供する場合、この feature の Password Safety Check semantics を前提にする。

## Requirements

### Requirement 1: Synchronous Password Safety Gate

**Objective:** As a registering user, I want unsafe passwords to be rejected before account creation succeeds, so that account state remains predictable and does not depend on later audit.

#### Acceptance Criteria

1. When public account registration evaluates a candidate password, the Account Registration workflow shall complete the Password Safety Check before returning registration success.
2. When the Password Safety Check determines that a candidate password violates local password policy, the Account Registration workflow shall reject registration with a password validation error.
3. When the Password Safety Check determines that a candidate password is in the custom banned-password list, the Account Registration workflow shall reject registration with a password validation error.
4. When the Password Safety Check determines from compromised-password evidence that a candidate password is compromised, the Account Registration workflow shall reject registration with a password validation error.
5. When account registration is requested in validation-only mode, the Account Registration workflow shall apply the same Password Safety Check outcome as account-creating registration.
6. The Account Registration workflow shall not treat a worker-side post-registration audit as the source of truth for whether a password passed the Password Safety Check.

### Requirement 2: Evidence Freshness and Responsiveness

**Objective:** As a registering user, I want repeated password safety checks to avoid unnecessary external waiting, so that registration remains responsive while still using recent compromised-password evidence.

#### Acceptance Criteria

1. When fresh compromised-password range evidence for a candidate password is available, the Password Safety Check shall evaluate the candidate password without waiting for the external evidence provider.
2. The Password Safety Check shall treat compromised-password range evidence as fresh for no longer than 24 hours after it is obtained successfully.
3. When compromised-password range evidence is older than 24 hours, the Password Safety Check shall not use it as fresh evidence for a candidate password decision.
4. If no fresh compromised-password range evidence is available and the external evidence provider does not respond within 1.0 seconds, the Password Safety Check shall continue without an external compromised-password verdict.
5. When newly obtained or fresh compromised-password range evidence does not identify the candidate password as compromised, the Password Safety Check shall allow the caller to continue to the remaining registration or password-change rules.

### Requirement 3: Fail-Open Degradation

**Objective:** As a registering user, I want temporary external safety-check failures not to block registration when local password rules pass, so that account creation is not dependent on third-party availability.

#### Acceptance Criteria

1. If the external compromised-password evidence provider is unavailable, the Password Safety Check shall fail open for the external compromised-password portion of the decision.
2. If fresh compromised-password evidence cannot be read, the Password Safety Check shall still attempt the external compromised-password check within the configured 1.0 second wait limit.
3. If newly obtained compromised-password evidence cannot be preserved for future reuse, the Password Safety Check shall still use the current evidence for the current password decision.
4. If both fresh compromised-password evidence and the external evidence provider are unavailable, the Password Safety Check shall allow registration to continue when local password policy and custom banned-password list checks pass.
5. When the Password Safety Check fails open for external compromised-password evidence, Athena shall make the fail-open outcome visible to operators without changing the user's successful registration response.

### Requirement 4: Password Operation Scope

**Objective:** As an operator and future WebUI user, I want public self-service password changes to follow registration-grade safety while administrative resets remain separate, so that the two identity operations are not confused.

#### Acceptance Criteria

1. Where Self-Service Password Change is provided, Athena shall require current-password proof before returning password-change success.
2. Where Self-Service Password Change is provided, Athena shall complete the Password Safety Check for the new password before returning password-change success.
3. Where Administrative Password Reset is used by operator or development tooling, Athena shall not require the user's current-password proof as part of this feature.
4. Where Administrative Password Reset is used by operator or development tooling, Athena shall not require external compromised-password evidence availability as part of this feature.
5. The feature shall not rename existing development password tooling.

### Requirement 5: Privacy and Operator Diagnostics

**Objective:** As an operator, I want to observe Password Safety Check performance and degradation without exposing password-derived data, so that registration issues can be diagnosed safely.

#### Acceptance Criteria

1. When the Password Safety Check uses fresh evidence, obtains new evidence, times out, or fails open, Athena shall record an operator-observable diagnostic category for that outcome.
2. The Password Safety Check diagnostics shall not include plaintext passwords, password hashes, complete SHA-1 values, SHA-1 prefixes, SHA-1 suffixes, compromised-password evidence bodies, or per-password safe/compromised cached verdicts.
3. The Password Safety Check shall not place plaintext passwords or password-derived compromised-check material into worker job payloads for this feature.
4. When registration is rejected because a password is compromised, Athena shall expose only a password validation error to the user and shall not expose compromised-password evidence details.
5. When external compromised-password evidence is unavailable and the check fails open, Athena shall not expose third-party provider failure details to the registering user.
