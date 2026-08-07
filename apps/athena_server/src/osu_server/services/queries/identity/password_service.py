"""Password hash, verification, and banned-password query serviceを提供するmodule.

stable client互換のMD5 credentialをargon2id hashと照合し, optional HIBP確認をread-onlyで行う.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING

import structlog
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from osu_server.domain.identity.passwords import normalize_legacy_md5_hex

if TYPE_CHECKING:
    from osu_server.infrastructure.security.hibp import HIBPClient

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class PasswordService:
    """passwordのhash化, credential照合, banned-password確認を提供するservice.

    Attributes:
        _hasher (PasswordHasher): password hash化と照合を行うargon2id hasher.
        _hibp_client (HIBPClient | None): 漏洩passwordを確認するoptional HIBP client.
        _banned_passwords (frozenset[str]): lowercase化したcustom banned password集合.

    Notes:
        PasswordHasherのCPU-bound操作はrun_in_executorで実行し,event loopをblockしない.
    """

    def __init__(
        self,
        hibp_client: HIBPClient | None = None,
        banned_passwords: list[str] | None = None,
    ) -> None:
        """argon2id hasherとoptional password policy dependencyを初期化する.

        Args:
            hibp_client (HIBPClient | None): 漏洩passwordを確認するclient. 無効化する場合はNone.
            banned_passwords (list[str] | None): lowercase比較用に登録するcustom banned password群.

        Notes:
            banned_passwordsは初期化時にlowercaseのfrozensetへ正規化する.
        """
        self._hasher: PasswordHasher = PasswordHasher()
        self._hibp_client: HIBPClient | None = hibp_client
        self._banned_passwords: frozenset[str] = frozenset(
            p.lower() for p in (banned_passwords or [])
        )

    async def hash(self, password: str) -> str:
        """入力password credentialをargon2id hashへ変換する.

        Args:
            password (str): hash化するpasswordまたはstable互換MD5 credential.

        Returns:
            str: argon2id形式のpassword hash.

        Notes:
            CPU-bound hash操作はevent loop外で実行する.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._hasher.hash, password)

    async def verify(self, hashed: str, password: str) -> bool:
        """argon2id hashとpassword credentialを照合する.

        Args:
            hashed (str): 保存済みpassword hash.
            password (str): 照合対象のpassword credential. stable authの32文字MD5 hexは
                大文字小文字を認証差にしない.

        Returns:
            bool: credentialが一致する場合はTrue. VerifyMismatchErrorの場合はFalse.

        Notes:
            CPU-bound verify操作はevent loop外で実行する.
        """
        loop = asyncio.get_running_loop()
        password = normalize_legacy_md5_hex(password)
        try:
            return await loop.run_in_executor(None, self._hasher.verify, hashed, password)
        except VerifyMismatchError:
            logger.warning("password_verification_failed", reason="hash_mismatch")
            return False

    async def prepare_password(self, plain_password: str) -> str:
        """平文passwordをstable互換MD5 credentialへ変換してargon2id hash化する.

        Args:
            plain_password (str): 登録formから受け取ったplain password.

        Returns:
            str: stable auth互換MD5 credentialをargon2id hash化した保存用文字列.

        Notes:
            MD5はstable client互換inputへの変換だけに使う. 永続化される値はargon2id hashであり,
            plain passwordとMD5 credentialは返さない.
        """
        md5_hex = self.legacy_plaintext_md5(plain_password)
        return await self.hash(md5_hex)

    def legacy_plaintext_md5(self, plain_password: str) -> str:
        """Stable legacy auth互換のplain password MD5 hexを返す.

        Args:
            plain_password (str): userが入力したplain password.

        Returns:
            str: stable legacy authで使うlowercase MD5 hex文字列.

        Notes:
            MD5は互換protocol値の再現だけに使う. 新しいpassword保存やauthorization policyの
            hash方式として扱わない.
        """
        return hashlib.md5(plain_password.encode(), usedforsecurity=False).hexdigest()

    async def check_hibp(self, password: str) -> bool:
        """HIBPでpasswordが漏洩済みかを確認する.

        Args:
            password (str): HIBPへ照会するplain password.

        Returns:
            bool: passwordが漏洩済みの場合はTrue. HIBP client未設定時はFalse.

        Notes:
            HIBPClientが未設定の場合はnetwork照会を行わずFalseを返す.
        """
        if self._hibp_client is None:
            return False
        return await self._hibp_client.is_password_compromised(password)

    async def is_password_banned(self, password: str) -> bool:
        """Custom banned password集合とHIBPを統合してpassword禁止状態を確認する.

        Args:
            password (str): custom listとHIBPへ照合するplain password.

        Returns:
            bool: custom listまたはHIBPがpasswordを禁止と判定する場合はTrue.

        Notes:
            custom listを先に照合し, 一致した場合はHIBPを呼ばない.
        """
        if password.lower() in self._banned_passwords:
            logger.warning("password_banned", source="custom_list")
            return True
        is_compromised = await self.check_hibp(password)
        if is_compromised:
            logger.warning("password_banned", source="hibp")
        return is_compromised
