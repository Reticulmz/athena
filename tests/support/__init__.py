from __future__ import annotations

from tests.support.fakes import ErrorRaisingUserRepository, FakeHIBPClient
from tests.support.runtime_assertions import assert_rejects_setattr

__all__ = [
    "ErrorRaisingUserRepository",
    "FakeHIBPClient",
    "assert_rejects_setattr",
]
