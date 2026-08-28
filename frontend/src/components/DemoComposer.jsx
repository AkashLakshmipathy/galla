import { useEffect, useState } from "react";
import { api } from "../lib/api.js";
import { Row, Sheet } from "./ui.jsx";

/* F11 — the presenter's side of the counter.
 * Deliberately labelled and deliberately plain: judges will see this on camera,
 * so it should read as an intentional demo mode, not a hidden back door. It
 * posts to the same /ingest path a real WhatsApp webhook would. */

export function DemoChip({ onOpen, sendingAs }) {
  return (
    <button
      onClick={onOpen}
      className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-fill-2
                 text-meta font-semibold text-text-2"
    >
      <span className="w-[7px] h-[7px] rounded-full bg-amber" />
      {sendingAs ? `Sending as ${sendingAs}` : "Demo"}
    </button>
  );
}

export function DemoComposer({ open, onClose, onSent, onReset }) {
  const [scenarios, setScenarios] = useState([]);
  const [busy, setBusy] = useState(null);

  useEffect(() => {
    if (!open) return;
    api.demoScenarios().then((d) => setScenarios(d.scenarios)).catch(() => setScenarios([]));
  }, [open]);

  const send = async (key, label) => {
    setBusy(key);
    try {
      const result = await api.demoSend(key);
      onSent?.(result, label);
      onClose();
    } finally {
      setBusy(null);
    }
  };

  const reset = async () => {
    setBusy("reset");
    try {
      await api.demoReset();
      onReset?.();
      onClose();
    } finally {
      setBusy(null);
    }
  };

  return (
    <Sheet open={open} onClose={onClose} title="Demo controls">
      <div className="px-gutter pb-8">
        <p className="text-meta text-text-3 text-center -mt-1 mb-4">only you see this</p>
        <div className="bg-card rounded-card overflow-hidden">
          {scenarios.map((scenario) => (
            <Row key={scenario.key} chevron
                 onClick={() => send(scenario.key, scenario.label)}>
              <div className="text-body font-semibold">
                {busy === scenario.key ? "Sending…" : scenario.label}
              </div>
              <div className="text-meta text-text-3 mt-0.5">{scenario.sub}</div>
            </Row>
          ))}
        </div>
        <div className="bg-card rounded-card overflow-hidden mt-3.5">
          <Row chevron onClick={reset}>
            <div className="text-body font-semibold">
              {busy === "reset" ? "Resetting…" : "Reset demo"}
            </div>
            <div className="text-meta text-text-3 mt-0.5">
              Back to the start of the story
            </div>
          </Row>
        </div>
        <p className="text-micro text-text-3 text-center mt-4">
          Each of these publishes a real event through the same ingestion path as
          WhatsApp — the agents do the work either way.
        </p>
      </div>
    </Sheet>
  );
}
