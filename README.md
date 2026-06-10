# Credit Passport Scoring

Credit Passport Scoring is a credit risk scoring API that extracts financial signals from M-Pesa, bank, and SACCO statements and returns a structured credit score with actionable improvement advice.

## Project summary

This project is a prototype credit scoring backend built with FastAPI, Pydantic, and async statement parsing. It:

- downloads and parses statement files from provided URLs
- extracts transaction features from M-Pesa and other statement formats
- applies a rule-based credit scoring engine
- returns a credit score, risk band, and improvement recommendations

The code is organized into a download/parser layer, a feature extraction layer, and a scoring/advice layer.

## Getting started

### Prerequisites

- Python 3.13+
- Git
- `pip`

### Install dependencies

This repository uses `pyproject.toml` as the primary dependency manifest.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
```

If the project is not yet installable via `pyproject.toml`, install dependencies directly:

```bash
python -m pip install -r requirements.txt
```

### Run locally

Start the FastAPI app with Uvicorn:

```bash
export SCORING_API_KEY="your-secret-key"
python -m uvicorn main:app --reload
```

The API will be available at `http://127.0.0.1:8000`.

## API routes

### GET /health

A simple health check endpoint.

Response:

```json
{ "status": "ok" }
```

### POST /score

Compute a credit score for a customer based on profile data and statement URLs.

Request body fields:

- `id` (string): unique request/customer identifier
- `natId` (string): national ID
- `gender` (optional): one of `MALE`, `FEMALE`, `OTHER`, `PREFER_NOT_TO_SAY`
- `isVerified` (boolean): whether the customer identity is verified
- `employmentStatus` (optional): one of `EMPLOYED`, `SELF_EMPLOYED`, `UNEMPLOYED`, `STUDENT`, `RETIRED`
- `monthlyIncomeKes` (optional): declared monthly income in KES
- `statements` (array): list of statement payloads

Each statement payload includes:

- `statementType`: `MPESA`, `BANK`, or `SACCO`
- `statementUrl`: URL of the statement file to parse

#### Request example

```bash
curl -X POST "http://127.0.0.1:8000/score" \
  -H "Content-Type: application/json" \
  -H "X-API-KEY: your-secret-key" \
  -d '{
    "id": "user-123",
    "natId": "12345678",
    "gender": "MALE",
    "isVerified": true,
    "employmentStatus": "EMPLOYED",
    "monthlyIncomeKes": 80000,
    "statements": [
      {
        "statementType": "MPESA",
        "statementUrl": "https://example.com/mpesa-statement.pdf"
      }
    ]
  }'
```

#### Response example

```json
{
  "creditScore": 720,
  "creditScoreBand": "GOOD",
  "improvement": {
    "pillars": {
      "INCOME": {
        "label": "Income Strength",
        "score": 85,
        "strengths": [
          {
            "label": "Observed Income",
            "explanation": "Your M-Pesa statement shows meaningful regular inflows.",
            "points": 150
          }
        ],
        "improvements": []
      }
    },
    "topActions": [],
    "strengthsSummary": [
      {
        "label": "Observed Income",
        "explanation": "Your M-Pesa statement shows meaningful regular inflows.",
        "points": 150
      }
    ],
    "scorePotential": 0
  }
}
```

## Environment variables

- `SCORING_API_KEY` — API key required by the `/score` endpoint. Set this value before starting the app.

## Repository structure

- `main.py` — FastAPI application entrypoint
- `app/` — API models and scoring orchestration
- `operations/` — statement download, feature build, and scoring logic
- `data_stuff/` — statement parsing and feature extraction utilities
- `pyproject.toml` — dependency manifest

## Notes

- The project is designed as a prototype; scoring is currently rule-based rather than ML-driven.
- Use `pyproject.toml` as the preferred dependency source.
- If you add new scoring signals, update both `operations/rule_based_scoring.py` and `operations/advice_engine.py`.
