import { useState } from "react";
import { useParams } from "react-router-dom";
import { BackBar } from "../components/BackBar.jsx";
import { Processing } from "../components/Processing.jsx";
import { TraceRelay } from "../components/TraceRelay.jsx";
import { Card, ConfidenceChip, FatPill, NewBadge } from "../components/ui.jsx";
import { api } from "../lib/api.js";
import { ddmmyyyy, inr } from "../lib/format.js";
import { usePolling } from "../lib/hooks.js";

/* S4 — khata review. The photograph on top, the extracted rows below, and a tap
 * on a row highlights the exact handwriting it came from.
 *
 * This is the trust mechanism the whole product rests on: the paper khata earned
 * the owner's confidence by being inspectable, so a digital entry that cannot be
 * traced back to its ink is worth less than the paper it replaced. */

function PageWithHighlight({ path, rows, selected }) {
  const active = rows.find((row) => row.row_id === selected);
  return (
    <div className="relative rounded-input overflow-hidden bg-khata-paper
                    shadow-[inset_0_0_0_1px_rgba(0,0,0,.04)]">
      {path ? (
        <img src={path} alt="The khata page" className="w-full block" />
      ) : (
        <MockPage rows={rows} selected={selected} />
      )}
      {active && path && (
        <span
          className="absolute rounded-[4px] ring-2 ring-accent bg-accent/10
                     transition-all duration-300 pointer-events-none"
          style={{
            left: `${active.bbox.x * 100}%`,
            top: `${active.bbox.y * 100}%`,
            width: `${active.bbox.w * 100}%`,
            height: `${active.bbox.h * 100}%`,
          }}
        />
      )}
    </div>
  );
}

/** Until a real photograph is attached, draw the ruled page so the tap-to-trace
 *  interaction is still demonstrable and the bboxes are visibly meaningful. */
function MockPage({ rows, selected }) {
  return (
    <div className="relative w-full" style={{ paddingBottom: "125%" }}>
      <div className="absolute inset-0">
        <div className="absolute top-0 bottom-0 left-[8%] w-px
                        bg-[rgba(180,60,50,.3)]" />
        {rows.map((row) => {
          const isActive = row.row_id === selected;
          return (
            <div key={row.row_id}
                 className={`absolute flex items-baseline gap-2 px-1 text-khata-ink
                   transition-all duration-300 rounded-[4px]
                   ${isActive ? "ring-2 ring-accent bg-accent/10" : ""}`}
                 style={{
                   left: `${row.bbox.x * 100}%`,
                   top: `${row.bbox.y * 100}%`,
                   width: `${row.bbox.w * 100}%`,
                   height: `${row.bbox.h * 100}%`,
                 }}>
              <span className="text-[11px] flex-1 truncate">{row.party_name_raw}</span>
              <span className="text-[10px] opacity-70 tnum">
                {String(row.date ?? "").slice(8)}
              </span>
              <span className="text-[11px] tnum">{Math.round(row.amount)}</span>
            </div>
          );
        })}
        {rows.map((row) => (
          <div key={`rule-${row.row_id}`}
               className="absolute left-0 right-0 h-px bg-khata-rule"
               style={{ top: `${(row.bbox.y + row.bbox.h) * 100}%` }} />
        ))}
      </div>
    </div>
  );
}

export function KhataReview({ onToast }) {
  const { importId } = useParams();
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);

  const { data: fleet } = usePolling(api.fleet, { interval: 0 });
  const { data: record, refresh } = usePolling(() => api.khata(importId),
    { interval: 1500, deps: [importId] });
  const { data: trace } = usePolling(
    () => (record?.trace_id ? api.trace(record.trace_id) : Promise.resolve(null)),
    { interval: 1500, active: Boolean(record?.trace_id), deps: [record?.trace_id] });

  if (!record) {
    return <Processing title="Reading the khata page…"
                       titleTa="கணக்குப் புத்தகத்தைப் படிக்கிறேன்…" />;
  }

  const rows = record.rows ?? [];
  const pending = rows.filter((row) => row.status === "needs_confirm");
  const committed = record.status === "committed";

  const commit = async () => {
    setBusy(true);
    try {
      const result = await api.commitKhata(importId);
      onToast?.(`${result.posted} entries posted to the ledger ✓`);
      await refresh();
    } catch (error) {
      onToast?.(error.message ?? "Could not post those entries");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <BackBar title={`Khata page ${record.page_no ?? ""}`}
               sub={`${record.auto_accepted_count} clear · ${record.needs_confirm_count} to confirm`} />

      <div className="px-gutter pb-40 space-y-3.5">
        <PageWithHighlight path={record.page_image_path} rows={rows} selected={selected} />
        <p className="text-micro text-text-3 text-center -mt-1">
          Tap any row below to see where it came from
        </p>

        <Card className="p-cardpad">
          <TraceRelay trace={trace} chain={fleet?.chains?.khata_page ?? []} />
        </Card>

        <div className="bg-card rounded-card overflow-hidden">
          {rows.map((row) => (
            <button
              key={row.row_id}
              onClick={() => setSelected(selected === row.row_id ? null : row.row_id)}
              className={`w-full px-[18px] py-[13px] text-left border-b border-separator
                last:border-0 ${selected === row.row_id ? "bg-separator" : ""}`}
            >
              <div className="flex items-start gap-3">
                <div className="flex-1 min-w-0">
                  <div className="text-body font-semibold truncate">
                    {row.party_name_raw}
                  </div>
                  {row.is_new_party && (
                    <div className="text-micro text-accent mt-0.5">
                      No account yet — posting opens{" "}
                      {row.is_company ? "a company" : "a personal"} account
                    </div>
                  )}
                  {row.near_miss && (
                    <div className="text-micro text-amber-deep mt-0.5">
                      Might be {row.near_miss.name} — confirm which
                    </div>
                  )}
                  <div className="text-meta text-text-2 tnum mt-0.5">
                    {ddmmyyyy(row.date)} ·{" "}
                    {row.entry_type === "payment_received" ? "paid" : "on credit"}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-body font-semibold tnum">{inr(row.amount)}</div>
                  <div className="mt-1">
                    {row.is_new_party ? (
                      <NewBadge>New account</NewBadge>
                    ) : (
                      <ConfidenceChip value={row.confidence}
                                      corrected={row.status === "confirmed"} />
                    )}
                  </div>
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>

      <div className="fixed bottom-0 left-0 right-0 z-30 bg-bg/95 backdrop-blur">
        <div className="mx-auto max-w-[430px] px-5 pt-3 pb-[22px] space-y-1.5 safe-bottom">
          {committed ? (
            <FatPill disabled>Posted to the ledger ✓</FatPill>
          ) : (
            <>
              {record.new_party_count > 0 && pending.length === 0 && (
                <p className="text-micro text-accent text-center mb-2">
                  {record.new_party_count} new{" "}
                  {record.new_party_count === 1 ? "account" : "accounts"} will be
                  opened
                </p>
              )}
              <FatPill onClick={commit} disabled={busy || pending.length > 0}>
                {busy ? "Posting…"
                  : pending.length > 0
                    ? `Clear ${pending.length} in the confirm queue first`
                    : `Post ${rows.length} entries to the ledger`}
              </FatPill>
              {pending.length > 0 && (
                <p className="text-micro text-text-3 text-center pt-1">
                  {pending.length} rows are below the shop's confidence threshold —
                  they never post unread.
                </p>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
