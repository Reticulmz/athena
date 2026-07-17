"""Getscores completion evidence向けのsymbolic test helper。"""

from __future__ import annotations

from dataclasses import replace
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from athena_cli.stable_verification.getscores_evidence import (
    GetscoresIdentityProfile,
    GetscoresMutationProfile,
    GetscoresRequestSelector,
    GetscoresSeedProfile,
    GetscoresWireShapeId,
)
from osu_server.domain.scores.mods import Mod

_UNAVAILABLE_CHECKSUM = "f" * 32
_UPDATE_CANDIDATE_CHECKSUM = "a" * 32
_INVALID_PASSWORD_MD5 = "0" * 32
_ALTERNATE_SYNTHETIC_MD5 = "e" * 32
_CANONICAL_COMPLETION_BODY_ROOT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "web_legacy" / "getscores" / "completion"
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from athena_cli.stable_verification.getscores_evidence import (
        GetscoresBranchCase,
        GetscoresCompletionEvidence,
    )


def build_getscores_contract_query(
    case: GetscoresBranchCase,
    base_query: Mapping[str, str],
) -> dict[str, str]:
    """Symbolic branch caseからsafeなstable queryを構築する。

    Args:
        case (GetscoresBranchCase): Closed profileだけを保持するbranch case。
        base_query (Mapping[str, str]): Caller所有のsynthetic基底query。

    Returns:
        dict[str, str]: Caller入力から独立した新しいquery。

    Raises:
        ValueError: Unknown/incoherent profileまたはrequired base field不足の場合。

    Notes:
        Callerのquery値を保存または記録しない。
    """
    query = dict(base_query)
    query.update({"m": "0", "mods": "0", "s": "0", "v": "1", "vv": "4"})
    _ = query.pop("a", None)

    _apply_identity_profile(query, case.identity_profile)
    _apply_request_selector(query, case.request_selector, case.seed_profile)
    _apply_mutation_profiles(query, case.mutation_profiles)
    return query


def _apply_identity_profile(query: dict[str, str], raw_profile: object) -> None:
    profile = _closed_profile(
        GetscoresIdentityProfile,
        raw_profile,
        "getscores_contract:identity_profile:unknown_profile",
    )

    match profile:
        case GetscoresIdentityProfile.AUTH_MISSING:
            _ = _required_base_value(query, "c")
            _ = query.pop("us", None)
            _ = query.pop("ha", None)
        case GetscoresIdentityProfile.AUTH_INVALID:
            _ = _required_base_value(query, "c")
            _ = _required_base_value(query, "us")
            password_md5 = _required_base_value(query, "ha")
            query["ha"] = _different_synthetic_md5(
                password_md5,
                _INVALID_PASSWORD_MD5,
            )
        case GetscoresIdentityProfile.KNOWN_BEATMAP:
            _ = _required_base_value(query, "c")
            _ = _required_base_value(query, "us")
            _ = _required_base_value(query, "ha")
        case GetscoresIdentityProfile.MISSING_BEATMAP_IDENTITY:
            _ = _required_base_value(query, "us")
            _ = _required_base_value(query, "ha")
            for field in ("c", "f", "i"):
                _ = query.pop(field, None)
        case GetscoresIdentityProfile.INVALID_CHECKSUM:
            _ = _required_base_value(query, "us")
            _ = _required_base_value(query, "ha")
            query["c"] = "not-a-valid-md5"
            _ = query.pop("f", None)
            _ = query.pop("i", None)
        case GetscoresIdentityProfile.UNAVAILABLE_BEATMAP:
            checksum = _required_base_value(query, "c")
            _ = _required_base_value(query, "us")
            _ = _required_base_value(query, "ha")
            query["c"] = _different_synthetic_md5(checksum, _UNAVAILABLE_CHECKSUM)
            _ = query.pop("f", None)
            _ = query.pop("i", None)
        case GetscoresIdentityProfile.UPDATE_CANDIDATE:
            checksum = _required_base_value(query, "c")
            _ = _required_base_value(query, "f")
            _ = _required_base_value(query, "i")
            _ = _required_base_value(query, "us")
            _ = _required_base_value(query, "ha")
            query["c"] = _different_synthetic_md5(
                checksum,
                _UPDATE_CANDIDATE_CHECKSUM,
            )


def _apply_request_selector(
    query: dict[str, str],
    raw_selector: object,
    raw_seed_profile: object,
) -> None:
    selector = _closed_profile(
        GetscoresRequestSelector,
        raw_selector,
        "getscores_contract:request_selector:unknown_profile",
    )
    seed_profile = _closed_profile(
        GetscoresSeedProfile,
        raw_seed_profile,
        "getscores_contract:seed_profile:unknown_profile",
    )

    match selector:
        case GetscoresRequestSelector.GLOBAL_DOMAIN | GetscoresRequestSelector.LOCAL:
            query["v"] = "1"
        case GetscoresRequestSelector.SELECTED_MODS:
            query["v"] = "2"
            match seed_profile:
                case GetscoresSeedProfile.SELECTED_MODS_SUPPORTED:
                    query["mods"] = str(int(Mod.MIRROR))
                case GetscoresSeedProfile.SELECTED_MODS_UNSUPPORTED:
                    query["mods"] = str(1 << 31)
                case _:
                    raise ValueError("getscores_contract:seed_profile:invalid_selector_profile")
        case GetscoresRequestSelector.FRIENDS:
            query["v"] = "3"
        case GetscoresRequestSelector.COUNTRY:
            query["v"] = "4"
        case GetscoresRequestSelector.SONG_SELECT:
            query.update({"s": "1", "v": "1"})
        case GetscoresRequestSelector.UNSUPPORTED_LEADERBOARD:
            query["v"] = "99"
        case GetscoresRequestSelector.UNSUPPORTED_PLAYSTYLE:
            query.update({"mods": str(int(Mod.RELAX)), "v": "1"})


def _apply_mutation_profiles(
    query: dict[str, str],
    mutation_profiles: tuple[object, ...],
) -> None:
    for raw_mutation in mutation_profiles:
        mutation = _closed_profile(
            GetscoresMutationProfile,
            raw_mutation,
            "getscores_contract:mutation_profile:unknown_profile",
        )
        match mutation:
            case GetscoresMutationProfile.INVALID_MODE:
                query["m"] = "invalid-mode"
            case GetscoresMutationProfile.INVALID_MODS:
                query["mods"] = "invalid-mods"
            case GetscoresMutationProfile.INVALID_LEADERBOARD_TYPE:
                query["v"] = "invalid-leaderboard-type"
            case GetscoresMutationProfile.INVALID_LEADERBOARD_VERSION:
                query["vv"] = "invalid-leaderboard-version"
            case GetscoresMutationProfile.INVALID_SONG_SELECT_FLAG:
                query["s"] = "invalid-song-select-flag"
            case GetscoresMutationProfile.INVALID_ANTI_CHEAT_SIGNAL:
                query["a"] = "invalid-anti-cheat-signal"
            case GetscoresMutationProfile.INVALID_BEATMAPSET_ID_HINT:
                query["i"] = "invalid-beatmapset-id-hint"
            case GetscoresMutationProfile.VALID_ANTI_CHEAT_SIGNAL:
                query["a"] = "1"
            case GetscoresMutationProfile.REQUEST_VERSION_VARIANT:
                query["vv"] = "5"


def _closed_profile[ProfileT: StrEnum](
    profile_type: type[ProfileT],
    raw_profile: object,
    error_code: str,
) -> ProfileT:
    try:
        return profile_type(raw_profile)
    except (TypeError, ValueError):
        raise ValueError(error_code) from None


def _required_base_value(query: Mapping[str, str], field: str) -> str:
    value = query.get(field)
    if not value:
        raise ValueError(f"getscores_contract:base_query:{field}:missing_field")
    return value


def _different_synthetic_md5(current: str, preferred: str) -> str:
    if current != preferred:
        return preferred
    return _ALTERNATE_SYNTHETIC_MD5


def read_getscores_expected_body(
    evidence: GetscoresCompletionEvidence,
    shape_id: GetscoresWireShapeId,
) -> bytes:
    """Known shapeに対応するexact body bytesを読み出す。

    Args:
        evidence (GetscoresCompletionEvidence): Typed completion evidence bundle。
        shape_id (GetscoresWireShapeId): 読み出すknown wire shape ID。

    Returns:
        bytes: Canonical Base64 fixtureから復元したresponse body。

    Raises:
        ValueError: Unknown/missing/duplicate shapeまたはcanonical root外のpathの場合。
        GetscoresEvidenceValidationError: Canonical Base64 fixtureのdecodeまたは内容検証に
            失敗した場合。
    """
    known_shape_id = _closed_profile(
        GetscoresWireShapeId,
        shape_id,
        "getscores_contract:shape_id:unknown_shape",
    )
    matches = [shape for shape in evidence.response_shapes if shape.shape_id == known_shape_id]
    if not matches:
        raise ValueError("getscores_contract:shape_id:missing_shape")
    if len(matches) > 1:
        raise ValueError("getscores_contract:shape_id:duplicate_shape")

    shape = next(iter(matches))
    try:
        body_root = _CANONICAL_COMPLETION_BODY_ROOT.resolve(strict=True)
        body_file = shape.body_file.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise ValueError("getscores_contract:body_file:unsafe_body_root") from None
    if not body_file.is_relative_to(body_root) or body_file.parent != body_root:
        raise ValueError("getscores_contract:body_file:unsafe_body_root")
    if body_file.name != f"{known_shape_id.value}.body.b64":
        raise ValueError("getscores_contract:body_file:unexpected_body_owner")
    return replace(shape, body_file=body_file).read_body_bytes()
