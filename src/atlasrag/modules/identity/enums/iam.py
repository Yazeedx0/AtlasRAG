from enum import Enum

from sqlalchemy import Enum as SqlEnum

from atlasrag.contracts.identity import IdentifierType

__all__ = [
    "IdentifierType",
    "PRINCIPAL_TYPE_DB_ENUM",
    "PrincipalType",
]


class PrincipalType(Enum):

    USER = "user"
    ROLE = "role"
    GROUP = "group"


PRINCIPAL_TYPE_DB_ENUM = SqlEnum(
    PrincipalType,
    name="principal_type",
    schema="iam",
    values_callable=lambda enum: [member.value for member in enum],
)