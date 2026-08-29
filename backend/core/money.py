"""Indian money and GST arithmetic. Integers of rupees everywhere — no floats
in the books; GST components are rounded once, at the line, and then summed.
"""
from __future__ import annotations

import re
from datetime import date, datetime

_UNITS = ["", "one", "two", "three", "four", "five", "six", "seven", "eight",
          "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
          "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
         "eighty", "ninety"]


def parse_amount(value) -> float:
    """'₹4,250' / 'Rs 4,250' / 4250 -> 4250.0.

    The confirm queue shows the owner a formatted amount and hands back whatever
    he tapped, so the value coming in may be display text.
    """
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[^\d.-]", "", str(value or ""))
    try:
        return float(cleaned) if cleaned not in {"", "-", "."} else 0.0
    except ValueError:
        return 0.0


def pdf_text(text: str) -> str:
    """ReportLab's built-in fonts have no rupee glyph, and an embedded font is a
    lot of bytes for one character. Documents say "Rs" instead — which is what a
    printed Indian invoice usually says anyway."""
    return (text or "").replace("\u20b9", "Rs ").replace("Rs  ", "Rs ")


def inr(amount) -> str:
    """₹1,12,500 — lakh/crore grouping, never thousands grouping.

    Coerces rather than raising: this formats model output as often as it does
    our own arithmetic, and a model that answers "1,575" where a number was asked
    for should not crash a scan half way through a shop's stack of paper.
    """
    if isinstance(amount, str):
        amount = parse_amount(amount)
    n = int(round(amount or 0))
    sign = "-" if n < 0 else ""
    s = str(abs(n))
    if len(s) <= 3:
        return f"{sign}₹{s}"
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return f"{sign}₹{','.join(groups)},{tail}"


def ddmmyyyy(value: str | date | datetime | None) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    return value.strftime("%d-%m-%Y")


def gst_split(taxable: float, rate: float, intra_state: bool = True) -> dict:
    """CGST/SGST for a same-state sale, IGST across states.

    `state_code` on the shop vs the party decides which; Tamil Nadu selling to
    Tamil Nadu is the demo case, so intra_state defaults True.
    """
    total = round(taxable * rate / 100)
    if intra_state:
        half = round(total / 2)
        return {"cgst": half, "sgst": total - half, "igst": 0, "total": total}
    return {"cgst": 0, "sgst": 0, "igst": total, "total": total}


def line_amount(qty: float, rate: float) -> int:
    return int(round((qty or 0) * (rate or 0)))


def order_totals(lines: list[dict], intra_state: bool = True) -> tuple[int, dict, int]:
    """(subtotal, gst dict, grand total). Lines carry `amount` and `gst_rate`."""
    subtotal = 0
    cgst = sgst = igst = 0
    for line in lines:
        amount = int(line.get("amount") or 0)
        subtotal += amount
        split = gst_split(amount, float(line.get("gst_rate") or 0), intra_state)
        cgst += split["cgst"]
        sgst += split["sgst"]
        igst += split["igst"]
    gst = {"cgst": cgst, "sgst": sgst, "igst": igst, "total": cgst + sgst + igst}
    return subtotal, gst, subtotal + gst["total"]


def _under_thousand(n: int) -> str:
    if n < 20:
        return _UNITS[n]
    if n < 100:
        return (_TENS[n // 10] + (f" {_UNITS[n % 10]}" if n % 10 else "")).strip()
    return (f"{_UNITS[n // 100]} hundred"
            + (f" and {_under_thousand(n % 100)}" if n % 100 else ""))


def rupees_in_words(amount: float | int) -> str:
    """'Rupees Twenty Four Thousand Three Hundred Eighty Only' — required on a
    GST invoice, and the sort of detail a CA notices immediately."""
    n = int(round(amount or 0))
    if n == 0:
        return "Rupees Zero Only"
    parts: list[str] = []
    for divisor, label in ((10_000_000, "crore"), (100_000, "lakh"), (1_000, "thousand")):
        if n >= divisor:
            parts.append(f"{_under_thousand(n // divisor)} {label}")
            n %= divisor
    if n:
        parts.append(_under_thousand(n))
    words = " ".join(parts).replace("  ", " ").strip()
    return "Rupees " + words.title() + " Only"
