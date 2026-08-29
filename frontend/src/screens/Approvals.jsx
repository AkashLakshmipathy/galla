import { useNavigate } from "react-router-dom";
import { VerdictDot } from "../components/Verdict.jsx";
import { useState } from "react";
import { Card, Chevron, EmptyState, FatPill, GroupedList, Row, SectionLabel } from "../components/ui.jsx";
import { api } from "../lib/api.js";
import { ago, inr } from "../lib/format.js";
import { usePolling } from "../lib/hooks.js";

/* Approvals — the badge-counted stack. Orders waiting on a decision, then the
 * confirm queue of things the agents were not sure enough about to book. */

export function Approvals({ onToast }) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const { data, loading, refresh } = usePolling(api.approvals, { interval: 2500 });
  const orders = data?.orders ?? [];
  const queue = data?.confirm_queue ?? [];
  const ready = data?.khata_ready ?? [];
  const waiting = data?.khata_waiting ?? [];
  const unsaved = data?.purchases_unsaved ?? [];

  const postAll = async () => {
    setBusy(true);
    try {
      const result = await api.commitReadyKhata();
      onToast?.(`${result.entries} entries posted`
        + (result.accounts_opened ? `, ${result.accounts_opened} accounts opened` : ""));
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="px-gutter pt-2 space-y-5">
      <h1 className="text-screen font-bold pt-1">Approvals</h1>

      {/* Work that is finished and simply has not been posted. Without this it
          is invisible, and a day's scanning sits in review looking done. */}
      {ready.length > 0 && (
        <div>
          <SectionLabel>Read and ready — not yet in your books</SectionLabel>
          <Card className="p-cardpad">
            <div className="text-tile font-bold">
              {ready.length} {ready.length === 1 ? "page" : "pages"} ready to post
            </div>
            <p className="text-row text-text-2 mt-1">
              Nothing left to check on {ready.length === 1 ? "it" : "them"}. Until
              you post, none of it counts towards what anyone owes you.
            </p>
            <div className="mt-3 space-y-[6px]">
              {ready.slice(0, 6).map((k) => (
                <button key={k.import_id} onClick={() => navigate(`/khata/${k.import_id}`)}
                        className="w-full flex items-center gap-2 text-row text-left">
                  <span className={`w-2 h-2 rounded-full shrink-0 ${
                    k.balances ? "bg-green" : "bg-amber"}`} />
                  <span className="flex-1 truncate">
                    {k.party_name_raw ?? "Khata page"}
                  </span>
                  <span className="text-text-3 tnum">{k.rows} entries</span>
                </button>
              ))}
            </div>
            <div className="mt-4">
              <FatPill onClick={postAll} disabled={busy}>
                {busy ? "Posting…"
                  : `Post ${ready.length === 1 ? "this page" : `all ${ready.length} pages`} to the ledger`}
              </FatPill>
            </div>
          </Card>
        </div>
      )}

      {unsaved.length > 0 && (
        <div>
          <SectionLabel>Bills not yet saved to stock</SectionLabel>
          <GroupedList>
            {unsaved.map((p) => (
              <Row key={p.purchase_id} chevron
                   onClick={() => navigate(`/purchases/${p.purchase_id}`)}>
                <div className="flex items-center gap-2">
                  <span className="text-body font-semibold flex-1 truncate">
                    {p.supplier_name_raw ?? "Supplier bill"}
                  </span>
                  <span className="text-body font-semibold tnum">
                    {inr(p.totals?.total)}
                  </span>
                </div>
                <div className="text-meta text-text-2 mt-1">
                  {p.lines?.length ?? 0} lines · nothing added to stock yet
                </div>
              </Row>
            ))}
          </GroupedList>
        </div>
      )}

      {waiting.length > 0 && (
        <div>
          <SectionLabel>Pages with something to check</SectionLabel>
          <GroupedList>
            {waiting.map((k) => (
              <Row key={k.import_id} chevron
                   onClick={() => navigate(`/khata/${k.import_id}`)}>
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-amber shrink-0" />
                  <span className="text-body font-semibold flex-1 truncate">
                    {k.party_name_raw ?? "Khata page"}
                  </span>
                  <span className="text-body font-semibold tnum">{k.rows}</span>
                </div>
                <div className="text-meta text-text-2 mt-1 pl-4">
                  {k.blocked} {k.blocked === 1 ? "entry needs" : "entries need"} checking
                  before this page can be posted
                </div>
              </Row>
            ))}
          </GroupedList>
        </div>
      )}

      {!loading && orders.length === 0 && queue.length === 0
        && ready.length === 0 && waiting.length === 0 && unsaved.length === 0 && (
        <EmptyState
          icon="✓"
          title="Nothing waiting"
          titleTa="காத்திருப்பது எதுவும் இல்லை"
          body="Every order is decided and the confirm queue is clear."
        />
      )}

      {orders.length > 0 && (
        <div>
          <SectionLabel>Waiting on you</SectionLabel>
          <GroupedList>
            {orders.map((order) => (
              <Row key={order.order_id} chevron
                   onClick={() => navigate(`/orders/${order.order_id}`)}>
                <div className="flex items-center gap-2">
                  <VerdictDot decision={order.credit_verdict?.decision} />
                  <span className="text-body font-semibold flex-1 truncate">
                    {order.party_name}
                  </span>
                  <span className="text-body font-semibold tnum">{inr(order.total)}</span>
                </div>
                <div className="text-meta text-text-2 mt-1 line-clamp-1 pl-4">
                  {order.credit_verdict?.reason}
                </div>
              </Row>
            ))}
          </GroupedList>
        </div>
      )}

      {queue.length > 0 && (
        <div>
          <SectionLabel>Confirm queue</SectionLabel>
          <Card>
            <button onClick={() => navigate("/queue")}
                    className="w-full p-cardpad flex items-center gap-3">
              <div className="flex-1 text-left">
                <div className="text-tile font-bold tnum">{queue.length} to confirm</div>
                <div className="text-meta text-text-2 mt-1">
                  Values the agents were not sure enough about to book
                </div>
                <div className="mt-3 h-[6px] rounded-full bg-fill-3 overflow-hidden">
                  <div className="h-full bg-ink rounded-full transition-[width] duration-300"
                       style={{ width: "0%" }} />
                </div>
              </div>
              <Chevron />
            </button>
          </Card>
          <p className="text-micro text-text-3 mt-2 px-1">
            Oldest first · {ago(queue[0]?.created_at)}
          </p>
        </div>
      )}
    </div>
  );
}
