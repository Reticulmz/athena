# TanStack StartとNext.jsの評判比較調査

- 調査基準日: 2026-07-30
- 対象: React full-stack frameworkとしてのTanStack StartとNext.js
- 判断対象: Athena Web Appの初期基盤としてTanStack StartをNext.jsより優先すべきか

## Executive conclusion

2026-07-30時点では、AthenaはNext.js App Routerの採用判断を維持するのが妥当である。

TanStack Startの評判は単なる期待先行ではない。Vite/Rsbuild、型付きrouteとsearch params、明示的なloader/cache、TanStack Queryとの統合、RSCを必須にしないSSR、Vercelへの依存を避けやすいdeployment modelは、複数の公開移行計画で一貫して評価されている。[U1][U2][U3] 特に、interactiveなAdmin/Ops UIを持ち、Python backendをsource of truthとするAthenaの設計思想とはよく合う。

一方、公式資料自身がTanStack StartをRelease Candidateと位置付け、RSCをexperimentalとしている。[T1][T3] `@tanstack/react-start`が非prereleaseの`1.168.33`を公開していても、frameworkの成熟度はpackageのmajor versionではなく公式product statusに従ってRCと評価すべきである。[T1][T2] 公開されたLTS期間、維持対象version、backport方針も確認できなかった。[T7][T8]

Next.js 16.xはActive LTSで、15.xもMaintenance LTSにあり、upgrade command、codemod、multi-instance self-hostingを含む運用資料が整っている。[N1][N2][N3][N5] Athenaではdomain/auth/API contractをFastAPIとOpenAPIが所有するため、TanStack Start最大の差別化要素であるServer Functionsのend-to-end型安全性を主要な価値として使わない。この条件では、Startの開発体験上の利点より、RC、hosting integration、plugin compatibility、upgrade policyの不確実性が上回る。

これは既存ADRを変更コストだけで追認した結論ではない。実装を白紙から選び直しても、Athena固有の価値差が小さい一方でNext.jsの公式な運用成熟度が明確なため、現時点のrisk-adjusted choiceはNext.jsになる。

## 調査方法と限界

### 証拠の扱い

| 強度 | 扱い |
| --- | --- |
| 強 | framework自身のstatus/support policy、現行公式docs、release情報、Athenaのaccepted ADR |
| 中 | 複数の独立した利用projectで反復する評価、reproducerやproduction contextを持つ公開Issue |
| 弱 | 単一projectの計画、原因未確定のperformance report、再現条件が不足した感想 |

事実、利用者報告、推論を次のように分離した。

- 事実: 公式status、support policy、documented feature、release、Issueのopen/closed状態。
- 利用者報告: 公開Issueや移行計画の執筆者が述べた利点、不満、測定結果。
- 推論: それらをAthenaのarchitectureへ当てはめた採用判断。

### 標本偏り

- GitHub Issueは問題を持つ利用者が投稿するため、障害や不満を過大に含む。
- 公開migration issueは技術選定を公開するOSS projectに偏り、市場全体の採用率を表さない。AI生成と思われる移行計画もあるため、計画数を採用率として数えていない。
- TanStack公式比較ページはvendor-authored marketingである。statusやdocumented featureの確認には使うが、優劣主張の独立証拠には使わない。[T4]
- RedditとXは利用可能な取得backendがなく、今回の標本に含められなかった。したがって、private community、企業内採用、非GitHub利用者の評判は未観測である。
- framework間の一般化可能なperformance benchmarkは確認できなかった。個別projectの測定をframework全体の速度差へ一般化しない。

## Evidence table

| 論点 | 確認できた証拠 | 評価 | 強度 |
| --- | --- | --- | --- |
| TanStack Startのstatus | 公式overviewはRelease Candidate、feature-complete、API considered stableだがbug-freeではないと説明する。[T1] | production利用は可能だがGA/LTS相当とは扱わない。 | 強 |
| package versionとの不一致 | `@tanstack/react-start@1.168.33`は2026-07-29公開の非prerelease releaseである。[T2] | `1.x`だけを根拠にstableと判断しない。公式product statusを優先する。 | 強 |
| Next.jsのstatus | 16.xはActive LTS、15.xはMaintenance LTS。最新stableとして16.2.12が2026-07-25に公開された。[N1][N2] | support対象と期間を運用計画へ組み込める。 | 強 |
| Rendering model | Startは通常SSRが標準でRSCはoptionalかつexperimental。Next App RouterはServer Componentsがdefaultで、Client Componentsも選べる。[T3][N6] | RSCを設計中心にしないAthenaにはStartのmodelが単純だが、NextでもClient boundaryを明示すれば実現できる。 | 強 |
| Self-host | StartはNode/Docker、Cloudflare、Netlify、Railway、Nitro等をdocumentするが、`nitro/vite`はactive development中。[T5] NextはNode/Dockerの全feature対応とmulti-instance運用をdocumentする。[N4][N5] | 両方self-host可能。現時点の運用資料はNextが強い。 | 強 |
| Upgrade支援 | StartのNext migration guideは手動mappingが中心で、application version upgrade用codemod suiteは確認できない。[T6] Nextは`next upgrade`と`@next/codemod`を提供する。[N3][N3C] | 高頻度更新への追随コストはNextの方が予測しやすい。 | 強 |
| Startへの肯定的評価 | 独立projectがVite speed、typed routes/search、Query統合、Cloudflare/self-host、Next/Vercel coupling回避を移行理由に挙げる。[U1][U2][U3] | 開発体験とdeployment autonomyへの肯定は反復しており、単発感想より強い。 | 中 |
| Startのproduction利用報告 | GitHub DiscussionではAWS ECS Fargateへのproduction deploy、HNでは1万user未満の複数appでのproduction利用とDXへの好評価が報告されている。[U16][U17] | 実利用の存在は確認できるが、自己申告の少数事例であり、運用規模や障害率の一般化には使わない。 | 弱から中 |
| Auth navigation | 推奨auth patternでnavigation/preloadごとにserver round tripが発生するというIssueが2025-04-15からopenである。[U5] | Athenaで同じpatternを採用すると遅延要因になる。backend sessionを毎navigation RPCで再検証しない設計が必要。 | 中 |
| Vite plugin互換性 | `vite-plugin-pwa`がStartのproduction buildで動かないIssueがopenで、Vite Environment API対応が論点になっている。[U6] | 「Vite ecosystemをそのまま利用できる」とは限らない。pluginごとのproduction検証が必要。 | 中 |
| Production bundling | Node server-only dependencyがdevelopmentでは動き、Docker productionで失敗するIssueがopenである。[U7] | 単一事例だが、Nitro/Vite bundlingとNix artifactの検証riskを示す。 | 弱から中 |
| SSR/prerender edge cases | static server function、redirect race、旧server function ID、error loggingにproduction-shaped Issueがある。[U8][U9][U10][U11] | production利用の存在と、境界条件がまだ収束中であることの両方を示す。Issue tracker由来の否定的偏りに注意する。 | 中 |
| 改善実績 | Coolify preview/deployとserver/client import diagnosticsのIssueはclosedになった。[U12][U13] | 過去の摩擦を現在も未修正とは扱わない。一方、release追随が必要な領域だったことは示す。 | 中 |
| Next.jsへの不満 | 公開framework decisionではchurn、caching、hosting coupling等への不満が述べられたが、product defectとの因果が薄いためNextを継続した。[U4] | Nextの複雑さは実在するが、移行利益がproduct固有の問題を上回るとは限らない。 | 弱から中 |

## TanStack Startの評判

### 繰り返し評価される利点

1. **Vite/Rsbuild中心の開発体験**

   公開移行計画ではbuild feedbackの速さ、testing、開発loopの短縮が繰り返し理由に挙がる。[U1][U2] これは公式overviewが掲げるVite/Rsbuild supportとも整合する。[T1]

2. **routeとdata flowの明示性**

   Typed routes、typed search params、route loader、preload、TanStack Queryとの統合が好意的に評価される。[U1][U2][U3] Admin/Ops画面のfilter、pagination、URL stateには具体的な利点がある。

3. **Reactをinteractive-firstで使えること**

   Startはfull-document SSRを提供しつつ、RSCをdefaultにしない。[T1][T3] RSCのcache invalidationやServer/Client boundaryを中心にarchitectureを組みたくない利用者にとって、Next.jsより理解しやすいという評判につながっている。ただし「理解しやすい」は利用者評価であり、全projectに共通する客観factではない。

4. **deployment autonomy**

   Cloudflare Workersやself-host Node/Dockerへの移行、Vercel couplingの回避が採用理由として現れる。[U1][U3] Herocastの移行epicはCloudflare上で実際のcookie、cache、SDK、cold startを検証しており、単なる希望より強いproduction-shaped evidenceである。[U1]

5. **TanStack ecosystemの一貫性**

   Router、Query、Startを同じmental modelで構成できる点は、TanStack利用者から明確に支持されている。[U2] 一方、AthenaがTanStack QueryだけをNext.js内で使う選択肢も残るため、この利点はStart専用ではない。

### 繰り返し確認される不満

1. **production deploymentとbundlingの摩擦**

   Coolify/self-host起動、server-only package、Nitro/Vite build、static server functionなど、developmentでは見えないproduction境界のIssueが複数ある。[U7][U8][U12] 一部は既にfixed/closedであり、すべてを現行bugとして数えるべきではない。それでも、hosting abstractionがまだ収束中という公式の`nitro/vite` caveatとは整合する。[T5]

2. **SSR、hydration、prerenderのedge case**

   prerender coverage外のstatic payload、redirect race、deployment後に残る旧server function IDなどの報告がある。[U8][U9][U10] これらは一般的な失敗率を示さないが、RC段階で重点的にacceptance testすべき領域を示す。

3. **Auth guardの性能と設計難度**

   `beforeLoad`にserver auth checkを置くpatternがnavigationやpreloadごとにround tripを起こし、React Query cache等の回避策が議論されている。[U5] Startそのものがsession validationを毎回必須にするわけではないが、公式例や一般的patternを素朴に採用した際のpitfallとして無視できない。

4. **docsと現行APIの追随**

   production起動方法、route generation、server/client import errorの診断に関するIssueが見つかる。[U12][U13] closedになった問題もあり改善は速いが、利用者側にはreleaseとdocsを同時に追う負担がある。

5. **Vite plugin ecosystemの条件付き互換性**

   Startのmulti-environment buildでは、通常のsingle-environment Vite app向けpluginがそのまま動かない場合がある。[U6] Vite採用を理由にplugin互換性を推定せず、SSR production buildで個別に確認する必要がある。

### Production adoptionについて言える範囲

TanStack Startがproductionで使われていること自体は、production errorを扱うIssue、実deployを含むmigration epic、self-host projectの移行計画に加え、AWS ECS Fargateへのdeploy報告と1万user未満の複数appでの利用報告から確認できる。[U1][U3][U9][U10][U11][U16][U17] しかし、公開Issueや自己申告から企業市場全体の採用率、traffic規模、運用年数、障害率を推定することはできない。

GitHub starやmigration issueの件数も、関心度のproxyにはなってもproduction maturityの証拠ではない。したがって本調査は「利用実績がない」とも「Next.jsと同等に実証済み」とも結論しない。

### 弱い証拠として隔離した情報

- Next.jsからStartへ移したstatic documentation siteで約30%のFCP regressionとpending flashが報告されているが、原因は未確定である。[U14] 個別case studyとしてのみ扱う。
- Mapbox使用時にStartのmemory使用量がNext.jsより大きいというIssueは、reproducerが失われ測定条件も不足したため、framework一般のmemory比較には使わない。[U15]
- 古いalpha期のblogやIssueは、2026-07-30のRC評価へ直接持ち込まない。現行docs、現行release、open Issueを優先した。

## Next.jsとの比較

### 公式な成熟度と運用面

Next.js 16.xはActive LTSであり、15.xにはMaintenance LTSとしてcritical fixとsecurity updateが提供される。[N1] `next upgrade`、codemod、major version別upgrade guideがあり、breaking changeへの移行経路がdocumentされている。[N3][N3C] Next.js 16.2ではdeployment Adaptersがstableとされた。[N9]

Self-hosting docsはreverse proxy、image optimization、distributed cache、build ID、Server Function encryption key、deployment ID、version skew、streaming proxy、multi-instance cache coordinationまで扱う。[N5] これはself-hostが自動的に単純という意味ではない。むしろNext.jsのcacheとrolling deploymentには明示的な運用責務があることを示す。ただし、その責務と対処方法が公式に列挙されている点はStartより成熟している。

App RouterはServer Componentsをdefaultとし、production HTML、RSC payload、streaming、hydrationを組み合わせる。[N6] このmodelは強力だが、AthenaのようにPython APIをsource of truthとするappでは、data ownershipとcacheをNext.jsへ寄せすぎない境界設計が必要である。

### 評判上の強み

- ecosystem、third-party integration、learning material、採用者数の大きさは、競合であるTanStack自身の比較ページでもNext.jsの強みとして認められている。[T4]
- LTS policy、security update区分、upgrade toolingが公開され、運用者がversion lifecycleを計画できる。[N1][N3][N3C]
- Node/Docker self-hostの全feature対応と、複数instance運用の具体的guideがある。[N4][N5]
- Server Actions、CSRF、closure encryption、rolling deployment時のkey共有まで公式docsが説明する。[N7]

### 評判上の弱み

- Vercel-centricに見える設計、caching semantics、App Router/RSCのmental model、major upgrade時のchurnへの不満は公開decisionやmigration planで繰り返される。[U1][U4]
- Self-host時にはcache coordination、encryption key共有、deployment skew対策が必要であり、単一Node process以外の運用は設定不要ではない。[N5]
- App RouterはReact canary releaseをframework validation下で利用するため、「すべてがReactの通常stable channelだけで構成される」とは言えない。[N8]

これらはNext.jsを無条件に選ぶ根拠でも、TanStack Startへ移る十分条件でもない。AthenaではNext.js側の責務をthin frontend/BFFに限定し、domain state、authorization、durable cacheをPython側へ残すことで、Next.js固有の複雑さを局所化できる。

## Athena固有条件での比較

| 判断軸 | Athenaの条件 | TanStack Start | Next.js | Athena向け評価 |
| --- | --- | --- | --- | --- |
| Domain/API ownership | FastAPI command/query use-caseとOpenAPIがsource of truth。[A1][A2] | Server Functionsをthin proxyに限定すれば適合する。主要なfull-stack型安全性は活用しにくい。 | Route Handler/Server Actionsをthin BFFに限定すれば適合する。既存ADRが境界を明文化済み。 | 同等。ただしStartの差別化価値が縮小する。 |
| Auth/session | FastAPI-issued HttpOnly session、Valkey state、same-origin `/api/web/*`。[A2][A3] | 実現可能。Start auth guardを毎navigation server RPCにしない独自設計が必要。[U5] | 実現可能。Nextはderived auth stateだけを読み、session authorityを持たない。[A3] | Nextがやや有利。既存contractと運用資料がある。 |
| CSRF | FastAPIがsynchronizer tokenを生成、検証する。[A4] | Server Functions内蔵保護を正本にせず、OpenAPI requestへtokenをforwardする必要がある。[T9] | Route Handler/Clientからtokenをforwardし、FastAPIで検証する既存方針がある。 | 同等。framework native mutationの価値は使わない。 |
| UI特性 | Public/User/Admin/Opsのinteractive UI。filterとURL stateが多い想定。[A1] | Typed search params、loader、Query統合が強く適合する。RSC不要。 | Client ComponentsとTanStack Queryを必要箇所で利用できる。RSC defaultのboundary設計は必要。 | 開発体験はStartが有利。決定的差ではない。 |
| Type safety | Python OpenAPI generated clientがcross-language contract。[A1] | Router内の型安全性は有益。Server Functionsのend-to-end型安全性はPython境界を越えない。 | Generated clientをServer/Client boundaryで共有できる。 | 同等。OpenAPIがframework差を吸収する。 |
| Self-host/Nix | Node artifactをNixで固定し、reverse proxy配下で運用する。 | Node/Dockerはdocument済み。Nix固有guideは未確認。Nitro/Vite integrationはactive development中。[T5] | Node/Dockerは全feature対応。multi-instance guideが詳細。[N4][N5] Nix固有guideは未確認。 | Nextが有利。どちらもNix acceptance testは必要。 |
| Upgrade/support | 長期運用とsecurity updateの予測可能性が重要。 | 公開LTS/backport期間を確認できない。release頻度が高い。 | Active/Maintenance LTS、upgrade command、codemodがある。[N1][N3][N3C] | Nextが明確に有利。 |
| Ecosystem | UI component system、testing、observability、OpenAPI client等との統合が必要。 | Vite ecosystemは魅力だがmulti-environment plugin compatibilityを個別確認する。[U6] | integration、guide、運用知識が多い。[T4] | Nextが有利。 |
| Migration/lock-in | implementation costは判断理由にしない。将来の可逆性は重視する。 | Nextからのmanual migration guideはある。[T6] | 現在のaccepted boundaryはframework非依存性を高く保っている。[A1] | 現時点はNext。thin boundaryを守れば将来移行可能。 |

## Athenaでのriskとunknown

### TanStack Startを今採用する場合

- RC中のAPI/docs/release追随をAthena側が負う。
- Nitro/Vite output、server-only dependency、prerender、rolling deployをNix production artifactで検証する必要がある。
- OpenAPI generated client、cookie forwarding、SSR response cache、CSRF token forwardingをAthenaの境界に合わせて設計する必要がある。
- Start native auth/server function patternを厚くすると、FastAPIがdomain/auth source of truthというarchitectureから逸脱する。
- Vite pluginはdevelopment successだけで判断せず、production SSR buildとruntimeの両方でcompatibility testが必要になる。

### Next.jsを継続する場合

- RSC/App RouterのServer/Client boundaryとcache semanticsを理解し続ける必要がある。
- multi-instance self-hostではcache coordination、encryption key、deployment ID、version skew対策が必要になる。[N5][N7]
- Vercel固有optimizationへ無意識に依存しないself-host acceptance testが必要になる。
- Next.jsをdomain backendへ拡張するとPython/OpenAPI contractが二重化するため、thin BFF制約を機械的に守る必要がある。[A1][A2]

### 未確認事項

- TanStack StartのGA時期、LTS期間、security backport policy。
- Nix向けの公式deployment support。両frameworkとも一般的Node/Docker artifactとしての利用は確認できるが、Nix固有保証はない。
- Athena実画面でのbuild time、HMR、SSR latency、memory、bundle size。一般benchmarkからは決められない。
- Athenaが将来RSCやframework-local Server Functionsを必要とするか。現行ADRでは必要性がない。
- 非公開企業でのTanStack Start production adoption、traffic規模、長期障害率。

## Recommendation

AthenaはNext.js App Routerを維持し、次の境界を採用条件として固定する。UI component systemはこのframework比較とは分離して実装開始時に決定する。

1. FastAPI command/query use-case、session、authorization、CSRF、OpenAPIをsource of truthにする。
2. Next.js Route Handler/Server Actionsはcookie、session bootstrap、CSRF forwarding、軽いresponse shapingに限定する。
3. RSCをdomain architectureの前提にせず、interactive部分はClient Componentsを明示的に使う。
4. URL stateやclient cacheに必要ならTanStack Routerへ全面移行せず、まずTanStack Query等の独立packageを評価する。
5. Nix self-host acceptance testでrolling deploy、streaming、cache、session cookie、CSRF、OpenAPI clientを検証する。

TanStack Startは却下ではなく、次の条件が揃った時点で再評価する有力候補とする。

- 公式docsがRCからGAへ移行する。
- 維持version、security fix、backport期間が公開される。
- Node/Nitro production integrationがactive development表記を脱し、Athena相当のNix self-host構成で再現可能になる。
- version upgrade支援とmigration guidanceが成熟する。
- Athenaの実測でNext.js固有の問題が顕在化し、Startがその問題を直接解消することをprototypeで確認できる。

再評価時は、同一のOpenAPI client、session cookie、CSRF、Admin table、SSR routeを両frameworkで実装し、build time、cold start、navigation latency、memory、rolling deployment、error observabilityを比較する。現時点では、そのprototypeを本採用前提で進めるだけの不確実性低減効果はない。

## Sources

### TanStack公式一次資料

- [T1] TanStack Start, "Overview", 取得日 2026-07-30.
- [T2] TanStack Router release, `@tanstack/react-start@1.168.33`, 2026-07-29.
- [T3] TanStack Start, "Server Components", 取得日 2026-07-30.
- [T4] TanStack Start, "Comparison", 取得日 2026-07-30. Vendor-authored comparisonとして利用。
- [T5] TanStack Start, "Hosting", 取得日 2026-07-30.
- [T6] TanStack Start, "Migrate from Next.js", 取得日 2026-07-30.
- [T7] TanStack, "Support", 取得日 2026-07-30.
- [T8] TanStack, "Paid Support", 取得日 2026-07-30.
- [T9] TanStack Start, "Server Functions", 取得日 2026-07-30.

### Next.js公式一次資料

- [N1] Next.js, "Support Policy", 取得日 2026-07-30.
- [N2] Next.js release `v16.2.12`, 2026-07-25.
- [N3] Next.js, "Upgrading", 取得日 2026-07-30.
- [N3C] Next.js, "Codemods", 取得日 2026-07-30.
- [N4] Next.js, "Deploying", 取得日 2026-07-30.
- [N5] Next.js, "Self-Hosting", 取得日 2026-07-30.
- [N6] Next.js, "Server and Client Components", 取得日 2026-07-30.
- [N7] Next.js, "Server Actions", 取得日 2026-07-30.
- [N8] Next.js, "Installation", 取得日 2026-07-30.
- [N9] Next.js, "Next.js 16.2", 2026-03-18.

### 公開利用者報告とGitHub一次情報

- [U1] hero-org/herocast #754, "Migrate Next.js 15 to TanStack Start on Cloudflare Workers", 2026-06-04, open.
- [U2] sendou-ink/sendou.ink #2900, "Migrate to TanStack Start", 2026-03-20, open.
- [U3] bambanah/melvin #419, "Migrate framework to TanStack Start", 2026-07-23, open.
- [U4] lukaprsina/jknm #2, "Decide: framework", 2026-07-13, closed.
- [U5] TanStack/router #3997, auth navigation performance, 2025-04-15, open.
- [U6] TanStack/router #4988, `vite-plugin-pwa` production incompatibility, 2025-08-17, open.
- [U7] TanStack/router #6450, server-only package production bundling, 2026-01-22, open.
- [U8] TanStack/router #7630, static server function JSON parse failure, 2026-06-14, open.
- [U9] TanStack/router #7753, redirect race and blank app, 2026-07-08, open.
- [U10] TanStack/router #7363, invalid server function ID returns 500, 2026-05-07, open.
- [U11] TanStack/router #7873, server function error logging, 2026-07-21, open.
- [U12] TanStack/router #5476, Coolify self-host preview/deploy, 2025-10-14, closed 2026-07-16.
- [U13] TanStack/router #5469, server/client import diagnostics, 2025-10-13, closed 2026-02-18.
- [U14] aymericzip/intlayer #462, static page FCP regression report, 2026-06-09, open.
- [U15] TanStack/router #5084, memory usage report, closed as not reproducible.
- [U16] TanStack/router Discussion #5780, TanStack Start appのAWS ECS Fargate production deploy報告, 2025-11-07.
- [U17] Hacker News #47761609, TanStack Start production利用とNext.js比較に関する利用者コメント, 取得日 2026-07-30.

### Athena repository evidence

- [A1] [ADR 0006: Adopt Next.js App Router for Athena Web App](../adr/0006-adopt-nextjs-for-web-app.md).
- [A2] [ADR 0007: Treat Web App API as an Exposed First-Party Surface](../adr/0007-treat-web-app-api-as-exposed-first-party-surface.md).
- [A3] [ADR 0008: Use Server-Side Session Cookies for Web App Authentication](../adr/0008-use-server-side-session-cookies-for-web-app-auth.md).
- [A4] [ADR 0009: Require CSRF Token Gate for Web App API](../adr/0009-require-csrf-token-gate-for-web-app-api.md).

[T1]: https://tanstack.com/start/latest/docs/framework/react/overview
[T2]: https://github.com/TanStack/router/releases/tag/%40tanstack/react-start%401.168.33
[T3]: https://tanstack.com/start/latest/docs/framework/react/guide/server-components
[T4]: https://tanstack.com/start/latest/docs/framework/react/comparison
[T5]: https://tanstack.com/start/latest/docs/framework/react/guide/hosting
[T6]: https://tanstack.com/start/latest/docs/framework/react/migrate-from-next-js
[T7]: https://tanstack.com/support
[T8]: https://tanstack.com/paid-support
[T9]: https://tanstack.com/start/latest/docs/framework/react/guide/server-functions
[N1]: https://nextjs.org/support-policy
[N2]: https://github.com/vercel/next.js/releases/tag/v16.2.12
[N3]: https://nextjs.org/docs/app/getting-started/upgrading
[N3C]: https://nextjs.org/docs/app/guides/upgrading/codemods
[N4]: https://nextjs.org/docs/app/getting-started/deploying
[N5]: https://nextjs.org/docs/app/guides/self-hosting
[N6]: https://nextjs.org/docs/app/getting-started/server-and-client-components
[N7]: https://nextjs.org/docs/app/guides/server-actions
[N8]: https://nextjs.org/docs/app/getting-started/installation
[N9]: https://nextjs.org/blog/next-16-2
[U1]: https://github.com/hero-org/herocast/issues/754
[U2]: https://github.com/sendou-ink/sendou.ink/issues/2900
[U3]: https://github.com/bambanah/melvin/issues/419
[U4]: https://github.com/lukaprsina/jknm/issues/2
[U5]: https://github.com/TanStack/router/issues/3997
[U6]: https://github.com/TanStack/router/issues/4988
[U7]: https://github.com/TanStack/router/issues/6450
[U8]: https://github.com/TanStack/router/issues/7630
[U9]: https://github.com/TanStack/router/issues/7753
[U10]: https://github.com/TanStack/router/issues/7363
[U11]: https://github.com/TanStack/router/issues/7873
[U12]: https://github.com/TanStack/router/issues/5476
[U13]: https://github.com/TanStack/router/issues/5469
[U14]: https://github.com/aymericzip/intlayer/issues/462
[U15]: https://github.com/TanStack/router/issues/5084
[U16]: https://github.com/TanStack/router/discussions/5780
[U17]: https://news.ycombinator.com/item?id=47761609
