# Requirements Document

## Project Description (Input)
basedpyright strict モード（typeCheckingMode = "all"）と type-safety-policy.md のルール厳格化により、テストコードに型エラーが発生している。主な違反パターンは: (1) AsyncMock の Any 漏れ（InMemory 実装が存在するにもかかわらず AsyncMock を使用）、(2) method-assign モンキーパッチによる型破壊、(3) Protocol パラメータ名の不一致、(4) テストヘルパーの kwargs 型不一致。これらを type-safety-policy.md に従って構造的に修正し、pre-commit フック（basedpyright src/ tests/）を全テストファイルでエラーゼロにする。

## Requirements
<!-- Will be generated in /kiro-spec-requirements phase -->

