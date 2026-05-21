# Roadmap

## Overview
osu! bancho 互換プライベートサーバー (athena) の段階的実装。まず stable クライアントがログインしてセッション確立できる PoC を最短で動かすことを目標とし、3 spec に分解して進める。

## Approach Decision
- **Chosen**: 設計書 (`bancho_server_design.md`) に従ったモジュラモノリス構成
- **Why**: 設計書で技術スタック・レイヤー構造・プロトコル仕様が詳細に定義済み。Phase 1-2 相当を PoC スコープとして切り出す
- **Rejected alternatives**: なし（設計書の方針をそのまま採用）

## Scope
- **In**: stable クライアントのログイン → セッション確立 → 基本応答パケット返却までの end-to-end フロー
- **Out**: チャット、スコア送信、マルチプレイ、spectator、lazer 対応、web_legacy、REST API v2、SignalR、worker プロセス

## Constraints
- Python 3.14+、uv パッケージマネージャー
- devenv (Nix) ベースの開発環境（設定済み）
- Redis + PostgreSQL（devenv で起動）
- Caterpillar でバイナリプロトコル定義
- import-linter でレイヤー依存違反を検出

## Boundary Strategy
- **Why this split**: foundation はフレームワーク非依存の基盤、bancho-protocol はワイヤフォーマット定義、bancho-login はビジネスロジック。各 spec が独立してテスト可能
- **Shared seams to watch**: DI コンテナ経由のサービス注入、StateStore Protocol の interface 定義

## Specs (dependency order)
- [ ] foundation -- プロジェクト骨格・DI・config・インフラ抽象・DB基盤・Starlette ルートアプリ。Dependencies: none
- [ ] bancho-protocol -- Caterpillar パケット定義・C2S/S2C enum・基本型・ディスパッチ機構。Dependencies: foundation
- [ ] bancho-login -- stable ログインフロー・AuthService・SessionStore・ログイン応答パケット。Dependencies: foundation, bancho-protocol
- [ ] ci-cd -- GitHub Actions CI/CD（lint, type check, import rules, tests）。Dependencies: foundation
