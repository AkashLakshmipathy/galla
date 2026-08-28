import { inr } from "../lib/format.js";

/* The Credit Guardian's verdict — the emotional centre of the product.
 * Colour never carries meaning alone: every state pairs a dot or pill with the
 * word, so it reads in sunlight and to a colour-blind owner. */

export const VERDICT = {
  approve: {
    word: "Approved — within limit",
    tint: "bg-green-tint", fg: "text-green", dot: "bg-green",
    action: "Approve order",
  },
  part_payment: {
    word: "Part-payment suggested",
    tint: "bg-amber-tint", fg: "text-amber-deep", dot: "bg-amber",
    action: "Ask advance",
  },
  escalate: {
    word: "Escalated — your decision",
    tint: "bg-red-tint", fg: "text-red", dot: "bg-red",
    action: "Your call",
  },
};

export function VerdictPill({ decision }) {
  const tone = VERDICT[decision] ?? VERDICT.escalate;
  return (
    <span className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full
                      text-row font-semibold ${tone.tint} ${tone.fg}`}>
      <span className={`w-2 h-2 rounded-full ${tone.dot}`} />
      {tone.word}
    </span>
  );
}

export function VerdictDot({ decision, className = "" }) {
  const tone = VERDICT[decision] ?? VERDICT.escalate;
  return <span className={`w-2 h-2 rounded-full shrink-0 ${tone.dot} ${className}`} />;
}

/** The full decision block: pill, amount, party, reasoning, Tamil gloss. */
export function VerdictBlock({ verdict, party, total }) {
  if (!verdict) return null;
  return (
    <div className="text-center px-gutter pt-2 pb-5 animate-rise">
      <VerdictPill decision={verdict.decision} />
      <div className="text-verdict font-bold mt-4 tnum">{inr(total)}</div>
      <div className="text-body text-text-2 mt-1.5">
        {party?.name ?? verdict.party_id}
        {party?.price_tier ? ` · ${party.price_tier}` : ""}
      </div>
      <p className="text-action mt-4 mx-auto max-w-[300px] leading-[1.65]">
        {verdict.reason}
      </p>
      {verdict.reason_ta && (
        <p className="text-meta text-text-3 mt-2 mx-auto max-w-[300px]">
          {verdict.reason_ta}
        </p>
      )}
      <p className="text-micro text-text-3 mt-4 tnum">
        Rule {verdict.rule_fired} · {verdict.exposure_pct}% of limit · decided by
        rules, phrased by Gemini
      </p>
    </div>
  );
}

/** Inline variant for the Counter thread — a dot and one bold-lead sentence. */
export function VerdictInline({ verdict }) {
  if (!verdict) return null;
  const lead = { approve: "Within limit.", part_payment: "Near the limit.",
                 escalate: "Over the line." }[verdict.decision];
  return (
    <div className="flex gap-2 items-start">
      <VerdictDot decision={verdict.decision} className="mt-[6px]" />
      <p className="text-row text-ink flex-1">
        <span className="font-semibold">{lead} </span>
        <span className="text-text-2">{verdict.reason}</span>
      </p>
    </div>
  );
}
