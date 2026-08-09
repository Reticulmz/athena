# osu-direct 調査メモ

Generated at: 2026-08-09T00:00:00+09:00

## 結論

Athena で「譜面リスト情報を取得して、Athena 側で osu!direct 検索結果を生成する」案は、外部実装と整合する。CheeseGull は osu! API から譜面set/譜面metadataを複製し、`/api/search` でDB/Sphinx検索結果を返す。bancho.py と Ripple lets は検索UI用の `/web/osu-search.php` を CheeseGull系 mirror APIへ委譲し、返ってきた JSON を stable client の pipe/newline 形式へ変換する。osuBasil と deck はローカルDB内の譜面metadataから同じ形式を直接生成する。

含意: osu!direct検索は、リクエストごとに公式 osu! API へ自由検索を投げる設計ではなく、事前取得/永続化済みの beatmapset metadata を検索して wire format に整形する境界として設計するのが妥当。

## CheeseGull / Cheesegull

- `osuripple/cheesegull` のREADMEは、CheeseGullを公式 osu! beatmap DB の非公式slave database兼 `.osz` cache middleman と説明し、Ripple の osu!direct 用 beatmap mirror を主目的としている。[README.md L5-L11](https://github.com/osuripple/cheesegull/blob/master/README.md#L5-L11)
- CheeseGull は更新検知APIが無い制約を前提に、WIP/Pending/Qualified は30分以上、それ以外は4日以上経過したものを更新対象にする。[README.md L17-L25](https://github.com/osuripple/cheesegull/blob/master/README.md#L17-L25), [models/set.go L31-L45](https://github.com/osuripple/cheesegull/blob/master/models/set.go#L31-L45)
- metadata search endpoint は `/api/search` で、`status`、`query`、`mode`、`amount`、`offset` を `models.SearchSets` に渡し、JSONで beatmapset list を返す。[api/metadata/single.go L94-L121](https://github.com/osuripple/cheesegull/blob/master/api/metadata/single.go#L94-L121)
- `SearchSets` は query がある場合 Sphinx の `cg` index から set id を取り、query が無い場合は `sets` table を直接読む。最終的に `beatmaps` table から子譜面を読み、各setの `ChildrenBeatmaps` に詰める。[models/set_search.go L57-L126](https://github.com/osuripple/cheesegull/blob/master/models/set_search.go#L57-L126), [models/set_search.go L134-L195](https://github.com/osuripple/cheesegull/blob/master/models/set_search.go#L134-L195)
- 永続metadataは `sets` と `beatmaps` に分かれ、set側に artist/title/creator/status/last_update/has_video/genre/language/favourites/set_modes、beatmap側に diff名/md5/mode/BPM/AR/OD/CS/HP/length/playcount/passcount/max_combo/difficulty_rating を持つ。[models/migrations/0001.sql L1-L18](https://github.com/osuripple/cheesegull/blob/master/models/migrations/0001.sql#L1-L18), [models/migrations/0002.sql L1-L22](https://github.com/osuripple/cheesegull/blob/master/models/migrations/0002.sql#L1-L22)
- 新規発見/更新は `go-osuapi` の `GetBeatmaps(BeatmapSetID)` でset単位に取得し、`models.CreateSet` でsetと子譜面を保存する。[dbmirror/discover.go L12-L60](https://github.com/osuripple/cheesegull/blob/master/dbmirror/discover.go#L12-L60), [dbmirror/dbmirror.go L71-L107](https://github.com/osuripple/cheesegull/blob/master/dbmirror/dbmirror.go#L71-L107)
- `.osz` download は検索metadataとは別責務で、`/d/:id` がset存在確認後に cache を取得/作成し、未取得なら downloader でオンデマンド取得する。[api/download/download.go L28-L79](https://github.com/osuripple/cheesegull/blob/master/api/download/download.go#L28-L79), [api/download/download.go L100-L137](https://github.com/osuripple/cheesegull/blob/master/api/download/download.go#L100-L137)
- download cache はサイズ上限、最終要求時刻、壊れた小さいファイルの掃除を持つが、これは検索結果生成には直接必要ない。[housekeeper/housekeeper.go L14-L31](https://github.com/osuripple/cheesegull/blob/master/housekeeper/housekeeper.go#L14-L31), [housekeeper/housekeeper.go L106-L168](https://github.com/osuripple/cheesegull/blob/master/housekeeper/housekeeper.go#L106-L168)

### Cheesegull派生

- `osukurikku/cheesegull` は元実装の `/api/search` に加えて、Chimu互換の `/api/v1/search`、`/api/v1/map/:id`、`/api/v1/set/:id`、`/api/v1/download/:id` を追加している。[api/metadata/single.go L292-L305](https://github.com/osukurikku/cheesegull/blob/master/api/metadata/single.go#L292-L305), [api/download/download.go L166-L170](https://github.com/osukurikku/cheesegull/blob/master/api/download/download.go#L166-L170)
- Chimu互換検索は同じ `sets`/`beatmaps` metadataを使い、AR/OD/CS/HP/difficulty/length/BPM/genre/language などの追加filterをローカルSQLで足す。[models/set_search.go L228-L303](https://github.com/osukurikku/cheesegull/blob/master/models/set_search.go#L228-L303), [models/set_search.go L373-L437](https://github.com/osukurikku/cheesegull/blob/master/models/set_search.go#L373-L437)
- md5 lookup endpoint も追加され、`file_md5` で `beatmaps` を引く。[api/metadata/single.go L65-L85](https://github.com/osukurikku/cheesegull/blob/master/api/metadata/single.go#L65-L85), [models/beatmap.go L136-L150](https://github.com/osukurikku/cheesegull/blob/master/models/beatmap.go#L136-L150)

## 公式osu! wiki

- osu! wikiのBeatmap searchページは、client-side filterはsong selectで使えるが、osu!directはregular full-text searchだけをsupportすると説明している。[Beatmap search / Client](https://osu.ppy.sh/wiki/en/Beatmap_search#client)
- 含意: osu!direct search query parserは作り込まない。MVPではfree textとstable directの`r`/`m`/`p` filterに絞り、AR/OD/CS/HPなどの詳細filterはWeb/APIや将来のmirror API互換拡張として扱う。

## 公式osu! API v2

- 公式 osu!api v2 docs は API 利用について caching と再利用を推奨し、同一user/beatmapの高頻度pollingやAPIをdatabaseのように使うことを避けるよう明記している。目安として 60 requests/minute 以下を求めている。[osu!api v2 Terms of Use L23-L39](https://osu.ppy.sh/docs/#terms-of-use)
- `/beatmapsets/search` は public OAuth endpoint として存在し、pagination 用に `cursor_string` を受けるが、該当sectionは `TODO: documentation` の状態である。[osu!api v2 Beatmapsets/Search L1718-L1769](https://osu.ppy.sh/docs/#search-beatmapset)

含意: Athena の catalog sync は公式API検索を request-time search backend として使わず、取得済みmetadataをDBへ保存して再利用する。coverage state は公式 search cursor/window の不安定さを隠蔽し、上流docs変更時に worker adapter だけを直せる境界に置く。

## Meilisearch

- Meilisearch の index settings は `searchableAttributes`、`filterableAttributes`、`sortableAttributes`、`displayedAttributes` を明示できる。`searchableAttributes` は検索対象fieldと優先順を定義し、`filterableAttributes` はfilter/facet対象、`sortableAttributes` はsort対象、`displayedAttributes` は検索結果に返すfieldを定義する。[Meilisearch settings API](https://www.meilisearch.com/docs/reference/api/settings/update-settings)
- `PATCH /indexes/{index_uid}/settings` は送信したsettingsだけを更新し、`null` でdefaultへ戻せる。[Meilisearch update settings](https://www.meilisearch.com/docs/reference/api/settings/update-settings)
- `searchableAttributes` を手動設定した後、新しくdocumentに追加されたfieldは自動で検索対象に追加されないため、index definition側でfieldを管理する必要がある。[Meilisearch configure searchable attributes](https://www.meilisearch.com/docs/capabilities/full_text_search/how_to/configure_searchable_attributes)

含意: Athena の Meilisearch backend は Rails の `meilisearch-rails` 的な「modelごとの検索field宣言」に近い内部 index definition を持つのが妥当。ただし Meilisearch document は検索候補抽出用であり、stable response の正本は PostgreSQL の beatmapset metadata からhydrateする。

## ParadeDB

- ParadeDB の `pg_search` は PostgreSQL extension としてBM25 index/searchを提供する。[ParadeDB extension install](https://docs.paradedb.com/deploy/self-hosted/extension)
- BM25 index は `USING bm25 (...) WITH (key_field = 'id')` で作成し、検索queryは `@@@` または `|||` と `pdb.score(id)` を使って relevance sort できる。[ParadeDB create index](https://docs.paradedb.com/documentation/indexing/create-index), [ParadeDB queries](https://docs.paradedb.com/documentation/getting-started/queries)
- filter/sort/group/aggregationに使う列もBM25 indexへ含めることが推奨されている。1つのtableにはBM25 indexを1つだけ作成できるため、検索対象fieldとfilter/sort fieldはindex definitionでまとめて管理する必要がある。[ParadeDB filtering](https://docs.paradedb.com/documentation/filtering), [ParadeDB create index](https://docs.paradedb.com/documentation/indexing/create-index)
- partial BM25 indexも作成できるが、query側にも同じ `WHERE` 条件が必要になる。[ParadeDB partial indexing](https://docs.paradedb.com/documentation/indexing/indexing-partial)

含意: Athena の PostgreSQL search backend は plain SQL fallback ではなく ParadeDB を第一候補にできる。ただし extension availability は環境依存なので、specでは `paradedb` backend として明示し、index definitionには searchable/filterable/sortable の列をまとめて持たせる。Meilisearchと同様、検索結果は beatmapset id と rank score を返し、stable response はPostgreSQL metadataからhydrateする。

## Ripple lets

- `osuripple/lets` の `/web/osu-search.php` handler は query/mode/ranked status/page を受け、`cheesegull.getListing` を呼び、結果を `cheesegull.toDirect` で stable client 用の pipe形式へ変換する。[handlers/osuSearchHandler.py L23-L44](https://github.com/osuripple/lets/blob/master/handlers/osuSearchHandler.py#L23-L44), [handlers/osuSearchHandler.py L47-L55](https://github.com/osuripple/lets/blob/master/handlers/osuSearchHandler.py#L47-L55)
- `cheesegull.getListing` は `CHEESEGULL_API_URL/search` に `query`、`offset`、`amount=100`、任意の `status`/`mode` を渡す。[ripple-python-common web/cheesegull.py L76-L87](https://github.com/osuripple/ripple-python-common/blob/master/web/cheesegull.py#L76-L87)
- `toDirect` は CheeseGull JSONの `SetID`、Artist/Title/Creator、RankedStatus、LastUpdate、HasVideo、ChildrenBeatmaps を osu!direct の1行へ整形し、`|` や `@` を壊れない文字へ置換する。[ripple-python-common web/cheesegull.py L108-L132](https://github.com/osuripple/ripple-python-common/blob/master/web/cheesegull.py#L108-L132)
- `/web/osu-search-set.php` は `b` または `s` で CheeseGull から set情報を取り、`toDirectNp` で単一set行を返す。[handlers/osuSearchSetHandler.py L22-L40](https://github.com/osuripple/lets/blob/master/handlers/osuSearchSetHandler.py#L22-L40), [ripple-python-common web/cheesegull.py L89-L98](https://github.com/osuripple/ripple-python-common/blob/master/web/cheesegull.py#L89-L98)
- lets の status mapping は osu!direct status を CheeseGull/osu! API statusへ変換し、direct status `4` は全件扱い、`0`/`7` は ranked/approved 相当のlist扱いにしている。[ripple-python-common web/cheesegull.py L144-L160](https://github.com/osuripple/ripple-python-common/blob/master/web/cheesegull.py#L144-L160)

## bancho.py

- bancho.py は `MIRROR_SEARCH_ENDPOINT` と `MIRROR_DOWNLOAD_ENDPOINT` を必須設定として読む。[app/settings.py L33-L37](https://github.com/osuAkatsuki/bancho.py/blob/master/app/settings.py#L33-L37)
- `/web/osu-search.php` は認証後、`DirectSearchService.search` を呼び、失敗時は `-1\nFailed to retrieve data from the beatmap mirror.`、成功時は pipe/newline format を返す。[app/api/domains/osu.py L330-L415](https://github.com/osuAkatsuki/bancho.py/blob/master/app/api/domains/osu.py#L330-L415)
- `DirectSearchService` は mirror search endpoint に `amount=100`、`offset=page*100`、任意の `query`、`mode`、`status` を渡す。`Newest`、`Top+Rated`、`Most+Played` は文字列検索queryとしては渡さない。[app/services/direct_search.py L97-L125](https://github.com/osuAkatsuki/bancho.py/blob/master/app/services/direct_search.py#L97-L125)
- mirror response は CheeseGull系 JSON shape を想定し、`ChildrenBeatmaps` が無いsetをskip、難易度順で子譜面を並べ、`|` を `I` に置換し、100件返った場合は client に続きがあることを示すため `101` を返す。[app/services/direct_search.py L129-L175](https://github.com/osuAkatsuki/bancho.py/blob/master/app/services/direct_search.py#L129-L175), [app/services/direct_search.py L177-L182](https://github.com/osuAkatsuki/bancho.py/blob/master/app/services/direct_search.py#L177-L182)
- `/web/osu-search-set.php` は `s`、`b`、`c` のいずれかで local `BeatmapSetService.fetch_set_info` を引き、見つからなければ空bodyを返す。ここは mirror search ではなく local DB lookup である。[app/api/domains/osu.py L418-L470](https://github.com/osuAkatsuki/bancho.py/blob/master/app/api/domains/osu.py#L418-L470)
- beatmap metadata cache は検索用mirrorとは別に、RAM cache、DB、osu! API/osu.direct API の三層で、missing時はset単位で取得/保存する。[app/objects/beatmap.py L286-L340](https://github.com/osuAkatsuki/bancho.py/blob/master/app/objects/beatmap.py#L286-L340), [app/objects/beatmap.py L857-L885](https://github.com/osuAkatsuki/bancho.py/blob/master/app/objects/beatmap.py#L857-L885)
- bancho.py の metadata fetch は osu! API key があれば `old.ppy.sh/api/get_beatmaps`、無ければ `osu.direct/api/get_beatmaps` を使う。[app/objects/beatmap.py L38-L61](https://github.com/osuAkatsuki/bancho.py/blob/master/app/objects/beatmap.py#L38-L61)
- cache expiry は最終更新からの経過時間と leaderboard有無で延ばし、最大1日で再確認する。[app/objects/beatmap.py L525-L550](https://github.com/osuAkatsuki/bancho.py/blob/master/app/objects/beatmap.py#L525-L550)

## 近い実装

### osuBasil

- osuBasil の `/web/osu-search.php` は認証後 `DirectSearchService.SearchFormattedAsync` を呼ぶ。route description は、search mirror があれば mirror catalog を検索し、mirrorが落ちたら local search へfallback、mirror無しなら local storage のみ検索すると明記している。[OsuWebRoutes.cs L110-L140](https://github.com/thnhmai06/osuBasil/blob/main/src/Basil.Web/Routing/Bancho/OsuWebRoutes.cs#L110-L140)
- `DirectSearchService.SearchAsync` は `Newest`/`Top Rated`/`Most Played` を非text query扱いにし、mode `-1` をany modeにして、repositoryの local search を呼ぶ。[DirectSearchService.cs L41-L67](https://github.com/thnhmai06/osuBasil/blob/main/src/Basil.Application/Services/Beatmaps/DirectSearchService.cs#L41-L67)
- `SearchFormattedAsync` は mirror設定がある場合 mirrorを先に使い、失敗時だけ local searchへfallbackする。コメントは、local結果があるだけで mirror catalog の残りを隠さないため、mirror設定時は mirrorを置換元として扱うと説明している。[DirectSearchService.cs L70-L108](https://github.com/thnhmai06/osuBasil/blob/main/src/Basil.Application/Services/Beatmaps/DirectSearchService.cs#L70-L108)
- local repository search は保存済み beatmap metadata に対する完全offline検索で、artist/title/creator のLIKE、mode filter、set単位pagination、難易度順の子譜面groupingを行う。[IBeatmapRepository.cs L67-L86](https://github.com/thnhmai06/osuBasil/blob/main/src/Basil.Application/Abstractions/Beatmaps/IBeatmapRepository.cs#L67-L86), [SqliteBeatmapRepository.cs L143-L196](https://github.com/thnhmai06/osuBasil/blob/main/src/Basil.Infrastructure/Persistence/Repositories/SqliteBeatmapRepository.cs#L143-L196)
- mirror client は Chimu/Nerinyan/osu.direct style の de facto contract として、`ChildrenBeatmaps` を持つset JSON arrayを読む。`HasVideo` はboolまたは0/1数値を許容する。[HttpMirrorSearchClient.cs L12-L18](https://github.com/thnhmai06/osuBasil/blob/main/src/Basil.Infrastructure/Beatmaps/HttpMirrorSearchClient.cs#L12-L18), [HttpMirrorSearchClient.cs L25-L47](https://github.com/thnhmai06/osuBasil/blob/main/src/Basil.Infrastructure/Beatmaps/HttpMirrorSearchClient.cs#L25-L47)

### osuTitanic/deck

- deck の direct route は external mirror ではなく local DB の `beatmapsets.search_direct` から検索結果を取り、`direct_beatmap` で pipe形式へ整形する。[direct.py L91-L149](https://github.com/osuTitanic/deck/blob/main/app/routes/web/direct.py#L91-L149)
- `direct_beatmap` は set metadata と子譜面version/modeから osu!direct 1行を構成する。[direct.py L47-L68](https://github.com/osuTitanic/deck/blob/main/app/routes/web/direct.py#L47-L68)
- pickup endpoint は `s`、`b`、`c`、`p`、`t` から local DB の beatmapset を解決し、inactive set は404にする。[direct.py L151-L201](https://github.com/osuTitanic/deck/blob/main/app/routes/web/direct.py#L151-L201)

## osu-search-set.php / NP / link lookup

- LETS は `/web/osu-search-set.php` handler の module 名を `osu_direct_np` としており、`b` または `s` から CheeseGull の beatmapset metadata を取り、`toDirectNp` で単一set行へ整形する。[handlers/osuSearchSetHandler.py L10-L40](https://github.com/osuripple/lets/blob/master/handlers/osuSearchSetHandler.py#L10-L40), [ripple-python-common web/cheesegull.py L89-L98](https://github.com/osuripple/ripple-python-common/blob/master/web/cheesegull.py#L89-L98)
- CheeseGull adapter の `getBeatmap(id)` は beatmap id から `ParentSetID` を引き、その set id で `getBeatmapSet` を呼ぶ。つまり `b` lookup は最終的に beatmapset-centered lookup へ収束する。[ripple-python-common web/cheesegull.py L93-L98](https://github.com/osuripple/ripple-python-common/blob/master/web/cheesegull.py#L93-L98)
- bancho.py の `/web/osu-search-set.php` は `s`、`b`、`c` を同じ `BeatmapSetService.fetch_set_info` へ渡し、レスポンスは検索結果と同じ direct beatmapset row shape を使う。[app/api/domains/osu.py L418-L470](https://github.com/osuAkatsuki/bancho.py/blob/master/app/api/domains/osu.py#L418-L470)
- deck は検索結果と pickup endpoint の両方で `direct_beatmap` を使う。pickup endpoint は `s`、`b`、`c`、`p`、`t` を受け、どれも local DB の beatmapset 解決に寄せている。[direct.py L47-L68](https://github.com/osuTitanic/deck/blob/main/app/routes/web/direct.py#L47-L68), [direct.py L151-L201](https://github.com/osuTitanic/deck/blob/main/app/routes/web/direct.py#L151-L201)
- neomod client は beatmap id しか分からない場合に `/web/osu-search-set.php?b=<beatmap_id>` を非同期に呼び、返ってきた direct row から beatmapset id を取り出して download URL を組み立てる。[Downloader.cpp L226-L258](https://github.com/neomodnet/neomod/blob/master/src/App/Neomod/Downloader.cpp#L226-L258), [Downloader.cpp L262-L312](https://github.com/neomodnet/neomod/blob/master/src/App/Neomod/Downloader.cpp#L262-L312)
- bancho-service-rs の NP parser は stable client の `/np` ACTION から `/beatmapsets/<set>#/<beatmap>` 形式の set id と beatmap id を取り出し、その beatmap id で beatmap metadata を取得して NP state に beatmapset id/md5/name を保存する。[models/tillerino.rs L10-L55](https://github.com/osuAkatsuki/bancho-service-rs/blob/master/src/models/tillerino.rs#L10-L55), [usecases/tillerino.rs L9-L31](https://github.com/osuAkatsuki/bancho-service-rs/blob/master/src/usecases/tillerino.rs#L9-L31)

含意: `osu-search-set.php`、NP command、beatmap link handling は HTTP handler を共有する必要はないが、内部では「beatmapset point lookup」を共有するのが妥当。入力は set id / beatmap id / checksum / topic id / post id / beatmap link を許容し、出力は保存済みまたはオンデマンド取得済みの beatmapset metadata に寄せる。osu!direct row 整形、BanchoBot表示、`.osz` download availability はそれぞれ別の薄い adapter に分ける。

## Athena設計への含意

1. 検索面は `beatmap-mirror` のmetadata cacheを読む read model にする。CheeseGull/osuBasil/deck はいずれも検索時に保存済みmetadataを使う。bancho.py/lets は検索を外部mirrorへ委譲するが、その外部mirrorが CheeseGull 型の保存済みmetadata検索である。
2. `beatmapset` と子 `beatmap` を同時に返せる repository query が必要。osu!direct list行は set metadata と各diff metadataの合成なので、beatmap単体lookupだけでは足りない。
3. 最小対応は `q`、`m`、`r`、`p`、100件page、`101` sentinel、`s`/`b`/`c` pickup、`|` delimiter sanitation。Chimu互換のAR/OD/CS/HP等filterは派生実装の追加機能で、公式wiki上もosu!directは通常全文検索だけなので、初期Athenaでは不要。
4. search miss のたびに公式APIへ同期問い合わせするのは避ける。公式APIは set/id/checksum 解決には使えるが、CheeseGullもbancho.pyも検索panel用の自由検索は保持済みcatalogかmirror catalogへ寄せている。
5. `.osz` download cache と `.osu` file availability は検索結果生成とは別責務。CheeseGullのdownload cacheは有用な参考だが、Athenaでは既存 `beatmap-mirror`/`blob-storage` 境界に合わせて分ける。
6. `beatmap-mirror` research の「osu!direct-compatible mirror URL support は future osu!direct spec で検討」という記述とは矛盾しない。今回の結果は、検索結果の正本を外部mirrorに置く選択肢もあるが、Athena内metadataから生成する選択肢も外部実装で実証済み、という補強である。

## 未決・注意点

- 100件ちょうどの件数表現は実装差がある。bancho.py と osuBasil は `101`、古い Ripple lets は `999` を使う。[bancho.py direct_search.py L168-L175](https://github.com/osuAkatsuki/bancho.py/blob/master/app/services/direct_search.py#L168-L175), [osuBasil DirectSearchService.cs L120-L135](https://github.com/thnhmai06/osuBasil/blob/main/src/Basil.Application/Services/Beatmaps/DirectSearchService.cs#L120-L135), [lets osuSearchHandler.py L47-L49](https://github.com/osuripple/lets/blob/master/handlers/osuSearchHandler.py#L47-L49)
- status mapping は明示仕様化が必要。lets は direct status `4` を全件、`0`/`7` を ranked/approved listとして扱うが、bancho.py は `RankedStatus.from_osudirect(...).osu_api` へ委譲している。[ripple-python-common web/cheesegull.py L144-L160](https://github.com/osuripple/ripple-python-common/blob/master/web/cheesegull.py#L144-L160), [bancho.py direct_search.py L118-L121](https://github.com/osuAkatsuki/bancho.py/blob/master/app/services/direct_search.py#L118-L121)
- `Top Rated`/`Most Played` は外部実装では特殊queryとして扱われるが、実際のsort軸は実装差がある。初期版は `Newest` を last_update/id順、その他は未対応または同一sortに倒す判断を要求仕様で固定する。
