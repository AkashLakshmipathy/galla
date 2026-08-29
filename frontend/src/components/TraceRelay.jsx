import { useState } from "react";
import { Sheet } from "./ui.jsx";

/* The trace relay — the product's signature.
 *
 * Four named agents joined by a line, lighting up left to right as each one
 * finishes. It is doing real work: every dot is a step in the `agent_traces`
 * document the backend writes, so what the owner watches on screen is the same
 * record an auditor would read afterwards.
 *
 * The dots for agents that have not started yet come from the chain declared by
 * /api/fleet, so the strip shows the whole plan from the first frame rather than
 * growing a dot at a time. */

const LABELS = {
  intake: "Intake",
  stock_pricing: "Stock & Pricing",
  credit_guardian: "Credit Guardian",
  quotation: "Quotation",
  purchase_entry: "Purchase Entry",
  khata_digitizer: "Khata Digitizer",
  gst_compiler: "GST Compiler",
  notifier: "Notifier",
};

const MARKS = { done: "✓", flagged: "!", error: "✕", waiting: "⏸", active: "…", idle: "·" };

const DOT = {
  done: "bg-ink text-white",
  flagged: "bg-amber text-white",
  error: "bg-red text-white",
  active: "bg-accent text-white animate-gpulse",
  waiting: "bg-separator text-text-3",
  idle: "bg-separator text-text-3",
};

function statusLine(steps, status) {
  const active = steps.find((s) => s.status === "active");
  if (active) {
    return {
      intake: "Listening to the voice note…",
      stock_pricing: "Intake done — matching items to stock…",
      credit_guardian: "Prices applied — checking the ledger…",
      quotation: "Verdict in — drawing up the quotation…",
      purchase_entry: "Reading your bill…",
      khata_digitizer: "Reading the khata page…",
      gst_compiler: "Compiling the month…",
      notifier: "Sending it on…",
    }[active.agent] ?? "Working…";
  }
  if (status === "failed") return "Something went wrong — nothing was saved.";
  const flagged = steps.some((s) => s.status === "flagged");
  const parked = steps.some((s) => s.status === "waiting");
  // Only claim a decision is needed when something was actually flagged. Saying
  // it over two green ticks teaches the owner to ignore the line entirely.
  if (flagged || parked) return "Flagged — your decision is needed.";
  if (status === "awaiting_owner") return "Read and ready for you.";
  if (status === "complete") return "All agents finished.";
  return "Working…";
}

export function TraceRelay({ trace, chain = [], compact = false }) {
  const [open, setOpen] = useState(false);
  const steps = trace?.steps ?? [];
  const byAgent = new Map();
  steps.forEach((step) => byAgent.set(step.agent, step));

  const planned = chain.length ? chain : steps.map((s) => s.agent);
  const dots = planned.map((agent) => ({
    agent,
    label: LABELS[agent] ?? agent,
    step: byAgent.get(agent),
    status: byAgent.get(agent)?.status ?? "idle",
  }));

  return (
    <>
      <div className="animate-rise">
        <div className="flex items-start">
          {dots.map((dot, index) => (
            <div key={dot.agent} className="flex-1 flex flex-col items-center relative">
              {index > 0 && (
                <span
                  className={`absolute h-[1.5px] top-[11.25px] right-1/2 w-full
                    ${dots[index - 1].status === "done"
                      || dots[index - 1].status === "flagged"
                      ? "bg-ink" : "bg-fill-3"}`}
                />
              )}
              <span
                className={`relative w-6 h-6 rounded-full flex items-center
                  justify-center text-chip font-semibold z-10 ${DOT[dot.status]}`}
                aria-label={`${dot.label}: ${dot.status}`}
              >
                {MARKS[dot.status] ?? "·"}
              </span>
              <span className="mt-1.5 text-micro font-medium text-text-2 text-center
                               leading-tight px-0.5">
                {dot.label}
              </span>
            </div>
          ))}
        </div>

        {!compact && (
          <div className="flex items-center justify-between mt-3">
            <span className="text-meta text-text-2">
              {statusLine(steps, trace?.status)}
            </span>
            <button onClick={() => setOpen(true)}
                    className="text-meta font-semibold text-accent shrink-0 pl-3">
              Detail
            </button>
          </div>
        )}
      </div>

      <Sheet open={open} onClose={() => setOpen(false)} title="Agent activity">
        <div className="px-gutter pb-8">
          <div className="bg-card rounded-card overflow-hidden">
            {steps.length === 0 && (
              <div className="px-[18px] py-4 text-row text-text-2">
                No agent has run yet.
              </div>
            )}
            {steps.map((step, index) => (
              <div key={`${step.agent}-${index}`}
                   className="px-[18px] py-[14px] border-b border-separator last:border-0">
                <div className="flex items-center gap-2">
                  <span className={`w-5 h-5 rounded-full flex items-center justify-center
                                    text-micro font-semibold ${DOT[step.status]}`}>
                    {MARKS[step.status] ?? "·"}
                  </span>
                  <span className="text-body font-semibold flex-1">
                    {LABELS[step.agent] ?? step.agent}
                  </span>
                  <span className="text-meta text-text-3 tnum">
                    {step.duration_ms != null ? `${step.duration_ms} ms` : "—"}
                  </span>
                </div>
                {step.output_summary && (
                  <p className="text-row text-text-2 mt-1.5 pl-7">{step.output_summary}</p>
                )}
                {step.model && (
                  <p className="text-micro text-text-3 mt-1 pl-7 tnum">
                    {step.model}
                    {step.tokens_in ? ` · ${step.tokens_in}→${step.tokens_out} tokens` : ""}
                  </p>
                )}
              </div>
            ))}
          </div>
          {trace?.trace_id && (
            <p className="text-micro text-text-3 mt-3 px-1 tnum">
              trace {trace.trace_id} · written to Firestore <code>agent_traces</code>
            </p>
          )}
        </div>
      </Sheet>
    </>
  );
}

export { LABELS as AGENT_LABELS };
