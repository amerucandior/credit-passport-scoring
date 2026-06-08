"""
rule_based_scoring.py
---------------------
Rule-based credit scoring engine.

Changes from v1:
  - score_from_features() now returns a structured ImprovementReport dict
    (via advice_engine.build_improvement_report) instead of a raw breakdown string.
  - The breakdown dict is still produced the same way — advice_engine reads it
    and maps each key to human-readable advice. No double logic.
  - format_breakdown() kept for debug logging only.

DESIGN NOTE — replacing with ML later:
    When you train a model, only replace the score calculation block:

        raw_score = 300 + int(model.predict([feature_vector(f)])[0] * 700)

    The advice engine is model-agnostic — it reads the breakdown dict, which
    you can still produce from SHAP values or feature importances if needed.
    Or you can populate breakdown manually from model output thresholds.
    Everything else (download, parse, feature extraction, API layer) stays.
"""

from .advice_engine import build_improvement_report

# ---------------------------------------------------------------------------
# Scoring engine
# ---------------------------------------------------------------------------


def score_from_features(f: dict) -> tuple[int, str, dict]:
    """
    Convert a feature dict into a credit score (300–1000).

    Returns:
        score       : int (300-1000)
        band        : str ("GOOD" | "FAIR" | "POOR")
        improvement : dict — structured ImprovementReport ready for the API response

    The improvement dict is built by advice_engine.build_improvement_report()
    and maps 1:1 to the ImprovementReport Pydantic model.
    """
    base = 500
    breakdown: dict[str, int] = {}

    # ----------------------------------------------------------------
    # A. Identity & verification (max: +60, min: -100)
    # ----------------------------------------------------------------
    if f["is_verified"]:
        breakdown["verified"] = +60
    else:
        breakdown["not_verified"] = -100

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

    # ----------------------------------------------------------------
    # C. Income (max: +150 from amount, +40 regularity, +30 salary)
    # ----------------------------------------------------------------
    income = f["observed_monthly_inflow"] or f["declared_income"]
    if income > 0:
        income_pts = min(150, int(income) // 500)
        breakdown["income"] = income_pts

    ivr = f["income_verification_ratio"]
    if 0 < ivr < 0.3:
        breakdown["income_inflation_penalty"] = -60
    elif ivr > 2.5:
        breakdown["income_underdeclaration"] = -20

    cv = f["inflow_regularity_cv"]
    if cv < 0.3:
        breakdown["income_regular"] = +40
    elif cv < 0.6:
        breakdown["income_moderate"] = +20

    if f["salary_detected"]:
        breakdown["salary_detected"] = +30

    # ----------------------------------------------------------------
    # D. Solvency (max: +60, min: -80)
    # ----------------------------------------------------------------
    sti = f["spend_to_income_ratio"]
    if 0 < sti <= 0.7:
        breakdown["solvency_strong"] = +60
    elif sti <= 0.9:
        breakdown["solvency_ok"] = +30
    elif sti <= 1.0:
        breakdown["solvency_tight"] = +10
    elif sti > 1.0:
        breakdown["solvency_deficit"] = -80

    # ----------------------------------------------------------------
    # E. Repayment behaviour proxies (max: +80)
    # ----------------------------------------------------------------
    uc = f["utility_consistency"]
    if uc >= 0.8:
        breakdown["utility_consistent"] = +50
    elif uc >= 0.5:
        breakdown["utility_moderate"] = +20
    elif uc > 0:
        breakdown["utility_low"] = +5

    upr = f["utility_payment_ratio"]
    if upr >= 0.05:
        breakdown["utility_ratio_ok"] = +30

    # ----------------------------------------------------------------
    # F. Fuliza / overdraft risk (max: 0, min: -120)
    # ----------------------------------------------------------------
    fpm = f["fuliza_per_month"]
    if fpm == 0:
        pass
    elif fpm <= 1:
        breakdown["fuliza_low"] = -20
    elif fpm <= 3:
        breakdown["fuliza_moderate"] = -50
    else:
        breakdown["fuliza_high"] = -90

    if f["fuliza_escalating"]:
        breakdown["fuliza_escalating"] = -30

    # ----------------------------------------------------------------
    # G. Savings behaviour (max: +50)
    # ----------------------------------------------------------------
    if f["mmf_net_flow"] > 0:
        breakdown["mmf_net_saver"] = +50
    elif f["mmf_deposit_count"] > 0:
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

    if f["other_txn_ratio"] > 0.1:
        breakdown["high_unclassified"] = -20

    # ----------------------------------------------------------------
    # I. Multi-statement bonus
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

    # Build the structured improvement report (this replaces the old breakdown string)
    improvement = build_improvement_report(breakdown, f)

    return score, band, improvement


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _band(score: int) -> str:
    if score >= 700:
        return "GOOD"
    elif score >= 550:
        return "FAIR"
    else:
        return "POOR"


def format_breakdown(breakdown: dict[str, int]) -> str:
    """
    Debug-only: human-readable text version of the breakdown dict.
    Used in logger.info() calls — not sent to the API.
    """
    import json

    return json.dumps(breakdown, indent=2)
