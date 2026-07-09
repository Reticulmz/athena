"""Replay download accounting gate の contract tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from osu_server.infrastructure.state.interfaces.replay_download_accounting_gate import (
    ReplayDownloadAccountingGate,
)
from osu_server.infrastructure.state.memory.replay_download_accounting_gate import (
    InMemoryReplayDownloadAccountingGate,
)
from osu_server.infrastructure.state.valkey.replay_download_accounting_gate import (
    ValkeyReplayDownloadAccountingGate,
)

if TYPE_CHECKING:
    from glide import Script
    from glide_shared.constants import TEncodable

VIEW_COOLDOWN_SECONDS = 86_400
ACTIVITY_THROTTLE_SECONDS = 300


@dataclass(slots=True)
class _Clock:
    now: float = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += seconds


@dataclass(frozen=True, slots=True)
class _ScriptInvocation:
    keys: tuple[str, ...]
    args: tuple[object, ...]


@dataclass(slots=True)
class _FakeValkeyClient:
    clock: Callable[[], float]
    expirations: dict[str, float] = field(default_factory=dict)
    invocations: list[_ScriptInvocation] = field(default_factory=list)

    async def invoke_script(
        self,
        script: Script,
        keys: list[TEncodable] | None = None,
        args: list[TEncodable] | None = None,
    ) -> int:
        _ = script
        if keys is None or len(keys) != 1:
            raise AssertionError(f"expected one key, got {keys!r}")

        now = self.clock()
        self._prune(now)

        key = keys[0]
        if not isinstance(key, str):
            raise TypeError(f"expected string key, got {key!r}")
        if args == []:
            self.invocations.append(_ScriptInvocation((key,), ()))
            _ = self.expirations.pop(key, None)
            return 1

        if args is None or len(args) != 2:
            raise AssertionError(f"expected marker and ttl args, got {args!r}")

        ttl_arg = args[1]
        if not isinstance(ttl_arg, str | int):
            raise TypeError(f"expected string or int ttl, got {ttl_arg!r}")

        self.invocations.append(_ScriptInvocation((key,), tuple(args)))
        if key in self.expirations:
            return 0

        self.expirations[key] = now + int(ttl_arg)
        return 1

    def _prune(self, now: float) -> None:
        expired_keys = [key for key, expires_at in self.expirations.items() if expires_at <= now]
        for key in expired_keys:
            del self.expirations[key]


@dataclass(slots=True)
class _GateHarness:
    gate: ReplayDownloadAccountingGate
    clock: _Clock
    valkey_client: _FakeValkeyClient | None = None


type _HarnessFactory = Callable[[], _GateHarness]


def _memory_harness() -> _GateHarness:
    clock = _Clock()
    return _GateHarness(
        gate=InMemoryReplayDownloadAccountingGate(time_func=clock),
        clock=clock,
    )


def _valkey_harness() -> _GateHarness:
    clock = _Clock()
    client = _FakeValkeyClient(clock)
    return _GateHarness(
        gate=ValkeyReplayDownloadAccountingGate(client),
        clock=clock,
        valkey_client=client,
    )


_GATE_FACTORIES: tuple[_HarnessFactory, ...] = (_memory_harness, _valkey_harness)


def test_gate_adapters_implement_protocol() -> None:
    clock = _Clock()
    client = _FakeValkeyClient(clock)

    assert isinstance(
        InMemoryReplayDownloadAccountingGate(time_func=clock),
        ReplayDownloadAccountingGate,
    )
    assert isinstance(
        ValkeyReplayDownloadAccountingGate(client),
        ReplayDownloadAccountingGate,
    )


@pytest.mark.parametrize("factory", _GATE_FACTORIES, ids=["memory", "valkey"])
async def test_same_viewer_same_score_claim_is_suppressed(
    factory: _HarnessFactory,
) -> None:
    harness = factory()

    assert (
        await harness.gate.claim_replay_view(
            viewer_user_id=10,
            score_id=100,
            ttl_seconds=VIEW_COOLDOWN_SECONDS,
        )
        is True
    )
    assert (
        await harness.gate.claim_replay_view(
            viewer_user_id=10,
            score_id=100,
            ttl_seconds=VIEW_COOLDOWN_SECONDS,
        )
        is False
    )


@pytest.mark.parametrize("factory", _GATE_FACTORIES, ids=["memory", "valkey"])
async def test_replay_view_claim_identity_is_viewer_and_score_scoped(
    factory: _HarnessFactory,
) -> None:
    harness = factory()

    assert await harness.gate.claim_replay_view(10, 100, VIEW_COOLDOWN_SECONDS) is True
    assert await harness.gate.claim_replay_view(10, 100, VIEW_COOLDOWN_SECONDS) is False
    assert await harness.gate.claim_replay_view(10, 101, VIEW_COOLDOWN_SECONDS) is True
    assert await harness.gate.claim_replay_view(11, 100, VIEW_COOLDOWN_SECONDS) is True


@pytest.mark.parametrize("factory", _GATE_FACTORIES, ids=["memory", "valkey"])
async def test_replay_view_claim_allows_again_after_cooldown(
    factory: _HarnessFactory,
) -> None:
    harness = factory()

    assert await harness.gate.claim_replay_view(10, 100, VIEW_COOLDOWN_SECONDS) is True
    harness.clock.advance(VIEW_COOLDOWN_SECONDS - 1)
    assert await harness.gate.claim_replay_view(10, 100, VIEW_COOLDOWN_SECONDS) is False
    harness.clock.advance(1)
    assert await harness.gate.claim_replay_view(10, 100, VIEW_COOLDOWN_SECONDS) is True


@pytest.mark.parametrize("factory", _GATE_FACTORIES, ids=["memory", "valkey"])
async def test_replay_view_release_allows_immediate_retry(
    factory: _HarnessFactory,
) -> None:
    harness = factory()

    assert await harness.gate.claim_replay_view(10, 100, VIEW_COOLDOWN_SECONDS) is True
    await harness.gate.release_replay_view(10, 100)
    assert await harness.gate.claim_replay_view(10, 100, VIEW_COOLDOWN_SECONDS) is True


@pytest.mark.parametrize("factory", _GATE_FACTORIES, ids=["memory", "valkey"])
async def test_latest_activity_claim_is_viewer_scoped(
    factory: _HarnessFactory,
) -> None:
    harness = factory()

    assert (
        await harness.gate.claim_latest_activity(
            viewer_user_id=10,
            ttl_seconds=ACTIVITY_THROTTLE_SECONDS,
        )
        is True
    )
    assert (
        await harness.gate.claim_latest_activity(
            viewer_user_id=10,
            ttl_seconds=ACTIVITY_THROTTLE_SECONDS,
        )
        is False
    )
    assert (
        await harness.gate.claim_latest_activity(
            viewer_user_id=11,
            ttl_seconds=ACTIVITY_THROTTLE_SECONDS,
        )
        is True
    )


@pytest.mark.parametrize("factory", _GATE_FACTORIES, ids=["memory", "valkey"])
async def test_latest_activity_claim_allows_again_after_throttle(
    factory: _HarnessFactory,
) -> None:
    harness = factory()

    assert await harness.gate.claim_latest_activity(10, ACTIVITY_THROTTLE_SECONDS) is True
    harness.clock.advance(ACTIVITY_THROTTLE_SECONDS - 1)
    assert await harness.gate.claim_latest_activity(10, ACTIVITY_THROTTLE_SECONDS) is False
    harness.clock.advance(1)
    assert await harness.gate.claim_latest_activity(10, ACTIVITY_THROTTLE_SECONDS) is True


@pytest.mark.parametrize("factory", _GATE_FACTORIES, ids=["memory", "valkey"])
async def test_latest_activity_release_allows_immediate_retry(
    factory: _HarnessFactory,
) -> None:
    harness = factory()

    assert await harness.gate.claim_latest_activity(10, ACTIVITY_THROTTLE_SECONDS) is True
    await harness.gate.release_latest_activity(10)
    assert await harness.gate.claim_latest_activity(10, ACTIVITY_THROTTLE_SECONDS) is True


async def test_valkey_gate_owns_replay_accounting_key_patterns() -> None:
    clock = _Clock()
    client = _FakeValkeyClient(clock)
    gate = ValkeyReplayDownloadAccountingGate(client, key_prefix="test:")

    assert await gate.claim_replay_view(10, 100, VIEW_COOLDOWN_SECONDS) is True
    assert await gate.claim_latest_activity(10, ACTIVITY_THROTTLE_SECONDS) is True

    assert client.invocations == [
        _ScriptInvocation(
            keys=("test:replay_download_accounting:view:10:score:100",),
            args=("1", str(VIEW_COOLDOWN_SECONDS)),
        ),
        _ScriptInvocation(
            keys=("test:replay_download_accounting:activity:10",),
            args=("1", str(ACTIVITY_THROTTLE_SECONDS)),
        ),
    ]
