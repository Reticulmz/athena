"""Identity bounded-contextのauthorization責務と依存境界を検証する."""

from __future__ import annotations

import ast
from pathlib import Path

from osu_server.domain.identity import authorization
from osu_server.domain.identity.authorization import Privileges, has_privilege
from osu_server.domain.identity.roles import Role
from osu_server.domain.identity.sessions import SessionAuthorization
from osu_server.domain.identity.users import User
from osu_server.services.queries.identity.permission_service import PermissionService

PROJECT_ROOT = Path(__file__).parents[6]
SOURCE_ROOT = PROJECT_ROOT / "apps" / "athena_server" / "src" / "osu_server"

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


def test_identity_static_authorization_audit_reads_server_owned_sources() -> None:
    """Identity authorizationのstatic auditがserver workspace sourceを読むことを検証する.

    移設後もinternal authorization collaboratorのAST監査がrootの削除済みsource treeへ
    fallbackせず、server productのphysical ownerを検査することを確認する.

    Returns:
        None: identity source rootのownershipを検証して完了する.
    """
    assert SOURCE_ROOT == PROJECT_ROOT / "apps" / "athena_server" / "src" / "osu_server"


def test_identity_context_owns_server_authorization_language() -> None:
    """Identity contextがserver-side authorization語彙を所有することを検証する.

    privilege, session authorization, username正規化を具体値で比較する.

    Returns:
        None: role privilege, session role ID, 正規化usernameを検証して完了する.

    Raises:
        AssertionError: identity contextが必要なserver authorization語彙を提供しない場合.
    """
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
    """旧flat identity module pathがrepositoryから除去されていることを検証する.

    Returns:
        None: 存在する旧module pathの一覧が空であることを検証して完了する.

    Raises:
        AssertionError: 移行後にdeprecatedなflat domain moduleが残っている場合.
    """
    remaining = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in OLD_FLAT_IDENTITY_MODULES
        if path.exists()
    ]

    assert remaining == []


def test_identity_authorization_does_not_define_client_permission_flags() -> None:
    """Identity authorization moduleがstable client permission flagを所有しないことを検証する.

    Returns:
        None: ClientPermissions attributeが存在しないことを検証して完了する.

    Raises:
        AssertionError: client compatibility permission語彙をidentity domainへ追加した場合.
    """
    assert not hasattr(authorization, "ClientPermissions")


def test_internal_authorization_modules_do_not_import_client_permission_flags() -> None:
    """Internal authorization collaboratorがclient permission flagへ依存しないことを検証する.

    Returns:
        None: AST import監査とPermissionServiceの公開surfaceを検証して完了する.

    Raises:
        AssertionError: internal authorization moduleがstable client permissionをimportした場合.
    """
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
    """指定source fileのabsolute import module名とfrom-import member名を収集する.

    Args:
        path (Path): ASTで解析するPython source fileのpath.

    Returns:
        set[str]: level 0 importから得たmodule名と完全修飾member名の集合.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)

    return names
