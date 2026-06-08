"""
advice_engine.py
----------------
Translates raw scoring signals into human-friendly financial advice.

Design philosophy:
  - Every signal that costs the user points must come with a concrete,
    actionable improvement tip — not generic "save more money" advice.
  - Advice is grouped into PILLARS (thematic areas), so the user sees
    their strongest and weakest financial dimensions at a glance.
  - Each pillar has a sub-score (0–100) so the frontend can draw a
    radar/spider chart. The sub-scores are derived from the same
    breakdown dict the scoring engine already produces — no double work.
  - Positive signals become "strengths" shown to the user (motivation).
  - Negative signals become "improvement areas" with ranked priority.

Pillars:
    INCOME       — how much comes in, how regularly, how verified
    SPENDING     — whether outflows are sustainable vs income
    REPAYMENT    — utility bill consistency (best proxy for loan repayment)
    SAVINGS      — MMF / M-Shwari activity
    DATA_QUALITY — statement completeness, coverage, classification rate

Adding a new rule:
    1. Add the scoring logic in rule_based_scoring.py (e.g. breakdown["new_key"] = +30)
    2. Add an entry in SIGNAL_CATALOGUE below with the same key.
    Done. Nothing else to change.
"""

from dataclasses import dataclass, field
from typing import Literal


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

Pillar = Literal["INCOME", "SPENDING", "REPAYMENT", "SAVINGS", "DATA_QUALITY"]
Sentiment = Literal["positive", "negative", "neutral"]


@dataclass
class SignalAdvice:
    """What we tell the user about one scoring signal."""
    pillar: Pillar
    sentiment: Sentiment
    # Short label shown in the UI (e.g. "Consistent Income")
    label: str
    # One sentence: what this signal means in plain language
    explanation: str
    # What the user should DO to fix or maintain this (shown only for negative signals)
    action: str | None = None
    # Priority 1 = most important to fix, 3 = nice-to-have
    priority: int = 2


# ---------------------------------------------------------------------------
# Signal catalogue — one entry per possible breakdown key
# ---------------------------------------------------------------------------
# To add a new rule: add its breakdown key here. The scoring engine key
# (in rule_based_scoring.py) must exactly match the key in this dict.

SIGNAL_CATALOGUE: dict[str, SignalAdvice] = {
    # ----------------------------------------------------------------
    # Identity & Verification
    # ----------------------------------------------------------------
    "verified": SignalAdvice(
        pillar="DATA_QUALITY",
        sentiment="positive",
        label="Identity Verified",
        explanation="Your identity has been verified, which builds lender trust.",
    ),
    "not_verified": SignalAdvice(
        pillar="DATA_QUALITY",
        sentiment="negative",
        label="Identity Not Verified",
        explanation="Lenders cannot confirm who you are, which significantly lowers confidence.",
        action="Complete identity verification with your National ID. "
               "This is the single highest-impact action you can take.",
        priority=1,
    ),

    # ----------------------------------------------------------------
    # Employment
    # ----------------------------------------------------------------
    "employment_formal": SignalAdvice(
        pillar="INCOME",
        sentiment="positive",
        label="Formally Employed or Self-Employed",
        explanation="You have a declared source of stable income.",
    ),
    "employment_student": SignalAdvice(
        pillar="INCOME",
        sentiment="neutral",
        label="Student Status",
        explanation="Student status is noted. Income history matters more than employment label.",
    ),
    "employment_retired": SignalAdvice(
        pillar="INCOME",
        sentiment="neutral",
        label="Retired",
        explanation="Retirement is noted. Pension regularity and savings are the key signals lenders watch.",
    ),

    # ----------------------------------------------------------------
    # Income
    # ----------------------------------------------------------------
    "income": SignalAdvice(
        pillar="INCOME",
        sentiment="positive",
        label="Observed Income",
        explanation="Your M-Pesa statement shows meaningful regular inflows.",
    ),
    "income_inflation_penalty": SignalAdvice(
        pillar="INCOME",
        sentiment="negative",
        label="Declared Income Much Higher Than Observed",
        explanation="Your stated monthly income is more than 3x what your M-Pesa statement shows. "
                    "This creates a red flag for lenders.",
        action="Ensure your declared income matches what actually flows through your M-Pesa or bank. "
               "If you receive income in cash or via a bank account, upload that statement too.",
        priority=1,
    ),
    "income_underdeclaration": SignalAdvice(
        pillar="INCOME",
        sentiment="negative",
        label="Possible Income Under-declaration",
        explanation="Your M-Pesa inflows are significantly higher than what you declared. "
                    "This suggests under-reporting, which lenders view cautiously.",
        action="Update your declared monthly income to reflect what actually arrives in your accounts.",
        priority=3,
    ),
    "income_regular": SignalAdvice(
        pillar="INCOME",
        sentiment="positive",
        label="Highly Regular Income",
        explanation="Your income arrives consistently each month with very little variation — "
                    "a strong indicator of financial stability.",
    ),
    "income_moderate": SignalAdvice(
        pillar="INCOME",
        sentiment="neutral",
        label="Moderately Regular Income",
        explanation="Your income is somewhat consistent but varies month-to-month.",
    ),
    "salary_detected": SignalAdvice(
        pillar="INCOME",
        sentiment="positive",
        label="Salary Deposits Detected",
        explanation="Your statement shows what appears to be regular salary payments — "
                    "the strongest income signal for lenders.",
    ),

    # ----------------------------------------------------------------
    # Spending / Solvency
    # ----------------------------------------------------------------
    "solvency_strong": SignalAdvice(
        pillar="SPENDING",
        sentiment="positive",
        label="Healthy Spending Rate",
        explanation="You spend 70% or less of what you earn — a sign of strong financial discipline.",
    ),
    "solvency_ok": SignalAdvice(
        pillar="SPENDING",
        sentiment="positive",
        label="Acceptable Spending Rate",
        explanation="You spend between 70–90% of your income. "
                    "There is room to build a larger buffer.",
    ),
    "solvency_tight": SignalAdvice(
        pillar="SPENDING",
        sentiment="neutral",
        label="Tight Budget",
        explanation="You are spending close to 100% of what you earn, leaving very little margin.",
        action="Try to reduce discretionary spending (merchant payments, peer transfers) "
               "to bring your spending below 90% of income. Even small reductions compound over months.",
        priority=2,
    ),
    "solvency_deficit": SignalAdvice(
        pillar="SPENDING",
        sentiment="negative",
        label="Spending Exceeds Income",
        explanation="Your outflows are higher than your inflows. "
                    "This is the strongest negative signal a lender can see.",
        action="Audit your M-Pesa transactions for the past 3 months. "
               "Identify your top 3 spending categories and set a monthly cap for each. "
               "Eliminating even one non-essential category (e.g., frequent merchant purchases) "
               "can flip this signal from negative to neutral within 2 months.",
        priority=1,
    ),

    # ----------------------------------------------------------------
    # Repayment behaviour (utility bills as proxy)
    # ----------------------------------------------------------------
    "utility_consistent": SignalAdvice(
        pillar="REPAYMENT",
        sentiment="positive",
        label="Consistent Bill Payments",
        explanation="You pay utility bills (electricity, water, etc.) in most months. "
                    "Lenders treat this as strong evidence you will repay loans on time.",
    ),
    "utility_moderate": SignalAdvice(
        pillar="REPAYMENT",
        sentiment="neutral",
        label="Occasional Bill Payments",
        explanation="You pay bills in some months but not consistently.",
        action="Set up monthly reminders or auto-payment for KPLC and water bills. "
               "Paying these via M-Pesa every month builds a track record that directly "
               "raises your credit score.",
        priority=2,
    ),
    "utility_low": SignalAdvice(
        pillar="REPAYMENT",
        sentiment="negative",
        label="Rare Bill Payments",
        explanation="Very few utility payments were detected in your statement.",
        action="Start paying at least one recurring bill (electricity, water, rent paybill) "
               "through M-Pesa every month. Even 3 consecutive months of consistent payments "
               "will improve this signal.",
        priority=2,
    ),
    "utility_ratio_ok": SignalAdvice(
        pillar="REPAYMENT",
        sentiment="positive",
        label="Bills Are Part of Your Spending",
        explanation="A meaningful portion of your outflows go to bills — "
                    "showing financial responsibility.",
    ),

    # ----------------------------------------------------------------
    # Fuliza / Overdraft risk
    # ----------------------------------------------------------------
    "fuliza_low": SignalAdvice(
        pillar="SPENDING",
        sentiment="negative",
        label="Occasional Fuliza Usage",
        explanation="You use Fuliza (M-Pesa overdraft) occasionally. "
                    "This shows you sometimes run short of funds.",
        action="Build a small emergency buffer of 3,000–5,000 KES kept in M-Pesa or M-Shwari. "
               "This eliminates the need for Fuliza and removes this penalty.",
        priority=3,
    ),
    "fuliza_moderate": SignalAdvice(
        pillar="SPENDING",
        sentiment="negative",
        label="Regular Fuliza Usage",
        explanation="You use Fuliza 1–3 times per month. This signals that your income "
                    "does not reliably cover your monthly expenses.",
        action="Track which days of the month you run out of funds. "
               "Move a fixed amount to M-Shwari at the start of every month as a buffer. "
               "Reducing Fuliza to once per month or less will improve this score within 60 days.",
        priority=2,
    ),
    "fuliza_high": SignalAdvice(
        pillar="SPENDING",
        sentiment="negative",
        label="Heavy Fuliza Dependence",
        explanation="You use Fuliza more than 3 times per month. "
                    "Lenders view this as a high risk of loan default.",
        action="This is your most urgent financial improvement area. "
               "Stop spending on non-essentials for 30 days and redirect that money to a buffer. "
               "Consider a structured budget: 50% essentials, 20% savings, 30% discretionary. "
               "Eliminating Fuliza usage entirely adds back up to 90 points to your score.",
        priority=1,
    ),
    "fuliza_escalating": SignalAdvice(
        pillar="SPENDING",
        sentiment="negative",
        label="Fuliza Usage is Increasing",
        explanation="Your reliance on Fuliza has grown over the statement period — "
                    "a trend lenders find alarming.",
        action="Review what changed in your spending pattern over the past 3 months. "
               "Identify the new or growing expense and address it specifically.",
        priority=1,
    ),

    # ----------------------------------------------------------------
    # Savings
    # ----------------------------------------------------------------
    "mmf_net_saver": SignalAdvice(
        pillar="SAVINGS",
        sentiment="positive",
        label="Net Saver (MMF)",
        explanation="You deposit more into your Money Market Fund than you withdraw — "
                    "a clear sign of healthy savings discipline.",
    ),
    "mmf_activity": SignalAdvice(
        pillar="SAVINGS",
        sentiment="neutral",
        label="Some MMF Activity",
        explanation="You have used an MMF (e.g. M-Shwari, Ziidi) but withdrawn all deposits.",
        action="Keep at least some funds in your MMF permanently. "
               "Even 500 KES left untouched each month builds a positive savings track record.",
        priority=3,
    ),

    # ----------------------------------------------------------------
    # Statement quality
    # ----------------------------------------------------------------
    "long_statement": SignalAdvice(
        pillar="DATA_QUALITY",
        sentiment="positive",
        label="6+ Months of History",
        explanation="Your statement covers at least 6 months — "
                    "enough data for lenders to trust the patterns they see.",
    ),
    "medium_statement": SignalAdvice(
        pillar="DATA_QUALITY",
        sentiment="neutral",
        label="3–6 Months of History",
        explanation="Your statement covers 3–6 months. More history increases lender confidence.",
        action="Request a longer M-Pesa statement (up to 24 months from Safaricom). "
               "The more history you provide, the more accurate your score.",
        priority=3,
    ),
    "statement_gap": SignalAdvice(
        pillar="DATA_QUALITY",
        sentiment="negative",
        label="Statement Has Missing Pages",
        explanation="There are gaps in your statement — some transactions may be missing. "
                    "This reduces the reliability of your score.",
        action="Download a fresh M-Pesa statement directly from the Safaricom app or *234#. "
               "Ensure you download the complete file without skipping pages.",
        priority=2,
    ),
    "high_unclassified": SignalAdvice(
        pillar="DATA_QUALITY",
        sentiment="negative",
        label="Many Transactions Unclassified",
        explanation="More than 10% of your transactions could not be categorised. "
                    "This may mean your statement format is unusual.",
        action="Contact support and share your statement — our team can improve "
               "classification for your specific transaction patterns.",
        priority=3,
    ),
    "has_bank_statement": SignalAdvice(
        pillar="DATA_QUALITY",
        sentiment="positive",
        label="Bank Statement Provided",
        explanation="You provided a bank statement in addition to M-Pesa, "
                    "giving lenders a more complete financial picture.",
    ),
    "has_sacco_statement": SignalAdvice(
        pillar="DATA_QUALITY",
        sentiment="positive",
        label="SACCO Statement Provided",
        explanation="Your SACCO membership shows long-term savings commitment — "
                    "highly regarded by lenders.",
    ),
}


# ---------------------------------------------------------------------------
# Pillar max points — used to normalise sub-scores to 0–100
# ---------------------------------------------------------------------------
# These are the THEORETICAL maximums if every positive signal in the pillar fired.
# Adjust these whenever you add new rules to maintain calibrated sub-scores.

PILLAR_MAX_POINTS: dict[Pillar, int] = {
    "INCOME":       320,  # income(150) + income_regular(40) + salary(30) + employment(60) + ivr_ok(~40)
    "SPENDING":     150,  # solvency_strong(60) + utility_ratio_ok(30) + no_fuliza(0=best) + tight budget avoided
    "REPAYMENT":    80,   # utility_consistent(50) + utility_ratio_ok(30)
    "SAVINGS":      50,   # mmf_net_saver(50)
    "DATA_QUALITY": 150,  # verified(60) + long_statement(40) + bank(30) + sacco(20)
}


# ---------------------------------------------------------------------------
# Main function — call this after scoring
# ---------------------------------------------------------------------------

def build_improvement_report(
    breakdown: dict[str, int],
    features: dict,
) -> dict:
    """
    Takes the raw scoring breakdown and the feature dict, and returns a
    structured improvement report for the API response and frontend.

    Returns:
    {
        "pillars": {
            "INCOME": { "score": 72, "label": "Income", "strengths": [...], "improvements": [...] },
            ...
        },
        "top_actions": [...],   # The 3 most impactful things to do RIGHT NOW
        "strengths_summary": [...],   # 3 things the user is doing well
        "score_potential": int,   # How many points they could gain by fixing all negatives
    }
    """
    # Accumulate points per pillar and collect advice items
    pillar_earned: dict[Pillar, int] = {p: 0 for p in PILLAR_MAX_POINTS}
    pillar_strengths: dict[Pillar, list[dict]] = {p: [] for p in PILLAR_MAX_POINTS}
    pillar_improvements: dict[Pillar, list[dict]] = {p: [] for p in PILLAR_MAX_POINTS}

    score_potential = 0

    for key, points in breakdown.items():
        advice = SIGNAL_CATALOGUE.get(key)
        if advice is None:
            # Unmapped signal — skip gracefully (log in production)
            continue

        pillar = advice.pillar

        if advice.sentiment == "positive":
            pillar_earned[pillar] += points
            pillar_strengths[pillar].append({
                "label": advice.label,
                "explanation": advice.explanation,
                "points": points,
            })
        elif advice.sentiment == "negative":
            # Points are negative here — track the opportunity cost
            opportunity = abs(points)
            score_potential += opportunity
            pillar_improvements[pillar].append({
                "label": advice.label,
                "explanation": advice.explanation,
                "action": advice.action,
                "priority": advice.priority,
                "points_at_stake": opportunity,
            })
        # neutral signals: log the label but don't add to improvements

    # Build pillar sub-scores (0–100)
    pillar_labels = {
        "INCOME": "Income Strength",
        "SPENDING": "Spending Discipline",
        "REPAYMENT": "Repayment Behaviour",
        "SAVINGS": "Savings Habit",
        "DATA_QUALITY": "Data & Verification",
    }

    pillars_output = {}
    for pillar, max_pts in PILLAR_MAX_POINTS.items():
        earned = max(0, pillar_earned[pillar])
        sub_score = round(min(100, (earned / max_pts) * 100))
        pillars_output[pillar] = {
            "label": pillar_labels[pillar],
            "score": sub_score,
            "strengths": sorted(
                pillar_strengths[pillar], key=lambda x: x["points"], reverse=True
            ),
            "improvements": sorted(
                pillar_improvements[pillar],
                key=lambda x: (x["priority"], -x["points_at_stake"]),
            ),
        }

    # Top 3 actions — highest priority, then highest points at stake
    all_improvements = []
    for pillar_data in pillars_output.values():
        for item in pillar_data["improvements"]:
            all_improvements.append({**item, "pillar": pillar_data["label"]})

    top_actions = sorted(
        all_improvements,
        key=lambda x: (x["priority"], -x["points_at_stake"]),
    )[:3]

    # Top 3 strengths across all pillars
    all_strengths = []
    for pillar_data in pillars_output.values():
        all_strengths.extend(pillar_data["strengths"])

    top_strengths = sorted(all_strengths, key=lambda x: x["points"], reverse=True)[:3]

    return {
        "pillars": pillars_output,
        "top_actions": top_actions,
        "strengths_summary": top_strengths,
        "score_potential": min(score_potential, 700),  # cap at max possible gain
    }