"""
scorer.py
---------
Wires the /score endpoint to the M-Pesa statement pipeline.

Flow:
  1. Receive ScoreRequest (profile fields + list of statement URLs)
  2. Download every statement URL concurrently
  3. Parse each PDF → clean transactions → extract features
  4. Merge profile features + statement features
  5. Run rule-based scoring engine → creditScore + creditScoreBand

The rule-based engine (score_from_features) is designed so that
when you train an ML model later, you only replace that one function.
Everything else stays the same.

Plain-language glossary for this file:
  features dict  — a flat dictionary of numbers describing one customer
  weight          — how many points a signal adds or subtracts from the score
  band            — the label bucket (GOOD / FAIR / POOR) based on final score
"""

import asyncio
import logging
from decimal import Decimal

from app.models import EmploymentStatus, ScoreRequest, StatementType

# Import the downloader from the same package
# It handles: HTTP fetch → PDF text → clean DataFrame → feature dict
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from downloader import download_statements

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
    score, band, breakdown = score_from_features(features)

    # Log the breakdown for debugging (remove in production or move to structured logging)
    logger.info(
        "Scored applicant %s | score=%d band=%s | breakdown=%s",
        req.id, score, band, breakdown
    )

    return {
        "creditScore": score,
        "creditScoreBand": band,
    }


# ---------------------------------------------------------------------------
# Step 1: Fetch all statements and collect features
# ---------------------------------------------------------------------------

def _fetch_statement_features(statements) -> dict:
    """
    Download every statement URL concurrently and return a merged
    feature dict. If a statement fails to download or parse, it is
    skipped with a warning — we never hard-fail a scoring request
    because one PDF was unavailable.

    Returns a dict with keys:
        mpesa_features   : dict or None
        bank_features    : dict or None
        sacco_features   : dict or None
        statements_ok    : int  (number of successfully parsed statements)
        statements_failed: int
    """
    result = {
        "mpesa_features":    None,
        "bank_features":     None,
        "sacco_features":    None,
        "statements_ok":     0,
        "statements_failed": 0,
    }

    if not statements:
        return result

    # Build payload list for the async downloader
    payloads = [
        {"statementUrl": s.statementUrl, "statementType": s.statementType.value}
        for s in statements
    ]

    # Run the async downloader from a sync context
    # asyncio.run() creates a new event loop for this call
    try:
        download_results = asyncio.run(download_statements(payloads))
    except Exception as exc:
        logger.error("Statement download batch failed: %s", exc)
        result["statements_failed"] = len(payloads)
        return result

    # Process each download result
    for dl in download_results:
        stype = dl.get("statement_type", "")
        if not dl.get("success"):
            logger.warning(
                "Failed to process %s statement: %s",
                stype, dl.get("error", "unknown error")
            )
            result["statements_failed"] += 1
            continue

        features = dl.get("features", {})
        if not features:
            logger.warning("Statement parsed but produced no features: %s", stype)
            result["statements_failed"] += 1
            continue

        result["statements_ok"] += 1

        # Store by type — for now we take the first successful one per type
        if stype == StatementType.MPESA.value and result["mpesa_features"] is None:
            result["mpesa_features"] = features
        elif stype == StatementType.BANK.value and result["bank_features"] is None:
            result["bank_features"] = features
        elif stype == StatementType.SACCO.value and result["sacco_features"] is None:
            result["sacco_features"] = features

    return result


# ---------------------------------------------------------------------------
# Step 2: Build unified feature set
# ---------------------------------------------------------------------------

def _build_feature_set(req: ScoreRequest, statement_features: dict) -> dict:
    """
    Merge profile fields from ScoreRequest with extracted statement features
    into a single flat dict that the scoring engine works from.

    This is the place where 'declared income' and 'observed income' meet.
    The scoring engine then decides how to weight them.
    """
    mpesa = statement_features.get("mpesa_features") or {}

    # Declared monthly income from the profile form
    declared_income = float(req.monthlyIncomeKes) if req.monthlyIncomeKes else 0.0

    # Observed monthly income from the M-Pesa statement
    observed_income = mpesa.get("monthly_inflow_avg", 0.0)

    # Income verification ratio — how close is declared to observed?
    # 1.0 = exact match, >2.5 or <0.3 = suspicious
    if declared_income > 0 and observed_income > 0:
        income_verification_ratio = observed_income / declared_income
    else:
        income_verification_ratio = 0.0

    return {
        # --- Profile ---
        "is_verified":            req.isVerified,
        "employment_status":      req.employmentStatus.value if req.employmentStatus else None,
        "declared_income":        declared_income,

        # --- Statement availability ---
        "statements_ok":          statement_features["statements_ok"],
        "statements_failed":      statement_features["statements_failed"],
        "has_mpesa":              mpesa is not None and bool(mpesa),
        "has_bank":               statement_features["bank_features"] is not None,
        "has_sacco":              statement_features["sacco_features"] is not None,

        # --- Observed income (M-Pesa) ---
        "observed_monthly_inflow":   observed_income,
        "income_verification_ratio": income_verification_ratio,
        "inflow_regularity_cv":      mpesa.get("inflow_regularity_cv", 0.0),
        "salary_detected":           mpesa.get("salary_detected", False),

        # --- Solvency ---
        "spend_to_income_ratio":     mpesa.get("spend_to_income_ratio", 0.0),
        "inflow_outflow_ratio":      mpesa.get("inflow_outflow_ratio", 0.0),
        "avg_balance":               mpesa.get("avg_balance"),
        "min_balance":               mpesa.get("min_balance"),

        # --- Repayment behaviour proxies ---
        "utility_consistency":       mpesa.get("utility_consistency", 0.0),
        "utility_payment_ratio":     mpesa.get("utility_payment_ratio", 0.0),

        # --- Risk signals ---
        "fuliza_per_month":          mpesa.get("fuliza_per_month", 0.0),
        "fuliza_escalating":         mpesa.get("fuliza_escalating", False),
        "fuliza_total_repaid":       mpesa.get("fuliza_total_repaid", 0.0),

        # --- Savings behaviour ---
        "mmf_net_flow":              mpesa.get("mmf_net_flow", 0.0),
        "mmf_deposit_count":         mpesa.get("mmf_deposit_count", 0),

        # --- Activity / engagement ---
        "active_days_ratio":         mpesa.get("active_days_ratio", 0.0),
        "statement_months":          mpesa.get("statement_months", 0.0),
        "statement_has_gap":         mpesa.get("statement_has_gap", False),

        # --- Data quality ---
        "other_txn_ratio":           mpesa.get("other_txn_ratio", 0.0),
    }


# ---------------------------------------------------------------------------
# Step 3: Rule-based scoring engine
# ---------------------------------------------------------------------------

def score_from_features(f: dict) -> tuple[int, str, dict]:
    """
    Converts a feature dict into a credit score (300–1000) using
    a weighted rule engine.

    Returns:
        (score: int, band: str, breakdown: dict)

    The breakdown dict is for logging and debugging — it shows exactly
    how many points each signal contributed.

    DESIGN NOTE:
    This function is intentionally the ONLY place where scoring logic lives.
    When you train an ML model later, you replace this function with:

        def score_from_features(f):
            score_raw = model.predict([feature_vector(f)])[0]  # 0.0 – 1.0
            score = int(300 + score_raw * 700)
            band = _band(score)
            return score, band, {}

    Everything else (download, parse, feature extraction, API layer) stays.
    """
    base  = 500
    score = 0
    breakdown = {}

    # ----------------------------------------------------------------
    # A. Identity & verification (max: +60, min: -100)
    # ----------------------------------------------------------------
    if f["is_verified"]:
        breakdown["verified"] = +60
    else:
        breakdown["not_verified"] = -100   # Unverified is a hard penalty

    # ----------------------------------------------------------------
    # B. Employment (max: +60)
    # ----------------------------------------------------------------
    emp = f.get("employment_status")
    if emp in ("EMPLOYED", "SELF_EMPLOYED"):
        breakdown["employment_formal"] = +60
    elif emp == "STUDENT":
        breakdown["employment_student"] = +10
    elif emp == "RETIRED":
        breakdown["employment_retired"] = +20
    # UNEMPLOYED = 0 (no bonus, no penalty — statements speak)

    # ----------------------------------------------------------------
    # C. Income — observed (M-Pesa inflow), not declared (max: +150)
    # Using OBSERVED income, not declared.
    # If no statement, fall back to declared income as a weaker signal.
    # ----------------------------------------------------------------
    income = f["observed_monthly_inflow"] or f["declared_income"]
    if income > 0:
        # 10,000 KES/month → +20 pts. Caps at 150 pts (75,000+ KES/month).
        income_pts = min(150, int(income) // 500)
        breakdown["income"] = income_pts

    # Income verification: penalise when declared >> observed (inflation risk)
    ivr = f["income_verification_ratio"]
    if 0 < ivr < 0.3:
        # Observed income is less than 30% of declared — suspicious
        breakdown["income_inflation_penalty"] = -60
    elif ivr > 2.5:
        # Observed is 2.5x declared — underdeclaration, flag but mild
        breakdown["income_underdeclaration"] = -20

    # Regular income (low CV = consistent monthly inflow) (max: +40)
    cv = f["inflow_regularity_cv"]
    if cv < 0.3:
        breakdown["income_regular"] = +40
    elif cv < 0.6:
        breakdown["income_moderate"] = +20
    # cv > 1.0 = very irregular, no bonus

    # Salary detection bonus
    if f["salary_detected"]:
        breakdown["salary_detected"] = +30

    # ----------------------------------------------------------------
    # D. Solvency — spend vs income (max: +60, min: -80)
    # ----------------------------------------------------------------
    sti = f["spend_to_income_ratio"]
    if 0 < sti <= 0.7:
        breakdown["solvency_strong"] = +60    # Spends ≤70% of income
    elif sti <= 0.9:
        breakdown["solvency_ok"] = +30
    elif sti <= 1.0:
        breakdown["solvency_tight"] = +10
    elif sti > 1.0:
        # Spending more than earning
        breakdown["solvency_deficit"] = -80

    # ----------------------------------------------------------------
    # E. Repayment behaviour proxies (max: +80)
    # ----------------------------------------------------------------
    # Utility consistency: paying bills in X% of months
    uc = f["utility_consistency"]
    if uc >= 0.8:
        breakdown["utility_consistent"] = +50
    elif uc >= 0.5:
        breakdown["utility_moderate"] = +20
    elif uc > 0:
        breakdown["utility_low"] = +5

    # Share of outflow that goes to bills (financial responsibility signal)
    upr = f["utility_payment_ratio"]
    if upr >= 0.05:   # At least 5% of spending goes to bills
        breakdown["utility_ratio_ok"] = +30

    # ----------------------------------------------------------------
    # F. Fuliza / overdraft risk (max: 0, min: -120)
    # ----------------------------------------------------------------
    fpm = f["fuliza_per_month"]
    if fpm == 0:
        pass   # No Fuliza = neutral (not all applicants use it)
    elif fpm <= 1:
        breakdown["fuliza_low"] = -20
    elif fpm <= 3:
        breakdown["fuliza_moderate"] = -50
    else:
        breakdown["fuliza_high"] = -90

    if f["fuliza_escalating"]:
        breakdown["fuliza_escalating"] = -30   # Additional penalty for trend

    # ----------------------------------------------------------------
    # G. Savings behaviour (max: +50)
    # ----------------------------------------------------------------
    if f["mmf_net_flow"] > 0:
        # Net saver — MMF deposits exceed withdrawals
        breakdown["mmf_net_saver"] = +50
    elif f["mmf_deposit_count"] > 0:
        # Has saved but withdrawn it all — partial credit
        breakdown["mmf_activity"] = +15

    # ----------------------------------------------------------------
    # H. Statement quality and coverage (max: +40, min: -40)
    # ----------------------------------------------------------------
    if f["statement_months"] >= 6:
        breakdown["long_statement"] = +40
    elif f["statement_months"] >= 3:
        breakdown["medium_statement"] = +20

    if f["statement_has_gap"]:
        breakdown["statement_gap"] = -30

    # Penalise if too many transactions were unclassified
    if f["other_txn_ratio"] > 0.1:
        breakdown["high_unclassified"] = -20

    # ----------------------------------------------------------------
    # I. Multi-statement bonus (bank + sacco give lenders more confidence)
    # ----------------------------------------------------------------
    if f["has_bank"]:
        breakdown["has_bank_statement"] = +30
    if f["has_sacco"]:
        breakdown["has_sacco_statement"] = +20

    # ----------------------------------------------------------------
    # Final score
    # ----------------------------------------------------------------
    total_adjustment = sum(breakdown.values())
    raw_score = base + total_adjustment
    score = max(300, min(1000, raw_score))

    band = _band(score)

    return score, band, breakdown


def _band(score: int) -> str:
    if score >= 700:
        return "GOOD"
    elif score >= 550:
        return "FAIR"
    else:
        return "POOR"