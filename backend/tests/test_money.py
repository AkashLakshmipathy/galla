from core.money import (gst_split, inr, order_totals, parse_amount, pdf_text,
                        rupees_in_words)


def test_indian_grouping_not_thousands():
    assert inr(112500) == "₹1,12,500"
    assert inr(1184300) == "₹11,84,300"
    assert inr(87400) == "₹87,400"
    assert inr(445) == "₹445"
    assert inr(0) == "₹0"
    assert inr(-2500) == "-₹2,500"


def test_gst_splits_evenly_and_loses_nothing_to_rounding():
    split = gst_split(8300, 28)
    assert split["cgst"] + split["sgst"] == split["total"] == 2324


def test_odd_gst_still_sums_to_the_total():
    split = gst_split(3185, 18)
    assert split["cgst"] + split["sgst"] == split["total"]


def test_inter_state_uses_igst_only():
    split = gst_split(1000, 18, intra_state=False)
    assert split["igst"] == 180 and split["cgst"] == 0 and split["sgst"] == 0


def test_order_totals_match_the_demo_script():
    """The seeded voice note must come to ₹24,380 — the figure in the video."""
    lines = [
        {"amount": 20 * 415, "gst_rate": 28},
        {"amount": 13 * 245, "gst_rate": 18},
        {"amount": 11 * 715, "gst_rate": 18},
        {"amount": 8 * 76, "gst_rate": 18},
    ]
    subtotal, gst, total = order_totals(lines)
    assert (subtotal, total) == (19958, 24380)
    assert gst["cgst"] + gst["sgst"] == gst["total"]


def test_amount_in_words():
    assert rupees_in_words(24380).startswith("Rupees Twenty Four Thousand")
    assert rupees_in_words(0) == "Rupees Zero Only"
    assert "Lakh" in rupees_in_words(1184300)


def test_parse_amount_round_trips_display_text():
    assert parse_amount("₹4,250") == 4250
    assert parse_amount("Rs 1,12,500") == 112500
    assert parse_amount(None) == 0


def test_pdf_text_drops_the_glyph_reportlab_cannot_draw():
    assert "₹" not in pdf_text("Net ₹4,250 payable")
