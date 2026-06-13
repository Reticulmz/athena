"""Shared in-memory command repository state."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import (
        Beatmap,
        BeatmapFetchRecord,
        BeatmapFetchTarget,
        BeatmapFileAttachment,
        BeatmapSet,
    )
    from osu_server.domain.chat.channels import Channel, ChannelRoleOverride
    from osu_server.domain.identity.roles import Role
    from osu_server.domain.identity.users import User
    from osu_server.domain.scores.replay import Replay
    from osu_server.domain.scores.score import Score
    from osu_server.domain.scores.submission import ScoreSubmission
    from osu_server.domain.storage.blobs import Blob


@dataclass(slots=True)
class InMemoryCommandRepositoryState:
    """Mutable state snapshot used by one in-memory command transaction."""

    users_by_id: dict[int, User] = field(default_factory=dict)
    user_id_by_safe_username: dict[str, int] = field(default_factory=dict)
    user_id_by_email: dict[str, int] = field(default_factory=dict)
    disallowed_usernames: set[str] = field(default_factory=set)
    next_user_id: int = 1

    roles_by_id: dict[int, Role] = field(default_factory=dict)
    role_id_by_name: dict[str, int] = field(default_factory=dict)
    role_ids_by_user_id: dict[int, set[int]] = field(default_factory=dict)

    channels_by_id: dict[int, Channel] = field(default_factory=dict)
    channel_id_by_name: dict[str, int] = field(default_factory=dict)
    channel_overrides_by_channel_id: dict[int, list[ChannelRoleOverride]] = field(
        default_factory=dict
    )
    next_channel_id: int = 1

    scores_by_id: dict[int, Score] = field(default_factory=dict)
    score_id_by_online_checksum: dict[str, int] = field(default_factory=dict)
    next_score_id: int = 1

    submissions_by_id: dict[int, ScoreSubmission] = field(default_factory=dict)
    submission_id_by_fingerprint: dict[str, int] = field(default_factory=dict)
    next_submission_id: int = 1

    replays_by_id: dict[int, Replay] = field(default_factory=dict)
    replay_id_by_checksum: dict[str, int] = field(default_factory=dict)
    next_replay_id: int = 1

    blobs_by_id: dict[int, Blob] = field(default_factory=dict)
    blob_id_by_sha256: dict[str, int] = field(default_factory=dict)
    next_blob_id: int = 1

    beatmapsets_by_id: dict[int, BeatmapSet] = field(default_factory=dict)
    beatmaps_by_id: dict[int, Beatmap] = field(default_factory=dict)
    beatmap_id_by_checksum: dict[str, int] = field(default_factory=dict)
    attachments_by_key: dict[tuple[int, str], BeatmapFileAttachment] = field(default_factory=dict)
    attachment_keys_by_beatmap_id: dict[int, list[tuple[int, str]]] = field(default_factory=dict)
    fetch_states_by_target: dict[BeatmapFetchTarget, BeatmapFetchRecord] = field(
        default_factory=dict
    )

    def clone(self) -> Self:
        """Return an isolated copy for a command transaction."""
        return deepcopy(self)
