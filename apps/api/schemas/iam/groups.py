from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AddGroupMemberRequest(BaseModel):
    member_id: UUID


class GroupMemberResponse(BaseModel):
    membership_id: UUID
    member_id: UUID
    member_type: str
    added_at: datetime
    added_by_principal_id: UUID | None
