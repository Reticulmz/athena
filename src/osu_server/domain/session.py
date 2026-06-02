from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SessionData:
    user_id: int
    username: str
    privileges: int
    country: str
    osu_version: str
    utc_offset: int
    display_city: bool
    client_hashes: str
    pm_private: bool
    role_ids: tuple[int, ...] = ()
    silence_end: int = 0

    def __post_init__(self) -> None:
        self.role_ids = tuple(self.role_ids)
