# Galla PWA

React + Vite + Tailwind. Mobile-only, 390px design width, installable.

```bash
npm install
npm run dev          # http://localhost:5173, proxying /api to localhost:8080
npm run build        # -> dist/, which the Dockerfile copies into backend/web
```

Point at a different API with `GALLA_API=https://… npm run dev`.

## How it is put together

- **Tokens, not hex.** Every colour, size, radius and animation in
  `../design/DESIGN-TOKENS.md` is mapped into `tailwind.config.js` under its own
  name (`ink`, `accent`, `amber.deep`, `text-verdict`, `animate-gpulse`). A raw
  hex value in a component is a bug.
- **`TraceRelay` is the signature.** It renders the `agent_traces` document the
  backend writes — the dots the owner watches are the same record an auditor
  would read. Idle dots come from `/api/fleet`, so the strip shows the whole plan
  from the first frame instead of growing one dot at a time.
- **Polling, not Firestore listeners.** `usePolling` refetches while the tab is
  visible. `onSnapshot` would push instead of pull, but it needs client
  credentials in the bundle; polling the API keeps the app credential-free and
  looks identical on camera.
- **Derived state stays on the server.** Product names, `needs_confirm` and the
  substitution prompt are computed in `core/serialize.py` and `core/stock.py` at
  read time, so the UI never recomputes a number the books disagree with.

## Screens

| Route | Screen |
|---|---|
| `/` | S1 Counter — the thread everything arrives in |
| `/orders/:id` | S2 Approval — verdict, lines, three fat buttons |
| `/purchases/:id` | S3 Invoice extraction review |
| `/khata/:id` | S4 Khata review with tap-to-trace |
| `/queue` | S5 Confirm queue |
| `/shop` | S6 Dashboard — exposure gauge |
| `/gst/:period` | S7 GST detail |

The demo composer (F11) lives behind the header chip and only renders when the
backend reports `DEMO_MODE`.
