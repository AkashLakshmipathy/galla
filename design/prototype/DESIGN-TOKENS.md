# Galla — Design Tokens & Component Spec (v3)
Source of truth: `Galla Prototype v3.dc.html`. Mobile-only PWA, 390px design width.

## Color
| Token | Hex | Use |
|---|---|---|
| `ink` | `#111113` | Primary text, primary buttons, done states |
| `text-2` | `#77777C` | Secondary text |
| `text-3` | `#AEAEB2` | Tertiary text, timestamps, placeholders |
| `chevron` | `#C7C7CC` | Chevrons, idle dots, disabled button bg |
| `bg` | `#F4F4F6` | App background, input fills |
| `card` | `#FFFFFF` | Cards (no border, no shadow) |
| `separator` | `#F0F0F2` | Hairline row separators (1px) |
| `fill-2` | `#EEEEF0` | Secondary buttons, demo chip |
| `fill-3` | `#E9E9EB` | Search field, progress track |
| `sheet` | `#F9F9FA` | Bottom sheets |
| `accent` | `#0A6BE0` | Links, back chevron, active trace dot, play button |
| `green` | `#28934E` (tint `#EAF6EE`) | Approve verdict, success |
| `amber` | `#C97F0E` (deep `#9C6408`, tint `#FBF2E0`) | Part-payment, flagged, low confidence |
| `red` | `#D23B2E` (tint `#FCEDEB`) | Escalate, decline, low stock, badge |
| Khata paper | `#FBFAF6`, rules `#EDE8DA`, margin `rgba(180,60,50,.3)`, ink `#4A463C` | Photo panels only |

Rules: color only where it means something; verdicts always pair dot/pill + word (never color alone); one black primary action per screen.

## Type
Stack: `-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', 'Noto Sans', 'Noto Sans Tamil', sans-serif`. All amounts `font-variant-numeric: tabular-nums`.
- 46/700, -2px tracking — verdict amount (S2)
- 38/700, -1.5px — queue extracted value
- 32/700, -1.1px — tab screen titles
- 30/700, -1px — gauge amount; 27/700 dashboard count; 22/700 tiles & completion
- 17/700 — invoice supplier name; 15/600 — buttons, row titles, headers
- 14/400-600 — body, list rows, reasoning
- 13/400-600 — secondary rows, status lines
- 12/400-600 — meta, labels, Tamil sublines
- 10-11/500-600 — trace labels, chips, LOW badge, tab labels

Formats: ₹ Indian grouping (₹1,12,500), DD-MM-YYYY.

## Spacing & shape
Base-4: 4, 8, 12, 14, 16, 18, 20, 24. Screen gutter 16; card padding 18; row padding 13-16px vertical, 18 horizontal; row min-height 52; gap between cards 14.
Radii: cards/sheet-cards 18; inputs/photo panels 12-14; sheets 22 22 0 0; buttons & chips 999 (pill). No shadows (khata paper: `inset 0 0 0 1px rgba(0,0,0,.04)`).

## Motion
`rise` (fade + 8px up, .3-.45s) for arrivals; `gpulse` ring on active trace dot; queue progress `width .3s`. Trace timing ~0.5/1.4/2.5/3.7s (÷ traceSpeed). Respect reduced-motion.

## Components
**Trace relay (signature)** — four 24px dots + 10px labels, joined by 1.5px lines (done `ink`, else `#E9E9EB`). States: idle `#F0F0F2`/`·`, active `accent` white `…` + gpulse, done `ink` white `✓`, flagged `amber` white `!`, waiting `#F0F0F2`/`⏸`. One plain-language status line + "Detail" link (opens agent activity sheet: grouped list, mark / name / timing / one-line output).
**Verdict** — S2 decision sheet: tinted pill (13/600, verdict tint bg + deep fg) → amount 46/700 centered → party line → reasoning sentence (15/1.65, max-width 300, centered) + Tamil (12, text-3). Inline (thread) variant: 8px verdict dot + one bold-lead sentence.
**Fat pill button** — width 100%, radius 999. Primary 54px black/white (red `#D23B2E` for Decline); secondary 48px `fill-2` black text; tertiary 44px text-only accent. Stacked, gap 6, bottom bar padding 12 20 22. All targets ≥44-48px.
**Confidence chip** — pill 4×10px, 11/600. High: `bg` fill, text-3, "98%". Low: amber tint + deep amber, "72% · fix", tappable → green tint "Corrected ✓".
**Voice bubble** — inside white card: 40px gray avatar circle with initials, name + "Contractor · via WhatsApp", pill waveform capsule (`bg` fill, 34px accent play circle, 2.5px `chevron` bars), Tamil transcript 14/1.6 + English gloss 12 text-2.
**Grouped list row** — white card container, rows separated by 1px `separator`, chevron `chevron`. Approval row: 8px verdict dot + name + amount + truncated reason.
**Gauge** — 180° arc, 9px round stroke, track `separator`, value in zone color (green <40%, amber 40-75%, red >75%); centered amount + "of ₹X · N%".
**Sheets** — scrim `rgba(17,17,19,.35)`, `sheet` bg, radius 22 top, 36×4 handle, centered title, grouped-list options, text-only Cancel.

## Copy
Buttons say what happens ("Ask ₹15,000 advance", "Send 3 to confirm queue"). Reasoning: one specific numeric sentence. English primary + Tamil where the owner speaks it. GST: "CA-ready summary", never "files your GST".

## Components — batch 2
**Processing state** — centered mock document (150px, `#FBFAF6`, inset ring `rgba(0,0,0,.05)`, `#EDE8DA` rule bars) + three 7px `accent` dots (`blink` 1s, .2s stagger) + "Reading your bill…" 15/600 with Tamil subline 12 text-3. Shown ~1.7s before any extraction review.
**Pinned source strip** — `position:sticky` top of the extraction scroll (app-bg mask behind): white card radius 14, 34×44 doc thumbnail + name 14/600 + meta 11 text-3.
**Editable extraction row** — grouped-list row, meta line "qty × rate · GST 18% = amount". Tap opens Line editor; the amber low-confidence row's first tap applies the suggested fix directly (chip → green "Corrected ✓"; user-changed rows show "Edited ✓"). Save bar totals recompute live (GST shown as 18/118 of total).
**Line editor sheet** — sheet (max-height 86%, scrolls); per line: name + optional ✕ remove (30px circle `fill-2`, order mode only, min 1 line); stepper pill (`bg` fill, 40px −/＋ targets, tabular qty); rate chip "@ ₹610" (accent text) opens keypad; line total right. Footer: running total 15/700 + black Done pill. Order edits rewrite the approval's items/GST/amount (GST keeps the order's original effective rate).
**Numeric keypad** — inside editor sheet: white card, label 12 text-2, value 30/700 tabular, 3-col grid of 48px keys radius 12 — digits `bg` fill, ⌫ `fill-2`, ✓ black/white. Max 6 digits.
**Doc preview sheet** — sheet + page mock (white, radius 14, inset ring, 20px pad): letterhead row (name 13/700 + GSTIN 10 text-3), 12px line items (secondary lines text-2), bold total row, 10px centered footer. Buttons: Download (`fill-2`) + Share on WhatsApp (black). Variants: quotation (#Q-…, "Valid 7 days · UPI …") and GST summary ("CA-ready · Galla does not file your GST").
**Voice capture screen** — 8px `red` blink dot + timer 34/700 tabular; full-width waveform (3px `ink` bars, `wv` scaleY .9s, staggered delays); Tamil prompt 17/600 + English line 13 text-2; 68px `red` stop circle with 20px white rounded square, "Tap to stop" 12 text-3.
**Camera confirm screen** — `ink` background; ✕ top-left (white), centered title/sub white; rotated paper mock preview (±0.5°); bottom pills: Retake `rgba(255,255,255,.14)` white text + "Use this photo" white pill ink text.
**Offline banner** — pill bar, `fill-2` bg, 12/600 text-2, 6px text-3 dot: "Offline — saved locally, will sync".
**Error / retry card** — white card: 8px `red` dot, title 15/600, reassurance 13 text-2 ("Kept safely on your phone"), accent "Retry" right. Uploading state swaps copy and hides the action; success routes into the processing state.
**Toast** — `green-tint` card, 13/600 green, centered, auto-dismiss ~3.2s.
**Empty state (first-run)** — white card 44px pad, centered: 52px `bg` icon circle, title 17/700 bilingual, body 13 text-2 (max-width 240), black primary pill + accent text-link secondary.
**Daily digest card** — white card "Today's close · 6:00 PM"; hairline rows (13px, label text-2 / value 600): orders count + revenue, cash/credit split, exposure with delta (green/red 12px), low stock → Inventory link row.
**Substitution suggestion** — inline in draft list: 8px `amber` dot + bold-lead sentence ("Ramco 53 is short — 12 of 20…"); pills Switch (black) / Keep (`fill-2`); collapses to a 12px gray note; totals and quotation update on accept.
**Demo composer sheet** — 7px `amber` dot + "Demo controls", sub "only you see this"; grouped rows: send voice note, send bill photo, upload failure, offline, empty state, reset, hide chrome. Chip in header opens it; never rendered outside demo mode.
