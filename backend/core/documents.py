"""Shared PDF rendering — shop letterhead, tables, and the house style.

Both the quotation and the monthly GST summary are documents the shop hands to
someone who will judge it: a contractor, or a CA. They should look like they
came from the same business, so the styles live here rather than twice.

Also here because it is not agent logic: an agent decides *what* the document
says, this decides what it looks like.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from io import BytesIO, StringIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from core.money import ddmmyyyy, inr, pdf_text

INK = colors.HexColor("#111113")
TEXT2 = colors.HexColor("#77777C")
RULE = colors.HexColor("#E9E9EB")

TITLE = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=13, textColor=INK,
                       leading=16)
META = ParagraphStyle("m", fontName="Helvetica", fontSize=8, textColor=TEXT2,
                      leading=11)
BODY = ParagraphStyle("b", fontName="Helvetica", fontSize=9.5, textColor=INK,
                      leading=13)
SMALL = ParagraphStyle("s", fontName="Helvetica", fontSize=7.5, textColor=TEXT2,
                       leading=10)


def rupees(amount) -> str:
    """Reportlab's core fonts have no rupee glyph, so documents say Rs."""
    return pdf_text(inr(amount))


def letterhead(shop: dict, subtitle: str = "") -> list:
    """Shop name, then address · GSTIN · phone — skipping whatever is unset."""
    line = " &nbsp;·&nbsp; ".join(part for part in (
        shop.get("address"),
        f"GSTIN {shop['gstin']}" if shop.get("gstin") else None,
        shop.get("phone"),
        subtitle or None,
    ) if part)
    return [Paragraph(shop.get("name", "Shop"), TITLE), Paragraph(line, META)]


def line_table(rows: list[list], col_widths: list[float]) -> Table:
    """Header row, hairline separators, everything but the first column right-aligned."""
    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 8.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), TEXT2),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, RULE),
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, RULE),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def totals_table(rows: list[list], label_width: float = 130 * mm,
                 value_width: float = 40 * mm) -> Table:
    """Right-aligned summary block; the last row is the bold grand total."""
    return Table(rows, colWidths=[label_width, value_width], hAlign="RIGHT",
                 style=TableStyle([
                     ("FONT", (0, 0), (-1, -2), "Helvetica", 9),
                     ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 10),
                     ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                     ("LINEABOVE", (0, -1), (-1, -1), 0.6, RULE),
                     ("TOPPADDING", (0, 0), (-1, -1), 4),
                 ]))


def render(flow: list, title: str, author: str = "Galla") -> bytes:
    buffer = BytesIO()
    SimpleDocTemplate(buffer, pagesize=A4, title=title, author=author,
                      leftMargin=16 * mm, rightMargin=16 * mm,
                      topMargin=14 * mm, bottomMargin=14 * mm).build(flow)
    return buffer.getvalue()


def gap(mm_height: float) -> Spacer:
    return Spacer(1, mm_height * mm)


# ------------------------------------------------------- the monthly GST pack
def gst_registers_csv(outward: dict, inward: dict) -> bytes:
    """The CSV a CA opens in Tally or Excel — one row per register section."""
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Register", "Section", "Taxable", "CGST", "SGST", "Invoices"])
    for section in ("b2b", "b2c"):
        row = outward[section]
        writer.writerow(["Outward", section.upper(), row["taxable"], row["cgst"],
                         row["sgst"], row["invoice_count"]])
    writer.writerow(["Inward", "ALL", inward["taxable"], inward["cgst"],
                     inward["sgst"], inward["invoice_count"]])
    return buffer.getvalue().encode("utf-8")


def gst_summary_pdf(period: str, shop: dict, outward: dict, inward: dict,
                    net: int, note: str) -> bytes:
    """The one page the CA reads first. It says CA-ready, never "filed"."""
    rows = [
        ["", "Taxable", "CGST", "SGST", "Invoices"],
        ["Outward — B2B", rupees(outward["b2b"]["taxable"]),
         rupees(outward["b2b"]["cgst"]), rupees(outward["b2b"]["sgst"]),
         str(outward["b2b"]["invoice_count"])],
        ["Outward — B2C", rupees(outward["b2c"]["taxable"]),
         rupees(outward["b2c"]["cgst"]), rupees(outward["b2c"]["sgst"]),
         str(outward["b2c"]["invoice_count"])],
        ["Inward (ITC)", rupees(inward["taxable"]), rupees(inward["cgst"]),
         rupees(inward["sgst"]), str(inward["invoice_count"])],
        ["Net tax payable (est.)", "", "", rupees(net), ""],
    ]
    table = line_table(rows, [52 * mm, 32 * mm, 28 * mm, 28 * mm, 22 * mm])
    table.setStyle([("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 10),
                    ("LINEABOVE", (0, -1), (-1, -1), 0.6, RULE)])

    flow = letterhead(shop, f"GST summary for {period}") + [
        gap(7), Paragraph(pdf_text(note), BODY), gap(6), table, gap(7),
        Paragraph("CA-ready summary · Galla does not file your GST. Figures are "
                  "compiled from the shop's own records for your accountant to "
                  "review and file.", META),
        Paragraph(f"Compiled {ddmmyyyy(datetime.now(timezone.utc))}.", META),
    ]
    return render(flow, f"GST summary {period}", shop.get("name", "Galla"))
