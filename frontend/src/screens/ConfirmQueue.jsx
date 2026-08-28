import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { BackBar } from "../components/BackBar.jsx";
import { Card, FatPill } from "../components/ui.jsx";
import { api } from "../lib/api.js";
import { usePolling } from "../lib/hooks.js";

const FIELD_LABEL = {
  sku_id: "Item the agent read",
  party_id: "Party the agent read",
  amount: "Amount the agent read",
  qty: "Quantity the agent read",
  rate: "Rate the agent read",
};

/* S5 — one card at a time. Source crop on top, the value the agent read below,
 * the alternatives it also considered. Clearing the last card should feel like
 * finishing something, so it gets a completion state rather than an empty list. */

function SourceCrop({ path, bbox }) {
  if (!path) {
    return (
      <div className="h-[120px] rounded-panel bg-khata-paper
                      shadow-[inset_0_0_0_1px_rgba(0,0,0,.05)] flex items-center
                      justify-center text-meta text-text-3">
        Source region
      </div>
    );
  }
  // Zoom the photo onto the row's rectangle so the owner sees the actual ink.
  const zoom = bbox?.h ? Math.min(6, 0.9 / bbox.h) : 1;
  return (
    <div className="h-[120px] rounded-panel overflow-hidden relative bg-khata-paper">
      <img
        src={path}
        alt="Source region of the original document"
        className="absolute origin-top-left max-w-none"
        style={bbox ? {
          width: `${100 * zoom}%`,
          left: `${-bbox.x * 100 * zoom}%`,
          top: `${-bbox.y * 100 * zoom + 10}%`,
        } : { width: "100%" }}
      />
    </div>
  );
}

export function ConfirmQueue({ onToast }) {
  const navigate = useNavigate();
  const [index, setIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [startCount, setStartCount] = useState(null);
  const { data, refresh } = usePolling(api.confirmQueue, { interval: 4000 });

  const items = data?.items ?? [];
  useEffect(() => {
    if (startCount === null && data) setStartCount(items.length);
  }, [data, items.length, startCount]);

  const item = items[index] ?? items[0];
  const done = items.length === 0;
  const cleared = (startCount ?? 0) - items.length;

  const resolve = async (value, acceptExtracted) => {
    if (!item) return;
    setBusy(true);
    try {
      await api.resolveQueueItem(item.item_id,
        acceptExtracted ? { accept_extracted: true } : { value });
      setIndex(0);
      await refresh();
    } catch (error) {
      onToast?.(error.message ?? "Could not save that");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <BackBar title="Confirm queue"
               sub={done ? "All clear" : `${index + 1} of ${items.length}`} />
      <div className="px-gutter pt-2 pb-10">
        {startCount > 0 && (
          <div className="h-[6px] rounded-full bg-fill-3 overflow-hidden mb-4">
            <div className="h-full bg-ink rounded-full transition-[width] duration-300"
                 style={{ width: `${(cleared / Math.max(startCount, 1)) * 100}%` }} />
          </div>
        )}

        {done && (
          <Card className="p-11 text-center animate-rise">
            <div className="w-[52px] h-[52px] rounded-full bg-green-tint mx-auto mb-4
                            flex items-center justify-center text-green text-[22px]">
              ✓
            </div>
            <div className="text-tile font-bold">Queue cleared</div>
            <p className="text-row text-text-2 mt-2">
              {cleared > 0
                ? `${cleared} ${cleared === 1 ? "entry" : "entries"} confirmed and written to the books.`
                : "Nothing needs confirming right now."}
            </p>
            <div className="mt-5">
              <FatPill onClick={() => navigate(-1)}>Back to approvals</FatPill>
            </div>
          </Card>
        )}

        {!done && item && (
          <div className="animate-rise space-y-3.5">
            <Card className="p-cardpad">
              <div className="text-meta text-text-3 mb-3">
                {item.source_type === "khata"
                  ? `From khata ${item.source_id} · row ${item.row_id}`
                  : `From supplier bill ${item.source_id} · line ${Number(item.row_id) + 1}`}
              </div>
              <SourceCrop path={item.source_image_path} bbox={item.crop_bbox} />
              <div className="text-meta text-text-2 mt-4">
                {FIELD_LABEL[item.field] ?? "What the agent read"}
              </div>
              <div className={`font-bold tnum mt-1 ${
                String(item.extracted_value ?? "").length > 16
                  ? "text-tile" : "text-extracted"}`}>
                {item.extracted_value}
              </div>
              <div className="text-meta text-amber-deep font-semibold mt-2 tnum">
                {Math.round((item.confidence ?? 0) * 100)}% sure
              </div>
            </Card>

            {(item.alternatives ?? []).length > 1 && (
              <div className="bg-card rounded-card overflow-hidden">
                {item.alternatives.map((alternative, i) => (
                  <button
                    key={`${alternative}-${i}`}
                    disabled={busy}
                    onClick={() => resolve(alternative, i === 0)}
                    className="w-full px-[18px] py-[14px] text-left text-body font-semibold
                               tnum border-b border-separator last:border-0 active:bg-separator"
                  >
                    {alternative}
                    {i === 0 && (
                      <span className="text-meta text-text-3 font-normal ml-2">
                        what the agent read
                      </span>
                    )}
                  </button>
                ))}
              </div>
            )}

            <div className="space-y-1.5 pt-1">
              <FatPill disabled={busy} onClick={() => resolve(null, true)}>
                {busy ? "Saving…" : "Confirm as read"}
              </FatPill>
              {items.length > 1 && (
                <FatPill variant="tertiary"
                         onClick={() => setIndex((i) => (i + 1) % items.length)}>
                  Skip for now
                </FatPill>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
