import { useState } from "react";
import { Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { DemoChip, DemoComposer } from "./components/DemoComposer.jsx";
import { TabBar } from "./components/TabBar.jsx";
import { OfflineBanner, Toast } from "./components/ui.jsx";
import { api } from "./lib/api.js";
import { useOnline, usePolling, useToast } from "./lib/hooks.js";
import { Approvals } from "./screens/Approvals.jsx";
import { ConfirmQueue } from "./screens/ConfirmQueue.jsx";
import { Counter } from "./screens/Counter.jsx";
import { GstDetail } from "./screens/GstDetail.jsx";
import { InvoiceReview } from "./screens/InvoiceReview.jsx";
import { KhataReview } from "./screens/KhataReview.jsx";
import { OrderDetail } from "./screens/OrderDetail.jsx";
import { Shop } from "./screens/Shop.jsx";

export default function App() {
  const [composerOpen, setComposerOpen] = useState(false);
  const [toast, showToast] = useToast();
  const [nudge, setNudge] = useState(0);          // bump to force screens to refetch
  const online = useOnline();
  const navigate = useNavigate();
  const location = useLocation();

  const { data: shop } = usePolling(api.shop, { interval: 0 });
  const { data: approvals } = usePolling(api.approvals, { interval: 4000 });
  const isTab = ["/", "/approvals", "/shop"].includes(location.pathname);

  const onSent = (result, label) => {
    showToast(`${label} — the agents are on it`);
    setNudge((n) => n + 1);
    if (result?.order_id) navigate(`/orders/${result.order_id}`);
    else if (result?.purchase_id) navigate(`/purchases/${result.purchase_id}`);
    else if (result?.import_id) navigate(`/khata/${result.import_id}`);
  };

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
          <DemoChip onOpen={() => setComposerOpen(true)} />
        </div>
        {!online && <div className="pb-2"><OfflineBanner /></div>}
      </header>

      <main className={isTab ? "pb-[96px]" : "pb-8"} key={nudge}>
        <Routes>
          <Route path="/" element={<Counter onToast={showToast} />} />
          <Route path="/approvals" element={<Approvals />} />
          <Route path="/shop" element={<Shop onToast={showToast} />} />
          <Route path="/orders/:orderId" element={<OrderDetail onToast={showToast} />} />
          <Route path="/purchases/:purchaseId"
                 element={<InvoiceReview onToast={showToast} />} />
          <Route path="/khata/:importId" element={<KhataReview onToast={showToast} />} />
          <Route path="/queue" element={<ConfirmQueue onToast={showToast} />} />
          <Route path="/gst/:period" element={<GstDetail />} />
        </Routes>
      </main>

      {isTab && <TabBar badge={approvals?.badge ?? 0} />}
      <DemoComposer
        open={composerOpen}
        onClose={() => setComposerOpen(false)}
        onSent={onSent}
        onReset={() => {
          showToast("Demo reset — back to the start");
          setNudge((n) => n + 1);
          navigate("/");
        }}
      />
      <Toast message={toast} />
    </div>
  );
}
