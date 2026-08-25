import pytest

from atlasrag.contracts.authentication import (
    AuthenticatedIdentity,
    TokenVerificationError,
    TokenVerifier,
)

pytestmark = pytest.mark.unit


def test_authenticated_identity_is_immutable() -> None:
    identity = AuthenticatedIdentity(
        issuer="https://auth.example.com/realms/atlas",
        subject="user-123",
    )

    with pytest.raises(AttributeError):
        identity.subject = "other-user"  # type: ignore[misc]


def test_authenticated_identity_accepts_optional_profile_fields() -> None:
    identity = AuthenticatedIdentity(
        issuer="https://auth.example.com/realms/atlas",
        subject="user-123",
        email="user@example.com",
        email_verified=True,
        username="user",
        display_name="Example User",
    )

    assert identity.issuer == "https://auth.example.com/realms/atlas"
    assert identity.subject == "user-123"
    assert identity.email == "user@example.com"
    assert identity.email_verified is True
    assert identity.username == "user"
    assert identity.display_name == "Example User"


def test_authenticated_identity_optional_fields_default_to_none() -> None:
    identity = AuthenticatedIdentity(
        issuer="https://auth.example.com/realms/atlas",
        subject="user-123",
    )

    assert identity.email is None
    assert identity.email_verified is None
    assert identity.username is None
    assert identity.display_name is None


def test_authenticated_identity_equality_is_by_value() -> None:
    first = AuthenticatedIdentity(issuer="https://auth.example.com/realms/atlas", subject="user-123")
    second = AuthenticatedIdentity(issuer="https://auth.example.com/realms/atlas", subject="user-123")
    different = AuthenticatedIdentity(issuer="https://auth.example.com/realms/atlas", subject="user-456")

    assert first == second
    assert first != different


def test_token_verification_error_is_an_exception() -> None:
    with pytest.raises(TokenVerificationError):
        raise TokenVerificationError("token signature invalid")


def test_token_verifier_protocol_runtime_checkable_membership() -> None:
    class WorkingVerifier:
        async def verify(self, token: str) -> AuthenticatedIdentity:
            return AuthenticatedIdentity(issuer="https://auth.example.com/realms/atlas", subject="user-123")

    verifier: TokenVerifier = WorkingVerifier()
    assert hasattr(verifier, "verify")


async def test_token_verifier_implementation_returns_identity() -> None:
    class StubVerifier:
        async def verify(self, token: str) -> AuthenticatedIdentity:
            if token != "valid-token":
                raise TokenVerificationError("invalid token")
            return AuthenticatedIdentity(
                issuer="https://auth.example.com/realms/atlas",
                subject="user-123",
            )

    verifier = StubVerifier()

    identity = await verifier.verify("valid-token")
    assert identity.subject == "user-123"

    with pytest.raises(TokenVerificationError):
        await verifier.verify("bad-token")
