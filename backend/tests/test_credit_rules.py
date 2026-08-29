"""The Credit Guardian's rules decide money, so they are the thing to test.

`decide` is pure: no Firestore, no model, no clock beyond the date passed in.
That is the whole reason the architecture puts the decision in Python and gives
Gemini only the sentence.
"""
from datetime import date

import pytest

from agents.credit_guardian_agent import days_since, decide

TODAY = date(2026, 8, 28)


def party(limit, outstanding, last_paid, name="Test"):
    return {"name": name,
            "credit": {"limit": limit, "outstanding": outstanding,
                       "last_payment_date": last_paid}}


def test_within_limit_approves():
    verdict = decide(party(150000, 32000, "2026-08-20"), 24380, TODAY)
    assert verdict.decision == "approve"
    assert verdict.rule_fired == "WITHIN_LIMIT"
    assert verdict.suggested_advance == 0


def test_near_limit_asks_for_a_round_advance():
    """The demo's money shot: 92% of limit, ₹15,000 advance, phrased in Tamil."""
    verdict = decide(party(95000, 87400, "2026-07-25"), 24380, TODAY)
    assert verdict.decision == "part_payment"
    assert verdict.rule_fired == "NEAR_LIMIT"
    assert verdict.exposure_pct == 92
    assert verdict.suggested_advance == 15000


def test_overdue_escalates_even_when_inside_the_limit():
    """Time matters as much as size: a party who has not paid in two months is
    the owner's call regardless of headroom."""
    verdict = decide(party(120000, 20000, "2026-06-30"), 5000, TODAY)
    assert verdict.decision == "escalate"
    assert verdict.rule_fired == "OVERDUE"


def test_far_over_limit_escalates_rather_than_bargaining():
    verdict = decide(party(50000, 40000, "2026-08-20"), 40000, TODAY)
    assert verdict.decision == "escalate"
    assert verdict.rule_fired == "OVER_LIMIT"


def test_exposure_is_current_not_projected():
    """The gauge shows what the party owes now; the decision looks ahead. Mixing
    the two was the bug that made the demo's amber case read as red."""
    verdict = decide(party(100000, 50000, "2026-08-20"), 90000, TODAY)
    assert verdict.exposure_pct == 50
    assert verdict.decision in {"part_payment", "escalate"}


def test_never_asks_for_zero_when_money_is_owed():
    verdict = decide(party(100000, 86000, "2026-08-27"), 100, TODAY)
    assert verdict.decision == "part_payment"
    assert verdict.suggested_advance >= 1000


def test_no_limit_set_is_treated_as_no_headroom():
    verdict = decide({"credit": {"limit": 0, "outstanding": 0}}, 5000, TODAY)
    assert verdict.exposure_pct == 100


@pytest.mark.parametrize("last_paid,expected", [
    ("2026-07-25", 34), ("2026-08-28", 0), (None, 999), ("garbage", 999),
])
def test_days_since_payment(last_paid, expected):
    assert days_since(last_paid, TODAY) == expected


def test_verdict_is_serialisable_for_firestore():
    from dataclasses import asdict
    verdict = decide(party(95000, 87400, "2026-07-25"), 24380, TODAY)
    data = asdict(verdict)
    # `rule_fired` is what makes a verdict auditable after the fact.
    assert data["rule_fired"] == "NEAR_LIMIT"
    assert set(data["inputs"]) == {
        "outstanding", "limit", "days_since_payment", "order_total"}
