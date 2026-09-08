"""Billing & tax arithmetic. Pure functions — no model, no I/O, no Firestore.

Nothing in this module may reach for the network or the clock. That is what
makes the whole of it testable against the spec's vectors, and it is why the
tax rules live here instead of inside the agent that happens to bill.

THE DESIGN PRINCIPLE (docs/TAX-ENGINE-SPEC.md §1)

A shopkeeper says "bag 445, with tax". Almost every billing package makes him
type 415 and watch the machine add tax on top — teaching him its arithmetic
instead of speaking his. Galla accepts the number the way he says it and works
backwards. `price_includes_tax` is that switch, and it defaults per party:
walk-in counter sales are quoted inclusive, contractor B2B exclusive.

WHY Decimal AND NOT float

`round(1849.53 / 2, 2)` is 924.76 in binary floating point, because 924.765 is
really 924.76499999999998749. The spec's own discount vector wants 924.77. Money
that is out by a paisa is money a CA has to reconcile by hand, so every figure
here is a Decimal quantized half-up. Python's built-in `round()` is also
banker's rounding, which is the wrong rule for Indian tax invoices.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

TWO_PLACES = Decimal("0.01")
SHOP_STATE_CODE = "33"          # Tamil Nadu


def to_decimal(value) -> Decimal:
    """Accept whatever the UI, the catalogue or a model hands us.

    Floats are routed through `str()` on purpose: Decimal(0.1) is
    0.1000000000000000055511151231257827, while Decimal("0.1") is exactly 0.1.
    """
    if isinstance(value, Decimal):
        return value
    if value is None or value == "":
        return Decimal("0")
    return Decimal(str(value))


def round_half_up(value, places: int = 2) -> Decimal:
    """Half-up, the rule Indian invoices use — never banker's rounding."""
    exponent = Decimal(1).scaleb(-places)
    return to_decimal(value).quantize(exponent, rounding=ROUND_HALF_UP)


def split_tax(tax: Decimal, intra_state: bool) -> tuple[Decimal, Decimal, Decimal]:
    """(cgst, sgst, igst).

    The halving rule that guarantees no drift: only CGST is rounded, and SGST is
    whatever is left. Rounding both independently is how a 0.01 appears out of
    nowhere on a bill and a CA spends an afternoon looking for it.
    """
    if not intra_state:
        return Decimal("0.00"), Decimal("0.00"), round_half_up(tax)
    cgst = round_half_up(tax / 2)
    return cgst, round_half_up(tax - cgst), Decimal("0.00")


def is_intra_state(party_state_code: str | None,
                   shop_state_code: str = SHOP_STATE_CODE) -> bool:
    """An unregistered walk-in has no state code and is served at the counter,
    so the place of supply is the shop's own state."""
    if not party_state_code:
        return True
    return str(party_state_code).strip() == str(shop_state_code).strip()


@dataclass(frozen=True)
class TaxLine:
    description: str
    qty: Decimal
    unit_price: Decimal
    rate: Decimal                       # GST %, e.g. 28
    price_includes_tax: bool
    discount: Decimal                   # absolute rupees taken off this line
    gross_entered: Decimal              # qty x unit_price, before discount
    net_entered: Decimal                # after discount
    taxable: Decimal
    tax: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    total: Decimal
    hsn_code: str = ""
    unit: str = ""
    sku_id: str | None = None

    def as_dict(self) -> dict:
        """Floats for JSON, because a Decimal will not serialise. Every value
        is already quantized, so this cannot reintroduce a rounding error."""
        return {
            "sku_id": self.sku_id, "description": self.description,
            "hsn_code": self.hsn_code, "unit": self.unit,
            "qty": float(self.qty), "unit_price": float(self.unit_price),
            "rate": float(self.rate),
            "price_includes_tax": self.price_includes_tax,
            "discount": float(self.discount),
            "gross_entered": float(self.gross_entered),
            "net_entered": float(self.net_entered),
            "taxable": float(self.taxable), "tax": float(self.tax),
            "cgst": float(self.cgst), "sgst": float(self.sgst),
            "igst": float(self.igst), "total": float(self.total),
        }


@dataclass(frozen=True)
class TaxInvoice:
    lines: list[TaxLine] = field(default_factory=list)
    intra_state: bool = True
    subtotal_taxable: Decimal = Decimal("0.00")
    total_cgst: Decimal = Decimal("0.00")
    total_sgst: Decimal = Decimal("0.00")
    total_igst: Decimal = Decimal("0.00")
    total_tax: Decimal = Decimal("0.00")
    total_discount: Decimal = Decimal("0.00")
    gross: Decimal = Decimal("0.00")
    round_off: Decimal = Decimal("0.00")
    payable: int = 0

    def as_dict(self) -> dict:
        return {
            "lines": [line.as_dict() for line in self.lines],
            "intra_state": self.intra_state,
            "subtotal_taxable": float(self.subtotal_taxable),
            "cgst": float(self.total_cgst), "sgst": float(self.total_sgst),
            "igst": float(self.total_igst), "total_tax": float(self.total_tax),
            "total_discount": float(self.total_discount),
            "gross": float(self.gross), "round_off": float(self.round_off),
            "payable": self.payable,
        }


def _discount_amount(gross: Decimal, discount, discount_pct) -> Decimal:
    """Flat rupees or a percentage — never both, percentage wins if given.

    Clamped to the line: a 120% discount is a typo, and a negative taxable value
    would propagate into the register as a credit that never happened.
    """
    if discount_pct:
        amount = gross * to_decimal(discount_pct) / Decimal("100")
    else:
        amount = to_decimal(discount)
    amount = round_half_up(amount)
    if amount < 0:
        return Decimal("0.00")
    return min(amount, round_half_up(gross))


def compute_line(description: str, qty, unit_price, rate, *,
                 price_includes_tax: bool = True,
                 discount=0, discount_pct=0,
                 intra_state: bool = True,
                 hsn_code: str = "", unit: str = "",
                 sku_id: str | None = None) -> TaxLine:
    """One invoice line, fully split and rounded to paise (spec §2-§5).

    Note the ordering, which the spec is specific about: the discount comes off
    the *entered* amount, and only then is tax backed out of what remains. Doing
    it the other way rounds twice and lands a paisa away.
    """
    qty_d = to_decimal(qty)
    price_d = to_decimal(unit_price)
    rate_d = to_decimal(rate)

    gross_entered = round_half_up(qty_d * price_d)
    discount_amount = _discount_amount(gross_entered, discount, discount_pct)
    net_entered = round_half_up(gross_entered - discount_amount)

    if rate_d == 0:
        # Exempt or zero-rated: no tax, and no split to argue about.
        taxable, tax = net_entered, Decimal("0.00")
    elif price_includes_tax:
        taxable = round_half_up(net_entered / (Decimal("1") + rate_d / Decimal("100")))
        tax = round_half_up(net_entered - taxable)
    else:
        taxable = net_entered
        tax = round_half_up(taxable * rate_d / Decimal("100"))

    cgst, sgst, igst = split_tax(tax, intra_state) if tax else (
        Decimal("0.00"), Decimal("0.00"), Decimal("0.00"))

    return TaxLine(
        description=description, qty=qty_d, unit_price=price_d, rate=rate_d,
        price_includes_tax=price_includes_tax, discount=discount_amount,
        gross_entered=gross_entered, net_entered=net_entered,
        taxable=taxable, tax=tax, cgst=cgst, sgst=sgst, igst=igst,
        total=round_half_up(taxable + tax),
        hsn_code=hsn_code, unit=unit, sku_id=sku_id,
    )


def compute_invoice(lines: list[dict], *, intra_state: bool = True,
                    default_includes_tax: bool = True) -> TaxInvoice:
    """Price a whole bill: per-line arithmetic, then one round-off at the foot.

    Lines are dicts as they arrive from the counter screen or an order document.
    `price_includes_tax` is per line — the counter defaults it inclusive, a
    contractor's order exclusive — falling back to `default_includes_tax`.
    """
    computed: list[TaxLine] = []
    for line in lines:
        computed.append(compute_line(
            description=line.get("description") or line.get("name") or "",
            qty=line.get("qty", 1),
            unit_price=line.get("unit_price", line.get("rate", 0)),
            rate=line.get("gst_rate", line.get("tax_rate", 0)),
            price_includes_tax=bool(line.get("price_includes_tax",
                                             default_includes_tax)),
            discount=line.get("discount", 0),
            discount_pct=line.get("discount_pct", 0),
            intra_state=intra_state,
            hsn_code=line.get("hsn_code", ""),
            unit=line.get("unit", ""),
            sku_id=line.get("sku_id"),
        ))

    def total_of(attribute: str) -> Decimal:
        return round_half_up(sum((getattr(l, attribute) for l in computed),
                                 Decimal("0")))

    gross = total_of("total")
    # Nearest whole rupee, .50 up — `payable` is always an integer, and
    # `round_off` is the (usually negative) difference printed on the bill.
    payable = int(round_half_up(gross, 0))
    return TaxInvoice(
        lines=computed, intra_state=intra_state,
        subtotal_taxable=total_of("taxable"),
        total_cgst=total_of("cgst"), total_sgst=total_of("sgst"),
        total_igst=total_of("igst"), total_tax=total_of("tax"),
        total_discount=total_of("discount"),
        gross=gross,
        round_off=round_half_up(Decimal(payable) - gross),
        payable=payable,
    )


# ------------------------------------------------------- invoice numbering §7
def financial_year(on: date | None = None) -> str:
    """'26-27' for any date in the Indian FY starting 1 April 2026.

    Kept here, pure, so the counter key and the printed number can never
    disagree about which year a bill belongs to.
    """
    on = on or date.today()
    start = on.year if on.month >= 4 else on.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


def invoice_number(sequence: int, prefix: str = "SBH",
                   on: date | None = None, fy: str | None = None) -> str:
    """SBH/26-27/0042 — consecutive, unique per financial year, max 16 chars."""
    number = f"{prefix}/{fy or financial_year(on)}/{sequence:04d}"
    if len(number) > 16:
        raise ValueError(f"invoice number exceeds 16 characters: {number}")
    return number


def counter_key(kind: str = "invoice", on: date | None = None,
                fy: str | None = None) -> str:
    """`invoice#26-27` / `quote#26-27` — the counters row this FY increments."""
    return f"{kind}#{fy or financial_year(on)}"
