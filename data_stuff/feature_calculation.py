"""
feature_calculation.py
----------------------
Computes credit-scoring features from a cleaned M-Pesa transaction DataFrame.
  - "Inflow" = money coming IN to the account
  - "Outflow" = money going OUT of the account
  - "Active day" = any day with at least one transaction
  - "Fuliza" = M-Pesa's overdraft product
  - "MMF" = Mobile Money Fund (like ZIIDI) — savings behaviour
"""

import pandas as pd
from .transaction_type import classify_transaction_type
import re


# ---------------------------------------------------------------------------
# Main feature calculation function
# ---------------------------------------------------------------------------


def calculate_customer_features(df: pd.DataFrame, customer_id: str = None) -> dict:
    """
    Turn a transaction DataFrame into a flat feature dictionary.

    Parameters:
        df          : DataFrame from data_cleaning.extract_transactions()
        customer_id : Optional string ID to include in the output

    Returns:
        dict — one key per feature, ready to feed into a credit model.
                All monetary values are in KES. All rates are per month.
    """
    # ----------------------------------------------------------------
    # Guard: empty statement
    # ----------------------------------------------------------------
    if df is None or df.empty:
        return _empty_features(customer_id)

    # ----------------------------------------------------------------
    # Never mutate the caller's DataFrame — always work on a copy
    # ----------------------------------------------------------------
    df = df.copy()

    # ----------------------------------------------------------------
    # Ensure classification column exists
    # ----------------------------------------------------------------
    if "txn_type" not in df.columns:
        if "details" not in df.columns:
            raise KeyError(
                "DataFrame must contain either 'txn_type' or 'details' column for transaction classification."
            )
        df["txn_type"] = df["details"].apply(classify_transaction_type)

    # ----------------------------------------------------------------
    # Exclude transactions that should not count:
    #   - Reversals (economically null)
    #   - Transaction fees (not behavioural signal)
    # ----------------------------------------------------------------
    df_active = df[~df["txn_type"].isin(["REVERSAL", "TRANSACTION_FEE"])].copy()

    # ----------------------------------------------------------------
    # Statement window — all features normalised to this
    # ----------------------------------------------------------------
    statement_months = _get_statement_months(df)
    statement_days = _get_statement_days(df)

    # ----------------------------------------------------------------
    # Date column for day-level analysis
    # ----------------------------------------------------------------
    df_active["date"] = pd.to_datetime(df_active["completion_time"]).dt.date
    df_active["hour"] = pd.to_datetime(df_active["completion_time"]).dt.hour
    df_active["day_of_week"] = pd.to_datetime(
        df_active["completion_time"]
    ).dt.dayofweek  # 0=Mon, 6=Sun
    df_active["month_key"] = pd.to_datetime(df_active["completion_time"]).dt.to_period(
        "M"
    )

    # ================================================================
    # BLOCK 1 — Inflow features
    # ================================================================
    inflow_df = df_active[df_active["paid_in"] > 0]
    total_inflow = inflow_df["paid_in"].sum()

    # Monthly inflow per calendar month
    monthly_inflow = (
        inflow_df.groupby("month_key")["paid_in"].sum()
        if not inflow_df.empty
        else pd.Series(dtype=float)
    )
    monthly_inflow_avg = monthly_inflow.mean() if len(monthly_inflow) > 0 else 0.0
    monthly_inflow_stddev = monthly_inflow.std() if len(monthly_inflow) > 1 else 0.0

    # Coefficient of variation: lower = more regular income
    # Ranges 0 (perfectly regular) to >1 (highly irregular)
    inflow_cv = (
        (monthly_inflow_stddev / monthly_inflow_avg) if monthly_inflow_avg > 0 else 0.0
    )

    # Salary detection: any Business Payment from a known employer
    salary_rows = df_active[
        df_active["txn_type"].str.startswith("BANK_CREDIT_")
        | (df_active["txn_type"] == "SALARY_OR_BANK_CREDIT")
    ]
    salary_detected = len(salary_rows) > 0

    # ================================================================
    # BLOCK 2 — Outflow features
    # ================================================================
    outflow_df = df_active[df_active["withdrawn"] > 0]
    total_outflow = outflow_df["withdrawn"].sum()

    monthly_outflow = (
        outflow_df.groupby(
            pd.to_datetime(outflow_df["completion_time"]).dt.to_period("M")
        )["withdrawn"].sum()
        if not outflow_df.empty
        else pd.Series(dtype=float)
    )
    monthly_outflow_avg = monthly_outflow.mean() if len(monthly_outflow) > 0 else 0.0

    # Net financial position: values above 1.0 mean inflow > outflow
    inflow_outflow_ratio = (total_inflow / total_outflow) if total_outflow > 0 else 0.0

    # Spend-to-income ratio: closer to 1.0 = spending everything; >1.0 = spending more than earning
    spend_to_income_ratio = (total_outflow / total_inflow) if total_inflow > 0 else 0.0

    # ================================================================
    # BLOCK 3 — Utility payments
    # ================================================================
    utility_df = df_active[df_active["txn_type"].str.startswith("UTILITY_")]
    utility_count = len(utility_df)
    utility_amount = utility_df["withdrawn"].sum()

    # What share of outflow went to utilities (higher = bill-paying priority)
    utility_payment_ratio = (
        (utility_amount / total_outflow) if total_outflow > 0 else 0.0
    )

    # Utility payment consistency: fraction of months that had at least one utility payment
    if statement_months > 0 and not utility_df.empty:
        months_with_utility = utility_df.groupby(
            pd.to_datetime(utility_df["completion_time"]).dt.to_period("M")
        ).ngroups
        utility_consistency = months_with_utility / statement_months
    else:
        utility_consistency = 0.0

    # ================================================================
    # BLOCK 4 — Fuliza (overdraft) features
    # ================================================================
    fuliza_df = df_active[df_active["txn_type"] == "FULIZA_REPAYMENT"]
    fuliza_count = len(fuliza_df)
    fuliza_total_repaid = fuliza_df["withdrawn"].sum()
    fuliza_per_month = (
        (fuliza_count / statement_months) if statement_months > 0 else 0.0
    )

    # Trend: is Fuliza usage increasing? Compare first half vs second half of statement.
    fuliza_escalating = False
    if fuliza_count >= 4:
        mid = pd.to_datetime(df["completion_time"]).median()
        fuliza_times = pd.to_datetime(fuliza_df["completion_time"])
        first_half = (fuliza_times < mid).sum()
        second_half = (fuliza_times >= mid).sum()
        fuliza_escalating = bool(second_half > first_half)

    # ================================================================
    # BLOCK 5 — P2P (peer-to-peer) features
    # ================================================================
    p2p_sent_df = df_active[df_active["txn_type"] == "P2P_SENT"]
    p2p_received_df = df_active[df_active["txn_type"] == "P2P_RECEIVED"]

    p2p_sent_count = len(p2p_sent_df)
    p2p_received_count = len(p2p_received_df)
    p2p_total = p2p_sent_count + p2p_received_count

    # Network size = unique counterparties (extracts masked numbers like 07*****)
    all_p2p = pd.concat([p2p_sent_df, p2p_received_df])
    p2p_network_size = _count_unique_counterparties(all_p2p)

    # Balance between sending and receiving P2P
    # 0.0 = only sends, 1.0 = only receives, 0.5 = balanced
    p2p_sent_received_ratio = p2p_received_count / p2p_total if p2p_total > 0 else 0.0

    # ================================================================
    # BLOCK 6 — MMF / savings features
    # ================================================================
    mmf_deposit_df = df_active[df_active["txn_type"] == "MMF_DEPOSIT"]
    mmf_withdrawal_df = df_active[df_active["txn_type"] == "MMF_WITHDRAWAL"]

    mmf_deposit_count = len(mmf_deposit_df)
    mmf_withdrawal_count = len(mmf_withdrawal_df)
    mmf_total_deposited = mmf_deposit_df[
        "withdrawn"
    ].sum()  # withdrawing from M-Pesa TO MMF
    mmf_total_withdrawn = mmf_withdrawal_df[
        "paid_in"
    ].sum()  # withdrawing FROM MMF to M-Pesa

    # Net accumulation: positive = net saver, negative = net withdrawer
    mmf_net_flow = mmf_total_deposited - mmf_total_withdrawn

    # ================================================================
    # BLOCK 7 — Activity and velocity features
    # ================================================================
    active_days = df_active["date"].nunique()
    active_days_ratio = (active_days / statement_days) if statement_days > 0 else 0.0

    # Average time between transactions (in hours)
    if len(df_active) > 1:
        sorted_times = pd.to_datetime(df_active["completion_time"]).sort_values()
        time_diffs_hours = sorted_times.diff().dropna().dt.total_seconds() / 3600
        avg_hours_between_txns = (
            time_diffs_hours.median()
        )  # median is more robust than mean here
    else:
        avg_hours_between_txns = 0.0

    # Average transaction value (excluding fees)
    all_amounts = pd.concat([df_active["paid_in"], df_active["withdrawn"]])
    avg_txn_value = (
        all_amounts[all_amounts > 0].mean() if (all_amounts > 0).any() else 0.0
    )

    # ================================================================
    # BLOCK 8 — Seasonality / time-of-day features
    # ================================================================
    weekend_txns = df_active[df_active["day_of_week"] >= 5]  # Saturday=5, Sunday=6
    weekday_txns = df_active[df_active["day_of_week"] < 5]

    weekend_txn_ratio = (
        len(weekend_txns) / len(df_active) if len(df_active) > 0 else 0.0
    )

    # Night-time transactions (10pm–5am) — cash flow pressure indicator
    night_txns = df_active[
        df_active["hour"].between(22, 24) | df_active["hour"].between(0, 5)
    ]
    night_txn_ratio = len(night_txns) / len(df_active) if len(df_active) > 0 else 0.0

    # ================================================================
    # BLOCK 9 — Balance features
    # ================================================================
    has_gap = (
        bool(df["statement_has_gap"].any())
        if "statement_has_gap" in df.columns
        else False
    )

    if not has_gap:
        avg_balance = df_active["balance"].mean()
        min_balance = df_active["balance"].min()
        balance_stddev = df_active["balance"].std()
    else:
        # Don't trust balance figures if there are gaps
        avg_balance = None
        min_balance = None
        balance_stddev = None

    # ================================================================
    # BLOCK 10 — Statement quality flags
    # ================================================================
    total_transactions = len(df_active)
    other_txn_ratio = (
        (df_active["txn_type"] == "OTHER").sum() / total_transactions
        if total_transactions > 0
        else 0.0
    )

    # ================================================================
    # Assemble output
    # ================================================================
    features = {
        # Identity
        "customer_id": customer_id,
        # Statement window
        "statement_months": round(statement_months, 2),
        "statement_days": statement_days,
        "total_transactions": total_transactions,
        # Inflow
        "total_inflow": round(total_inflow, 2),
        "monthly_inflow_avg": round(monthly_inflow_avg, 2),
        "monthly_inflow_stddev": round(monthly_inflow_stddev, 2),
        "inflow_regularity_cv": round(inflow_cv, 4),  # lower = better
        "salary_detected": salary_detected,
        # Outflow
        "total_outflow": round(total_outflow, 2),
        "monthly_outflow_avg": round(monthly_outflow_avg, 2),
        "inflow_outflow_ratio": round(inflow_outflow_ratio, 4),
        "spend_to_income_ratio": round(spend_to_income_ratio, 4),
        # Utility payments
        "utility_payment_count": utility_count,
        "utility_payment_amount": round(utility_amount, 2),
        "utility_payment_ratio": round(utility_payment_ratio, 4),
        "utility_consistency": round(utility_consistency, 4),
        # Fuliza (overdraft)
        "fuliza_usage_count": fuliza_count,
        "fuliza_total_repaid": round(fuliza_total_repaid, 2),
        "fuliza_per_month": round(fuliza_per_month, 4),
        "fuliza_escalating": fuliza_escalating,
        # P2P
        "p2p_sent_count": p2p_sent_count,
        "p2p_received_count": p2p_received_count,
        "p2p_network_size": p2p_network_size,
        "p2p_sent_received_ratio": round(p2p_sent_received_ratio, 4),
        # MMF / savings
        "mmf_deposit_count": mmf_deposit_count,
        "mmf_withdrawal_count": mmf_withdrawal_count,
        "mmf_net_flow": round(mmf_net_flow, 2),
        # Activity
        "active_days": active_days,
        "active_days_ratio": round(active_days_ratio, 4),
        "avg_txn_value": round(avg_txn_value, 2),
        "avg_hours_between_txns": round(avg_hours_between_txns, 2),
        # Seasonality
        "weekend_txn_ratio": round(weekend_txn_ratio, 4),
        "night_txn_ratio": round(night_txn_ratio, 4),
        # Balance (None if statement has gaps)
        "avg_balance": round(avg_balance, 2) if avg_balance is not None else None,
        "min_balance": round(min_balance, 2) if min_balance is not None else None,
        "balance_stddev": round(balance_stddev, 2)
        if balance_stddev is not None
        else None,
        # Quality flags
        "statement_has_gap": has_gap,
        "other_txn_ratio": round(other_txn_ratio, 4),
    }

    return features


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _get_statement_months(df: pd.DataFrame) -> float:
    """Number of calendar months covered by the statement."""
    if df.empty or "completion_time" not in df.columns:
        return 0.0
    times = pd.to_datetime(df["completion_time"], errors="coerce").dropna()
    if times.empty:
        return 0.0
    delta_days = (times.max() - times.min()).days
    return max(delta_days / 30.44, 1.0)  # 30.44 = average days per month


def _get_statement_days(df: pd.DataFrame) -> int:
    """Total calendar days in the statement window."""
    if df.empty or "completion_time" not in df.columns:
        return 0
    times = pd.to_datetime(df["completion_time"], errors="coerce").dropna()
    if times.empty:
        return 0
    return max((times.max() - times.min()).days, 1)


def _count_unique_counterparties(p2p_df: pd.DataFrame) -> int:
    """
    Count unique phone numbers (counterparties) in P2P transaction details.
    M-Pesa masks numbers like 07******479 or 2547******073.
    We use the visible digits as a fingerprint.
    """
    if p2p_df.empty:
        return 0
    # Extract masked numbers — treat each unique masked pattern as one person
    pattern = re.compile(r"(07[\*\d]{7,9}|2547[\*\d]{6,8})")
    counterparties = set()
    for detail in p2p_df["details"].dropna():
        matches = pattern.findall(detail)
        counterparties.update(matches)
    return len(counterparties)


def _empty_features(customer_id: str = None) -> dict:
    """Return a zeroed feature dict for customers with no transactions."""
    return {
        "customer_id": customer_id,
        "statement_months": 0,
        "statement_days": 0,
        "total_transactions": 0,
        "total_inflow": 0,
        "monthly_inflow_avg": 0,
        "monthly_inflow_stddev": 0,
        "inflow_regularity_cv": 0,
        "salary_detected": False,
        "total_outflow": 0,
        "monthly_outflow_avg": 0,
        "inflow_outflow_ratio": 0,
        "spend_to_income_ratio": 0,
        "utility_payment_count": 0,
        "utility_payment_amount": 0,
        "utility_payment_ratio": 0,
        "utility_consistency": 0,
        "fuliza_usage_count": 0,
        "fuliza_total_repaid": 0,
        "fuliza_per_month": 0,
        "fuliza_escalating": False,
        "p2p_sent_count": 0,
        "p2p_received_count": 0,
        "p2p_network_size": 0,
        "p2p_sent_received_ratio": 0,
        "mmf_deposit_count": 0,
        "mmf_withdrawal_count": 0,
        "mmf_net_flow": 0,
        "active_days": 0,
        "active_days_ratio": 0,
        "avg_txn_value": 0,
        "avg_hours_between_txns": 0,
        "weekend_txn_ratio": 0,
        "night_txn_ratio": 0,
        "avg_balance": None,
        "min_balance": None,
        "balance_stddev": None,
        "statement_has_gap": False,
        "other_txn_ratio": 0,
    }
