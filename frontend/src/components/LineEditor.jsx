import { useEffect, useState } from "react";
import { FatPill, Sheet } from "./ui.jsx";
import { inr } from "../lib/format.js";

/* Line editor sheet — stepper for quantity, keypad for rate, remove for a line
 * the customer did not actually ask for. Edits rewrite the order's items and
 * GST; the running total updates as you go so the owner never saves blind. */

function Keypad({ label, value, onChange, onDone }) {
  const press = (key) => {
    if (key === "⌫") return onChange(value.slice(0, -1));
    if (key === "✓") return onDone();
    if (value.length >= 6) return undefined;
    return onChange(value + key);
  };
  return (
    <div className="bg-card rounded-card p-cardpad mt-3.5">
      <div className="text-meta text-text-2">{label}</div>
      <div className="text-gauge font-bold tnum mt-1">₹{value || "0"}</div>
      <div className="grid grid-cols-3 gap-2 mt-4">
        {["1", "2", "3", "4", "5", "6", "7", "8", "9", "⌫", "0", "✓"].map((key) => (
          <button
            key={key}
            onClick={() => press(key)}
            className={`h-12 rounded-panel text-action font-semibold
              ${key === "✓" ? "bg-ink text-white"
                : key === "⌫" ? "bg-fill-2 text-ink" : "bg-bg text-ink"}`}
          >
            {key}
          </button>
        ))}
      </div>
    </div>
  );
}

export function LineEditor({ open, onClose, lines = [], onSave, allowRemove = true }) {
  const [draft, setDraft] = useState(lines);
  const [keypad, setKeypad] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) setDraft(lines.map((line) => ({ ...line })));
  }, [open, lines]);

  const total = draft.reduce(
    (sum, line) => sum + Math.round((Number(line.qty) || 0) * (Number(line.rate) || 0)), 0);

  const setQty = (index, delta) =>
    setDraft((rows) => rows.map((row, i) =>
      i === index ? { ...row, qty: Math.max(1, (Number(row.qty) || 0) + delta) } : row));

  const remove = (index) =>
    setDraft((rows) => (rows.length > 1 ? rows.filter((_, i) => i !== index) : rows));

  const save = async () => {
    setSaving(true);
    try {
      const edits = [];
      lines.forEach((original, index) => {
        const kept = draft.find((row) => row._key === original._key
          || row.name_raw === original.name_raw);
        if (!kept) return edits.push({ index, remove: true });
        if (Number(kept.qty) !== Number(original.qty) || Number(kept.rate) !== Number(original.rate)) {
          edits.push({ index, qty: Number(kept.qty), rate: Number(kept.rate) });
        }
        return undefined;
      });
      await onSave(edits);
      onClose();
    } finally {
      setSaving(false);
    }
  };

  return (
    <Sheet open={open} onClose={onClose} title="Line editor">
      <div className="px-gutter pb-6">
        <div className="bg-card rounded-card overflow-hidden">
          {draft.map((line, index) => (
            <div key={line._key ?? index}
                 className="px-[18px] py-[14px] border-b border-separator last:border-0">
              <div className="flex items-start gap-2">
                <div className="flex-1 text-body font-semibold">{line.name}</div>
                {allowRemove && draft.length > 1 && (
                  <button onClick={() => remove(index)} aria-label="Remove line"
                          className="w-[30px] h-[30px] rounded-full bg-fill-2 text-text-2
                                     flex items-center justify-center shrink-0">
                    ✕
                  </button>
                )}
              </div>
              <div className="flex items-center justify-between mt-3">
                <div className="flex items-center bg-bg rounded-full">
                  <button onClick={() => setQty(index, -1)} aria-label="Decrease"
                          className="w-10 h-10 text-[18px] text-ink">−</button>
                  <span className="w-10 text-center text-body font-semibold tnum">
                    {Number(line.qty) || 0}
                  </span>
                  <button onClick={() => setQty(index, +1)} aria-label="Increase"
                          className="w-10 h-10 text-[18px] text-ink">＋</button>
                </div>
                <button onClick={() => setKeypad({ index, value: String(line.rate ?? "") })}
                        className="text-body font-semibold text-accent tnum px-2">
                  @ {inr(line.rate)}
                </button>
                <div className="text-body font-semibold tnum w-[86px] text-right">
                  {inr((Number(line.qty) || 0) * (Number(line.rate) || 0))}
                </div>
              </div>
            </div>
          ))}
        </div>

        {keypad && (
          <Keypad
            label="New rate per unit"
            value={keypad.value}
            onChange={(value) => setKeypad((k) => ({ ...k, value }))}
            onDone={() => {
              setDraft((rows) => rows.map((row, i) =>
                i === keypad.index ? { ...row, rate: Number(keypad.value) || 0 } : row));
              setKeypad(null);
            }}
          />
        )}

        <div className="flex items-center justify-between mt-5">
          <span className="text-action font-bold tnum">{inr(total)}</span>
          <div className="w-[140px]">
            <FatPill onClick={save} disabled={saving}>
              {saving ? "Saving…" : "Done"}
            </FatPill>
          </div>
        </div>
        <p className="text-micro text-text-3 text-center mt-3">
          Changes update the quotation.
        </p>
      </div>
    </Sheet>
  );
}
