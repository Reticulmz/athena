## E2E Verification with Playwright

### Post-Implementation Verification
After implementing UI-facing features, bug fixes, or view changes, use Playwright MCP tools to verify the result in a real browser **if Playwright MCP is available**:

1. **Navigate** to the relevant page and take a screenshot to confirm rendering.
2. **Interact** with the implemented feature (click, fill forms, submit) to verify behavior.
3. **Check console messages** for JavaScript errors or warnings.
4. **Debug visually** — if the screenshot reveals layout issues, missing elements, or incorrect content, fix immediately before reporting completion.

### When to Run E2E Verification
- New or modified views, partials, and ViewComponents.
- Stimulus controller changes or Turbo Frame/Stream updates.
- CSS/Tailwind styling changes that affect layout or responsiveness.
- Form submission flows and validation feedback.
- Search, filter, and pagination interactions.

### When E2E Verification Is Not Required
- Backend-only changes (models, services, migrations) with no view impact.
- RSpec-only changes or factory updates.
- Documentation, configuration, or CI pipeline changes.

### Workflow
- Start the dev server (`devenv up`) if not already running.
- Use `browser_navigate` to load the target page.
- Use `browser_take_screenshot` to capture the current state.
- Use `browser_click`, `browser_fill_form`, `browser_press_key`, etc. to interact.
- Use `browser_console_messages` to check for client-side errors.
- If issues are found, fix them and re-verify until the feature works correctly.
