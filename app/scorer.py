from app.models import EmploymentStatus, ScoreRequest


def compute_score(req: ScoreRequest) -> dict:
    base = 500

    if req.monthlyIncomeKes:
        base += min(150, int(req.monthlyIncomeKes) // 5000)

    if req.employmentStatus in (EmploymentStatus.EMPLOYED, EmploymentStatus.SELF_EMPLOYED):
        base += 50

    statements = req.statements or []
    statement_count = len(statements)
    if statement_count > 0:
        base += 40

    statement_types = {s.statementType for s in statements}
    if len(statement_types) >= 3:
        base += 40

    if not req.isVerified:
        base -= 80

    score = max(300, min(1000, base))
    if score >= 700:
        band = "GOOD"
    elif score >= 550:
        band = "FAIR"
    else:
        band = "POOR"

    return {
        "creditScore": score,
        "creditScoreBand": band,
    }
