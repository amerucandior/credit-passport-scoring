# ---------------------------------------------------------------------------
# Build unified feature set
# ---------------------------------------------------------------------------
from app.models import ScoreRequest


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
        "is_verified": req.isVerified,
        "employment_status": (
            req.employmentStatus.value if req.employmentStatus else None
        ),
        "declared_income": declared_income,
        # --- Statement availability ---
        "statements_ok": statement_features["statements_ok"],
        "statements_failed": statement_features["statements_failed"],
        "has_mpesa": mpesa is not None and bool(mpesa),
        "has_bank": statement_features["bank_features"] is not None,
        "has_sacco": statement_features["sacco_features"] is not None,
        # --- Observed income (M-Pesa) ---
        "observed_monthly_inflow": observed_income,
        "income_verification_ratio": income_verification_ratio,
        "inflow_regularity_cv": mpesa.get("inflow_regularity_cv", 0.0),
        "salary_detected": mpesa.get("salary_detected", False),
        # --- Solvency ---
        "spend_to_income_ratio": mpesa.get("spend_to_income_ratio", 0.0),
        "inflow_outflow_ratio": mpesa.get("inflow_outflow_ratio", 0.0),
        "avg_balance": mpesa.get("avg_balance"),
        "min_balance": mpesa.get("min_balance"),
        # --- Repayment behaviour proxies ---
        "utility_consistency": mpesa.get("utility_consistency", 0.0),
        "utility_payment_ratio": mpesa.get("utility_payment_ratio", 0.0),
        # --- Risk signals ---
        "fuliza_per_month": mpesa.get("fuliza_per_month", 0.0),
        "fuliza_escalating": mpesa.get("fuliza_escalating", False),
        "fuliza_total_repaid": mpesa.get("fuliza_total_repaid", 0.0),
        # --- Savings behaviour ---
        "mmf_net_flow": mpesa.get("mmf_net_flow", 0.0),
        "mmf_deposit_count": mpesa.get("mmf_deposit_count", 0),
        # --- Activity / engagement ---
        "active_days_ratio": mpesa.get("active_days_ratio", 0.0),
        "statement_months": mpesa.get("statement_months", 0.0),
        "statement_has_gap": mpesa.get("statement_has_gap", False),
        # --- Data quality ---
        "other_txn_ratio": mpesa.get("other_txn_ratio", 0.0),
    }
