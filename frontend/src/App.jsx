import { useCallback, useEffect, useState } from "react";
import { Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { CaptureButton, CaptureSheet } from "./components/Capture.jsx";
import { DemoChip, DemoComposer } from "./components/DemoComposer.jsx";
import { TabBar } from "./components/TabBar.jsx";
import { OfflineBanner, Toast } from "./components/ui.jsx";
import { api, session } from "./lib/api.js";
import { useOnline, usePolling, useToast } from "./lib/hooks.js";
import { Approvals } from "./screens/Approvals.jsx";
import { ConfirmQueue } from "./screens/ConfirmQueue.jsx";
import { Counter } from "./screens/Counter.jsx";
import { Credit, PartyLedger } from "./screens/Credit.jsx";
import { Purchases, SupplierLedger } from "./screens/Purchases.jsx";
import { LockScreen, Onboarding } from "./screens/Onboarding.jsx";
import { GstDetail } from "./screens/GstDetail.jsx";
import { InvoiceReview } from "./screens/InvoiceReview.jsx";
import { KhataReview } from "./screens/KhataReview.jsx";
import { OrderDetail } from "./screens/OrderDetail.jsx";
import { Shop } from "./screens/Shop.jsx";

export default function App() {
  const [gate, setGate] = useState(null);      // null while we find out
  const [composerOpen, setComposerOpen] = useState(false);
  const [captureOpen, setCaptureOpen] = useState(false);
  const [toast, showToast] = useToast();
  const [nudge, setNudge] = useState(0);          // bump to force screens to refetch
  const online = useOnline();
  const navigate = useNavigate();
  const location = useLocation();

  const refreshGate = useCallback(async () => {
    try {
      const state = await api.setupState();
      setGate({ ...state, signedIn: Boolean(session.get()) });
    } catch {
      // Offline on a cold start: assume a configured shop and let the lock
      // screen ask. Better than blocking behind a network call the shop
      // counter may not have.
      setGate({ configured: true, locked: true, signedIn: Boolean(session.get()) });
    }
  }, []);

  useEffect(() => {
    refreshGate();
    const signedOut = () => setGate((g) => (g ? { ...g, signedIn: false } : g));
    window.addEventListener("galla:signed-out", signedOut);
    return () => window.removeEventListener("galla:signed-out", signedOut);
  }, [refreshGate]);

  const unlocked = Boolean(gate?.configured && (gate.signedIn || !gate.locked));
  const { data: shop } = usePolling(api.shop, { interval: 0, active: unlocked,
                                                deps: [unlocked] });
  const { data: approvals } = usePolling(api.approvals,
    { interval: 4000, active: unlocked, deps: [unlocked] });
  const { data: demo } = usePolling(api.demoScenarios,
    { interval: 0, active: unlocked, deps: [unlocked] });
  const demoMode = Boolean(demo?.demo_mode);
  const isTab = ["/", "/approvals", "/credit", "/purchases-book", "/shop"]
    .includes(location.pathname);

  const onSent = (result, label) => {
    showToast(`${label} — the agents are on it`);
    setNudge((n) => n + 1);
    if (result?.order_id) navigate(`/orders/${result.order_id}`);
    else if (result?.purchase_id) navigate(`/purchases/${result.purchase_id}`);
    else if (result?.import_id) navigate(`/khata/${result.import_id}`);
  };

  if (gate === null) {
    return <div className="min-h-screen bg-bg" aria-busy="true" />;
  }

  if (!gate.configured) {
    return (
      <div className="min-h-full mx-auto max-w-[430px] bg-bg">
        <Onboarding states={gate.states ?? {}}
                    onDone={() => { refreshGate(); navigate("/"); }} />
      </div>
    );
  }

  if (!unlocked) {
    return (
      <div className="min-h-full mx-auto max-w-[430px] bg-bg">
        <LockScreen shopName={gate.shop_name} shopNameTa={gate.shop_name_ta}
                    onUnlocked={() => setGate((g) => ({ ...g, signedIn: true }))} />
      </div>
    );
  }

  return (
    <div className="min-h-full mx-auto max-w-[430px] bg-bg">
      <header className="sticky top-0 z-30 bg-bg/95 backdrop-blur safe-top">
        <div className="flex items-center justify-between px-gutter h-[52px]">
          <div className="min-w-0">
            <div className="text-action font-semibold truncate">
              {shop?.name ?? "Galla"}
            </div>
            {shop?.name_ta && (
              <div className="text-micro text-text-3 truncate -mt-0.5">{shop.name_ta}</div>
            )}
          </div>
          {demoMode && <DemoChip onOpen={() => setComposerOpen(true)} />}
        </div>
        {!online && <div className="pb-2"><OfflineBanner /></div>}
      </header>

      <main className={isTab ? "pb-[96px]" : "pb-8"} key={nudge}>
        <Routes>
          <Route path="/" element={<Counter onToast={showToast} />} />
          <Route path="/approvals" element={<Approvals onToast={showToast} />} />
          <Route path="/credit" element={<Credit />} />
          <Route path="/credit/:partyId" element={<PartyLedger />} />
          <Route path="/purchases-book" element={<Purchases />} />
          <Route path="/purchases-book/:partyId" element={<SupplierLedger />} />
          <Route path="/shop" element={<Shop onToast={showToast} />} />
          <Route path="/orders/:orderId" element={<OrderDetail onToast={showToast} />} />
          <Route path="/purchases/:purchaseId"
                 element={<InvoiceReview onToast={showToast} />} />
          <Route path="/khata/:importId" element={<KhataReview onToast={showToast} />} />
          <Route path="/queue" element={<ConfirmQueue onToast={showToast} />} />
          <Route path="/gst/:period" element={<GstDetail />} />
        </Routes>
      </main>

      {isTab && <CaptureButton onOpen={() => setCaptureOpen(true)} />}
      {isTab && <TabBar badge={approvals?.badge ?? 0} />}
      <CaptureSheet
        open={captureOpen}
        onClose={() => setCaptureOpen(false)}
        onError={showToast}
        onStarted={(result) => {
          const n = result.count ?? 1;
          showToast(`${n} sent for reading — keep going`);
          setNudge((x) => x + 1);
          if (location.pathname !== "/") navigate("/");
        }}
      />
      {demoMode && <DemoComposer
        open={composerOpen}
        onClose={() => setComposerOpen(false)}
        onSent={onSent}
        onReset={() => {
          showToast("Demo reset — back to the start");
          setNudge((n) => n + 1);
          navigate("/");
        }}
      />}
      <Toast message={toast} />
    </div>
  );
}
