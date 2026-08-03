"""replay download accounting gateのmemoryとValkey契約を検証する."""

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
    """testが手動で進められる単調clock fake.

    Attributes:
        now (float): 現在時刻として返す秒数.
    """

    now: float = 1_000.0

    def __call__(self) -> float:
        """現在のfake時刻を返す.

        Returns:
            float: advanceで変更できる現在秒数.
        """
        return self.now

    def advance(self, seconds: int) -> None:
        """fake時刻を指定秒数だけ進める.

        Args:
            seconds (int): 現在時刻へ加算する秒数.

        Returns:
            None: 時刻更新後に値を返さない.
        """
        self.now += seconds


@dataclass(frozen=True, slots=True)
class _ScriptInvocation:
    """fake Valkey clientが記録するscript invocation.

    Attributes:
        keys (tuple[str, ...]): scriptへ渡したkey列.
        args (tuple[object, ...]): scriptへ渡したargument列.
    """

    keys: tuple[str, ...]
    args: tuple[object, ...]


@dataclass(slots=True)
class _FakeValkeyClient:
    """TTL付きclaim scriptを再現して呼出内容を記録するValkey fake.

    Attributes:
        clock (Callable[[], float]): 期限判定に使う現在時刻取得操作.
        expirations (dict[str, float]): keyごとの失効予定時刻.
        invocations (list[_ScriptInvocation]): script呼出の順序付き履歴.
    """

    clock: Callable[[], float]
    expirations: dict[str, float] = field(default_factory=dict)
    invocations: list[_ScriptInvocation] = field(default_factory=list)

    async def invoke_script(
        self,
        script: Script,
        keys: list[TEncodable] | None = None,
        args: list[TEncodable] | None = None,
    ) -> int:
        """claimまたはrelease scriptを検証用in-memory stateへ適用する.

        Args:
            script (Script): API互換のscript objectでfakeでは実行しない.
            keys (list[TEncodable] | None): 対象keyを1件だけ持つ列.
            args (list[TEncodable] | None): claim markerとTTLまたはrelease用空列.

        Returns:
            int: 新規claimまたはreleaseなら1で既存claimなら0.

        Raises:
            AssertionError: keyまたはargumentの形が想定契約と異なる場合.
            TypeError: keyまたはTTLが許可されない型の場合.
        """
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
        """指定時刻までに失効したclaim keyを除去する.

        Args:
            now (float): 失効比較に使う現在時刻.

        Returns:
            None: 期限切れkeyの除去後に値を返さない.
        """
        expired_keys = [key for key, expires_at in self.expirations.items() if expires_at <= now]
        for key in expired_keys:
            del self.expirations[key]


class _InvalidResultValkeyClient:
    """result型検証用に非integer値を返すValkey client fake."""

    async def invoke_script(
        self,
        script: Script,
        keys: list[TEncodable] | None = None,
        args: list[TEncodable] | None = None,
    ) -> object:
        """Claim result変換の型検証用にbytes payloadを返す.

        Args:
            script (Script): API互換のscript objectで使用しない.
            keys (list[TEncodable] | None): API互換のkey列で使用しない.
            args (list[TEncodable] | None): API互換のargument列で使用しない.

        Returns:
            object: gateが不正型として拒否するbytes値.
        """
        del script, keys, args
        return b"1"


@dataclass(slots=True)
class _GateHarness:
    """memoryとValkey adapterへ共通のgate検証stateを提供するharness.

    Attributes:
        gate (ReplayDownloadAccountingGate): claimとreleaseを検証するadapter.
        clock (_Clock): cooldown経過を制御するfake clock.
        valkey_client (_FakeValkeyClient | None): Valkey実装時の呼出履歴を持つfake.
    """

    gate: ReplayDownloadAccountingGate
    clock: _Clock
    valkey_client: _FakeValkeyClient | None = None


type _HarnessFactory = Callable[[], _GateHarness]


def _memory_harness() -> _GateHarness:
    """独立fake clockを持つmemory gate harnessを生成する.

    Returns:
        _GateHarness: memory adapterを検証するharness.
    """
    clock = _Clock()
    return _GateHarness(
        gate=InMemoryReplayDownloadAccountingGate(time_func=clock),
        clock=clock,
    )


def _valkey_harness() -> _GateHarness:
    """独立fake clientとclockを持つValkey gate harnessを生成する.

    Returns:
        _GateHarness: Valkey adapterを検証するharness.
    """
    clock = _Clock()
    client = _FakeValkeyClient(clock)
    return _GateHarness(
        gate=ValkeyReplayDownloadAccountingGate(client),
        clock=clock,
        valkey_client=client,
    )


_GATE_FACTORIES: tuple[_HarnessFactory, ...] = (_memory_harness, _valkey_harness)


def test_gate_adapters_implement_protocol() -> None:
    """memoryとValkey adapterがReplayDownloadAccountingGate Protocolを満たすことを確認する.

    Returns:
        None: 検証を完了し値を返さない.
    """
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
async def test_claim_rejects_non_positive_ttl(
    factory: _HarnessFactory,
) -> None:
    """TTLが0以下のclaimを要求したとき両adapterがValueErrorを送出することを確認する.

    Args:
        factory (_HarnessFactory): memoryまたはValkey gate harnessを生成するfactory.

    Returns:
        None: 検証を完了し値を返さない.
    """
    harness = factory()

    with pytest.raises(ValueError, match="ttl_seconds must be positive"):
        _ = await harness.gate.claim_replay_view(10, 100, ttl_seconds=0)
    with pytest.raises(ValueError, match="ttl_seconds must be positive"):
        _ = await harness.gate.claim_latest_activity(10, ttl_seconds=-1)


async def test_valkey_claim_raises_type_error_on_non_integer_result() -> None:
    """Valkey scriptがinteger以外を返したときgateがTypeErrorを送出することを確認する.

    Returns:
        None: 検証を完了し値を返さない.
    """
    gate = ValkeyReplayDownloadAccountingGate(_InvalidResultValkeyClient())

    with pytest.raises(TypeError, match="Unexpected replay accounting claim result"):
        _ = await gate.claim_replay_view(10, 100, VIEW_COOLDOWN_SECONDS)


@pytest.mark.parametrize("factory", _GATE_FACTORIES, ids=["memory", "valkey"])
async def test_same_viewer_same_score_claim_is_suppressed(
    factory: _HarnessFactory,
) -> None:
    """同viewerとscoreの二重claimが最初だけTrueで後続をFalseにすることを確認する.

    Args:
        factory (_HarnessFactory): memoryまたはValkey gate harnessを生成するfactory.

    Returns:
        None: 検証を完了し値を返さない.
    """
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
    """Replay view claimがviewerとscoreの組合せごとに独立することを確認する.

    Args:
        factory (_HarnessFactory): memoryまたはValkey gate harnessを生成するfactory.

    Returns:
        None: 検証を完了し値を返さない.
    """
    harness = factory()

    assert await harness.gate.claim_replay_view(10, 100, VIEW_COOLDOWN_SECONDS) is True
    assert await harness.gate.claim_replay_view(10, 100, VIEW_COOLDOWN_SECONDS) is False
    assert await harness.gate.claim_replay_view(10, 101, VIEW_COOLDOWN_SECONDS) is True
    assert await harness.gate.claim_replay_view(11, 100, VIEW_COOLDOWN_SECONDS) is True


@pytest.mark.parametrize("factory", _GATE_FACTORIES, ids=["memory", "valkey"])
async def test_replay_view_claim_allows_again_after_cooldown(
    factory: _HarnessFactory,
) -> None:
    """cooldown期限直前は拒否し期限到達後の同一claimを許可することを確認する.

    Args:
        factory (_HarnessFactory): memoryまたはValkey gate harnessを生成するfactory.

    Returns:
        None: 検証を完了し値を返さない.
    """
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
    """Replay view claimをreleaseした後はcooldownを待たず再claimできることを確認する.

    Args:
        factory (_HarnessFactory): memoryまたはValkey gate harnessを生成するfactory.

    Returns:
        None: 検証を完了し値を返さない.
    """
    harness = factory()

    assert await harness.gate.claim_replay_view(10, 100, VIEW_COOLDOWN_SECONDS) is True
    await harness.gate.release_replay_view(10, 100)
    assert await harness.gate.claim_replay_view(10, 100, VIEW_COOLDOWN_SECONDS) is True


@pytest.mark.parametrize("factory", _GATE_FACTORIES, ids=["memory", "valkey"])
async def test_latest_activity_claim_is_viewer_scoped(
    factory: _HarnessFactory,
) -> None:
    """Latest activity claimがviewer単位で抑制され別viewerを許可することを確認する.

    Args:
        factory (_HarnessFactory): memoryまたはValkey gate harnessを生成するfactory.

    Returns:
        None: 検証を完了し値を返さない.
    """
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
    """Activity throttleの期限直前は拒否し期限後は同viewerを許可することを確認する.

    Args:
        factory (_HarnessFactory): memoryまたはValkey gate harnessを生成するfactory.

    Returns:
        None: 検証を完了し値を返さない.
    """
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
    """Latest activity claimをreleaseした直後に同viewerを再claimできることを確認する.

    Args:
        factory (_HarnessFactory): memoryまたはValkey gate harnessを生成するfactory.

    Returns:
        None: 検証を完了し値を返さない.
    """
    harness = factory()

    assert await harness.gate.claim_latest_activity(10, ACTIVITY_THROTTLE_SECONDS) is True
    await harness.gate.release_latest_activity(10)
    assert await harness.gate.claim_latest_activity(10, ACTIVITY_THROTTLE_SECONDS) is True


async def test_valkey_gate_owns_replay_accounting_key_patterns() -> None:
    """prefix付きValkey adapterがviewとactivityの規定key patternへscriptを送ることを確認する.

    Returns:
        None: 検証を完了し値を返さない.
    """
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
