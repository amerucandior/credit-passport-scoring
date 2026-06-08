import os

from fastapi import FastAPI, Header, HTTPException

from app.models import ScoreRequest, ScoreResponse
from app.scorer import compute_score
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("SCORING_API_KEY")

app = FastAPI(title="Credit Passport Scoring", version="0.1.0")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/score", response_model=ScoreResponse)
def score(
    body: ScoreRequest,
    x_api_key: str | None = Header(default=None, alias="X-API-KEY"),
):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    if not body.statements:
        raise HTTPException(
            status_code=400,
            detail="At least one financial statement is required for credit scoring",
        )
    result = compute_score(body)
    return ScoreResponse(**result)
