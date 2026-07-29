"""Taskiq job 登録用の utility を公開します."""

from __future__ import annotations

from osu_server.infrastructure.jobs.registry import JobRegistry, jobs

__all__ = ["JobRegistry", "jobs"]
