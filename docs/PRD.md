# Galla — Product & Design Document
### The Agentic Back Office for Indian Small Trade Shops
**Version 1.0 · For UI/UX design · Target: All Things Agentic Hackathon — Best Multimodal UX category**

---

## 1. What this product is

Galla replaces the two employees a small Indian shop can't afford: the data-entry person and the computer operator. It is a mobile-only web app (PWA) where a hardware-shop owner runs his entire back office — orders, purchases, credit ledger, GST — by doing only what he already does naturally: **speaking, photographing, and tapping**.

Behind the screen, a fleet of AI agents (Google ADK + Gemini multimodal on Google Cloud) does the heavy lifting asynchronously: parsing Tamil voice notes, reading handwritten material lists, extracting supplier invoices, digitizing decades-old paper ledgers, guarding contractor credit, and compiling monthly GST summaries while the shop sleeps.

**One-line pitch:** *Tally needs a computer and an operator. Galla needs only a phone camera and a thumb.*

**The name:** The *galla* is the cash drawer at every Indian shop counter — where the money lives. The product does exactly what the name promises: it guards the galla while the owner runs the shop. Design should quietly honor this (e.g., the credit-exposure gauge and Credit Guardian verdicts are "the galla being protected" — the emotional core of the brand).

**Brand lines:** English — *"Your shop. Your galla. Guarded."* · Demo/Tamil market line — *"Photo podunga, kanakku mudinjidum."*

**Design's job:** make an AI agent system feel as familiar as WhatsApp and as trustworthy as a handwritten ledger — while making the invisible agents *visibly* intelligent on screen (that visibility is what wins the Multimodal UX prize).

---

## 2. Who it's for (personas)

**P1 — Murugan, 52, shop owner (PRIMARY).** Runs a 25-year-old hardware shop near Coimbatore. Comfortable with WhatsApp and YouTube; has never used a spreadsheet. Wears reading glasses; shop counter is busy, dusty, sometimes dim. Interacts one-handed while standing, often interrupted mid-task. Reads Tamil first, English numerals fine. Deeply distrustful of software that hides where his money went — he trusts his paper khata because he can *see* every entry.

**P2 — Selvam, 38, contractor (SECONDARY, simulated in demo).** Orders materials by sending Tamil voice notes or photos of handwritten lists. Will never install an app. In the demo his side is a "Send as contractor" mode inside the same app.

**P3 — The CA (TERTIARY, passive).** Receives a monthly GST-ready summary (PDF + CSV). Never opens the app; appears in the product only as a delivery status ("Sent to CA ✓").

**P4 — The hackathon judge (META-AUDIENCE).** Watches a 4-minute video. Every screen must read instantly at video resolution: big verdicts, visible agent activity, obvious before/after. Design for the demo as much as for Murugan.

---

## 3. Design principles (in priority order)

1. **Zero learning curve.** The chat/inbox mental model everyone already has. If a screen needs explaining, redesign it.
2. **One thumb, standing up.** Primary actions in the bottom third. Touch targets ≥ 48px. No hover states matter; long-press is acceptable for secondary actions only.
3. **Trust through visibility.** Every AI decision shows its reasoning in one plain sentence. Every extracted number can be traced back to the source photo (tap a value → see the cropped region of the original image it came from). The paper khata earned trust by being inspectable; the app must match that.
4. **The agents are characters, not plumbing.** Show the fleet working: named agents lighting up in sequence, verdicts arriving with reasoning. This is the product's signature and the Multimodal UX differentiator.
5. **Bilingual by default.** Tamil + English side by side or toggle; ₹ and Indian number format (₹1,48,000 not ₹148,000) everywhere.
6. **Calm urgency.** Money decisions (credit flags) must be unmissable but never alarming — amber and firm, not red panic, unless truly escalated.

---

## 4. Complete feature list

### F1 — Order intake (voice / photo / text)
- Contractor's order arrives as: Tamil/Tanglish voice note, photo of a handwritten material list, or typed text.
- Intake Agent transcribes/reads it and resolves trade slang to real SKUs ("2 bag ramco 53" → Ramco Supergrade 53 OPC 50kg × 2; "10 adi ¾ pipe" → CPVC ¾" × 10 ft).
- Output: a structured draft order card with line items, matched SKUs, and per-line confidence.
- Ambiguous lines are marked and tappable to correct (shows top-3 SKU suggestions).

### F2 — Stock check & pricing
- Each draft order is checked against live inventory; out-of-stock lines show a suggested substitute ("Dalmia 53 available instead — accept?").
- Contractor-tier pricing applied automatically; owner can override a line price with a numeric keypad.

### F3 — Credit Guardian (THE STAR FEATURE)
- Before any credit order is confirmed, the agent checks the contractor's outstanding balance, credit limit, and payment history — and **decides**: 
  - ✅ **Approve** (green): within limit, good history.
  - ⚠️ **Part-payment** (amber): near limit; agent states the suggested advance amount.
  - ⛔ **Escalate** (red): over limit or overdue history; owner must decide.
- The verdict always appears with one-sentence reasoning in plain language: *"Selvam owes ₹87,400 of his ₹95,000 limit and last paid 34 days ago — suggest ₹15,000 advance."*
- This screen is the emotional center of the product. Design it like a decision, not a notification.

### F4 — Quotation / invoice generation
- One tap on Approve produces a GST-format quotation PDF: shop letterhead, HSN codes, CGST/SGST split, totals in words.
- PDF preview card in the thread; share/download actions.

### F5 — Purchase entry by photo
- Owner photographs a printed supplier invoice → Purchase Entry Agent extracts supplier, GSTIN, line items, quantities, tax.
- Result shown as an editable extraction table with a **confidence chip** per line (high = quiet, low = amber + tappable).
- On save: stock increments, supplier payable is recorded. Before/after stock counts shown ("GI Pipe ¾": 40 → 65).

### F6 — Khata digitization by photo
- Owner photographs a page of the old handwritten credit ledger → Khata Digitizer Agent returns structured entries (party, date, amount, paid/balance).
- Review screen shows the **original page photo and extracted rows side by side**; each row highlights its source region on the photo when tapped.
- Low-confidence rows go to a Confirm Queue (F8). This flow is the demo's "gasp" moment — design it to look magical but inspectable.

### F7 — Monthly GST compilation (fully autonomous)
- On the 1st of each month, Cloud Scheduler wakes the GST Compiler Agent: aggregates sales + purchase registers, splits B2B/B2C, produces a CA-ready summary PDF + CSV, and dispatches it.
- In the UI this is a Dashboard tile: month, status timeline ("Compiled 6:02 AM → Sent to CA ✓"), tap to preview the PDF.
- Copy must say "CA-ready summary" — never "files your GST."

### F8 — Approvals & Confirm Queue (human-in-the-loop)
- **Approval cards**: order + credit verdict + three fat buttons (Approve · Modify · Ask part-payment).
- **Confirm Queue**: a swipeable stack of low-confidence extractions; each card = source image crop on top, extracted value below, tap-to-correct with keypad. Clearing the queue should feel satisfying (progress count, subtle completion state).
- **Daily digest** (evening): today's orders, cash vs credit, exposure change, low stock — one glanceable card.

### F9 — Agent Activity panel (THE DEMO WEAPON)
- A live trace strip visible during processing and expandable afterwards: each agent as a named chip lighting up in sequence —
  *Intake ✓ → Stock & Pricing ✓ → Credit Guardian ⚠ FLAGGED → Quotation ⏸ waiting for owner*
- Expanded view shows each agent's one-line output and timing. This makes the multi-agent system *visible* — judges must be able to see the machine think.

### F10 — Shop Dashboard
- Tiles: today's sales (cash/credit split) · **total credit exposure gauge** with top-5 risky contractors · low-stock list · GST tile (F7) · pending approvals count.
- The exposure gauge is the owner's "is my money safe?" glance — give it weight.

### F11 — Demo/contractor mode
- A discreet toggle that lets the presenter send messages *as* the contractor from the same device (clearly labeled "Demo: sending as Selvam"). Must look intentional, not hacky — judges will see it.

---

## 5. Information architecture

Bottom tab bar, 3 tabs + 1 overlay:

1. **Counter** (default) — the chat-style inbox where everything arrives and is acted on. 80% of time lives here.
2. **Approvals** — badge-counted stack: approval cards + confirm queue.
3. **Shop** — dashboard (F10) + GST tile + settings (language, shop profile, credit limits).
- **Agent Activity** — not a tab; a slide-up panel attached to any processing message (F9).

The Counter thread contains typed message cards: incoming order (voice/photo/text) → agent trace strip → draft order card → verdict banner → quotation PDF card. One vertical story per order.

---

## 6. Key screens — required states

For every screen, design: default · loading/agent-working · success · low-confidence/partial · error+retry · empty (first-run).

**S1 Counter/inbox:** empty state invites first action ("Photograph a supplier bill or play a customer voice note — watch what happens"). Recording state: full-width waveform, Tamil prompt. Processing: agent trace strip animates in-thread.

**S2 Approval card:** the verdict banner dominates (color + icon + one-line reasoning); line items collapsed beneath; three buttons fill the bottom — Approve is the largest.

**S3 Invoice extraction review (F5):** photo thumbnail pinned top; extraction table below; confidence chips; sticky Save bar showing totals and stock delta.

**S4 Khata review (F6):** split view (photo ↕ rows) with tap-to-highlight source regions; count of auto-accepted vs needs-confirmation rows.

**S5 Confirm Queue (F8):** one card at a time, swipe/tap flow, progress "3 of 7", finishing state.

**S6 Dashboard (F10):** exposure gauge as the hero tile.

**S7 GST detail (F7):** month timeline + PDF preview + "Sent to CA" status.

---

## 7. Visual direction (a starting point — the designer may push further)

Ground the aesthetic in the shop's own world, not in generic fintech. The two sacred objects of Indian trade are the **red cloth-bound khata ledger** and the **carbon-copy bill book** — borrow their DNA:

- **Palette (named, indicative):** Ledger Red `#8C2B2B` (brand/accents, sparingly) · Bill-Book Blue `#2B4C7E` (primary actions, like carbon-copy ink) · Counter Cream `#FAF6EE` (background, aged-paper warmth) · Cement Grey `#8A8D8F` (secondary text/dividers) · Approval Green `#2E7D4F` · Caution Amber `#C77D1F`. Avoid neon SaaS gradients; this must feel like a tool a 52-year-old trusts with money.
- **Typography:** a characterful display face for numbers/verdicts (amounts are the heroes of every screen — consider a strong tabular-numeral face), a clean body face with excellent **Noto Sans Tamil** pairing. Tamil must never look like an afterthought font substitution.
- **Signature element (pick one and commit):** the recommended signature is the **agent trace strip** — a horizontal relay of named agent chips that light in sequence, unique to this product and demo-perfect. Alternative: ledger-ruled backgrounds (faint horizontal rules + red margin line) on financial cards, echoing the khata.
- **Motion:** one orchestrated moment — the trace strip lighting left-to-right as agents complete — and the verdict banner's arrival. Everything else calm. Respect reduced-motion.
- **Copy voice:** plain verbs, sentence case, bilingual. Buttons say what happens: "Approve order," "Ask ₹15,000 advance," "Confirm 3 entries." Reasoning sentences are written like a trusted munim (clerk) speaking: specific, brief, numeric.

---

## 8. Accessibility & environment

- Contrast AA minimum; test in bright sunlight simulation (shop counter is semi-outdoor).
- Touch targets ≥ 48px; primary actions reachable by right thumb on a 6.1–6.7" phone.
- All voice features have visual equivalents; all amounts readable without color (icon + text on verdicts).
- Indian formats everywhere: ₹, lakh/crore grouping, DD-MM-YYYY.

---

## 9. What "winning UX" means (judging alignment)

The category is **Best Multimodal UX** in a Google agentic-AI hackathon (rubric: 40% operational utility, 30% architecture, 30% demo/production polish). The design wins if a judge can, within 30 seconds of video:
1. See three input modalities working (voice note, handwriting photo, invoice photo).
2. See the multi-agent system visibly reasoning (trace strip) and *deciding* (verdict banner with reasoning).
3. Believe a non-technical 52-year-old could use it today — because it looks like a chat, not like software.

## 10. Out of scope (do not design)

Payment collection/UPI flows · reminder campaigns · e-way bills · actual GST portal filing · multi-shop management · desktop layouts (mobile-first only; a simple responsive stretch is enough) · contractor-side real app (demo mode only).

---

## 11. Demo choreography the design must support

The 4-minute video sequence, in order — every screen listed must be camera-ready:
1. Real shop footage → cut to Counter inbox (S1).
2. Contractor voice note arrives (demo mode) → trace strip animates → draft order card.
3. Credit Guardian flags at 92% → amber verdict banner with reasoning (S2) → owner taps "Ask ₹15,000 advance."
4. Quotation PDF card appears → open preview.
5. Owner photographs supplier invoice → extraction table with confidence chips → Save → stock 40 → 65 (S3).
6. Khata page photo → split review with source highlighting (S4) → confirm queue clears (S5).
7. Calendar flips → GST tile shows "Compiled 6:02 AM · Sent to CA ✓" (S7).
8. Close on Dashboard exposure gauge (S6) + Cloud Run console proof.
