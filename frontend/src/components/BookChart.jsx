import { inr, monthName, shortInr } from "../lib/format.js";

/* Shared by both books, because "money out against money back, over time" is
 * the same question whether the other party is a customer or a supplier. */

export function PeriodTabs({ value, onChange }) {
  return (
    <div className="flex gap-1">
      {[["month", "Monthly"], ["year", "Yearly"], ["all", "All time"]].map(
        ([key, label]) => (
          <button key={key} onClick={() => onChange(key)}
                  className={`px-2.5 py-1 rounded-full text-micro font-semibold
                    ${value === key ? "bg-ink text-white" : "bg-fill-2 text-text-2"}`}>
            {label}
          </button>
        ))}
    </div>
  );
}

export function periodLabel(period, granularity) {
  if (granularity === "all" || period === "all") return "All time";
  if (granularity === "year") return period;
  return monthName(period);
}

function shortLabel(period, granularity) {
  if (granularity === "all" || period === "all") return "All";
  if (granularity === "year") return String(period).slice(2);
  return monthName(period).slice(0, 3);
}

export function BookChart({ periods = [], granularity, outKey, backKey,
                            outLabel, backLabel }) {
  const shown = periods.slice(-12);
  const peak = Math.max(1, ...shown.map((p) => Math.max(p[outKey], p[backKey])));
  const moved = [...shown].reverse().filter((p) => p[outKey] || p[backKey]);

  return (
    <>
      <div className="flex items-baseline justify-between">
        <span className="text-supplier font-bold">
          {granularity === "all" ? "All time"
            : granularity === "year" ? "Year by year" : "Month by month"}
        </span>
        <span className="text-micro text-text-3">
          <span className="inline-block w-2 h-2 rounded-sm bg-ink mr-1" />{outLabel}
          <span className="inline-block w-2 h-2 rounded-sm bg-green ml-3 mr-1" />{backLabel}
        </span>
      </div>

      {/* Bar heights are in pixels, not percentages: a percentage height inside
          a flex-grown parent has no definite box to resolve against, so every
          bar collapsed to its min-height and the chart read as a flat line. */}
      {/* A year view has one point, and one flex-1 column is the whole card —
          the chart read as a solid black rectangle. Cap the column so a sparse
          series looks like a sparse series rather than a filled box. */}
      <div className={`flex items-end gap-2 mt-4 ${
        shown.length < 4 ? "justify-start" : ""}`}>
        {shown.map((p) => (
          <div key={p.period}
               className={`flex flex-col items-center gap-1 min-w-0 ${
                 shown.length < 4 ? "w-[64px]" : "flex-1"}`}>
            <div className="w-full flex items-end justify-center gap-[3px] h-[86px]">
              <div className="w-[42%] bg-ink rounded-t-[3px]"
                   style={{ height: `${Math.max(2, (p[outKey] / peak) * 86)}px` }} />
              <div className="w-[42%] bg-green rounded-t-[3px]"
                   style={{ height: `${Math.max(2, (p[backKey] / peak) * 86)}px` }} />
            </div>
            <span className="text-micro text-text-3 truncate w-full text-center">
              {shortLabel(p.period, granularity)}
            </span>
          </div>
        ))}
      </div>

      <div className="mt-4 pt-3 border-t border-separator">
        <div className="flex text-micro text-text-3 pb-1.5">
          <span className="flex-1">Period</span>
          <span className="w-[84px] text-right">{outLabel}</span>
          <span className="w-[84px] text-right">{backLabel}</span>
        </div>
        {/* Only periods where something happened. The full series belongs in the
            chart, where a flat month is information; as a table row it is nine
            lines of zero between the owner and the months he actually traded. */}
        {moved.length === 0 && (
          <div className="text-row text-text-3 py-3 text-center">
            Nothing recorded in this period yet.
          </div>
        )}
        {moved.map((p) => (
          <div key={p.period} className="flex text-row py-[5px] border-t border-separator">
            <span className="text-text-2 flex-1 truncate">
              {periodLabel(p.period, granularity)}
            </span>
            <span className="tnum w-[84px] text-right font-semibold">
              {shortInr(p[outKey])}
            </span>
            <span className="tnum w-[84px] text-right text-green font-semibold">
              {shortInr(p[backKey])}
            </span>
          </div>
        ))}
      </div>
    </>
  );
}

export function TotalsRow({ items }) {
  return (
    <div className="grid grid-cols-2 gap-x-4">
      {items.map((i) => (
        <div key={i.label} className="py-[7px] border-b border-separator last:border-0">
          <div className="text-micro text-text-3">{i.label}</div>
          <div className={`text-row font-semibold tnum mt-0.5 ${i.tone ?? ""}`}>
            {typeof i.value === "number" ? inr(i.value) : i.value}
          </div>
        </div>
      ))}
    </div>
  );
}
