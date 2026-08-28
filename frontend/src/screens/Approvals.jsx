import { useNavigate } from "react-router-dom";
import { VerdictDot } from "../components/Verdict.jsx";
import { Card, Chevron, EmptyState, GroupedList, Row, SectionLabel } from "../components/ui.jsx";
import { api } from "../lib/api.js";
import { ago, inr } from "../lib/format.js";
import { usePolling } from "../lib/hooks.js";

/* Approvals — the badge-counted stack. Orders waiting on a decision, then the
 * confirm queue of things the agents were not sure enough about to book. */

export function Approvals() {
  const navigate = useNavigate();
  const { data, loading } = usePolling(api.approvals, { interval: 2500 });
  const orders = data?.orders ?? [];
  const queue = data?.confirm_queue ?? [];

  return (
    <div className="px-gutter pt-2 space-y-5">
      <h1 className="text-screen font-bold pt-1">Approvals</h1>

      {!loading && orders.length === 0 && queue.length === 0 && (
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
