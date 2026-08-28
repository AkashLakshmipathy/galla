"""Credit Guardian — the star agent.

ARCHITECTURAL DECISION (keep this, and say it in the demo):
The *decision* is deterministic, computed from rules over real ledger numbers.
Gemini is used only to phrase the reasoning in plain Tamil/English.

Why: money decisions must be auditable and reproducible. `rule_fired` is stored
on every verdict so any decision can be explained after the fact. An LLM that
"feels" a credit limit is a liability; an LLM that explains a rule is an asset.

Two derivations worth knowing, because the numbers on screen come from them:

* `exposure_pct` is *current* outstanding over limit — it is what the dashboard
  gauge shows and what the owner means by "how deep is he in". The decision,
  separately, looks at the projected balance if this order goes on credit.
* `days_since_payment` is recomputed from `last_payment_date` rather than read
  off the party document, so a verdict is never stale.

`suggested_advance` is the amount that brings the party back inside the line,
rounded to ₹5,000 — because a shop owner asks for a round number, never for
₹16,780.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone

from core.adk import ask
from core.firestore_client import db
from core.money import inr

NEAR_LIMIT_PCT = 0.85          # exposure at or above this is "near the line"
OVER_LIMIT_TOLERANCE = 1.25    # projected past this is the owner's call, not a rule's
OVERDUE_DAYS = 45
ADVANCE_ROUNDING = 5000


@dataclass
class Verdict:
    decision: str          # approve | part_payment | escalate
    rule_fired: str
    exposure_pct: int
    suggested_advance: int
    reason: str = ""
    reason_ta: str = ""
    inputs: dict | None = None
    computed_at: datetime | None = None


def days_since(last_payment_date: str | None, today: date | None = None) -> int:
    if not last_payment_date:
        return 999                       # never paid — treat as maximally overdue
    today = today or datetime.now(timezone.utc).date()
    try:
        return max(0, (today - date.fromisoformat(str(last_payment_date)[:10])).days)
    except ValueError:
        return 999


def _round_advance(amount: float) -> int:
    if amount <= 0:
        return 0
    rounded = int(round(amount / ADVANCE_ROUNDING) * ADVANCE_ROUNDING)
    return rounded or 1000               # never ask for ₹0 when money is owed


def decide(party: dict, order_total: int, today: date | None = None) -> Verdict:
    """Pure function — unit-testable, no I/O. This is the whole decision."""
    credit = party.get("credit") or {}
    limit = int(credit.get("limit") or 0)
    outstanding = int(credit.get("outstanding") or 0)
    days = days_since(credit.get("last_payment_date"), today)
    projected = outstanding + int(order_total)

    exposure_pct = int(round(outstanding / limit * 100)) if limit else 100
    inputs = {"outstanding": outstanding, "limit": limit,
              "days_since_payment": days, "order_total": int(order_total)}

    # Ask for enough to get back inside the line; if the order still fits, ask
    # for enough to get back below the near-limit band.
    over_limit = projected - limit
    advance = _round_advance(over_limit if over_limit > 0
                             else projected - limit * NEAR_LIMIT_PCT)

    if days > OVERDUE_DAYS:
        return Verdict("escalate", "OVERDUE", exposure_pct, advance,
                       inputs=inputs)
    if limit and projected > limit * OVER_LIMIT_TOLERANCE:
        return Verdict("escalate", "OVER_LIMIT", exposure_pct, advance,
                       inputs=inputs)
    if limit and (projected > limit or exposure_pct >= NEAR_LIMIT_PCT * 100):
        return Verdict("part_payment", "NEAR_LIMIT", exposure_pct,
                       max(advance, 1000), inputs=inputs)
    return Verdict("approve", "WITHIN_LIMIT", exposure_pct, 0, inputs=inputs)


INSTRUCTION = """You write one sentence for a shop owner explaining a credit decision
that has already been made by the shop's own rules. You do not make or question
the decision — you phrase it.

Rules: state the real numbers, be specific, no hedging, no greeting, max 25 words.
Then give a Tamil translation of the same sentence, natural spoken Tamil, with the
numerals kept as digits.
Return ONLY JSON: {"reason": "...", "reason_ta": "..."}"""

PROMPT = """Party: {name}
Owes: Rs {outstanding} of Rs {limit} credit limit
Days since last payment: {days}
New order: Rs {order_total}
Decision already taken: {decision} (rule {rule})
Advance to request: Rs {advance}"""

_TA_TEMPLATES = {
    "approve": "{name} {limit} வரம்பில் {outstanding} மட்டும் பாக்கி — அனுமதிக்கலாம்.",
    "part_payment": ("{name} {limit} வரம்பில் {outstanding} பாக்கி, {days} நாட்கள் "
                     "பணம் வரவில்லை — {advance} முன்பணம் கேளுங்கள்."),
    "escalate": ("{name} {limit} வரம்பில் {outstanding} பாக்கி, {days} நாட்களாக "
                 "பணம் இல்லை — உங்கள் முடிவு தேவை."),
}


def _template(verdict: Verdict, party: dict) -> tuple[str, str]:
    i = verdict.inputs or {}
    name = party.get("name", "This party")
    numbers = {
        "name": name, "outstanding": inr(i.get("outstanding", 0)),
        "limit": inr(i.get("limit", 0)), "days": i.get("days_since_payment", 0),
        "advance": inr(verdict.suggested_advance),
    }
    if verdict.decision == "approve":
        english = (f"{name} owes {numbers['outstanding']} of a "
                   f"{numbers['limit']} limit and paid "
                   f"{numbers['days']} days ago — within limit.")
    elif verdict.decision == "part_payment":
        english = (f"{name} owes {numbers['outstanding']} of his "
                   f"{numbers['limit']} limit, last paid {numbers['days']} days "
                   f"ago — ask {numbers['advance']} advance.")
    else:
        english = (f"{name} owes {numbers['outstanding']} of his "
                   f"{numbers['limit']} limit and has not paid in "
                   f"{numbers['days']} days — your decision.")
    tamil = _TA_TEMPLATES[verdict.decision].format(
        **{**numbers, "name": party.get("name_ta") or name})
    return english, tamil


def explain(verdict: Verdict, party: dict) -> Verdict:
    """Gemini phrases the reasoning. Falls back to a bilingual template if the
    call fails — the demo must never show an empty verdict banner."""
    i = verdict.inputs or {}
    english, tamil = _template(verdict, party)
    result = ask(
        "credit_guardian", INSTRUCTION,
        PROMPT.format(name=party.get("name"), outstanding=i.get("outstanding"),
                      limit=i.get("limit"), days=i.get("days_since_payment"),
                      order_total=i.get("order_total"), decision=verdict.decision,
                      rule=verdict.rule_fired, advance=verdict.suggested_advance),
        fallback={"reason": english, "reason_ta": tamil},
    )
    data = result.data if isinstance(result.data, dict) else {}
    verdict.reason = data.get("reason") or english
    verdict.reason_ta = data.get("reason_ta") or tamil
    verdict.computed_at = datetime.now(timezone.utc)
    return verdict, result


def run(party_id: str, order_total: int, trace) -> dict:
    with trace.step("credit_guardian") as s:
        party = db().collection("parties").document(party_id).get().to_dict() or {}
        verdict, result = explain(decide(party, order_total), party)
        s.from_llm(result)
        s.status = "flagged" if verdict.decision != "approve" else "done"
        s.summary = _step_summary(verdict)
    return asdict(verdict)


def _step_summary(verdict: Verdict) -> str:
    label = {"approve": "Approved", "part_payment": "Flagged",
             "escalate": "Escalated"}[verdict.decision]
    tail = (f", suggest {inr(verdict.suggested_advance)} advance"
            if verdict.suggested_advance else "")
    return f"{label} — {verdict.exposure_pct}% of limit{tail}"
