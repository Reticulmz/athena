# ADR 0002: Adopt Dishka for Composition DI

## Status
Accepted (2026-06-13)

## Context
Athena の app process と worker process は、現在の自前軽量 DI コンテナと手動 composition により `service_registry` と worker runtime の依存解決コードが肥大化しています。Athena は service class を DI ライブラリ非依存に保ちつつ、型ヒント中心で app/worker の構成を明示的に整理したいため、DI フレームワークとして Dishka を採用します。Starlette integration は Dishka 公式 documentation で分離先として案内されている `starlette-dishka` を使い、taskiq integration は `dishka.integrations.taskiq` を使います。

## Alternatives Considered

- `dependency-injector`: 成熟しているが、`providers.*` と `Provide[...]` を中心にした DSL 色が強く、Athena の型ヒント中心・constructor injection 優先の方針に合いにくいため不採用。
- Lagom: 型ベースの自動解決が簡潔だが、暗黙的な wiring が増えると composition root の可読性を下げる懸念があるため不採用。
- 自前軽量コンテナ継続: 現状の肥大化と app/worker composition の重複を根本的に解消しにくいため不採用。
