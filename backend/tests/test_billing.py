"""Billing: the invoice number, the document, and the one number that matters.

The property these protect: the figure in the ledger and the figure on the tax
invoice are the same figure. They are computed at different moments by different
code paths, so nothing but a test keeps them honest.
"""
import base64
import re
import zlib

from agents import billing_agent, stock_pricing_agent
from core.firestore_client import db
from core.money import order_totals


def pdf_text(pdf: bytes) -> str:
    """The visible text of a reportlab PDF, without pulling in a parser.

    Page content is ASCII85-encoded around a Flate-compressed stream, so the
    words on the page are not in the raw bytes — which is exactly how an
    assertion like `b"GSTIN..." in pdf` passes for the wrong reason. Both
    codecs are in the standard library. Text then sits inside `(literal) Tj`
    operators, with parentheses backslash-escaped.
    """
    chunks = []
    for block in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.DOTALL):
        raw = block.strip(b"\r\n")
        for decode in (
            lambda b: zlib.decompress(base64.a85decode(b, adobe=True)),
            lambda b: zlib.decompress(b),
            lambda b: base64.a85decode(b, adobe=True),
            lambda b: b,
        ):
            try:
                chunks.append(decode(raw))
                break
            except Exception:                             # noqa: BLE001
                continue
    body = b"".join(chunks)
    words = re.findall(rb"\((?:\\.|[^\\()])*\)", body)
    return " ".join(w[1:-1].replace(b"\\(", b"(").replace(b"\\)", b")")
                    .decode("latin-1") for w in words)


SPEC_LINES = [
    {"sku_id": "cem-ramco-53", "qty": 3, "rate": 415, "gst_rate": 28},
    {"sku_id": "plm-cpvc-075", "qty": 7, "rate": 245, "gst_rate": 18},
]


def test_the_pipeline_total_matches_the_spec_vector(seeded):
    """docs/TAX-ENGINE-SPEC.md §6: gross 3617.30, round off -0.30, payable 3617.

    The superseded `money.order_totals` rounds each line's GST to a whole rupee
    before summing and answers 3618. A rupee between the ledger and the tax
    invoice is a rupee the shop cannot explain, which is why this is pinned.
    """
    order = {"party_id": "selvam", "price_includes_tax": False}
    subtotal, gst, total = stock_pricing_agent.totals_for(order, SPEC_LINES)

    assert subtotal == 2960
    assert total == 3617
    assert order_totals(
        [{"amount": 1245, "gst_rate": 28}, {"amount": 1715, "gst_rate": 18}]
    )[2] == 3618, "the old whole-rupee path really did disagree"


def test_the_ledger_amount_equals_the_invoice_payable(seeded):
    """Approve a multi-line order and the two numbers must be one number."""
    from core.transactions import approve_order

    order_id = "ord_test_billing"
    order = {"order_id": order_id, "party_id": "selvam",
             "price_includes_tax": False, "status": "awaiting_approval",
             "lines": SPEC_LINES}
    subtotal, gst, total = stock_pricing_agent.totals_for(order, SPEC_LINES)
    order.update({"subtotal": subtotal, "gst": gst, "total": total})
    db().collection("orders").document(order_id).set(order)

    result = approve_order(order_id)
    stored = db().collection("orders").document(order_id).get().to_dict()

    shop = db().collection("shop").document("main").get().to_dict()
    party = db().collection("parties").document("selvam").get().to_dict()
    invoice = billing_agent.price(stored, party, shop)

    assert result["amount"] == invoice.payable == stored["total"] == 3617


def test_an_out_of_state_party_is_billed_igst(seeded):
    shop = db().collection("shop").document("main").get().to_dict()
    kerala = {"name": "Kerala Builders", "gstin": "32AABCK1234M1Z9",
              "state_code": "32", "price_tier": "retail"}
    invoice = billing_agent.price(
        {"lines": SPEC_LINES, "price_includes_tax": False}, kerala, shop)

    assert invoice.intra_state is False
    assert invoice.total_igst == invoice.total_tax
    assert invoice.total_cgst == invoice.total_sgst == 0
    assert invoice.payable == 3617       # the split changes, the payable does not


def test_the_invoice_pdf_renders_for_both_splits(seeded):
    """A document that raises on render is a demo with a blank screen."""
    from core import documents

    shop = db().collection("shop").document("main").get().to_dict()
    party = db().collection("parties").document("selvam").get().to_dict()
    order = {"lines": SPEC_LINES, "price_includes_tax": False}

    for state_code in ("33", "32"):
        pdf = documents.tax_invoice_pdf(
            billing_agent.price(order, {**party, "state_code": state_code}, shop),
            shop, party, "SBH/26-27/0042")
        assert pdf.startswith(b"%PDF") and len(pdf) > 1500


def test_the_gst_register_reconciles_against_the_issued_invoice(seeded):
    """A CA checks the summary against the invoices. Recomputing the tax here
    from line amounts rounds each line to a whole rupee and lands two rupees
    away from the document the customer is holding."""
    import json
    from datetime import datetime, timezone

    from agents import router
    from core.transactions import approve_order

    fixture = json.loads(open("seed/fixtures/voice_selvam.json").read())
    order = router.handle("sale_order", fixture)
    approve_order(order["order_id"])
    order = router.resume_after_decision(
        db().collection("orders").document(order["order_id"]).get().to_dict(),
        "approve")

    invoice = order["invoice"]
    register = router.handle(
        "gst_compile", {"period": datetime.now(timezone.utc).strftime("%Y-%m")})
    b2b = register["outward"]["b2b"]

    assert b2b["invoice_count"] == 1, "a registered contractor's sale is B2B"
    assert b2b["taxable"] == round(invoice["subtotal_taxable"])
    assert b2b["cgst"] == round(invoice["cgst"])
    assert b2b["sgst"] == round(invoice["sgst"])


def test_the_invoice_carries_everything_the_spec_requires(seeded):
    """docs/TAX-ENGINE-SPEC.md §8, read off the rendered page.

    Every one of these is a field a GST invoice is required to show, and a
    missing one is not visible from the fact that the PDF rendered.
    """
    from core import documents

    party = db().collection("parties").document("selvam").get().to_dict()
    shop = db().collection("shop").document("main").get().to_dict()
    assert party.get("gstin"), "the contractor is registered"

    invoice = billing_agent.price(
        {"lines": SPEC_LINES, "price_includes_tax": False}, party, shop)
    text = pdf_text(documents.tax_invoice_pdf(
        invoice, shop, party, "SBH/26-27/0042"))

    assert "TAX INVOICE SBH/26-27/0042" in text
    assert shop["name"] in text and shop["gstin"] in text
    assert party["gstin"] in text, "party GSTIN is required when B2B"
    assert "Place of supply 33" in text and "Tamil Nadu" in text
    assert "2523" in text, "HSN code per line"
    assert "Rs 3,617" in text, "the payable"
    assert "Rupees Three Thousand Six Hundred And Seventeen Only" in text
    assert "CGST" in text and "SGST" in text and "IGST" not in text


def test_an_unregistered_walk_in_invoice_says_so(seeded):
    from core import documents

    shop = db().collection("shop").document("main").get().to_dict()
    walk_in = db().collection("parties").document("walk_in").get().to_dict()
    invoice = billing_agent.price(
        {"lines": SPEC_LINES, "price_includes_tax": True}, walk_in, shop)
    text = pdf_text(documents.tax_invoice_pdf(
        invoice, shop, walk_in, "SBH/26-27/0043"))

    assert "Unregistered" in text
    assert "GSTIN 33A" not in text.replace(f"GSTIN {shop['gstin']}", "")


def test_an_inter_state_invoice_shows_igst_and_not_the_state_pair(seeded):
    from core import documents

    shop = db().collection("shop").document("main").get().to_dict()
    kerala = {"name": "Kerala Builders", "gstin": "32AABCK1234M1Z9",
              "state_code": "32", "price_tier": "retail"}
    text = pdf_text(documents.tax_invoice_pdf(
        billing_agent.price({"lines": SPEC_LINES, "price_includes_tax": False},
                            kerala, shop),
        shop, kerala, "SBH/26-27/0044"))

    assert "Place of supply 32" in text and "Kerala" in text
    assert "IGST" in text
    assert "CGST" not in text and "SGST" not in text
