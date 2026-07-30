# ADR 0016: Use the apex domain for the Web App

## Status
Accepted (2026-07-30)

## Context
AthenaはStable client互換の`osu.<domain>`、`c.<domain>`系hostと、first-party Web Appを同じdeploymentで提供します。Web Appのsession cookieとsame-origin APIをStable client用hostへ露出させず、private serverとして一般的なapex domainを利用者向けWeb URLにする必要があります。

## Decision
`https://<domain>`をAthena Web Appのcanonical originとします。Reverse proxyはapex domainの`/api/web/*`、`/api/public/*`、`/api/admin/*`、`/api/v2/*`、`/signalr/*`を`athena_server`へ転送し、それ以外を`athena_web`へ転送します。

このapex routing contractはfrontend workspaceを作成してWeb Appを有効化する時点で適用します。Initial monorepo migrationでは`athena_web` upstreamやapexのWeb catch-all routeを追加せず、存在しないprocessをdevelopment/production ingressの必須前提にしません。

`osu.<domain>`はStable legacy Web endpoint、`c.<domain>`、`c<digits>.<domain>`、`ce.<domain>`はBancho endpointとして`athena_server`だけへ転送します。`a.<domain>`と`b.<domain>`はStable互換asset/beatmap surfaceとしてserver側のownershipに残します。`api.<domain>`はcanonical API originとして作らず、Public/Admin APIもapex domainのversioned pathを正本とします。

Web Session cookieは`Domain`属性を設定しないhost-only cookieとし、Stable用subdomainへ送信しません。Stable responseが返すbeatmap/user chart URLは`https://<domain>/b/{id}`および`https://<domain>/u/{id}`を指します。Local certificateはapex domainとwildcard subdomainの両方を含めます。

## Consequences
BrowserのWeb Appと`/api/web/*`はsame-originを維持しながら、session credentialはStable client hostから隔離されます。Nginxがpath/host routingを所有し、Next.js Route HandlerやServer Actionはauthorizationまたはdomain mutationのauthorityになりません。
