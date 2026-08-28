# Galla — 4-minute demo video script

Judging weight: Demo & Production Readiness is 30%. Record live and unedited.
Show the Google Cloud backend on screen — this is a hard submission requirement.

| Time | Beat | What is on screen |
|---|---|---|
| 0:00-0:20 | The problem | Real footage: shop counter, paper khata, handwritten slips. VO: a 25-year-old shop, no computer, credit tracked on paper. |
| 0:20-0:35 | The promise | "Tally needs a computer and an operator. Galla needs a phone camera and a thumb." Cut to Counter inbox. |
| 0:35-1:15 | Async intake + agents thinking | Demo composer sends Selvam's Tamil voice note. Trace strip animates: Intake ✓ → Stock & Pricing ✓ → Credit Guardian ! → waiting. Show the out-of-stock substitute prompt (Ramco short → Dalmia). |
| 1:15-1:50 | **The decision (the money shot)** | Amber verdict: "Selvam owes ₹87,400 of his ₹95,000 limit, last paid 34 days ago — ask ₹15,000 advance." Say aloud: the decision is rule-based and auditable; Gemini only phrases it. Tap "Ask ₹15,000 advance". |
| 1:50-2:10 | Output | Quotation PDF preview, GST split, share. |
| 2:10-2:45 | No data-entry person | Photograph supplier bill → extraction table, 72% line flagged amber → fix → save → stock 40 → 65. |
| 2:45-3:15 | The gasp | Photograph an old khata page → rows extracted, tap a row → source region highlights on the photo → 3 low-confidence rows to confirm queue → clear it. |
| 3:15-3:35 | Fully autonomous | GST tile: "Compiled 6:02 AM · Sent to CA ✓". Say: Cloud Scheduler fired this on the 1st, nobody opened the app. |
| 3:35-4:00 | Proof + close | Cloud Run console, Pub/Sub subscription, Firestore documents, agent_traces audit log. Close on the exposure gauge. |

Do not say "files your GST" — say "CA-ready summary".
