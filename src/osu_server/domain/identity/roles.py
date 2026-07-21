"""Identity context の role model を定義する module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.identity.authorization import Privileges


@dataclass(slots=True)
class Role:
    """User へ privilege bundle を付与する named authorization role を表す value object.

    Attributes:
        id (int): 永続化された role ID.
        name (str): 管理画面などで表示する role 名.
        permissions (Privileges): role が付与する privilege bit flag の組合せ.
        position (int): role を並べる際に使う優先順位.
    """

    id: int
    name: str
    permissions: Privileges
    position: int
