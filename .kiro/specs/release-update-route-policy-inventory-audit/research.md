# Research & Design Decisions

## Summary

- **Feature**: `release-update-route-policy-inventory-audit`
- **Discovery Scope**: Stable release/update compatibility inventory audit; light discovery for an existing documentation extension
- **Key Findings**:
  - `/web/check-updates.php` は Athena の初期実装では no-update response を返す方針にする。
  - 現行 osu!stable の `--devserver` 利用時は update check が `osu.ppy.sh` へ問い合わせに行く挙動が手元の fixture 観測で確認されたため、Athena 側で hosted updater を既定実装にしなくても stable client 運用上は問題にならない可能性がある（issue #34 spec discussion, 2026-06-20 JST）。
  - 外部 proxying と hosted artifact storage は route 互換分類とは分け、運用判断が必要な依存として扱う。
  - Existing inventory audit specs use a matrix-first documentation design with explicit boundary, file structure, traceability, and documentation-component contracts; this release/update audit follows the same pattern.

## Research Log

### Existing documentation integration points

- **Context**: Design generation requires concrete files and boundaries before task generation.
- **Sources Consulted**:
  - `docs/stable-compatibility-guide.md` Update And Release Endpoints
  - `docs/stable-compatibility-matrix.md` Stable HTTP Endpoint Coverage
  - `CONTEXT.md` stable compatibility glossary area
  - Existing `bancho-packet-struct-inventory-audit` design structure
- **Findings**:
  - `docs/stable-compatibility-matrix.md` is the row-level inventory and should remain the primary audit output.
  - `docs/stable-compatibility-guide.md` contains response shape evidence but should not become a duplicated row inventory.
  - `CONTEXT.md` should contain only durable glossary terms, not route-specific response shapes.
  - Existing inventory audit design treats docs changes as documentation components with explicit contracts and traceability.
- **Implications**:
  - Use a matrix-first documentation audit pattern.
  - Keep runtime implementation, proxying, hosting, and fixture file creation out of boundary.
  - Include `CONTEXT.md`, matrix docs, guide docs, and spec docs in the File Structure Plan.

### `/web/check-updates.php` の no-update response

- **Context**: Issue #34 acceptance criteria requires `/web/check-updates.php` classification with a chosen no-update response shape and evidence source.
- **Sources Consulted**:
  - `docs/stable-compatibility-guide.md` Update And Release Endpoints
  - `docs/stable-compatibility-matrix.md` Stable HTTP Endpoint Coverage
  - User-confirmed current osu!stable `--devserver` behavior
- **Findings**:
  - `docs/stable-compatibility-guide.md` records `deck` returning `[]` and `bancho.py` returning an empty body for `/web/check-updates.php`.
  - A local fixture observation of current osu!stable behavior indicates that `--devserver` may still send update checks to `osu.ppy.sh`, so Athena may not need to own this endpoint for normal private server operation. Evidence attribution: issue #34 spec discussion, 2026-06-20 JST.
  - Even if the client often bypasses Athena, returning `[]` is still the clearer no-update response when Athena receives the route because it is distinguishable from an accidental empty body.
- **Implications**:
  - Classify `/web/check-updates.php` as `required-no-update` with response shape `[]`.
  - Record the initial no-update row as `Stable Operational Dependency = none`; proxying to `osu.ppy.sh` remains a future `proxy-decision-required` decision, not the implementation default.
  - Mark a fixture for the `[]` response as required unless later traffic evidence proves the route is never Athena-observable for the supported stable client range.

## Design Decisions

### Decision: Use matrix-first documentation audit pattern

- **Context**: This spec classifies compatibility rows and fixture handoff; it does not implement runtime routes.
- **Alternatives Considered**:
  1. Create a standalone release/update audit document.
  2. Update the existing stable compatibility matrix with row-level axes and keep detailed rationale in `research.md`.
- **Selected Approach**: Update the existing matrix and keep `research.md` as the rationale log.
- **Rationale**: The matrix is already the stable compatibility inventory source of truth. A standalone document would create a second source of truth and make #17 handoff harder to discover.
- **Trade-offs**: Matrix rows may need compact structured notes to avoid wide tables, but the audit remains visible where implementers already look.
- **Follow-up**: Implementation tasks should avoid adding new docs unless the existing matrix layout cannot represent the required axes.

### Decision: Separate route classification from operational dependency

- **Context**: Release/update route families include plain no-update endpoints, ppy proxy candidates, and hosted release artifact candidates.
- **Alternatives Considered**:
  1. Put `proxy-required` and `hosted-required` directly in the route classification.
  2. Keep route compatibility classification, operational dependency, and fixture requirement as separate axes.
- **Selected Approach**: Use separate axes.
- **Rationale**: Route compatibility answers what the stable client contract needs. Operational dependency answers whether Athena must make a deployment/storage/proxy decision beyond the default server implementation. Mixing them would make proxying or hosting look like the default implementation path.
- **Trade-offs**: The matrix gains more columns, but each row becomes less ambiguous.
- **Follow-up**: Requirements generation should define allowed values for `Stable Compatibility Route Classification`, `Stable Operational Dependency`, and `Stable Fixture Requirement`.

### Decision: Treat release manifest routes and root aliases as required no-update routes

- **Context**: Issue #34 requires `/release/update*`, `/release/patches.php`, root `/update*`, and root `/patches.php` aliases to be classified.
- **Alternatives Considered**:
  1. Classify only `/release/*` routes as no-update and leave root aliases as `needs-reference`.
  2. Classify both `/release/*` routes and root aliases as `required-no-update` with matching no-update response shapes.
- **Selected Approach**: Classify both `/release/*` routes and root aliases as `required-no-update`.
- **Rationale**: Even when Athena does not distribute update artifacts, these routes can return stable-compatible no-update responses without proxying or hosted storage. Root aliases should share the same contract as their `/release/*` counterparts to avoid ambiguous matrix rows.
- **Selected Response Shapes**:
  - `/release/update`: empty body
  - `/release/update.php`: `0`
  - `/release/update2.php`: empty body
  - `/release/patches.php`: empty body
  - `/update`, `/update.php`, `/update2.php`, `/patches.php`: same no-update response as the corresponding `/release/*` route
- **Trade-offs**: This may classify aliases as implementation-relevant before target-client traffic proves direct usage, but the response is intentionally inert and keeps private-server behavior stable.
- **Follow-up**: Matrix rows should identify which response bytes need fixtures in #17.

### Decision: Defer release file, filter, and Localisation routes behind operational decisions

- **Context**: Issue #34 requires release file, Localisation, filter, patch, and extra-file routes to be marked no-op, deferred, proxy-required, hosted-required, or out of scope.
- **Alternatives Considered**:
  1. Treat all release file-like routes as compatibility no-op.
  2. Defer file-like routes and record whether they require proxying or hosted artifact storage.
- **Selected Approach**: Defer file-like routes and capture operational dependency separately.
- **Rationale**: These routes are not simple no-update manifests. They either serve bytes or proxy external release resources, so implementing them changes operational responsibilities beyond the default Athena server.
- **Selected Classification**:
  - `/release/<filename>`: `deferred`, `hosted-artifact-decision-required`
  - `/release/filter.txt`: `deferred`, `proxy-decision-required`
  - `/release/Localisation/<filename>`: `deferred`, `proxy-decision-required`
  - `/release/<language>/<filename>`: `deferred`, `hosted-artifact-decision-required`
- **Trade-offs**: Deferred rows may leave some old updater flows unsupported until an operational decision is made, but this avoids silently adding external network or artifact hosting behavior.
- **Follow-up**: Matrix rows should make clear that these are not implementation defaults for the initial no-update policy.

### Decision: Group fixtures by response bytes

- **Context**: Issue #34 requires matrix rows to identify which update/release responses need fixtures in #17.
- **Alternatives Considered**:
  1. Require one fixture per route.
  2. Require one fixture per distinct response byte contract and let each matrix row reference the shared fixture.
- **Selected Approach**: Group fixtures by response bytes.
- **Rationale**: Root aliases intentionally share the same no-update contract as their `/release/*` counterparts, and empty-body manifest routes do not need duplicate fixture bytes. Per-route fixture duplication would increase maintenance without adding new evidence.
- **Selected Fixture Set**:
  - `check_updates_no_update_json_array`: `/web/check-updates.php` -> `[]`
  - `release_no_update_empty`: `/release/update`, `/update`, `/release/update2.php`, `/update2.php`, `/release/patches.php`, and `/patches.php` -> empty body
  - `release_update_php_zero`: `/release/update.php` and `/update.php` -> `0`
- **Trade-offs**: Shared fixtures require matrix rows to reference fixture identifiers clearly, but they avoid redundant fixture files.
- **Follow-up**: Deferred file/proxy routes should mark fixture requirement as `deferred` until a separate operational implementation decision exists.

### Decision: Do not introduce runtime or fixture-generation components

- **Context**: Design synthesis requires checking whether additional components or abstractions are necessary.
- **Alternatives Considered**:
  1. Add a lightweight audit helper script or fixture manifest file.
  2. Keep the design documentation-only and use targeted review checks.
- **Selected Approach**: Keep the design documentation-only.
- **Rationale**: The current requirements ask for classification and handoff, not automated route probing or fixture extraction. A script or new manifest would add an extra artifact before matrix needs prove it.
- **Trade-offs**: Reviewers must inspect Markdown output directly, but the scope remains small and avoids speculative tooling.
- **Follow-up**: If #17 needs machine-readable fixture input, create that in #17 rather than this audit spec.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Matrix-first documentation audit | Update `docs/stable-compatibility-matrix.md` with row axes and fixture identifiers | Keeps one inventory source of truth; aligns with existing audit specs | May require careful Markdown layout | Selected |
| Standalone audit document | Create a separate release/update inventory file | Easy to format independently | Splits source of truth from existing matrix | Rejected |
| Runtime probe first | Capture client traffic or execute route probes before classification | Strong empirical evidence | Out of scope and delays policy classification | Rejected for this spec |
| Machine-readable fixture manifest | Add a YAML/JSON manifest for #17 | Easier automation | Premature until #17 defines exact consumer format | Deferred |

## Risks & Mitigations

- Matrix table width becomes unreadable — use structured row notes while preserving the same fields.
- User-confirmed `--devserver` behavior is not yet a captured fixture — record it as evidence and keep fixture requirement for `[]` response.
- Deferred routes are misread as forgotten work — require explicit `deferred` classification and operational dependency value.
- Proxying or hosting is treated as approved by classification — separate operational dependency from route compatibility.

## References

- `docs/stable-compatibility-guide.md` — Update And Release Endpoints
- `docs/stable-compatibility-matrix.md` — Stable HTTP Endpoint Coverage and Release/update files rows
