"""Replay domain model."""

from dataclasses import dataclass


@dataclass(slots=True)
class Replay:
    """Replay domain model for replay binary storage."""

    id: int | None
    score_id: int
    blob_key: str
    checksum_sha256: str
    byte_size: int
