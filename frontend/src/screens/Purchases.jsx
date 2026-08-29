import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { BookChart, PeriodTabs, TotalsRow } from "../components/BookChart.jsx";
import { Card, Chevron, EmptyState, GroupedList, Row, SectionLabel } from "../components/ui.jsx";
import { api } from "../lib/api.js";
import { ddmmyyyy, inr } from "../lib/format.js";
import { usePolling } from "../lib/hooks.js";

/* What the shop bought, from whom, and what it still owes.
 *
 * The mirror of Credit, and deliberately built from the same pieces: balances
 * from the append-only ledger, and what was actually bought from the bills
 * themselves — so "what have I bought from Annai this year, at what rate" is
 * answered off the shop's own paperwork rather than anybody's recollection. */

export function Purchases() {
  const navigate = useNavigate();
  const [period, setPeriod] = useState("month");
  const [tab, setTab] = useState("suppliers");
  const { data, loading } = usePolling(() => api.purchasesBook(period),
    { interval: 8000, deps: [period] });

  const totals = data?.totals;

  return (
    <div className="px-gutter pt-2 space-y-5">
      <h1 className="text-screen font-bold pt-1">Purchases</h1>

      {!loading && (totals?.suppliers ?? 0) === 0 && (
        <EmptyState
          icon="⌾"
          title="No bills yet"
          titleTa="இன்னும் பில் இல்லை"
          body="Photograph a supplier bill. The products, the quantities and what you owe all enter themselves."
        />
      )}

      {(totals?.suppliers ?? 0) > 0 && (
        <>
          <Card className="p-cardpad">
            <div className="text-meta text-text-2">Owed to suppliers</div>
            <div className="text-verdict font-bold tnum mt-1">
              {inr(totals.payable)}
            </div>
            <div className="text-row text-text-2 mt-1">
              to {totals.owed_to} of {totals.suppliers}{" "}
              {totals.suppliers === 1 ? "supplier" : "suppliers"}
            </div>
            <div className="mt-4 pt-3 border-t border-separator">
              <TotalsRow items={[
                { label: "Bought, all time", value: totals.bought_all_time },
                { label: "Paid, all time", value: totals.paid_all_time,
                  tone: "text-green" },
                { label: "Bills photographed", value: String(totals.bills) },
                { label: "Suppliers", value: String(totals.suppliers) },
              ]} />
            </div>
          </Card>

          <div>
            <div className="flex items-center justify-between mb-2">
              <SectionLabel className="mb-0">How the book moved</SectionLabel>
              <PeriodTabs value={period} onChange={setPeriod} />
            </div>
            <Card className="p-cardpad">
              {(data.periods ?? []).length > 0 ? (
                <BookChart periods={data.periods} granularity={period}
                           outKey="bought" backKey="paid"
                           outLabel="bought" backLabel="paid" />
              ) : (
                <p className="text-row text-text-2 text-center py-4">
                  Nothing recorded yet.
                </p>
              )}
            </Card>
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <SectionLabel className="mb-0">
                {tab === "suppliers" ? "Who you buy from" : "What you buy"}
              </SectionLabel>
              <div className="flex gap-1">
                {[["suppliers", "Suppliers"], ["items", "Items"]].map(([k, l]) => (
                  <button key={k} onClick={() => setTab(k)}
                          className={`px-2.5 py-1 rounded-full text-micro font-semibold
                            ${tab === k ? "bg-ink text-white" : "bg-fill-2 text-text-2"}`}>
                    {l}
                  </button>
                ))}
              </div>
            </div>

            {tab === "suppliers" ? (
              <GroupedList>
                {data.suppliers.map((s) => (
                  <Row key={s.party_id} chevron
                       onClick={() => navigate(`/purchases-book/${s.party_id}`)}>
                    <div className="flex items-center gap-2">
                      <span className={`w-2 h-2 rounded-full shrink-0 ${
                        s.payable > 0 ? "bg-amber" : "bg-green"}`} />
                      <span className="text-body font-semibold flex-1 truncate">
                        {s.name}
                      </span>
                      <span className="text-body font-semibold tnum">
                        {inr(s.payable)}
                      </span>
                    </div>
                    <div className="text-meta text-text-2 mt-1 pl-4 tnum">
                      {s.bills} {s.bills === 1 ? "bill" : "bills"} ·{" "}
                      {inr(s.bill_value)} bought
                      {s.last_bill ? ` · last ${ddmmyyyy(s.last_bill)}` : ""}
                    </div>
                    {s.top_items?.length > 0 && (
                      <div className="text-micro text-text-3 mt-1 pl-4 truncate">
                        mostly {s.top_items.map((i) => i.name).join(", ")}
                      </div>
                    )}
                  </Row>
                ))}
              </GroupedList>
            ) : (
              <GroupedList>
                {data.items.map((i) => (
                  <Row key={i.sku_id}>
                    <div className="flex items-center gap-2">
                      <span className="text-body font-semibold flex-1 truncate">
                        {i.name}
                      </span>
                      <span className="text-body font-semibold tnum">
                        {inr(i.value)}
                      </span>
                    </div>
                    <div className="text-meta text-text-2 mt-1 tnum">
                      {i.qty} {i.unit || "units"} across {i.bills}{" "}
                      {i.bills === 1 ? "bill" : "bills"} · last at {inr(i.last_rate)}
                      {i.suppliers > 1 ? ` · ${i.suppliers} suppliers` : ""}
                    </div>
                  </Row>
                ))}
                {data.items.length === 0 && (
                  <Row>
                    <div className="text-row text-text-2">
                      Nothing saved to stock yet — bills waiting in review do not
                      count as bought.
                    </div>
                  </Row>
                )}
              </GroupedList>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export function SupplierLedger() {
  const navigate = useNavigate();
  const { partyId } = useParams();
  const { data } = usePolling(() => api.ledger(partyId),
    { interval: 0, deps: [partyId] });
  const { data: book } = usePolling(() => api.purchasesBook("all"),
    { interval: 0 });

  if (!data) return <div className="px-gutter pt-6 text-body text-text-2">Loading…</div>;
  const party = data.party ?? {};
  const mine = (book?.suppliers ?? []).find((s) => s.party_id === partyId);

  return (
    <div className="px-gutter pt-2 pb-10">
      <button onClick={() => navigate(-1)}
              className="text-accent text-action font-semibold -ml-1 mb-3 min-h-[44px]
                         flex items-center gap-1">
        <span className="text-[18px] leading-none">‹</span> Purchases
      </button>

      <Card className="p-cardpad">
        <div className="text-supplier font-bold">{party.name}</div>
        {party.gstin && (
          <div className="text-micro text-text-3 tnum mt-0.5">GSTIN {party.gstin}</div>
        )}
        <div className="text-verdict font-bold tnum mt-3">
          {inr(party.credit?.outstanding)}
        </div>
        <div className="text-row text-text-2 mt-1">still to pay</div>
        <div className="mt-4 pt-3 border-t border-separator">
          <TotalsRow items={[
            { label: "Bought, all time", value: mine?.bill_value ?? 0 },
            { label: "Paid, all time", value: data.received ?? 0, tone: "text-green" },
            { label: "Bills", value: String(mine?.bills ?? 0) },
            { label: "Last bill", value: ddmmyyyy(mine?.last_bill) || "—" },
          ]} />
        </div>
      </Card>

      {mine?.top_items?.length > 0 && (
        <>
          <SectionLabel className="mt-5">What you buy from them</SectionLabel>
          <GroupedList>
            {mine.top_items.map((i) => (
              <Row key={i.sku_id}>
                <div className="flex items-center gap-2">
                  <span className="text-body flex-1 truncate">{i.name}</span>
                  <span className="text-body font-semibold tnum">{inr(i.value)}</span>
                </div>
                <div className="text-meta text-text-3 mt-0.5 tnum">{i.qty} bought</div>
              </Row>
            ))}
          </GroupedList>
        </>
      )}

      <SectionLabel className="mt-5">Every entry</SectionLabel>
      <GroupedList>
        {(data.entries ?? []).map((e) => {
          const paid = e.direction === "debit";
          return (
            <Row key={e.entry_id}>
              <div className="flex items-center gap-2">
                <span className="text-body flex-1">
                  {paid ? "Paid them" : "Bill entered"}
                </span>
                <span className={`text-body font-semibold tnum ${
                  paid ? "text-green" : ""}`}>
                  {paid ? "−" : "+"}{inr(e.amount)}
                </span>
              </div>
              <div className="text-meta text-text-3 mt-0.5 tnum">
                {ddmmyyyy(e.date)}
                {e.ref?.type === "purchase" ? ` · bill ${e.ref.id}` : ""}
              </div>
            </Row>
          );
        })}
      </GroupedList>
      {(data.entries ?? []).length === 0 && (
        <Card className="p-cardpad text-center text-row text-text-2">
          No entries yet.
        </Card>
      )}
    </div>
  );
}
