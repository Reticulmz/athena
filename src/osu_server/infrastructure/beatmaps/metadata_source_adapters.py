"""外部APIとcommunity mirrorをビートマップメタデータproviderへ適合させる."""

from __future__ import annotations

import time
from http import HTTPStatus
from typing import TYPE_CHECKING, cast
from urllib.parse import urlencode, urlparse

import httpx
import structlog

from osu_server.domain.beatmaps import (
    BeatmapMetadataSource,
    BeatmapSourceError,
    BeatmapSourceErrorCategory,
    BeatmapSourceVerification,
)
from osu_server.infrastructure.beatmaps.mappers import (
    beatmap_json_to_snapshot,
    beatmap_v1_json_to_snapshot,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from osu_server.domain.beatmaps import BeatmapsetSnapshot
    from osu_server.infrastructure.http.interfaces import BeatmapHttpClient

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class InMemoryBeatmapMetadataProvider:
    """テスト環境向けにスナップショットをインメモリで検索可能にする.

    Attributes:
        _by_beatmap_id (dict[int, BeatmapsetSnapshot]): ビートマップIDからスナップショットを引く
            索引.
        _by_beatmapset_id (dict[int, BeatmapsetSnapshot]): ビートマップセットIDから
            スナップショットを引く索引.
        _checksum_to_beatmap_id (dict[str, int]): MD5チェックサムからビートマップIDを引く索引.
    """

    def __init__(self) -> None:
        """空の検索索引を初期化する."""
        self._by_beatmap_id: dict[int, BeatmapsetSnapshot] = {}
        self._by_beatmapset_id: dict[int, BeatmapsetSnapshot] = {}
        self._checksum_to_beatmap_id: dict[str, int] = {}

    def add_snapshot(self, snapshot: BeatmapsetSnapshot) -> None:
        """スナップショットを全検索索引へ事前登録する.

        Args:
            snapshot (BeatmapsetSnapshot): ビートマップセットと内包ビートマップを表す登録対象.

        Returns:
            None: 対応するビートマップセットID,ビートマップID,MD5チェックサムで検索可能にする.
        """
        self._by_beatmapset_id[snapshot.beatmapset_id] = snapshot
        for bm in snapshot.beatmaps:
            self._by_beatmap_id[bm.beatmap_id] = snapshot
            if bm.checksum_md5:
                self._checksum_to_beatmap_id[bm.checksum_md5] = bm.beatmap_id

    async def lookup_by_beatmap_id(self, beatmap_id: int) -> BeatmapsetSnapshot | None:
        """ビートマップIDに対応する登録済みスナップショットを取得する.

        Args:
            beatmap_id (int): 検索対象のビートマップID.

        Returns:
            BeatmapsetSnapshot | None: 登録済みのスナップショット. 該当IDがない場合は ``None``.
        """
        return self._by_beatmap_id.get(beatmap_id)

    async def lookup_by_beatmapset_id(self, beatmapset_id: int) -> BeatmapsetSnapshot | None:
        """ビートマップセットIDに対応する登録済みスナップショットを取得する.

        Args:
            beatmapset_id (int): 検索対象のビートマップセットID.

        Returns:
            BeatmapsetSnapshot | None: 登録済みのスナップショット. 該当IDがない場合は ``None``.
        """
        return self._by_beatmapset_id.get(beatmapset_id)

    async def lookup_by_checksum(self, checksum_md5: str) -> BeatmapsetSnapshot | None:
        """MD5チェックサムに対応する登録済みスナップショットを取得する.

        Args:
            checksum_md5 (str): 検索対象のビートマップMD5チェックサム.

        Returns:
            BeatmapsetSnapshot | None: 登録済みのスナップショット. 該当チェックサムがない場合は
                ``None``.
        """
        beatmap_id = self._checksum_to_beatmap_id.get(checksum_md5)
        if beatmap_id is None:
            return None
        return self._by_beatmap_id.get(beatmap_id)


class OsuApiMetadataProviderService:
    """OAuth認証付きの公式osu! API v2からメタデータを取得する.

    Attributes:
        _client_id (str): OAuth client credentialsのclient ID.
        _client_secret (str): OAuth client credentialsのclient secret.
        _base_url (str): API v2 endpointの末尾スラッシュを除いたURL.
        _token_url (str): OAuth token endpointのURL.
        _http_client (BeatmapHttpClient): HTTP clientを提供するinfrastructure adapter.
        _access_token (str | None): 有効期限内で再利用するBearer token.
        _token_expiry (float): cached tokenを再取得するUNIX時刻.
    """

    _client_id: str
    _client_secret: str
    _base_url: str
    _token_url: str
    _http_client: BeatmapHttpClient

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        http_client: BeatmapHttpClient,
        base_url: str = "https://osu.ppy.sh/api/v2",
        token_url: str = "https://osu.ppy.sh/oauth/token",
    ) -> None:
        """公式APIのOAuth credentialsとHTTP adapterを設定する.

        Args:
            client_id (str): OAuth token発行に使うclient ID.
            client_secret (str): OAuth token発行に使うclient secret.
            http_client (BeatmapHttpClient): token取得とAPI requestを実行するHTTP adapter.
            base_url (str): API v2 endpointのURL. 末尾の ``/`` は保存前に除去する.
            token_url (str): OAuth token endpointのURL.
        """
        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = base_url.rstrip("/")
        self._token_url = token_url
        self._http_client = http_client
        self._access_token: str | None = None
        self._token_expiry: float = 0.0

    async def lookup_by_beatmap_id(self, beatmap_id: int) -> BeatmapsetSnapshot | None:
        """公式APIからビートマップIDに対応するスナップショットを取得する.

        Args:
            beatmap_id (int): 検索対象のビートマップID.

        Returns:
            BeatmapsetSnapshot | None: 公式APIが返したスナップショット. HTTP 404の場合は ``None``.

        Raises:
            BeatmapSourceError: OAuth取得,HTTP request,またはresponse正規化に失敗した場合.
        """
        return await self._lookup(f"/beatmaps/{beatmap_id}", lookup_key=str(beatmap_id))

    async def lookup_by_beatmapset_id(self, beatmapset_id: int) -> BeatmapsetSnapshot | None:
        """公式APIからビートマップセットIDに対応するスナップショットを取得する.

        Args:
            beatmapset_id (int): 検索対象のビートマップセットID.

        Returns:
            BeatmapsetSnapshot | None: 公式APIが返したスナップショット. HTTP 404の場合は ``None``.

        Raises:
            BeatmapSourceError: OAuth取得,HTTP request,またはresponse正規化に失敗した場合.
        """
        return await self._lookup(f"/beatmapsets/{beatmapset_id}", lookup_key=str(beatmapset_id))

    async def lookup_by_checksum(self, checksum_md5: str) -> BeatmapsetSnapshot | None:
        """公式APIからMD5チェックサムに対応するスナップショットを取得する.

        Args:
            checksum_md5 (str): 検索対象のビートマップMD5チェックサム.

        Returns:
            BeatmapsetSnapshot | None: 公式APIが返したスナップショット. HTTP 404の場合は ``None``.

        Raises:
            BeatmapSourceError: OAuth取得,HTTP request,またはresponse正規化に失敗した場合.
        """
        return await self._lookup(
            f"/beatmaps/lookup?checksum={checksum_md5}",
            lookup_key=checksum_md5,
        )

    async def _lookup(self, path: str, *, lookup_key: str) -> BeatmapsetSnapshot | None:
        """OAuth tokenを付けて公式APIのmetadata endpointを照会する.

        Args:
            path (str): base URLに連結するAPI v2のrelative path.
            lookup_key (str): エラーと構造化logへ記録する検索値.

        Returns:
            BeatmapsetSnapshot | None: JSONを変換したスナップショット. HTTP 404の場合は ``None``.

        Raises:
            BeatmapSourceError: token取得,request,JSON形式,またはHTTP statusが正常でない場合.
        """
        source_label = "osu_api_v2"
        token = await self._get_token()
        url = f"{self._base_url}{path}"

        client = self._http_client.get_client()
        try:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
        except httpx.TimeoutException as exc:
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.TIMEOUT,
                source=source_label,
                lookup_key=lookup_key,
                message=f"Request failed: {exc}",
                original_error=exc,
            ) from exc
        except Exception as exc:
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE,
                source=source_label,
                lookup_key=lookup_key,
                message=f"Request failed: {exc}",
                original_error=exc,
            ) from exc

        if response.status_code == HTTPStatus.OK:
            try:
                parsed: object = response.json()
            except Exception as exc:
                raise BeatmapSourceError(
                    category=BeatmapSourceErrorCategory.INVALID_RESPONSE,
                    source=source_label,
                    lookup_key=lookup_key,
                    message=f"Invalid JSON from {source_label}",
                    original_error=exc,
                ) from exc
            if not isinstance(parsed, dict):
                actual = type(parsed).__name__
                raise BeatmapSourceError(
                    category=BeatmapSourceErrorCategory.INVALID_RESPONSE,
                    source=source_label,
                    lookup_key=lookup_key,
                    message=f"Expected JSON object from {source_label}, got {actual}",
                )
            return beatmap_json_to_snapshot(cast("dict[str, object]", parsed))

        if response.status_code == HTTPStatus.NOT_FOUND:
            return None

        if response.status_code == HTTPStatus.UNAUTHORIZED:
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.UNAUTHORIZED,
                source=source_label,
                lookup_key=lookup_key,
                message=f"HTTP {response.status_code} from {source_label}",
            )

        if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.RATE_LIMITED,
                source=source_label,
                lookup_key=lookup_key,
                message=f"HTTP {response.status_code} from {source_label}",
            )

        if 500 <= response.status_code < 600:  # noqa: PLR2004
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE,
                source=source_label,
                lookup_key=lookup_key,
                message=f"HTTP {response.status_code} from {source_label}",
            )

        raise BeatmapSourceError(
            category=BeatmapSourceErrorCategory.INVALID_RESPONSE,
            source=source_label,
            lookup_key=lookup_key,
            message=f"HTTP {response.status_code} from {source_label}",
        )

    async def _get_token(self) -> str:
        """有効なOAuth access tokenを返し,必要なら再取得する.

        Returns:
            str: 公式API requestのBearer認証に使うaccess token.

        Raises:
            BeatmapSourceError: token endpointのrequest,JSON形式,認証,またはstatusが不正な場合.

        Notes:
            cached tokenは現在時刻が ``expires_in - 60`` 秒で計算した有効期限より前だけ再利用する.
        """
        if self._access_token and time.time() < self._token_expiry:
            return self._access_token

        source_label = "osu_oauth"
        client = self._http_client.get_client()

        try:
            response = await client.post(
                self._token_url,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "client_credentials",
                    "scope": "public",
                },
            )
        except httpx.TimeoutException as exc:
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.TIMEOUT,
                source=source_label,
                lookup_key="token",
                message=f"Token request timeout: {exc}",
                original_error=exc,
            ) from exc
        except Exception as exc:
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE,
                source=source_label,
                lookup_key="token",
                message=f"Token request failed: {exc}",
                original_error=exc,
            ) from exc

        if response.status_code == HTTPStatus.UNAUTHORIZED:
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.UNAUTHORIZED,
                source=source_label,
                lookup_key="token",
                message=f"Token endpoint returned {response.status_code}",
            )

        if 500 <= response.status_code < 600:  # noqa: PLR2004
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE,
                source=source_label,
                lookup_key="token",
                message=f"Token endpoint returned {response.status_code}",
            )

        if response.status_code != HTTPStatus.OK:
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.INVALID_RESPONSE,
                source=source_label,
                lookup_key="token",
                message=f"Token endpoint returned {response.status_code}",
            )

        try:
            parsed: object = response.json()
        except Exception as exc:
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.INVALID_RESPONSE,
                source=source_label,
                lookup_key="token",
                message=f"Invalid JSON from token endpoint: {exc}",
                original_error=exc,
            ) from exc

        if not isinstance(parsed, dict):
            actual = type(parsed).__name__
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.INVALID_RESPONSE,
                source=source_label,
                lookup_key="token",
                message=f"Expected JSON object from token endpoint, got {actual}",
            )
        data = cast("Mapping[str, object]", parsed)

        access_token = data.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.INVALID_RESPONSE,
                source=source_label,
                lookup_key="token",
                message="Token response missing valid access_token",
            )

        expires_in = data.get("expires_in", 86400)
        try:
            expires_seconds = float(cast("int | float | str", expires_in))
        except (TypeError, ValueError) as exc:
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.INVALID_RESPONSE,
                source=source_label,
                lookup_key="token",
                message="Token response has invalid expires_in",
                original_error=exc,
            ) from exc

        self._access_token = access_token
        self._token_expiry = time.time() + expires_seconds - 60
        return self._access_token


def _source_label(base_url: str) -> str:
    """入力URLから構造化logとerror用のsource labelを作る.

    Args:
        base_url (str): mirror APIのbase URL.

    Returns:
        str: hostnameを含む ``mirror[...]`` 形式のlabel. hostnameを取得できない場合は入力URLを使う.
    """
    hostname = urlparse(base_url).hostname or base_url
    return f"mirror[{hostname}]"


def _is_nerinyan_url(base_url: str) -> bool:
    """URLがNerinyan互換endpointを指すか判定する.

    Args:
        base_url (str): 判定対象のmirror API base URL.

    Returns:
        bool: hostnameに大文字小文字を区別せず ``nerinyan`` を含む場合は ``True``.
    """
    hostname = urlparse(base_url).hostname
    return hostname is not None and "nerinyan" in hostname.lower()


class MirrorMetadataProviderService:
    """community mirrorからメタデータを設定順に取得する.

    Attributes:
        _base_urls (tuple[str, ...]): 空白と末尾スラッシュを除去した照会順のmirror URL群.
        _api_version (str): Nerinyan以外のmirror URLへ連結するAPI version.
        _http_client (BeatmapHttpClient): JSON requestを実行するHTTP adapter.
    """

    _base_urls: tuple[str, ...]
    _api_version: str
    _http_client: BeatmapHttpClient

    def __init__(
        self,
        *,
        http_client: BeatmapHttpClient,
        base_url: str | None = None,
        base_urls: Sequence[str] | None = None,
        api_version: str = "v2",
    ) -> None:
        """Mirror URL群とHTTP adapterを設定する.

        Args:
            http_client (BeatmapHttpClient): mirrorへのJSON requestを実行するHTTP adapter.
            base_url (str | None): 単一の追加mirror URL. ``base_urls`` 指定時は末尾に追加する.
            base_urls (Sequence[str] | None): 優先順で照会するmirror URL群.
            api_version (str): Nerinyan以外のmirror URLへ連結するAPI version.
        """
        self._base_urls = _normalize_base_urls(base_url=base_url, base_urls=base_urls)
        self._api_version = api_version
        self._http_client = http_client

    async def lookup_by_beatmap_id(self, beatmap_id: int) -> BeatmapsetSnapshot | None:
        """Community mirrorからビートマップIDに対応するスナップショットを取得する.

        Args:
            beatmap_id (int): 検索対象のビートマップID.

        Returns:
            BeatmapsetSnapshot | None: 最初に成功したmirrorのスナップショット. URL未設定または
                全mirrorが未検出なら
                ``None``.

        Raises:
            BeatmapSourceError: 未検出以外の最後のmirror errorにより全mirrorが失敗した場合.
        """
        return await self._lookup(
            f"/b/{beatmap_id}",
            lookup_key=str(beatmap_id),
            nerinyan_params={"b": str(beatmap_id)},
        )

    async def lookup_by_beatmapset_id(self, beatmapset_id: int) -> BeatmapsetSnapshot | None:
        """Community mirrorからビートマップセットIDに対応するスナップショットを取得する.

        Args:
            beatmapset_id (int): 検索対象のビートマップセットID.

        Returns:
            BeatmapsetSnapshot | None: 最初に成功したmirrorのスナップショット. URL未設定または
                全mirrorが未検出なら
                ``None``.

        Raises:
            BeatmapSourceError: 未検出以外の最後のmirror errorにより全mirrorが失敗した場合.
        """
        return await self._lookup(
            f"/s/{beatmapset_id}",
            lookup_key=str(beatmapset_id),
            nerinyan_params={"s": str(beatmapset_id)},
        )

    async def lookup_by_checksum(self, checksum_md5: str) -> BeatmapsetSnapshot | None:
        """Community mirrorからMD5チェックサムに対応するスナップショットを取得する.

        Args:
            checksum_md5 (str): 検索対象のビートマップMD5チェックサム.

        Returns:
            BeatmapsetSnapshot | None: 最初に成功したmirrorのスナップショット. URL未設定または
                全mirrorが未検出なら
                ``None``.

        Raises:
            BeatmapSourceError: 未検出以外の最後のmirror errorにより全mirrorが失敗した場合.
        """
        return await self._lookup(
            f"/hash/{checksum_md5}",
            lookup_key=checksum_md5,
            nerinyan_params={"h": checksum_md5},
        )

    async def _lookup(
        self,
        path: str,
        *,
        lookup_key: str,
        nerinyan_params: Mapping[str, str],
    ) -> BeatmapsetSnapshot | None:
        """設定順にmirror endpointを照会して最初の有効なレスポンスを変換する.

        Args:
            path (str): Nerinyan以外のmirror URLへ連結するrelative path.
            lookup_key (str): HTTP adapterと生成するerrorへ渡す検索値.
            nerinyan_params (Mapping[str, str]): Nerinyan endpointへ渡すquery parameter.

        Returns:
            BeatmapsetSnapshot | None: 最初に変換できたスナップショット. URL未設定または全sourceが
                未検出なら
                ``None``.

        Raises:
            BeatmapSourceError: 未検出以外の最後のsource error,または不正JSONを全sourceで
                解決できない場合.
        """
        if not self._base_urls:
            return None

        last_error: BeatmapSourceError | None = None
        for base_url in self._base_urls:
            source_label = _source_label(base_url)
            is_nerinyan = _is_nerinyan_url(base_url)
            url = (
                f"{base_url}/v1/get_beatmaps?{urlencode(nerinyan_params)}"
                if is_nerinyan
                else f"{base_url}/{self._api_version}{path}"
            )
            try:
                data = await self._http_client.fetch_json(
                    url,
                    source=source_label,
                    lookup_key=lookup_key,
                )
            except BeatmapSourceError as exc:
                if exc.category == BeatmapSourceErrorCategory.NOT_FOUND:
                    continue
                last_error = exc
                continue

            if is_nerinyan and isinstance(data, list):
                return beatmap_v1_json_to_snapshot(
                    cast("Sequence[Mapping[str, object]]", data),
                    source=BeatmapMetadataSource.MIRROR,
                    verification=BeatmapSourceVerification.UNVERIFIED,
                )

            if isinstance(data, dict):
                data_dict: dict[str, object] = data
                if is_nerinyan:
                    return beatmap_v1_json_to_snapshot(
                        [data_dict],
                        source=BeatmapMetadataSource.MIRROR,
                        verification=BeatmapSourceVerification.UNVERIFIED,
                    )
                return beatmap_json_to_snapshot(
                    data_dict,
                    source=BeatmapMetadataSource.MIRROR,
                    verification=BeatmapSourceVerification.UNVERIFIED,
                )

            last_error = BeatmapSourceError(
                category=BeatmapSourceErrorCategory.INVALID_RESPONSE,
                source=source_label,
                lookup_key=lookup_key,
                message=f"Unexpected JSON from {source_label}",
            )

        if last_error is not None:
            raise last_error
        return None


def _normalize_base_urls(
    *,
    base_url: str | None,
    base_urls: Sequence[str] | None,
) -> tuple[str, ...]:
    """単一URLとURL列を照会順を保った正規化済みtupleへ変換する.

    Args:
        base_url (str | None): ``base_urls`` の後ろへ追加する単一URL.
        base_urls (Sequence[str] | None): 優先順で受け取るURL列.

    Returns:
        tuple[str, ...]: 前後空白と末尾 ``/`` を除去し,空文字を除外したURL列.
    """
    raw_urls: Sequence[str]
    if base_urls is not None:
        raw_urls = base_urls if base_url is None else (*base_urls, base_url)
    elif base_url is not None:
        raw_urls = (base_url,)
    else:
        raw_urls = ()

    return tuple(normalized for url in raw_urls if (normalized := url.strip().rstrip("/")))
