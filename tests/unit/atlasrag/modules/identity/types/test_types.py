from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from atlasrag.modules.identity.types import ResolvedUserIdentity


def test_resolved_user_identity_contains_principal_id() -> None:
    principal_id = uuid4()

    identity = ResolvedUserIdentity(
        user_principal_id=principal_id,
    )

    assert identity.user_principal_id == principal_id


def test_resolved_user_identity_is_immutable() -> None:
    identity = ResolvedUserIdentity(
        user_principal_id=uuid4(),
    )

    with pytest.raises(FrozenInstanceError):
        identity.user_principal_id = uuid4()  # type: ignore[misc]