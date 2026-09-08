import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { TraceRelay } from "../components/TraceRelay.jsx";
import { VerdictDot, VerdictInline } from "../components/Verdict.jsx";
import { VoiceBubble } from "../components/VoiceBubble.jsx";
import { Card, Chevron, EmptyState } from "../components/ui.jsx";
import { api } from "../lib/api.js";
import { ago, inr } from "../lib/format.js";
import { usePolling } from "../lib/hooks.js";

/* S1 — the Counter. Everything arrives here and is acted on here; 80% of the
 * owner's time lives on this one screen, so it is a thread, not a dashboard.
 *
 * It polls fast while any chain is still running and slows right down once the
 * shop is quiet — the trace strip has to feel live without holding a phone
 * radio open all afternoon. */

function useCounterFeed() {
  const { data: fleet } = usePolling(api.fleet, { interval: 0 });
  const feed = usePolling(api.counter, { interval: 1200 });
  const items = feed.data?.items ?? [];
  const busy = items.some((item) =>
    ["running"].includes(item.data?.trace?.status)
    || item.data?.status === "draft");
  return { ...feed, items, chains: fleet?.chains ?? {}, busy };
}

function DocThumb({ path, kind, tall = false }) {
  const size = tall ? "w-[44px] h-[56px]" : "w-[34px] h-[44px]";
  // A voice note has no page to show. A blank sheet of paper would be a lie
  // about what arrived, so it gets its own mark.
  if (kind === "order" && !path) {
    return (
      <div className={`${size} rounded-[6px] bg-fill-2 shrink-0 flex items-center
                       justify-center gap-[2px]`} aria-hidden="true">
        {[7, 13, 9, 15, 8].map((h, i) => (
          <span key={i} className="w-[2px] rounded-full bg-text-3"
                style={{ height: `${h}px` }} />
        ))}
      </div>
    );
  }
  return (
    <div className={`${size} rounded-[6px] bg-khata-paper shrink-0 overflow-hidden
                     shadow-[inset_0_0_0_1px_rgba(0,0,0,.06)]`}>
      {path && <img src={path} alt="" className="w-full h-full object-cover" />}
    </div>
  );
}

function ThreadItem({ item, chains }) {
  const navigate = useNavigate();
  const [showTrace, setShowTrace] = useState(false);
  const { kind, data } = item;
  const { data: trace } = usePolling(
    () => (data.trace_id ? api.trace(data.trace_id) : Promise.resolve(null)),
    { interval: 1200, active: Boolean(data.trace_id) }
  );
  const running = !trace || trace.status === "running";
  // A walk-in ran two agents, not six. Showing the full sale chain would draw
  // four idle dots for steps that were never going to run on this sale.
  const chainKey = kind === "order"
    ? (data.source === "counter" ? "counter_sale" : "sale_order")
    : { purchase: "purchase_inv", khata: "khata_page" }[kind];
  const steps = trace?.steps ?? [];
  const flagged = steps.filter((s) => s.status === "flagged").length;

  const open = () => navigate(
    kind === "order" ? `/orders/${data.order_id}`
      : kind === "purchase" ? `/purchases/${data.purchase_id}`
        : `/khata/${data.import_id}`);

  const title = kind === "order" ? (data.party_name ?? data.party_id)
    : kind === "purchase" ? (data.supplier_name_raw ?? "Supplier bill")
      : `Khata page ${data.page_no ?? ""}`;

  const line = kind === "order"
    ? `${data.lines?.length ?? 0} items · ${inr(data.total)}`
    : kind === "purchase"
      ? `${data.lines?.length ?? 0} lines · ${inr(data.totals?.total)}`
      : `${data.auto_accepted_count ?? 0} clear · ${data.needs_confirm_count ?? 0} to confirm`;

  // Only the order status is a snake_case token needing prettifying; the others
  // are already written as sentences and must not be title-cased.
  const state = kind === "order"
    ? (({ awaiting_approval: "Waiting on you", approved: "Approved",
          rejected: "Declined", fulfilled: "Fulfilled", draft: "Draft",
          unreadable: "Could not read this — open it" })[data.status]
       ?? String(data.status ?? "").replace(/_/g, " "))
    : kind === "purchase"
      ? (data.stock_applied ? "Stock updated ✓" : "Review and save to stock")
      : (data.status === "committed" ? "Posted to the ledger ✓" : "Review the page");

  return (
    <Card className="animate-rise overflow-hidden">
      {kind === "order" && running && (
        <VoiceBubble
          name={data.party_name ?? data.party_id} tier={data.price_tier}
          source={data.source} mediaPath={data.source_media_path}
          transcript={data.transcript} gloss={data.transcript_en}
        />
      )}

      {/* While the agents work the strip is the point of the screen. Once they
          are done it collapses to a single line, because five finished bills
          should read as five rows, not fifteen cards. */}
      {running ? (
        <div className="p-cardpad">
          {kind !== "order" && (
            <div className="flex items-center gap-3 mb-3.5">
              <DocThumb path={data.source_image_path ?? data.page_image_path}
                        kind={kind} />
              <div className="min-w-0">
                <div className="text-body font-semibold truncate">{title}</div>
                <div className="text-meta text-text-3">{ago(item.at)}</div>
              </div>
            </div>
          )}
          <TraceRelay trace={trace} chain={chains[chainKey] ?? []} />
        </div>
      ) : (
        <>
          <button onClick={open}
                  className="w-full p-cardpad flex items-center gap-3 text-left">
            <DocThumb path={data.source_image_path ?? data.page_image_path}
                      kind={kind} tall />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                {kind === "order" && data.credit_verdict && (
                  <VerdictDot decision={data.credit_verdict.decision} />
                )}
                <span className="text-body font-semibold truncate">{title}</span>
              </div>
              <div className="text-body font-semibold tnum mt-0.5">{line}</div>
              <div className="text-meta text-text-3">{state}</div>
            </div>
            <Chevron />
          </button>

          {kind === "order" && data.credit_verdict && (
            <div className="px-cardpad pb-cardpad -mt-1">
              <VerdictInline verdict={data.credit_verdict} />
            </div>
          )}

          <button
            onClick={() => setShowTrace((v) => !v)}
            className="w-full px-cardpad py-2.5 flex items-center gap-2
                       border-t border-separator text-meta text-text-2"
          >
            <span className={`w-[6px] h-[6px] rounded-full
              ${flagged ? "bg-amber" : "bg-ink"}`} />
            <span className="flex-1 text-left">
              {steps.length} agents ran
              {flagged ? ` · ${flagged} flagged something` : " · nothing flagged"}
            </span>
            <span className="text-accent font-semibold">
              {showTrace ? "Hide" : "Show"}
            </span>
          </button>
          {showTrace && (
            <div className="px-cardpad pb-cardpad pt-1">
              <TraceRelay trace={trace} chain={chains[chainKey] ?? []} />
            </div>
          )}
        </>
      )}
    </Card>
  );
}

export function Counter() {
  const { items, chains, loading } = useCounterFeed();
  const navigate = useNavigate();

  return (
    <div className="px-gutter pt-2 space-y-3.5">
      <div className="flex items-center justify-between pt-1 pb-2">
        <h1 className="text-screen font-bold">Counter</h1>
        {/* The walk-in path. The camera button handles paper arriving; this is
            the customer standing in front of the owner right now. */}
        <button
          onClick={() => navigate("/sell")}
          className="h-[38px] px-4 rounded-full bg-ink text-white text-body
                     font-semibold active:opacity-80"
        >
          New sale
        </button>
      </div>

      {!loading && items.length === 0 && (
        <EmptyState
          icon="◎"
          title="Your shop is ready"
          titleTa="உங்கள் கடை தயார்"
          body="Tap the camera button and photograph a supplier bill. The products and quantities add themselves — you do not type anything in."
        />
      )}

      {items.map((item) => (
        <ThreadItem key={`${item.kind}-${item.id}`} item={item} chains={chains} />
      ))}
    </div>
  );
}
