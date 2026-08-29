import { useRef, useState } from "react";
import { api } from "../lib/api.js";
import { FatPill, Sheet } from "./ui.jsx";

/* Getting paper into the app.
 *
 * `capture="environment"` on a file input is what opens the rear camera
 * directly on a phone, with no camera permission dance and no custom viewfinder
 * to maintain — the phone's own camera app is better than anything we would
 * build, and the owner already knows how to use it.
 *
 * The upload and the agent run are separate: the photo lands in Cloud Storage
 * first, so a chain that fails can be retried against the same image rather than
 * asking a busy shopkeeper to photograph the bill again. */

const KINDS = {
  invoice: {
    label: "Supplier bill",
    sub: "Printed invoice → stock and payables",
    event: "purchase_inv",
    working: "Reading your bill…",
    workingTa: "உங்கள் பில்லைப் படிக்கிறேன்…",
  },
  khata: {
    label: "Khata page",
    sub: "Handwritten ledger → digital entries",
    event: "khata_page",
    working: "Reading the khata page…",
    workingTa: "கணக்குப் புத்தகத்தைப் படிக்கிறேன்…",
  },
};

export function CaptureButton({ onOpen }) {
  return (
    <button
      onClick={onOpen}
      aria-label="Photograph a bill or ledger page"
      className="fixed right-gutter bottom-[104px] z-30 w-[56px] h-[56px] rounded-full
                 bg-ink text-white text-[24px] leading-none flex items-center
                 justify-center active:opacity-80"
      style={{ right: "max(16px, env(safe-area-inset-right))" }}
    >
      ⌾
    </button>
  );
}

export function CaptureSheet({ open, onClose, onStarted, onError }) {
  const [kind, setKind] = useState(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef(null);

  const choose = (which) => {
    setKind(which);
    // Let the sheet paint before opening the camera, or iOS ignores the click.
    setTimeout(() => inputRef.current?.click(), 60);
  };

  const onFile = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";                    // allow re-picking the same file
    if (!file || !kind) return;
    setBusy(true);
    try {
      const { uri } = await api.upload(file, kind);
      const queued = await api.ingest({ type: KINDS[kind].event, media_path: uri });
      onStarted({ ...queued, kind, working: KINDS[kind].working,
                  workingTa: KINDS[kind].workingTa });
      onClose();
    } catch (err) {
      onError?.(err.message ?? "That did not upload — the photo is still on your phone");
    } finally {
      setBusy(false);
      setKind(null);
    }
  };

  return (
    <>
      <input
        ref={inputRef} type="file" accept="image/*" capture="environment"
        onChange={onFile} className="hidden"
      />
      <Sheet open={open} onClose={onClose} title="What are you photographing?">
        <div className="px-gutter pb-8">
          <div className="bg-card rounded-card overflow-hidden">
            {Object.entries(KINDS).map(([key, k]) => (
              <button
                key={key} disabled={busy} onClick={() => choose(key)}
                className="w-full px-[18px] py-[16px] text-left border-b border-separator
                           last:border-0 active:bg-separator disabled:opacity-50"
              >
                <div className="text-body font-semibold">
                  {busy && kind === key ? "Uploading…" : k.label}
                </div>
                <div className="text-meta text-text-3 mt-0.5">{k.sub}</div>
              </button>
            ))}
          </div>
          <p className="text-micro text-text-3 text-center mt-4 leading-relaxed">
            Lay the paper flat and fill the frame. The photo is kept so you can
            always check what was read against the original.
          </p>
          <div className="mt-4">
            <FatPill variant="tertiary" onClick={onClose}>Cancel</FatPill>
          </div>
        </div>
      </Sheet>
    </>
  );
}
