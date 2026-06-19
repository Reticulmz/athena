# Requirements Document

## Introduction

Release/update route policy inventory audit は、Athena の stable compatibility docs に残っている release/update 系 route の Missing / Candidate 状態を、明示的な互換分類、運用依存、evidence、fixture 引き渡しへ変換するための監査である。この監査は Athena の初期 no-update / no-op 方針を matrix 上で検証可能にしつつ、外部 proxying や hosted artifact storage を実装既定値ではなく別の運用判断として分離する。

## Boundary Context

- **In scope**: `/web/check-updates.php`、`/release/update*`、`/release/patches.php`、root `/update*` / `/patches.php` aliases、release file、filter、Localisation route の互換分類、response shape、evidence source、運用依存、fixture 要否の整理。
- **Out of scope**: release/update route の実装、ppy への proxy 実装、release artifact hosting、artifact storage 設計、fixture ファイル作成そのもの。
- **Adjacent expectations**: #17 はこの監査が指定する fixture identifier を受け取り、stable compatibility docs は監査結果と evidence source を保持する。Proxying または artifact hosting が必要な場合は、別の運用判断または後続 spec で扱う。

## Requirements

### Requirement 1: `/web/check-updates.php` no-update policy

**Objective:** As an Athena maintainer, I want `/web/check-updates.php` の no-update 方針を明示的に分類したい, so that stable update check behavior can be audited without enabling updater proxying by default.

#### Acceptance Criteria

1. When `/web/check-updates.php` の監査行を分類する, the Athena stable compatibility audit shall classify the route as `required-no-update`.
2. When `/web/check-updates.php` の response shape を記録する, the Athena stable compatibility audit shall record `[]` as the chosen no-update response.
3. When `/web/check-updates.php` の evidence source を記録する, the Athena stable compatibility audit shall include the documented `deck` response, the documented `bancho.py` empty-body comparison, and the user-confirmed current osu!stable `--devserver` behavior.
4. If `/web/check-updates.php` proxying to `osu.ppy.sh` is considered, then the Athena stable compatibility audit shall mark it as `proxy-decision-required` rather than an implementation default.
5. When `/web/check-updates.php` fixture handoff is recorded, the Athena stable compatibility audit shall reference fixture identifier `check_updates_no_update_json_array`.

### Requirement 2: Release manifest and root alias no-update policy

**Objective:** As an Athena maintainer, I want release manifest routes and root aliases to share explicit no-update contracts, so that missing updater support does not leave ambiguous stable compatibility rows.

#### Acceptance Criteria

1. When `/release/update` と `/update` の監査行を分類する, the Athena stable compatibility audit shall classify both routes as `required-no-update` with an empty-body response shape.
2. When `/release/update.php` と `/update.php` の監査行を分類する, the Athena stable compatibility audit shall classify both routes as `required-no-update` with response shape `0`.
3. When `/release/update2.php` と `/update2.php` の監査行を分類する, the Athena stable compatibility audit shall classify both routes as `required-no-update` with an empty-body response shape.
4. When `/release/patches.php` と `/patches.php` の監査行を分類する, the Athena stable compatibility audit shall classify both routes as `required-no-update` with an empty-body response shape.
5. When release manifest no-update rows are recorded, the Athena stable compatibility audit shall mark their operational dependency as `none`.
6. If hosted update metadata or release artifact distribution is proposed for these manifest routes, then the Athena stable compatibility audit shall identify that behavior as outside the initial no-update policy.

### Requirement 3: Release file, filter, and Localisation operational dependency policy

**Objective:** As an Athena operator, I want file-like release routes separated from no-update manifest routes, so that proxying and hosted artifact storage require explicit operational decisions.

#### Acceptance Criteria

1. When `/release/<filename>` の監査行を分類する, the Athena stable compatibility audit shall classify the route as `deferred` with operational dependency `hosted-artifact-decision-required`.
2. When `/release/filter.txt` の監査行を分類する, the Athena stable compatibility audit shall classify the route as `deferred` with operational dependency `proxy-decision-required`.
3. When `/release/Localisation/<filename>` の監査行を分類する, the Athena stable compatibility audit shall classify the route as `deferred` with operational dependency `proxy-decision-required`.
4. When `/release/<language>/<filename>` の監査行を分類する, the Athena stable compatibility audit shall classify the route as `deferred` with operational dependency `hosted-artifact-decision-required`.
5. If a release/update route serves file bytes or proxies external release resources, then the Athena stable compatibility audit shall not classify it as `required-no-update`.
6. Where a file-like release route is deferred, the Athena stable compatibility audit shall state that the route is not an initial implementation default.

### Requirement 4: Matrix evidence and fixture handoff

**Objective:** As an Athena maintainer, I want each audited matrix row to expose classification, operational dependency, and fixture handoff, so that #17 can create fixtures without re-deciding release/update policy.

#### Acceptance Criteria

1. When a release/update matrix row is updated, the Athena stable compatibility audit shall record stable compatibility route classification, stable operational dependency, evidence source, and stable fixture requirement.
2. When multiple routes share the same no-update response shape, the Athena stable compatibility audit shall reference a shared fixture identifier instead of requiring duplicate route-specific fixtures.
3. When `/web/check-updates.php` fixture handoff is recorded, the Athena stable compatibility audit shall reference `check_updates_no_update_json_array`.
4. When release manifest fixture handoff is recorded, the Athena stable compatibility audit shall reference `release_update_empty`, `release_update_php_zero`, `release_update2_empty`, or `release_patches_empty` according to the response shape.
5. Where a release file, filter, or Localisation route is deferred behind an operational decision, the Athena stable compatibility audit shall mark fixture requirement as `deferred`.
6. If evidence is insufficient to choose a stable compatibility route classification, then the Athena stable compatibility audit shall mark the row as `needs-reference` instead of inventing a response contract.
