# Implementation Plan

- [x] 1. Foundation: command metadata and chat response contracts
- [x] 1.1 Define command metadata needed for authorization, destinations, and help
  - Add command metadata fields for description, usage, argument help, required privileges, and allowed destinations.
  - Replace static visibility with discoverability derived from privileges and current destination.
  - Ensure public commands remain the default when required privileges are omitted.
  - Ensure commands default to channel and PM execution when allowed destinations are omitted.
  - Completed state: existing `!roll` and `!help` can be registered with the new metadata without adding new player-visible admin commands.
  - _Requirements: 1.1, 1.2, 1.6, 3.8, 4.3, 5.6_

- [x] 1.2 Update chat contracts to carry authorization and multiple command responses
  - Introduce a shared chat authorization snapshot usable by both channel and PM sends.
  - Change command response carrying from one optional response to zero or more responses.
  - Preserve the existing command response target and content semantics for single-response commands.
  - Completed state: channel and PM chat results can represent no response, one response, and channel plus sender guidance responses.
  - _Requirements: 2.1, 2.2, 2.5, 2.6, 2.7_

- [x] 2. Core command registry and execution behavior
- [x] 2.1 Extend command registration and registry listing behavior
  - Support registration of required privileges and allowed destinations through the standard command registration contract.
  - Keep case-insensitive resolution and deterministic registration order.
  - Provide all registered command metadata to command execution so filtering can use the current user and destination.
  - Completed state: tests can register a command requiring privileges and a PM-only command without product catalog changes.
  - _Requirements: 1.1, 1.2, 1.6, 3.4, 5.6_

- [x] 2.2 Implement privilege checks for command entry authorization
  - Evaluate command required privileges using the session authorization snapshot.
  - Treat omitted privileges as public command access.
  - Require all specified privilege flags when multiple flags are configured.
  - Treat `ADMIN` as satisfying command required privileges.
  - Exclude role id, role name, and role position from entry authorization.
  - Completed state: authorized commands execute, unauthorized registered commands return the fixed unknown response, and ADMIN bypass is verified.
  - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.7, 2.3, 2.5, 2.8_

- [x] 2.3 Implement destination gating and destination guidance
  - Determine whether the invocation came from channel or PM before command execution.
  - Allow command execution only when the current destination is included in allowed destinations.
  - For authorized users in public channel on a disallowed command, return public unknown plus sender-only PM guidance.
  - For authorized users in PM on a disallowed command, return sender-only PM guidance.
  - For unauthorized users, never return destination guidance.
  - Completed state: PM-only command behavior is indistinguishable from unknown in public channel for observers, while authorized sender receives guidance.
  - _Requirements: 2.1, 2.2, 2.3, 2.6, 2.7, 2.8_

- [x] 2.4 Preserve parsing and no-response behavior
  - Keep non-command messages ignored.
  - Keep prefix-only and empty command names ignored.
  - Keep handler `None` responses as no command response.
  - Keep non-first `--help` as a normal handler argument.
  - Completed state: existing parser edge-case tests continue to pass under the tuple response contract.
  - _Requirements: 4.6, 5.3, 5.4, 5.5_

- [x] 3. Help and builtin command behavior
- [x] 3.1 Implement destination-aware command discovery for `!help`
  - Filter the short help list by both required privileges and current destination.
  - Preserve command registry order in help output.
  - Keep public channel help from showing PM-only command names, even for privileged users.
  - Preserve the existing short list format for normal public `!help`.
  - Completed state: public channel `!help` still returns `Available commands: !roll, !help` for the baseline builtin registry.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.7, 3.8, 5.2_

- [x] 3.2 Implement common help options and detail help
  - Add `!help --all` to show command names and descriptions after the same auth and destination filtering as `!help`.
  - Add `!help --help` to show help command usage and available help options.
  - Add `!<command> --help` to show command name, usage, and argument help for executable commands.
  - Ensure required privilege names are never displayed in chat help output.
  - Ensure unauthorized detail help returns the fixed unknown response.
  - Completed state: `--help` as the first argument is handled by common help behavior, and `!help --all` lists only currently executable commands.
  - _Requirements: 3.5, 3.6, 4.1, 4.2, 4.4, 4.5, 4.7_

- [x] 3.3 Update builtin `!roll` and `!help` metadata and compatibility
  - Register `!roll` and `!help` as public commands allowed in both channel and PM.
  - Add usage and argument help metadata for `!roll` and `!help`.
  - Keep normal `!roll` output unchanged.
  - Keep normal `!help` output compatible except for authorized destination-aware filtering.
  - Completed state: existing user-visible `!roll` and baseline `!help` assertions pass with the new metadata model.
  - _Requirements: 1.2, 1.6, 3.8, 4.1, 5.1, 5.2_

- [x] 4. Chat service and Bancho transport integration
- [x] 4.1 Wire command execution through channel and PM chat services
  - Pass channel authorization into command execution after existing validation and routing gates.
  - Pass PM authorization into command execution using the session-derived snapshot from the transport layer.
  - Preserve silence, rate limit, message validation, channel delivery, and PM target handling order.
  - Return tuple command responses from chat service results.
  - Completed state: commands are not executed when normal chat rejection conditions stop the message, and PM commands use current session privileges.
  - _Requirements: 2.5, 2.9_

- [x] 4.2 Enqueue multiple BanchoBot command responses in transport handlers
  - Pass session privileges and role ids into PM chat input.
  - Serialize every command response with BanchoBot identity.
  - Preserve channel response visibility for normal channel commands and unknown responses.
  - Route sender-only guidance responses only to the invoking user.
  - Completed state: a channel invocation can deliver the original message, a public unknown response, and a sender-only PM guidance response in deterministic order.
  - _Requirements: 2.1, 2.2, 2.6, 2.7_

- [x] 4.3 Update composition and type-checking integration
  - Keep builtin registry creation and command service injection compatible with the new command contracts.
  - Update worker/runtime composition paths affected by signature changes.
  - Remove stale single-response references from service and transport call sites.
  - Completed state: import resolution and static typing no longer reference obsolete command response fields or command metadata fields.
  - _Requirements: 1.1, 2.5, 5.6_

- [x] 5. Validation and regression coverage
- [x] 5.1 Add command service unit coverage for authorization, destinations, and help
  - Cover public, privileged, multi-privilege, ADMIN bypass, unauthorized, unknown, and destination-restricted commands using test-only registered commands.
  - Cover help filtering by privileges and current destination.
  - Cover `!help --all`, `!help --help`, and `!<command> --help`.
  - Cover parser edge cases and handler no-response under the tuple response contract.
  - Completed state: command service tests prove every command-level requirement without adding product-visible admin commands.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 2.3, 2.4, 2.6, 2.7, 2.8, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 5.3, 5.4, 5.5, 5.6, 6.1, 6.2, 6.3_

- [x] 5.2 Add chat service and transport integration coverage
  - Verify channel and PM authorization propagation from session snapshot into command execution.
  - Verify normal chat rejection prevents command execution.
  - Verify transport enqueues multiple command responses with BanchoBot identity and correct recipient visibility.
  - Verify existing `!roll`, `!help`, and unknown command flows remain compatible at integration level.
  - Completed state: chat service and Bancho handler tests pass for both single-response and multi-response command outcomes.
  - _Requirements: 2.1, 2.2, 2.5, 2.6, 2.7, 2.9, 5.1, 5.2_

- [x] 5.3 Run focused quality checks for the feature
  - Run the BanchoBot command service test module.
  - Run affected chat service and Bancho handler tests.
  - Run affected integration or E2E chat tests that cover `!help`, `!roll`, and unknown command behavior.
  - Run type and lint checks required for touched files.
  - Completed state: focused tests, type checks, and lint checks pass or any remaining failures are documented as unrelated.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 6.1, 6.2, 6.3_
