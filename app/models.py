"""
models.py
---------
Pydantic data models for the Credit Passport Scoring API.

Key addition from v1:
  ScoreResponse now includes a full ImprovementReport so callers get
  actionable advice alongside the raw score — not just a number.

Structure overview:
  ScoreRequest          — what the caller sends (identity + statements)
  ScoreResponse         — what we return:
      creditScore           int (300–1000)
      creditScoreBand       GOOD | FAIR | POOR
      improvement           ImprovementReport (NEW)
          pillars               per-dimension scores + advice
          topActions            top 3 things to do RIGHT NOW
          strengthsSummary      top 3 things the user is doing well
          scorePotential        how many points they can gain by improving
"""

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


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Improvement report models
# ---------------------------------------------------------------------------


class StrengthItem(BaseModel):
    """One positive signal that helped the user's score."""

    label: str = Field(description="Short label, e.g. 'Consistent Bill Payments'")
    explanation: str = Field(
        description="Plain-language explanation of why this helps."
    )
    points: int = Field(description="How many points this contributed.")


class ImprovementItem(BaseModel):
    """One negative signal with an actionable fix."""

    label: str = Field(description="Short label, e.g. 'Heavy Fuliza Dependence'")
    explanation: str = Field(description="Why this hurts the score in plain language.")
    action: Optional[str] = Field(
        default=None, description="Exactly what the user should DO to fix this."
    )
    priority: int = Field(
        description="1 = fix this first, 2 = important, 3 = nice-to-have",
        ge=1,
        le=3,
    )
    pointsAtStake: int = Field(
        description="How many points the user would gain by resolving this signal."
    )
    pillar: Optional[str] = Field(
        default=None, description="Which financial dimension this belongs to."
    )


class PillarReport(BaseModel):
    """Assessment for one financial dimension (Income, Spending, etc.)"""

    label: str = Field(description="Human-readable pillar name.")
    score: int = Field(
        description="Sub-score for this dimension, 0–100.",
        ge=0,
        le=100,
    )
    strengths: list[StrengthItem] = Field(
        default_factory=list,
        description="Positive signals in this dimension.",
    )
    improvements: list[ImprovementItem] = Field(
        default_factory=list,
        description="Negative signals in this dimension, with fix actions.",
    )


class ImprovementReport(BaseModel):
    """
    The full improvement report attached to every ScoreResponse.

    How to use this in a frontend:
      - pillars → draw a spider/radar chart with 5 axes
      - topActions → show as a numbered to-do list ("Your next steps")
      - strengthsSummary → show as badges or a "What you're doing well" section
      - scorePotential → show as "You could improve your score by up to X points"
    """

    pillars: dict[str, PillarReport] = Field(
        description=(
            "Keyed by pillar code (INCOME, SPENDING, REPAYMENT, SAVINGS, DATA_QUALITY). "
            "Each contains a 0–100 sub-score plus strengths and improvement items."
        )
    )
    topActions: list[ImprovementItem] = Field(
        description="The 3 highest-impact actions the user should take right now.",
        max_length=3,
    )
    strengthsSummary: list[StrengthItem] = Field(
        description="The 3 strongest positive signals in the user's financial profile.",
        max_length=3,
    )
    scorePotential: int = Field(
        description=(
            "How many additional points the user could earn by addressing "
            "all flagged improvement areas. Capped at 700 (the maximum possible gain)."
        ),
        ge=0,
        le=700,
    )


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------


class ScoreResponse(BaseModel):
    creditScore: int = Field(ge=300, le=1000)
    creditScoreBand: str  # GOOD | FAIR | POOR
    improvement: ImprovementReport = Field(
        description="Actionable breakdown of what drives the score and how to improve it."
    )