"""
test_score_pipeline.py
----------------------
Integration test for the full /score pipeline.

What this tests (in plain language):
  1. A mock PDF file is served at a fake URL (no real internet needed)
  2. ScoreRequest is built exactly as the frontend would send it
  3. compute_score() runs the full pipeline: download → parse → features → score
  4. We assert the response is valid and the score reflects real features

Run with:
  pip install pytest respx httpx pdfplumber pandas
  pytest test_score_pipeline.py -v
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))

import asyncio
import io
from decimal import Decimal
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


from app.models import (
    ScoreRequest,
    StatementPayload,
    StatementType,
    EmploymentStatus,
    Gender,
)
from app.scorer import compute_score, score_from_features, _build_feature_set


# ---------------------------------------------------------------------------
# Sample M-Pesa statement text (trimmed but structurally valid)
# ---------------------------------------------------------------------------

SAMPLE_MPESA_TEXT = """
M-PESA STATEMENT
Customer Name: JAMLICK MBAABU MUTHURI
Mobile Number: 0714225936
Email Address: ianmwirigi638@gmail.com
Statement Period: 01 January 2025 - 30 June 2025
Request Date: 01 July 2025

Receipt No. Completion Time Details Transaction Status Paid In Withdrawn Balance
UEKDY4TG83 2025-06-20 08:01:34 Customer Payment to Small Business to - 07******479 Stephen Paul Completed 0 100.00 5000.00
UEKDY4TAJN 2025-06-18 07:45:04 Customer Transfer to - 07******194 MUNYAO MWONGELA Completed 0 500.00 5100.00
UEKDY4TEJQ 2025-06-15 07:42:51 Unit Trust Withdraw From 4145555 - ZIIDI MMF by M-PESA UnitTrust Completed 2000.00 0 5600.00
UEJDY4SE2D 2025-05-30 20:15:15 Pay Bill Online to 888880 - KPLC PREPAID Acc. 37169986496 Completed 0 500.00 3600.00
UEJOY4J1ES 2025-05-20 20:05:21 Funds received from - 2547******073 FRANKLINE JAMLICK Completed 5000.00 0 4100.00
UEIDY4MF8I 2025-04-18 09:47:56 Merchant Payment to 3566421 - GOLDENMART VENTURES LTD Completed 0 185.00 6000.00
UEIDY4MI0L 2025-04-16 09:47:29 Unit Trust Invest To 4145555 - ZIIDI MMF by M-PESA UnitTrust Completed 0 2000.00 6185.00
UEHDY4LAJW 2025-03-17 21:12:55 Business Payment from 501901 - KCB 1 via API. Original conversation ID is MBNHEF3DQWYIW9OA. Completed 30000.00 0 8185.00
UEHDY4LDB8 2025-03-01 21:12:26 Pay Bill Online to 888880 - KPLC PREPAID Acc. 37169986496 Completed 0 600.00 6000.00
UEGDY4EP58 2025-02-16 10:56:31 Merchant Payment Fuliza M-Pesa to 6614845 - Goldenmart Ventures Completed 0 110.00 0.00
UEFDY4CF93 2025-01-15 18:14:25 Business Payment from 501901 - KCB 1 via API. Completed 30000.00 0 5000.00
UEFDY4BY6E 2025-01-10 17:44:55 Customer Bundle Purchase to 4093441 SAFARICOM DATA BUNDLES by - 2547936 JAMLICK MUTHURI Completed 0 20.00 2000.00
"""


# ---------------------------------------------------------------------------
# Test 1: Transaction classifier (unit test — no network needed)
# ---------------------------------------------------------------------------


class TestTransactionClassifier:
    def test_fuliza_repayment_classified_correctly(self):
        from data_stuff.transaction_type import classify_transaction_type

        result = classify_transaction_type(
            "Merchant Payment Fuliza M-Pesa to 6614845 - Goldenmart Ventures"
        )
        assert result == "FULIZA_REPAYMENT", f"Got: {result}"

    def test_kplc_utility_classified_correctly(self):
        from data_stuff.transaction_type import classify_transaction_type

        result = classify_transaction_type(
            "Pay Bill Online to 888880 - KPLC PREPAID Acc. 37169986496"
        )
        assert result == "UTILITY_KPLC_PREPAID", f"Got: {result}"

    def test_p2p_received_classified_correctly(self):
        from data_stuff.transaction_type import classify_transaction_type

        result = classify_transaction_type(
            "Funds received from - 2547******073 FRANKLINE JAMLICK"
        )
        assert result == "P2P_RECEIVED", f"Got: {result}"

    def test_mmf_withdrawal_classified_correctly(self):
        from data_stuff.transaction_type import classify_transaction_type

        result = classify_transaction_type(
            "Unit Trust Withdraw From 4145555 - ZIIDI MMF by M-PESA UnitTrust"
        )
        assert result == "MMF_WITHDRAWAL", f"Got: {result}"

    def test_salary_from_kcb_api(self):
        from data_stuff.transaction_type import classify_transaction_type

        result = classify_transaction_type(
            "Business Payment from 501901 - KCB 1 via API."
        )
        assert result == "BANK_CREDIT_KCB", f"Got: {result}"

    def test_none_input_returns_other(self):
        from data_stuff.transaction_type import classify_transaction_type

        assert classify_transaction_type(None) == "OTHER"
        assert classify_transaction_type("") == "OTHER"


# ---------------------------------------------------------------------------
# Test 2: Data cleaning (unit test)
# ---------------------------------------------------------------------------


class TestDataCleaning:
    def test_extract_transactions_from_sample_text(self):
        from data_stuff.data_cleaning import extract_transactions

        df = extract_transactions(SAMPLE_MPESA_TEXT)

        assert not df.empty, "DataFrame should not be empty"
        assert "receipt_no" in df.columns
        assert "paid_in" in df.columns
        assert "withdrawn" in df.columns
        assert "balance" in df.columns
        assert "details" in df.columns

    def test_paid_in_and_withdrawn_are_positive(self):
        from data_stuff.data_cleaning import extract_transactions

        df = extract_transactions(SAMPLE_MPESA_TEXT)
        assert (df["paid_in"] >= 0).all(), "paid_in should never be negative"
        assert (df["withdrawn"] >= 0).all(), "withdrawn should never be negative"

    def test_deduplication(self):
        from data_stuff.data_cleaning import extract_transactions

        # Feed same text twice — should deduplicate on receipt_no
        df = extract_transactions(SAMPLE_MPESA_TEXT + SAMPLE_MPESA_TEXT)
        receipt_counts = df["receipt_no"].value_counts()
        assert receipt_counts.max() == 1, "Duplicate receipt_nos found after dedup"

    def test_metadata_extraction(self):
        from data_stuff.data_cleaning import extract_statement_metadata

        meta = extract_statement_metadata(SAMPLE_MPESA_TEXT)
        assert meta["customer_name"] == "JAMLICK MBAABU MUTHURI"
        assert meta["mobile_number"] == "0714225936"
        assert meta["statement_start"] is not None
        assert meta["statement_end"] is not None


# ---------------------------------------------------------------------------
# Test 3: Feature calculation (unit test)
# ---------------------------------------------------------------------------


class TestFeatureCalculation:
    def _get_df(self):
        from data_stuff.data_cleaning import extract_transactions

        return extract_transactions(SAMPLE_MPESA_TEXT)

    def test_features_returns_dict(self):
        from data_stuff.feature_calculation import calculate_customer_features

        df = self._get_df()
        features = calculate_customer_features(df)
        assert isinstance(features, dict)

    def test_inflow_is_positive(self):
        from data_stuff.feature_calculation import calculate_customer_features

        df = self._get_df()
        features = calculate_customer_features(df)
        assert features["total_inflow"] > 0

    def test_fuliza_detected(self):
        from data_stuff.feature_calculation import calculate_customer_features

        df = self._get_df()
        features = calculate_customer_features(df)
        # Sample text has one Fuliza repayment
        assert features["fuliza_usage_count"] >= 1, "Fuliza repayment not detected"

    def test_utility_detected(self):
        from data_stuff.feature_calculation import calculate_customer_features

        df = self._get_df()
        features = calculate_customer_features(df)
        assert features["utility_payment_count"] >= 1, (
            "KPLC utility payment not detected"
        )

    def test_salary_detected(self):
        from data_stuff.feature_calculation import calculate_customer_features

        df = self._get_df()
        features = calculate_customer_features(df)
        assert features["salary_detected"] is True, "KCB salary credit not detected"

    def test_empty_df_returns_zeros(self):
        import pandas as pd
        from data_stuff.feature_calculation import calculate_customer_features

        features = calculate_customer_features(pd.DataFrame())
        assert features["total_inflow"] == 0
        assert features["salary_detected"] is False

    def test_no_mutation_of_input(self):
        """calculate_customer_features must not add columns to the caller's df."""
        import pandas as pd
        from data_stuff.feature_calculation import calculate_customer_features

        df = self._get_df()
        original_columns = set(df.columns)
        calculate_customer_features(df)
        assert set(df.columns) == original_columns, (
            "calculate_customer_features mutated the input DataFrame"
        )


# ---------------------------------------------------------------------------
# Test 4: Scoring engine (unit test — no network)
# ---------------------------------------------------------------------------


class TestScoringEngine:
    def _good_features(self):
        """Feature set for a clearly creditworthy applicant."""
        return {
            "is_verified": True,
            "employment_status": "EMPLOYED",
            "declared_income": 50000.0,
            "statements_ok": 1,
            "statements_failed": 0,
            "has_mpesa": True,
            "has_bank": False,
            "has_sacco": False,
            "observed_monthly_inflow": 48000.0,
            "income_verification_ratio": 0.96,  # matches declared
            "inflow_regularity_cv": 0.15,  # very regular
            "salary_detected": True,
            "spend_to_income_ratio": 0.65,  # spends 65%
            "inflow_outflow_ratio": 1.35,
            "avg_balance": 15000.0,
            "min_balance": 500.0,
            "utility_consistency": 0.9,
            "utility_payment_ratio": 0.08,
            "fuliza_per_month": 0.0,
            "fuliza_escalating": False,
            "fuliza_total_repaid": 0.0,
            "mmf_net_flow": 5000.0,
            "mmf_deposit_count": 8,
            "active_days_ratio": 0.7,
            "statement_months": 12.0,
            "statement_has_gap": False,
            "other_txn_ratio": 0.02,
        }

    def _risky_features(self):
        """Feature set for a high-risk applicant."""
        return {
            "is_verified": False,
            "employment_status": "UNEMPLOYED",
            "declared_income": 100000.0,
            "statements_ok": 1,
            "statements_failed": 0,
            "has_mpesa": True,
            "has_bank": False,
            "has_sacco": False,
            "observed_monthly_inflow": 5000.0,  # declared 100k, observed 5k
            "income_verification_ratio": 0.05,  # massive mismatch
            "inflow_regularity_cv": 1.8,  # very irregular
            "salary_detected": False,
            "spend_to_income_ratio": 1.4,  # spending 40% more than earning
            "inflow_outflow_ratio": 0.7,
            "avg_balance": 200.0,
            "min_balance": 0.0,
            "utility_consistency": 0.1,
            "utility_payment_ratio": 0.01,
            "fuliza_per_month": 5.0,
            "fuliza_escalating": True,
            "fuliza_total_repaid": 8000.0,
            "mmf_net_flow": -1000.0,
            "mmf_deposit_count": 2,
            "active_days_ratio": 0.3,
            "statement_months": 2.0,
            "statement_has_gap": True,
            "other_txn_ratio": 0.15,
        }

    def test_good_applicant_scores_high(self):
        score, band, _ = score_from_features(self._good_features())
        assert score >= 700, f"Good applicant should score GOOD, got {score}"
        assert band == "GOOD"

    def test_risky_applicant_scores_low(self):
        score, band, _ = score_from_features(self._risky_features())
        assert score < 550, f"Risky applicant should score POOR/FAIR, got {score}"

    def test_score_always_in_range(self):
        """Score must always be between 300 and 1000 regardless of inputs."""
        score, _, _ = score_from_features(self._good_features())
        assert 300 <= score <= 1000

        score, _, _ = score_from_features(self._risky_features())
        assert 300 <= score <= 1000

    def test_breakdown_is_returned(self):
        _, _, breakdown = score_from_features(self._good_features())
        assert isinstance(breakdown, dict)
        assert len(breakdown) > 0


# ---------------------------------------------------------------------------
# Test 5: Full pipeline with mocked HTTP (integration test)
# ---------------------------------------------------------------------------


class TestFullPipeline:
    """
    Tests the entire compute_score() function end-to-end.
    We mock the HTTP layer so no real internet is needed.
    The mock returns our SAMPLE_MPESA_TEXT as a fake PDF.
    """

    def _make_fake_pdf_bytes(self) -> bytes:
        """
        Create a minimal fake PDF that pdfplumber can open.
        We mock pdfplumber.open() to return our sample text instead,
        so this just needs to be valid bytes.
        """
        return b"%PDF-1.4 fake"

    def test_compute_score_with_mocked_download(self):
        """
        Full pipeline test:
        1. HTTP GET is mocked to return fake PDF bytes
        2. pdfplumber.open() is mocked to return our sample statement text
        3. compute_score() runs the full pipeline
        4. We assert a valid ScoreResponse is produced
        """
        req = ScoreRequest(
            id="test-applicant-001",
            natId="12345678",
            gender=Gender.MALE,
            isVerified=True,
            employmentStatus=EmploymentStatus.EMPLOYED,
            monthlyIncomeKes=Decimal("30000"),
            statements=[
                StatementPayload(
                    statementType=StatementType.MPESA,
                    statementUrl="https://fake-storage.example.com/statements/test.pdf",
                )
            ],
        )

        fake_pdf_bytes = self._make_fake_pdf_bytes()

        # Mock the HTTP response
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {"content-type": "application/pdf"}

        async def fake_aiter_bytes():
            yield fake_pdf_bytes

        mock_response.aiter_bytes = fake_aiter_bytes
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_client = MagicMock()
        mock_client.stream = MagicMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        # Mock pdfplumber to return our sample text
        mock_page = MagicMock()
        mock_page.extract_text = MagicMock(return_value=SAMPLE_MPESA_TEXT)

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("pdfplumber.open", return_value=mock_pdf),
        ):
            result = compute_score(req)

        # Validate response structure
        assert "creditScore" in result
        assert "creditScoreBand" in result
        assert 300 <= result["creditScore"] <= 1000
        assert result["creditScoreBand"] in ("GOOD", "FAIR", "POOR")

    def test_score_without_statements_still_returns_valid(self):
        """
        Edge case: request with no statements.
        Should still return a valid score (penalised for lack of data).
        """
        req = ScoreRequest(
            id="test-no-statements",
            natId="99999999",
            isVerified=False,
            employmentStatus=EmploymentStatus.UNEMPLOYED,
            statements=[],
        )
        # FastAPI route rejects empty statements before reaching scorer,
        # but scorer itself should handle it gracefully too
        result = compute_score(req)
        assert 300 <= result["creditScore"] <= 1000
        assert result["creditScoreBand"] in ("GOOD", "FAIR", "POOR")

    def test_failed_download_does_not_crash_scorer(self):
        """
        If the PDF URL returns a 404 or connection error,
        compute_score should still return a valid (low) score,
        not raise an exception.
        """
        req = ScoreRequest(
            id="test-bad-url",
            natId="11111111",
            isVerified=True,
            employmentStatus=EmploymentStatus.EMPLOYED,
            monthlyIncomeKes=Decimal("50000"),
            statements=[
                StatementPayload(
                    statementType=StatementType.MPESA,
                    statementUrl="https://fake-storage.example.com/404.pdf",
                )
            ],
        )

        import httpx

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.__aenter__ = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "404 Not Found",
                request=MagicMock(),
                response=MagicMock(status_code=404),
            )
        )
        mock_client.stream = MagicMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = compute_score(req)

        assert 300 <= result["creditScore"] <= 1000
        assert result["creditScoreBand"] in ("GOOD", "FAIR", "POOR")


# ---------------------------------------------------------------------------
# Run directly with: python test_score_pipeline.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import subprocess

    subprocess.run(["python", "-m", "pytest", __file__, "-v"])
