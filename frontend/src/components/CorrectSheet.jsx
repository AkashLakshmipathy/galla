import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api.js";
import { inr } from "../lib/format.js";
import { usePolling } from "../lib/hooks.js";
import { Card, FatPill, Sheet } from "./ui.jsx";

/* Correcting what the agent read.
 *
 * Flagging a line and then offering only "confirm as read" is not review — the
 * owner can see it is wrong and has no way to say so. An amount gets a keypad,
 * a name gets the list of accounts he already has plus somewhere to type a new
 * one. Picking off the list is the common case and the safest: it names the
 * exact record rather than making us parse a name back into one.
 */

function Keypad({ value, onChange }) {
  const press = (key) => {
    if (key === "⌫") return onChange(value.slice(0, -1));
    if (key === "." && value.includes(".")) return undefined;
    return onChange((value + key).slice(0, 10));
  };
  return (
    <div className="grid grid-cols-3 gap-2 mt-4">
      {["1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "⌫"].map((key) => (
        <button key={key} type="button" onClick={() => press(key)}
                className={`h-[58px] rounded-input text-[22px] font-semibold
                  active:opacity-70 ${key === "⌫" ? "bg-fill-2" : "bg-card"}`}>
          {key}
        </button>
      ))}
    </div>
  );
}

const FIELD_TITLE = {
  amount: "What does the page say?",
  qty: "What is the quantity?",
  rate: "What is the rate?",
  party_id: "Whose account is this?",
  sku_id: "Which item is this?",
};

export function CorrectSheet({ open, item, onClose, onResolved }) {
  const [typed, setTyped] = useState("");
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);

  const isRecord = item?.field === "party_id" || item?.field === "sku_id";
  // Which *record* this belongs to is worth changing whatever field the agent
  // happened to flag. It flagged an amount because it was unsure of the digits,
  // but it may equally have put the row on the wrong man's account — and
  // offering only a keypad leaves no way to say so.
  const kind = item?.source_type === "purchase" ? "sku" : "party";
  const wantsParties = open && kind === "party";
  const wantsCatalog = open && kind === "sku";

  const { data: parties } = usePolling(api.parties,
    { interval: 0, active: wantsParties, deps: [wantsParties] });
  const { data: catalog } = usePolling(api.inventory,
    { interval: 0, active: wantsCatalog, deps: [wantsCatalog] });

  useEffect(() => {
    if (open) {
      setTyped("");
      setSearch("");
    }
  }, [open, item?.item_id]);

  const options = useMemo(() => {
    const rows = kind === "party"
      ? (parties?.parties ?? []).map((p) => ({
          id: p.party_id, label: p.name,
          hint: p.credit?.outstanding ? `owes ${inr(p.credit.outstanding)}` : "" }))
      : (catalog?.items ?? []).map((i) => ({
          id: i.sku_id, label: i.name,
          hint: `${i.qty_on_hand} ${i.unit ?? ""} in stock` }));
    const needle = search.trim().toLowerCase();
    return needle
      ? rows.filter((r) => (r.label ?? "").toLowerCase().includes(needle))
      : rows;
  }, [parties, catalog, search, kind]);

  if (!item) return null;

  const send = async (body) => {
    setBusy(true);
    try {
      await api.resolveQueueItem(item.item_id, body);
      await onResolved?.();
      onClose();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet open={open} onClose={onClose} title="Fix what the agent read">
      <div className="px-gutter pb-8">
        <Card className="p-cardpad">
          <div className="text-meta text-text-2">The agent read</div>
          <div className="text-tile font-bold tnum mt-1">{item.extracted_value}</div>
          <div className="text-meta text-amber-deep font-semibold mt-1 tnum">
            {Math.round((item.confidence ?? 0) * 100)}% sure
          </div>
        </Card>

        <div className="text-meta font-semibold text-text-3 uppercase tracking-wide
                        px-1 mt-5 mb-2">
          {kind === "party" ? "Whose account is this?" : "Which item is this?"}
        </div>
        <>
          <>
            <input
              value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder={kind === "party"
                ? "Search your accounts" : "Search your items"}
              className="w-full bg-fill-3 rounded-full px-4 h-11 mt-3.5 text-body
                         outline-none placeholder:text-text-3"
            />
            <div className="bg-card rounded-card overflow-hidden mt-3 max-h-[280px]
                            overflow-y-auto no-scrollbar">
              {options.map((o) => (
                <button key={o.id} disabled={busy}
                        onClick={() => send(kind === "party"
                          ? { party_id: o.id } : { sku_id: o.id })}
                        className="w-full px-[18px] py-[13px] text-left border-b
                                   border-separator last:border-0 active:bg-separator">
                  <div className="text-body font-semibold">{o.label}</div>
                  {o.hint && <div className="text-meta text-text-3 tnum">{o.hint}</div>}
                </button>
              ))}
              {options.length === 0 && (
                <div className="px-[18px] py-4 text-row text-text-2">
                  {search.trim()
                    ? `Nothing matches "${search.trim()}".`
                    : "No accounts yet."}
                </div>
              )}
            </div>
          </>
        </>

        {!isRecord && (
          <>
            <div className="text-meta font-semibold text-text-3 uppercase
                            tracking-wide px-1 mt-5 mb-2">
              {FIELD_TITLE[item.field] ?? "The correct value"}
            </div>
            <Card className="p-cardpad">
              <div className="text-verdict font-bold tnum">
                {typed ? inr(typed) : "₹0"}
              </div>
            </Card>
            <Keypad value={typed} onChange={setTyped} />
          </>
        )}

        {isRecord && (
          <input
            value={typed} onChange={(e) => setTyped(e.target.value)}
            placeholder={kind === "party"
              ? "…or type a name to open a new account"
              : "…or type the correct item name"}
            className="w-full bg-card rounded-input px-4 h-12 mt-3 text-body
                       font-semibold outline-none placeholder:text-text-3
                       placeholder:font-normal"
          />
        )}

        {(item.alternatives ?? []).length > 1 && !isRecord && (
          <div className="bg-card rounded-card overflow-hidden mt-3.5">
            {item.alternatives.slice(1).map((alternative, i) => (
              <button key={i} disabled={busy}
                      onClick={() => send({ value: alternative })}
                      className="w-full px-[18px] py-[13px] text-left text-body
                                 font-semibold tnum border-b border-separator
                                 last:border-0 active:bg-separator">
                {alternative}
                <span className="text-meta text-text-3 font-normal ml-2">
                  also possible
                </span>
              </button>
            ))}
          </div>
        )}

        <div className="mt-5 space-y-1.5">
          <FatPill disabled={busy || !typed.trim()}
                   onClick={() => send({ value: typed.trim() })}>
            {busy ? "Saving…" : "Save this"}
          </FatPill>
          <FatPill variant="secondary" disabled={busy}
                   onClick={() => send({ accept_extracted: true })}>
            The agent was right
          </FatPill>
          <FatPill variant="tertiary" onClick={onClose}>Leave it for now</FatPill>
        </div>
      </div>
    </Sheet>
  );
}
