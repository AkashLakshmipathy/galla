# Galla — Firestore Schema

Database: Firestore **Native mode**, single region `asia-south1` (Mumbai — lowest latency for Coimbatore, and the right story for an India-first product).

Design rules for this build:
1. **Denormalise for read speed on the demo path.** `parties.credit.outstanding` is a maintained running total, not a sum-on-read, so the Credit Guardian answers in one document read instead of scanning the ledger.
2. **Every write that moves money runs in a Firestore transaction.** Ledger entry + party balance update happen atomically or not at all.
3. **Every agent run writes a trace.** `agent_traces` powers both the UI trace strip and the audit log — one collection serving product and production-readiness at once.
4. **Confidence is a first-class field.** Anything the model extracted carries a `confidence`; anything below threshold routes to `confirm_queue` rather than silently entering the books.

---

## Collection: `shop` (singleton, doc id `main`)

```
{
  shop_id: "main",
  name: "Sri Balaji Hardware",
  name_ta: "ஸ்ரீ பாலாஜி ஹார்டுவேர்",
  gstin: "33AAMPM8712K1ZQ",
  state_code: "33",                  // Tamil Nadu — drives CGST/SGST vs IGST
  address: "Thudiyalur, Coimbatore",
  phone: "+91XXXXXXXXXX",
  ca_contact: { name: "...", phone: "+91XXXXXXXXXX", email: "..." },
  defaults: { credit_limit: 50000, credit_days: 30 },
  confidence_threshold: 0.85          // below this → confirm_queue
}
```

## Collection: `parties` (customers **and** suppliers)

```
{
  party_id: "selvam",
  name: "Selvam",
  name_ta: "செல்வம்",
  type: "customer" | "supplier" | "both",
  phone: "+91XXXXXXXXXX",
  gstin: "33XXXXXXXXXXXZX" | null,
  price_tier: "retail" | "contractor" | "bulk",
  credit: {
    limit: 95000,
    outstanding: 87400,              // maintained; never summed on read
    last_payment_date: "2026-07-25",
    last_payment_amount: 20000,
    days_since_payment: 34,          // recomputed on read or by scheduler
    avg_days_to_pay: 41,
    total_business_value: 1240000,
    dispute_count: 0
  },
  created_at, updated_at
}
```
Index: `type ASC, name ASC`.

## Collection: `catalog` (SKUs)

The `aliases` array is what makes voice/handwriting intake work — it holds the trade slang the model must resolve.

```
{
  sku_id: "cem-ramco-53-50kg",
  name: "Ramco Supergrade OPC 53 Grade 50kg",
  name_ta: "ராம்கோ 53 சிமெண்ட்",
  aliases: ["ramco 53", "ramco bag", "ராம்கோ", "supergrade", "53 grade ramco"],
  brand: "Ramco", category: "cement",
  unit: "bag", hsn_code: "2523", gst_rate: 28,
  purchase_rate: 385,
  price_tiers: { retail: 445, contractor: 415, bulk: 405 },
  substitutes: ["cem-dalmia-53-50kg"],   // powers the out-of-stock flow
  active: true
}
```
Index: `category ASC, name ASC`. Alias matching is done in-agent (fuzzy match over a cached catalog), **not** by Firestore query.

## Collection: `inventory` (doc id = `sku_id`)

Separate from `catalog` because it is write-hot while catalog is read-mostly.

```
{ sku_id, qty_on_hand: 40, reorder_level: 15, last_updated, last_purchase_id }
```

## Collection: `orders`

```
{
  order_id: "ord_1043",
  party_id: "selvam",
  source: "voice" | "photo" | "text",
  source_media_url: "gs://galla-media/voice/...",
  transcript: "20 bags Ramco 53, ten ¾ pipe...",
  transcript_ta: "...",
  lines: [{
    sku_id, name_raw: "20 bag ramco 53", qty: 20, unit: "bag",
    rate: 415, amount: 8300, gst_rate: 28,
    confidence: 0.97,
    substitute_of: null,             // set when agent swapped an out-of-stock SKU
    in_stock: true
  }],
  subtotal, gst: { cgst, sgst, total }, total: 24380,
  credit_verdict: {
    decision: "approve" | "part_payment" | "escalate",
    reason: "Selvam owes ₹87,400 of his ₹95,000 limit, last paid 34 days ago — ask ₹15,000 advance.",
    reason_ta: "...",
    suggested_advance: 15000,
    exposure_pct: 92,
    inputs: { outstanding: 87400, limit: 95000, days_since_payment: 34, order_total: 24380 },
    rule_fired: "NEAR_LIMIT",        // auditable: which rule produced the decision
    computed_at
  },
  status: "draft" | "awaiting_approval" | "approved" | "rejected" | "fulfilled",
  owner_action: { action, at, note },
  quotation_url, trace_id, created_at
}
```
Indexes: `status ASC, created_at DESC` · `party_id ASC, created_at DESC`.

## Collection: `purchases`

```
{
  purchase_id, supplier_id, supplier_name_raw: "Sri Balaji Hardware Agencies",
  invoice_no, invoice_date, supplier_gstin,
  source_image_url,
  lines: [{ sku_id, description_raw, qty, rate, amount, gst_rate, confidence: 0.72, matched: true }],
  totals: { subtotal, cgst, sgst, total },
  status: "extracted" | "needs_confirm" | "confirmed",
  stock_applied: false,              // guard against double-increment
  stock_delta: [{ sku_id, before: 40, after: 65 }],
  payable_ledger_id, trace_id, created_at
}
```
Index: `supplier_id ASC, invoice_date DESC`.

## Collection: `ledger` (append-only money log)

```
{
  entry_id, party_id, date,
  type: "sale_credit" | "payment_received" | "purchase_credit" | "payment_made" | "opening_balance",
  amount, direction: "debit" | "credit",
  balance_after: 111780,
  ref: { type: "order" | "purchase" | "khata_import" | "manual", id },
  source: "agent" | "owner" | "khata_import",
  note, created_at
}
```
Index: `party_id ASC, date DESC`. **Never update or delete** — corrections are new reversing entries.

## Collection: `khata_imports`

```
{
  import_id, page_no: 12, page_image_url,
  rows: [{
    row_id, party_name_raw: "பழனி", party_id: "palani" | null,
    date: "2026-06-14", amount: 4250, entry_type: "sale_credit",
    confidence: 0.68,
    bbox: { x: 0.12, y: 0.44, w: 0.61, h: 0.06 },   // normalised 0-1, drives tap-to-trace
    status: "auto_accepted" | "needs_confirm" | "confirmed",
    alternatives: [4250, 4230, 1250]
  }],
  auto_accepted_count: 9, needs_confirm_count: 3,
  status: "reviewing" | "committed", trace_id, created_at
}
```
Rows only post to `ledger` when the import is committed — so a bad OCR read never silently changes a balance.

## Provisional records (created from scanned paper)

A shop installing Galla has an empty `catalog` and no `parties`, so the scanning
agents can *create* both. Two fields are added to those collections:

```
provisional: true              // built from a scan; the owner has not reviewed it
created_from: { type: "purchase" | "khata_import", id }
```

and `catalog` additionally carries:

```
needs_pricing: true            // price_tiers are all 0 — receivable, not sellable
```

Rules, in order of how much they matter:

1. **Three bands, not two.** Score ≥ 0.85 uses the existing record; below 0.55
   creates a new one; *in between, the owner is asked and nothing is created*.
   Auto-creating in the middle band is how one contractor becomes two ledgers —
   and two ledgers for one debtor means real exposure is double what either
   profile shows, the exact failure the Credit Guardian exists to catch.
2. **Creation happens inside the money transaction**, never at scan time, so a
   scan the owner discards leaves no phantom products or empty accounts.
3. **A new SKU is received but not sellable.** Quantity, purchase rate, HSN and
   GST come off the bill; the selling price is left at 0 because guessing a
   margin is deciding money. `approve_order` refuses any line with rate 0.
4. **A new party gets the shop's default credit limit**, never one inferred from
   the page.

## Merging duplicate profiles

Handwriting varies and a name gets spelled two ways over twenty years, so
duplicates arrive despite the ambiguous-band rule above. Two profiles for one
contractor is the worst state this system can be in: his real exposure is the
sum of both while the Credit Guardian only ever sees one, so the shop can extend
nearly double the credit it believes it has.

`parties` gains:

```
merged_into: "selvam" | null     // this profile was folded into that one
merged_at, merged_by
aliases_merged: ["Selvan"]       // names this profile has absorbed
active: false                    // set on the profile that was merged away
```

**The ledger is never rewritten by a merge.** Repointing `party_id` on historical
entries would make an old khata page silently vanish from the profile it was
filed under — exactly the quiet history-editing the append-only rule exists to
prevent. Instead:

- the outstanding balance moves to the survivor, whose **credit limit is left
  alone** (summing two limits would grant more rope than anyone agreed to);
- `orders`, `purchases` and `khata_imports.rows` are repointed, because those
  name a party as a pointer rather than as history;
- `ledger` rows stay exactly where they were written, and
  `GET /api/parties/{id}/ledger` unions the survivor's entries with every merged
  profile's, each tagged with the name it was recorded under.

Because nothing is destroyed, a merge is reversible.

## Collection: `confirm_queue`

```
{
  item_id, source_type: "purchase" | "khata" | "order", source_id, row_id,
  field: "amount",
  source_image_url, crop_bbox,
  extracted_value: "₹4,250", confidence: 0.68,
  alternatives: ["₹4,250", "₹4,230", "₹1,250"],
  status: "pending" | "confirmed" | "corrected",
  resolved_value, resolved_at, resolved_by: "owner"
}
```
Index: `status ASC, created_at ASC`.

## Collection: `gst_registers` (doc id = period, e.g. `2026-07`)

```
{
  period: "2026-07",
  outward: { taxable, cgst, sgst, total, b2b: {...}, b2c: {...}, invoice_count },
  inward:  { taxable, cgst, sgst, total, invoice_count },
  net_liability,
  generated_at: "2026-08-01T06:02:00+05:30",
  summary_pdf_url, registers_csv_url,
  sent_to_ca_at, ca_channel: "whatsapp" | "email",
  status: "compiled" | "sent",
  trace_id
}
```

## Collection: `agent_traces` (UI trace strip + audit log)

```
{
  trace_id, event_type: "sale_order" | "purchase_inv" | "khata_page" | "gst_compile",
  ref: { type: "order", id: "ord_1043" },
  steps: [{
    agent: "credit_guardian",
    status: "done" | "flagged" | "error" | "waiting",
    started_at, ended_at, duration_ms: 340,
    output_summary: "Flagged — 92% of limit, suggest ₹15,000 advance",
    model: "gemini-flash", tokens_in, tokens_out
  }],
  status: "running" | "complete" | "awaiting_owner" | "failed",
  error: null, created_at
}
```
Index: `status ASC, created_at DESC`.

---

## Required composite indexes (`infra/firestore.indexes.json`)

| Collection | Fields |
|---|---|
| orders | `status ASC, created_at DESC` |
| orders | `party_id ASC, created_at DESC` |
| ledger | `party_id ASC, date DESC` |
| confirm_queue | `status ASC, created_at ASC` |
| purchases | `supplier_id ASC, invoice_date DESC` |
| agent_traces | `status ASC, created_at DESC` |

## Transaction boundaries (do not violate)

- **Approve order** → write `ledger` entry + increment `parties.credit.outstanding` + set `orders.status` — one transaction.
- **Confirm purchase** → increment each `inventory.qty_on_hand` + write supplier payable `ledger` entry + set `stock_applied: true` — one transaction, guarded by `stock_applied` so a retry can't double-count.
- **Commit khata import** → batch-write all confirmed rows to `ledger` + update each party's `outstanding` — one transaction.

## Security rules posture

Agents run server-side with the Admin SDK and bypass rules. Client rules allow read/write only to an authenticated owner account. For the hackathon a single owner UID is sufficient — do not ship open rules, judges do look.
