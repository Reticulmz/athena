"""Command repository interface package."""

from osu_server.repositories.interfaces.commands.beatmaps import BeatmapCommandRepository
from osu_server.repositories.interfaces.commands.blobs import BlobCommandRepository
from osu_server.repositories.interfaces.commands.channels import ChannelCommandRepository
from osu_server.repositories.interfaces.commands.chat import ChatCommandRepository
from osu_server.repositories.interfaces.commands.replays import ReplayCommandRepository
from osu_server.repositories.interfaces.commands.roles import RoleCommandRepository
from osu_server.repositories.interfaces.commands.scores import ScoreCommandRepository
from osu_server.repositories.interfaces.commands.submissions import (
    ScoreSubmissionCommandRepository,
)
from osu_server.repositories.interfaces.commands.users import UserCommandRepository

__all__ = [
    "BeatmapCommandRepository",
    "BlobCommandRepository",
    "ChannelCommandRepository",
    "ChatCommandRepository",
    "ReplayCommandRepository",
    "RoleCommandRepository",
    "ScoreCommandRepository",
    "ScoreSubmissionCommandRepository",
    "UserCommandRepository",
]
