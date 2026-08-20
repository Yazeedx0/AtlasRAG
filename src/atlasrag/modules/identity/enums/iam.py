from enum import StrEnum

from sqlalchemy import Enum as SqlEnum


class PrincipalType(StrEnum):

    USER = "user"
    ROLE = "role"
    GROUP = "group"


PRINCIPAL_TYPE_DB_ENUM = SqlEnum(
    PrincipalType,
    name="principal_type",
    schema="iam",
    values_callable=lambda enum: [member.value for member in enum],
)