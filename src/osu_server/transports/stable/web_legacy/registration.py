"""Stable clientのlegacy account registration endpointを提供する.

`check=1`は入力検証だけを行い, `check=0`は検証後にaccountを作成する.
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
    """`POST /users`をregistration commandへ適合させるhandler.

    Attributes:
        _register_user_command (RegisterUserCommand): 入力を検証しaccountを作成するcommand.
    """

    _register_user_command: RegisterUserCommand

    def __init__(self, *, register_user_command: RegisterUserCommand) -> None:
        """Registration commandをhandlerへ設定する.

        Args:
            register_user_command (RegisterUserCommand): account登録または入力検証を行うcommand.
        """
        self._register_user_command = register_user_command

    async def __call__(self, request: Request) -> Response:
        """Form requestをregistration commandへ渡してstable responseへ変換する.

        Args:
            request (Request): stable clientから届いたform-encoded POST request.

        Returns:
            Response: 成功時は`ok`のHTTP 200, 検証失敗時はform_errorを持つHTTP 400 response.
        """
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
