import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Card, EmptyState, FatPill, GroupedList, Row, SectionLabel, Sheet } from "../components/ui.jsx";
import { api } from "../lib/api.js";
import { BookChart, PeriodTabs, TotalsRow } from "../components/BookChart.jsx";
import { ddmmyyyy, inr } from "../lib/format.js";
import { usePolling } from "../lib/hooks.js";

/* The khata, digitised — the screen the owner opens most after the counter.
 *
 * Everything on it is derived from the ledger rather than from a running total,
 * so the list and the history can never disagree. The ageing buckets are the
 * part a shopkeeper actually reasons with: not "how much is owed" but "how long
 * has it been owed", which is the number that predicts whether it arrives. */

const BUCKETS = [
  { key: "current", label: "Within 30 days", tone: "bg-green" },
  { key: "30", label: "30 – 60 days", tone: "bg-amber" },
  { key: "60", label: "60 – 90 days", tone: "bg-amber" },
  { key: "90+", label: "Over 90 days", tone: "bg-red" },
];

export function Credit() {
  const navigate = useNavigate();
  const [filter, setFilter] = useState("all");
  const [period, setPeriod] = useState("month");
  const { data, loading } = usePolling(() => api.credit(period),
    { interval: 8000, deps: [period] });

  const totals = data?.totals;
  const parties = (data?.parties ?? []).filter((p) =>
    filter === "all" ? true : filter === "owing" ? p.outstanding > 0 : p.bucket !== "current");

  return (
    <div className="px-gutter pt-2 space-y-5">
      <h1 className="text-screen font-bold pt-1">Credit</h1>

      {!loading && (totals?.customers ?? 0) === 0 && (
        <EmptyState
          icon="₹"
          title="No credit given yet"
          titleTa="இன்னும் கடன் இல்லை"
          body="Photograph a page of your khata. The accounts open themselves, with their balances, and everything below fills in."
        />
      )}

      {(totals?.customers ?? 0) > 0 && (
        <>
          <Card className="p-cardpad">
            <div className="text-meta text-text-2">Out on credit right now</div>
            <div className="text-verdict font-bold tnum mt-1">
              {inr(totals.outstanding)}
            </div>
            <div className="text-row text-text-2 mt-1">
              across {totals.in_debt} of {totals.customers} customers
              {totals.over_limit > 0 && (
                <span className="text-red font-semibold">
                  {" · "}{totals.over_limit} over limit
                </span>
              )}
            </div>

            <div className="flex h-[8px] rounded-full overflow-hidden mt-4 bg-separator">
              {BUCKETS.map((b) => {
                const value = data.ageing?.[b.key] ?? 0;
                const pct = totals.outstanding
                  ? (value / totals.outstanding) * 100 : 0;
                return pct > 0
                  ? <div key={b.key} className={b.tone} style={{ width: `${pct}%` }} />
                  : null;
              })}
            </div>
            <div className="mt-3">
              {BUCKETS.map((b) => {
                const value = data.ageing?.[b.key] ?? 0;
                if (!value) return null;
                return (
                  <div key={b.key}
                       className="flex items-center gap-2 py-[5px] text-row">
                    <span className={`w-2 h-2 rounded-full ${b.tone}`} />
                    <span className="text-text-2 flex-1">{b.label}</span>
                    <span className="font-semibold tnum">{inr(value)}</span>
                  </div>
                );
              })}
            </div>
          </Card>

          <Card className="p-cardpad">
            <TotalsRow items={[
              { label: "Given, all time", value: totals.given_all_time },
              { label: "Received, all time", value: totals.received_all_time,
                tone: "text-green" },
              { label: "Customers on the book", value: String(totals.customers) },
              { label: "Credit limits total", value: totals.limit },
            ]} />
          </Card>

          <div>
            <div className="flex items-center justify-between mb-2">
              <SectionLabel className="mb-0">How the book moved</SectionLabel>
              <PeriodTabs value={period} onChange={setPeriod} />
            </div>
            <Card className="p-cardpad">
              {(data.periods ?? []).length > 0 ? (
                <BookChart periods={data.periods} granularity={period}
                           outKey="given" backKey="received"
                           outLabel="given" backLabel="received" />
              ) : (
                <p className="text-row text-text-2 text-center py-4">
                  Nothing recorded yet.
                </p>
              )}
            </Card>
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <SectionLabel className="mb-0">Who owes you</SectionLabel>
              <div className="flex gap-1">
                {[["all", "All"], ["owing", "Owing"], ["late", "Late"]].map(([k, l]) => (
                  <button key={k} onClick={() => setFilter(k)}
                          className={`px-2.5 py-1 rounded-full text-micro font-semibold
                            ${filter === k ? "bg-ink text-white" : "bg-fill-2 text-text-2"}`}>
                    {l}
                  </button>
                ))}
              </div>
            </div>
            <GroupedList>
              {parties.map((p) => (
                <Row key={p.party_id} chevron
                     onClick={() => navigate(`/credit/${p.party_id}`)}>
                  <div className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full shrink-0 ${
                      p.bucket === "current" ? "bg-green"
                        : p.bucket === "90+" ? "bg-red" : "bg-amber"}`} />
                    <span className="text-body font-semibold flex-1 truncate">
                      {p.name}
                    </span>
                    <span className="text-body font-semibold tnum">
                      {inr(p.outstanding)}
                    </span>
                  </div>
                  <div className="text-meta text-text-2 mt-1 pl-4 tnum">
                    {p.days_since_payment >= 900
                      ? "never paid"
                      : `paid ${p.days_since_payment} days ago`}
                    {p.limit ? ` · ${p.exposure_pct}% of limit` : ""}
                    {p.provisional ? " · from a scan" : ""}
                  </div>
                </Row>
              ))}
            </GroupedList>
            {parties.length === 0 && (
              <Card className="p-cardpad text-center text-row text-text-2">
                Nobody in this list.
              </Card>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export function PartyLedger() {
  const navigate = useNavigate();
  const { partyId } = useParams();
  const [renaming, setRenaming] = useState(false);
  const { data, refresh } = usePolling(() => api.ledger(partyId),
    { interval: 0, deps: [partyId] });
  if (!data) return <div className="px-gutter pt-6 text-body text-text-2">Loading…</div>;

  const party = data.party ?? {};
  const credit = party.credit ?? {};

  return (
    <div className="px-gutter pt-2 pb-10">
      <button onClick={() => navigate(-1)}
              className="text-accent text-action font-semibold -ml-1 mb-3 min-h-[44px]
                         flex items-center gap-1">
        <span className="text-[18px] leading-none">‹</span> Credit
      </button>

      <Card className="p-cardpad">
        <div className="flex items-start gap-3">
          <div className="flex-1 min-w-0">
            <div className="text-supplier font-bold">{party.name}</div>
            {party.name_ta && party.name_ta !== party.name && (
              <div className="text-meta text-text-3">{party.name_ta}</div>
            )}
          </div>
          <button onClick={() => setRenaming(true)}
                  className="text-meta font-semibold text-accent shrink-0">
            Rename
          </button>
        </div>
        {party.provisional && (
          <div className="text-micro text-amber-deep mt-1">
            Name read from your handwriting — check it
          </div>
        )}
        <div className="text-verdict font-bold tnum mt-3">
          {inr(credit.outstanding)}
        </div>
        <div className="text-row text-text-2 mt-1 tnum">
          of {inr(credit.limit)} limit · {party.exposure_pct}%
        </div>
        {party.merged_from?.length > 0 && (
          <p className="text-micro text-text-3 mt-3 pt-3 border-t border-separator">
            Also known as {party.merged_from.map((m) => m.name).join(", ")} —
            merged into this account.
          </p>
        )}
      </Card>

      <Card className="p-cardpad mt-3.5">
        <TotalsRow items={[
          { label: "Given, all time", value: data.given ?? 0 },
          { label: "Received, all time", value: data.received ?? 0,
            tone: "text-green" },
          { label: "Entries", value: String((data.entries ?? []).length) },
          { label: "Trading since", value: ddmmyyyy(data.since) || "—" },
        ]} />
      </Card>

      <SectionLabel className="mt-5">Every entry</SectionLabel>
      <GroupedList>
        {(data.entries ?? []).map((e) => {
          const received = e.direction === "credit";
          return (
            <Row key={e.entry_id}>
              <div className="flex items-center gap-2">
                <span className="text-body flex-1">
                  {received ? "Paid" : "Goods on credit"}
                  {e.recorded_under && (
                    <span className="text-meta text-text-3">
                      {" "}· as {e.recorded_under}
                    </span>
                  )}
                </span>
                <span className={`text-body font-semibold tnum ${
                  received ? "text-green" : ""}`}>
                  {received ? "−" : "+"}{inr(e.amount)}
                </span>
              </div>
              <div className="text-meta text-text-3 mt-0.5 tnum">
                {ddmmyyyy(e.date)} · balance {inr(e.balance_after)}
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

      <RenameSheet open={renaming} party={party} onClose={() => setRenaming(false)}
                   onSaved={refresh} />
    </div>
  );
}

/* Correcting a name the handwriting got wrong. The old spelling is kept, not
 * replaced — it is how this customer appears on every page already scanned. */
function RenameSheet({ open, party, onClose, onSaved }) {
  const [name, setName] = useState("");
  const [nameTa, setNameTa] = useState("");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setName(party?.name ?? "");
      setNameTa(party?.name_ta ?? "");
      setPhone(party?.phone ?? "");
    }
  }, [open, party]);

  const save = async () => {
    setBusy(true);
    try {
      await api.renameParty(party.party_id, { name, name_ta: nameTa, phone });
      await onSaved?.();
      onClose();
    } finally {
      setBusy(false);
    }
  };

  const field = "w-full bg-transparent text-body font-semibold outline-none mt-1";
  return (
    <Sheet open={open} onClose={onClose} title="Correct the name">
      <div className="px-gutter pb-8">
        <Card className="overflow-hidden">
          <label className="block px-[18px] py-[13px] border-b border-separator">
            <span className="text-meta text-text-2">Name</span>
            <input className={field} value={name} autoFocus
                   onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="block px-[18px] py-[13px] border-b border-separator">
            <span className="text-meta text-text-2">In your language</span>
            <input className={field} value={nameTa} placeholder="optional"
                   onChange={(e) => setNameTa(e.target.value)} />
          </label>
          <label className="block px-[18px] py-[13px]">
            <span className="text-meta text-text-2">Phone</span>
            <input className={field} value={phone} inputMode="tel" placeholder="optional"
                   onChange={(e) => setPhone(e.target.value)} />
          </label>
        </Card>
        <p className="text-micro text-text-3 mt-3 leading-relaxed">
          {party?.name
            ? `"${party.name}" is kept as an old spelling, so pages already scanned — and the same handwriting next time — still land here.`
            : ""}
        </p>
        <div className="mt-4 space-y-1.5">
          <FatPill onClick={save} disabled={busy || !name.trim()}>
            {busy ? "Saving…" : "Save"}
          </FatPill>
          <FatPill variant="tertiary" onClick={onClose}>Cancel</FatPill>
        </div>
      </div>
    </Sheet>
  );
}
