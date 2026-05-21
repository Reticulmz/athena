# Implementation Plan

- [ ] 1. caterpillar-py 依存追加とプロトコル基盤セットアップ
- [x] 1.1 caterpillar-py を依存に追加しパッケージ構造とエラー階層を準備する
  - caterpillar-py をプロジェクト依存に追加し依存解決が成功すること
  - bancho トランスポートのパッケージ構造（protocol, dispatch, handlers）を作成する
  - テストディレクトリ構造を作成する
  - プロトコル例外階層（PacketError, PacketReadError, DuplicateHandlerError）を定義する
  - caterpillar のインポートと例外クラスのインポートが成功すること
  - _Requirements: 1.1, 4.4, 4.5, 5.5_

- [ ] 2. コアデータ定義
- [x] 2.1 (P) C2S / S2C パケット ID 列挙型を定義する
  - ClientPacketID を整数列挙型として定義し、bancho-documentation Wiki 準拠の C2S 全 41 エントリを含める
  - ServerPacketID を整数列挙型として定義し、S2C 全 62 エントリを含める
  - 2 つの列挙型が独立しており同一数値 ID が方向別に共存できること
  - 全メンバーの値と名前を検証するテストが通ること
  - _Requirements: 2.1, 2.2, 2.3, 2.4_
  - _Boundary: ClientPacketID, ServerPacketID_

- [x] 2.2 (P) パケットヘッダを Caterpillar struct として定義する
  - PacketID (unsigned 16-bit)、Compression (boolean)、ContentSize (unsigned 32-bit) の 3 フィールドをリトルエンディアンで定義する
  - ヘッダサイズ定数（7 バイト）を定義する
  - pack/unpack ラウンドトリップテストと既知バイト列との照合テストが通ること
  - _Requirements: 1.1, 1.2, 1.3, 1.4_
  - _Boundary: PacketHeader_

- [x] 2.3 (P) BanchoString を Caterpillar カスタムフィールド型として実装する
  - osu! 独自のプレゼンスバイト方式（空文字列 / ULEB128 長 + UTF-8 データ）を双方向変換する
  - 他の Caterpillar struct にフィールドとしてネスト可能であること
  - 空文字列、ASCII 文字列、マルチバイト UTF-8 文字列のラウンドトリップテストが通ること
  - _Requirements: 3.1, 3.6_
  - _Boundary: BanchoString_

- [ ] 3. ワイヤ型とパケット I/O
- [x] 3.1 Message, IntList, Channel, StatusUpdate を定義する
  - 各型を Caterpillar struct として定義し BanchoString を文字列フィールドに使用する
  - IntList は長さプレフィックス付き動的配列として定義する
  - 各型の pack/unpack ラウンドトリップテストと既知バイト列照合テストが通ること
  - _Requirements: 3.2, 3.3, 3.4, 3.5, 3.6_
  - _Depends: 2.3_
  - _Boundary: Wire Types_

- [x] 3.2 (P) RawPacket struct と read_packets 関数を実装する
  - ヘッダフィールドと可変長ペイロードを一体化したパケット struct を定義する
  - Caterpillar の Greedy 配列で HTTP body から全パケットを一括パースする関数を実装する
  - パース結果を ClientPacketID とペイロードバイト列の組に変換する
  - 未知の PacketID（ClientPacketID に存在しない値）はフィルタしてスキップする
  - Caterpillar の例外を PacketReadError でラップする
  - Greedy 配列のエラー挙動を PoC テストで検証し、不完全データを黙って切り捨てる場合は消費バイト数 vs 入力バイト数の事後チェックを追加する
  - テスト: 単一パケット、複数連結パケット、空データで空リスト返却、ヘッダ 7 バイト未満でエラー、ペイロード不足でエラー、未知 ID スキップ
  - _Requirements: 4.1, 4.2, 4.4, 4.5_
  - _Depends: 2.1, 2.2_
  - _Boundary: RawPacket, read_packets_

- [x] 3.3 (P) write_packet 関数を実装する
  - ServerPacketID とペイロードバイト列からヘッダ付き完全パケットバイト列を生成する
  - Compression は常に False で構築する
  - 空ペイロードと既知パケットの出力テストが通ること
  - _Requirements: 4.3_
  - _Depends: 2.1, 2.2_
  - _Boundary: write_packet_

- [ ] 3.4 (P) PacketDispatcher を実装する
  - デコレータで ClientPacketID にハンドラ関数を紐づけて登録する機能を実装する
  - 受信パケットの ClientPacketID に対応するハンドラを呼び出し、未登録 ID は無視する
  - 登録済み全ハンドラの一覧を取得する機能を実装する
  - 同一 ClientPacketID への重複登録を DuplicateHandlerError で拒否する
  - テスト: 登録→呼び出し成功、未登録 ID 無視、一覧取得、重複登録エラー
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_
  - _Depends: 2.1_
  - _Boundary: PacketDispatcher_

- [ ] 4. ログイン関連 S2C パケット型
- [ ] 4.1 スカラーペイロードの S2C パケット型とビルダー関数を定義する
  - LoginReply（signed 32-bit: ユーザー ID またはエラーコード）のビルダーを実装する
  - ProtocolVersion（signed 32-bit）のビルダーを実装する
  - LoginPermissions（signed 32-bit: 権限ビットマスク）のビルダーを実装する
  - Notification（BanchoString）のビルダーを実装する
  - ChannelInfoComplete（空ペイロード）のビルダーを実装する
  - SilenceInfo（signed 32-bit: 残り秒数）のビルダーを実装する
  - FriendsList（IntList）のビルダーを実装する
  - UserPresenceBundle（IntList: ユーザー ID 一覧）のビルダーを実装する
  - 各ビルダーが正しい ServerPacketID と正しいバイト列を生成するテストが通ること
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.7, 6.9, 6.10, 6.11_
  - _Depends: 3.1, 3.3_
  - _Boundary: S2C Login Packets_

- [ ] 4.2 複合ペイロードの S2C パケット型とビルダー関数を定義する
  - UserPresence（UserId, Username, Timezone, CountryId, Permissions|Mode packed, Longitude, Latitude, Rank）の struct とビルダーを実装する
  - UserStats（UserId, StatusUpdate, RankedScore, Accuracy, PlayCount, TotalScore, Rank, PP）の struct とビルダーを実装する
  - ChannelAvailable と ChannelAvailableAutojoin（Channel 型ペイロード、異なる ServerPacketID）のビルダーを実装する
  - 各ビルダーが正しい ServerPacketID と正しいバイト列を生成するテストが通ること
  - _Requirements: 6.5, 6.6, 6.8, 6.12_
  - _Depends: 3.1, 3.3_
  - _Boundary: S2C Login Packets_

- [ ] 5. 統合と検証
- [ ] 5.1 PacketDispatcher の DI 登録と protocol パブリック API を整備する
  - app.py の lifespan 内で PacketDispatcher を DI コンテナにシングルトン登録する（infrastructure → transports の逆方向 import を回避）
  - protocol パッケージの公開 API を re-export する
  - Container 経由で PacketDispatcher を resolve できること
  - import-linter チェックが通ること
  - _Requirements: 5.1, 5.2_
  - _Depends: 3.4_
  - _Boundary: PacketDispatcher, DI Container_

- [ ] 5.2 read_packets → PacketDispatcher の end-to-end フロー検証
  - バイトストリームから read_packets で読み取り → dispatch で各ハンドラ呼び出しの統合テストを書く
  - ダミーハンドラを登録し正しい PacketID でのみ呼び出されることを検証する
  - ruff check, basedpyright, import-linter が全て通ること
  - _Requirements: 4.1, 4.2, 5.2, 5.3_
  - _Depends: 3.2, 3.4, 5.1_
