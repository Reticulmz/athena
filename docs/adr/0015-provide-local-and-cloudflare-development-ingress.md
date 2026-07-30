# ADR 0015: Provide local and Cloudflare development ingress profiles

## Status
Accepted (2026-07-30)

## Context
AthenaのStable/Lazer clientとWeb AppはHTTPS、複数hostname、reverse proxyを含む実際のingressに近い環境で検証する必要があります。Cloudflare Tunnelはreal clientや外部callbackのintegrationに有用ですが、Cloudflare account、network、machine固有credentialを必要とするため、open-source contributorとCIの必須前提にはできません。Appのloopback portへ直接接続するだけではproduction相当のrouting contractを検証できません。

## Decision
Local development ingressを2つの正式profileとして提供します。`just dev`はNginx、mkcert、`*.athena.localhost`を使うcredential不要かつoffline可能なprofileとします。`just dev-tunnel`は同じprocess graphとNginx routingへCloudflare Tunnelを追加し、real client、external callback、HTTPS/subdomain integrationの推奨profileとします。

`localhost:8000`や`localhost:3000`などapp portへの直接アクセスはreadiness、health check、internal debuggingだけに使用し、通常のclient access URLとしてdocumentしません。LocalとCloudflareでapp routingを分岐させず、どちらも同じreverse proxyを経由します。

Tracked templateは`infra/development/`、generated certificateとmachine固有Cloudflare設定はworktreeの`.state/`が所有します。Cloudflare設定がない場合はcore processを失敗させず、`just dev-tunnel`が必要なsetupを明示します。

## Consequences
ContributorとCIはexternal credentialなしでfull local stackを再現できます。MaintainerはCloudflareを使う高忠実度profileを明示的に選択でき、raw localhost accessによるcookie、host routing、TLS behaviorの見落としを減らせます。
