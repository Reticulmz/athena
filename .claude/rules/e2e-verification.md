## E2E Verification with Playwright

### Post-Implementation Verification
After implementing UI-facing features, bug fixes, or view changes, use Playwright MCP tools to verify the result in a real browser **if Playwright MCP is available**:

1. **Navigate** to the relevant page and take a screenshot to confirm rendering.
2. **Interact** with the implemented feature (click, fill forms, submit) to verify behavior.
3. **Check console messages** for JavaScript errors or warnings.
4. **Debug visually** — if the screenshot reveals layout issues, missing elements, or incorrect content, fix immediately before reporting completion.

### When to Run E2E Verification
- WebUI (別リポジトリ) のフロントエンド変更時。
- API レスポンス形式の変更がフロントエンドに影響する場合。

### When E2E Verification Is Not Required
- バックエンド専用の変更 (ドメインモデル, サービス, リポジトリ, マイグレーション)。
- bancho バイナリプロトコルのハンドラ変更 (pytest で検証)。
- テストコードのみの変更。
- ドキュメント、設定、CI パイプラインの変更。

### Workflow
- 開発サーバーを起動 (`devenv up`) していない場合は起動する。
- Use `browser_navigate` to load the target page.
- Use `browser_take_screenshot` to capture the current state.
- Use `browser_click`, `browser_fill_form`, `browser_press_key`, etc. to interact.
- Use `browser_console_messages` to check for client-side errors.
- If issues are found, fix them and re-verify until the feature works correctly.

### Note
athena は現時点ではバックエンドサーバーのみ (WebUI は別リポジトリの予定)。
Playwright E2E は将来の WebUI 開発時に本格活用する。現在の E2E テストは
pytest + TestClient (HTTP POST → S2C レスポンスバイト列検証) で行う。
