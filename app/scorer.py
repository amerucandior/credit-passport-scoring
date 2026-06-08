"""
scorer.py
---------
Flow:
  1. Receive ScoreRequest (profile fields + list of statement URLs)
  2. Download every statement URL concurrently
  3. Parse each PDF → clean transactions → extract features
  4. Merge profile features + statement features
  5. Run rule-based scoring engine → creditScore + creditScoreBand

The rule-based engine (score_from_features) designed to be replaced by a
ML model later, you only replace that one function.
Everything else stays the same.
"""

import logging

from app.models import ScoreRequest

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from operations.download_statements import _fetch_statement_features
from operations.build_features import _build_feature_set
from operations.rule_based_scoring import score_from_features

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entry point — called by the FastAPI route
# ---------------------------------------------------------------------------


def compute_score(req: ScoreRequest) -> dict:
    """
    Main scoring function. Synchronous wrapper around the async pipeline
    so FastAPI's sync route handler can call it cleanly.

    Returns dict matching ScoreResponse:
        { "creditScore": int, "creditScoreBand": str }
    """
    # Step 1: Download and parse all statements
    statement_features = _fetch_statement_features(req.statements)

    # Step 2: Build the merged feature set (profile + statements)
    features = _build_feature_set(req, statement_features)

    # Step 3: Score
    score, band, improvement = score_from_features(features)

    # Log the improvement report for debugging (remove in production or move to structured logging)
    logger.info(
        "Scored applicant %s | score=%d band=%s | improvement=%s",
        req.id,
        score,
        band,
        improvement,
    )

    return {
        "creditScore": score,
        "creditScoreBand": band,
        "improvement": _serialise_improvement(improvement),
    }


def _serialise_improvement(improvement: dict) -> dict:
    """
    Convert the improvement report into a JSON-serialisable dict that
    Pydantic's ScoreResponse.improvement (ImprovementReport) can validate.
    """
    serialised_pillars = {}
    for pillar_code, pillar_data in improvement["pillars"].items():
        serialised_pillars[pillar_code] = {
            "label": pillar_data["label"],
            "score": pillar_data["score"],
            "strengths": pillar_data["strengths"],
            "improvements": [
                {
                    "label": item["label"],
                    "explanation": item["explanation"],
                    "action": item.get("action"),
                    "priority": item["priority"],
                    "pointsAtStake": item["points_at_stake"],
                }
                for item in pillar_data["improvements"]
            ],
        }

    top_actions = [
        {
            "label": item["label"],
            "explanation": item["explanation"],
            "action": item.get("action"),
            "priority": item["priority"],
            "pointsAtStake": item["points_at_stake"],
            "pillar": item.get("pillar"),
        }
        for item in improvement["top_actions"]
    ]

    return {
        "pillars": serialised_pillars,
        "topActions": top_actions,
        "strengthsSummary": improvement["strengths_summary"],
        "scorePotential": improvement["score_potential"],
    }
