# Brief: bancho-protocol

## Problem
stable クライアントとの通信にはバイナリプロトコルの実装が必要。パケット定義・シリアライゼーション・ディスパッチ機構がないとハンドラを書けない。

## Current State
foundation spec でプロジェクト骨格は整っているが、bancho プロトコル関連のコードは未実装。

## Desired Outcome
- Caterpillar でパケットヘッダ（PacketID u16 + Compression bool + ContentSize u32）が定義されている
- ClientPacketID / ServerPacketID が別 enum として定義されている
- 基本型（BanchoString, BanchoInt 等）が Caterpillar struct で定義されている
- C2S パケットの読み取り（parse）と S2C パケットの構築（build）ができる
- デコレータ駆動のディスパッチ機構でハンドラ登録・呼び出しができる
- ログインに必要な S2C パケット型（UserID, ProtocolVersion, Notification 等）が定義されている

## Approach
設計書 Section 5-6 + bancho-documentation Wiki に従い、Caterpillar DSL でパケット構造を宣言的に定義。ディスパッチはデコレータ登録 + 自動 import パターン。

## Scope
- **In**: パケットヘッダ定義、C2S/S2C enum、基本型 (BanchoString, Message 等)、パケット読み書きユーティリティ、ディスパッチ機構（デコレータ + レジストリ）、ログイン関連 S2C パケット定義
- **Out**: 個別ハンドラの実装（login handler 以外）、チャット・スコア・マルチプレイ関連パケット

## Boundary Candidates
- パケット定義ファイルの粒度（1ファイル1パケット vs 機能グループ）
- ディスパッチ機構と DI コンテナの接続方法

## Out of Boundary
- ログインビジネスロジック（bancho-login spec が担当）
- チャット / スコア / マルチプレイのパケット定義（後続 spec）

## Upstream / Downstream
- **Upstream**: foundation (DI, config, app 骨格)
- **Downstream**: bancho-login, 以降全ての bancho transport 関連 spec

## Existing Spec Touchpoints
- **Extends**: なし
- **Adjacent**: foundation (DI コンテナへのディスパッチャ登録)

## Constraints
- Caterpillar ライブラリ（Python 3.12+ 必須、3.14 で動作確認要）
- パケット仕様は bancho-documentation Wiki 準拠
- C2S / S2C は別名前空間（enum 分離）
