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
    silence_end: int = 0
