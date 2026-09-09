import { useState } from "react";
import { useParams } from "react-router-dom";
import { BackBar } from "../components/BackBar.jsx";
import { DocPreview, quotationDoc } from "../components/DocPreview.jsx";
import { LineEditor } from "../components/LineEditor.jsx";
import { Processing } from "../components/Processing.jsx";
import { TraceRelay } from "../components/TraceRelay.jsx";
import { VerdictBlock } from "../components/Verdict.jsx";
import { Card, ConfidenceChip, FatPill } from "../components/ui.jsx";
import { api } from "../lib/api.js";
import { shareDocument } from "../lib/share.js";
import { inr } from "../lib/format.js";
import { usePolling } from "../lib/hooks.js";

/* S2 — the approval. The verdict dominates; the line items sit underneath; the
 * three fat buttons fill the bottom. Designed as a decision, not a notification. */

function actionsFor(decision, verdict) {
  if (decision === "approve") {
    return [{ key: "approve", label: "Approve order", variant: "primary" },
            { key: "modify", label: "Modify order", variant: "secondary" },
            { key: "reject", label: "Decline order", variant: "tertiary" }];
  }
  if (decision === "part_payment") {
    return [{ key: "part_payment",
              label: `Ask ${inr(verdict.suggested_advance)} advance`, variant: "primary" },
            { key: "approve", label: "Approve full credit anyway", variant: "secondary" },
            { key: "reject", label: "Decline order", variant: "tertiary" }];
  }
  return [{ key: "part_payment",
            label: `Ask ${inr(verdict.suggested_advance)} advance first`, variant: "primary" },
          { key: "approve", label: "Approve anyway (over limit)", variant: "secondary" },
          { key: "reject", label: "Decline order", variant: "danger" }];
}

function Substitution({ suggestion, onSwitch, onKeep, busy }) {
  return (
    <Card className="p-cardpad animate-rise">
      <div className="flex gap-2 items-start">
        <span className="w-2 h-2 rounded-full bg-amber mt-[6px] shrink-0" />
        <p className="text-row flex-1">
          <span className="font-semibold">Short on stock. </span>
          <span className="text-text-2">{suggestion.message}</span>
        </p>
      </div>
      {suggestion.substitute_sku_id && (
        <div className="flex gap-2 mt-3.5">
          <button onClick={onSwitch} disabled={busy}
                  className="flex-1 h-11 rounded-full bg-ink text-white text-action
                             font-semibold disabled:bg-chevron">
            {busy ? "Switching…" : `Switch ${Math.round(suggestion.qty_wanted - suggestion.qty_available)} to ${suggestion.substitute_name?.split(" ")[0]}`}
          </button>
          <button onClick={onKeep}
                  className="flex-1 h-11 rounded-full bg-fill-2 text-ink text-action
                             font-semibold">
            Keep
          </button>
        </div>
      )}
    </Card>
  );
}

export function OrderDetail({ onToast }) {
  const { orderId } = useParams();
  const [busy, setBusy] = useState(null);
  const [editing, setEditing] = useState(false);
  const [preview, setPreview] = useState(false);
  const [keptSubs, setKeptSubs] = useState([]);

  const { data: shop } = usePolling(api.shop, { interval: 0 });
  const { data: fleet } = usePolling(api.fleet, { interval: 0 });
  const { data: order, refresh } = usePolling(() => api.order(orderId),
    { interval: 1200, deps: [orderId] });
  const { data: trace } = usePolling(
    () => (order?.trace_id ? api.trace(order.trace_id) : Promise.resolve(null)),
    { interval: 1200, active: Boolean(order?.trace_id), deps: [order?.trace_id] });

  if (!order) return <Processing title="Reading the order…" titleTa="ஆர்டரைப் படிக்கிறேன்…" />;

  const verdict = order.credit_verdict;
  const decided = ["approved", "rejected", "fulfilled"].includes(order.status);
  const suggestions = (order.stock_suggestions ?? [])
    .filter((s) => !keptSubs.includes(s.line_index));

  const decide = async (action) => {
    setBusy(action);
    try {
      const result = await api.decide(orderId, { action });
      const said = {
        approve: "Order approved · quotation sent ✓",
        part_payment: `Advance of ${inr(verdict?.suggested_advance)} requested · quotation held ✓`,
        reject: "Order declined · the customer was told politely ✓",
      }[action];
      onToast?.(said);
      if (action === "approve") setPreview(true);
      await refresh();
      return result;
    } catch (error) {
      onToast?.(error.message ?? "That did not go through");
      return null;
    } finally {
      setBusy(null);
    }
  };

  const switchTo = async (index) => {
    setBusy(`sub-${index}`);
    try {
      await api.substitute(orderId, { line_index: index, accept: true });
      onToast?.("Switched ✓ — draft updated");
      await refresh();
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <BackBar title={`Order ${orderId.replace("ord_", "#")}`}
               sub={order.party_name} />

      <div className="px-gutter space-y-3.5 pb-40">
        {verdict && (
          <Card className="pt-4">
            <VerdictBlock verdict={verdict} party={order.party} total={order.total} />
          </Card>
        )}

        {suggestions.map((suggestion) => (
          <Substitution
            key={suggestion.line_index}
            suggestion={suggestion}
            busy={busy === `sub-${suggestion.line_index}`}
            onSwitch={() => switchTo(suggestion.line_index)}
            onKeep={() => setKeptSubs((k) => [...k, suggestion.line_index])}
          />
        ))}

        <div>
          <div className="flex items-center justify-between px-1 mb-2">
            <span className="text-meta font-semibold text-text-3 uppercase tracking-wide">
              {order.lines?.length} {order.lines?.length === 1 ? "item" : "items"}
            </span>
            {!decided && (
              <button onClick={() => setEditing(true)}
                      className="text-meta font-semibold text-accent">
                Edit
              </button>
            )}
          </div>
          <div className="bg-card rounded-card overflow-hidden">
            {order.lines?.map((line, index) => (
              <div key={index}
                   className="px-[18px] py-[13px] border-b border-separator last:border-0">
                <div className="flex items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="text-body font-semibold">{line.name}</div>
                    <div className="text-meta text-text-2 tnum mt-0.5">
                      {Math.round(line.qty)} {line.unit} × {inr(line.rate)} · GST{" "}
                      {Math.round(line.gst_rate)}%
                      {line.substitute_of ? " · substitute" : ""}
                      {!line.in_stock ? " · short" : ""}
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className="text-body font-semibold tnum">
                      {inr(line.line_total ?? line.amount)}
                    </div>
                    <div className="mt-1"><ConfidenceChip value={line.confidence} /></div>
                  </div>
                </div>
              </div>
            ))}
            <div className="px-[18px] py-[13px] flex justify-between text-meta text-text-2">
              <span>Taxable + CGST/SGST</span>
              <span className="tnum">
                {inr(order.subtotal)} + {inr(order.gst?.total)}
              </span>
            </div>
          </div>
        </div>

        {/* Once the owner has approved, the goods are sold and the shop owes
            the customer a tax invoice, not a quotation. Both stay on the
            screen: the quote is what was offered, the invoice is what was
            issued, and a shop is asked for either one later. */}
        {order.invoice_path && (
          <Card>
            <div className="p-cardpad flex items-center gap-3">
              <div className="w-[34px] h-[44px] rounded-[6px] bg-bg shrink-0" />
              <div className="flex-1 min-w-0 text-left">
                <div className="text-body font-semibold truncate">
                  Tax invoice {order.invoice_no}
                </div>
                <div className="text-meta text-text-3">
                  {inr(order.total)} · GST invoice
                </div>
              </div>
              <button
                onClick={() => shareDocument({
                  path: order.invoice_path,
                  title: `Tax invoice ${order.invoice_no}`,
                  text: `Tax invoice ${order.invoice_no} — ${inr(order.total)}`,
                })}
                className="text-accent text-meta font-semibold shrink-0"
              >
                Share
              </button>
            </div>
          </Card>
        )}

        {order.quotation_path && (
          <Card>
            <button onClick={() => setPreview(true)}
                    className="w-full p-cardpad flex items-center gap-3">
              <div className="w-[34px] h-[44px] rounded-[6px] bg-bg shrink-0" />
              <div className="flex-1 text-left">
                <div className="text-body font-semibold">
                  Quotation #Q-{orderId.split("_").pop()}
                </div>
                <div className="text-meta text-text-3">GST format · valid 7 days</div>
              </div>
              <span className="text-accent text-meta font-semibold">Preview</span>
            </button>
          </Card>
        )}

        {/* One strip per order. There used to be two — one here and one above
            the lines — and because they picked their chain differently the same
            order showed six dots in one and one dot in the other. */}
        <Card className="p-cardpad">
          <TraceRelay
            trace={trace}
            chain={fleet?.chains?.[
              order.source === "counter" ? "counter_sale" : "sale_order"] ?? []}
          />
        </Card>
      </div>

      {verdict && !decided && (
        <div className="fixed bottom-0 left-0 right-0 z-30 bg-bg/95 backdrop-blur">
          <div className="mx-auto max-w-[430px] px-5 pt-3 pb-[22px] space-y-1.5 safe-bottom">
            {actionsFor(verdict.decision, verdict).map((action) => (
              <FatPill key={action.key} variant={action.variant} disabled={Boolean(busy)}
                       onClick={() => (action.key === "modify"
                         ? setEditing(true) : decide(action.key))}>
                {busy === action.key ? "Working…" : action.label}
              </FatPill>
            ))}
          </div>
        </div>
      )}

      <LineEditor
        open={editing}
        onClose={() => setEditing(false)}
        lines={order.lines ?? []}
        onSave={async (edits) => {
          if (edits.length) await api.editLines(orderId, edits);
          onToast?.("Order updated · quotation will follow");
          await refresh();
        }}
      />
      <DocPreview
        open={preview}
        onClose={() => setPreview(false)}
        doc={quotationDoc(order, shop)}
        pdfPath={order.quotation_path}
      />
    </div>
  );
}
