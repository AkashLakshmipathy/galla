import { useState } from "react";
import { useParams } from "react-router-dom";
import { BackBar } from "../components/BackBar.jsx";
import { DocPreview } from "../components/DocPreview.jsx";
import { TraceRelay } from "../components/TraceRelay.jsx";
import { Card, FatPill } from "../components/ui.jsx";
import { api } from "../lib/api.js";
import { shareDocument } from "../lib/share.js";
import { ddmmyyyy, inr, monthName, timeOfDay } from "../lib/format.js";
import { usePolling } from "../lib/hooks.js";

/* S7 — the month, compiled while the shop slept. The timeline is the point:
 * nobody opened the app for any of it. */

function Line({ label, value, strong }) {
  return (
    <div className="flex justify-between py-[9px] border-b border-separator last:border-0">
      <span className={`text-row ${strong ? "font-semibold" : "text-text-2"}`}>{label}</span>
      <span className={`text-row tnum ${strong ? "font-bold" : "font-semibold"}`}>{value}</span>
    </div>
  );
}

export function GstDetail() {
  const { period } = useParams();
  const [preview, setPreview] = useState(false);
  const { data: shop } = usePolling(api.shop, { interval: 0 });
  const { data: register } = usePolling(() => api.gstPeriod(period),
    { interval: 0, deps: [period] });
  const { data: trace } = usePolling(
    () => (register?.trace_id ? api.trace(register.trace_id) : Promise.resolve(null)),
    { interval: 0, active: Boolean(register?.trace_id), deps: [register?.trace_id] });

  if (!register) return <div className="px-gutter pt-6 text-body text-text-2">Loading…</div>;

  const outward = register.outward ?? {};
  const inward = register.inward ?? {};

  return (
    <div>
      <BackBar title={monthName(period)} sub="CA-ready summary" />
      <div className="px-gutter pb-10 space-y-3.5">
        <Card className="p-cardpad">
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-row">
              <span className="w-2 h-2 rounded-full bg-green" />
              <span className="text-text-2">
                Compiled {timeOfDay(register.generated_at)} on{" "}
                {ddmmyyyy(register.generated_at)}
              </span>
            </div>
            <div className="flex items-center gap-2 text-row">
              <span className={`w-2 h-2 rounded-full ${
                register.sent_to_ca_at ? "bg-green" : "bg-chevron"}`} />
              <span className="text-text-2">
                {register.sent_to_ca_at
                  ? `Sent to CA on ${register.ca_channel} ✓`
                  : "Not sent yet"}
              </span>
            </div>
          </div>
          {register.note && (
            <p className="text-row text-text-2 mt-3.5 pt-3.5 border-t border-separator">
              {register.note}
            </p>
          )}
        </Card>

        <Card className="p-cardpad">
          <div className="text-meta font-semibold text-text-3 uppercase tracking-wide mb-1">
            Outward supplies
          </div>
          <Line label="B2B taxable" value={inr(outward.b2b?.taxable)} />
          <Line label="B2C taxable" value={inr(outward.b2c?.taxable)} />
          <Line label="CGST + SGST" value={inr((outward.cgst ?? 0) + (outward.sgst ?? 0))} />
          <div className="mt-4 text-meta font-semibold text-text-3 uppercase tracking-wide mb-1">
            Inward supplies
          </div>
          <Line label="Taxable" value={inr(inward.taxable)} />
          <Line label="Input credit" value={inr((inward.cgst ?? 0) + (inward.sgst ?? 0))} />
          <div className="mt-2">
            <Line label="Net tax payable (est.)" value={inr(register.net_liability)} strong />
          </div>
        </Card>

        {trace && (
          <Card className="p-cardpad">
            <TraceRelay trace={trace} chain={["gst_compiler", "notifier"]} />
          </Card>
        )}

        {/* One document, one job: get it to the accountant. The screen used to
            lead with "Preview summary", which opened a sheet holding the two
            actions that actually do something — four taps' worth of choice for
            a man who wants to send one file. Sending leads now, looking at it
            first is the alternative, and the CSV stays for the accountant who
            asks for it rather than sitting at the same weight as the rest. */}
        <div className="space-y-1.5 pt-1">
          <FatPill onClick={() => shareDocument({
            path: register.summary_pdf_path,
            title: `GST summary ${period}`,
            text: `${shop?.name ?? "Shop"} — CA-ready GST summary for ${monthName(period)}`,
          })}>
            Send to the CA
          </FatPill>
          <FatPill variant="secondary" onClick={() => setPreview(true)}>
            Look at it first
          </FatPill>
          {register.registers_csv_path && (
            <button
              onClick={() => window.open(register.registers_csv_path,
                                         "_blank", "noopener")}
              className="w-full text-meta text-text-3 py-2"
            >
              Registers as CSV — for your accountant's software
            </button>
          )}
        </div>
        <p className="text-micro text-text-3 text-center">
          CA-ready summary · Galla does not file your GST.
        </p>
      </div>

      <DocPreview
        open={preview}
        onClose={() => setPreview(false)}
        variant="gst"
        pdfPath={register.summary_pdf_path}
        doc={{
          shopName: shop?.name,
          gstin: shop?.gstin,
          lines: [
            { label: "Outward — B2B", value: inr(outward.b2b?.taxable) },
            { label: "Outward — B2C", value: inr(outward.b2c?.taxable) },
            { label: "Output GST", value: inr((outward.cgst ?? 0) + (outward.sgst ?? 0)) },
            { label: "Input credit", value: inr((inward.cgst ?? 0) + (inward.sgst ?? 0)) },
          ],
          total: inr(register.net_liability),
          totalLabel: "Net tax payable (est.)",
          footer: "CA-ready · Galla does not file your GST",
        }}
      />
    </div>
  );
}
