class AppError(Exception):
    """Base error for all application errors."""


class DecryptionError(AppError):
    """Raised when score payload decryption fails."""
