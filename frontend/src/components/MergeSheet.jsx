import { useState } from "react";
import { FatPill, Sheet } from "./ui.jsx";
import { inr } from "../lib/format.js";

/* Merging two profiles that turned out to be one trader.
 *
 * This is the most consequential tap in the app — it moves money between
 * accounts — so the sheet shows the arithmetic before it happens, states plainly
 * which name survives, and says that nothing is deleted. */

function Side({ party, role }) {
  return (
    <div className="flex-1 min-w-0">
      <div className="text-micro text-text-3 uppercase tracking-wide">{role}</div>
      <div className="text-body font-semibold truncate mt-0.5">{party?.name}</div>
      <div className="text-meta text-text-2 tnum mt-0.5">
        {inr(party?.credit?.outstanding)} of {inr(party?.credit?.limit)}
      </div>
    </div>
  );
}

export function MergeSheet({ open, onClose, pair, onMerge }) {
  const [keep, setKeep] = useState("a");
  const [busy, setBusy] = useState(false);
  if (!pair) return null;

  const target = keep === "a" ? pair.a : pair.b;
  const source = keep === "a" ? pair.b : pair.a;
  const combined = (target?.credit?.outstanding ?? 0) + (source?.credit?.outstanding ?? 0);
  const limit = target?.credit?.limit ?? 0;
  const exposure = limit ? Math.round((combined / limit) * 100) : 0;

  const run = async () => {
    setBusy(true);
    try {
      await onMerge(source.party_id, target.party_id);
      onClose();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet open={open} onClose={onClose} title="Merge these profiles?">
      <div className="px-gutter pb-8">
        <div className="bg-card rounded-card p-cardpad">
          <div className="flex gap-3">
            <Side party={pair.a} role="Profile A" />
            <Side party={pair.b} role="Profile B" />
          </div>
          <p className="text-meta text-text-2 mt-3 pt-3 border-t border-separator">
            Flagged because of a {pair.reason}.
          </p>
        </div>

        <div className="mt-3.5">
          <div className="text-meta font-semibold text-text-3 uppercase tracking-wide
                          px-1 mb-2">
            Which name to keep
          </div>
          <div className="bg-card rounded-card overflow-hidden">
            {[["a", pair.a], ["b", pair.b]].map(([key, party]) => (
              <button
                key={key}
                onClick={() => setKeep(key)}
                className="w-full px-[18px] py-[14px] flex items-center gap-3 text-left
                           border-b border-separator last:border-0 active:bg-separator"
              >
                <span className={`w-[18px] h-[18px] rounded-full border-2 shrink-0
                  ${keep === key ? "border-ink bg-ink" : "border-chevron"}`} />
                <span className="text-body font-semibold flex-1 truncate">
                  {party?.name}
                </span>
                {party?.provisional && (
                  <span className="text-micro text-text-3">from a scan</span>
                )}
              </button>
            ))}
          </div>
        </div>

        <div className="bg-card rounded-card p-cardpad mt-3.5">
          <div className="text-meta font-semibold text-text-3 uppercase tracking-wide mb-2">
            After merging
          </div>
          <div className="flex justify-between py-[7px] text-row">
            <span className="text-text-2">{target?.name} will owe</span>
            <span className="font-semibold tnum">{inr(combined)}</span>
          </div>
          <div className="flex justify-between py-[7px] text-row border-t border-separator">
            <span className="text-text-2">Credit limit (unchanged)</span>
            <span className="font-semibold tnum">{inr(limit)}</span>
          </div>
          <div className="flex justify-between py-[7px] text-row border-t border-separator">
            <span className="text-text-2">Exposure</span>
            <span className={`font-semibold tnum ${
              exposure > 100 ? "text-red" : exposure > 85 ? "text-amber-deep" : "text-green"}`}>
              {exposure}%
            </span>
          </div>
          {exposure > 85 && (
            <p className="text-meta text-amber-deep mt-2 pt-2 border-t border-separator">
              Their real exposure is higher than either profile showed on its own.
              That is what a duplicate hides.
            </p>
          )}
        </div>

        <p className="text-micro text-text-3 mt-3.5 px-1 leading-relaxed">
          Nothing is deleted. {source?.name}&apos;s past entries stay exactly where
          they were written and appear in {target?.name}&apos;s history labelled with
          the name they were filed under. Orders and bills move across.
        </p>

        <div className="mt-4 space-y-1.5">
          <FatPill onClick={run} disabled={busy}>
            {busy ? "Merging…" : `Merge into ${target?.name}`}
          </FatPill>
          <FatPill variant="tertiary" onClick={onClose}>
            They are different people
          </FatPill>
        </div>
      </div>
    </Sheet>
  );
}
