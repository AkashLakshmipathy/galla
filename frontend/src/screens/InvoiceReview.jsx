import { useState } from "react";
import { useParams } from "react-router-dom";
import { BackBar } from "../components/BackBar.jsx";
import { LineEditor } from "../components/LineEditor.jsx";
import { Processing } from "../components/Processing.jsx";
import { TraceRelay } from "../components/TraceRelay.jsx";
import { Card, ConfidenceChip, FatPill, NewBadge } from "../components/ui.jsx";
import { api } from "../lib/api.js";
import { ddmmyyyy, inr } from "../lib/format.js";
import { usePolling } from "../lib/hooks.js";

/* S3 — invoice extraction review. The photo stays pinned at the top so the
 * owner can always check the paper; the table below is editable; the save bar
 * shows what will happen to stock before it happens. */

export function InvoiceReview({ onToast }) {
  const { purchaseId } = useParams();
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [fixed, setFixed] = useState([]);

  const { data: fleet } = usePolling(api.fleet, { interval: 0 });
  const { data: purchase, refresh } = usePolling(() => api.purchase(purchaseId),
    { interval: 1500, deps: [purchaseId] });
  const { data: trace } = usePolling(
    () => (purchase?.trace_id ? api.trace(purchase.trace_id) : Promise.resolve(null)),
    { interval: 1500, active: Boolean(purchase?.trace_id), deps: [purchase?.trace_id] });

  if (!purchase) return <Processing />;

  const applied = purchase.stock_applied;
  const lines = purchase.lines ?? [];

  /** The amber chip's first tap applies the agent's own best match — which is
   *  right far more often than not, and saves the owner a keypad. */
  const quickFix = async (index) => {
    const queue = await api.confirmQueue();
    const card = queue.items.find(
      (item) => item.source_id === purchaseId && Number(item.row_id) === index);
    if (!card) return;
    await api.resolveQueueItem(card.item_id, { accept_extracted: true });
    setFixed((rows) => [...rows, index]);
    await refresh();
  };

  const save = async () => {
    setBusy(true);
    try {
      const result = await api.confirmPurchase(purchaseId);
      const moved = (result.stock_delta ?? [])
        .map((d) => `${d.before} → ${d.after}`).join(", ");
      onToast?.(`Saved · stock updated ${moved}`);
      await refresh();
    } catch (error) {
      onToast?.(error.message ?? "Could not save");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <BackBar title="Supplier bill" sub={purchase.supplier_name_raw} />

      <div className="px-gutter pb-40">
        <div className="sticky top-[98px] z-10 -mx-gutter px-gutter pt-1 pb-3 bg-bg">
          <Card className="p-3 flex items-center gap-3">
            <div className="w-[34px] h-[44px] rounded-[6px] bg-khata-paper shrink-0
                            shadow-[inset_0_0_0_1px_rgba(0,0,0,.06)] overflow-hidden">
              {purchase.source_image_path && (
                <img src={purchase.source_image_path} alt="" className="w-full h-full object-cover" />
              )}
            </div>
            <div className="min-w-0">
              <div className="text-body font-semibold truncate">
                Invoice {purchase.invoice_no}
              </div>
              <div className="text-micro text-text-3 truncate tnum">
                {ddmmyyyy(purchase.invoice_date)} · GSTIN {purchase.supplier_gstin ?? "—"}
              </div>
            </div>
          </Card>
        </div>

        <Card className="p-cardpad mb-3.5">
          <TraceRelay trace={trace} chain={fleet?.chains?.purchase_inv ?? []} />
        </Card>

        <div className="flex items-center justify-between px-1 mb-2">
          <span className="text-meta font-semibold text-text-3 uppercase tracking-wide">
            {lines.length} lines
          </span>
          {!applied && (
            <button onClick={() => setEditing(true)}
                    className="text-meta font-semibold text-accent">
              Edit bill lines
            </button>
          )}
        </div>

        <div className="bg-card rounded-card overflow-hidden">
          {lines.map((line, index) => (
            <div key={index}
                 className="px-[18px] py-[13px] border-b border-separator last:border-0">
              <div className="flex items-start gap-3">
                <div className="flex-1 min-w-0">
                  <div className="text-body font-semibold">{line.name}</div>
                  <div className="text-meta text-text-2 tnum mt-0.5">
                    {Math.round(line.qty)} × {inr(line.rate)} · GST{" "}
                    {Math.round(line.gst_rate)}% = {inr(line.amount)}
                  </div>
                  {line.description_raw !== line.name && (
                    <div className="text-micro text-text-3 mt-1 truncate">
                      as printed: {line.description_raw}
                    </div>
                  )}
                  {line.is_new && (
                    <div className="text-micro text-accent mt-1">
                      Not in your catalogue — saving adds it and stocks{" "}
                      {Math.round(line.qty)}. You set the selling price later.
                    </div>
                  )}
                  {line.near_miss && (
                    <div className="text-micro text-amber-deep mt-1">
                      Might be {line.near_miss.name} — tap the chip to confirm,
                      or it will be added as a separate item.
                    </div>
                  )}
                </div>
                {line.is_new ? (
                  <NewBadge>New item</NewBadge>
                ) : (
                  <ConfidenceChip
                    value={line.confidence}
                    corrected={fixed.includes(index)}
                    onClick={() => quickFix(index)}
                  />
                )}
              </div>
            </div>
          ))}
        </div>

        {applied && purchase.stock_delta?.length > 0 && (
          <Card className="p-cardpad mt-3.5">
            <div className="text-meta font-semibold text-text-3 uppercase tracking-wide mb-2">
              Stock updated
            </div>
            {purchase.stock_delta.map((delta) => (
              <div key={delta.sku_id} className="flex justify-between text-body py-1">
                <span className="text-text-2 truncate pr-3">{delta.sku_id}</span>
                <span className="tnum font-semibold shrink-0">
                  {delta.before} → {delta.after}
                </span>
              </div>
            ))}
          </Card>
        )}
      </div>

      <div className="fixed bottom-0 left-0 right-0 z-30 bg-bg/95 backdrop-blur">
        <div className="mx-auto max-w-[430px] px-5 pt-3 pb-[22px] safe-bottom">
          <div className="flex justify-between text-meta text-text-2 mb-2.5 tnum">
            <span>
              Taxable {inr(purchase.totals?.subtotal)} · GST{" "}
              {inr((purchase.totals?.cgst ?? 0) + (purchase.totals?.sgst ?? 0))}
            </span>
            <span className="font-semibold text-ink">{inr(purchase.totals?.total)}</span>
          </div>
          {!applied && purchase.new_sku_count > 0 && (
            <p className="text-micro text-accent text-center mb-2">
              {purchase.new_sku_count} new{" "}
              {purchase.new_sku_count === 1 ? "item" : "items"} will be added to
              your catalogue
            </p>
          )}
          <FatPill onClick={save} disabled={busy || applied}>
            {applied ? "Saved to stock ✓" : busy ? "Saving…" : "Save to stock & payables"}
          </FatPill>
        </div>
      </div>

      <LineEditor
        open={editing}
        onClose={() => setEditing(false)}
        allowRemove={false}
        lines={lines.map((line) => ({ ...line, name: line.name }))}
        onSave={async (edits) => {
          if (edits.length) await api.editPurchaseLines(purchaseId, edits);
          onToast?.("Bill updated");
          await refresh();
        }}
      />
    </div>
  );
}
