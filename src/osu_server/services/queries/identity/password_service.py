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

_MD5_HEX_LENGTH = 32
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


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
        """ハッシュ照合。VerifyMismatchError -> False。

        Stable auth の password は MD5 hex credential として届くため、
        32文字の hex 値は大小文字差を認証差にしない。
        """
        loop = asyncio.get_running_loop()
        password = _normalize_legacy_md5_hex(password)
        try:
            return await loop.run_in_executor(None, self._hasher.verify, hashed, password)
        except VerifyMismatchError:
            logger.warning("password_verification_failed", reason="hash_mismatch")
            return False

    async def prepare_password(self, plain_password: str) -> str:
        """平文 password を legacy MD5 hex に変換してから argon2id で hash する.

        引数:
            plain_password: 登録フォームから受け取った平文 password.

        戻り値:
            Legacy stable auth 互換の MD5 hex を argon2id で hash した文字列.

        例外:
            argon2-cffi の hash 処理が失敗した場合は実装依存の例外を送出する.

        制約:
            MD5 は password 保存用途ではなく Stable client 互換入力への変換だけに使う.
            永続化される値は argon2id hash であり, 平文 password と MD5 hex は返さない.
        """
        md5_hex = self.legacy_plaintext_md5(plain_password)
        return await self.hash(md5_hex)

    def legacy_plaintext_md5(self, plain_password: str) -> str:
        """Stable legacy auth 互換の平文 password MD5 hex を返す.

        引数:
            plain_password: ユーザーが入力した平文 password.

        戻り値:
            Stable legacy auth で使う lowercase MD5 hex 文字列.

        例外:
            なし.

        制約:
            MD5 は互換プロトコル値の再現だけに使う. 新しい password 保存や
            authorization policy の hash 方式として扱わない.
        """
        return hashlib.md5(plain_password.encode(), usedforsecurity=False).hexdigest()

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


def _normalize_legacy_md5_hex(value: str) -> str:
    """MD5 hex credential だけを lowercase に正規化する."""
    if len(value) != _MD5_HEX_LENGTH:
        return value
    if any(character not in _HEX_DIGITS for character in value):
        return value
    return value.lower()
