# Task Brief

You are implementing a specific task within a feature specification.

## Core Directives
1. **Test-Driven Development**: You MUST write failing tests (RED) before writing the implementation (GREEN).
2. **Feature Flag Protocol**: If this task changes or adds behavior, you MUST use a feature flag. Write the test (fails with flag OFF), implement with flag ON (test passes), then remove the flag (test still passes).
3. **Spec Alignment**: Follow the requirements and design explicitly. Do not invent new requirements or deviate from the design.
4. **Task Boundaries**: Respect the `_Boundary:_` constraints. Do not refactor unrelated code or implement parts of other tasks.
5. **No Spec Changes**: You are not authorized to modify `requirements.md` or `design.md`.

## Task Details
Task: {task_description}
Scope/Boundary: {boundary_scope}

## Context Files
- Requirements: {requirements_path} (Pay special attention to: {requirement_refs})
- Design: {design_path} (Pay special attention to: {design_refs})
- Tasks: {tasks_path}
- Task-relevant notes: {previous_learnings}

## Validation Commands
Tests: {test_commands}
Build: {build_commands}
Smoke: {smoke_commands}

## Instructions

1. **Read the Specs**: Briefly review the specific requirement and design sections referenced above to understand the acceptance criteria, completion definition, and design constraints.
2. **Write Tests (RED)**: Write the necessary unit/integration tests to verify the acceptance criteria. Ensure they fail.
3. **Implement (GREEN)**: Implement the simplest code to make the tests pass, adhering to the design constraints and boundary.
4. **Refactor & Verify**: Clean up the code. Run the validation commands. Ensure everything passes without regressions.
5. **Report Status**: You MUST output EXACTLY this format at the end of your response:

## Status Report
- STATUS: READY_FOR_REVIEW | BLOCKED | NEEDS_CONTEXT
- FILES_CHANGED: (list files you modified)
- BLOCKER_REASON: (only if BLOCKED)
- MISSING_CONTEXT: (only if NEEDS_CONTEXT)
