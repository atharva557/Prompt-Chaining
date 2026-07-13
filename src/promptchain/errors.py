"""Typed exceptions for the promptchain public API.

Each error also subclasses the builtin exception the pre-library code raised
(ConnectionError / TimeoutError / RuntimeError), so callers written against
the old contract — including the bundled Streamlit app — keep working.
"""


class PromptChainError(Exception):
    """Base class for every promptchain error."""


class BackendConnectionError(PromptChainError, ConnectionError):
    """The backend server is unreachable or dropped the connection."""


class GenerationTimeout(PromptChainError, TimeoutError):
    """A generation request exceeded its timeout."""


class BackendResponseError(PromptChainError, RuntimeError):
    """The backend answered with an error status."""

    def __init__(self, message: str, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


class AuthenticationError(BackendResponseError):
    """The backend rejected the API key."""


class ModelNotRegistered(PromptChainError, KeyError):
    """The named model was never registered with the ModelManager."""


class ModelNotResident(PromptChainError, RuntimeError):
    """Under policy='manual', the model must be loaded explicitly before use."""
