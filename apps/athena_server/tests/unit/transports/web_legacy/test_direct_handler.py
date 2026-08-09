"""Stable osu!direct handlerの認証とquery委譲契約を検証するmodule."""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

from osu_server.domain.beatmaps import DirectAccessDecision, DirectPointLookupTargetKind
from osu_server.services.queries.beatmaps import (
    DirectPointLookupQueryResult,
    DirectSearchQueryResult,
)
from osu_server.transports.stable.web_legacy.direct import (
    StableDirectPointLookupHandler,
    StableDirectSearchHandler,
)
from osu_server.transports.stable.web_legacy.direct_access import StableDirectAccessResult
from osu_server.transports.stable.web_legacy.mappers import (
    StableDirectPointLookupQueryParser,
    StableDirectSearchQueryParser,
)
from tests.support.starlette_requests import make_starlette_request

if TYPE_CHECKING:
    from collections.abc import Mapping

    from osu_server.domain.beatmaps import DirectPointLookupRequest, DirectSearchRequest
    from osu_server.services.queries.beatmaps import DirectPointLookupQuery, DirectSearchQuery
    from osu_server.transports.stable.web_legacy.direct_access import StableDirectAccessGate


@dataclass(slots=True)
class _DirectAccessGateFake:
    """Direct handler test用に固定access resultを返すgate fake.

    Attributes:
        result (StableDirectAccessResult): authorizeが返す固定結果.
        queries (list[dict[str, str]]): authorizeへ渡されたquery parameter.
    """

    result: StableDirectAccessResult
    queries: list[dict[str, str]]

    async def authorize(self, query: Mapping[str, str]) -> StableDirectAccessResult:
        """Query parameterを記録して固定access resultを返す.

        Args:
            query (Mapping[str, str]): stable direct requestのquery parameter.

        Returns:
            StableDirectAccessResult: testごとに指定したaccess result.
        """
        self.queries.append(dict(query))
        return self.result


@dataclass(slots=True)
class _DirectSearchQueryFake:
    """Direct search handler test用に固定検索結果を返すquery fake.

    Attributes:
        result (DirectSearchQueryResult): executeが返す固定結果.
        requests (list[DirectSearchRequest]): executeへ渡されたrequest.
    """

    result: DirectSearchQueryResult
    requests: list[DirectSearchRequest]

    async def execute(self, request: DirectSearchRequest) -> DirectSearchQueryResult:
        """Direct search requestを記録して固定結果を返す.

        Args:
            request (DirectSearchRequest): handlerがparseした検索request.

        Returns:
            DirectSearchQueryResult: formatterへ渡す固定検索結果.
        """
        self.requests.append(request)
        return self.result


@dataclass(slots=True)
class _DirectPointLookupQueryFake:
    """Direct point lookup handler test用に固定lookup結果を返すquery fake.

    Attributes:
        result (DirectPointLookupQueryResult): executeが返す固定結果.
        requests (list[DirectPointLookupRequest]): executeへ渡されたrequest.
    """

    result: DirectPointLookupQueryResult
    requests: list[DirectPointLookupRequest]

    async def execute(
        self,
        request: DirectPointLookupRequest,
    ) -> DirectPointLookupQueryResult:
        """Direct point lookup requestを記録して固定結果を返す.

        Args:
            request (DirectPointLookupRequest): handlerがparseしたlookup request.

        Returns:
            DirectPointLookupQueryResult: formatterへ渡す固定lookup結果.
        """
        self.requests.append(request)
        return self.result


async def test_direct_search_handler_rejects_auth_failure_before_query() -> None:
    """認証失敗時にdirect search handlerがcatalog queryを呼ばない契約を検証する.

    Returns:
        None: 空bodyのHTTP 401とquery未呼出しを確認して完了する.
    """
    query = _DirectSearchQueryFake(DirectSearchQueryResult((), 0), [])
    handler = StableDirectSearchHandler(
        access_gate=cast(
            "StableDirectAccessGate",
            cast(
                "object",
                _DirectAccessGateFake(
                    StableDirectAccessResult(DirectAccessDecision.AUTHENTICATION_REQUIRED),
                    [],
                ),
            ),
        ),
        search_parser=StableDirectSearchQueryParser(),
        search_query=cast("DirectSearchQuery", cast("object", query)),
    )

    response = await handler(make_starlette_request(path="/web/osu-search.php"))

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.body == b""
    assert query.requests == []


async def test_direct_search_handler_executes_parsed_query_for_authorized_user() -> None:
    """認証済みdirect search requestがparse済みquery use-caseへ渡る契約を検証する.

    Returns:
        None: stable query parameterからsearch requestを作りcount responseを返すことを確認する.
    """
    query = _DirectSearchQueryFake(DirectSearchQueryResult((), 0), [])
    handler = StableDirectSearchHandler(
        access_gate=cast(
            "StableDirectAccessGate",
            cast(
                "object",
                _DirectAccessGateFake(
                    StableDirectAccessResult(
                        DirectAccessDecision.ALLOWED,
                        authenticated_user_id=42,
                    ),
                    [],
                ),
            ),
        ),
        search_parser=StableDirectSearchQueryParser(),
        search_query=cast("DirectSearchQuery", cast("object", query)),
    )

    response = await handler(
        make_starlette_request(
            path="/web/osu-search.php",
            query_params={"u": "Player", "h": "hash", "q": "Camellia", "r": "4"},
        )
    )

    assert response.status_code == HTTPStatus.OK
    assert response.body == b"0"
    assert len(query.requests) == 1
    assert query.requests[0].authenticated_user_id == 42
    assert query.requests[0].query_text == "Camellia"


async def test_direct_point_lookup_handler_executes_parsed_lookup_for_authorized_user() -> None:
    """認証済みpoint lookup requestがparse済みlookup use-caseへ渡る契約を検証する.

    Returns:
        None: s parameterからpoint lookup requestを作り空body responseを返すことを確認する.
    """
    query = _DirectPointLookupQueryFake(DirectPointLookupQueryResult(None), [])
    handler = StableDirectPointLookupHandler(
        access_gate=cast(
            "StableDirectAccessGate",
            cast(
                "object",
                _DirectAccessGateFake(
                    StableDirectAccessResult(
                        DirectAccessDecision.ALLOWED,
                        authenticated_user_id=42,
                    ),
                    [],
                ),
            ),
        ),
        point_lookup_parser=StableDirectPointLookupQueryParser(),
        point_lookup_query=cast("DirectPointLookupQuery", cast("object", query)),
    )

    response = await handler(
        make_starlette_request(
            path="/web/osu-search-set.php",
            query_params={"u": "Player", "h": "hash", "s": "123"},
        )
    )

    assert response.status_code == HTTPStatus.OK
    assert response.body == b""
    assert len(query.requests) == 1
    assert query.requests[0].authenticated_user_id == 42
    assert query.requests[0].target_kind is DirectPointLookupTargetKind.BEATMAPSET_ID
    assert query.requests[0].target_value == 123
