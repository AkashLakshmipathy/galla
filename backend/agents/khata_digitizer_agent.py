"""Khata Digitizer — twenty-five years of paper ledger, one page at a time.

The owner trusts his khata because he can *see* every entry, so this agent's
output is built to be inspected: every row carries a normalised `bbox` locating
it on the source photograph, which is what lets the review screen highlight the
exact handwriting a number came from when the owner taps the row.

Nothing posts to the ledger here. Rows land in `khata_imports` as
`auto_accepted` or `needs_confirm`; only a committed import moves balances, in
one transaction. A bad OCR read must never silently change what a contractor
owes.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from core import confirm_queue, ids, parties, provisioning, storage
from core.catalog import normalise as catalog_normalise
from core.config import CONFIDENCE_THRESHOLD, DEMO_MODE, FIXTURES_DIR
from core.firestore_client import db
from core.llm import Media, ask
from core.money import inr

INSTRUCTION = """You read one page from an Indian hardware shop's handwritten
credit book (khata). Read it exactly as the shopkeeper wrote it.

HOW THESE PAGES ARE LAID OUT

One page is ONE customer's running account, not a list of different people. The
customer's name is written at the top, usually with a date beside it, and often
underlined. Read it carefully and letter by letter — it is a South Indian name
and it will be written the same way on the customer's other pages, so a careless
reading splits one man's account in two. Report it exactly as written; do not
tidy it, translate it, or guess at a more familiar-looking name.

Under the name comes "B/F" or "B.F" — the balance brought forward from the
previous page. It is the starting figure, NOT something bought that day.

Then the goods, one per line: a description with the quantity written into it
("SIF 8233 4Lt", "1 1/4 MS Nails 1/4kg", "4\" wood cutter 7 Nos"), and the
amount for that line in the right-hand column.

Under a group of lines the shopkeeper writes a running total — sometimes labelled
"total", often just underlined. It equals the balance so far plus the lines above
it. Payments received are written the same way and SUBTRACT from the running
total. A page may carry several dates; entries continue under the last date
written until a new one appears.

WHAT TO RETURN

{
  "party_name_raw": "<the name at the top, exactly as written>",
  "page_date": "<YYYY-MM-DD of the first date on the page, or null>",
  "opening_balance": <the B/F figure, or null if there is none>,
  "closing_balance": <the final figure at the bottom, or null>,
  "rows": [
    {"description_raw": "<the line exactly as written, quantity included>",
     "date": "<YYYY-MM-DD — carry the last date on the page forward>",
     "amount": <the amount for this line>,
     "entry_type": "sale_credit" | "payment_received",
     "confidence": <0-1 for how legible this line was>,
     "bbox": {"x": <0-1>, "y": <0-1>, "w": <0-1>, "h": <0-1>},
     "alternatives": [<your reading, then the next most likely>]}
  ]
}

THE RULE THAT MATTERS MOST

`rows` contains ONLY things bought and payments made. It must NOT contain the
B/F figure, any running total, any subtotal, or the closing balance. Those are
arithmetic *about* the entries, and reporting one as a transaction charges a man
money he never spent. If a figure roughly equals the sum of what is above it, it
is a total — put it in `opening_balance` or `closing_balance`, or leave it out.

Anything written on the page that is a payment coming in — "Recd", "paid",
"cash", a figure that makes the running total go *down* — is
"payment_received". Everything else is "sale_credit".

`bbox` is the line's rectangle on the photo, normalised 0-1 from the top left;
the owner taps a row to see the handwriting it came from. Where a digit is
genuinely ambiguous lower the confidence and list the alternative readings. The
page may be photographed at an angle or upside down — read it anyway."""


def _fixture() -> dict:
    """The canned reading, for the demo only.

    A fixture standing in for a failed model call is fine on stage and
    catastrophic in a shop: it would write invented names and invented debts
    into a real ledger, indistinguishable from a genuine read. Outside DEMO_MODE
    there is no stand-in — an unread page says so and waits for a better photo.
    """
    if not DEMO_MODE:
        return {}
    path = FIXTURES_DIR / "khata_page.json"
    return json.loads(path.read_text("utf-8")) if path.exists() else {}


RECHECK_PROMPT = """Your reading does not agree with the page's own arithmetic.

You read the balance brought forward as {opening} and the closing figure as
{closing}. The entries you listed come to {bought} bought and {paid} paid, which
would close at {expected} — off by {difference}.

The shopkeeper's own totals are right; the misreading is yours. A difference like
this is almost always one of:
  - a dropped leading digit (575 read where the page says 1575)
  - a line you skipped altogether
  - a running total mistaken for an entry, or an entry mistaken for a total
  - a payment read as a purchase, or the reverse

Look again at the amounts column and return the SAME JSON structure, corrected so
that opening + bought - paid equals the closing figure. Do not invent a line to
make it balance; if you genuinely cannot make it agree, return your best reading
and lower the confidence on the lines you are least sure of."""


def _extract(payload: dict) -> tuple[dict, object]:
    image_uri = payload.get("media_path") or payload.get("page_image_url")
    media: list[Media] = []
    if image_uri:
        blob = storage.get_bytes(image_uri)
        if blob:
            # Shrunk for the model only; the full photograph stays in storage.
            payload, kind = storage.for_model(
                blob, storage.content_type_of(image_uri))
            media.append(Media(kind, payload))
    result = ask("khata_digitizer", INSTRUCTION,
                 "Read this khata page and return the JSON.",
                 media=media, fallback=_fixture(),
                 fast=True)
    data = result.data if isinstance(result.data, dict) and result.data.get("rows") \
        else _fixture()

    # The page checks the machine. If our reading does not reproduce the
    # shopkeeper's own closing figure, something was misread — so say exactly by
    # how much and let the model look again. One retry: a second failure means
    # the page genuinely needs a human, and asking a third time only spends money.
    check = arithmetic_check(data, _amounts_only(data.get("rows") or []))
    if media and check.get("checked") and not check["balances"]:
        retry = ask("khata_digitizer", INSTRUCTION,
                    RECHECK_PROMPT.format(
                        opening=check["opening"], closing=check["closing"],
                        bought=check["bought"], paid=check["paid"],
                        expected=check["expected_closing"],
                        difference=abs(check["difference"])),
                    media=media, fallback=None, fast=True)
        if isinstance(retry.data, dict) and retry.data.get("rows"):
            second = arithmetic_check(retry.data,
                                      _amounts_only(retry.data.get("rows") or []))
            # Keep the second reading only if it is actually better.
            if second.get("balances") or (
                    second.get("checked")
                    and abs(second["difference"]) < abs(check["difference"])):
                return retry.data, retry
    return data, result


def _amounts_only(rows: list[dict]) -> list[dict]:
    """The shape `arithmetic_check` needs, before parties have been resolved."""
    return [{"amount": int(float(r.get("amount") or 0)),
             "entry_type": r.get("entry_type") or "sale_credit"} for r in rows]


def arithmetic_check(extraction: dict, rows: list[dict]) -> dict:
    """Does the page's own arithmetic agree with what we read off it?

    A khata writes its running totals down the right-hand side, and those totals
    are a gift: opening balance, plus everything bought, minus everything paid,
    must equal the closing figure the shopkeeper wrote himself. When it does, the
    read is almost certainly right — a missed line or a misread digit would break
    it. When it does not, something is wrong and the page should be checked
    before a rupee of it reaches anyone's ledger.

    This is the strongest signal available here, and it costs nothing: the paper
    is checking the machine.
    """
    opening = extraction.get("opening_balance")
    closing = extraction.get("closing_balance")
    bought = sum(int(r["amount"]) for r in rows if r["entry_type"] != "payment_received")
    paid = sum(int(r["amount"]) for r in rows if r["entry_type"] == "payment_received")
    if opening is None or closing is None:
        return {"checked": False, "bought": bought, "paid": paid}

    expected = int(opening) + bought - paid
    difference = int(closing) - expected
    return {"checked": True, "opening": int(opening), "closing": int(closing),
            "bought": bought, "paid": paid, "expected_closing": expected,
            "difference": difference, "balances": difference == 0}


def _resolve_rows(raw_rows: list[dict], page_party: str | None = None,
                  opening_balance: float | None = None) -> list[dict]:
    """Attach the page's party to every row — or propose opening an account.

    An old khata is full of names the system has never seen, and each one is a
    person or a firm the shop already trades with. Rather than stalling on them,
    the agent proposes a profile. The proposal is applied only when the import is
    committed, in the same transaction that posts the ledger entries.

    A name that is *close* to an existing party is never auto-created: two
    profiles for one contractor means his real exposure is double what either
    shows, which is exactly what the Credit Guardian exists to catch.
    """
    index = parties.index()
    # A khata page names the same person on several lines. Proposing a fresh
    # account per row would open one debtor twice and split their balance across
    # both, which is the very thing the merge feature exists to undo.
    proposed_here: dict[str, dict] = {}
    rows: list[dict] = []
    for position, raw in enumerate(raw_rows, start=1):
        read = float(raw.get("confidence") or 0.9)
        # One page is one customer: the name at the top governs every line.
        name_raw = raw.get("party_name_raw") or page_party or ""
        entry_type = raw.get("entry_type") or "sale_credit"
        resolution = provisioning.resolve_party(name_raw, entry_type, index,
                                                opening_balance=opening_balance)

        row = {
            "row_id": f"r{position}",
            "party_name_raw": name_raw,
            "description_raw": raw.get("description_raw"),
            "party_id": resolution.existing_id,
            "date": raw.get("date"),
            "amount": float(raw.get("amount") or 0),
            "entry_type": entry_type,
            "bbox": raw.get("bbox") or {"x": 0, "y": 0, "w": 1, "h": 0},
            "alternatives": raw.get("alternatives") or [],
        }
        if resolution.action == provisioning.USE:
            row["confidence"] = round(read * resolution.score, 2)
        elif resolution.creates:
            # Nobody by this name is on file. Opening an account is the right
            # answer, so the row is only as uncertain as the handwriting was.
            row["confidence"] = round(read, 2)
            key = catalog_normalise(name_raw)
            row["new_party"] = proposed_here.setdefault(key, resolution.proposed)
        else:
            # Close to someone we know — the owner must say which.
            row["confidence"] = round(read * resolution.score, 2)
            row["new_party"] = resolution.proposed
            row["near_miss"] = resolution.near_miss

        row["status"] = ("auto_accepted" if row["confidence"] >= CONFIDENCE_THRESHOLD
                         else "needs_confirm")
        rows.append(row)
    return rows


def _queue_uncertain(import_id: str, rows: list[dict], image_uri: str | None,
                     check: dict | None = None) -> int:
    """Ask about as little as possible.

    A page whose own totals reconcile has already checked itself: opening plus
    what was bought minus what was paid reaches the closing figure the
    shopkeeper wrote. A misread amount would have broken that. So when the
    arithmetic agrees, an individually shaky-looking row is not worth a
    question — the page as a whole is evidence the row is right, and asking
    anyway trains the owner to tap through without looking, which is worse than
    not asking at all.

    When the arithmetic does not agree, something genuinely is wrong. Even then
    only the least legible rows are raised, because the gap lives in one or two
    of them and a queue of eleven cards buries which.
    """
    if check and check.get("balances"):
        return 0

    doubtful = sorted((r for r in rows if r["status"] == "needs_confirm"),
                      key=lambda r: r["confidence"])[:3]
    queued = 0
    for row in doubtful:
        queued += 1
        known_party = bool(row.get("party_id"))
        confirm_queue.enqueue(
            source_type="khata", source_id=import_id, row_id=row["row_id"],
            field="amount" if known_party else "party_id",
            extracted_value=(inr(row["amount"]) if known_party
                             else row.get("party_name_raw")),
            confidence=row["confidence"],
            alternatives=([inr(a) for a in row.get("alternatives") or []]
                          if known_party else []),
            source_image_url=image_uri, crop_bbox=row["bbox"])
    return queued


def run(payload: dict, trace) -> dict:
    with trace.step("khata_digitizer") as s:
        extraction, result = _extract(payload)
        s.from_llm(result)
        rows = _resolve_rows(extraction.get("rows") or [],
                             extraction.get("party_name_raw"),
                             extraction.get("opening_balance"))
        unread = not rows
        image_uri = payload.get("media_path") or payload.get("page_image_url")
        import_id = payload.get("import_id") or ids.import_id()
        accepted = sum(1 for row in rows if row["status"] == "auto_accepted")
        pending = len(rows) - accepted
        new_parties = len({r["new_party"]["party_id"] for r in rows
                           if r.get("new_party") and not r.get("near_miss")})

        check = arithmetic_check(extraction, rows)
        if check.get("balances"):
            # The page proved itself, so nothing on it needs a human — including
            # rows for a customer with no account yet. Requiring an existing
            # party_id here left a fully reconciled page stuck behind seven
            # questions it had already answered.
            for row in rows:
                if row["status"] == "needs_confirm" and (
                        row.get("party_id") or row.get("new_party")):
                    row["status"] = "auto_accepted"
        # One resolved name, used by the record, the trace step and the
        # notifier alike — they were disagreeing, with the strip saying "Page"
        # while the message said the customer's name, off the same import.
        page_name = (extraction.get("party_name_raw")
                     or next((r.get("party_name_raw")
                              for r in (extraction.get("rows") or [])
                              if r.get("party_name_raw")), None)
                     or "Page")
        record = {
            "import_id": import_id,
            # The page-level name is what the review screen puts at the top,
            # so fall back to the rows when the extraction did not give one.
            # A page is one customer's account, so any row answers it — and the
            # demo fixture predates the page-level field entirely, which would
            # otherwise put "Not read" on screen the moment a model call fails.
            "party_name_raw": None if page_name == "Page" else page_name,
            "opening_balance": extraction.get("opening_balance"),
            "closing_balance": extraction.get("closing_balance"),
            "arithmetic": check,
            "page_no": extraction.get("page_no") or payload.get("page_no"),
            "page_image_url": image_uri,
            "rows": rows,
            "auto_accepted_count": accepted,
            "needs_confirm_count": pending,
            "status": "reviewing",
            "trace_id": trace.trace_id,
            "created_at": datetime.now(timezone.utc),
        }
        db().collection("khata_imports").document(import_id).set(record)
        trace.set_ref("khata_import", import_id)
        _queue_uncertain(import_id, rows, image_uri, check)

        if unread:
            # Nothing was read. Saying so is the only honest answer; inventing
            # rows here would put debts on real people that nobody owes.
            s.status = "error"
            s.summary = ("Could not read this page — take the photo again in "
                         "better light, with the page flat")
        elif check.get("checked") and not check["balances"]:
            # The page's own totals disagree with what we read. Something is
            # missing or misread; none of it should be trusted on sight.
            s.status = "flagged"
            s.summary = (f"{page_name} — the "
                         f"figures do not add up: the page closes at "
                         f"{inr(check['closing'])} but these entries make "
                         f"{inr(check['expected_closing'])}. Check it before posting.")
        else:
            s.status = "flagged" if pending else "done"
            tail = " · totals agree ✓" if check.get("balances") else ""
            s.summary = (f"{page_name} — "
                         f"{len(rows)} entries, {accepted} clear, "
                         f"{pending} to confirm"
                         + (f", {new_parties} new account(s)" if new_parties else "")
                         + tail)
    return record
