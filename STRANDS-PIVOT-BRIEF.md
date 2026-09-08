# STRANDS PIVOT BRIEF — read this before touching the code

## The pivot in one paragraph

We are **not** moving to AWS infrastructure. Everything stays on Google Cloud — Cloud Run, Firestore, Cloud Storage, Pub/Sub, Cloud Scheduler, the frontend, the prompts, the whole deployed app. The **only** change is the agent layer: **Google ADK comes out, Strands Agents SDK goes in.** Strands is an open-source, cloud-agnostic Python library; it runs perfectly well inside our existing Cloud Run service. Every ADK import, reference, and dependency is removed from the repo.

**Why:** the hackathon (Agents for Humans) requires the Strands Agents SDK and nothing else. Bedrock/AgentCore deployment is explicitly optional. So we satisfy the requirement with a library swap instead of an infrastructure migration.

## Target architecture

| Layer | Stays / Changes |
|---|---|
| Agent orchestration | **CHANGES → Strands Agents SDK** |
| Model calls | **CHANGES → provider-swappable (see §5)** |
| Compute | Cloud Run — **unchanged** |
| Database | Firestore — **unchanged** |
| Object storage | Cloud Storage — **unchanged** |
| Events | Pub/Sub — **unchanged** |
| Scheduled jobs | Cloud Scheduler — **unchanged** |
| Frontend | React PWA — **unchanged** |
| Prompts & extraction schemas | **unchanged** |
| Business logic, tax engine, credit rules | **unchanged** |

**Anything in the repo that references DynamoDB, EventBridge, Lambda, S3, AgentCore or API Gateway from the earlier AWS plan should be deleted.** That plan is cancelled.

---

## STEP 0 — Inventory first. Report before changing anything.

1. List every file that imports or references Google ADK.
2. List every model call site (Gemini/Vertex) and what each does: audio, vision, text, structured extraction.
3. **Copy every tuned prompt verbatim into `docs/prompts/`** with the exact output schema each returns. These are the hardest-won asset in the repo — preserve them before any refactor.
4. List any partially-done AWS port work (DynamoDB, Lambda, EventBridge) so it can be deleted cleanly.
5. State which agents currently work end to end and which are partial.

Report this, then proceed.

---

## 1. Removing Google ADK — checklist

- [ ] Remove `google-adk` from `requirements.txt` / `pyproject.toml`
- [ ] Delete every `from google.adk import ...` and its usage
- [ ] Replace ADK agent classes with Strands equivalents (§3)
- [ ] Replace ADK tool registration with Strands `@tool`
- [ ] Remove ADK-specific session/state handling — our state lives in Firestore
- [ ] Grep the whole repo for `adk`, `Agent Development Kit`, `LlmAgent`, `SequentialAgent`, `ParallelAgent`, `LoopAgent` and clear every hit, including comments, README, and the architecture diagram
- [ ] Update the architecture diagram: the orchestration box now reads **Strands Agents SDK**, everything else unchanged

**Keep Vertex AI / Gemini as an option** — the model provider is a separate decision (§5). Removing ADK does not mean removing Gemini.

## 2. Install

```
pip install strands-agents strands-agents-tools
```

**Read the official docs before writing code:** https://strandsagents.com/ and the `strands-agents/sdk-python` repo. The SDK is new; do not infer its API from memory. Verify the exact class names, constructor arguments, and model-provider interfaces against the quickstart, then implement.

## 3. Strands implementation — agents-as-tools

Our existing structure already fits this pattern: an orchestrator calling specialists in sequence. In Strands, each specialist becomes a tool the orchestrator can call.

Expected shape (**verify against the docs**):

```python
from strands import Agent, tool

@tool
def credit_guardian(party_id: str, order_total: int) -> dict:
    """Decide whether this credit order is safe: approve, part-payment, or escalate."""
    party = firestore_get_party(party_id)
    verdict = decide(party, order_total)      # pure rules — unchanged, no model
    return explain(verdict, party)            # one small model call for phrasing

orchestrator = Agent(
    model=MODEL,                              # from §5
    system_prompt=ORCHESTRATOR_PROMPT,
    tools=[intake, pricing_tax, stock_check, credit_guardian, billing, notifier],
)
```

**Mapping from the current fleet:**

| Current agent | Becomes |
|---|---|
| Orchestrator / router | Strands `Agent` with the specialists as tools |
| Intake | `@tool` — multimodal extraction (model call) |
| Pricing & Tax | `@tool` — **pure function, no model** |
| Stock | `@tool` — **pure lookup, no model** |
| Credit Guardian | `@tool` — **rules decide, one model call to phrase** |
| Billing | `@tool` — **no model** |
| Purchase entry | `@tool` — vision/OCR extraction |
| Khata digitiser | `@tool` — vision extraction |
| GST compiler | Separate `Agent`, triggered by Cloud Scheduler |
| Notifier | `@tool` — **no model** |

Keep the trace-step wrapper around every tool so the UI trace strip and audit log keep working exactly as they do now.

## 4. Event flow — unchanged

Pub/Sub push → Cloud Run endpoint → Strands orchestrator → tools → Firestore/GCS. Cloud Scheduler → the GST agent monthly. Do not rewrite this; only the orchestrator's internals change.

## 5. Model provider — make it swappable

Put the provider behind one module (`core/model.py`) exposing a single `MODEL` object, so it can be switched with an environment variable and no other file changes.

**Option A — Bedrock (preferred if an AWS account is available).** Strands' native provider. Costs roughly $5–15 in pay-per-token for this build, needs **no AWS infrastructure at all** — no Lambda, no DynamoDB, no NAT gateway, nothing hourly. This is real AWS usage in an AWS-sponsored hackathon and removes the weakest point in our submission.

**Option B — Gemini via LiteLLM (fallback if no AWS account).** Strands supports LiteLLM as a provider, which fronts Gemini. Zero AWS, uses our existing GCP credits, breaks no rule. Honest trade-off: the judges are AWS employees and one criterion is technical use of the stack, so expect this to cost us something on that criterion even though it is permitted.

Build for A, keep B working as a fallback. The swap must be one env var.

## 6. Do not change

- Firestore schema, collections, or transaction boundaries
- The tax engine (`core/tax.py`) and its tests
- Credit Guardian's `decide()` — pure rules, no model
- Prompts and extraction schemas (adapt wording only if the model provider changes; keep schemas and few-shot examples identical)
- The React frontend — not a pixel
- Design tokens

## 7. Hard rules (carry over unchanged)

1. **Rules decide money; the model explains.** Persist `rule_fired` on every verdict.
2. **Five of the ten agents call no model at all** (pricing, stock, billing, notifier, and the Credit Guardian's decision). Keep it that way — it is better engineering and near-zero cost.
3. **Confidence gates the books.** Below threshold → confirm queue, never silently into ledger or inventory.
4. **Ledger is append-only.** Corrections are reversing entries.
5. **Every tool opens a trace step.** The trace strip and audit log depend on it.
6. **Every model call needs a deterministic fallback.** The demo must never show an empty state because an API call failed.
7. **Money moves only inside Firestore transactions** — the three boundaries already implemented.
8. Copy says **"CA-ready summary"**, never "files your GST". Never claim e-invoicing.

## 8. Submission requirements

- **Public repo with MIT or Apache licence visible in the About section** — a missed checkbox loses a prize
- README with setup verified from a clean clone
- Architecture diagram (updated: Strands orchestration on Cloud Run)
- **Live demo URL** — and it must stay up through the whole judging period; the rules require the project to be available to judges without restriction until judging ends. Cloud Run scales to zero, so this is nearly free
- Demo video **≤ 5 minutes**, showing it working end to end, explicitly stating **the problem, who it's for, why it matters**
- AWS Builder ID linked (free to create, no card needed)
- Track: **Professional Agents**
- Three posts on builder.aws.com, hashtag **#AgentsforHumans** — worth up to 0.6 on a 1–5 scale, roughly 12% of the maximum, earned by writing rather than building

## 9. Plan to the deadline

Hard deadline **Mon Sept 14, 5:00pm PDT**. Target submission **Sat Sept 12**.

| Slot | Work |
|---|---|
| 1 | Step 0 inventory · strip ADK · install Strands · read the docs · `core/model.py` with both providers |
| 2 | Port the orchestrator + Intake, Pricing/Tax, Stock, Credit Guardian as Strands tools. Trace wrapper intact |
| 3 | Port Billing, Notifier, Purchase entry, GST agent. Full end-to-end run on Cloud Run |
| 4 | Redeploy · verify all three credit verdict states · update README, licence, architecture diagram · live URL confirmed from another device |
| 5 | Freeze. Record the 5-minute video. Write the three builder.aws.com posts |
| 6 (Sat 12) | **Submit.** Devpost flags missing items on early submissions — that safety net is free |

*If an AWS account is going to happen, claim the $50 credits before the form closes Fri Sept 11, 12:00pm PT.*

## 10. First task

Run Step 0 and report. Then strip ADK and stand up `core/model.py` with both providers behind one env var. Getting a single Strands agent to answer through our existing Cloud Run service is the first milestone — prove that before porting the rest.
