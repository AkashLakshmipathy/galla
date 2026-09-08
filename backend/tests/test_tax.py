"""The tax engine against docs/TAX-ENGINE-SPEC.md §6, vector for vector.

These are the spec's own numbers, not numbers read back off the implementation.
If one of them ever has to change, the spec changes first.
"""
from datetime import date
from decimal import Decimal

import pytest

from core.tax import (compute_invoice, compute_line, counter_key,
                      financial_year, invoice_number, is_intra_state,
                      round_half_up, split_tax)


def D(value) -> Decimal:
    return Decimal(str(value))


# --------------------------------------------------- §6 single line, intra-state
@pytest.mark.parametrize("price,inclusive,rate,taxable,half,total", [
    (445.00, True,  28, "347.66", "48.67",  "445.00"),
    (415.00, False, 28, "415.00", "58.10",  "531.20"),
    (265.00, True,  18, "224.58", "20.21",  "265.00"),
    (245.00, False, 18, "245.00", "22.05",  "289.10"),
])
def test_single_line_intra_state(price, inclusive, rate, taxable, half, total):
    line = compute_line("Ramco 53", 1, price, rate,
                        price_includes_tax=inclusive, intra_state=True)
    assert line.taxable == D(taxable)
    assert line.cgst == D(half)
    assert line.sgst == D(half)
    assert line.igst == D("0.00")
    assert line.total == D(total)


def test_inter_state_charges_igst_at_the_full_rate():
    line = compute_line("Ramco 53", 1, 415.00, 28,
                        price_includes_tax=False, intra_state=False)
    assert line.taxable == D("415.00")
    assert line.igst == D("116.20")
    assert line.cgst == line.sgst == D("0.00")
    assert line.total == D("531.20")


# ------------------------------------------------- §6 multi-line with round-off
def test_multi_line_invoice_rounds_to_a_whole_rupee():
    invoice = compute_invoice([
        {"description": "Ramco 53", "qty": 3, "unit_price": 415.00,
         "gst_rate": 28, "price_includes_tax": False},
        {"description": "CPVC 3/4", "qty": 7, "unit_price": 245.00,
         "gst_rate": 18, "price_includes_tax": False},
    ], intra_state=True)

    cement, pipe = invoice.lines
    assert (cement.taxable, cement.cgst, cement.sgst, cement.total) == \
        (D("1245.00"), D("174.30"), D("174.30"), D("1593.60"))
    assert (pipe.taxable, pipe.cgst, pipe.sgst, pipe.total) == \
        (D("1715.00"), D("154.35"), D("154.35"), D("2023.70"))

    assert invoice.subtotal_taxable == D("2960.00")
    assert invoice.total_tax == D("657.30")
    assert invoice.gross == D("3617.30")
    assert invoice.round_off == D("-0.30")
    assert invoice.payable == 3617
    assert isinstance(invoice.payable, int)


# ------------------------------------------------- §6 discount, inclusive entry
def test_percentage_discount_on_an_inclusive_price():
    """The vector that proves the Decimal choice: 1849.53 / 2 is 924.765, which
    binary float rounds *down* to 924.76. The spec says 924.77."""
    line = compute_line("Ramco 53", 20, 445.00, 28,
                        price_includes_tax=True, discount_pct=5,
                        intra_state=True)
    assert line.gross_entered == D("8900.00")
    assert line.discount == D("445.00")
    assert line.net_entered == D("8455.00")
    assert line.taxable == D("6605.47")
    assert line.tax == D("1849.53")
    assert line.cgst == D("924.77")
    assert line.sgst == D("924.76")
    assert line.cgst + line.sgst == line.tax
    assert line.total == D("8455.00")


# ------------------------------------------------------------- §6 edge cases
def test_zero_rated_sku_has_no_tax_and_no_split():
    line = compute_line("Exempt item", 2, 100.00, 0, price_includes_tax=True)
    assert line.taxable == D("200.00")
    assert (line.tax, line.cgst, line.sgst, line.igst) == \
        (D("0.00"), D("0.00"), D("0.00"), D("0.00"))
    assert line.total == D("200.00")


def test_arbitrary_price_override_is_recomputed_never_rejected():
    line = compute_line("Ramco 53", 1, 437.37, 28, price_includes_tax=True)
    assert line.total == D("437.37")
    assert line.taxable + line.tax == line.total


@pytest.mark.parametrize("tax", ["0.01", "0.03", "1849.53", "97.35", "0.05"])
def test_split_always_balances_even_on_a_half_paisa(tax):
    """`sgst = tax - cgst` must hold exactly, including when tax/2 lands on .005."""
    cgst, sgst, igst = split_tax(D(tax), intra_state=True)
    assert cgst + sgst == D(tax)
    assert igst == D("0.00")


def test_decimal_quantity():
    line = compute_line("Binding wire", 2.5, 82.00, 18,
                        price_includes_tax=False, intra_state=True)
    assert line.gross_entered == D("205.00")
    assert line.taxable == D("205.00")
    assert line.tax == D("36.90")
    assert line.cgst == line.sgst == D("18.45")


def test_flat_rupee_discount_is_taken_before_tax_is_backed_out():
    line = compute_line("Ramco 53", 1, 445.00, 28,
                        price_includes_tax=True, discount=45.00)
    assert line.net_entered == D("400.00")
    assert line.taxable == D("312.50")
    assert line.tax == D("87.50")
    assert line.total == D("400.00")


def test_discount_larger_than_the_line_is_clamped_not_negative():
    line = compute_line("Ramco 53", 1, 445.00, 28,
                        price_includes_tax=True, discount=900.00)
    assert line.discount == D("445.00")
    assert line.net_entered == D("0.00")
    assert line.taxable == D("0.00")
    assert line.total == D("0.00")


def test_round_off_can_be_positive():
    """A gross of .40 rounds down; .60 rounds up. Both must land on a rupee."""
    down = compute_invoice([{"qty": 1, "unit_price": 100.40, "gst_rate": 0,
                             "price_includes_tax": True}])
    up = compute_invoice([{"qty": 1, "unit_price": 100.60, "gst_rate": 0,
                           "price_includes_tax": True}])
    assert (down.payable, down.round_off) == (100, D("-0.40"))
    assert (up.payable, up.round_off) == (101, D("0.40"))


def test_exact_half_rupee_rounds_up():
    invoice = compute_invoice([{"qty": 1, "unit_price": 100.50, "gst_rate": 0,
                                "price_includes_tax": True}])
    assert invoice.payable == 101


def test_empty_invoice_is_zero_not_an_error():
    invoice = compute_invoice([])
    assert invoice.payable == 0 and invoice.gross == D("0.00")


def test_round_half_up_is_not_bankers_rounding():
    assert round_half_up("0.125") == D("0.13")      # banker's would give 0.12
    assert round_half_up("924.765") == D("924.77")


# ----------------------------------------------------------- §3 place of supply
def test_place_of_supply():
    assert is_intra_state("33") is True              # Tamil Nadu to Tamil Nadu
    assert is_intra_state("29") is False             # Karnataka
    assert is_intra_state(None) is True              # unregistered walk-in
    assert is_intra_state("") is True


# ------------------------------------------------------- §7 invoice numbering
def test_financial_year_starts_in_april():
    assert financial_year(date(2026, 4, 1)) == "26-27"
    assert financial_year(date(2027, 3, 31)) == "26-27"
    assert financial_year(date(2026, 3, 31)) == "25-26"
    assert financial_year(date(2026, 12, 25)) == "26-27"


def test_invoice_number_format_and_length():
    assert invoice_number(42, on=date(2026, 9, 7)) == "SBH/26-27/0042"
    assert len(invoice_number(9999, on=date(2026, 9, 7))) <= 16


def test_invoice_number_refuses_to_exceed_sixteen_characters():
    with pytest.raises(ValueError):
        invoice_number(42, prefix="TOOLONGPREFIX", on=date(2026, 9, 7))


def test_counter_keys_are_separate_per_document_kind():
    assert counter_key("invoice", on=date(2026, 9, 7)) == "invoice#26-27"
    assert counter_key("quote", on=date(2026, 9, 7)) == "quote#26-27"
