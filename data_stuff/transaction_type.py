import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Known utility paybill codes
# ---------------------------------------------------------------------------
UTILITY_PAYBILLS = {
    "888880": "KPLC_PREPAID",
    "888884": "KPLC_POSTPAID",
    "880100": "NAIROBI_WATER",
    "400200": "ZUKU",
    "200999": "DSTV",
    "444700": "FAHARI_ELECTRICITY",
}

BANK_PAYBILLS = {
    "247247": "EQUITY_BANK",
    "522522": "SAFARICOM_MPESA",
    "329329": "STANCHART",
    "700200": "COOPERATIVE_BANK",
    "600100": "NCBA",
    "501901": "KCB",
}


def classify_transaction_type(df: pd.DataFrame, details_col: str = "details") -> pd.Series:
    """
    Vectorized classification of M-Pesa transaction details.
    Returns a Series of string labels aligned with df's index.
    """
    d = df[details_col].fillna("")

    # ------------------------------------------------------------------
    # Helper: case-insensitive contains, missing → False
    # ------------------------------------------------------------------
    def has(pattern: str) -> pd.Series:
        return d.str.contains(pattern, case=False, regex=True, na=False)

    # ------------------------------------------------------------------
    # 0. Reversals
    # ------------------------------------------------------------------
    is_reversal = has(r"Reversal|Refund")

    # ------------------------------------------------------------------
    # 1. Fuliza — must precede Merchant/PayBill
    # ------------------------------------------------------------------
    is_fuliza_repayment = has(r"Pay Bill Fuliza|Merchant Payment Fuliza")
    is_fuliza_other     = has(r"Fuliza")

    # ------------------------------------------------------------------
    # 2. MMF (savings)
    # ------------------------------------------------------------------
    is_mmf_withdrawal = has(r"Unit Trust Withdraw")
    is_mmf_deposit    = has(r"Unit Trust (?:Invest To|Deposit)")

    # ------------------------------------------------------------------
    # 3. Utility payments — one condition per known paybill code,
    #    plus keyword fallback
    # ------------------------------------------------------------------
    utility_conditions = []
    utility_choices    = []
    for code, name in UTILITY_PAYBILLS.items():
        utility_conditions.append(has(rf"\b{code}\b"))
        utility_choices.append(f"UTILITY_{name}")
    is_utility_keyword = has(r"KPLC|Kenya Power|Nairobi Water|ZUKU|DSTV|Fahari")

    # ------------------------------------------------------------------
    # 4. Salary / bank credits
    #    Resolved in two passes: known paybill first, generic fallback.
    # ------------------------------------------------------------------
    is_biz_payment = has(r"Business Payment from")

    bank_conditions = []
    bank_choices    = []
    for code, name in BANK_PAYBILLS.items():
        bank_conditions.append(is_biz_payment & has(rf"Business Payment from {code}"))
        bank_choices.append(f"BANK_CREDIT_{name}")
    is_salary_generic = is_biz_payment  # fallback when no code matched

    # ------------------------------------------------------------------
    # 5. M-Shwari / KCB M-PESA
    # ------------------------------------------------------------------
    is_mshwari_withdrawal  = has(r"M-Shwari (?:Withdraw|Lock)")
    is_mshwari_deposit     = has(r"M-Shwari (?:Deposit|In)")
    is_kcb_withdrawal      = has(r"KCB M-PESA Withdraw")
    is_kcb_deposit         = has(r"KCB M-PESA Deposit")

    # ------------------------------------------------------------------
    # 6. Airtime & data bundles
    # ------------------------------------------------------------------
    is_bundle  = has(r"Customer Bundle Purchase|Bundle Purchase|DATA BUNDLES")
    is_airtime = has(r"Airtime (?:Purchase|for)")

    # ------------------------------------------------------------------
    # 7. P2P sent
    # ------------------------------------------------------------------
    is_p2p_sent = (
        has(r"Customer Transfer to")
        | (has(r"Customer Payment to Small Business") & has(r"07\*{4,}|2547\*{4,}"))
    )

    # ------------------------------------------------------------------
    # 8. P2P received
    # ------------------------------------------------------------------
    is_p2p_received = has(r"Funds received from|Received Money")

    # ------------------------------------------------------------------
    # 9. Merchant / Buy Goods
    # ------------------------------------------------------------------
    is_merchant = (
        has(r"Merchant Payment to\s+\d{4,7}")
        | has(r"Customer Payment to Small Business")
    )

    # ------------------------------------------------------------------
    # 10. Paybill — general
    # ------------------------------------------------------------------
    is_bill_other = has(r"Pay Bill (?:Online )?to|Lipa na M-PESA.*Paybill")

    # ------------------------------------------------------------------
    # 11. Agent cash
    # ------------------------------------------------------------------
    is_agent_withdrawal = has(r"Withdraw Cash|Agent Withdrawal|Teller Withdrawal")
    is_agent_deposit    = has(r"Deposited by Agent|M-Pesa Deposit|Agent Deposit")

    # ------------------------------------------------------------------
    # 12. Transaction fees
    # ------------------------------------------------------------------
    is_fee = has(r"Transfer of Funds Charge|Pay Bill Charge|Transaction Cost|Withdraw Charge")

    # ------------------------------------------------------------------
    # Assemble conditions + choices in strict priority order
    # ------------------------------------------------------------------
    conditions = [
        is_reversal,
        is_fuliza_repayment,
        is_fuliza_other,
        is_mmf_withdrawal,
        is_mmf_deposit,
        *utility_conditions,        # one entry per known paybill code
        is_utility_keyword,
        *bank_conditions,           # one entry per known bank paybill
        is_salary_generic,
        is_mshwari_withdrawal,
        is_mshwari_deposit,
        is_kcb_withdrawal,
        is_kcb_deposit,
        is_bundle,
        is_airtime,
        is_p2p_sent,
        is_p2p_received,
        is_merchant,
        is_bill_other,
        is_agent_withdrawal,
        is_agent_deposit,
        is_fee,
    ]

    choices = [
        "REVERSAL",
        "FULIZA_REPAYMENT",
        "FULIZA_OTHER",
        "MMF_WITHDRAWAL",
        "MMF_DEPOSIT",
        *utility_choices,
        "UTILITY_PAYMENT",
        *bank_choices,
        "SALARY_OR_BANK_CREDIT",
        "MSHWARI_WITHDRAWAL",
        "MSHWARI_DEPOSIT",
        "KCB_MPESA_WITHDRAWAL",
        "KCB_MPESA_DEPOSIT",
        "BUNDLE_PURCHASE",
        "AIRTIME_PURCHASE",
        "P2P_SENT",
        "P2P_RECEIVED",
        "MERCHANT_PAYMENT",
        "BILL_PAYMENT_OTHER",
        "AGENT_WITHDRAWAL",
        "AGENT_DEPOSIT",
        "TRANSACTION_FEE",
    ]

    return pd.Series(
        np.select(conditions, choices, default="OTHER"),
        index=df.index,
        name="txn_type",
    )