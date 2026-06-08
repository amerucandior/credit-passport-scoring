import asyncio
import logging
from app.downloader import download_statements
from app.models import StatementType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fetch all statements and collect features
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
        "mpesa_features": None,
        "bank_features": None,
        "sacco_features": None,
        "statements_ok": 0,
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
                stype,
                dl.get("error", "unknown error"),
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
