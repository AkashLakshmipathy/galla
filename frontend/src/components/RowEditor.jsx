import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api.js";
import { inr } from "../lib/format.js";
import { usePolling } from "../lib/hooks.js";
import { Card, FatPill, Sheet } from "./ui.jsx";

/* Editing one entry the agent read off a khata page.
 *
 * Everything on the row is editable — the amount, the date, whose account it is,
 * and whether it was goods taken or money paid. The agent's reading is a
 * starting point, not a verdict, and the owner is the one who was there.
 */

export function RowEditor({ open, row, importId, onClose, onSaved }) {
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState("");
  const [partyId, setPartyId] = useState("");
  const [kind, setKind] = useState("sale_credit");
  const [busy, setBusy] = useState(false);
  const { data: parties } = usePolling(api.parties, { interval: 0, active: open });

  useEffect(() => {
    if (open && row) {
      setAmount(String(Math.round(row.amount ?? 0)));
      setDate(String(row.date ?? "").slice(0, 10));
      setPartyId(row.party_id ?? "");
      setKind(row.entry_type ?? "sale_credit");
    }
  }, [open, row]);

  const accounts = useMemo(() => parties?.parties ?? [], [parties]);
  if (!row) return null;

  const save = async () => {
    setBusy(true);
    try {
      await api.editKhataRows(importId, [{
        row_id: row.row_id, amount: Number(amount) || 0,
        party_id: partyId || null, date: date || null,
        entry_type: kind, confirm: true,
      }]);
      await onSaved?.();
      onClose();
    } finally {
      setBusy(false);
    }
  };

  const field = "w-full bg-transparent text-body font-semibold outline-none mt-1";
  return (
    <Sheet open={open} onClose={onClose} title="Edit this entry">
      <div className="px-gutter pb-8">
        {row.description_raw && (
          <p className="text-meta text-text-2 text-center -mt-1 mb-3">
            {row.description_raw}
          </p>
        )}

        <Card className="overflow-hidden">
          <label className="block px-[18px] py-[13px] border-b border-separator">
            <span className="text-meta text-text-2">Amount</span>
            <input className={`${field} tnum`} value={amount} inputMode="decimal"
                   onChange={(e) => setAmount(e.target.value.replace(/[^0-9.]/g, ""))} />
            <span className="block text-micro text-text-3 mt-1">{inr(amount)}</span>
          </label>
          <label className="block px-[18px] py-[13px] border-b border-separator">
            <span className="text-meta text-text-2">Date</span>
            <input className={field} type="date" value={date}
                   onChange={(e) => setDate(e.target.value)} />
          </label>
          <label className="block px-[18px] py-[13px]">
            <span className="text-meta text-text-2">Account</span>
            <select className={`${field} appearance-none`} value={partyId}
                    onChange={(e) => setPartyId(e.target.value)}>
              <option value="">
                {row.party_name_raw ? `${row.party_name_raw} — new account` : "Choose"}
              </option>
              {accounts.map((p) => (
                <option key={p.party_id} value={p.party_id}>{p.name}</option>
              ))}
            </select>
          </label>
        </Card>

        <div className="flex gap-2 mt-3.5">
          {[["sale_credit", "Goods on credit"], ["payment_received", "Money paid"]]
            .map(([key, label]) => (
              <button key={key} onClick={() => setKind(key)}
                      className={`flex-1 h-11 rounded-full text-action font-semibold
                        ${kind === key ? "bg-ink text-white" : "bg-fill-2 text-text-2"}`}>
                {label}
              </button>
            ))}
        </div>

        <div className="mt-5 space-y-1.5">
          <FatPill onClick={save} disabled={busy}>
            {busy ? "Saving…" : "Save"}
          </FatPill>
          <FatPill variant="tertiary" onClick={onClose}>Cancel</FatPill>
        </div>
      </div>
    </Sheet>
  );
}
