import re

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

# ---------------------------------------------------------------------------
# Known salary/employer paybill prefixes
# ---------------------------------------------------------------------------
BANK_PAYBILLS = {
    "247247": "EQUITY_BANK",
    "522522": "SAFARICOM_MPESA",  # M-Pesa to bank
    "329329": "STANCHART",
    "700200": "COOPERATIVE_BANK",
    "600100": "NCBA",
    "501901": "KCB",
}


def classify_transaction_type(details: str) -> str:
    """
    Classify a single transaction by its Details string.
    Returns a string label. First match in priority order wins.

    Priority rationale:
      - Fuliza must come first: a Fuliza repayment also contains 'Merchant Payment'
        and 'Pay Bill' substrings. If you check those first, Fuliza is misclassified.
      - MMF must come before generic BILL_PAYMENT patterns.
      - Specific paybill utilities before the catch-all BILL_PAYMENT_OTHER.
      - REVERSAL before everything else so reversed transactions are never counted.
    """
    if not isinstance(details, str) or not details.strip():
        return "OTHER"

    d = details.strip()

    # ------------------------------------------------------------------
    # 0. Reversals — must be first, they modify other transaction types
    # ------------------------------------------------------------------
    if re.search(r"Reversal|REVERSAL|Refund", d, re.IGNORECASE):
        return "REVERSAL"

    # ------------------------------------------------------------------
    # 1. Fuliza — CRITICAL credit signal. Must precede Merchant/PayBill.
    #         sample: "Merchant Payment Fuliza M-Pesa to 6614845"
    #                 "Pay Bill Fuliza M-Pesa to 247247"
    # ------------------------------------------------------------------
    if re.search(r"Fuliza", d, re.IGNORECASE):
        if re.search(r"Pay Bill Fuliza|Merchant Payment Fuliza", d, re.IGNORECASE):
            return "FULIZA_REPAYMENT"
        return "FULIZA_OTHER"

    # ------------------------------------------------------------------
    # 2. MMF (savings) — before generic Unit Trust / Bill patterns
    #         sample: "Unit Trust Withdraw From 4145555 - ZIIDI MMF"
    #                 "Unit Trust Invest To 4145555 - ZIIDI MMF"
    # ------------------------------------------------------------------
    if re.search(r"Unit Trust Withdraw", d, re.IGNORECASE):
        return "MMF_WITHDRAWAL"
    if re.search(r"Unit Trust (Invest To|Deposit)", d, re.IGNORECASE):
        return "MMF_DEPOSIT"

    # ------------------------------------------------------------------
    # 3. Utility payments — match paybill codes AND keyword variants
    #    Handles: "Pay Bill Online to 888880", "Pay Bill to 888880"
    # ------------------------------------------------------------------
    for code, name in UTILITY_PAYBILLS.items():
        if re.search(rf"\b{code}\b", d):
            return f"UTILITY_{name}"
    # Keyword fallback for utilities not in the code list
    if re.search(r"KPLC|Kenya Power|Nairobi Water|ZUKU|DSTV|Fahari", d, re.IGNORECASE):
        return "UTILITY_PAYMENT"

    # ------------------------------------------------------------------
    # 4. Salary / bank credits — "Business Payment from <paybill>"
    #    Your sample: "Business Payment from 501901 - KCB 1 via API"
    # ------------------------------------------------------------------
    if re.search(r"Business Payment from", d, re.IGNORECASE):
        # Try to extract the paybill code to identify the employer
        match = re.search(r"Business Payment from (\d+)", d)
        if match:
            code = match.group(1)
            if code in BANK_PAYBILLS:
                return f"BANK_CREDIT_{BANK_PAYBILLS[code]}"
        return "SALARY_OR_BANK_CREDIT"

    # ------------------------------------------------------------------
    # 5. M-Shwari / KCB M-PESA (savings products)
    # ------------------------------------------------------------------
    if re.search(r"M-Shwari (Withdraw|Lock)", d, re.IGNORECASE):
        return "MSHWARI_WITHDRAWAL"
    if re.search(r"M-Shwari (Deposit|In)", d, re.IGNORECASE):
        return "MSHWARI_DEPOSIT"
    if re.search(r"KCB M-PESA Withdraw", d, re.IGNORECASE):
        return "KCB_MPESA_WITHDRAWAL"
    if re.search(r"KCB M-PESA Deposit", d, re.IGNORECASE):
        return "KCB_MPESA_DEPOSIT"

    # ------------------------------------------------------------------
    # 6. Airtime and data bundles
    # ------------------------------------------------------------------
    if re.search(
        r"Customer Bundle Purchase|Bundle Purchase|DATA BUNDLES", d, re.IGNORECASE
    ):
        return "BUNDLE_PURCHASE"
    if re.search(r"Airtime (Purchase|for)", d, re.IGNORECASE):
        return "AIRTIME_PURCHASE"

    # ------------------------------------------------------------------
    # 7. P2P sent — two variants in M-Pesa
    #    "Customer Transfer to - 07******194 MUNYAO MWONGELA"  (send money)
    #    "Customer Payment to Small Business to - 07******479"  (till-less)
    # ------------------------------------------------------------------
    if re.search(r"Customer Transfer to", d, re.IGNORECASE):
        return "P2P_SENT"
    if re.search(
        r"Customer Payment to Small Business.*?(07\*{4,}|2547\*{4,})", d, re.IGNORECASE
    ):
        return "P2P_SENT"

    # ------------------------------------------------------------------
    # 8. P2P received
    #    "Funds received from - 2547******073 FRANKLINE JAMLICK"
    # ------------------------------------------------------------------
    if re.search(r"Funds received from|Received Money", d, re.IGNORECASE):
        return "P2P_RECEIVED"

    # ------------------------------------------------------------------
    # 9. Merchant / Buy Goods (till numbers — typically 5–7 digits)
    #    "Merchant Payment to 3566421 - GOLDENMART VENTURES"
    #    "Customer Payment to Small Business to - 07... MILCAH KAMAU"
    #    NOTE: Small Business WITHOUT a masked number is a merchant till
    # ------------------------------------------------------------------
    if re.search(r"Merchant Payment to\s+\d{4,7}", d, re.IGNORECASE):
        return "MERCHANT_PAYMENT"
    if re.search(r"Customer Payment to Small Business", d, re.IGNORECASE):
        return "MERCHANT_PAYMENT"

    # ------------------------------------------------------------------
    # 10. Paybill — general (not caught by utilities above)
    # ------------------------------------------------------------------
    if re.search(r"Pay Bill (Online )?to|Lipa na M-PESA.*Paybill", d, re.IGNORECASE):
        return "BILL_PAYMENT_OTHER"

    # ------------------------------------------------------------------
    # 11. Agent cash transactions
    # ------------------------------------------------------------------
    if re.search(r"Withdraw Cash|Agent Withdrawal|Teller Withdrawal", d, re.IGNORECASE):
        return "AGENT_WITHDRAWAL"
    if re.search(r"Deposited by Agent|M-Pesa Deposit|Agent Deposit", d, re.IGNORECASE):
        return "AGENT_DEPOSIT"

    # ------------------------------------------------------------------
    # 12. Transaction charges
    # ------------------------------------------------------------------
    if re.search(
        r"(Transfer of Funds Charge|Pay Bill Charge|Transaction Cost|Withdraw Charge)",
        d,
        re.IGNORECASE,
    ):
        return "TRANSACTION_FEE"

    return "OTHER"
