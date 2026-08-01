"""athena_crypto native extensionのpublic import namespaceを提供する."""

from collections.abc import Callable
from importlib import import_module
from typing import cast

type DecryptScorePayload = Callable[[bytes, bytes, str | None], tuple[str, bool]]

decrypt_score_payload = cast(
    "DecryptScorePayload",
    vars(import_module(".athena_crypto", __name__))["decrypt_score_payload"],
)

__all__ = ["decrypt_score_payload"]
