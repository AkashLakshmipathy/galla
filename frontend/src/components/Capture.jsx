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
      className="fixed bottom-[104px] z-30 w-[60px] h-[60px] rounded-full bg-ink
                 text-white flex items-center justify-center active:opacity-80
                 shadow-[0_6px_20px_rgba(17,17,19,.28)]"
      style={{ right: "max(16px, env(safe-area-inset-right))" }}
    >
      <svg width="26" height="26" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M4 8.5A2.5 2.5 0 0 1 6.5 6h1.3a1 1 0 0 0 .83-.45l.74-1.1A1 1 0 0 1 10.2 4h3.6a1 1 0 0 1 .83.45l.74 1.1a1 1 0 0 0 .83.45h1.3A2.5 2.5 0 0 1 20 8.5v8A2.5 2.5 0 0 1 17.5 19h-11A2.5 2.5 0 0 1 4 16.5v-8Z"
              stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
        <circle cx="12" cy="12.5" r="3.4" stroke="currentColor" strokeWidth="1.8" />
      </svg>
    </button>
  );
}

export function CaptureSheet({ open, onClose, onStarted, onError }) {
  const [kind, setKind] = useState(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(0);
  const cameraRef = useRef(null);
  const galleryRef = useRef(null);

  const choose = (which, ref) => {
    setKind(which);
    // Let the sheet paint before opening the camera, or iOS ignores the click.
    setTimeout(() => ref.current?.click(), 60);
  };

  const send = async (files, which) => {
    if (!files?.length) return;
    setBusy(true);
    try {
      const result = await api.scan(files, which);
      setDone((n) => n + result.count);
      onStarted?.(result);
    } catch (err) {
      onError?.(err.message
        ?? "That did not upload — the photo is still on your phone");
    } finally {
      setBusy(false);
    }
  };

  const onFile = async (event) => {
    const files = [...(event.target.files ?? [])];
    const which = kind;
    event.target.value = "";                    // allow re-picking the same file
    await send(files, which);
    // Deliberately does NOT close: a shop digitising twenty years of paper
    // photographs sheet after sheet. Reopening the camera each time is the
    // difference between a tool that gets used and one that gets abandoned.
    if (files.length === 1) setTimeout(() => cameraRef.current?.click(), 250);
  };

  const finish = () => {
    setDone(0);
    setKind(null);
    onClose();
  };

  return (
    <>
      <input ref={cameraRef} type="file" accept="image/*" capture="environment"
             onChange={onFile} className="hidden" />
      <input ref={galleryRef} type="file" accept="image/*" multiple
             onChange={onFile} className="hidden" />
      <Sheet open={open} onClose={finish}
             title={done ? `${done} sent for reading` : "What are you photographing?"}>
        <div className="px-gutter pb-8">
          {done > 0 && (
            <p className="text-row text-text-2 text-center -mt-1 mb-4">
              Keep going — nothing here waits for the last one. Results appear on
              the counter as each is read.
            </p>
          )}
          <div className="bg-card rounded-card overflow-hidden">
            {Object.entries(KINDS).map(([key, k]) => (
              <button
                key={key} disabled={busy} onClick={() => choose(key, cameraRef)}
                className="w-full px-[18px] py-[16px] text-left border-b border-separator
                           last:border-0 active:bg-separator disabled:opacity-50"
              >
                <div className="text-body font-semibold">
                  {busy && kind === key ? "Sending…" : k.label}
                </div>
                <div className="text-meta text-text-3 mt-0.5">{k.sub}</div>
              </button>
            ))}
          </div>

          <div className="bg-card rounded-card overflow-hidden mt-3.5">
            {Object.entries(KINDS).map(([key, k]) => (
              <button
                key={key} disabled={busy} onClick={() => choose(key, galleryRef)}
                className="w-full px-[18px] py-[14px] text-left border-b border-separator
                           last:border-0 active:bg-separator disabled:opacity-50"
              >
                <div className="text-body font-semibold">
                  Many {k.label.toLowerCase()}s at once
                </div>
                <div className="text-meta text-text-3 mt-0.5">
                  Pick a whole stack you have already photographed
                </div>
              </button>
            ))}
          </div>

          <p className="text-micro text-text-3 text-center mt-4 leading-relaxed">
            Lay the paper flat and fill the frame. Every photo is kept, so you can
            always check what was read against the original.
          </p>
          <div className="mt-4">
            <FatPill variant={done ? "primary" : "tertiary"} onClick={finish}>
              {done ? "Done for now" : "Cancel"}
            </FatPill>
          </div>
        </div>
      </Sheet>
    </>
  );
}
