import { useNavigate } from "react-router-dom";
import { TraceRelay } from "../components/TraceRelay.jsx";
import { VerdictInline } from "../components/Verdict.jsx";
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

function ThreadItem({ item, chains }) {
  const navigate = useNavigate();
  const { kind, data } = item;
  const { data: trace } = usePolling(
    () => (data.trace_id ? api.trace(data.trace_id) : Promise.resolve(null)),
    { interval: 1200, active: Boolean(data.trace_id) }
  );
  const running = trace?.status === "running";
  const chainKey = { order: "sale_order", purchase: "purchase_inv",
                     khata: "khata_page" }[kind];

  return (
    <div className="space-y-3.5 animate-rise">
      {kind === "order" && (
        <Card>
          <VoiceBubble
            name={data.party_name ?? data.party_id}
            tier={data.price_tier}
            source={data.source}
            mediaPath={data.source_media_path}
            transcript={data.transcript}
            gloss={data.transcript_en}
          />
        </Card>
      )}
      {kind !== "order" && (
        <Card className="p-cardpad flex items-center gap-3">
          <div className="w-[34px] h-[44px] rounded-[6px] bg-khata-paper
                          shadow-[inset_0_0_0_1px_rgba(0,0,0,.06)] shrink-0" />
          <div className="min-w-0">
            <div className="text-body font-semibold truncate">
              {kind === "purchase"
                ? data.supplier_name_raw ?? "Supplier bill"
                : `Khata page ${data.page_no ?? ""}`}
            </div>
            <div className="text-meta text-text-3 truncate">
              {kind === "purchase"
                ? `Invoice ${data.invoice_no ?? "—"} · ${ago(data.created_at)}`
                : `${data.rows?.length ?? 0} entries · ${ago(data.created_at)}`}
            </div>
          </div>
        </Card>
      )}

      <Card className="p-cardpad">
        <TraceRelay trace={trace} chain={chains[chainKey] ?? []} />
      </Card>

      {!running && kind === "order" && data.credit_verdict && (
        <Card className="p-cardpad space-y-3.5">
          <VerdictInline verdict={data.credit_verdict} />
          <button onClick={() => navigate(`/orders/${data.order_id}`)}
                  className="w-full flex items-center gap-3 pt-1">
            <div className="flex-1 text-left">
              <div className="text-body font-semibold">
                {data.lines?.length ?? 0} items · {inr(data.total)}
              </div>
              <div className="text-meta text-text-3 capitalize">
                {String(data.status ?? "").replace(/_/g, " ")}
              </div>
            </div>
            <Chevron />
          </button>
        </Card>
      )}

      {!running && kind === "purchase" && (
        <Card>
          <button onClick={() => navigate(`/purchases/${data.purchase_id}`)}
                  className="w-full flex items-center gap-3 p-cardpad">
            <div className="flex-1 text-left">
              <div className="text-body font-semibold">
                {data.lines?.length ?? 0} lines · {inr(data.totals?.total)}
              </div>
              <div className="text-meta text-text-3">
                {data.stock_applied ? "Stock updated ✓" : "Review and save to stock"}
              </div>
            </div>
            <Chevron />
          </button>
        </Card>
      )}

      {!running && kind === "khata" && (
        <Card>
          <button onClick={() => navigate(`/khata/${data.import_id}`)}
                  className="w-full flex items-center gap-3 p-cardpad">
            <div className="flex-1 text-left">
              <div className="text-body font-semibold">
                {data.auto_accepted_count} clear · {data.needs_confirm_count} to confirm
              </div>
              <div className="text-meta text-text-3">
                {data.status === "committed" ? "Posted to the ledger ✓" : "Review the page"}
              </div>
            </div>
            <Chevron />
          </button>
        </Card>
      )}
    </div>
  );
}

export function Counter() {
  const { items, chains, loading } = useCounterFeed();

  return (
    <div className="px-gutter pt-2 space-y-3.5">
      <h1 className="text-screen font-bold pt-1 pb-2">Counter</h1>

      {!loading && items.length === 0 && (
        <EmptyState
          icon="◎"
          title="Nothing at the counter yet"
          titleTa="இன்னும் எதுவும் இல்லை"
          body="Photograph a supplier bill or play a customer voice note — watch what happens."
        />
      )}

      {items.map((item) => (
        <div key={`${item.kind}-${item.id}`} className="pb-1">
          <div className="text-micro text-text-3 pb-2 pl-1">{ago(item.at)}</div>
          <ThreadItem item={item} chains={chains} />
        </div>
      ))}
    </div>
  );
}
