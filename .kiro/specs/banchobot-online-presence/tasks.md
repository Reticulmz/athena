# Implementation Plan

- [ ] 1. Foundation: identity and active-session boundaries
- [x] 1.1 Define BanchoBot as a system identity
  - Establish a single immutable identity for BanchoBot that can be shared by login roster construction and command responses.
  - Preserve the existing BanchoBot user ID and display name values through that identity.
  - Completed state is observable when identity tests prove the ID, display name, and immutability, and no session data is created for BanchoBot.
  - _Requirements: 2.1, 2.2, 3.4_

- [x] 1.2 Codify active human session list semantics
  - Keep the online-user service contract focused on active human sessions rather than roster-visible system users.
  - Add regression coverage that BanchoBot is not implicitly appended to active session IDs.
  - Completed state is observable when lifecycle and online-user tests show human disconnect fan-out never targets BanchoBot.
  - _Requirements: 3.3, 3.4_

- [ ] 2. Core online roster and sender behavior
- [x] 2.1 Add BanchoBot to the successful login roster
  - Build the initial roster from BanchoBot plus the relevant active human users without duplicate IDs.
  - Emit BanchoBot presence before the roster bundle and before any BanchoBot command response can be displayed by the client.
  - Preserve the existing connecting-user presence, stats packet, channel packets, friends packet, and silence packet behavior.
  - Completed state is observable when login response tests decode BanchoBot presence and the roster bundle contains BanchoBot exactly once alongside the human roster.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.4, 3.1, 3.2_

- [ ] 2.2 (P) Align command responses with the shared BanchoBot identity
  - Make channel command responses and private command responses use the same BanchoBot identity that the login roster exposes.
  - Preserve existing command names, command parsing, response content, response target selection, and delivery behavior.
  - Completed state is observable when command-service and chat-handler tests prove every BanchoBot response uses the shared sender ID and display name.
  - _Requirements: 2.1, 2.2, 2.3, 4.1, 4.2, 4.3, 4.4_
  - _Boundary: CommandService_

- [ ] 3. Integration and validation
- [ ] 3.1 Verify login-to-command identity consistency end to end
  - Add protocol-level integration coverage for a successful login followed by channel and private command responses.
  - Verify the client receives BanchoBot presence before observing a BanchoBot-authored message.
  - Verify normal human users remain visible in the roster when BanchoBot is present and are not hidden or replaced.
  - Completed state is observable when integration tests show the roster identity and command sender identity match for BanchoBot.
  - _Requirements: 1.1, 1.2, 2.1, 2.2, 2.3, 3.1, 3.2, 4.1, 4.2, 4.3_

- [ ] 3.2 Run final quality and regression checks
  - Run the targeted unit and integration tests that cover identity, login roster, lifecycle fan-out, and command response behavior.
  - Run the project quality checks required for Python source changes.
  - Completed state is observable when all targeted tests and quality checks pass with no skipped required coverage.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4_
