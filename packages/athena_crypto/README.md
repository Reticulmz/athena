# athena-crypto

`athena-crypto` はAthena serverが利用するnative score payload復号packageです。配布名とimport namespaceは、それぞれ `athena-crypto` と `athena_crypto` です。

このworkspaceをrepository rootから独立して検証するには、workspace directoryで次を実行します。

```bash
nix develop --command python scripts/verify_artifact.py
```

このentrypointはRust unit test、temporary directoryへのclean wheel build、wheel archive内のnative extensionとpublic typing artifact、wheelだけをinstallしたconsumer venvでのnative behavior testとtype-aware consumer checkを順に実行します。

Repository-wide artifact validationはrootで次を実行します。

```bash
just build
```
