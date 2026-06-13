"""Score submission authorization service.

Implements Requirement 4 (Authorization) for score-ingestion Wave 1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from osu_server.domain.user import User

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.session_store import SessionStore
    from osu_server.repositories.interfaces.user_repository import UserRepository
    from osu_server.services.password_service import PasswordService


@dataclass(frozen=True, slots=True)
class AuthorizationContext:
    """Authorization result for score submission.

    Attributes:
        user_id: Authenticated user ID
        username: Authenticated username
        session_valid: Whether active bancho session exists
        password_valid: Whether password-md5 is valid
        payload_identity_match: Whether payload identity matches authenticated user
    """

    user_id: int
    username: str
    session_valid: bool
    password_valid: bool
    payload_identity_match: bool

    @property
    def authorized(self) -> bool:
        """Check if fully authorized (all checks pass)."""
        return self.session_valid and self.password_valid and self.payload_identity_match


class ScoreAuthorizationService:
    """Authorize score submissions (password + session + identity).

    Uses repository-backed auth. Test credentials must be provided through
    explicit test doubles at the composition boundary.
    """

    _user_repo: UserRepository
    _password_service: PasswordService
    _session_store: SessionStore

    _NO_PAYLOAD_USER_ID: int = 0

    def __init__(
        self,
        *,
        user_repo: UserRepository,
        password_service: PasswordService,
        session_store: SessionStore,
    ) -> None:
        self._user_repo = user_repo
        self._password_service = password_service
        self._session_store = session_store

    async def authorize_submission(
        self,
        password_md5: str,
        payload_username: str,
        payload_user_id: int,
    ) -> AuthorizationContext:
        """Authorize score submission.

        Preconditions: password_md5 is valid MD5 hash
        Postconditions: Returns authorization result with all checks
        Invariants: No raw credentials logged

        Requirements:
            - 4.1: Valid password + active session + payload match → authorize
            - 4.2: Invalid password → reject
            - 4.3: No active session → reject
            - 4.4: Payload identity mismatch → reject
            - 4.5: No raw password-md5 logged

        Args:
            password_md5: MD5 hash of password (never logged)
            payload_username: Username from decrypted payload
            payload_user_id: User ID from decrypted payload

        Returns:
            AuthorizationContext with verification results
        """
        return await self._authorize_with_repositories(
            password_md5,
            payload_username,
            payload_user_id,
        )

    async def _authorize_with_repositories(
        self,
        password_md5: str,
        payload_username: str,
        payload_user_id: int,
    ) -> AuthorizationContext:
        safe_username = User.normalize_username(payload_username)
        user = await self._user_repo.get_by_safe_username(safe_username)
        if user is None:
            return AuthorizationContext(
                user_id=0,
                username=payload_username,
                session_valid=False,
                password_valid=False,
                payload_identity_match=False,
            )

        password_valid = await self._password_service.verify(user.password_hash, password_md5)
        session = await self._session_store.get_by_user(user.id)
        session_valid = session is not None
        payload_user_id_matches = payload_user_id in (self._NO_PAYLOAD_USER_ID, user.id)
        payload_identity_match = safe_username == user.safe_username and payload_user_id_matches

        return AuthorizationContext(
            user_id=user.id,
            username=user.username,
            session_valid=session_valid,
            password_valid=password_valid,
            payload_identity_match=payload_identity_match,
        )
