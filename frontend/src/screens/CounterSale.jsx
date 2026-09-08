import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BackBar } from "../components/BackBar.jsx";
import { Card, EmptyState, FatPill, GroupedList } from "../components/ui.jsx";
import { api } from "../lib/api.js";
import { inr, inrPaise } from "../lib/format.js";
import { shareDocument } from "../lib/share.js";

/* S9 — the counter sale. A walk-in buys three bags of cement and leaves with a
 * bill on his phone.
 *
 * The one idea this screen is built around: the owner types the price he says
 * out loud. "Bag 445, with tax" is 445 in the box with the toggle on Incl.,
 * not 415 and a mental note. Every other billing package makes him do the
 * arithmetic its way; this one works backwards from his.
 *
 * There is no barcode scanner and that is deliberate — cement, pipe and loose
 * hardware carry no barcodes, so the catalogue's alias list is the input
 * method. Typing "ramco" finds the SKU.
 *
 * No tax arithmetic happens in this file. The running total comes from the
 * preview endpoint, which runs the same `core.tax` the invoice does, because a
 * second implementation in JavaScript is the one nobody unit-tests. */

const DEBOUNCE_MS = 180;

function useDebounced(value, delay = DEBOUNCE_MS) {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return settled;
}

function SearchResults({ results, onPick }) {
  if (!results.length) return null;
  return (
    <GroupedList className="mt-2">
      {results.map((sku) => (
        <button
          key={sku.sku_id}
          onClick={() => onPick(sku)}
          className="w-full flex items-center gap-3 px-[18px] py-[13px] min-h-[52px]
                     text-left border-b border-separator last:border-0
                     active:bg-separator"
        >
          <div className="flex-1 min-w-0">
            <div className="text-body font-semibold truncate">{sku.name}</div>
            {sku.name_ta && (
              <div className="text-meta text-text-3 truncate">{sku.name_ta}</div>
            )}
          </div>
          <div className="text-body font-semibold tnum shrink-0">
            {inr(sku.price_tiers?.retail ?? 0)}
          </div>
        </button>
      ))}
    </GroupedList>
  );
}

function LineRow({ line, onChange, onRemove }) {
  const step = (delta) => onChange({ ...line, qty: Math.max(0.5, line.qty + delta) });
  return (
    <div className="px-[18px] py-[13px] border-b border-separator last:border-0">
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="text-body font-semibold truncate">{line.name}</div>
          <div className="text-meta text-text-3">{line.unit} · {line.gst_rate}% GST</div>
        </div>
        <button onClick={onRemove}
                className="text-meta text-text-3 shrink-0 px-1 active:opacity-60"
                aria-label={`Remove ${line.name}`}>
          Remove
        </button>
      </div>

      <div className="flex items-center gap-2 mt-2.5">
        <div className="flex items-center rounded-input bg-fill-2 overflow-hidden">
          <button onClick={() => step(-1)}
                  className="w-[38px] h-[38px] text-action font-semibold active:bg-fill-3"
                  aria-label="One less">−</button>
          <span className="min-w-[42px] text-center text-body font-semibold tnum">
            {line.qty}
          </span>
          <button onClick={() => step(1)}
                  className="w-[38px] h-[38px] text-action font-semibold active:bg-fill-3"
                  aria-label="One more">+</button>
        </div>

        <label className="flex-1 flex items-center rounded-input bg-fill-2 h-[38px] px-3">
          <span className="text-meta text-text-3 mr-1">₹</span>
          <input
            type="number" inputMode="decimal" min="0" step="0.01"
            value={line.unit_price}
            onChange={(e) => onChange({ ...line, unit_price: e.target.value })}
            className="w-full bg-transparent text-body font-semibold tnum
                       outline-none"
            aria-label={`Price for ${line.name}`}
          />
        </label>
      </div>
    </div>
  );
}

function TotalsPanel({ invoice, taxIncluded }) {
  if (!invoice) return null;
  const rows = [
    ["Taxable value", inrPaise(invoice.subtotal_taxable)],
    ...(invoice.total_discount
      ? [["Discount", `- ${inrPaise(invoice.total_discount)}`]] : []),
    ...(invoice.intra_state
      ? [["CGST", inrPaise(invoice.cgst)], ["SGST", inrPaise(invoice.sgst)]]
      : [["IGST", inrPaise(invoice.igst)]]),
    ...(invoice.round_off ? [["Round off", inrPaise(invoice.round_off)]] : []),
  ];
  return (
    <Card className="p-cardpad">
      {rows.map(([label, value]) => (
        <div key={label} className="flex items-center justify-between py-[3px]">
          <span className="text-body text-text-2">{label}</span>
          <span className="text-body tnum">{value}</span>
        </div>
      ))}
      <div className="flex items-end justify-between pt-3 mt-2 border-t border-separator">
        <div>
          <div className="text-meta text-text-3">Payable</div>
          <div className="text-micro text-text-3">
            {taxIncluded ? "tax included in the prices above"
                         : "tax added on top"}
          </div>
        </div>
        <span className="text-count font-bold tnum">{inr(invoice.payable)}</span>
      </div>
    </Card>
  );
}

function BilledPanel({ result, onShare, onNewSale }) {
  return (
    <div className="space-y-3.5">
      <Card className="p-cardpad text-center">
        <div className="text-meta text-text-3">Tax invoice</div>
        <div className="text-tile font-bold tnum mt-1">{result.invoice_no}</div>
        <div className="text-verdict font-bold tnum mt-3">
          {inr(result.order?.total)}
        </div>
        <div className="text-meta text-text-3 mt-1">
          paid at the counter · stock updated
        </div>
      </Card>
      <FatPill onClick={onShare}>Share the bill</FatPill>
      <FatPill variant="secondary" onClick={onNewSale}>Next sale</FatPill>
    </div>
  );
}

export function CounterSale({ onToast }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [lines, setLines] = useState([]);
  const [taxIncluded, setTaxIncluded] = useState(true);
  const [invoice, setInvoice] = useState(null);
  const [billing, setBilling] = useState(false);
  const [billed, setBilled] = useState(null);
  const searchRef = useRef(null);
  const settledQuery = useDebounced(query);

  useEffect(() => {
    let cancelled = false;
    if (!settledQuery.trim()) { setResults([]); return undefined; }
    api.catalogSearch(settledQuery)
      .then((data) => { if (!cancelled) setResults(data.results ?? []); })
      .catch(() => { if (!cancelled) setResults([]); });
    return () => { cancelled = true; };
  }, [settledQuery]);

  // The payload the preview and the bill both take. Memoised on the lines
  // themselves so a re-render does not re-price a basket that has not changed.
  const payload = useMemo(() => ({
    lines: lines.map((l) => ({
      sku_id: l.sku_id, qty: Number(l.qty) || 0,
      unit_price: l.unit_price === "" ? null : Number(l.unit_price),
    })),
    price_includes_tax: taxIncluded,
    paid: true,
  }), [lines, taxIncluded]);

  const settledPayload = useDebounced(payload);

  useEffect(() => {
    let cancelled = false;
    if (!settledPayload.lines.length) { setInvoice(null); return undefined; }
    api.counterSalePreview(settledPayload)
      .then((data) => { if (!cancelled) setInvoice(data.invoice); })
      .catch(() => { /* the total simply does not update; nothing is lost */ });
    return () => { cancelled = true; };
  }, [settledPayload]);

  const addSku = useCallback((sku) => {
    setLines((current) => {
      const existing = current.findIndex((l) => l.sku_id === sku.sku_id);
      if (existing >= 0) {
        const next = [...current];
        next[existing] = { ...next[existing], qty: next[existing].qty + 1 };
        return next;
      }
      return [...current, {
        sku_id: sku.sku_id, name: sku.name, unit: sku.unit,
        gst_rate: sku.gst_rate, qty: 1,
        unit_price: sku.price_tiers?.retail ?? 0,
      }];
    });
    setQuery("");
    setResults([]);
    searchRef.current?.focus();
  }, []);

  const share = useCallback((result) => shareDocument({
    path: result.invoice_url,
    title: `Tax invoice ${result.invoice_no}`,
    text: `Tax invoice ${result.invoice_no} — ${inr(result.order?.total)}`,
  }), []);

  const bill = async () => {
    setBilling(true);
    try {
      const result = await api.counterSale(payload);
      setBilled(result);
      onToast?.(`Invoice ${result.invoice_no} — ${inr(result.order?.total)}`);
      share(result);
    } catch (error) {
      onToast?.(error.message ?? "Could not bill this sale");
    } finally {
      setBilling(false);
    }
  };

  const reset = () => {
    setBilled(null); setLines([]); setInvoice(null); setQuery("");
    searchRef.current?.focus();
  };

  return (
    <div>
      <BackBar title="New sale" sub="Walk-in customer" />
      <div className="px-gutter pb-10">
      {billed ? (
        <BilledPanel result={billed} onShare={() => share(billed)}
                     onNewSale={reset} />
      ) : (
        <div className="space-y-3.5">
          <div>
            <input
              ref={searchRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Type a product — ramco, 3/4 pipe, 53"
              className="w-full h-[48px] rounded-input bg-card px-4 text-body
                         outline-none placeholder:text-text-3"
              aria-label="Search the catalogue"
            />
            <SearchResults results={results} onPick={addSku} />
          </div>

          {lines.length === 0 ? (
            <EmptyState
              icon="₹"
              title="Ring up a walk-in"
              titleTa="நேரடி விற்பனை"
              body="Type the first few letters of a product. Enter the price the way you say it — 445 with tax — and the split is worked out backwards."
            />
          ) : (
            <>
              <GroupedList>
                {lines.map((line, index) => (
                  <LineRow
                    key={line.sku_id}
                    line={line}
                    onChange={(next) => setLines((c) =>
                      c.map((l, i) => (i === index ? next : l)))}
                    onRemove={() => setLines((c) =>
                      c.filter((_, i) => i !== index))}
                  />
                ))}
              </GroupedList>

              <div className="flex rounded-input bg-fill-2 p-[3px]">
                {[[true, "Price incl. tax"], [false, "Plus tax"]].map(
                  ([value, label]) => (
                    <button
                      key={label}
                      onClick={() => setTaxIncluded(value)}
                      className={`flex-1 h-[38px] rounded-[11px] text-body font-semibold
                        ${taxIncluded === value
                          ? "bg-card text-ink shadow-[0_1px_2px_rgba(0,0,0,.08)]"
                          : "text-text-2"}`}
                    >
                      {label}
                    </button>
                  ))}
              </div>

              <TotalsPanel invoice={invoice} taxIncluded={taxIncluded} />

              <FatPill onClick={bill} disabled={billing || !invoice?.payable}>
                {billing ? "Billing…"
                         : `Bill ${inr(invoice?.payable ?? 0)} and share`}
              </FatPill>
            </>
          )}
        </div>
      )}
      </div>
    </div>
  );
}
