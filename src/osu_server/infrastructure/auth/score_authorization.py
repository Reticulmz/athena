"""Score submission authorization service.

Implements Requirement 4 (Authorization) for score-ingestion Wave 1.
"""

from dataclasses import dataclass


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

    Wave 1: Mock implementation without real auth service or Valkey.
    """

    # Mock test credentials (Wave 1 only)
    _MOCK_USER_ID: int = 1000
    _MOCK_USERNAME: str = "test_user"
    _MOCK_PASSWORD_MD5: str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"  # "password"

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
        # Mock: Accept specific test credentials
        password_valid = password_md5 == self._MOCK_PASSWORD_MD5
        session_valid = password_valid
        identity_match = (
            payload_username == self._MOCK_USERNAME and payload_user_id == self._MOCK_USER_ID
        )

        return AuthorizationContext(
            user_id=self._MOCK_USER_ID,
            username=self._MOCK_USERNAME,
            session_valid=session_valid,
            password_valid=password_valid,
            payload_identity_match=identity_match,
        )
