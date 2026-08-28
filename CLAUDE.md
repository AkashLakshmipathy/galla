# Instructions for Claude Code — Galla

## Context
Hackathon build, deadline 31 Aug 2026 5:00pm PT. Optimise for a working demo of the
happy path over completeness. A half-built feature that breaks on camera is worse
than a feature we scoped out and mentioned as roadmap.

## Before you write code
Read `README.md` (build order), `docs/firestore-schema.md` (data model),
`design/DESIGN-TOKENS.md` (styling). These three are authoritative — do not invent
field names, do not invent colors.

## Hard rules
1. Do NOT import or build on `design/*.dc.html` or `support.js`. Visual reference only.
2. Read `backend/agents/credit_guardian_agent.py` first — it is the reference
   implementation. Every other agent follows its shape: `run(payload, trace) -> dict`,
   one `trace.step(...)`, a one-line human-readable `step.summary`.
3. Rules decide money; the LLM extracts and explains. Persist `rule_fired`.
4. Anything below `CONFIDENCE_THRESHOLD` routes to `confirm_queue`, never to the books.
5. Ledger writes are transactional and append-only.
6. Every model call must have a deterministic fallback — the demo must never show
   an empty state because an API call failed.
7. Copy says "CA-ready summary", never "files your GST".

## Style
- Python: type hints, dataclasses for agent outputs, no ORM, Admin SDK direct.
- Frontend: React + Vite + Tailwind; map DESIGN-TOKENS.md into tailwind.config.js
  as named tokens (`ink`, `accent`, `green`, `amber`, `red`, ...) — no raw hex in components.
- Keep agent files under ~150 lines. If one grows past that, it is doing too much.

## When stuck on scope
Priority order is P0 → P1 → P2 in README. If P0 is not fully working, do not start P1.
