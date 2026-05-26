from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Gender(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    OTHER = "OTHER"
    PREFER_NOT_TO_SAY = "PREFER_NOT_TO_SAY"


class EmploymentStatus(str, Enum):
    EMPLOYED = "EMPLOYED"
    SELF_EMPLOYED = "SELF_EMPLOYED"
    UNEMPLOYED = "UNEMPLOYED"
    STUDENT = "STUDENT"
    RETIRED = "RETIRED"


class StatementType(str, Enum):
    MPESA = "MPESA"
    BANK = "BANK"
    SACCO = "SACCO"


class StatementPayload(BaseModel):
    statementType: StatementType
    statementUrl: str


class ScoreRequest(BaseModel):
    id: str
    natId: str
    gender: Optional[Gender] = None
    isVerified: bool = False
    employmentStatus: Optional[EmploymentStatus] = None
    monthlyIncomeKes: Optional[Decimal] = None
    statements: list[StatementPayload] = Field(default_factory=list)


class ScoreResponse(BaseModel):
    creditScore: int = Field(ge=300, le=1000)
    creditScoreBand: str  # GOOD | FAIR | POOR
