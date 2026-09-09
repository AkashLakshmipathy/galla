# Tax & Billing Engine — Specification

`backend/core/tax.py`. **Pure functions, fully unit-tested, no model, no I/O.** Never inline tax arithmetic inside an agent.

---

## 1. The design principle

A shopkeeper says **"bag ₹445, with tax."** Almost every billing package forces him to type ₹415 and watch the machine add tax — teaching him its arithmetic instead of speaking his. Galla accepts the price the way he says it and works backwards.

This is the product's key usability insight. Get it right.

## 2. Inclusive vs exclusive entry

A per-line flag, defaulted per party and remembered:

- **Counter / walk-in sale → inclusive** (`price_includes_tax: true`)
- **Contractor B2B → exclusive** (`price_includes_tax: false`)

```
exclusive:  taxable = entered_price
inclusive:  taxable = entered_price / (1 + rate/100)
tax         = (taxable × rate/100)        # exclusive
tax         = entered_price − taxable      # inclusive
```

## 3. Tax split by place of supply

Shop state = Tamil Nadu, state code **33**.

- **Same state** (party state == shop state, or unregistered walk-in) → **CGST + SGST**, half the rate each
- **Different state** → **IGST** at the full rate

**Splitting rule that guarantees no rounding drift:**
```
cgst = round_half_up(tax / 2, 2)
sgst = tax − cgst          # never round sgst independently
```

## 4. Rounding

1. Compute `taxable`, `tax`, `cgst`, `sgst` **per line**, rounded to 2 decimals (half-up, not banker's rounding).
2. Sum lines to get the invoice total.
3. Add a **`round_off`** line bringing the payable to a whole rupee (nearest; .50 rounds up).
4. `payable` is always an integer number of rupees.

## 5. Discount

Applied to the entered amount **before** tax back-calculation. Percentage or flat rupee.

```
net_entered = entered_total − discount
then apply §2 to net_entered
```

## 6. Test vectors — write these as tests first

### Single line, intra-state

| Entry | Rate | taxable | cgst | sgst | line total |
|---|---|---|---|---|---|
| 445.00 **inclusive** | 28% | 347.66 | 48.67 | 48.67 | 445.00 |
| 415.00 **exclusive** | 28% | 415.00 | 58.10 | 58.10 | 531.20 |
| 265.00 **inclusive** | 18% | 224.58 | 20.21 | 20.21 | 265.00 |
| 245.00 **exclusive** | 18% | 245.00 | 22.05 | 22.05 | 289.10 |

### Inter-state (IGST)

| Entry | Rate | taxable | igst | line total |
|---|---|---|---|---|
| 415.00 exclusive | 28% | 415.00 | 116.20 | 531.20 |

### Multi-line with round-off

```
3 × Ramco 53 @ 415.00 exclusive, 28%  → taxable 1245.00, cgst 174.30, sgst 174.30, total 1593.60
7 × CPVC 3/4 @ 245.00 exclusive, 18%  → taxable 1715.00, cgst 154.35, sgst 154.35, total 2023.70

subtotal_taxable = 2960.00
total_tax        =  657.30
gross            = 3617.30
round_off        =   -0.30
payable          = 3617.00
```

### Discount, inclusive entry

```
20 × Ramco 53 @ 445.00 inclusive, 28%, 5% discount
gross_entered = 8900.00
discount      =  445.00
net_entered   = 8455.00
taxable       = 8455.00 / 1.28 = 6605.47
tax           = 1849.53
cgst          =  924.77          # round_half_up(1849.53/2, 2)
sgst          =  924.76          # tax − cgst, never rounded independently
line total    = 8455.00
```

### Edge cases to cover
- Zero-rated / exempt SKU (rate 0) → tax 0, no split
- Price override to an arbitrary figure → recompute, never reject
- Single-paisa line where `tax/2` lands exactly on .005 → the `sgst = tax − cgst` rule must still balance
- Quantity with decimals (e.g. 2.5 kg)

## 7. Invoice numbering

Format: **`SBH/26-27/0042`**

- Consecutive, **unique per Indian financial year (April 1 – March 31)**
- Max 16 characters
- Never gaps, never duplicates

Implementation: `counters` collection, document `invoice#26-27`, incremented inside a Firestore transaction (`core/ids.py::next_invoice_number`). **Never read-then-write** — two counter sales in the same second must not be handed the same number.

Quotations use a separate counter (`quote#26-27`) and have no ledger effect until approved.

## 8. Tax invoice PDF

reportlab, rendered in the Cloud Run service, written to Cloud Storage, served back through `/api/media/...` so the PWA needs no signing credentials.

Must carry:
- Title **"Tax Invoice"** (or "Quotation" / "Duplicate" as applicable)
- Shop name, address, **GSTIN**, phone
- Invoice number and date
- **Place of supply**
- Party name and address; **party GSTIN when B2B**
- Line items: description, **HSN code**, qty, unit, rate, discount, taxable value, rate %, CGST, SGST (or IGST)
- Totals block: taxable, tax by component, round-off, **payable**
- **Amount in words**, Indian format ("Three Thousand Six Hundred and Seventeen Rupees Only"; lakh/crore for larger)

## 9. Delivery

**The device's native share sheet.** Owner taps Share, picks WhatsApp, sends the link.

No WhatsApp Business API (Meta approval), no SNS/SMS (needs DLT registration with TRAI), no SES dependency. Optional SES email if production access arrives — bonus, never a dependency.

## 10. Compliance language

- Say **"CA-ready summary"**, never "files your GST"
- **Never claim e-invoicing** — that is the IRN/QR-from-IRP regime with a turnover threshold that has changed repeatedly
- The defensible claim: *electronic delivery of a valid tax invoice, and every sale becomes a structured auditable record the moment it happens*
