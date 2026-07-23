"""legacy score submission用のmultipart request data factoryを提供する."""


def make_multipart_request(
    *,
    score: str = "",
    iv: str = "",
    osuver: str = "20260412",
    pass_: str = "",
) -> dict[str, str]:
    """Score submission testに渡すmultipart fieldを作る.

    Args:
        score (str): 暗号化済みscore payload.
        iv (str): score payloadのinitialization vector.
        osuver (str): request元のosu! version.
        pass_ (str): score submissionのpassword field値.

    Returns:
        dict[str, str]: legacy endpointが期待するform field mapping.
    """
    return {
        "score": score,
        "iv": iv,
        "osuver": osuver,
        "pass": pass_,
    }
