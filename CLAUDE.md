# Instructions for Claude Code — Galla

## Context
Galla is a working web app on Google Cloud (Cloud Run, Firestore, Gemini) used on real
shop data. We are entering the **Agents for Humans Hackathon** (Professional Agents track).
Hard deadline **Mon Sept 14, 5:00pm PDT**; target submission **Sat Sept 12**.

**The only required change is the agent layer: Google ADK out, Strands Agents SDK in.**
All GCP infrastructure stays. The earlier AWS-infrastructure port plan is CANCELLED —
delete any DynamoDB / Lambda / EventBridge / S3 / AgentCore work from that attempt.

**Read `STRANDS-PIVOT-BRIEF.md` first and run its Step 0 before changing anything.**

## Read before writing code
1. `STRANDS-PIVOT-BRIEF.md` — authoritative for this build
2. `docs/TAX-ENGINE-SPEC.md` — tax/billing arithmetic (already spec'd; do not re-derive)
3. `docs/firestore-schema.md` — data model, unchanged
4. `design/DESIGN-TOKENS.md` — styling, unchanged
5. **The official Strands docs** (https://strandsagents.com/) — do NOT infer the SDK API
   from memory. Verify class names, constructor args and model-provider interfaces first.

## Hard rules
1. Rules decide money; the model explains. Persist `rule_fired`. `decide()` stays a pure
   function with no model call.
2. Five of the ten agents call no model at all (pricing, stock, billing, notifier, and the
   Credit Guardian's decision itself). Keep it that way.
3. Below the confidence threshold → confirm queue. Never silently into ledger or inventory.
4. Ledger is append-only. Corrections are reversing entries.
5. Every tool opens a trace step — the UI trace strip and audit log depend on it.
6. Every model call needs a deterministic fallback. The demo must never show an empty
   state because an API call failed.
7. Money moves only inside Firestore transactions — the three existing boundaries.
8. Tax arithmetic lives only in `core/tax.py`. Never inline it in an agent.
9. Copy says "CA-ready summary", never "files your GST". Never claim e-invoicing.
10. Model provider lives behind `core/model.py` and is switchable by one env var
    (Bedrock preferred; Gemini-via-LiteLLM fallback).

## Do not touch
Firestore schema · tax engine and its tests · prompts and extraction schemas (preserve
verbatim in `docs/prompts/` before refactoring) · the React frontend · design tokens ·
Pub/Sub and Cloud Scheduler wiring.

## Style
- Python: type hints, dataclasses for tool outputs, no ORM.
- Keep each agent/tool file under ~150 lines.
- Grep for `adk`, `LlmAgent`, `SequentialAgent`, `ParallelAgent`, `LoopAgent` and clear
  every hit including comments, README and diagram labels.

## Scope discipline
Working end-to-end beats complete. If the port is not running end to end by slot 3,
stop adding and harden what exists. A half-built feature that breaks on camera is worse
than one named as roadmap.
