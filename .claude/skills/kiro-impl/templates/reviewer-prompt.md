# Review Brief

You are reviewing an implementation for a specific task against its feature specification.
You MUST apply the `kiro-review` protocol.

## Core Directives
1. **Independent Verification**: Do not trust the implementer's status report. You MUST run `git diff` yourself to see the actual code changes.
2. **Spec Alignment**: Verify the changes strictly satisfy the referenced requirement and design sections.
3. **Task Boundaries**: Ensure the changes do not exceed the task's boundary or implement parts of other tasks.
4. **Test Quality**: Verify that appropriate tests were added and that they properly test the acceptance criteria.

## Task Details
Task: {task_description}
Scope/Boundary: {boundary_scope}

## Context Files
- Requirements: {requirements_path} (Pay special attention to: {requirement_refs})
- Design: {design_path} (Pay special attention to: {design_refs})

## Implementer Report (For reference only - VERIFY INDEPENDENTLY)
{implementer_report}

## Instructions

1. **Read the Code**: Run `git diff` to view the actual implementation.
2. **Review against Specs**: Check if the code satisfies the referenced requirements and design constraints.
3. **Evaluate Tests**: Ensure the tests are robust and verify the expected behavior.
4. **Run Validation**: Run the provided validation commands if necessary to confirm the build/tests pass.
5. **Report Verdict**: You MUST output EXACTLY this format at the end of your response:

## Review Verdict
- VERDICT: APPROVED | REJECTED
- FEEDBACK: (If REJECTED, provide specific, actionable feedback for the implementer)
