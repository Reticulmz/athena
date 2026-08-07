# Athena Crypto Agent Guidance

Follow root `AGENTS.md` ([../../AGENTS.md](../../AGENTS.md)) for repository-wide
rules. For Python tests, packaging helpers, and public stubs, read
[../../docs/agent-python.md](../../docs/agent-python.md).

## Scope

- Rust and Python native extension sources live under `packages/athena_crypto/src`.
- Package tests live under `packages/athena_crypto/tests`.
- Public typing artifacts live under `packages/athena_crypto/typings`.
- `Cargo.toml`, `pyproject.toml`, and `default.nix` belong to this package owner.

## Commands

Run the package artifact verifier from this workspace inside the root Nix shell:

```bash
cd packages/athena_crypto
python scripts/verify_artifact.py
```

The repository-wide artifact gate is:

```bash
just build
```

## Boundaries

- Preserve the distribution name `athena-crypto` and import namespace `athena_crypto`.
- Do not depend on server source tree imports for artifact verification.
- Public typing changes must be verified from a built wheel, not only an editable checkout.
