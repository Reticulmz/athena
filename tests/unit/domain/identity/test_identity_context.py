"""Identity bounded-context architecture tests."""

from __future__ import annotations

import ast
from pathlib import Path

from osu_server.domain.identity import authorization
from osu_server.domain.identity.authorization import Privileges, has_privilege
from osu_server.domain.identity.roles import Role
from osu_server.domain.identity.sessions import SessionAuthorization
from osu_server.domain.identity.users import User
from osu_server.services.queries.identity.permission_service import PermissionService

PROJECT_ROOT = Path(__file__).parents[4]
SOURCE_ROOT = PROJECT_ROOT / "src" / "osu_server"

INTERNAL_AUTHORIZATION_MODULES = (
    SOURCE_ROOT / "services" / "queries" / "identity" / "permission_service.py",
    SOURCE_ROOT / "services" / "commands" / "identity" / "session_authorization_service.py",
    SOURCE_ROOT / "services" / "commands" / "identity" / "auth_service.py",
    SOURCE_ROOT / "services" / "commands" / "chat" / "join_channel.py",
    SOURCE_ROOT / "services" / "queries" / "chat" / "channels.py",
    SOURCE_ROOT / "services" / "commands" / "chat" / "bancho_bot" / "command_service.py",
)

OLD_FLAT_IDENTITY_MODULES = (
    SOURCE_ROOT / "domain" / "auth.py",
    SOURCE_ROOT / "domain" / "role.py",
    SOURCE_ROOT / "domain" / "session.py",
    SOURCE_ROOT / "domain" / "session_authorization.py",
    SOURCE_ROOT / "domain" / "user.py",
)


def test_identity_context_owns_server_authorization_language() -> None:
    role = Role(
        id=1,
        name="Admin",
        permissions=Privileges.ADMIN,
        position=100,
    )
    authorization = SessionAuthorization(
        privileges=role.permissions,
        role_ids=(role.id,),
    )

    assert has_privilege(int(authorization.privileges), Privileges.MODERATOR)
    assert authorization.role_ids == (1,)
    assert User.normalize_username("Test User") == "test_user"


def test_flat_identity_domain_modules_are_not_supported() -> None:
    remaining = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in OLD_FLAT_IDENTITY_MODULES
        if path.exists()
    ]

    assert remaining == []


def test_identity_authorization_does_not_define_client_permission_flags() -> None:
    assert not hasattr(authorization, "ClientPermissions")


def test_internal_authorization_modules_do_not_import_client_permission_flags() -> None:
    offenders = [
        f"{path.relative_to(PROJECT_ROOT).as_posix()} imports {name}"
        for path in INTERNAL_AUTHORIZATION_MODULES
        for name in _imported_names(path)
        if name.endswith("ClientPermissions")
        or name.startswith("osu_server.domain.compatibility.stable.permissions")
    ]

    assert offenders == []
    assert not hasattr(PermissionService, "to_client_flags")


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
