import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { BackBar } from "../components/BackBar.jsx";
import { Processing } from "../components/Processing.jsx";
import { TraceRelay } from "../components/TraceRelay.jsx";
import { RowEditor } from "../components/RowEditor.jsx";
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
              <span className="text-chip flex-1 truncate">{row.party_name_raw}</span>
              <span className="text-micro opacity-70 tnum">
                {String(row.date ?? "").slice(8)}
              </span>
              <span className="text-chip tnum">{Math.round(row.amount)}</span>
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
  const navigate = useNavigate();
  const [selected, setSelected] = useState(null);
  const [editing, setEditing] = useState(null);
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
  // Every row on a page belongs to the same account, so one row answers this.
  const isNewParty = rows.some((r) => r.is_new_party);

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

        {/* A khata page is one customer's running account, so the name belongs
            here once — not stamped onto all twelve rows, which turned a page
            into a wall of the same three lines repeated. It also puts the name
            where it can be questioned: the model read it off handwriting, and
            if it read it wrong the owner should see that at the top, before he
            reads any amount underneath it. */}
        <Card className="p-cardpad">
          <div className="flex items-start gap-3">
            <div className="flex-1 min-w-0">
              <div className="text-meta text-text-3">Whose account this is</div>
              <div className="text-tile font-bold truncate mt-0.5">
                {record.party_name_raw || "Not read"}
              </div>
              {isNewParty && (
                <div className="text-meta text-accent mt-1">
                  No account yet — posting opens one
                </div>
              )}
            </div>
            {isNewParty && <NewBadge>New account</NewBadge>}
          </div>
        </Card>

        <div className="bg-card rounded-card overflow-hidden">
          {rows.map((row) => (
            <div
              key={row.row_id}
              onClick={() => setSelected(selected === row.row_id ? null : row.row_id)}
              className={`w-full px-[18px] py-[13px] text-left border-b border-separator
                last:border-0 ${selected === row.row_id ? "bg-separator" : ""}`}
            >
              <div className="flex items-start gap-3">
                <div className="flex-1 min-w-0">
                  {/* Not every khata line carries a date. Saying so is better
                      than an empty heading, and it tells him which rows need a
                      date typed in before they post. */}
                  <div className={`text-body font-semibold tnum ${
                    row.date ? "" : "text-text-3 font-normal"}`}>
                    {row.date ? ddmmyyyy(row.date) : "No date on the page"}
                  </div>
                  <div className="text-meta text-text-2 mt-0.5">
                    {row.entry_type === "payment_received"
                      ? "paid" : "on credit"}
                    {row.note ? ` · ${row.note}` : ""}
                  </div>
                  {row.near_miss && (
                    <div className="text-micro text-amber-deep mt-0.5">
                      Might be {row.near_miss.name} — confirm which
                    </div>
                  )}
                </div>
                <div className="text-right shrink-0">
                  <div className={`text-body font-semibold tnum ${
                    row.entry_type === "payment_received" ? "text-green" : ""}`}>
                    {row.entry_type === "payment_received" ? "− " : ""}
                    {inr(row.amount)}
                  </div>
                  {!row.is_new_party && (
                    <div className="mt-1">
                      <ConfidenceChip value={row.confidence}
                                      corrected={row.status === "confirmed"} />
                    </div>
                  )}
                </div>
              </div>
              {/* Any row can be wrong, not only the ones the agent doubted. */}
              {selected === row.row_id && !committed && (
                <button
                  onClick={(e) => { e.stopPropagation(); setEditing(row); }}
                  className="mt-2.5 text-meta font-semibold text-accent"
                >
                  Edit this entry
                </button>
              )}
            </div>
          ))}
        </div>
      </div>

      <RowEditor
        open={Boolean(editing)} row={editing} importId={importId}
        onClose={() => setEditing(null)}
        onSaved={async () => { await refresh(); onToast?.("Entry updated"); }}
      />

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
              {/* This used to be a dead end: a disabled button telling the
                  owner to go to the confirm queue, on a screen with no way to
                  get there. The only link lived on Approvals, so the answer to
                  "clear them first" was to go back and hunt. If we are going to
                  send him somewhere, send him. */}
              {pending.length > 0 && !busy ? (
                <FatPill onClick={() => navigate("/queue")}>
                  Confirm {pending.length} row{pending.length === 1 ? "" : "s"} first
                </FatPill>
              ) : (
                <FatPill onClick={commit} disabled={busy}>
                  {busy ? "Posting…"
                        : `Post ${rows.length} entries to the ledger`}
                </FatPill>
              )}
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
