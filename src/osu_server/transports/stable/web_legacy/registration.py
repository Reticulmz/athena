"""RegistrationHandler — POST /users handler for osu! stable account registration.

The osu! stable client sends form-encoded data to ``POST /users`` on ``osu.$DOMAIN``.
Fields: ``user[username]``, ``user[user_email]``, ``user[password]``, ``check``.

- ``check=1``: validate only (real-time validation while the user types)
- ``check=0``: validate and create the account
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from starlette.responses import Response

from osu_server.domain.identity.authentication import RegistrationForm
from osu_server.services.commands.identity import RegisterUserCommandInput

if TYPE_CHECKING:
    from starlette.requests import Request

    from osu_server.services.commands.identity import RegisterUserCommand

_log = logging.getLogger(__name__)


class RegistrationHandler:
    """Starlette handler for ``POST /users``.

    Receives DI dependencies in ``__init__`` and acts as a callable ASGI
    endpoint via ``__call__``.
    """

    _register_user_command: RegisterUserCommand

    def __init__(self, *, register_user_command: RegisterUserCommand) -> None:
        self._register_user_command = register_user_command

    async def __call__(self, request: Request) -> Response:
        """Parse form data and execute the registration command use-case."""
        async with request.form() as form_data:
            username = str(form_data.get("user[username]", ""))
            email = str(form_data.get("user[user_email]", ""))
            password = str(form_data.get("user[password]", ""))
            check = str(form_data.get("check", "0"))

        check_only = check == "1"

        registration_form = RegistrationForm(
            username=username,
            email=email,
            password=password,
        )

        command_result = await self._register_user_command.execute(
            RegisterUserCommandInput(
                form_data=registration_form,
                check_only=check_only,
            ),
        )
        result = command_result.outcome

        if result.success:
            return Response(content=b"ok", status_code=200)

        error_body = json.dumps({"form_error": {"user": result.errors}})
        return Response(
            content=error_body.encode(),
            status_code=400,
            media_type="application/json",
        )
