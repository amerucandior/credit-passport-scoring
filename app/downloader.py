"""
downloader.py
-------------
Downloads M-Pesa statement PDFs (or CSVs/Excel) from URLs,
extracts the raw text, and passes it through the cleaning pipeline.

"""

import asyncio
import io

import httpx
import pandas as pd
import pdfplumber

# Local modules
from data_stuff.data_cleaning import extract_transactions, extract_statement_metadata
from data_stuff.feature_calculation import calculate_customer_features

# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------
TIMEOUT_SECONDS = 30.0
MAX_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB
MAX_CONCURRENCY = 3


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------


def _detect_format(url: str, content_type: str) -> str:
    ext = url.split("?")[0].rsplit(".", 1)[-1].lower()
    ct = (content_type or "").lower()

    if ext == "csv" or "csv" in ct or "text/plain" in ct:
        return "csv"
    if ext in ("xls", "xlsx") or "spreadsheet" in ct or "excel" in ct:
        return "excel"
    if ext == "pdf" or "pdf" in ct:
        return "pdf"
    return "unknown"


# ---------------------------------------------------------------------------
# Parsers: bytes → raw text (for PDFs) or DataFrame (for CSV/Excel)
# ---------------------------------------------------------------------------


def _parse_csv(content: bytes) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(content))


def _parse_excel(content: bytes) -> pd.DataFrame:
    sheets = pd.read_excel(io.BytesIO(content), sheet_name=None)
    frames = []
    for sheet_name, df in sheets.items():
        df = df.copy()
        df["_sheet"] = sheet_name
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _extract_pdf_text(content: bytes) -> str:
    """
    Extract the full text from all pages of an M-Pesa PDF.
    """
    pages_text = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=3, y_tolerance=3)
            if text:
                pages_text.append(text)
                
    return "\n".join(pages_text)

# ---------------------------------------------------------------------------
# Top-level parse + clean + feature extraction
# ---------------------------------------------------------------------------


def parse_statement(
    content: bytes,
    content_type: str,
    url: str,
    compute_features: bool = True,
) -> dict:
    """
    Full pipeline: bytes → features dict.

    Returns a result dict with keys:
        success       : bool
        error         : str or None
        metadata      : dict (customer name, mobile, statement period)
        transactions  : list of dicts (clean transaction rows)
        features      : dict (credit scoring features) — if compute_features=True
        raw_text      : str (full PDF text) — useful for debugging misclassifications
    """
    fmt = _detect_format(url, content_type)
    result = {
        "success": False,
        "error": None,
        "metadata": {},
        "transactions": [],
        "features": {},
        "raw_text": "",
    }

    try:
        if fmt == "pdf":
            # Step 1: Extract raw text from PDF
            raw_text = _extract_pdf_text(content)
            result["raw_text"] = raw_text

            # Step 2: Extract statement metadata (name, mobile, period)
            result["metadata"] = extract_statement_metadata(raw_text)

            # Step 3: Parse into clean transaction DataFrame
            df = extract_transactions(raw_text)
            result["transactions"] = df.where(pd.notna(df), other=None).to_dict(
                orient="records"
            )

            # Step 4: Compute features
            if compute_features and not df.empty:
                customer_id = result["metadata"].get("mobile_number")
                result["features"] = calculate_customer_features(df, customer_id)

        elif fmt == "csv":
            df = _parse_csv(content)
            result["transactions"] = df.where(pd.notna(df), other=None).to_dict(
                orient="records"
            )

        elif fmt == "excel":
            df = _parse_excel(content)
            result["transactions"] = df.where(pd.notna(df), other=None).to_dict(
                orient="records"
            )

        else:
            result["error"] = (
                f"Unsupported format: url={url}, content-type={content_type}"
            )
            return result

        result["success"] = True

    except Exception as exc:
        result["error"] = str(exc)

    return result


# ---------------------------------------------------------------------------
# Async downloader
# ---------------------------------------------------------------------------


async def _download_one(
    client: httpx.AsyncClient,
    statement_url: str,
    statement_type: str,
    semaphore: asyncio.Semaphore,
) -> dict:
    async with semaphore:
        try:
            async with client.stream("GET", statement_url) as resp:
                resp.raise_for_status()

                content = bytearray()
                async for chunk in resp.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_SIZE_BYTES:
                        raise ValueError(
                            f"Statement exceeds max allowed size of {MAX_SIZE_BYTES} bytes"
                        )

                content_type = resp.headers.get("content-type", "")
                parse_result = parse_statement(
                    bytes(content), content_type, statement_url
                )

                return {
                    "statement_type": statement_type,
                    "statement_url": statement_url,
                    "size_bytes": len(content),
                    "content_type": content_type,
                    **parse_result,
                }

        except (httpx.HTTPError, ValueError) as exc:
            return {
                "statement_type": statement_type,
                "statement_url": statement_url,
                "success": False,
                "error": str(exc),
            }


async def download_statements(statements: list[dict]) -> list[dict]:
    """
    Fetch, parse, and extract features for every statement concurrently.

    Parameters:
        statements: list of dicts, each with keys:
                    { "statementUrl": str, "statementType": str }

    Returns:
        list of result dicts (one per statement), each containing
        success, error, metadata, transactions, and features.
    """
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    timeout = httpx.Timeout(TIMEOUT_SECONDS)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        tasks = [
            _download_one(client, s["statementUrl"], s["statementType"], semaphore)
            for s in statements
        ]
        return await asyncio.gather(*tasks)
