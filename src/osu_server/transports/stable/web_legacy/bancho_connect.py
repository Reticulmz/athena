"""GET /web/bancho_connect.php — osu! stable login handshake.

osu! stable sends ``GET /web/bancho_connect.php?v=...&u=...&h=...&fail=...``
before the bancho login POST. The ``u`` (username) and ``h`` (password md5)
parameters are validated by the subsequent bancho login flow; this endpoint
only confirms the server is reachable.

Reference implementations:
- `lets`_ validates credentials here and returns the country code or
  ``"error: pass\\n"``.
- `bancho.py`_ declares parameters but returns an empty response (auth
  dependency is commented out).

.. _lets: https://github.com/osuripple/lets/blob/master/handlers/banchoConnectHandler.py
.. _bancho.py: https://github.com/osuAkatsuki/bancho.py/blob/master/app/api/domains/osu.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.responses import Response

if TYPE_CHECKING:
    from starlette.requests import Request


async def bancho_connect_endpoint(request: Request) -> Response:
    _username = request.query_params.get("u")
    _password_md5 = request.query_params.get("h")
    _osu_version = request.query_params.get("v")
    _active_endpoint = request.query_params.get("fail")
    # Future: validate credentials here as lets does.
    # Currently delegated to the bancho login POST flow.
    return Response(b"")
