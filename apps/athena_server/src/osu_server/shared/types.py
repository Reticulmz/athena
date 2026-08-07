"""複数の境界で意味を区別する共有の NewType を定義する."""

from typing import NewType

UserId = NewType("UserId", int)
Token = NewType("Token", str)
