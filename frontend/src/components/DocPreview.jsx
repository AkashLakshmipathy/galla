import { FatPill, Sheet } from "./ui.jsx";
import { inr } from "../lib/format.js";

/* Doc preview sheet. A page mock the owner recognises as "the bill", with the
 * real PDF one tap away. Two variants: a quotation, and the monthly GST
 * summary — whose footer must say CA-ready, never "filed". */

export function DocPreview({ open, onClose, variant = "quotation", doc, pdfPath }) {
  const isQuote = variant === "quotation";
  return (
    <Sheet open={open} onClose={onClose}
           title={isQuote ? "Quotation" : "GST summary"}>
      <div className="px-gutter pb-8">
        <div className="bg-card rounded-input p-5
                        shadow-[inset_0_0_0_1px_rgba(0,0,0,.04)]">
          <div className="flex items-baseline justify-between gap-2">
            <div className="text-row font-bold truncate">{doc?.shopName}</div>
            <div className="text-micro text-text-3 tnum shrink-0">{doc?.gstin}</div>
          </div>
          <div className="h-px bg-separator my-3" />
          {(doc?.lines ?? []).map((line, index) => (
            <div key={index} className="flex justify-between text-meta py-[3px]">
              <span className={index === 0 ? "text-ink" : "text-text-2"}>{line.label}</span>
              <span className="tnum text-text-2">{line.value}</span>
            </div>
          ))}
          <div className="h-px bg-separator my-3" />
          <div className="flex justify-between text-row font-bold">
            <span>{doc?.totalLabel ?? "Total incl. GST"}</span>
            <span className="tnum">{doc?.total}</span>
          </div>
          <p className="text-micro text-text-3 text-center mt-4">{doc?.footer}</p>
        </div>

        <div className="mt-4 space-y-1.5">
          <FatPill
            onClick={() => pdfPath && window.open(pdfPath, "_blank", "noopener")}
            disabled={!pdfPath}
          >
            Share on WhatsApp
          </FatPill>
          <FatPill
            variant="secondary"
            onClick={() => pdfPath && window.open(pdfPath, "_blank", "noopener")}
            disabled={!pdfPath}
          >
            Download PDF
          </FatPill>
        </div>
      </div>
    </Sheet>
  );
}

export function quotationDoc(order, shop) {
  return {
    shopName: shop?.name,
    gstin: shop?.gstin,
    lines: (order?.lines ?? []).map((line) => ({
      label: `${line.name} × ${Math.round(line.qty)}`,
      value: inr(line.amount),
    })).concat([
      { label: "CGST + SGST", value: inr((order?.gst?.cgst ?? 0) + (order?.gst?.sgst ?? 0)) },
    ]),
    total: inr(order?.total),
    footer: `#Q-${String(order?.order_id ?? "").split("_").pop()} · Valid 7 days`,
  };
}
