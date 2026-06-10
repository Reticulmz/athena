# ADR 0001: Rijndael-256 Decryption via PyO3 + Rust

## Status
Accepted (Updated 2026-06-11)

## Context
osu! stable client は score payload を Rijndael-256 で暗号化して送信します。仕様:
- Algorithm: Rijndael-256 (AES の原型、block size が可変)
- Key size: 256-bit (32 bytes)
- Block size: 256-bit (32 bytes) — **標準 AES-256 は block size 128-bit**
- Mode: CBC
- IV: 32-byte (block size と同じ)
- Key selection: `osuver` field の有無で key が変わる

Python の標準 crypto library (`cryptography`) は AES (block size 128-bit 固定) のみ対応で、Rijndael-256 (block size 256-bit) には対応していません。

## Decision
Rust の `simple-rijndael` crate を PyO3 で wrap し、Python から呼び出す形で実装します。

`simple-rijndael` は Pure-Peace (peace サーバー開発者) が osu! score decryption 専用に開発した crate で、Rijndael-CBC + block_size=32 に対応しています。

Implementation structure:
```
athena-crypto/           # Rust workspace
├── Cargo.toml
├── src/
│   └── lib.rs          # PyO3 bindings
└── pyproject.toml      # maturin build config

osu_server/
└── infrastructure/
    └── crypto/
        └── score_crypto.py  # Python interface
```

## Consequences

### Positive
- **Security**: Well-tested Rust crate を使用し、自前実装の crypto vulnerability を回避
- **Correctness**: Rijndael-256 の正確な実装を保証
- **Performance**: Rust native performance (ただし decrypt は heavy operation ではないので、実質的な差は小さい)
- **Type safety**: Rust の強い型システムで crypto logic の安全性向上
- **Future-proof**: lazer 対応時に crypto layer の拡張が容易

### Negative
- **Build complexity**: maturin + Rust toolchain が必要 (CI/CD と開発環境)
- **Maintenance burden**: Rust code の保守が必要 (ただし crypto logic は stable)
- **Deployment**: Wheel build または platform-specific binary が必要

### Neutral
- PyPI に rijndael-256 対応 library が存在する可能性もあるが、信頼性・保守状況が不明
- bancho.py/lets の実装も何らかの rijndael library を使っているはず (調査の余地あり)

## Alternatives Considered

### Pure Python rijndael library
- PyPI で rijndael-256 対応を探す
- pip install で完結
- **Rejected**: 信頼できる well-maintained library が見つからない、security-critical

### Self-implementation (Pure Python or Rust)
- bancho.py/lets の実装を参考に自前実装
- **Rejected**: Crypto implementation は security-critical で、自前実装は避けるべき

## Implementation Notes
- `simple-rijndael` crate: https://github.com/Pure-Peace/simple-rijndael
- PyO3 build tool: maturin
- Key management: osu_server config から key を読み込み、Rust 側に渡す
- Error handling: Rust の Result → Python Exception に変換
