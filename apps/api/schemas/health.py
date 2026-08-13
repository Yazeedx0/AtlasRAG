"""Wire shapes for the probe endpoints.

Infrastructure-only: these carry no domain meaning and deliberately have no
counterpart in ``atlasrag.contracts``.
"""

from pydantic import BaseModel


class LivenessResponse(BaseModel):
    status: str
    service: str
    version: str


class ReadinessResponse(BaseModel):
    status: str
    checks: dict[str, str]
