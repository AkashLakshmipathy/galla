# Demo video (5 min) + submission checklist

## The film

**Open on paper. Close on the paper gone.** Everything else is detail.

Max 5 minutes. The rules require it to state, out loud, **the problem, who it is
for, and why it matters** — say those three things in the first forty seconds
rather than trusting the footage to imply them.

Slides, screen recording and voiceover are all fine. Nobody has to be on camera.

| Time | Beat | Say |
|---|---|---|
| 0:00–0:40 | A real shop counter. The paper khata. The carbon-copy bill book. | "Twenty-five years of accounts, on paper. Most of the revenue is credit, and credit on paper is what kills shops like this — the owner cannot see who owes him what until it is too late." |
| 0:40–1:10 | Why the obvious fix never arrived | "Billing software exists. The licence was never the cost — a computer on a counter with no room for it, its upkeep, and a person trained to sit and operate it. **Galla removes that person. Not the shopkeeper — the data-entry clerk.**" |
| 1:10–2:10 | **Khata digitisation.** Photograph a real handwritten page. The trace strip lights agent by agent. Rows appear with dates and amounts; the customer's name sits at the top where it can be corrected. Tap *Post 12 entries to the ledger*. | "He photographs the page he already writes. Twelve entries, into the books, in the time it took to take the photo." |
| 2:10–3:00 | **The credit decision.** Open an order from a contractor near his limit. The amber verdict, in English and Tamil. | "The rules decided this, not the model — the model only put it into a sentence he can read. Every verdict stores which rule fired, so any decision can be explained months later." |
| 3:00–3:50 | **Counter sale.** Type three letters, tap the product, enter **445 with tax** — the way he says it. The split is worked backwards. Bill. Share to WhatsApp. | "Every other package makes him type 415 and watch the machine add tax. This one speaks his arithmetic. A GST-compliant tax invoice, on the customer's phone, before he leaves the counter." |
| 3:50–4:20 | **The agent nobody triggers.** Cloud Scheduler fires the GST compiler on the 1st. Show the CA-ready summary. | "Nobody opened the app. It is a CA-ready summary — Galla does not file anything, and never claims to." |
| 4:20–5:00 | Architecture diagram · the live URL on screen · close on the exposure gauge | "Strands Agents on Cloud Run. Ten agents; five of them never call a model at all — pricing, stock, billing, notification, and the credit decision itself. That is why it runs on almost nothing." |

### Three lines worth landing word for word

- **"Galla removes the data-entry clerk, not the shopkeeper."**
- **"Rules decide the money. The model only explains the decision."**
- **"He keeps writing on paper exactly as he does today, and the books keep themselves."**

### Do not say

"Files your GST" · "e-invoicing" · "IRN" · "fully automated bookkeeping". Galla
issues a valid tax invoice and produces a CA-ready summary. That is the
defensible claim and it is a strong one.

## Checklist

- [x] Public repo, **MIT licence visible in the About section**
- [x] README, setup verified from a clean clone
- [x] Architecture diagram — Strands orchestration on Cloud Run
- [x] **Live demo URL** — https://galla-tosijyjgva-el.a.run.app
- [ ] **Passcode in the submission text** — the app is gated and the rules
      require judges to reach it without restriction; a private site is allowed
      *provided the credentials are supplied*
- [ ] Video ≤ 5 min, states problem / who / why
- [x] AWS Builder ID linked — @akashlp
- [ ] Text description: what it does, who it is for, how it works, roadmap
- [x] Track selected: **Professional Agents**
- [ ] Three builder.aws.com posts, hashtag **#AgentsforHumans**, published
      before the deadline. Suggested: (1) agents-as-tools with Strands and why
      the orchestrator sequences but never decides; (2) why the real cost of
      shop software was a salary, not a licence; (3) rules decide, the model
      explains — and what it takes to hold that line in code
- [ ] Submitted **Sat Sept 12**, not the 14th — Devpost flags missing items on
      early submissions and that safety net is free
