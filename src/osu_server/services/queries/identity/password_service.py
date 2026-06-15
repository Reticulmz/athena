from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING

import structlog
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

if TYPE_CHECKING:
    from osu_server.infrastructure.security.hibp import HIBPClient

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class PasswordService:
    """パスワードのハッシュと検証を担当するサービス。

    argon2-cffi の PasswordHasher は CPU バウンドでイベントループをブロックするため、
    全操作を ``run_in_executor`` で非同期化する。

    HIBP チェックとカスタム禁止パスワードリストによるセキュリティ強化を提供する。
    """

    def __init__(
        self,
        hibp_client: HIBPClient | None = None,
        banned_passwords: list[str] | None = None,
    ) -> None:
        self._hasher: PasswordHasher = PasswordHasher()
        self._hibp_client: HIBPClient | None = hibp_client
        self._banned_passwords: frozenset[str] = frozenset(
            p.lower() for p in (banned_passwords or [])
        )

    async def hash(self, password: str) -> str:
        """argon2id でハッシュ。run_in_executor で非同期化。"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._hasher.hash, password)

    async def verify(self, hashed: str, password: str) -> bool:
        """ハッシュ照合。VerifyMismatchError → False。"""
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, self._hasher.verify, hashed, password)
        except VerifyMismatchError:
            logger.warning("password_verification_failed", reason="hash_mismatch")
            return False

    async def prepare_password(self, plain_password: str) -> str:
        """平文 → MD5 → argon2id。登録時に使用。"""
        md5_hex = hashlib.md5(plain_password.encode()).hexdigest()
        return await self.hash(md5_hex)

    async def check_hibp(self, password: str) -> bool:
        """HIBP で漏洩パスワードか判定する。

        HIBPClient が未設定の場合は False を返す。

        Args:
            password: 平文パスワード。

        Returns:
            True なら漏洩済み。クライアント未設定時は False。
        """
        if self._hibp_client is None:
            return False
        return await self._hibp_client.is_password_compromised(password)

    async def is_password_banned(self, password: str) -> bool:
        """カスタム禁止リスト + HIBP の統合チェック。

        カスタムリストを先にチェック(高速)し、一致すれば即 True を返す。
        カスタムリストに無ければ HIBP をチェックする。

        Args:
            password: 平文パスワード。

        Returns:
            True ならパスワードは使用禁止。
        """
        if password.lower() in self._banned_passwords:
            logger.warning("password_banned", source="custom_list")
            return True
        is_compromised = await self.check_hibp(password)
        if is_compromised:
            logger.warning("password_banned", source="hibp")
        return is_compromised
