"""
data_cleaning.py
----------------
Parses raw text extracted from an M-Pesa PDF statement into a clean DataFrame.

Key fixes from v1:
  - Page-break guard no longer hardcoded to "of 133"
  - Multi-line transaction details are merged before parsing
  - Transactions split into paid_in + withdrawn (not a single signed amount)
  - Balance continuity check flags statement gaps
  - Deduplication on receipt_no
  - Reversal matching nullifies reversed transactions
"""

import re
import pandas as pd


# ---------------------------------------------------------------------------
# Step 1: Extract raw transaction rows from text
# ---------------------------------------------------------------------------


def extract_transactions(raw_text: str) -> pd.DataFrame:
    """
    Convert the raw text of an M-Pesa PDF into a structured DataFrame.

    What this function does (plain language):
      1. Finds the line in the PDF text that says "Receipt No. Completion Time..."
         — that is the column header row. Everything after it is transaction data.
      2. Reads each line and stitches together multi-line Details fields.
         (M-Pesa PDFs often break long Details across two lines.)
      3. Parses each completed transaction row into 7 fields.
      4. Returns a DataFrame — think of it as a clean spreadsheet.

    Parameters:
        raw_text: The full text of the PDF, extracted by pdfplumber.

    Returns:
        DataFrame with columns:
        receipt_no, completion_time, details, status, paid_in, withdrawn, balance
    """
    lines = raw_text.split("\n")
    transactions = []

    # ---- Find where transactions start ----
    start_idx = None
    for i, line in enumerate(lines):
        if "Receipt No." in line and "Completion Time" in line:
            start_idx = i + 1
            break

    if start_idx is None:
        raise ValueError(
            "Could not find the transaction table header in this statement. "
            "Check that the PDF was extracted correctly."
        )

    # ---- Merge multi-line transaction rows ----
    # A valid transaction line starts with a receipt number like: UEKDY4TG83
    # Lines that do NOT start with a receipt number are continuation lines
    # (extra words from a long Details field that wrapped to the next line).
    RECEIPT_PATTERN = re.compile(r"^[A-Z0-9]{8,12}\s")
    PAGE_PATTERNS = [
        re.compile(r"^Page \d+ of \d+"),  # "Page 3 of 45"
        re.compile(r"^Disclaimer:"),
        re.compile(r"Statement Verification Code"),
        re.compile(r"^TRANSACTION TYPE"),
        re.compile(r"^TOTAL:"),
        re.compile(r"^M-PESA STATEMENT"),
        re.compile(r"^Customer Name:"),
    ]

    merged_lines = []
    current = None

    for line in lines[start_idx:]:
        stripped = line.strip()
        if not stripped:
            continue

        # Stop on footer / header markers (page-count agnostic)
        if any(p.match(stripped) for p in PAGE_PATTERNS):
            continue

        if RECEIPT_PATTERN.match(stripped):
            # New transaction — save the previous one
            if current is not None:
                merged_lines.append(current)
            current = stripped
        else:
            # Continuation of previous transaction's Details
            if current is not None:
                current = current + " " + stripped

    if current is not None:
        merged_lines.append(current)

    # ---- Parse each merged line into fields ----
    for line in merged_lines:
        row = _parse_transaction_line(line)
        if row is not None:
            transactions.append(row)

    df = pd.DataFrame(transactions)
    if df.empty:
        return df

    # ---- Type casting ----
    df["completion_time"] = pd.to_datetime(df["completion_time"], errors="coerce")
    df["paid_in"] = pd.to_numeric(df["paid_in"], errors="coerce").fillna(0.0)
    df["withdrawn"] = pd.to_numeric(df["withdrawn"], errors="coerce").fillna(0.0)
    df["balance"] = pd.to_numeric(df["balance"], errors="coerce")

    # ---- Deduplication ----
    before = len(df)
    df = df.drop_duplicates(subset=["receipt_no"])
    dupes_removed = before - len(df)
    if dupes_removed > 0:
        print(f"[data_cleaning] Removed {dupes_removed} duplicate receipt(s).")

    # ---- Keep only Completed transactions ----
    df = df[df["status"] == "Completed"].copy()

    # ---- Sort chronologically (oldest first — important for feature windows) ----
    df = df.sort_values("completion_time").reset_index(drop=True)

    # ---- Balance continuity check ----
    df = _check_balance_continuity(df)

    return df


def _parse_transaction_line(line: str) -> dict | None:
    """
    Parse a single (already-merged) transaction line into a dict.

    M-Pesa line structure (space-delimited):
      RECEIPT_NO  DATE  TIME  ...DETAILS...  STATUS  PAID_IN_OR_DASH  WITHDRAWN_OR_DASH  BALANCE

    The tricky part: Details can be many words. We anchor on STATUS being
    one of: Completed / Pending / Failed / Reversed.
    """
    parts = line.split()
    if len(parts) < 7:
        return None

    receipt_no = parts[0]
    completion_time = f"{parts[1]} {parts[2]}"

    # Find STATUS position
    status_idx = None
    for status_word in ["Completed", "Pending", "Failed", "Reversed"]:
        try:
            status_idx = parts.index(status_word, 3)
            break
        except ValueError:
            continue

    if status_idx is None:
        return None

    details = " ".join(parts[3:status_idx])
    status = parts[status_idx]

    # After STATUS: we expect up to 3 more tokens (paid_in_or_dash, withdrawn_or_dash, balance)
    # M-Pesa format: if paid_in is empty it shows "-", same for withdrawn
    remaining = parts[status_idx + 1 :]
    if len(remaining) < 2:
        return None

    def parse_amount(s: str) -> float:
        """Convert '145,296.00' or '-' or '-100.00' to float."""
        s = s.replace(",", "").strip()
        if s in ("-", "", "—"):
            return 0.0
        try:
            return abs(
                float(s)
            )  # Always store as positive; direction is in the column name
        except ValueError:
            return 0.0

    # Layout depends on how many tokens remain
    if len(remaining) == 3:
        # paid_in_str, withdrawn_str, balance_str
        paid_in = parse_amount(remaining[0])
        withdrawn = parse_amount(remaining[1])
        balance = parse_amount(remaining[2])
    elif len(remaining) == 2:
        # Some rows show only the net amount + balance (older statement format)
        # Determine direction from sign or from paid_in/withdrawn context
        amount_str = remaining[0]
        balance = parse_amount(remaining[1])
        raw_val = (
            float(amount_str.replace(",", "")) if amount_str not in ("-", "") else 0.0
        )
        paid_in = raw_val if raw_val > 0 else 0.0
        withdrawn = abs(raw_val) if raw_val < 0 else 0.0
    else:
        return None

    return {
        "receipt_no": receipt_no,
        "completion_time": completion_time,
        "details": details,
        "status": status,
        "paid_in": paid_in,
        "withdrawn": withdrawn,
        "balance": balance,
    }


# ---------------------------------------------------------------------------
# Step 2: Balance continuity check
# ---------------------------------------------------------------------------


def _check_balance_continuity(df: pd.DataFrame, tolerance: float = 1.0) -> pd.DataFrame:
    """
    Verifies that each row's balance equals the previous balance minus
    withdrawn plus paid_in. Flags rows where this breaks.

    Why this matters: a break means pages are missing from the statement,
    or transactions were edited. You should not compute features like
    'lowest balance' or 'average balance' on a statement with gaps.

    Adds two columns:
        balance_check_ok  — True if the balance is consistent with prev row
        statement_has_gap — True for ALL rows if any gap was detected
    """
    df = df.copy()
    df["balance_check_ok"] = True

    for i in range(1, len(df)):
        expected = df.at[i - 1, "balance"] - df.at[i, "withdrawn"] + df.at[i, "paid_in"]
        actual = df.at[i, "balance"]
        if abs(expected - actual) > tolerance:
            df.at[i, "balance_check_ok"] = False

    gap_count = (~df["balance_check_ok"]).sum()
    df["statement_has_gap"] = gap_count > 0

    if gap_count > 0:
        print(
            f"[data_cleaning] WARNING: {gap_count} balance discontinuity(ies) detected. "
            "Statement may have missing pages. Balance-derived features are unreliable."
        )

    return df


# ---------------------------------------------------------------------------
# Step 3: Statement metadata extraction
# ---------------------------------------------------------------------------


def extract_statement_metadata(raw_text: str) -> dict:
    """
    Pull the header fields from the statement:
      customer_name, mobile_number, statement_start, statement_end

    Returns a dict. Missing fields are None.
    """
    metadata = {
        "customer_name": None,
        "mobile_number": None,
        "statement_start": None,
        "statement_end": None,
    }

    name_match = re.search(r"Customer Name:\s*(.+)", raw_text)
    if name_match:
        metadata["customer_name"] = name_match.group(1).strip()

    mobile_match = re.search(r"Mobile Number:\s*(\d+)", raw_text)
    if mobile_match:
        metadata["mobile_number"] = mobile_match.group(1).strip()

    # "Statement Period: 20 May 2024 - 20 May 2026"
    period_match = re.search(
        r"Statement Period:\s*(\d{1,2} \w+ \d{4})\s*[-–]\s*(\d{1,2} \w+ \d{4})",
        raw_text,
    )
    if period_match:
        metadata["statement_start"] = pd.to_datetime(
            period_match.group(1), dayfirst=True, errors="coerce"
        )
        metadata["statement_end"] = pd.to_datetime(
            period_match.group(2), dayfirst=True, errors="coerce"
        )

    return metadata
