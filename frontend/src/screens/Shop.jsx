import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Gauge } from "../components/Gauge.jsx";
import { MergeSheet } from "../components/MergeSheet.jsx";
import { Card, Chevron, GroupedList, Row, SectionLabel } from "../components/ui.jsx";
import { api } from "../lib/api.js";
import { inr, monthName, timeOfDay } from "../lib/format.js";
import { usePolling } from "../lib/hooks.js";

/* S6 — the dashboard. The exposure gauge is the hero: it is the owner's
 * "is my money safe?" glance, so it gets the weight and the top of the screen. */

function StatRow({ label, value, delta, deltaTone }) {
  return (
    <div className="flex items-baseline justify-between py-[9px] border-b
                    border-separator last:border-0">
      <span className="text-row text-text-2">{label}</span>
      <span className="flex items-baseline gap-2">
        <span className="text-row font-semibold tnum">{value}</span>
        {delta && (
          <span className={`text-meta tnum ${deltaTone === "up" ? "text-red" : "text-green"}`}>
            {delta}
          </span>
        )}
      </span>
    </div>
  );
}

export function Shop({ onToast }) {
  const navigate = useNavigate();
  const owing = (exposure?.top ?? []).filter(
    (p) => (p.credit?.outstanding ?? 0) > 0).length;
  const nearLimit = (exposure?.top ?? []).filter(
    (p) => (p.exposure_pct ?? 0) > 75).length;
  const [pair, setPair] = useState(null);
  const { data } = usePolling(api.dashboard, { interval: 5000 });
  const { data: dupes, refresh: refreshDupes } = usePolling(api.duplicates,
    { interval: 15000 });
  const exposure = data?.exposure;
  const gst = data?.gst;

  const merge = async (sourceId, targetId) => {
    const result = await api.mergeParties(sourceId, targetId);
    onToast?.(`Merged · now owes ${inr(result.combined_outstanding)} on one profile`);
    await refreshDupes();
  };

  return (
    <div className="px-gutter pt-2 space-y-5">
      <h1 className="text-screen font-bold pt-1">Shop</h1>

      {exposure && exposure.limit === 0 && (
        <Card className="p-cardpad">
          <div className="text-supplier font-bold">No customers yet</div>
          <p className="text-row text-text-2 mt-2">
            Photograph a page of your khata and accounts open themselves, with
            their balances. Until then there is nothing to guard.
          </p>
        </Card>
      )}

      <Card className={`p-cardpad pt-6 ${exposure && exposure.limit === 0 ? "hidden" : ""}`}>
        <SectionLabel className="text-center">Credit exposure</SectionLabel>
        <Gauge outstanding={exposure?.outstanding ?? 0} limit={exposure?.limit ?? 1} />
        {/* This was the same ranked customer list the credit book already
            shows, truncated to five — and every row navigated to the counter
            rather than to the customer, so tapping a name with a lakh against
            it went home. Shop answers "how much is out there"; Credit answers
            "with whom". One line joins them. */}
        <button
          onClick={() => navigate("/credit")}
          className="w-full mt-5 pt-4 border-t border-separator flex items-center
                     gap-2 text-left"
        >
          <span className="flex-1 text-row text-text-2">
            {owing} {owing === 1 ? "customer owes" : "customers owe"} you
            {nearLimit > 0 && (
              <span className="text-amber-deep"> · {nearLimit} near the line</span>
            )}
          </span>
          <span className="text-row text-accent font-semibold">The book</span>
          <Chevron />
        </button>
      </Card>

      <Card className="p-cardpad">
        <div className="text-supplier font-bold">Today's close</div>
        <div className="text-meta text-text-3 mb-1.5">6:00 PM</div>
        <StatRow label="Orders" value={`${data?.today?.orders ?? 0}`} />
        <StatRow label="Revenue" value={inr(data?.today?.revenue)} />
        <StatRow label="On credit" value={inr(data?.today?.credit)} />
        <StatRow label="Pending approvals" value={`${data?.pending_approvals ?? 0}`} />
        <StatRow label="Confirm queue" value={`${data?.confirm_queue ?? 0}`} />
      </Card>

      {gst && (
        <div>
          <SectionLabel>GST</SectionLabel>
          <Card>
            <button onClick={() => navigate(`/gst/${gst.period}`)}
                    className="w-full p-cardpad text-left">
              <div className="flex items-baseline justify-between">
                <span className="text-supplier font-bold">{monthName(gst.period)}</span>
                <span className="text-meta text-text-3">CA-ready summary</span>
              </div>
              <div className="mt-3 space-y-1.5">
                <div className="flex items-center gap-2 text-row">
                  <span className="w-2 h-2 rounded-full bg-green" />
                  <span className="text-text-2 flex-1">
                    Compiled {timeOfDay(gst.generated_at)}
                  </span>
                </div>
                <div className="flex items-center gap-2 text-row">
                  <span className={`w-2 h-2 rounded-full ${
                    gst.sent_to_ca_at ? "bg-green" : "bg-chevron"}`} />
                  <span className="text-text-2 flex-1">
                    {gst.sent_to_ca_at ? "Sent to CA ✓" : "Not sent yet"}
                  </span>
                </div>
              </div>
              <div className="mt-3 pt-3 border-t border-separator flex justify-between">
                <span className="text-row text-text-2">Net tax payable (est.)</span>
                <span className="text-row font-semibold tnum">
                  {inr(gst.net_liability)}
                </span>
              </div>
            </button>
          </Card>
          <p className="text-micro text-text-3 mt-2 px-1">
            Compiled unattended by Cloud Scheduler on the 1st. Galla does not file
            your GST.
          </p>
        </div>
      )}

      {(dupes?.pairs ?? []).length > 0 && (
        <div>
          <SectionLabel>Possible duplicates</SectionLabel>
          <GroupedList>
            {dupes.pairs.map((p) => (
              <Row key={`${p.a.party_id}-${p.b.party_id}`} chevron
                   onClick={() => setPair(p)}>
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-amber shrink-0" />
                  <span className="text-body font-semibold flex-1 truncate">
                    {p.a.name} · {p.b.name}
                  </span>
                  <span className="text-body font-semibold tnum">
                    {inr(p.combined_outstanding)}
                  </span>
                </div>
                <div className="text-meta text-text-2 mt-1 pl-4">
                  Same trader? {p.reason} — together they owe{" "}
                  {inr(p.combined_outstanding)}, which neither profile shows.
                </div>
              </Row>
            ))}
          </GroupedList>
          <p className="text-micro text-text-3 mt-2 px-1">
            Two profiles for one contractor hide half his exposure from the Credit
            Guardian.
          </p>
        </div>
      )}

      {(data?.low_stock ?? []).length > 0 && (
        <div>
          <SectionLabel>Low stock</SectionLabel>
          <GroupedList>
            {data.low_stock.map((item) => (
              <Row key={item.sku_id}>
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-red shrink-0" />
                  <span className="text-body flex-1 truncate">{item.name}</span>
                  <span className="text-body font-semibold tnum">
                    {item.qty_on_hand} {item.unit}
                  </span>
                </div>
              </Row>
            ))}
          </GroupedList>
        </div>
      )}

      <MergeSheet open={Boolean(pair)} pair={pair} onClose={() => setPair(null)}
                  onMerge={merge} />
    </div>
  );
}
