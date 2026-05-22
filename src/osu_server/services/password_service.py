from __future__ import annotations

import asyncio
import hashlib

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError


class PasswordService:
    """パスワードのハッシュと検証を担当するサービス。

    argon2-cffi の PasswordHasher は CPU バウンドでイベントループをブロックするため、
    全操作を ``run_in_executor`` で非同期化する。
    """

    def __init__(self) -> None:
        self._hasher: PasswordHasher = PasswordHasher()

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
            return False

    async def prepare_password(self, plain_password: str) -> str:
        """平文 → MD5 → argon2id。登録時に使用。"""
        md5_hex = hashlib.md5(plain_password.encode()).hexdigest()
        return await self.hash(md5_hex)
