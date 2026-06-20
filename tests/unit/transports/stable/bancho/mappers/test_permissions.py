"""Stable bancho authorization output mapper tests."""

from __future__ import annotations

import ast
from pathlib import Path

from osu_server.domain.compatibility.stable.permissions import BanchoClientPermission
from osu_server.domain.identity.authorization import Privileges
from osu_server.transports.stable.bancho.mappers.permissions import (
    map_stable_bancho_authorization,
)

PROJECT_ROOT = Path(__file__).parents[6]
SOURCE_ROOT = PROJECT_ROOT / "src" / "osu_server"

INTERNAL_AUTHORIZATION_MODULES = (
    SOURCE_ROOT / "services" / "queries" / "identity" / "permission_service.py",
    SOURCE_ROOT / "services" / "commands" / "identity" / "session_authorization_service.py",
    SOURCE_ROOT / "services" / "commands" / "identity" / "auth_service.py",
    SOURCE_ROOT / "services" / "commands" / "chat" / "join_channel.py",
    SOURCE_ROOT / "services" / "queries" / "chat" / "channels.py",
    SOURCE_ROOT / "services" / "commands" / "chat" / "bancho_bot" / "command_service.py",
)
CAPTURED_FULL_PRIVILEGES_MASK = 0x1FF


def test_stable_client_permission_values_match_bancho_reference() -> None:
    assert BanchoClientPermission.NORMAL == 1
    assert BanchoClientPermission.NOMINATOR == 2
    assert BanchoClientPermission.SUPPORTER == 4
    assert BanchoClientPermission.OWNER == 8
    assert BanchoClientPermission.FRIEND == 8
    assert BanchoClientPermission.DEVELOPER == 16
    assert BanchoClientPermission.PEPPY == 16
    assert BanchoClientPermission.TOURNAMENT_STAFF == 32


def test_stable_bancho_authorization_output_is_derived_from_privileges() -> None:
    output = map_stable_bancho_authorization(
        Privileges.SUPPORTER | Privileges.MODERATOR | Privileges.UNRESTRICTED
    )

    expected_login = (
        BanchoClientPermission.NORMAL
        | BanchoClientPermission.NOMINATOR
        | BanchoClientPermission.SUPPORTER
    )
    assert output.login_permissions == expected_login
    assert output.presence_permissions == BanchoClientPermission.NOMINATOR


def test_stable_bancho_authorization_maps_all_supported_privileges() -> None:
    output = map_stable_bancho_authorization(
        Privileges.MODERATOR
        | Privileges.SUPPORTER
        | Privileges.ADMIN
        | Privileges.DEVELOPER
        | Privileges.TOURNAMENT
    )

    expected_login = (
        BanchoClientPermission.NORMAL
        | BanchoClientPermission.NOMINATOR
        | BanchoClientPermission.SUPPORTER
        | BanchoClientPermission.PEPPY
    )
    assert output.login_permissions == expected_login | BanchoClientPermission.TOURNAMENT_STAFF
    assert output.presence_permissions == BanchoClientPermission.PEPPY


def test_stable_bancho_authorization_maps_captured_full_privileges_to_peppy_presence() -> None:
    output = map_stable_bancho_authorization(Privileges(CAPTURED_FULL_PRIVILEGES_MASK))

    assert output.login_permissions == (
        BanchoClientPermission.NORMAL
        | BanchoClientPermission.NOMINATOR
        | BanchoClientPermission.SUPPORTER
        | BanchoClientPermission.PEPPY
        | BanchoClientPermission.TOURNAMENT_STAFF
    )
    assert output.presence_permissions == BanchoClientPermission.PEPPY


def test_stable_bancho_authorization_maps_admin_and_developer_to_peppy() -> None:
    output = map_stable_bancho_authorization(Privileges.ADMIN | Privileges.DEVELOPER)

    expected = BanchoClientPermission.NORMAL | BanchoClientPermission.PEPPY
    assert output.login_permissions == expected
    assert output.presence_permissions == BanchoClientPermission.PEPPY


def test_stable_bancho_authorization_keeps_tournament_staff_out_of_presence() -> None:
    output = map_stable_bancho_authorization(Privileges.TOURNAMENT)

    assert output.login_permissions == (
        BanchoClientPermission.NORMAL | BanchoClientPermission.TOURNAMENT_STAFF
    )
    assert output.presence_permissions == BanchoClientPermission.NORMAL


def test_stable_bancho_authorization_output_ignores_internal_only_privileges() -> None:
    output = map_stable_bancho_authorization(
        Privileges.VERIFIED
        | Privileges.UNRESTRICTED
        | Privileges.EDIT_CHANNEL
        | Privileges.BYPASS_CHANNEL_ACL
    )

    assert output.login_permissions == BanchoClientPermission.NORMAL
    assert output.presence_permissions == BanchoClientPermission.NORMAL


def test_stable_bancho_authorization_full_privileges_set() -> None:
    all_privileges = Privileges.NONE
    for privilege in Privileges:
        all_privileges |= privilege

    output = map_stable_bancho_authorization(all_privileges)

    expected_login = (
        BanchoClientPermission.NORMAL
        | BanchoClientPermission.NOMINATOR
        | BanchoClientPermission.SUPPORTER
        | BanchoClientPermission.PEPPY
    )
    assert output.login_permissions == expected_login | BanchoClientPermission.TOURNAMENT_STAFF
    assert output.presence_permissions == BanchoClientPermission.PEPPY


def test_stable_client_permissions_are_not_internal_authorization_inputs() -> None:
    offenders = [
        f"{path.relative_to(PROJECT_ROOT).as_posix()} imports {name}"
        for path in INTERNAL_AUTHORIZATION_MODULES
        for name in _imported_names(path)
        if name == "osu_server.domain.compatibility.stable.permissions"
        or name.startswith("osu_server.domain.compatibility.stable.permissions.")
        or name.endswith("BanchoClientPermission")
    ]

    assert offenders == []


def test_stable_bancho_mapper_does_not_accept_client_permissions_as_input() -> None:
    mapper_path = SOURCE_ROOT / "transports" / "stable" / "bancho" / "mappers" / "permissions.py"
    tree = ast.parse(mapper_path.read_text(encoding="utf-8"), filename=mapper_path.as_posix())

    offenders = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
        if _annotation_name(arg.annotation) == "BanchoClientPermission"
    ]

    assert offenders == []


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)

    return names


def _annotation_name(annotation: ast.expr | None) -> str | None:
    if isinstance(annotation, ast.Name):
        return annotation.id
    if isinstance(annotation, ast.Attribute):
        return annotation.attr
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        return annotation.value
    return None
