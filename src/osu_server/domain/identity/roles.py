"""Role model for the identity bounded context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.identity.authorization import Privileges


@dataclass(slots=True)
class Role:
    id: int
    name: str
    permissions: Privileges
    position: int
