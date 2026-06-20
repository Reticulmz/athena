# 調査メモ

## 概要

- **機能**: `legacy-web-endpoint-inventory-audit`
- **調査範囲**: Extension
- **主な調査結果**:
  - Athena の runtime 実装済み legacy web routes は `/web/bancho_connect.php`、`/web/osu-osz2-getscores.php`、`/web/osu-submit-modular-selector.php`、registration fallback に限られる。
  - `docs/stable-compatibility-matrix.md` は stable compatibility inventory の source of truth として定義済みで、Reference Route Inventory には exact path audit 用の route rows がある。
  - `docs/stable-compatibility-guide.md` には legacy web endpoint family ごとの request / response shape が一部存在するが、auth failure、not-found、malformed request、old alias response variants は未確認が残る。

## 調査ログ

### 既存 Athena route surface

- **文脈**: Design は route 実装ではなく、現状 route coverage と docs inventory の差分を監査可能にする必要がある。
- **参照した情報源**:
  - `src/osu_server/composition/application.py`
  - `src/osu_server/transports/stable/web_legacy/*`
  - `tests/unit/transports/web_legacy/*`
  - `tests/integration/test_getscores_endpoint.py`
- **調査結果**:
  - `osu.$DOMAIN` の web legacy routes は Starlette `Router` で登録される。
  - 現在登録済みの stable web legacy routes は registration、bancho connect、modern getscores、modern score submit に集中している。
  - 多くの matrix candidate rows は runtime 実装ではなく reference inventory 由来である。
- **含意**:
  - Design は route 実装計画を追加せず、docs 上で implemented / partial / missing / candidate と監査分類を分離する。
  - フォローアップチェックリストは missing implementation と missing evidence を区別する必要がある。

### 互換性ドキュメントサーフェス

- **文脈**: Issue #32 の成果は existing docs から読める必要がある。
- **参照した情報源**:
  - `docs/stable-compatibility-matrix.md`
  - `docs/stable-compatibility-guide.md`
  - `CONTEXT.md`
- **調査結果**:
  - Matrix は stable compatibility の canonical inventory として定義済みで、source-of-truth policy と reference implementation map を持つ。
  - Matrix の Stable HTTP Endpoint Coverage は grouped route rows を持つ。
  - Matrix の Reference Route Inventory は exact path rows を持つ。
  - Guide は `/web/bancho_connect.php`、`/web/osu-osz2-getscores.php`、score submit、ratings/comments/favourites/status などの detailed shapes を持つ。
  - `CONTEXT.md` には `Legacy Web Endpoint Inventory Classification` と関連用語が追加済みである。
- **含意**:
  - Matrix は分類と進捗の source of truth とする。
  - Guide は endpoint family 別 evidence note と unresolved evidence gaps の置き場とする。
  - CONTEXT の用語を design と docs 更新で一貫して使う。

### スコープと境界の確認

- **文脈**: `$grill-with-docs` session で Issue #32 の boundary を決めた。
- **参照した情報源**:
  - User decisions in the current session
  - `.kiro/specs/legacy-web-endpoint-inventory-audit/requirements.md`
  - `CONTEXT.md`
- **調査結果**:
  - 現行 osu!stable client が primary target で、古い stable client alias は best effort support 候補である。
  - `/web/osu-getseasonal.php` は現行 client 呼び出し確認済みだが、exact empty-array body と cache contract が fixture-backed になるまでは `needs reference evidence` として扱う。
  - Beatmap submission endpoints は将来 support 予定だが、P0 core login/play 後なので `deferred` で扱う。
  - coins / benchmark は通常プレイ evidence がなければ `out of scope` に寄せる。
- **含意**:
  - Design は future support と initial behavior の note を許容しつつ、単一軸の classification を維持する。
  - Endpoint aliases は response variants が特定されるまで required として扱わない。

## アーキテクチャパターン評価

| 選択肢 | 説明 | 強み | リスク / 制約 | 備考 |
|--------|-------------|-----------|---------------------|-------|
| Matrix-only audit | すべての classification、evidence、follow-up notes を `docs/stable-compatibility-matrix.md` に置く | single source として読みやすい | matrix が広くなりすぎ、保守しづらい | 不採用 |
| Guide-only audit | すべての details を `docs/stable-compatibility-guide.md` に置き、matrix は軽量に保つ | endpoint family context を詳細に残せる | issue / project progress の canonical row state が失われる | 不採用 |
| Split source of truth | Matrix が classification と exact path traceability を扱い、guide が detailed evidence gaps を扱う | progress と evidence の両方を読みやすく保てる | cross-reference discipline が必要 | 採用 |

## 設計判断

### 判断: Matrix が分類を扱い、Guide が evidence detail を扱う

- **文脈**: Requirements は source-of-truth tracking と detailed request / response evidence の両方を要求する。
- **検討した代替案**:
  1. すべての detail を matrix rows に保存する。
  2. すべての classification を guide sections に保存する。
  3. classification と detail を matrix / guide に分ける。
- **採用案**: Matrix は classification、exact path traceability、concise evidence status を記録する。Guide は endpoint family evidence notes と unresolved gaps を記録する。
- **根拠**: Matrix は GitHub issue/project tracking に使いやすく保ち、guide は detailed compatibility notes に適したままにできる。
- **トレードオフ**: evidence gaps を持つ endpoint families では implementers が2つの docs を更新する必要がある。
- **フォローアップ**: Task generation は endpoint family ごとに matrix と guide の更新をまとめる。

### 判断: Documentation-only design

- **文脈**: Requirements は route implementation、fixture creation、traffic capture を明示的に除外する。
- **検討した代替案**:
  1. compatibility no-op endpoints の route stubs を含める。
  2. この spec 内に fixture extraction tasks を作る。
  3. この spec を docs inventory と follow-up checklist creation に限定する。
- **採用案**: この spec では runtime source files を変更しない。
- **根拠**: Issue #32 は audit task であり、classification 前の implementation は guessed compatibility を再導入する。
- **トレードオフ**: client-visible な missing routes の一部は follow-up tasks まで missing のまま残る。
- **フォローアップ**: 後続の implementation issues は classification と evidence checklist を入力として使う。

### 判断: Exact path rows は grouped families の下で追跡可能に保つ

- **文脈**: 一部の grouped rows は response variants が異なる aliases を表す。
- **検討した代替案**:
  1. grouped Stable HTTP Endpoint Coverage rows だけを分類する。
  2. Reference Route Inventory に per-exact-path classification を追加する。
- **採用案**: Grouped rows は family state を要約し、exact path rows は route-specific classification または evidence notes を保持する。
- **根拠**: Old getscores と submit aliases は modern formatter behavior を安全に継承できない。
- **トレードオフ**: Reference Route Inventory の metadata が増える。
- **フォローアップ**: matrix row width が扱いづらくなった場合、detailed exact path notes を同じ section の近くの table に分ける。

## リスクと緩和策

- リスク: `required` と `compatibility no-op` はどちらも client-visible になりうるため混同される。緩和策: `required` は real behavior のみに使い、`compatibility no-op` は confirmed static / empty / sentinel responses のみに使う。
- リスク: old alias rows が modern formatter behavior で誤実装される。緩和策: 各 response variant が特定されるまで old alias rows を `needs reference evidence` に残す。
- リスク: matrix と guide が drift する。緩和策: grouped matrix rows、exact path rows、guide evidence gaps が同じ endpoint family を相互参照することを design で要求する。
- リスク: audit scope が route implementation に拡大する。緩和策: runtime source files を modified file plan から外し、missing implementation は follow-up としてのみ記録する。

## 参照

- `docs/stable-compatibility-matrix.md`: stable compatibility inventory と reference route list。
- `docs/stable-compatibility-guide.md`: legacy web endpoint family request / response notes。
- `CONTEXT.md`: stable compatibility glossary と legacy web classification vocabulary。
- `src/osu_server/composition/application.py`: current Starlette route registration surface。
- `.kiro/specs/legacy-web-endpoint-inventory-audit/requirements.md`: audit requirements と boundary context。
